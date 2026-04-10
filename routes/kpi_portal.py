import json
from datetime import date as date_cls

from flask import Blueprint, flash, redirect, render_template, request, session

from database import get_db
from routes.hris import (
    _current_timestamp,
    _decorate_kpi_metric_entries,
    _decorate_kpi_staff_report_row,
    _get_self_service_employee,
    _resolve_effective_kpi_profile,
)
from services.kpi_catalog import (
    KPI_REPORT_STATUS_LABELS,
    KPI_WEEK_OPTIONS,
    build_kpi_metric_entries,
    format_kpi_period_label,
    get_current_kpi_week_key,
    normalize_kpi_period_label,
    normalize_kpi_week_key,
    summarize_kpi_metric_entries,
)
from services.rbac import has_permission


kpi_portal_bp = Blueprint("kpi_portal", __name__, url_prefix="/kpi-staff")


def _has_kpi_portal_access():
    return has_permission(session.get("role"), "access_kpi_portal")


def _fetch_recent_kpi_reports(db, linked_employee, limit=8):
    if not linked_employee:
        return []

    rows = db.execute(
        """
        SELECT
            r.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS submitter_username,
            ru.username AS reviewed_by_name
        FROM kpi_staff_reports r
        JOIN employees e ON r.employee_id = e.id
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN users ru ON r.reviewed_by = ru.id
        WHERE r.employee_id=?
        ORDER BY r.period_label DESC, r.week_key DESC, r.id DESC
        LIMIT ?
        """,
        (linked_employee["id"], limit),
    ).fetchall()
    return [_decorate_kpi_staff_report_row(row) for row in rows]


def _build_kpi_portal_context(db):
    linked_employee = _get_self_service_employee(db)
    if linked_employee:
        linked_employee = dict(linked_employee)

    kpi_profile = None
    recent_kpi_reports = []
    kpi_report_summary = {
        "total": 0,
        "submitted": 0,
        "reviewed": 0,
        "follow_up": 0,
        "avg_score": 0,
    }

    if linked_employee:
        kpi_profile = _resolve_effective_kpi_profile(
            db,
            linked_employee,
            period_label=normalize_kpi_period_label(date_cls.today().isoformat()),
        )
        if kpi_profile:
            kpi_profile["metrics"] = _decorate_kpi_metric_entries(kpi_profile.get("metrics", []))
        recent_kpi_reports = _fetch_recent_kpi_reports(db, linked_employee)
        if recent_kpi_reports:
            report_count = len(recent_kpi_reports)
            total_score = sum(float(item.get("weighted_score") or 0) for item in recent_kpi_reports)
            kpi_report_summary = {
                "total": report_count,
                "submitted": sum(1 for item in recent_kpi_reports if item.get("status") == "submitted"),
                "reviewed": sum(1 for item in recent_kpi_reports if item.get("status") == "reviewed"),
                "follow_up": sum(1 for item in recent_kpi_reports if item.get("status") == "follow_up"),
                "avg_score": round(total_score / report_count, 2) if report_count else 0,
            }

    return {
        "linked_employee": linked_employee,
        "kpi_profile": kpi_profile,
        "current_kpi_week_key": get_current_kpi_week_key(),
        "current_kpi_period_label": normalize_kpi_period_label(date_cls.today().isoformat()),
        "current_kpi_period_label_human": format_kpi_period_label(date_cls.today().isoformat()),
        "kpi_week_options": KPI_WEEK_OPTIONS,
        "recent_kpi_reports": recent_kpi_reports,
        "kpi_report_summary": kpi_report_summary,
        "kpi_status_labels": KPI_REPORT_STATUS_LABELS,
    }


