from datetime import date as date_cls, datetime

from flask import Blueprint, render_template, request, redirect, flash, session

from database import get_db
from services.hris_catalog import get_hris_module, get_hris_modules
from services.rbac import is_scoped_role


hris_bp = Blueprint("hris", __name__, url_prefix="/hris")

EMPLOYEE_STATUSES = {"active", "probation", "leave", "inactive"}
ATTENDANCE_STATUSES = {"present", "late", "leave", "absent", "half_day"}
LEAVE_TYPES = {"annual", "sick", "permit", "unpaid", "special"}
LEAVE_STATUSES = {"pending", "approved", "rejected", "cancelled"}
PAYROLL_STATUSES = {"draft", "approved", "paid", "cancelled"}
RECRUITMENT_STAGES = {"applied", "screening", "interview", "offer", "hired"}
RECRUITMENT_STATUSES = {"active", "on_hold", "rejected", "withdrawn", "closed"}
ONBOARDING_STAGES = {"preboarding", "orientation", "system_access", "training", "go_live"}
ONBOARDING_STATUSES = {"pending", "in_progress", "completed", "blocked"}
OFFBOARDING_STAGES = {"notice", "clearance", "handover", "exit_complete"}
OFFBOARDING_STATUSES = {"planned", "in_progress", "completed", "cancelled"}
PERFORMANCE_STATUSES = {"draft", "reviewed", "acknowledged", "closed"}
HELPDESK_CATEGORIES = {"system", "access", "attendance", "payroll", "asset", "other"}
HELPDESK_PRIORITIES = {"low", "medium", "high", "urgent"}
HELPDESK_STATUSES = {"open", "in_progress", "resolved", "closed"}
ASSET_STATUSES = {"allocated", "standby", "maintenance", "returned"}
ASSET_CONDITIONS = {"good", "fair", "damaged"}
PROJECT_PRIORITIES = {"low", "medium", "high", "critical"}
PROJECT_STATUSES = {"planning", "active", "on_hold", "completed", "cancelled"}
BIOMETRIC_PUNCH_TYPES = {"check_in", "check_out"}
BIOMETRIC_SYNC_STATUSES = {"queued", "synced", "failed", "manual"}
HRIS_MANAGE_ROLES = {"super_admin", "owner", "admin", "leader"}


def _to_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def can_manage_hris_records():
    return session.get("role") in HRIS_MANAGE_ROLES


def can_manage_employee_records():
    return can_manage_hris_records()


def can_manage_attendance_records():
    return can_manage_hris_records()


def can_manage_leave_records():
    return can_manage_hris_records()


def can_manage_payroll_records():
    return can_manage_hris_records()


def can_manage_recruitment_records():
    return can_manage_hris_records()


def can_manage_onboarding_records():
    return can_manage_hris_records()


def can_manage_offboarding_records():
    return can_manage_hris_records()


def can_manage_performance_records():
    return can_manage_hris_records()


def can_manage_helpdesk_records():
    return can_manage_hris_records()


def can_manage_asset_records():
    return can_manage_hris_records()


def can_manage_project_records():
    return can_manage_hris_records()


def can_manage_biometric_records():
    return can_manage_hris_records()


def get_hris_scope():
    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id")
    return None


def _normalize_status(value):
    status = (value or "").strip().lower()
    return status if status in EMPLOYEE_STATUSES else "active"


def _normalize_attendance_status(value):
    status = (value or "").strip().lower()
    return status if status in ATTENDANCE_STATUSES else "present"


def _normalize_leave_type(value):
    leave_type = (value or "").strip().lower()
    return leave_type if leave_type in LEAVE_TYPES else "annual"


def _normalize_leave_status(value):
    status = (value or "").strip().lower()
    return status if status in LEAVE_STATUSES else "pending"


def _normalize_payroll_status(value):
    status = (value or "").strip().lower()
    return status if status in PAYROLL_STATUSES else "draft"


def _normalize_recruitment_stage(value):
    stage = (value or "").strip().lower()
    return stage if stage in RECRUITMENT_STAGES else "applied"


def _normalize_recruitment_status(value):
    status = (value or "").strip().lower()
    return status if status in RECRUITMENT_STATUSES else "active"


def _normalize_onboarding_stage(value):
    stage = (value or "").strip().lower()
    return stage if stage in ONBOARDING_STAGES else "preboarding"


def _normalize_onboarding_status(value):
    status = (value or "").strip().lower()
    return status if status in ONBOARDING_STATUSES else "pending"


def _normalize_offboarding_stage(value):
    stage = (value or "").strip().lower()
    return stage if stage in OFFBOARDING_STAGES else "notice"


def _normalize_offboarding_status(value):
    status = (value or "").strip().lower()
    return status if status in OFFBOARDING_STATUSES else "planned"


def _normalize_performance_status(value):
    status = (value or "").strip().lower()
    return status if status in PERFORMANCE_STATUSES else "draft"


def _normalize_helpdesk_category(value):
    category = (value or "").strip().lower()
    return category if category in HELPDESK_CATEGORIES else "other"


def _normalize_helpdesk_priority(value):
    priority = (value or "").strip().lower()
    return priority if priority in HELPDESK_PRIORITIES else "medium"


def _normalize_helpdesk_status(value):
    status = (value or "").strip().lower()
    return status if status in HELPDESK_STATUSES else "open"


def _normalize_asset_status(value):
    status = (value or "").strip().lower()
    return status if status in ASSET_STATUSES else "allocated"


def _normalize_asset_condition(value):
    condition = (value or "").strip().lower()
    return condition if condition in ASSET_CONDITIONS else "good"


def _normalize_project_priority(value):
    priority = (value or "").strip().lower()
    return priority if priority in PROJECT_PRIORITIES else "medium"


def _normalize_project_status(value):
    status = (value or "").strip().lower()
    return status if status in PROJECT_STATUSES else "planning"


def _normalize_biometric_punch_type(value):
    punch_type = (value or "").strip().lower()
    return punch_type if punch_type in BIOMETRIC_PUNCH_TYPES else "check_in"


def _normalize_biometric_sync_status(value):
    status = (value or "").strip().lower()
    return status if status in BIOMETRIC_SYNC_STATUSES else "queued"


def _calculate_leave_days(start_date, end_date):
    if not start_date or not end_date:
        return None

    try:
        start_value = date_cls.fromisoformat(start_date)
        end_value = date_cls.fromisoformat(end_date)
    except ValueError:
        return None

    if end_value < start_value:
        return None

    return (end_value - start_value).days + 1


def _current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_datetime_input(value):
    raw_value = (value or "").strip()
    if not raw_value:
        return None

    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", ""))
    except ValueError:
        return None

    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _build_leave_handling(status):
    if status == "pending":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_payroll_handling(status):
    if status == "draft":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_recruitment_handling(status):
    if status == "active":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_onboarding_handling(status):
    if status == "pending":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_offboarding_handling(status):
    if status == "planned":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_performance_handling(status):
    if status == "draft":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_helpdesk_handling(status):
    if status == "open":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_asset_handling(status):
    if status == "standby":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_project_handling(status):
    if status == "planning":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_biometric_handling(status):
    if status == "queued":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _calculate_net_pay(base_salary, allowance, overtime_pay, deduction, leave_deduction):
    return round(base_salary + allowance + overtime_pay - deduction - leave_deduction, 2)


def _calculate_performance_score(goal_score, discipline_score, teamwork_score):
    return round((goal_score + discipline_score + teamwork_score) / 3.0, 2)


def _derive_performance_rating(final_score):
    if final_score >= 90:
        return "excellent"
    if final_score >= 75:
        return "good"
    if final_score >= 60:
        return "fair"
    return "needs_improvement"


def _derive_biometric_attendance_status(check_in_time):
    if check_in_time and check_in_time > "08:30":
        return "late"
    return "present"


def _resolve_employee_warehouse(db, raw_warehouse_id):
    scope_warehouse = get_hris_scope()
    if scope_warehouse:
        return scope_warehouse

    warehouse_id = _to_int(raw_warehouse_id)
    if warehouse_id is None:
        return None

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    return warehouse["id"] if warehouse else None


