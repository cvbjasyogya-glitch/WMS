from datetime import date as date_cls, datetime


MONTH_NAMES_ID = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

AUDIENCE_LABELS = {
    "all": "Semua Tim",
    "leaders": "Leaders",
    "warehouse_team": "Warehouse Team",
}

LEADER_AUDIENCE_ROLES = {"super_admin", "owner", "hr", "leader"}
SCOPED_AUDIENCE_ROLES = {"leader", "admin", "staff"}


def parse_iso_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    try:
        return date_cls.fromisoformat(raw_value)
    except ValueError:
        return None


def format_long_date(value):
    parsed = parse_iso_date(value)
    if not parsed:
        return value or "-"
    return f"{parsed.day:02d} {MONTH_NAMES_ID[parsed.month - 1]} {parsed.year}"


def format_date_range(start_date, end_date=None):
    parsed_start = parse_iso_date(start_date)
    parsed_end = parse_iso_date(end_date) if end_date else None

    if not parsed_start:
        return start_date or "-"

    if parsed_end and parsed_end != parsed_start:
        return f"{format_long_date(start_date)} s.d. {format_long_date(end_date)}"

    return format_long_date(start_date)


def audience_label(value):
    return AUDIENCE_LABELS.get((value or "").strip().lower(), "Semua Tim")


def role_matches_audience(role, audience):
    normalized_role = (role or "").strip().lower()
    normalized_audience = (audience or "all").strip().lower()

    if normalized_audience == "leaders":
        return normalized_role in LEADER_AUDIENCE_ROLES

    return True


def user_matches_scope(role, user_warehouse_id, target_warehouse_id):
    if target_warehouse_id in (None, ""):
        return True

    normalized_role = (role or "").strip().lower()
    if normalized_role not in SCOPED_AUDIENCE_ROLES:
        return True

    try:
        return int(user_warehouse_id) == int(target_warehouse_id)
    except (TypeError, ValueError):
        return False


def build_announcement_notification_payload(announcement):
    title = (announcement.get("title") or "Pengumuman Baru").strip()
    warehouse_name = (announcement.get("warehouse_name") or "Semua Gudang").strip()
    publish_label = format_long_date(announcement.get("publish_date"))
    audience_name = audience_label(announcement.get("audience"))
    body = (announcement.get("message") or "").strip() or "Ada pengumuman baru yang perlu dicek."
    subject = f"Pengumuman baru: {title}"
    message = (
        f"{warehouse_name}\n"
        f"Audience: {audience_name}\n"
        f"Publish: {publish_label}\n\n"
        f"{body}"
    )
    push_body = f"{warehouse_name} | {body[:120]}".strip()
    return {
        "subject": subject,
        "message": message,
        "push_title": title,
        "push_body": push_body[:160],
        "push_tag": f"announcement-{announcement.get('id') or 'new'}",
    }


def build_schedule_change_notification_payload(event):
    title = (event.get("title") or "Perubahan Jadwal").strip()
    message = (event.get("message") or "").strip() or "Ada pembaruan jadwal yang perlu dicek."
    subject = f"Perubahan jadwal: {title}"
    return {
        "subject": subject,
        "message": message,
        "push_title": title,
        "push_body": message[:160],
        "push_tag": f"schedule-change-{event.get('id') or 'new'}",
    }


def create_schedule_change_event(
    db,
    *,
    warehouse_id,
    event_kind,
    title,
    message,
    audience="all",
    affected_employee_id=None,
    affected_employee_name=None,
    start_date=None,
    end_date=None,
    target_url="/schedule/",
    created_by=None,
):
    cursor = db.execute(
        """
        INSERT INTO schedule_change_events(
            warehouse_id,
            audience,
            event_kind,
            title,
            message,
            affected_employee_id,
            affected_employee_name,
            start_date,
            end_date,
            target_url,
            created_by
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            warehouse_id,
            audience,
            event_kind,
            title,
            message,
            affected_employee_id,
            affected_employee_name,
            start_date,
            end_date,
            target_url,
            created_by,
        ),
    )
    return cursor.lastrowid
