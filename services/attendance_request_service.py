import json
from datetime import date as date_cls

from services.rbac import normalize_role


ATTENDANCE_REQUEST_TYPE_META = {
    "schedule_entry": {
        "label": "Perubahan Shift Jadwal",
        "category": "schedule",
    },
    "shift_swap": {
        "label": "Tukar Shift",
        "category": "schedule",
    },
    "overtime_add": {
        "label": "Penambahan Saldo Lembur",
        "category": "overtime",
    },
    "overtime_use": {
        "label": "Pemakaian / Utang Lembur",
        "category": "overtime",
    },
    "overtime_usage_delete": {
        "label": "Pembatalan Pemakaian Lembur",
        "category": "overtime",
    },
}

ATTENDANCE_REQUEST_STATUSES = {"pending", "approved", "rejected", "cancelled"}
ATTENDANCE_REQUEST_APPROVER_ROLES = {"hr", "super_admin"}


def normalize_attendance_request_type(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ATTENDANCE_REQUEST_TYPE_META else ""


def normalize_attendance_request_status(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ATTENDANCE_REQUEST_STATUSES else "pending"


def can_manage_attendance_request_approvals(role):
    return normalize_role(role) in ATTENDANCE_REQUEST_APPROVER_ROLES


def get_attendance_request_type_label(request_type):
    normalized = normalize_attendance_request_type(request_type)
    meta = ATTENDANCE_REQUEST_TYPE_META.get(normalized, {})
    return meta.get("label") or str(request_type or "").strip().replace("_", " ").title() or "Request Attendance"


def get_attendance_request_category(request_type):
    normalized = normalize_attendance_request_type(request_type)
    meta = ATTENDANCE_REQUEST_TYPE_META.get(normalized, {})
    return meta.get("category") or "attendance"


def parse_attendance_request_payload(raw_payload):
    if isinstance(raw_payload, dict):
        return raw_payload
    try:
        payload = json.loads(str(raw_payload or "").strip() or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def queue_attendance_request(
    db,
    *,
    request_type,
    warehouse_id,
    employee_id=0,
    requested_by=0,
    summary_title="",
    summary_note="",
    payload=None,
):
    normalized_type = normalize_attendance_request_type(request_type)
    if not normalized_type:
        raise ValueError("Tipe request attendance tidak valid.")

    safe_payload = payload if isinstance(payload, dict) else {}
    payload_json = json.dumps(safe_payload, sort_keys=True, ensure_ascii=True)
    safe_warehouse_id = int(warehouse_id or 0)
    safe_employee_id = int(employee_id or 0)
    safe_requested_by = int(requested_by or 0)
    safe_title = " ".join(str(summary_title or "").strip().split()) or get_attendance_request_type_label(normalized_type)
    safe_note = str(summary_note or "").strip()

    existing = db.execute(
        """
        SELECT id
        FROM attendance_action_requests
        WHERE request_type=?
          AND warehouse_id=?
          AND COALESCE(employee_id, 0)=?
          AND status='pending'
          AND COALESCE(payload, '')=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            normalized_type,
            safe_warehouse_id,
            safe_employee_id,
            payload_json,
        ),
    ).fetchone()
    if existing is not None:
        return {
            "queued": False,
            "existing": True,
            "request_id": int(existing["id"]),
        }

    cursor = db.execute(
        """
        INSERT INTO attendance_action_requests(
            request_type,
            warehouse_id,
            employee_id,
            summary_title,
            summary_note,
            payload,
            status,
            requested_by,
            handled_by,
            handled_at,
            decision_note,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """,
        (
            normalized_type,
            safe_warehouse_id,
            safe_employee_id or None,
            safe_title,
            safe_note or None,
            payload_json,
            "pending",
            safe_requested_by or None,
            None,
            None,
            None,
        ),
    )
    return {
        "queued": True,
        "existing": False,
        "request_id": int(cursor.lastrowid),
    }


def fetch_attendance_requests(
    db,
    *,
    status="all",
    search="",
    warehouse_id=None,
    date_from="",
    date_to="",
    limit=None,
):
    normalized_status = normalize_attendance_request_status(status) if status != "all" else "all"
    safe_search = str(search or "").strip()
    safe_warehouse_id = int(warehouse_id or 0) if warehouse_id not in (None, "", 0, "0") else 0
    safe_date_from = str(date_from or "").strip()
    safe_date_to = str(date_to or "").strip()

    query = """
        SELECT
            r.*,
            e.employee_code,
            e.full_name,
            e.position,
            w.name AS warehouse_name,
            ru.username AS requested_by_name,
            hu.username AS handled_by_name
        FROM attendance_action_requests r
        LEFT JOIN employees e ON e.id = r.employee_id
        LEFT JOIN warehouses w ON w.id = r.warehouse_id
        LEFT JOIN users ru ON ru.id = r.requested_by
        LEFT JOIN users hu ON hu.id = r.handled_by
        WHERE 1=1
    """
    params = []

    if normalized_status != "all":
        query += " AND r.status=?"
        params.append(normalized_status)

    if safe_warehouse_id:
        query += " AND r.warehouse_id=?"
        params.append(safe_warehouse_id)

    if safe_search:
        like = f"%{safe_search}%"
        query += """
            AND (
                COALESCE(r.summary_title, '') LIKE ?
                OR COALESCE(r.summary_note, '') LIKE ?
                OR COALESCE(e.employee_code, '') LIKE ?
                OR COALESCE(e.full_name, '') LIKE ?
                OR COALESCE(ru.username, '') LIKE ?
            )
        """
        params.extend([like, like, like, like, like])

    if safe_date_from:
        query += " AND substr(COALESCE(r.created_at, ''), 1, 10) >= ?"
        params.append(safe_date_from)

    if safe_date_to:
        query += " AND substr(COALESCE(r.created_at, ''), 1, 10) <= ?"
        params.append(safe_date_to)

    query += """
        ORDER BY
            CASE WHEN r.status='pending' THEN 0 ELSE 1 END,
            COALESCE(r.handled_at, r.created_at) DESC,
            r.id DESC
    """

    if limit:
        query += " LIMIT ?"
        params.append(int(limit))

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    for row in rows:
        row["request_type_label"] = get_attendance_request_type_label(row.get("request_type"))
        row["request_category"] = get_attendance_request_category(row.get("request_type"))
        row["payload_map"] = parse_attendance_request_payload(row.get("payload"))
        row["status_label"] = str(row.get("status") or "").replace("_", " ").title() or "-"
    return rows


def split_attendance_requests(rows, recent_limit=20):
    safe_rows = list(rows or [])
    pending_rows = [row for row in safe_rows if str(row.get("status") or "").lower() == "pending"]
    recent_rows = [
        row for row in safe_rows
        if str(row.get("status") or "").lower() != "pending"
    ]
    recent_rows.sort(
        key=lambda row: (
            str(row.get("handled_at") or row.get("updated_at") or row.get("created_at") or ""),
            int(row.get("id") or 0),
        ),
        reverse=True,
    )
    return pending_rows, recent_rows[:recent_limit]


def build_attendance_request_summary(rows):
    safe_rows = list(rows or [])
    pending_rows = [row for row in safe_rows if str(row.get("status") or "").lower() == "pending"]
    today_iso = date_cls.today().isoformat()
    return {
        "total": len(safe_rows),
        "pending": len(pending_rows),
        "approved": sum(1 for row in safe_rows if str(row.get("status") or "").lower() == "approved"),
        "rejected": sum(1 for row in safe_rows if str(row.get("status") or "").lower() == "rejected"),
        "today": sum(1 for row in safe_rows if str(row.get("created_at") or "")[:10] == today_iso),
    }