def _submit_kpi_staff_report_form(success_redirect):
    if not _has_kpi_portal_access():
        flash("Akses portal KPI staff hanya tersedia untuk role yang diizinkan.", "error")
        return redirect("/workspace/")

    db = get_db()
    linked_employee = _get_self_service_employee(db)
    if not linked_employee:
        flash("Akun ini belum ditautkan ke data karyawan, jadi form KPI belum bisa dipakai.", "error")
        return redirect("/kpi-staff/")
    linked_employee = dict(linked_employee)

    period_label = normalize_kpi_period_label(request.form.get("period_label"))
    kpi_profile = _resolve_effective_kpi_profile(db, linked_employee, period_label=period_label)
    if not kpi_profile:
        flash("Template KPI untuk akun ini belum tersedia.", "error")
        return redirect("/kpi-staff/")

    week_key = normalize_kpi_week_key(request.form.get("week_key"))
    obstacle_note = (request.form.get("obstacle_note") or "").strip()
    solution_note = (request.form.get("solution_note") or "").strip()
    coordination_note = (request.form.get("coordination_note") or "").strip()

    if not obstacle_note or not solution_note:
        flash("Kendala dan solusi KPI wajib diisi.", "error")
        return redirect("/kpi-staff/#kpi-target-form")

    actual_values_by_code = {}
    for metric in kpi_profile.get("metrics", []):
        actual_values_by_code[metric["code"]] = request.form.get(f"metric_{metric['code']}")

    metric_entries = build_kpi_metric_entries(kpi_profile, actual_values_by_code)
    metric_summary = summarize_kpi_metric_entries(metric_entries)
    target_snapshot = {
        "key": kpi_profile.get("key"),
        "display_name": kpi_profile.get("display_name"),
        "warehouse_group": kpi_profile.get("warehouse_group"),
        "warehouse_label": kpi_profile.get("warehouse_label"),
        "minimum_pass_score": kpi_profile.get("minimum_pass_score"),
        "summary": kpi_profile.get("summary"),
        "metrics": [
            {
                "code": metric.get("code"),
                "group": metric.get("group"),
                "label": metric.get("label"),
                "unit": metric.get("unit"),
                "target": metric.get("target"),
                "weight": metric.get("weight"),
            }
            for metric in kpi_profile.get("metrics", [])
        ],
    }

    existing = db.execute(
        """
        SELECT id
        FROM kpi_staff_reports
        WHERE employee_id=? AND period_label=? AND week_key=?
        LIMIT 1
        """,
        (linked_employee["id"], period_label, week_key),
    ).fetchone()

    payload_values = (
        session.get("user_id"),
        linked_employee["id"],
        linked_employee["warehouse_id"],
        date_cls.today().isoformat(),
        period_label,
        week_key,
        kpi_profile["key"],
        kpi_profile["display_name"],
        json.dumps(target_snapshot, ensure_ascii=False),
        json.dumps(metric_entries, ensure_ascii=False),
        json.dumps(kpi_profile.get("team_focus") or [], ensure_ascii=False),
        float(metric_summary["total_weight"]),
        float(metric_summary["weighted_score"]),
        float(metric_summary["completion_ratio"]),
        obstacle_note,
        solution_note,
        coordination_note or None,
        "submitted",
        None,
        None,
        None,
        _current_timestamp(),
    )

    if existing:
        db.execute(
            """
            UPDATE kpi_staff_reports
            SET user_id=?,
                employee_id=?,
                warehouse_id=?,
                report_date=?,
                period_label=?,
                week_key=?,
                template_key=?,
                template_name=?,
                target_payload=?,
                metric_payload=?,
                team_focus_payload=?,
                total_weight=?,
                weighted_score=?,
                completion_ratio=?,
                obstacle_note=?,
                solution_note=?,
                coordination_note=?,
                status=?,
                review_note=?,
                reviewed_by=?,
                reviewed_at=?,
                updated_at=?
            WHERE id=?
            """,
            payload_values + (existing["id"],),
        )
        action_label = "diupdate"
    else:
        db.execute(
            """
            INSERT INTO kpi_staff_reports(
                user_id,
                employee_id,
                warehouse_id,
                report_date,
                period_label,
                week_key,
                template_key,
                template_name,
                target_payload,
                metric_payload,
                team_focus_payload,
                total_weight,
                weighted_score,
                completion_ratio,
                obstacle_note,
                solution_note,
                coordination_note,
                status,
                review_note,
                reviewed_by,
                reviewed_at,
                updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            payload_values,
        )
        action_label = "disimpan"

    db.commit()
    flash(
        f"Input KPI {week_key} untuk {format_kpi_period_label(period_label)} berhasil {action_label} dan akan direview HR / Super Admin.",
        "success",
    )
    return redirect(success_redirect)


@kpi_portal_bp.route("/")
def index():
    if not _has_kpi_portal_access():
        flash("Akses portal KPI staff hanya tersedia untuk role yang diizinkan.", "error")
        return redirect("/workspace/")

    db = get_db()
    return render_template("kpi_portal.html", **_build_kpi_portal_context(db))


@kpi_portal_bp.route("/submit", methods=["POST"])
def submit():
    return _submit_kpi_staff_report_form("/kpi-staff/#kpi-target-form")