def _get_accessible_employee(db, employee_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            e.*,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        WHERE e.id=?
    """
    params = [employee_id]

    if scope_warehouse:
        query += " AND e.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_employee_by_id(db, employee_id):
    return _get_accessible_employee(db, employee_id)


def _get_attendance_by_id(db, attendance_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name
        FROM attendance_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        WHERE a.id=?
    """
    params = [attendance_id]

    if scope_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_leave_request_by_id(db, leave_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            l.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM leave_requests l
        JOIN employees e ON l.employee_id = e.id
        LEFT JOIN warehouses w ON l.warehouse_id = w.id
        LEFT JOIN users u ON l.handled_by = u.id
        WHERE l.id=?
    """
    params = [leave_id]

    if scope_warehouse:
        query += " AND l.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_payroll_by_id(db, payroll_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM payroll_runs p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE p.id=?
    """
    params = [payroll_id]

    if scope_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_recruitment_candidate_by_id(db, candidate_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            r.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM recruitment_candidates r
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.handled_by = u.id
        WHERE r.id=?
    """
    params = [candidate_id]

    if scope_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_onboarding_by_id(db, onboarding_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM onboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE o.id=?
    """
    params = [onboarding_id]

    if scope_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_offboarding_by_id(db, offboarding_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM offboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE o.id=?
    """
    params = [offboarding_id]

    if scope_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_performance_by_id(db, review_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM performance_reviews p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE p.id=?
    """
    params = [review_id]

    if scope_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_helpdesk_ticket_by_id(db, ticket_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            h.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM helpdesk_tickets h
        JOIN employees e ON h.employee_id = e.id
        LEFT JOIN warehouses w ON h.warehouse_id = w.id
        LEFT JOIN users u ON h.handled_by = u.id
        WHERE h.id=?
    """
    params = [ticket_id]

    if scope_warehouse:
        query += " AND h.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_asset_record_by_id(db, asset_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM asset_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE a.id=?
    """
    params = [asset_id]

    if scope_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_project_by_id(db, project_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM project_records p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE p.id=?
    """
    params = [project_id]

    if scope_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_biometric_log_by_id(db, biometric_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            b.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM biometric_logs b
        JOIN employees e ON b.employee_id = e.id
        LEFT JOIN warehouses w ON b.warehouse_id = w.id
        LEFT JOIN users u ON b.handled_by = u.id
        WHERE b.id=?
    """
    params = [biometric_id]

    if scope_warehouse:
        query += " AND b.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _resync_attendance_from_biometrics(db, employee_id, warehouse_id, attendance_date):
    if not employee_id or not warehouse_id or not attendance_date:
        return

    logs = [
        dict(row)
        for row in db.execute(
            """
            SELECT punch_time, punch_type, sync_status
            FROM biometric_logs
            WHERE employee_id=?
              AND warehouse_id=?
              AND substr(punch_time, 1, 10)=?
              AND sync_status IN (?,?)
            ORDER BY punch_time ASC, id ASC
            """,
            (employee_id, warehouse_id, attendance_date, "synced", "manual"),
        ).fetchall()
    ]
    existing = db.execute(
        """
        SELECT id, note
        FROM attendance_records
        WHERE employee_id=? AND attendance_date=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (employee_id, attendance_date),
    ).fetchone()

    if not logs:
        if existing and (existing["note"] or "") == "Synced from biometric":
            db.execute("DELETE FROM attendance_records WHERE id=?", (existing["id"],))
        return

    check_in = next(
        (
            datetime.fromisoformat(log["punch_time"]).strftime("%H:%M")
            for log in logs
            if log["punch_type"] == "check_in"
        ),
        None,
    )
    check_out = next(
        (
            datetime.fromisoformat(log["punch_time"]).strftime("%H:%M")
            for log in reversed(logs)
            if log["punch_type"] == "check_out"
        ),
        None,
    )
    status = _derive_biometric_attendance_status(check_in)

    if existing:
        db.execute(
            """
            UPDATE attendance_records
            SET warehouse_id=?,
                check_in=?,
                check_out=?,
                status=?,
                note=?,
                updated_at=?
            WHERE id=?
            """,
            (
                warehouse_id,
                check_in,
                check_out,
                status,
                "Synced from biometric",
                _current_timestamp(),
                existing["id"],
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO attendance_records(
                employee_id,
                warehouse_id,
                attendance_date,
                check_in,
                check_out,
                status,
                note,
                updated_at
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                employee_id,
                warehouse_id,
                attendance_date,
                check_in,
                check_out,
                status,
                "Synced from biometric",
                _current_timestamp(),
            ),
        )


def _fetch_employee_options(db):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            e.id,
            e.employee_code,
            e.full_name,
            e.employment_status,
            e.warehouse_id,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        WHERE 1=1
    """
    params = []

    if scope_warehouse:
        query += " AND e.warehouse_id=?"
        params.append(scope_warehouse)

    query += " ORDER BY e.full_name COLLATE NOCASE ASC, e.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _build_employee_summary(employees):
    return {
        "total": len(employees),
        "active": sum(1 for employee in employees if employee["employment_status"] == "active"),
        "probation": sum(1 for employee in employees if employee["employment_status"] == "probation"),
        "leave": sum(1 for employee in employees if employee["employment_status"] == "leave"),
        "inactive": sum(1 for employee in employees if employee["employment_status"] == "inactive"),
        "with_email": sum(1 for employee in employees if employee["email"]),
        "with_phone": sum(1 for employee in employees if employee["phone"]),
    }


def _build_attendance_summary(attendance_records):
    return {
        "total": len(attendance_records),
        "present": sum(1 for record in attendance_records if record["status"] == "present"),
        "late": sum(1 for record in attendance_records if record["status"] == "late"),
        "leave": sum(1 for record in attendance_records if record["status"] == "leave"),
        "absent": sum(1 for record in attendance_records if record["status"] == "absent"),
        "half_day": sum(1 for record in attendance_records if record["status"] == "half_day"),
        "with_check_in": sum(1 for record in attendance_records if record["check_in"]),
        "with_check_out": sum(1 for record in attendance_records if record["check_out"]),
    }


def _build_leave_summary(leave_requests):
    return {
        "total": len(leave_requests),
        "pending": sum(1 for record in leave_requests if record["status"] == "pending"),
        "approved": sum(1 for record in leave_requests if record["status"] == "approved"),
        "rejected": sum(1 for record in leave_requests if record["status"] == "rejected"),
        "cancelled": sum(1 for record in leave_requests if record["status"] == "cancelled"),
        "total_days": sum((record["total_days"] or 0) for record in leave_requests),
    }


def _build_payroll_summary(payroll_runs):
    return {
        "total": len(payroll_runs),
        "draft": sum(1 for record in payroll_runs if record["status"] == "draft"),
        "approved": sum(1 for record in payroll_runs if record["status"] == "approved"),
        "paid": sum(1 for record in payroll_runs if record["status"] == "paid"),
        "cancelled": sum(1 for record in payroll_runs if record["status"] == "cancelled"),
        "total_base_salary": round(sum((record["base_salary"] or 0) for record in payroll_runs), 2),
        "total_net_pay": round(sum((record["net_pay"] or 0) for record in payroll_runs), 2),
    }


def _build_recruitment_summary(recruitment_candidates):
    return {
        "total": len(recruitment_candidates),
        "interview": sum(1 for candidate in recruitment_candidates if candidate["stage"] == "interview"),
        "offer": sum(1 for candidate in recruitment_candidates if candidate["stage"] == "offer"),
        "hired": sum(1 for candidate in recruitment_candidates if candidate["stage"] == "hired" or candidate["status"] == "closed"),
        "active": sum(1 for candidate in recruitment_candidates if candidate["status"] == "active"),
        "closed": sum(1 for candidate in recruitment_candidates if candidate["status"] in {"closed", "rejected", "withdrawn"}),
    }


def _build_onboarding_summary(onboarding_records):
    return {
        "total": len(onboarding_records),
        "pending": sum(1 for record in onboarding_records if record["status"] == "pending"),
        "in_progress": sum(1 for record in onboarding_records if record["status"] == "in_progress"),
        "completed": sum(1 for record in onboarding_records if record["status"] == "completed"),
        "blocked": sum(1 for record in onboarding_records if record["status"] == "blocked"),
        "preboarding": sum(1 for record in onboarding_records if record["stage"] == "preboarding"),
        "go_live": sum(1 for record in onboarding_records if record["stage"] == "go_live"),
    }


def _build_offboarding_summary(offboarding_records):
    return {
        "total": len(offboarding_records),
        "planned": sum(1 for record in offboarding_records if record["status"] == "planned"),
        "in_progress": sum(1 for record in offboarding_records if record["status"] == "in_progress"),
        "completed": sum(1 for record in offboarding_records if record["status"] == "completed"),
        "cancelled": sum(1 for record in offboarding_records if record["status"] == "cancelled"),
        "notice": sum(1 for record in offboarding_records if record["stage"] == "notice"),
        "exit_complete": sum(1 for record in offboarding_records if record["stage"] == "exit_complete"),
    }


def _build_performance_summary(performance_reviews):
    total_score = sum((record["final_score"] or 0) for record in performance_reviews)
    count = len(performance_reviews)
    return {
        "total": count,
        "draft": sum(1 for record in performance_reviews if record["status"] == "draft"),
        "reviewed": sum(1 for record in performance_reviews if record["status"] == "reviewed"),
        "acknowledged": sum(1 for record in performance_reviews if record["status"] == "acknowledged"),
        "closed": sum(1 for record in performance_reviews if record["status"] == "closed"),
        "avg_score": round(total_score / count, 2) if count else 0,
    }


def _build_helpdesk_summary(helpdesk_tickets):
    return {
        "total": len(helpdesk_tickets),
        "open": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "open"),
        "in_progress": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "in_progress"),
        "resolved": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "resolved"),
        "closed": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "closed"),
        "urgent": sum(1 for ticket in helpdesk_tickets if ticket["priority"] == "urgent"),
        "assigned": sum(1 for ticket in helpdesk_tickets if ticket["assigned_to"]),
    }


def _build_asset_summary(asset_records):
    return {
        "total": len(asset_records),
        "allocated": sum(1 for record in asset_records if record["asset_status"] == "allocated"),
        "standby": sum(1 for record in asset_records if record["asset_status"] == "standby"),
        "maintenance": sum(1 for record in asset_records if record["asset_status"] == "maintenance"),
        "returned": sum(1 for record in asset_records if record["asset_status"] == "returned"),
        "good": sum(1 for record in asset_records if record["condition_status"] == "good"),
        "damaged": sum(1 for record in asset_records if record["condition_status"] == "damaged"),
    }


def _build_project_summary(project_records):
    total_progress = sum((record["progress_percent"] or 0) for record in project_records)
    count = len(project_records)
    overdue_count = 0
    today_value = date_cls.today().isoformat()
    for record in project_records:
        due_date = record["due_date"] or ""
        if due_date and due_date < today_value and record["status"] not in {"completed", "cancelled"}:
            overdue_count += 1

    return {
        "total": count,
        "planning": sum(1 for record in project_records if record["status"] == "planning"),
        "active": sum(1 for record in project_records if record["status"] == "active"),
        "on_hold": sum(1 for record in project_records if record["status"] == "on_hold"),
        "completed": sum(1 for record in project_records if record["status"] == "completed"),
        "cancelled": sum(1 for record in project_records if record["status"] == "cancelled"),
        "critical": sum(1 for record in project_records if record["priority"] == "critical"),
        "avg_progress": round(total_progress / count, 2) if count else 0,
        "overdue": overdue_count,
    }


def _build_biometric_summary(biometric_logs):
    devices = {log["device_name"] for log in biometric_logs if log["device_name"]}
    return {
        "total": len(biometric_logs),
        "queued": sum(1 for log in biometric_logs if log["sync_status"] == "queued"),
        "synced": sum(1 for log in biometric_logs if log["sync_status"] == "synced"),
        "manual": sum(1 for log in biometric_logs if log["sync_status"] == "manual"),
        "failed": sum(1 for log in biometric_logs if log["sync_status"] == "failed"),
        "check_in": sum(1 for log in biometric_logs if log["punch_type"] == "check_in"),
        "check_out": sum(1 for log in biometric_logs if log["punch_type"] == "check_out"),
        "devices": len(devices),
    }


def _build_report_snapshot(db):
    scope_warehouse = get_hris_scope()
    selected_warehouse = scope_warehouse or _to_int(request.args.get("warehouse"))
    base_params = [selected_warehouse] if selected_warehouse else []

    def count_from(table_name, extra_where="", extra_params=None):
        query = f"SELECT COUNT(*) FROM {table_name} WHERE 1=1"
        params = list(base_params)
        if selected_warehouse:
            query += " AND warehouse_id=?"
        if extra_where:
            query += f" AND {extra_where}"
            if extra_params:
                params.extend(extra_params)
        return db.execute(query, params).fetchone()[0]

    def avg_from(table_name, column_name):
        query = f"SELECT AVG({column_name}) FROM {table_name} WHERE 1=1"
        params = list(base_params)
        if selected_warehouse:
            query += " AND warehouse_id=?"
        value = db.execute(query, params).fetchone()[0]
        return round(value or 0, 2)

    total_employees = count_from("employees")
    active_employees = count_from("employees", "employment_status=?", ["active"])
    probation_employees = count_from("employees", "employment_status=?", ["probation"])
    leave_employees = count_from("employees", "employment_status=?", ["leave"])

    open_leave = count_from("leave_requests", "status=?", ["pending"])
    active_recruitment = count_from("recruitment_candidates", "status=?", ["active"])
    onboarding_live = count_from("onboarding_records", "status=?", ["in_progress"])
    offboarding_live = count_from("offboarding_records", "status IN (?,?)", ["planned", "in_progress"])
    helpdesk_open = count_from("helpdesk_tickets", "status IN (?,?)", ["open", "in_progress"])
    asset_live = count_from("asset_records", "asset_status IN (?,?)", ["allocated", "maintenance"])
    active_projects = count_from("project_records", "status IN (?,?)", ["planning", "active"])
    biometric_queue = count_from("biometric_logs", "sync_status=?", ["queued"])
    paid_payroll = count_from("payroll_runs", "status=?", ["paid"])
    avg_score = avg_from("performance_reviews", "final_score")

    warehouse_name = "Semua Gudang"
    if selected_warehouse:
        warehouse = db.execute("SELECT name FROM warehouses WHERE id=?", (selected_warehouse,)).fetchone()
        if warehouse:
            warehouse_name = warehouse["name"]

    summary = {
        "total_employees": total_employees,
        "open_ops": open_leave + onboarding_live + offboarding_live + helpdesk_open + biometric_queue,
        "active_projects": active_projects,
        "avg_score": avg_score,
        "warehouse_name": warehouse_name,
        "snapshot_at": _current_timestamp(),
    }

    workforce_rows = [
        {"label": "Total Karyawan", "value": total_employees, "detail": "Headcount dalam scope report saat ini."},
        {"label": "Karyawan Aktif", "value": active_employees, "detail": "Resource inti yang siap operasional."},
        {"label": "Probation", "value": probation_employees, "detail": "Perlu onboarding dan evaluasi dekat."},
        {"label": "Status Leave", "value": leave_employees, "detail": "Karyawan yang sedang leave dari master status."},
    ]
    pipeline_rows = [
        {"module": "Leave", "value": open_leave, "detail": "Pengajuan leave yang masih menunggu proses."},
        {"module": "Recruitment", "value": active_recruitment, "detail": "Kandidat aktif dalam hiring pipeline."},
        {"module": "Onboarding", "value": onboarding_live, "detail": "Onboarding yang sedang berjalan."},
        {"module": "Offboarding", "value": offboarding_live, "detail": "Exit flow yang masih aktif."},
    ]
    service_rows = [
        {"module": "Helpdesk", "value": helpdesk_open, "detail": "Ticket support yang masih terbuka atau dikerjakan."},
        {"module": "Asset", "value": asset_live, "detail": "Asset aktif yang terdistribusi atau maintenance."},
        {"module": "Project", "value": active_projects, "detail": "Project yang sedang planning atau active."},
        {"module": "Biometric Queue", "value": biometric_queue, "detail": "Log biometric yang masih menunggu sinkronisasi."},
        {"module": "Payroll Paid", "value": paid_payroll, "detail": "Run payroll yang sudah dibayar."},
        {"module": "Avg Performance", "value": f'{avg_score:.2f}', "detail": "Rata-rata skor review performa."},
    ]

    return summary, {"warehouse_id": selected_warehouse}, workforce_rows, pipeline_rows, service_rows


def _fetch_employees(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            e.*,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in EMPLOYEE_STATUSES:
        query += " AND e.employment_status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND e.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY e.full_name COLLATE NOCASE ASC, e.id DESC"

    employees = [dict(row) for row in db.execute(query, params).fetchall()]
    return employees, search, status, selected_warehouse


def _fetch_attendance_records(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name
        FROM attendance_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in ATTENDANCE_STATUSES:
        query += " AND a.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(selected_warehouse)

    if date_from:
        query += " AND a.attendance_date>=?"
        params.append(date_from)

    if date_to:
        query += " AND a.attendance_date<=?"
        params.append(date_to)

    query += " ORDER BY a.attendance_date DESC, e.full_name COLLATE NOCASE ASC, a.id DESC"

    attendance_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return attendance_records, search, status, selected_warehouse, date_from, date_to


def _fetch_leave_requests(db):
    search = (request.args.get("q") or "").strip()
    leave_type = (request.args.get("leave_type") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            l.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM leave_requests l
        JOIN employees e ON l.employee_id = e.id
        LEFT JOIN warehouses w ON l.warehouse_id = w.id
        LEFT JOIN users u ON l.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(l.reason, '') LIKE ?
                OR COALESCE(l.note, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if leave_type in LEAVE_TYPES:
        query += " AND l.leave_type=?"
        params.append(leave_type)

    if status in LEAVE_STATUSES:
        query += " AND l.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND l.warehouse_id=?"
        params.append(selected_warehouse)

    if date_from:
        query += " AND l.start_date>=?"
        params.append(date_from)

    if date_to:
        query += " AND l.end_date<=?"
        params.append(date_to)

    query += " ORDER BY l.start_date DESC, e.full_name COLLATE NOCASE ASC, l.id DESC"

    leave_requests = [dict(row) for row in db.execute(query, params).fetchall()]
    return leave_requests, search, leave_type, status, selected_warehouse, date_from, date_to


def _fetch_payroll_runs(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    period_month = _to_int(request.args.get("period_month"))
    period_year = _to_int(request.args.get("period_year"))
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM payroll_runs p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in PAYROLL_STATUSES:
        query += " AND p.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(selected_warehouse)

    if period_month:
        query += " AND p.period_month=?"
        params.append(period_month)

    if period_year:
        query += " AND p.period_year=?"
        params.append(period_year)

    query += " ORDER BY p.period_year DESC, p.period_month DESC, e.full_name COLLATE NOCASE ASC, p.id DESC"

    payroll_runs = [dict(row) for row in db.execute(query, params).fetchall()]
    return payroll_runs, search, status, selected_warehouse, period_month, period_year


def _fetch_recruitment_candidates(db):
    search = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            r.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM recruitment_candidates r
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                r.candidate_name LIKE ?
                OR r.position_title LIKE ?
                OR COALESCE(r.department, '') LIKE ?
                OR COALESCE(r.source, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if stage in RECRUITMENT_STAGES:
        query += " AND r.stage=?"
        params.append(stage)

    if status in RECRUITMENT_STATUSES:
        query += " AND r.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY r.created_at DESC, r.candidate_name COLLATE NOCASE ASC, r.id DESC"

    recruitment_candidates = [dict(row) for row in db.execute(query, params).fetchall()]
    return recruitment_candidates, search, stage, status, selected_warehouse


def _fetch_onboarding_records(db):
    search = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM onboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if stage in ONBOARDING_STAGES:
        query += " AND o.stage=?"
        params.append(stage)

    if status in ONBOARDING_STATUSES:
        query += " AND o.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY o.start_date DESC, e.full_name COLLATE NOCASE ASC, o.id DESC"

    onboarding_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return onboarding_records, search, stage, status, selected_warehouse


def _fetch_offboarding_records(db):
    search = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM offboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(o.exit_reason, '') LIKE ?
                OR COALESCE(o.handover_pic, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if stage in OFFBOARDING_STAGES:
        query += " AND o.stage=?"
        params.append(stage)

    if status in OFFBOARDING_STATUSES:
        query += " AND o.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY o.notice_date DESC, e.full_name COLLATE NOCASE ASC, o.id DESC"

    offboarding_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return offboarding_records, search, stage, status, selected_warehouse


def _fetch_performance_reviews(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    review_period = (request.args.get("review_period") or "").strip()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM performance_reviews p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in PERFORMANCE_STATUSES:
        query += " AND p.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(selected_warehouse)

    if review_period:
        query += " AND p.review_period=?"
        params.append(review_period)

    query += " ORDER BY p.review_period DESC, e.full_name COLLATE NOCASE ASC, p.id DESC"

    performance_reviews = [dict(row) for row in db.execute(query, params).fetchall()]
    return performance_reviews, search, status, selected_warehouse, review_period


def _fetch_helpdesk_tickets(db):
    search = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "all").strip().lower()
    priority = (request.args.get("priority") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            h.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM helpdesk_tickets h
        JOIN employees e ON h.employee_id = e.id
        LEFT JOIN warehouses w ON h.warehouse_id = w.id
        LEFT JOIN users u ON h.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR h.ticket_title LIKE ?
                OR COALESCE(h.assigned_to, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if category in HELPDESK_CATEGORIES:
        query += " AND h.category=?"
        params.append(category)

    if priority in HELPDESK_PRIORITIES:
        query += " AND h.priority=?"
        params.append(priority)

    if status in HELPDESK_STATUSES:
        query += " AND h.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND h.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY h.created_at DESC, e.full_name COLLATE NOCASE ASC, h.id DESC"

    helpdesk_tickets = [dict(row) for row in db.execute(query, params).fetchall()]
    return helpdesk_tickets, search, category, priority, status, selected_warehouse


def _fetch_asset_records(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    condition = (request.args.get("condition") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM asset_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR a.asset_name LIKE ?
                OR a.asset_code LIKE ?
                OR COALESCE(a.serial_number, '') LIKE ?
                OR COALESCE(a.category, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like, like, like])

    if status in ASSET_STATUSES:
        query += " AND a.asset_status=?"
        params.append(status)

    if condition in ASSET_CONDITIONS:
        query += " AND a.condition_status=?"
        params.append(condition)

    if selected_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY a.assigned_date DESC, e.full_name COLLATE NOCASE ASC, a.id DESC"

    asset_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return asset_records, search, status, condition, selected_warehouse


def _fetch_project_records(db):
    search = (request.args.get("q") or "").strip()
    priority = (request.args.get("priority") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM project_records p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR p.project_name LIKE ?
                OR p.project_code LIKE ?
                OR COALESCE(p.owner_name, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like, like])

    if priority in PROJECT_PRIORITIES:
        query += " AND p.priority=?"
        params.append(priority)

    if status in PROJECT_STATUSES:
        query += " AND p.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY p.start_date DESC, e.full_name COLLATE NOCASE ASC, p.id DESC"

    project_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return project_records, search, priority, status, selected_warehouse


def _fetch_biometric_logs(db):
    search = (request.args.get("q") or "").strip()
    punch_type = (request.args.get("punch_type") or "all").strip().lower()
    sync_status = (request.args.get("sync_status") or "all").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            b.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM biometric_logs b
        JOIN employees e ON b.employee_id = e.id
        LEFT JOIN warehouses w ON b.warehouse_id = w.id
        LEFT JOIN users u ON b.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(b.device_name, '') LIKE ?
                OR COALESCE(b.device_user_id, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if punch_type in BIOMETRIC_PUNCH_TYPES:
        query += " AND b.punch_type=?"
        params.append(punch_type)

    if sync_status in BIOMETRIC_SYNC_STATUSES:
        query += " AND b.sync_status=?"
        params.append(sync_status)

    if selected_warehouse:
        query += " AND b.warehouse_id=?"
        params.append(selected_warehouse)

    if date_from:
        query += " AND substr(b.punch_time, 1, 10)>=?"
        params.append(date_from)

    if date_to:
        query += " AND substr(b.punch_time, 1, 10)<=?"
        params.append(date_to)

    query += " ORDER BY b.punch_time DESC, e.full_name COLLATE NOCASE ASC, b.id DESC"

    biometric_logs = [dict(row) for row in db.execute(query, params).fetchall()]
    return biometric_logs, search, punch_type, sync_status, selected_warehouse, date_from, date_to


@hris_bp.route("/")
@hris_bp.route("/<module_slug>")
def hris_index(module_slug=None):
    db = get_db()
    modules = get_hris_modules()
    selected_module = get_hris_module(module_slug or "employee")

    if selected_module is None:
        selected_module = modules[0]

    scope_warehouse = get_hris_scope()
    can_manage_hris = can_manage_hris_records()

    employees = []
    employee_summary = None
    employee_filters = None
    attendance_records = []
    attendance_summary = None
    attendance_filters = None
    attendance_employees = []
    leave_requests = []
    leave_summary = None
    leave_filters = None
    leave_employees = []
    payroll_runs = []
    payroll_summary = None
    payroll_filters = None
    payroll_employees = []
    recruitment_candidates = []
    recruitment_summary = None
    recruitment_filters = None
    onboarding_records = []
    onboarding_summary = None
    onboarding_filters = None
    onboarding_employees = []
    offboarding_records = []
    offboarding_summary = None
    offboarding_filters = None
    offboarding_employees = []
    performance_reviews = []
    performance_summary = None
    performance_filters = None
    performance_employees = []
    helpdesk_tickets = []
    helpdesk_summary = None
    helpdesk_filters = None
    helpdesk_employees = []
    asset_records = []
    asset_summary = None
    asset_filters = None
    asset_employees = []
    project_records = []
    project_summary = None
    project_filters = None
    project_employees = []
    biometric_logs = []
    biometric_summary = None
    biometric_filters = None
    biometric_employees = []
    report_summary = None
    report_filters = None
    report_workforce_rows = []
    report_pipeline_rows = []
    report_service_rows = []
    warehouses = db.execute(
        "SELECT * FROM warehouses ORDER BY name"
    ).fetchall()

    if selected_module["slug"] == "employee":
        employees, search, status, selected_warehouse = _fetch_employees(db)
        employee_summary = _build_employee_summary(employees)
        employee_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
    elif selected_module["slug"] == "attendance":
        attendance_records, search, status, selected_warehouse, date_from, date_to = _fetch_attendance_records(db)
        attendance_summary = _build_attendance_summary(attendance_records)
        attendance_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
            "date_from": date_from,
            "date_to": date_to,
        }
        attendance_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "leave":
        leave_requests, search, leave_type, status, selected_warehouse, date_from, date_to = _fetch_leave_requests(db)
        leave_summary = _build_leave_summary(leave_requests)
        leave_filters = {
            "search": search,
            "leave_type": leave_type,
            "status": status,
            "warehouse_id": selected_warehouse,
            "date_from": date_from,
            "date_to": date_to,
        }
        leave_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "payroll":
        payroll_runs, search, status, selected_warehouse, period_month, period_year = _fetch_payroll_runs(db)
        payroll_summary = _build_payroll_summary(payroll_runs)
        payroll_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
            "period_month": period_month,
            "period_year": period_year,
        }
        payroll_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "recruitment":
        recruitment_candidates, search, stage, status, selected_warehouse = _fetch_recruitment_candidates(db)
        recruitment_summary = _build_recruitment_summary(recruitment_candidates)
        recruitment_filters = {
            "search": search,
            "stage": stage,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
    elif selected_module["slug"] == "onboarding":
        onboarding_records, search, stage, status, selected_warehouse = _fetch_onboarding_records(db)
        onboarding_summary = _build_onboarding_summary(onboarding_records)
        onboarding_filters = {
            "search": search,
            "stage": stage,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
        onboarding_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "offboarding":
        offboarding_records, search, stage, status, selected_warehouse = _fetch_offboarding_records(db)
        offboarding_summary = _build_offboarding_summary(offboarding_records)
        offboarding_filters = {
            "search": search,
            "stage": stage,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
        offboarding_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "pms":
        performance_reviews, search, status, selected_warehouse, review_period = _fetch_performance_reviews(db)
        performance_summary = _build_performance_summary(performance_reviews)
        performance_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
            "review_period": review_period,
        }
        performance_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "helpdesk":
        helpdesk_tickets, search, category, priority, status, selected_warehouse = _fetch_helpdesk_tickets(db)
        helpdesk_summary = _build_helpdesk_summary(helpdesk_tickets)
        helpdesk_filters = {
            "search": search,
            "category": category,
            "priority": priority,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
        helpdesk_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "asset":
        asset_records, search, status, condition, selected_warehouse = _fetch_asset_records(db)
        asset_summary = _build_asset_summary(asset_records)
        asset_filters = {
            "search": search,
            "status": status,
            "condition": condition,
            "warehouse_id": selected_warehouse,
        }
        asset_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "project":
        project_records, search, priority, status, selected_warehouse = _fetch_project_records(db)
        project_summary = _build_project_summary(project_records)
        project_filters = {
            "search": search,
            "priority": priority,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
        project_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "report":
        report_summary, report_filters, report_workforce_rows, report_pipeline_rows, report_service_rows = _build_report_snapshot(db)
    elif selected_module["slug"] == "biometric":
        biometric_logs, search, punch_type, sync_status, selected_warehouse, date_from, date_to = _fetch_biometric_logs(db)
        biometric_summary = _build_biometric_summary(biometric_logs)
        biometric_filters = {
            "search": search,
            "punch_type": punch_type,
            "sync_status": sync_status,
            "warehouse_id": selected_warehouse,
            "date_from": date_from,
            "date_to": date_to,
        }
        biometric_employees = _fetch_employee_options(db)

    return render_template(
        "hris.html",
        modules=modules,
        selected_module=selected_module,
        employees=employees,
        employee_summary=employee_summary,
        employee_filters=employee_filters,
        attendance_records=attendance_records,
        attendance_summary=attendance_summary,
        attendance_filters=attendance_filters,
        attendance_employees=attendance_employees,
        leave_requests=leave_requests,
        leave_summary=leave_summary,
        leave_filters=leave_filters,
        leave_employees=leave_employees,
        payroll_runs=payroll_runs,
        payroll_summary=payroll_summary,
        payroll_filters=payroll_filters,
        payroll_employees=payroll_employees,
        recruitment_candidates=recruitment_candidates,
        recruitment_summary=recruitment_summary,
        recruitment_filters=recruitment_filters,
        onboarding_records=onboarding_records,
        onboarding_summary=onboarding_summary,
        onboarding_filters=onboarding_filters,
        onboarding_employees=onboarding_employees,
        offboarding_records=offboarding_records,
        offboarding_summary=offboarding_summary,
        offboarding_filters=offboarding_filters,
        offboarding_employees=offboarding_employees,
        performance_reviews=performance_reviews,
        performance_summary=performance_summary,
        performance_filters=performance_filters,
        performance_employees=performance_employees,
        helpdesk_tickets=helpdesk_tickets,
        helpdesk_summary=helpdesk_summary,
        helpdesk_filters=helpdesk_filters,
        helpdesk_employees=helpdesk_employees,
        asset_records=asset_records,
        asset_summary=asset_summary,
        asset_filters=asset_filters,
        asset_employees=asset_employees,
        project_records=project_records,
        project_summary=project_summary,
        project_filters=project_filters,
        project_employees=project_employees,
        biometric_logs=biometric_logs,
        biometric_summary=biometric_summary,
        biometric_filters=biometric_filters,
        biometric_employees=biometric_employees,
        report_summary=report_summary,
        report_filters=report_filters,
        report_workforce_rows=report_workforce_rows,
        report_pipeline_rows=report_pipeline_rows,
        report_service_rows=report_service_rows,
        warehouses=warehouses,
        can_manage_employee=can_manage_hris,
        can_manage_attendance=can_manage_hris,
        can_manage_leave=can_manage_hris,
        can_manage_payroll=can_manage_hris,
        can_manage_recruitment=can_manage_hris,
        can_manage_onboarding=can_manage_hris,
        can_manage_offboarding=can_manage_hris,
        can_manage_performance=can_manage_hris,
        can_manage_helpdesk=can_manage_hris,
        can_manage_asset=can_manage_hris,
        can_manage_project=can_manage_hris,
        can_manage_biometric=can_manage_hris,
        employee_scope_warehouse=scope_warehouse,
        attendance_scope_warehouse=scope_warehouse,
        leave_scope_warehouse=scope_warehouse,
        payroll_scope_warehouse=scope_warehouse,
        recruitment_scope_warehouse=scope_warehouse,
        onboarding_scope_warehouse=scope_warehouse,
        offboarding_scope_warehouse=scope_warehouse,
        performance_scope_warehouse=scope_warehouse,
        helpdesk_scope_warehouse=scope_warehouse,
        asset_scope_warehouse=scope_warehouse,
        project_scope_warehouse=scope_warehouse,
        biometric_scope_warehouse=scope_warehouse,
        report_scope_warehouse=scope_warehouse,
    )


@hris_bp.route("/employee/add", methods=["POST"])
def add_employee():
    if not can_manage_employee_records():
        flash("Tidak punya akses untuk mengelola data karyawan", "error")
        return redirect("/hris/employee")

    db = get_db()
    employee_code = (request.form.get("employee_code") or "").strip().upper()
    full_name = (request.form.get("full_name") or "").strip()
    department = (request.form.get("department") or "").strip()
    position = (request.form.get("position") or "").strip()
    employment_status = _normalize_status(request.form.get("employment_status"))
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    join_date = (request.form.get("join_date") or "").strip()
    work_location = (request.form.get("work_location") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not employee_code or not full_name:
        flash("Employee code dan nama lengkap wajib diisi", "error")
        return redirect("/hris/employee")

    if warehouse_id is None:
        flash("Gudang kerja wajib diisi", "error")
        return redirect("/hris/employee")

    duplicate = db.execute(
        "SELECT id FROM employees WHERE employee_code=?",
        (employee_code,),
    ).fetchone()
    if duplicate:
        flash("Employee code sudah digunakan", "error")
        return redirect("/hris/employee")

    db.execute(
        """
        INSERT INTO employees(
            employee_code,
            full_name,
            warehouse_id,
            department,
            position,
            employment_status,
            phone,
            email,
            join_date,
            work_location,
            notes,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            employee_code,
            full_name,
            warehouse_id,
            department or None,
            position or None,
            employment_status,
            phone or None,
            email or None,
            join_date or None,
            work_location or None,
            notes or None,
        ),
    )
    db.commit()

    flash("Data karyawan berhasil ditambahkan", "success")
    return redirect("/hris/employee")


@hris_bp.route("/employee/update/<int:employee_id>", methods=["POST"])
def update_employee(employee_id):
    if not can_manage_employee_records():
        flash("Tidak punya akses untuk mengelola data karyawan", "error")
        return redirect("/hris/employee")

    db = get_db()
    employee = _get_employee_by_id(db, employee_id)
    if not employee:
        flash("Data karyawan tidak ditemukan", "error")
        return redirect("/hris/employee")

    employee_code = (request.form.get("employee_code") or "").strip().upper()
    full_name = (request.form.get("full_name") or "").strip()
    department = (request.form.get("department") or "").strip()
    position = (request.form.get("position") or "").strip()
    employment_status = _normalize_status(request.form.get("employment_status"))
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    join_date = (request.form.get("join_date") or "").strip()
    work_location = (request.form.get("work_location") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not employee_code or not full_name:
        flash("Employee code dan nama lengkap wajib diisi", "error")
        return redirect("/hris/employee")

    if warehouse_id is None:
        flash("Gudang kerja wajib diisi", "error")
        return redirect("/hris/employee")

    duplicate = db.execute(
        "SELECT id FROM employees WHERE employee_code=? AND id<>?",
        (employee_code, employee_id),
    ).fetchone()
    if duplicate:
        flash("Employee code sudah digunakan oleh karyawan lain", "error")
        return redirect("/hris/employee")

    db.execute(
        """
        UPDATE employees
        SET employee_code=?,
            full_name=?,
            warehouse_id=?,
            department=?,
            position=?,
            employment_status=?,
            phone=?,
            email=?,
            join_date=?,
            work_location=?,
            notes=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (
            employee_code,
            full_name,
            warehouse_id,
            department or None,
            position or None,
            employment_status,
            phone or None,
            email or None,
            join_date or None,
            work_location or None,
            notes or None,
            employee_id,
        ),
    )
    db.commit()

    flash("Data karyawan berhasil diupdate", "success")
    return redirect("/hris/employee")


@hris_bp.route("/employee/delete/<int:employee_id>", methods=["POST"])
def delete_employee(employee_id):
    if not can_manage_employee_records():
        flash("Tidak punya akses untuk mengelola data karyawan", "error")
        return redirect("/hris/employee")

    db = get_db()
    employee = _get_employee_by_id(db, employee_id)
    if not employee:
        flash("Data karyawan tidak ditemukan", "error")
        return redirect("/hris/employee")

    db.execute("DELETE FROM employees WHERE id=?", (employee_id,))
    db.commit()

    flash("Data karyawan berhasil dihapus", "success")
    return redirect("/hris/employee")


@hris_bp.route("/attendance/add", methods=["POST"])
def add_attendance():
    if not can_manage_attendance_records():
        flash("Tidak punya akses untuk mengelola attendance", "error")
        return redirect("/hris/attendance")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()
    check_in = (request.form.get("check_in") or "").strip()
    check_out = (request.form.get("check_out") or "").strip()
    status = _normalize_attendance_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/attendance")

    if not attendance_date:
        flash("Tanggal attendance wajib diisi", "error")
        return redirect("/hris/attendance")

    duplicate = db.execute(
        "SELECT id FROM attendance_records WHERE employee_id=? AND attendance_date=?",
        (employee_id, attendance_date),
    ).fetchone()
    if duplicate:
        flash("Attendance untuk tanggal tersebut sudah ada", "error")
        return redirect("/hris/attendance")

    db.execute(
        """
        INSERT INTO attendance_records(
            employee_id,
            warehouse_id,
            attendance_date,
            check_in,
            check_out,
            status,
            note,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            employee_id,
            employee["warehouse_id"],
            attendance_date,
            check_in or None,
            check_out or None,
            status,
            note or None,
        ),
    )
    db.commit()

    flash("Data attendance berhasil ditambahkan", "success")
    return redirect("/hris/attendance")


@hris_bp.route("/attendance/update/<int:attendance_id>", methods=["POST"])
def update_attendance(attendance_id):
    if not can_manage_attendance_records():
        flash("Tidak punya akses untuk mengelola attendance", "error")
        return redirect("/hris/attendance")

    db = get_db()
    attendance = _get_attendance_by_id(db, attendance_id)
    if not attendance:
        flash("Data attendance tidak ditemukan", "error")
        return redirect("/hris/attendance")

    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()
    check_in = (request.form.get("check_in") or "").strip()
    check_out = (request.form.get("check_out") or "").strip()
    status = _normalize_attendance_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/attendance")

    if not attendance_date:
        flash("Tanggal attendance wajib diisi", "error")
        return redirect("/hris/attendance")

    duplicate = db.execute(
        "SELECT id FROM attendance_records WHERE employee_id=? AND attendance_date=? AND id<>?",
        (employee_id, attendance_date, attendance_id),
    ).fetchone()
    if duplicate:
        flash("Attendance untuk tanggal tersebut sudah digunakan record lain", "error")
        return redirect("/hris/attendance")

    db.execute(
        """
        UPDATE attendance_records
        SET employee_id=?,
            warehouse_id=?,
            attendance_date=?,
            check_in=?,
            check_out=?,
            status=?,
            note=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            attendance_date,
            check_in or None,
            check_out or None,
            status,
            note or None,
            attendance_id,
        ),
    )
    db.commit()

    flash("Data attendance berhasil diupdate", "success")
    return redirect("/hris/attendance")


@hris_bp.route("/attendance/delete/<int:attendance_id>", methods=["POST"])
def delete_attendance(attendance_id):
    if not can_manage_attendance_records():
        flash("Tidak punya akses untuk mengelola attendance", "error")
        return redirect("/hris/attendance")

    db = get_db()
    attendance = _get_attendance_by_id(db, attendance_id)
    if not attendance:
        flash("Data attendance tidak ditemukan", "error")
        return redirect("/hris/attendance")

    db.execute("DELETE FROM attendance_records WHERE id=?", (attendance_id,))
    db.commit()

    flash("Data attendance berhasil dihapus", "success")
    return redirect("/hris/attendance")


@hris_bp.route("/leave/add", methods=["POST"])
def add_leave():
    if not can_manage_leave_records():
        flash("Tidak punya akses untuk mengelola leave", "error")
        return redirect("/hris/leave")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    leave_type = _normalize_leave_type(request.form.get("leave_type"))
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    status = _normalize_leave_status(request.form.get("status"))
    reason = (request.form.get("reason") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/leave")

    total_days = _calculate_leave_days(start_date, end_date)
    if total_days is None:
        flash("Rentang tanggal leave tidak valid", "error")
        return redirect("/hris/leave")

    if not reason:
        flash("Alasan leave wajib diisi", "error")
        return redirect("/hris/leave")

    duplicate = db.execute(
        """
        SELECT id
        FROM leave_requests
        WHERE employee_id=? AND leave_type=? AND start_date=? AND end_date=? AND status<>?
        """,
        (employee_id, leave_type, start_date, end_date, "cancelled"),
    ).fetchone()
    if duplicate:
        flash("Leave request serupa sudah ada", "error")
        return redirect("/hris/leave")

    handled_by, handled_at = _build_leave_handling(status)

    db.execute(
        """
        INSERT INTO leave_requests(
            employee_id,
            warehouse_id,
            leave_type,
            start_date,
            end_date,
            total_days,
            status,
            reason,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            leave_type,
            start_date,
            end_date,
            total_days,
            status,
            reason,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Leave request berhasil ditambahkan", "success")
    return redirect("/hris/leave")


@hris_bp.route("/leave/update/<int:leave_id>", methods=["POST"])
def update_leave(leave_id):
    if not can_manage_leave_records():
        flash("Tidak punya akses untuk mengelola leave", "error")
        return redirect("/hris/leave")

    db = get_db()
    leave_request = _get_leave_request_by_id(db, leave_id)
    if not leave_request:
        flash("Leave request tidak ditemukan", "error")
        return redirect("/hris/leave")

    employee_id = _to_int(request.form.get("employee_id"))
    leave_type = _normalize_leave_type(request.form.get("leave_type"))
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    status = _normalize_leave_status(request.form.get("status"))
    reason = (request.form.get("reason") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/leave")

    total_days = _calculate_leave_days(start_date, end_date)
    if total_days is None:
        flash("Rentang tanggal leave tidak valid", "error")
        return redirect("/hris/leave")

    if not reason:
        flash("Alasan leave wajib diisi", "error")
        return redirect("/hris/leave")

    duplicate = db.execute(
        """
        SELECT id
        FROM leave_requests
        WHERE employee_id=? AND leave_type=? AND start_date=? AND end_date=? AND status<>? AND id<>?
        """,
        (employee_id, leave_type, start_date, end_date, "cancelled", leave_id),
    ).fetchone()
    if duplicate:
        flash("Leave request serupa sudah digunakan record lain", "error")
        return redirect("/hris/leave")

    handled_by, handled_at = _build_leave_handling(status)

    db.execute(
        """
        UPDATE leave_requests
        SET employee_id=?,
            warehouse_id=?,
            leave_type=?,
            start_date=?,
            end_date=?,
            total_days=?,
            status=?,
            reason=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            leave_type,
            start_date,
            end_date,
            total_days,
            status,
            reason,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            leave_id,
        ),
    )
    db.commit()

    flash("Leave request berhasil diupdate", "success")
    return redirect("/hris/leave")


@hris_bp.route("/leave/delete/<int:leave_id>", methods=["POST"])
def delete_leave(leave_id):
    if not can_manage_leave_records():
        flash("Tidak punya akses untuk mengelola leave", "error")
        return redirect("/hris/leave")

    db = get_db()
    leave_request = _get_leave_request_by_id(db, leave_id)
    if not leave_request:
        flash("Leave request tidak ditemukan", "error")
        return redirect("/hris/leave")

    db.execute("DELETE FROM leave_requests WHERE id=?", (leave_id,))
    db.commit()

    flash("Leave request berhasil dihapus", "success")
    return redirect("/hris/leave")


@hris_bp.route("/payroll/add", methods=["POST"])
def add_payroll():
    if not can_manage_payroll_records():
        flash("Tidak punya akses untuk mengelola payroll", "error")
        return redirect("/hris/payroll")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    period_month = _to_int(request.form.get("period_month"))
    period_year = _to_int(request.form.get("period_year"))
    base_salary = _to_float(request.form.get("base_salary"))
    allowance = _to_float(request.form.get("allowance"))
    overtime_pay = _to_float(request.form.get("overtime_pay"))
    deduction = _to_float(request.form.get("deduction"))
    leave_deduction = _to_float(request.form.get("leave_deduction"))
    status = _normalize_payroll_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/payroll")

    if period_month is None or period_month < 1 or period_month > 12:
        flash("Periode bulan payroll tidak valid", "error")
        return redirect("/hris/payroll")

    if period_year is None or period_year < 2000 or period_year > 2100:
        flash("Periode tahun payroll tidak valid", "error")
        return redirect("/hris/payroll")

    duplicate = db.execute(
        "SELECT id FROM payroll_runs WHERE employee_id=? AND period_month=? AND period_year=?",
        (employee_id, period_month, period_year),
    ).fetchone()
    if duplicate:
        flash("Payroll untuk periode tersebut sudah ada", "error")
        return redirect("/hris/payroll")

    net_pay = _calculate_net_pay(base_salary, allowance, overtime_pay, deduction, leave_deduction)
    handled_by, handled_at = _build_payroll_handling(status)

    db.execute(
        """
        INSERT INTO payroll_runs(
            employee_id,
            warehouse_id,
            period_month,
            period_year,
            base_salary,
            allowance,
            overtime_pay,
            deduction,
            leave_deduction,
            net_pay,
            status,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            period_month,
            period_year,
            base_salary,
            allowance,
            overtime_pay,
            deduction,
            leave_deduction,
            net_pay,
            status,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Payroll berhasil ditambahkan", "success")
    return redirect("/hris/payroll")


@hris_bp.route("/payroll/update/<int:payroll_id>", methods=["POST"])
def update_payroll(payroll_id):
    if not can_manage_payroll_records():
        flash("Tidak punya akses untuk mengelola payroll", "error")
        return redirect("/hris/payroll")

    db = get_db()
    payroll = _get_payroll_by_id(db, payroll_id)
    if not payroll:
        flash("Data payroll tidak ditemukan", "error")
        return redirect("/hris/payroll")

    employee_id = _to_int(request.form.get("employee_id"))
    period_month = _to_int(request.form.get("period_month"))
    period_year = _to_int(request.form.get("period_year"))
    base_salary = _to_float(request.form.get("base_salary"))
    allowance = _to_float(request.form.get("allowance"))
    overtime_pay = _to_float(request.form.get("overtime_pay"))
    deduction = _to_float(request.form.get("deduction"))
    leave_deduction = _to_float(request.form.get("leave_deduction"))
    status = _normalize_payroll_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/payroll")

    if period_month is None or period_month < 1 or period_month > 12:
        flash("Periode bulan payroll tidak valid", "error")
        return redirect("/hris/payroll")

    if period_year is None or period_year < 2000 or period_year > 2100:
        flash("Periode tahun payroll tidak valid", "error")
        return redirect("/hris/payroll")

    duplicate = db.execute(
        "SELECT id FROM payroll_runs WHERE employee_id=? AND period_month=? AND period_year=? AND id<>?",
        (employee_id, period_month, period_year, payroll_id),
    ).fetchone()
    if duplicate:
        flash("Payroll untuk periode tersebut sudah digunakan record lain", "error")
        return redirect("/hris/payroll")

    net_pay = _calculate_net_pay(base_salary, allowance, overtime_pay, deduction, leave_deduction)
    handled_by, handled_at = _build_payroll_handling(status)

    db.execute(
        """
        UPDATE payroll_runs
        SET employee_id=?,
            warehouse_id=?,
            period_month=?,
            period_year=?,
            base_salary=?,
            allowance=?,
            overtime_pay=?,
            deduction=?,
            leave_deduction=?,
            net_pay=?,
            status=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            period_month,
            period_year,
            base_salary,
            allowance,
            overtime_pay,
            deduction,
            leave_deduction,
            net_pay,
            status,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            payroll_id,
        ),
    )
    db.commit()

    flash("Payroll berhasil diupdate", "success")
    return redirect("/hris/payroll")


@hris_bp.route("/payroll/delete/<int:payroll_id>", methods=["POST"])
def delete_payroll(payroll_id):
    if not can_manage_payroll_records():
        flash("Tidak punya akses untuk mengelola payroll", "error")
        return redirect("/hris/payroll")

    db = get_db()
    payroll = _get_payroll_by_id(db, payroll_id)
    if not payroll:
        flash("Data payroll tidak ditemukan", "error")
        return redirect("/hris/payroll")

    db.execute("DELETE FROM payroll_runs WHERE id=?", (payroll_id,))
    db.commit()

    flash("Payroll berhasil dihapus", "success")
    return redirect("/hris/payroll")


@hris_bp.route("/recruitment/add", methods=["POST"])
def add_recruitment():
    if not can_manage_recruitment_records():
        flash("Tidak punya akses untuk mengelola recruitment", "error")
        return redirect("/hris/recruitment")

    db = get_db()
    candidate_name = (request.form.get("candidate_name") or "").strip()
    position_title = (request.form.get("position_title") or "").strip()
    department = (request.form.get("department") or "").strip()
    stage = _normalize_recruitment_stage(request.form.get("stage"))
    status = _normalize_recruitment_status(request.form.get("status"))
    source = (request.form.get("source") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    expected_join_date = (request.form.get("expected_join_date") or "").strip()
    note = (request.form.get("note") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not candidate_name or not position_title:
        flash("Nama kandidat dan posisi wajib diisi", "error")
        return redirect("/hris/recruitment")

    if warehouse_id is None:
        flash("Gudang hiring wajib diisi", "error")
        return redirect("/hris/recruitment")

    handled_by, handled_at = _build_recruitment_handling(status)

    db.execute(
        """
        INSERT INTO recruitment_candidates(
            candidate_name,
            warehouse_id,
            position_title,
            department,
            stage,
            status,
            source,
            phone,
            email,
            expected_join_date,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            candidate_name,
            warehouse_id,
            position_title,
            department or None,
            stage,
            status,
            source or None,
            phone or None,
            email or None,
            expected_join_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Kandidat recruitment berhasil ditambahkan", "success")
    return redirect("/hris/recruitment")


@hris_bp.route("/recruitment/update/<int:candidate_id>", methods=["POST"])
def update_recruitment(candidate_id):
    if not can_manage_recruitment_records():
        flash("Tidak punya akses untuk mengelola recruitment", "error")
        return redirect("/hris/recruitment")

    db = get_db()
    candidate = _get_recruitment_candidate_by_id(db, candidate_id)
    if not candidate:
        flash("Data recruitment tidak ditemukan", "error")
        return redirect("/hris/recruitment")

    candidate_name = (request.form.get("candidate_name") or "").strip()
    position_title = (request.form.get("position_title") or "").strip()
    department = (request.form.get("department") or "").strip()
    stage = _normalize_recruitment_stage(request.form.get("stage"))
    status = _normalize_recruitment_status(request.form.get("status"))
    source = (request.form.get("source") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    expected_join_date = (request.form.get("expected_join_date") or "").strip()
    note = (request.form.get("note") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not candidate_name or not position_title:
        flash("Nama kandidat dan posisi wajib diisi", "error")
        return redirect("/hris/recruitment")

    if warehouse_id is None:
        flash("Gudang hiring wajib diisi", "error")
        return redirect("/hris/recruitment")

    handled_by, handled_at = _build_recruitment_handling(status)

    db.execute(
        """
        UPDATE recruitment_candidates
        SET candidate_name=?,
            warehouse_id=?,
            position_title=?,
            department=?,
            stage=?,
            status=?,
            source=?,
            phone=?,
            email=?,
            expected_join_date=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            candidate_name,
            warehouse_id,
            position_title,
            department or None,
            stage,
            status,
            source or None,
            phone or None,
            email or None,
            expected_join_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            candidate_id,
        ),
    )
    db.commit()

    flash("Kandidat recruitment berhasil diupdate", "success")
    return redirect("/hris/recruitment")


@hris_bp.route("/recruitment/delete/<int:candidate_id>", methods=["POST"])
def delete_recruitment(candidate_id):
    if not can_manage_recruitment_records():
        flash("Tidak punya akses untuk mengelola recruitment", "error")
        return redirect("/hris/recruitment")

    db = get_db()
    candidate = _get_recruitment_candidate_by_id(db, candidate_id)
    if not candidate:
        flash("Data recruitment tidak ditemukan", "error")
        return redirect("/hris/recruitment")

    db.execute("DELETE FROM recruitment_candidates WHERE id=?", (candidate_id,))
    db.commit()

    flash("Kandidat recruitment berhasil dihapus", "success")
    return redirect("/hris/recruitment")


@hris_bp.route("/onboarding/add", methods=["POST"])
def add_onboarding():
    if not can_manage_onboarding_records():
        flash("Tidak punya akses untuk mengelola onboarding", "error")
        return redirect("/hris/onboarding")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    start_date = (request.form.get("start_date") or "").strip()
    target_date = (request.form.get("target_date") or "").strip()
    stage = _normalize_onboarding_stage(request.form.get("stage"))
    status = _normalize_onboarding_status(request.form.get("status"))
    buddy_name = (request.form.get("buddy_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/onboarding")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    if target_date and _calculate_leave_days(start_date, target_date) is None:
        flash("Rentang tanggal onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    duplicate = db.execute(
        "SELECT id FROM onboarding_records WHERE employee_id=?",
        (employee_id,),
    ).fetchone()
    if duplicate:
        flash("Onboarding untuk karyawan ini sudah ada", "error")
        return redirect("/hris/onboarding")

    handled_by, handled_at = _build_onboarding_handling(status)

    db.execute(
        """
        INSERT INTO onboarding_records(
            employee_id,
            warehouse_id,
            start_date,
            target_date,
            stage,
            status,
            buddy_name,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            start_date,
            target_date or None,
            stage,
            status,
            buddy_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Onboarding berhasil ditambahkan", "success")
    return redirect("/hris/onboarding")


@hris_bp.route("/onboarding/update/<int:onboarding_id>", methods=["POST"])
def update_onboarding(onboarding_id):
    if not can_manage_onboarding_records():
        flash("Tidak punya akses untuk mengelola onboarding", "error")
        return redirect("/hris/onboarding")

    db = get_db()
    onboarding = _get_onboarding_by_id(db, onboarding_id)
    if not onboarding:
        flash("Data onboarding tidak ditemukan", "error")
        return redirect("/hris/onboarding")

    employee_id = _to_int(request.form.get("employee_id"))
    start_date = (request.form.get("start_date") or "").strip()
    target_date = (request.form.get("target_date") or "").strip()
    stage = _normalize_onboarding_stage(request.form.get("stage"))
    status = _normalize_onboarding_status(request.form.get("status"))
    buddy_name = (request.form.get("buddy_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/onboarding")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    if target_date and _calculate_leave_days(start_date, target_date) is None:
        flash("Rentang tanggal onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    duplicate = db.execute(
        "SELECT id FROM onboarding_records WHERE employee_id=? AND id<>?",
        (employee_id, onboarding_id),
    ).fetchone()
    if duplicate:
        flash("Onboarding untuk karyawan ini sudah digunakan record lain", "error")
        return redirect("/hris/onboarding")

    handled_by, handled_at = _build_onboarding_handling(status)

    db.execute(
        """
        UPDATE onboarding_records
        SET employee_id=?,
            warehouse_id=?,
            start_date=?,
            target_date=?,
            stage=?,
            status=?,
            buddy_name=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            start_date,
            target_date or None,
            stage,
            status,
            buddy_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            onboarding_id,
        ),
    )
    db.commit()

    flash("Onboarding berhasil diupdate", "success")
    return redirect("/hris/onboarding")


@hris_bp.route("/onboarding/delete/<int:onboarding_id>", methods=["POST"])
def delete_onboarding(onboarding_id):
    if not can_manage_onboarding_records():
        flash("Tidak punya akses untuk mengelola onboarding", "error")
        return redirect("/hris/onboarding")

    db = get_db()
    onboarding = _get_onboarding_by_id(db, onboarding_id)
    if not onboarding:
        flash("Data onboarding tidak ditemukan", "error")
        return redirect("/hris/onboarding")

    db.execute("DELETE FROM onboarding_records WHERE id=?", (onboarding_id,))
    db.commit()

    flash("Onboarding berhasil dihapus", "success")
    return redirect("/hris/onboarding")


@hris_bp.route("/offboarding/add", methods=["POST"])
def add_offboarding():
    if not can_manage_offboarding_records():
        flash("Tidak punya akses untuk mengelola offboarding", "error")
        return redirect("/hris/offboarding")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    notice_date = (request.form.get("notice_date") or "").strip()
    last_working_date = (request.form.get("last_working_date") or "").strip()
    stage = _normalize_offboarding_stage(request.form.get("stage"))
    status = _normalize_offboarding_status(request.form.get("status"))
    exit_reason = (request.form.get("exit_reason") or "").strip()
    handover_pic = (request.form.get("handover_pic") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/offboarding")

    if _calculate_leave_days(notice_date, notice_date) is None:
        flash("Tanggal notice offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    if last_working_date and _calculate_leave_days(notice_date, last_working_date) is None:
        flash("Rentang tanggal offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    duplicate = db.execute(
        "SELECT id FROM offboarding_records WHERE employee_id=?",
        (employee_id,),
    ).fetchone()
    if duplicate:
        flash("Offboarding untuk karyawan ini sudah ada", "error")
        return redirect("/hris/offboarding")

    handled_by, handled_at = _build_offboarding_handling(status)

    db.execute(
        """
        INSERT INTO offboarding_records(
            employee_id,
            warehouse_id,
            notice_date,
            last_working_date,
            stage,
            status,
            exit_reason,
            handover_pic,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            notice_date,
            last_working_date or None,
            stage,
            status,
            exit_reason or None,
            handover_pic or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Offboarding berhasil ditambahkan", "success")
    return redirect("/hris/offboarding")


@hris_bp.route("/offboarding/update/<int:offboarding_id>", methods=["POST"])
def update_offboarding(offboarding_id):
    if not can_manage_offboarding_records():
        flash("Tidak punya akses untuk mengelola offboarding", "error")
        return redirect("/hris/offboarding")

    db = get_db()
    offboarding = _get_offboarding_by_id(db, offboarding_id)
    if not offboarding:
        flash("Data offboarding tidak ditemukan", "error")
        return redirect("/hris/offboarding")

    employee_id = _to_int(request.form.get("employee_id"))
    notice_date = (request.form.get("notice_date") or "").strip()
    last_working_date = (request.form.get("last_working_date") or "").strip()
    stage = _normalize_offboarding_stage(request.form.get("stage"))
    status = _normalize_offboarding_status(request.form.get("status"))
    exit_reason = (request.form.get("exit_reason") or "").strip()
    handover_pic = (request.form.get("handover_pic") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/offboarding")

    if _calculate_leave_days(notice_date, notice_date) is None:
        flash("Tanggal notice offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    if last_working_date and _calculate_leave_days(notice_date, last_working_date) is None:
        flash("Rentang tanggal offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    duplicate = db.execute(
        "SELECT id FROM offboarding_records WHERE employee_id=? AND id<>?",
        (employee_id, offboarding_id),
    ).fetchone()
    if duplicate:
        flash("Offboarding untuk karyawan ini sudah digunakan record lain", "error")
        return redirect("/hris/offboarding")

    handled_by, handled_at = _build_offboarding_handling(status)

    db.execute(
        """
        UPDATE offboarding_records
        SET employee_id=?,
            warehouse_id=?,
            notice_date=?,
            last_working_date=?,
            stage=?,
            status=?,
            exit_reason=?,
            handover_pic=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            notice_date,
            last_working_date or None,
            stage,
            status,
            exit_reason or None,
            handover_pic or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            offboarding_id,
        ),
    )
    db.commit()

    flash("Offboarding berhasil diupdate", "success")
    return redirect("/hris/offboarding")


@hris_bp.route("/offboarding/delete/<int:offboarding_id>", methods=["POST"])
def delete_offboarding(offboarding_id):
    if not can_manage_offboarding_records():
        flash("Tidak punya akses untuk mengelola offboarding", "error")
        return redirect("/hris/offboarding")

    db = get_db()
    offboarding = _get_offboarding_by_id(db, offboarding_id)
    if not offboarding:
        flash("Data offboarding tidak ditemukan", "error")
        return redirect("/hris/offboarding")

    db.execute("DELETE FROM offboarding_records WHERE id=?", (offboarding_id,))
    db.commit()

    flash("Offboarding berhasil dihapus", "success")
    return redirect("/hris/offboarding")


@hris_bp.route("/performance/add", methods=["POST"])
def add_performance():
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola performance", "error")
        return redirect("/hris/pms")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    review_period = (request.form.get("review_period") or "").strip()
    goal_score = _to_float(request.form.get("goal_score"))
    discipline_score = _to_float(request.form.get("discipline_score"))
    teamwork_score = _to_float(request.form.get("teamwork_score"))
    status = _normalize_performance_status(request.form.get("status"))
    reviewer_name = (request.form.get("reviewer_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/pms")

    if not review_period:
        flash("Periode review wajib diisi", "error")
        return redirect("/hris/pms")

    duplicate = db.execute(
        "SELECT id FROM performance_reviews WHERE employee_id=? AND review_period=?",
        (employee_id, review_period),
    ).fetchone()
    if duplicate:
        flash("Performance review untuk periode tersebut sudah ada", "error")
        return redirect("/hris/pms")

    final_score = _calculate_performance_score(goal_score, discipline_score, teamwork_score)
    rating = _derive_performance_rating(final_score)
    handled_by, handled_at = _build_performance_handling(status)

    db.execute(
        """
        INSERT INTO performance_reviews(
            employee_id,
            warehouse_id,
            review_period,
            goal_score,
            discipline_score,
            teamwork_score,
            final_score,
            rating,
            status,
            reviewer_name,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            review_period,
            goal_score,
            discipline_score,
            teamwork_score,
            final_score,
            rating,
            status,
            reviewer_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Performance review berhasil ditambahkan", "success")
    return redirect("/hris/pms")


@hris_bp.route("/performance/update/<int:review_id>", methods=["POST"])
def update_performance(review_id):
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola performance", "error")
        return redirect("/hris/pms")

    db = get_db()
    review = _get_performance_by_id(db, review_id)
    if not review:
        flash("Data performance tidak ditemukan", "error")
        return redirect("/hris/pms")

    employee_id = _to_int(request.form.get("employee_id"))
    review_period = (request.form.get("review_period") or "").strip()
    goal_score = _to_float(request.form.get("goal_score"))
    discipline_score = _to_float(request.form.get("discipline_score"))
    teamwork_score = _to_float(request.form.get("teamwork_score"))
    status = _normalize_performance_status(request.form.get("status"))
    reviewer_name = (request.form.get("reviewer_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/pms")

    if not review_period:
        flash("Periode review wajib diisi", "error")
        return redirect("/hris/pms")

    duplicate = db.execute(
        "SELECT id FROM performance_reviews WHERE employee_id=? AND review_period=? AND id<>?",
        (employee_id, review_period, review_id),
    ).fetchone()
    if duplicate:
        flash("Performance review untuk periode tersebut sudah digunakan record lain", "error")
        return redirect("/hris/pms")

    final_score = _calculate_performance_score(goal_score, discipline_score, teamwork_score)
    rating = _derive_performance_rating(final_score)
    handled_by, handled_at = _build_performance_handling(status)

    db.execute(
        """
        UPDATE performance_reviews
        SET employee_id=?,
            warehouse_id=?,
            review_period=?,
            goal_score=?,
            discipline_score=?,
            teamwork_score=?,
            final_score=?,
            rating=?,
            status=?,
            reviewer_name=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            review_period,
            goal_score,
            discipline_score,
            teamwork_score,
            final_score,
            rating,
            status,
            reviewer_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            review_id,
        ),
    )
    db.commit()

    flash("Performance review berhasil diupdate", "success")
    return redirect("/hris/pms")


@hris_bp.route("/performance/delete/<int:review_id>", methods=["POST"])
def delete_performance(review_id):
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola performance", "error")
        return redirect("/hris/pms")

    db = get_db()
    review = _get_performance_by_id(db, review_id)
    if not review:
        flash("Data performance tidak ditemukan", "error")
        return redirect("/hris/pms")

    db.execute("DELETE FROM performance_reviews WHERE id=?", (review_id,))
    db.commit()

    flash("Performance review berhasil dihapus", "success")
    return redirect("/hris/pms")


@hris_bp.route("/helpdesk/add", methods=["POST"])
def add_helpdesk():
    if not can_manage_helpdesk_records():
        flash("Tidak punya akses untuk mengelola helpdesk", "error")
        return redirect("/hris/helpdesk")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    ticket_title = (request.form.get("ticket_title") or "").strip()
    category = _normalize_helpdesk_category(request.form.get("category"))
    priority = _normalize_helpdesk_priority(request.form.get("priority"))
    status = _normalize_helpdesk_status(request.form.get("status"))
    channel = (request.form.get("channel") or "").strip()
    assigned_to = (request.form.get("assigned_to") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/helpdesk")

    if not ticket_title:
        flash("Judul ticket wajib diisi", "error")
        return redirect("/hris/helpdesk")

    handled_by, handled_at = _build_helpdesk_handling(status)

    db.execute(
        """
        INSERT INTO helpdesk_tickets(
            employee_id,
            warehouse_id,
            ticket_title,
            category,
            priority,
            status,
            channel,
            assigned_to,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            ticket_title,
            category,
            priority,
            status,
            channel or None,
            assigned_to or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Ticket helpdesk berhasil ditambahkan", "success")
    return redirect("/hris/helpdesk")


@hris_bp.route("/helpdesk/update/<int:ticket_id>", methods=["POST"])
def update_helpdesk(ticket_id):
    if not can_manage_helpdesk_records():
        flash("Tidak punya akses untuk mengelola helpdesk", "error")
        return redirect("/hris/helpdesk")

    db = get_db()
    ticket = _get_helpdesk_ticket_by_id(db, ticket_id)
    if not ticket:
        flash("Ticket helpdesk tidak ditemukan", "error")
        return redirect("/hris/helpdesk")

    employee_id = _to_int(request.form.get("employee_id"))
    ticket_title = (request.form.get("ticket_title") or "").strip()
    category = _normalize_helpdesk_category(request.form.get("category"))
    priority = _normalize_helpdesk_priority(request.form.get("priority"))
    status = _normalize_helpdesk_status(request.form.get("status"))
    channel = (request.form.get("channel") or "").strip()
    assigned_to = (request.form.get("assigned_to") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/helpdesk")

    if not ticket_title:
        flash("Judul ticket wajib diisi", "error")
        return redirect("/hris/helpdesk")

    handled_by, handled_at = _build_helpdesk_handling(status)

    db.execute(
        """
        UPDATE helpdesk_tickets
        SET employee_id=?,
            warehouse_id=?,
            ticket_title=?,
            category=?,
            priority=?,
            status=?,
            channel=?,
            assigned_to=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            ticket_title,
            category,
            priority,
            status,
            channel or None,
            assigned_to or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            ticket_id,
        ),
    )
    db.commit()

    flash("Ticket helpdesk berhasil diupdate", "success")
    return redirect("/hris/helpdesk")


@hris_bp.route("/helpdesk/delete/<int:ticket_id>", methods=["POST"])
def delete_helpdesk(ticket_id):
    if not can_manage_helpdesk_records():
        flash("Tidak punya akses untuk mengelola helpdesk", "error")
        return redirect("/hris/helpdesk")

    db = get_db()
    ticket = _get_helpdesk_ticket_by_id(db, ticket_id)
    if not ticket:
        flash("Ticket helpdesk tidak ditemukan", "error")
        return redirect("/hris/helpdesk")

    db.execute("DELETE FROM helpdesk_tickets WHERE id=?", (ticket_id,))
    db.commit()

    flash("Ticket helpdesk berhasil dihapus", "success")
    return redirect("/hris/helpdesk")


@hris_bp.route("/asset/add", methods=["POST"])
def add_asset():
    if not can_manage_asset_records():
        flash("Tidak punya akses untuk mengelola asset", "error")
        return redirect("/hris/asset")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    asset_name = (request.form.get("asset_name") or "").strip()
    asset_code = (request.form.get("asset_code") or "").strip().upper()
    serial_number = (request.form.get("serial_number") or "").strip()
    category = (request.form.get("category") or "").strip()
    asset_status = _normalize_asset_status(request.form.get("asset_status"))
    condition_status = _normalize_asset_condition(request.form.get("condition_status"))
    assigned_date = (request.form.get("assigned_date") or "").strip()
    return_date = (request.form.get("return_date") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/asset")

    if not asset_name or not asset_code or not assigned_date:
        flash("Nama asset, kode asset, dan tanggal assign wajib diisi", "error")
        return redirect("/hris/asset")

    if _calculate_leave_days(assigned_date, assigned_date) is None:
        flash("Tanggal assign asset tidak valid", "error")
        return redirect("/hris/asset")

    if return_date and _calculate_leave_days(assigned_date, return_date) is None:
        flash("Rentang tanggal asset tidak valid", "error")
        return redirect("/hris/asset")

    duplicate = db.execute(
        "SELECT id FROM asset_records WHERE asset_code=?",
        (asset_code,),
    ).fetchone()
    if duplicate:
        flash("Kode asset sudah digunakan", "error")
        return redirect("/hris/asset")

    handled_by, handled_at = _build_asset_handling(asset_status)

    db.execute(
        """
        INSERT INTO asset_records(
            employee_id,
            warehouse_id,
            asset_name,
            asset_code,
            serial_number,
            category,
            asset_status,
            condition_status,
            assigned_date,
            return_date,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            asset_name,
            asset_code,
            serial_number or None,
            category or None,
            asset_status,
            condition_status,
            assigned_date,
            return_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Asset record berhasil ditambahkan", "success")
    return redirect("/hris/asset")


@hris_bp.route("/asset/update/<int:asset_id>", methods=["POST"])
def update_asset(asset_id):
    if not can_manage_asset_records():
        flash("Tidak punya akses untuk mengelola asset", "error")
        return redirect("/hris/asset")

    db = get_db()
    asset = _get_asset_record_by_id(db, asset_id)
    if not asset:
        flash("Asset record tidak ditemukan", "error")
        return redirect("/hris/asset")

    employee_id = _to_int(request.form.get("employee_id"))
    asset_name = (request.form.get("asset_name") or "").strip()
    asset_code = (request.form.get("asset_code") or "").strip().upper()
    serial_number = (request.form.get("serial_number") or "").strip()
    category = (request.form.get("category") or "").strip()
    asset_status = _normalize_asset_status(request.form.get("asset_status"))
    condition_status = _normalize_asset_condition(request.form.get("condition_status"))
    assigned_date = (request.form.get("assigned_date") or "").strip()
    return_date = (request.form.get("return_date") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/asset")

    if not asset_name or not asset_code or not assigned_date:
        flash("Nama asset, kode asset, dan tanggal assign wajib diisi", "error")
        return redirect("/hris/asset")

    if _calculate_leave_days(assigned_date, assigned_date) is None:
        flash("Tanggal assign asset tidak valid", "error")
        return redirect("/hris/asset")

    if return_date and _calculate_leave_days(assigned_date, return_date) is None:
        flash("Rentang tanggal asset tidak valid", "error")
        return redirect("/hris/asset")

    duplicate = db.execute(
        "SELECT id FROM asset_records WHERE asset_code=? AND id<>?",
        (asset_code, asset_id),
    ).fetchone()
    if duplicate:
        flash("Kode asset sudah digunakan record lain", "error")
        return redirect("/hris/asset")

    handled_by, handled_at = _build_asset_handling(asset_status)

    db.execute(
        """
        UPDATE asset_records
        SET employee_id=?,
            warehouse_id=?,
            asset_name=?,
            asset_code=?,
            serial_number=?,
            category=?,
            asset_status=?,
            condition_status=?,
            assigned_date=?,
            return_date=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            asset_name,
            asset_code,
            serial_number or None,
            category or None,
            asset_status,
            condition_status,
            assigned_date,
            return_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            asset_id,
        ),
    )
    db.commit()

    flash("Asset record berhasil diupdate", "success")
    return redirect("/hris/asset")


@hris_bp.route("/asset/delete/<int:asset_id>", methods=["POST"])
def delete_asset(asset_id):
    if not can_manage_asset_records():
        flash("Tidak punya akses untuk mengelola asset", "error")
        return redirect("/hris/asset")

    db = get_db()
    asset = _get_asset_record_by_id(db, asset_id)
    if not asset:
        flash("Asset record tidak ditemukan", "error")
        return redirect("/hris/asset")

    db.execute("DELETE FROM asset_records WHERE id=?", (asset_id,))
    db.commit()

    flash("Asset record berhasil dihapus", "success")
    return redirect("/hris/asset")


@hris_bp.route("/project/add", methods=["POST"])
def add_project():
    if not can_manage_project_records():
        flash("Tidak punya akses untuk mengelola project", "error")
        return redirect("/hris/project")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    project_name = (request.form.get("project_name") or "").strip()
    project_code = (request.form.get("project_code") or "").strip().upper()
    priority = _normalize_project_priority(request.form.get("priority"))
    status = _normalize_project_status(request.form.get("status"))
    start_date = (request.form.get("start_date") or "").strip()
    due_date = (request.form.get("due_date") or "").strip()
    progress_percent = max(0, min(100, _to_int(request.form.get("progress_percent"), 0) or 0))
    owner_name = (request.form.get("owner_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/project")

    if not project_name or not project_code or not start_date:
        flash("Nama project, kode project, dan start date wajib diisi", "error")
        return redirect("/hris/project")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai project tidak valid", "error")
        return redirect("/hris/project")

    if due_date and _calculate_leave_days(start_date, due_date) is None:
        flash("Rentang tanggal project tidak valid", "error")
        return redirect("/hris/project")

    duplicate = db.execute(
        "SELECT id FROM project_records WHERE project_code=?",
        (project_code,),
    ).fetchone()
    if duplicate:
        flash("Kode project sudah digunakan", "error")
        return redirect("/hris/project")

    handled_by, handled_at = _build_project_handling(status)
    db.execute(
        """
        INSERT INTO project_records(
            employee_id,
            warehouse_id,
            project_name,
            project_code,
            priority,
            status,
            start_date,
            due_date,
            progress_percent,
            owner_name,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            project_name,
            project_code,
            priority,
            status,
            start_date,
            due_date or None,
            progress_percent,
            owner_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Project berhasil ditambahkan", "success")
    return redirect("/hris/project")


@hris_bp.route("/project/update/<int:project_id>", methods=["POST"])
def update_project(project_id):
    if not can_manage_project_records():
        flash("Tidak punya akses untuk mengelola project", "error")
        return redirect("/hris/project")

    db = get_db()
    project = _get_project_by_id(db, project_id)
    if not project:
        flash("Project tidak ditemukan", "error")
        return redirect("/hris/project")

    employee_id = _to_int(request.form.get("employee_id"))
    project_name = (request.form.get("project_name") or "").strip()
    project_code = (request.form.get("project_code") or "").strip().upper()
    priority = _normalize_project_priority(request.form.get("priority"))
    status = _normalize_project_status(request.form.get("status"))
    start_date = (request.form.get("start_date") or "").strip()
    due_date = (request.form.get("due_date") or "").strip()
    progress_percent = max(0, min(100, _to_int(request.form.get("progress_percent"), 0) or 0))
    owner_name = (request.form.get("owner_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/project")

    if not project_name or not project_code or not start_date:
        flash("Nama project, kode project, dan start date wajib diisi", "error")
        return redirect("/hris/project")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai project tidak valid", "error")
        return redirect("/hris/project")

    if due_date and _calculate_leave_days(start_date, due_date) is None:
        flash("Rentang tanggal project tidak valid", "error")
        return redirect("/hris/project")

    duplicate = db.execute(
        "SELECT id FROM project_records WHERE project_code=? AND id<>?",
        (project_code, project_id),
    ).fetchone()
    if duplicate:
        flash("Kode project sudah digunakan record lain", "error")
        return redirect("/hris/project")

    handled_by, handled_at = _build_project_handling(status)
    db.execute(
        """
        UPDATE project_records
        SET employee_id=?,
            warehouse_id=?,
            project_name=?,
            project_code=?,
            priority=?,
            status=?,
            start_date=?,
            due_date=?,
            progress_percent=?,
            owner_name=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            project_name,
            project_code,
            priority,
            status,
            start_date,
            due_date or None,
            progress_percent,
            owner_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            project_id,
        ),
    )
    db.commit()

    flash("Project berhasil diupdate", "success")
    return redirect("/hris/project")


@hris_bp.route("/project/delete/<int:project_id>", methods=["POST"])
def delete_project(project_id):
    if not can_manage_project_records():
        flash("Tidak punya akses untuk mengelola project", "error")
        return redirect("/hris/project")

    db = get_db()
    project = _get_project_by_id(db, project_id)
    if not project:
        flash("Project tidak ditemukan", "error")
        return redirect("/hris/project")

    db.execute("DELETE FROM project_records WHERE id=?", (project_id,))
    db.commit()

    flash("Project berhasil dihapus", "success")
    return redirect("/hris/project")


@hris_bp.route("/biometric/add", methods=["POST"])
def add_biometric():
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk mengelola biometric", "error")
        return redirect("/hris/biometric")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    device_name = (request.form.get("device_name") or "").strip()
    device_user_id = (request.form.get("device_user_id") or "").strip()
    punch_time = _normalize_datetime_input(request.form.get("punch_time"))
    punch_type = _normalize_biometric_punch_type(request.form.get("punch_type"))
    sync_status = _normalize_biometric_sync_status(request.form.get("sync_status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/biometric")

    if not device_name or not punch_time:
        flash("Device name dan punch time wajib diisi", "error")
        return redirect("/hris/biometric")

    duplicate = db.execute(
        "SELECT id FROM biometric_logs WHERE employee_id=? AND punch_time=? AND punch_type=?",
        (employee_id, punch_time, punch_type),
    ).fetchone()
    if duplicate:
        flash("Log biometric dengan waktu dan tipe yang sama sudah ada", "error")
        return redirect("/hris/biometric")

    handled_by, handled_at = _build_biometric_handling(sync_status)
    db.execute(
        """
        INSERT INTO biometric_logs(
            employee_id,
            warehouse_id,
            device_name,
            device_user_id,
            punch_time,
            punch_type,
            sync_status,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            device_name,
            device_user_id or None,
            punch_time,
            punch_type,
            sync_status,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    _resync_attendance_from_biometrics(db, employee_id, employee["warehouse_id"], punch_time[:10])
    db.commit()

    flash("Log biometric berhasil ditambahkan", "success")
    return redirect("/hris/biometric")


@hris_bp.route("/biometric/update/<int:biometric_id>", methods=["POST"])
def update_biometric(biometric_id):
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk mengelola biometric", "error")
        return redirect("/hris/biometric")

    db = get_db()
    biometric = _get_biometric_log_by_id(db, biometric_id)
    if not biometric:
        flash("Log biometric tidak ditemukan", "error")
        return redirect("/hris/biometric")

    old_employee_id = biometric["employee_id"]
    old_warehouse_id = biometric["warehouse_id"]
    old_punch_date = (biometric["punch_time"] or "")[:10]

    employee_id = _to_int(request.form.get("employee_id"))
    device_name = (request.form.get("device_name") or "").strip()
    device_user_id = (request.form.get("device_user_id") or "").strip()
    punch_time = _normalize_datetime_input(request.form.get("punch_time"))
    punch_type = _normalize_biometric_punch_type(request.form.get("punch_type"))
    sync_status = _normalize_biometric_sync_status(request.form.get("sync_status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/biometric")

    if not device_name or not punch_time:
        flash("Device name dan punch time wajib diisi", "error")
        return redirect("/hris/biometric")

    duplicate = db.execute(
        "SELECT id FROM biometric_logs WHERE employee_id=? AND punch_time=? AND punch_type=? AND id<>?",
        (employee_id, punch_time, punch_type, biometric_id),
    ).fetchone()
    if duplicate:
        flash("Log biometric dengan waktu dan tipe yang sama sudah digunakan record lain", "error")
        return redirect("/hris/biometric")

    handled_by, handled_at = _build_biometric_handling(sync_status)
    db.execute(
        """
        UPDATE biometric_logs
        SET employee_id=?,
            warehouse_id=?,
            device_name=?,
            device_user_id=?,
            punch_time=?,
            punch_type=?,
            sync_status=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            device_name,
            device_user_id or None,
            punch_time,
            punch_type,
            sync_status,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            biometric_id,
        ),
    )

    _resync_attendance_from_biometrics(db, old_employee_id, old_warehouse_id, old_punch_date)
    _resync_attendance_from_biometrics(db, employee_id, employee["warehouse_id"], punch_time[:10])
    db.commit()

    flash("Log biometric berhasil diupdate", "success")
    return redirect("/hris/biometric")


@hris_bp.route("/biometric/delete/<int:biometric_id>", methods=["POST"])
def delete_biometric(biometric_id):
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk mengelola biometric", "error")
        return redirect("/hris/biometric")

    db = get_db()
    biometric = _get_biometric_log_by_id(db, biometric_id)
    if not biometric:
        flash("Log biometric tidak ditemukan", "error")
        return redirect("/hris/biometric")

    employee_id = biometric["employee_id"]
    warehouse_id = biometric["warehouse_id"]
    punch_date = (biometric["punch_time"] or "")[:10]

    db.execute("DELETE FROM biometric_logs WHERE id=?", (biometric_id,))
    _resync_attendance_from_biometrics(db, employee_id, warehouse_id, punch_date)
    db.commit()

    flash("Log biometric berhasil dihapus", "success")
    return redirect("/hris/biometric")
