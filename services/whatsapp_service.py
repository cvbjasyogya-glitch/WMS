import os
import re

from flask import current_app

from database import get_db
from services.announcement_center import user_matches_scope
from services.event_notification_policy import (
    get_event_notification_policy,
    row_matches_notification_aliases,
)
from services.notification_retention import cleanup_notification_history
from services.private_activity_policy import should_suppress_super_admin_notifications
from services.rbac import normalize_role

try:
    import requests as http_requests
except ImportError:
    http_requests = None


ROLE_EVENT_RECIPIENTS = {
    event_type: get_event_notification_policy(event_type)["roles"]
    for event_type in (
        "attendance.activity",
        "report.daily_submitted",
        "report.live_submitted",
        "report.status_approved",
        "report.status_rejected",
        "leave.status_approved",
        "leave.status_rejected",
        "request.owner_requested",
        "request.transfer_submitted",
        "inventory.activity",
        "inventory.inbound_approval_requested",
        "inventory.outbound_approval_requested",
        "inventory.adjust_approval_requested",
        "inventory.product_edit_approval_requested",
        "inventory.product_delete_approval_requested",
        "inventory.approval_approved",
        "inventory.approval_rejected",
        "inventory.product_approval_approved",
        "inventory.product_approval_rejected",
    )
}


def _normalize_phone_number(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = f"62{digits[1:]}"
    elif not digits.startswith("62") and len(digits) >= 8:
        digits = f"62{digits.lstrip('0')}"
    return digits


def _normalize_whatsapp_target(value):
    safe_value = str(value or "").strip()
    if not safe_value:
        return ""
    if safe_value.lower().startswith("group:"):
        safe_value = safe_value.split(":", 1)[1].strip()
    if "@" in safe_value:
        return safe_value
    normalized_phone = _normalize_phone_number(safe_value)
    return normalized_phone or safe_value


def _notification_status(result):
    ok = result.get("ok")
    if ok is None:
        return "skipped"
    return "sent" if ok else "failed"


def _notification_exists_recent(db, recipient, channel, subject, message):
    row = db.execute(
        """
        SELECT id
        FROM notifications
        WHERE recipient=?
          AND channel=?
          AND subject=?
          AND message=?
          AND created_at >= datetime('now', '-2 minutes')
        LIMIT 1
        """,
        (recipient, channel, subject, message),
    ).fetchone()
    return row is not None


def record_whatsapp_delivery(user_id, role, recipient, subject, message, result, *, channel="wa"):
    normalized_recipient = _normalize_whatsapp_target(recipient)
    if not normalized_recipient or not subject:
        return None

    db = get_db()
    cleanup_notification_history(db)
    notification_message = str(message or "").strip()
    error_message = str(result.get("error") or "").strip()
    if error_message and error_message not in notification_message:
        notification_message = (
            f"{notification_message}\nError: {error_message}".strip()
            if notification_message
            else f"Error: {error_message}"
        )

    try:
        db.execute(
            """
            INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                user_id,
                role,
                channel,
                normalized_recipient,
                str(subject).strip()[:255],
                notification_message[:2000],
                _notification_status(result),
            ),
        )
        return True
    except Exception:
        return False


def _kirimi_config_value(name):
    return str(current_app.config.get(name) or os.getenv(name) or "").strip()


def _kirimi_first_config_value(*names, default=""):
    for name in names:
        value = _kirimi_config_value(name)
        if value:
            return value
    return str(default or "").strip()


def _kirimi_send_endpoints(base_url):
    safe_base_url = str(base_url or "https://api.kirimi.id").strip().rstrip("/")
    configured_path = _kirimi_first_config_value(
        "KIRIMI_SEND_MESSAGE_PATH",
        "KIRIMI_SEND_PATH",
        default="/v1/send-message-fast",
    )
    fallback_paths = [
        configured_path,
        "/v1/send-message-fast",
        "/v1/send-message",
    ]
    endpoints = []
    for candidate in fallback_paths:
        safe_candidate = str(candidate or "").strip()
        if not safe_candidate:
            continue
        if safe_candidate.startswith(("http://", "https://")):
            endpoint_url = safe_candidate.rstrip("/")
        else:
            normalized_path = f"/{safe_candidate.lstrip('/')}"
            endpoint_url = f"{safe_base_url}{normalized_path}"
        if endpoint_url not in endpoints:
            endpoints.append(endpoint_url)
    return endpoints


def _kirimi_warehouse_aliases(*, warehouse_id=None, warehouse_name=None):
    aliases = []

    def _push(alias):
        normalized = str(alias or "").strip().upper()
        if normalized and normalized not in aliases:
            aliases.append(normalized)

    normalized_name = re.sub(r"[^a-z0-9]+", " ", str(warehouse_name or "").lower()).strip()
    if "mataram" in normalized_name:
        _push("MATARAM")
    if "mega" in normalized_name:
        _push("MEGA")

    try:
        safe_warehouse_id = int(warehouse_id)
    except (TypeError, ValueError):
        safe_warehouse_id = 0

    if safe_warehouse_id == 1:
        _push("MATARAM")
    elif safe_warehouse_id == 2:
        _push("MEGA")

    return aliases


def _cash_closing_group_target(*, warehouse_id=None, warehouse_name=None):
    for alias in _kirimi_warehouse_aliases(warehouse_id=warehouse_id, warehouse_name=warehouse_name):
        configured_target = _kirimi_config_value(f"CASH_CLOSING_WHATSAPP_GROUP_{alias}")
        if configured_target:
            return _normalize_whatsapp_target(configured_target)
    return _normalize_whatsapp_target(_kirimi_config_value("CASH_CLOSING_WHATSAPP_GROUP"))


def _kirimi_credentials(*, warehouse_id=None, warehouse_name=None):
    credentials = {
        "base_url": str(current_app.config.get("KIRIMI_BASE_URL") or "https://api.kirimi.id").strip().rstrip("/"),
        "user_code": _kirimi_config_value("KIRIMI_USER_CODE"),
        "device_id": _kirimi_config_value("KIRIMI_DEVICE_ID"),
        "secret": _kirimi_config_value("KIRIMI_SECRET"),
        "timeout": max(3, int(current_app.config.get("KIRIMI_TIMEOUT_SECONDS") or os.getenv("KIRIMI_TIMEOUT_SECONDS") or 15)),
    }

    for alias in _kirimi_warehouse_aliases(warehouse_id=warehouse_id, warehouse_name=warehouse_name):
        alias_user_code = _kirimi_config_value(f"KIRIMI_USER_CODE_{alias}")
        alias_device_id = _kirimi_config_value(f"KIRIMI_DEVICE_ID_{alias}")
        alias_secret = _kirimi_config_value(f"KIRIMI_SECRET_{alias}")
        if alias_user_code:
            credentials["user_code"] = alias_user_code
        if alias_device_id:
            credentials["device_id"] = alias_device_id
        if alias_secret:
            credentials["secret"] = alias_secret
        if alias_user_code or alias_device_id or alias_secret:
            credentials["warehouse_alias"] = alias.lower()
            break

    return credentials


def _send_via_kirimi(receiver, message, *, media_url=None, warehouse_id=None, warehouse_name=None):
    credentials = _kirimi_credentials(warehouse_id=warehouse_id, warehouse_name=warehouse_name)
    if http_requests is None:
        return {
            "ok": None,
            "provider": "kirimi",
            "receiver": receiver,
            "error": "requests_library_missing",
        }

    if not credentials["user_code"] or not credentials["device_id"] or not credentials["secret"]:
        return {
            "ok": None,
            "provider": "kirimi",
            "receiver": receiver,
            "error": "kirimi_not_configured",
        }

    payload = {
        "user_code": credentials["user_code"],
        "device_id": credentials["device_id"],
        "secret": credentials["secret"],
        "receiver": receiver,
        "message": str(message or "").strip(),
    }
    if media_url:
        payload["media_url"] = str(media_url).strip()

    last_failure = None
    endpoint_urls = _kirimi_send_endpoints(credentials["base_url"])

    for endpoint_url in endpoint_urls:
        try:
            response = http_requests.post(
                endpoint_url,
                json=payload,
                timeout=credentials["timeout"],
            )
        except Exception as exc:
            return {
                "ok": False,
                "provider": "kirimi",
                "receiver": receiver,
                "endpoint_url": endpoint_url,
                "error": f"kirimi_request_error: {exc}",
            }

        raw_payload = None
        try:
            raw_payload = response.json()
        except ValueError:
            raw_payload = None

        if not getattr(response, "ok", False):
            failure = {
                "ok": False,
                "provider": "kirimi",
                "receiver": receiver,
                "endpoint_url": endpoint_url,
                "status_code": getattr(response, "status_code", None),
                "response": raw_payload,
                "error": f"kirimi_http_{getattr(response, 'status_code', 'error')}",
            }
            last_failure = failure
            if getattr(response, "status_code", None) == 404:
                continue
            return failure

        if isinstance(raw_payload, dict):
            success_flag = raw_payload.get("success")
            status_value = raw_payload.get("status")
            if success_flag is False:
                return {
                    "ok": False,
                    "provider": "kirimi",
                    "receiver": receiver,
                    "endpoint_url": endpoint_url,
                    "status_code": getattr(response, "status_code", None),
                    "response": raw_payload,
                    "error": str(raw_payload.get("message") or "kirimi_send_failed"),
                }
            normalized_status = str(status_value or "").strip().lower()
            if normalized_status in {"failed", "error", "false", "0"}:
                return {
                    "ok": False,
                    "provider": "kirimi",
                    "receiver": receiver,
                    "endpoint_url": endpoint_url,
                    "status_code": getattr(response, "status_code", None),
                    "response": raw_payload,
                    "error": str(raw_payload.get("message") or normalized_status or "kirimi_send_failed"),
                }

        return {
            "ok": True,
            "provider": "kirimi",
            "receiver": receiver,
            "endpoint_url": endpoint_url,
            "status_code": getattr(response, "status_code", None),
            "response": raw_payload,
            "message_id": (
                (raw_payload.get("message_id") if isinstance(raw_payload, dict) else None)
                or ((raw_payload.get("data") or {}).get("id") if isinstance(raw_payload, dict) and isinstance(raw_payload.get("data"), dict) else None)
            ),
            "error": "",
        }

    return last_failure or {
        "ok": False,
        "provider": "kirimi",
        "receiver": receiver,
        "error": "kirimi_http_404",
    }


def _send_text_fallback_fonnte(receiver, message):
    api_key = str(os.getenv("FONNTE_API_KEY") or "").strip()
    if not api_key or http_requests is None:
        return {
            "ok": None,
            "provider": "fonnte",
            "receiver": receiver,
            "error": "fonnte_not_configured",
        }

    try:
        response = http_requests.post(
            "https://api.fonnte.com/send",
            headers={"Authorization": api_key},
            data={"target": receiver, "message": str(message or "").strip()},
            timeout=5,
        )
    except Exception as exc:
        return {
            "ok": False,
            "provider": "fonnte",
            "receiver": receiver,
            "error": f"fonnte_request_error: {exc}",
        }

    raw_payload = None
    try:
        raw_payload = response.json()
    except ValueError:
        raw_payload = None

    if not getattr(response, "ok", False):
        return {
            "ok": False,
            "provider": "fonnte",
            "receiver": receiver,
            "status_code": getattr(response, "status_code", None),
            "response": raw_payload,
            "error": f"fonnte_http_{getattr(response, 'status_code', 'error')}",
        }

    return {
        "ok": True,
        "provider": "fonnte",
        "receiver": receiver,
        "status_code": getattr(response, "status_code", None),
        "response": raw_payload,
        "error": "",
    }


def send_whatsapp_text(target, message, *, warehouse_id=None, warehouse_name=None):
    receiver = _normalize_whatsapp_target(target)
    if not receiver:
        return {
            "ok": None,
            "provider": "kirimi",
            "receiver": "",
            "error": "missing_target",
        }

    result = _send_via_kirimi(
        receiver,
        message,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
    )
    if result.get("ok") is None and result.get("error") == "kirimi_not_configured":
        return _send_text_fallback_fonnte(receiver, message)
    return result


def send_whatsapp_document(target, message, document_url, *, warehouse_id=None, warehouse_name=None):
    receiver = _normalize_whatsapp_target(target)
    safe_url = str(document_url or "").strip()
    if not receiver:
        return {
            "ok": None,
            "provider": "kirimi",
            "receiver": "",
            "error": "missing_target",
        }
    if not safe_url:
        return {
            "ok": None,
            "provider": "kirimi",
            "receiver": receiver,
            "error": "missing_document_url",
        }
    return _send_via_kirimi(
        receiver,
        message,
        media_url=safe_url,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
    )


def send_cash_closing_group_notification(subject, message, *, warehouse_id=None, warehouse_name=None):
    receiver = _cash_closing_group_target(warehouse_id=warehouse_id, warehouse_name=warehouse_name)
    normalized_subject = str(subject or "").strip()
    normalized_message = str(message or "").strip()
    result = {
        "target": receiver,
        "subject": normalized_subject,
        "message": normalized_message,
        "delivery": None,
    }
    if not receiver or not normalized_subject or not normalized_message:
        return result

    db = get_db()
    channel = "wa_group_event"
    if _notification_exists_recent(db, receiver, channel, normalized_subject, normalized_message):
        result["delivery"] = {
            "ok": None,
            "provider": "kirimi",
            "receiver": receiver,
            "error": "duplicate_recent_notification",
        }
        return result

    delivery = send_whatsapp_text(
        receiver,
        f"*{normalized_subject}*\n\n{normalized_message}",
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
    )
    record_whatsapp_delivery(
        None,
        "group",
        receiver,
        normalized_subject,
        normalized_message,
        delivery,
        channel=channel,
    )
    result["delivery"] = delivery
    return result


def _event_recipients_for_audience(roles, usernames=None, user_ids=None, warehouse_id=None, exclude_user_ids=None):
    normalized_roles = []
    for role in roles or []:
        normalized_role = normalize_role(role)
        if normalized_role and normalized_role not in normalized_roles:
            normalized_roles.append(normalized_role)

    normalized_user_ids = []
    seen_requested_user_ids = set()
    for value in user_ids or ():
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in seen_requested_user_ids:
            continue
        seen_requested_user_ids.add(user_id)
        normalized_user_ids.append(user_id)

    db = get_db()
    recipients = []
    seen_user_ids = set()
    excluded_ids = set()
    for value in exclude_user_ids or ():
        try:
            excluded_ids.add(int(value))
        except (TypeError, ValueError):
            continue

    rows = []
    if normalized_roles or usernames or normalized_user_ids:
        rows = db.execute(
            """
            SELECT
                u.id,
                u.role,
                u.username,
                u.notify_whatsapp,
                u.warehouse_id AS user_warehouse_id,
                e.warehouse_id AS employee_warehouse_id,
                COALESCE(NULLIF(TRIM(u.phone), ''), NULLIF(TRIM(e.phone), '')) AS phone,
                COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'User') AS display_name,
                COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), '') AS full_name
            FROM users u
            LEFT JOIN employees e ON e.id = u.employee_id
            ORDER BY u.id ASC
            """
        ).fetchall()

    for row in rows:
        row_dict = dict(row)
        user_id = int(row_dict["id"] or 0)
        if not user_id or user_id in seen_user_ids or user_id in excluded_ids:
            continue

        matches_role = row_dict["role"] in normalized_roles
        matches_alias = row_matches_notification_aliases(row_dict, usernames)
        matches_user_id = user_id in seen_requested_user_ids
        if not matches_role and not matches_alias and not matches_user_id:
            continue

        effective_warehouse_id = row_dict["employee_warehouse_id"] or row_dict["user_warehouse_id"]
        if not user_matches_scope(row_dict["role"], effective_warehouse_id, warehouse_id):
            continue

        phone = _normalize_phone_number(row_dict["phone"])
        if not phone or not int(row_dict["notify_whatsapp"] or 0):
            continue

        seen_user_ids.add(user_id)
        recipients.append(
            {
                "user_id": user_id,
                "role": row_dict["role"],
                "username": row_dict["username"],
                "display_name": row_dict["display_name"],
                "phone": phone,
            }
        )

    return recipients


def _role_recipients_for_event(roles, usernames=None, user_ids=None, warehouse_id=None, exclude_user_ids=None):
    if not roles and not usernames and not user_ids:
        return []
    return _event_recipients_for_audience(
        roles,
        usernames=usernames,
        user_ids=user_ids,
        warehouse_id=warehouse_id,
        exclude_user_ids=exclude_user_ids,
    )


def _describe_attendance_activity(punch_type, punch_label):
    normalized_punch_type = str(punch_type or "").strip().lower()
    descriptions = {
        "check_in": "mulai kerja / check in",
        "free_attendance": "checkpoint kehadiran di tengah shift, bukan check out",
        "break_start": "mulai istirahat",
        "break_finish": "selesai istirahat dan lanjut kerja",
        "check_out": "akhir kerja / check out",
    }
    if normalized_punch_type in descriptions:
        return descriptions[normalized_punch_type]

    safe_punch_label = str(punch_label or "").strip()
    if not safe_punch_label:
        return ""
    return f"aktivitas {safe_punch_label.lower()}"


def _build_event_subject_message(event_type, payload):
    payload = payload or {}
    explicit_subject = str(payload.get("subject") or "").strip()
    explicit_message = str(payload.get("message") or "").strip()
    if explicit_subject and explicit_message:
        return explicit_subject, explicit_message

    employee_name = str(payload.get("employee_name") or payload.get("staff_name") or payload.get("requester_name") or "Staff").strip()
    warehouse_name = str(payload.get("warehouse_name") or "Gudang").strip()
    time_label = str(payload.get("time_label") or payload.get("submitted_time") or "").strip()
    title = str(payload.get("title") or "").strip()
    item_count = int(payload.get("item_count") or 0)
    approval_type = str(payload.get("approval_type") or "APPROVAL").strip().upper()
    approver_name = str(payload.get("approver_name") or "Approver").strip()
    requester_name = str(payload.get("requester_name") or employee_name or "Staff").strip()
    sku = str(payload.get("sku") or "").strip()
    product_name = str(payload.get("product_name") or "").strip()
    variant_label = str(payload.get("variant_label") or "").strip()
    qty_label = str(payload.get("qty_label") or payload.get("qty") or "").strip()
    reason = str(payload.get("reason") or "").strip()

    if event_type == "attendance.activity":
        punch_type = str(payload.get("punch_type") or "").strip().lower()
        punch_label = str(payload.get("punch_label") or "Absensi").strip()
        location_label = str(payload.get("location_label") or "-").strip()
        shift_label = str(payload.get("shift_label") or "").strip()
        staff_note = str(payload.get("staff_note") or payload.get("note") or "").strip()
        duration_text = str(payload.get("duration_text") or "").strip()
        subject = explicit_subject or f"Absensi {punch_label}: {employee_name}"
        message = explicit_message
        if not message:
            message_parts = [
                (
                    f"{employee_name} merekam {punch_label} di {warehouse_name}"
                    f"{f' pukul {time_label}' if time_label else ''}."
                ),
                f"Keterangan: {_describe_attendance_activity(punch_type, punch_label)}.",
                f"Lokasi: {location_label}.",
            ]
            if shift_label:
                message_parts.append(f"Shift aktif: {shift_label}.")
            if duration_text:
                message_parts.append(duration_text)
            if staff_note:
                message_parts.append(f"Catatan staf: {staff_note}.")
            message = " ".join(part for part in message_parts if part).strip()
        return subject, message

    if event_type == "report.live_submitted":
        subject = explicit_subject or f"Live Report Baru: {employee_name}"
        message = explicit_message or (
            f"{employee_name} mengirim live report di {warehouse_name}"
            f"{f' pukul {time_label}' if time_label else ''}."
            f"{f' Judul: {title}.' if title else ''}"
        )
        return subject, message

    if event_type == "report.daily_submitted":
        subject = explicit_subject or f"Daily Report Baru: {employee_name}"
        message = explicit_message or (
            f"{employee_name} mengirim daily report di {warehouse_name}."
            f"{f' Judul: {title}.' if title else ''}"
        )
        return subject, message

    if event_type == "report.status_approved":
        report_type_label = str(payload.get("report_type_label") or "Report").strip()
        status_label = str(payload.get("status_label") or "Disetujui").strip()
        subject = explicit_subject or f"{report_type_label} {status_label}: {employee_name}"
        message = explicit_message or (
            f"{report_type_label} milik {employee_name} di {warehouse_name} "
            f"ditandai {status_label.lower()} oleh {approver_name}."
            f"{f' Judul: {title}.' if title else ''}"
            f"{f' Catatan HR: {reason}.' if reason else ''}"
        )
        return subject, message

    if event_type == "report.status_rejected":
        report_type_label = str(payload.get("report_type_label") or "Report").strip()
        status_label = str(payload.get("status_label") or "Perlu Follow Up").strip()
        subject = explicit_subject or f"{report_type_label} {status_label}: {employee_name}"
        message = explicit_message or (
            f"{report_type_label} milik {employee_name} di {warehouse_name} "
            f"butuh tindak lanjut menurut {approver_name}."
            f"{f' Judul: {title}.' if title else ''}"
            f"{f' Catatan HR: {reason}.' if reason else ''}"
        )
        return subject, message

    if event_type == "leave.status_approved":
        range_label = str(payload.get("range_label") or "-").strip()
        leave_type_label = str(payload.get("leave_type_label") or "Libur").strip()
        subject = explicit_subject or f"{leave_type_label} Disetujui: {employee_name}"
        message = explicit_message or (
            f"Pengajuan {leave_type_label.lower()} {employee_name} untuk {range_label} "
            f"disetujui oleh {approver_name} di {warehouse_name}."
        )
        return subject, message

    if event_type == "leave.status_rejected":
        range_label = str(payload.get("range_label") or "-").strip()
        leave_type_label = str(payload.get("leave_type_label") or "Libur").strip()
        subject = explicit_subject or f"{leave_type_label} Ditolak: {employee_name}"
        message = explicit_message or (
            f"Pengajuan {leave_type_label.lower()} {employee_name} untuk {range_label} "
            f"ditolak oleh {approver_name} di {warehouse_name}."
            f"{f' Alasan: {reason}.' if reason else ''}"
        )
        return subject, message

    if event_type == "request.owner_requested":
        subject = explicit_subject or f"Request Barang ke Owner: {warehouse_name}"
        message = explicit_message or (
            f"Ada {item_count} item request khusus ke owner dari {warehouse_name}."
            f"{f' Pengaju: {requester_name}.' if requester_name else ''}"
        )
        return subject, message

    if event_type == "request.transfer_submitted":
        target_warehouse_name = str(payload.get("target_warehouse_name") or "").strip()
        subject = explicit_subject or f"Request Antar Gudang: {warehouse_name}"
        message = explicit_message or (
            f"Ada {item_count} item request antar gudang dari {warehouse_name}"
            f"{f' ke {target_warehouse_name}' if target_warehouse_name else ''}."
            f"{f' Pengaju: {requester_name}.' if requester_name else ''}"
        )
        return subject, message

    if event_type == "inventory.activity":
        subject = explicit_subject or f"Aktivitas WMS: {warehouse_name}"
        message = explicit_message or (
            f"Ada aktivitas WMS baru di {warehouse_name}."
            f"{f' Detail: {title}.' if title else ''}"
        )
        return subject, message

    if event_type == "inventory.inbound_approval_requested":
        subject = explicit_subject or f"Approval Inbound: {warehouse_name}"
        message = explicit_message or (
            f"Ada {item_count} item inbound yang menunggu approval di {warehouse_name}"
            f"{f'. Pengaju: {employee_name}.' if employee_name else '.'}"
        )
        return subject, message

    if event_type == "inventory.outbound_approval_requested":
        subject = explicit_subject or f"Approval Outbound: {warehouse_name}"
        message = explicit_message or (
            f"Ada {item_count} item outbound yang menunggu approval di {warehouse_name}"
            f"{f'. Pengaju: {employee_name}.' if employee_name else '.'}"
        )
        return subject, message

    if event_type == "inventory.adjust_approval_requested":
        subject = explicit_subject or f"Approval Adjust: {warehouse_name}"
        message = explicit_message or (
            f"Ada {item_count} item adjustment yang menunggu approval di {warehouse_name}"
            f"{f'. Pengaju: {employee_name}.' if employee_name else '.'}"
        )
        return subject, message

    if event_type == "inventory.product_edit_approval_requested":
        item_label = " / ".join(part for part in [sku, product_name, variant_label] if part)
        subject = explicit_subject or f"Approval Edit Produk: {warehouse_name}"
        message = explicit_message or (
            f"Ada perubahan master produk yang menunggu approval di {warehouse_name}."
            f"{f' Pengaju: {employee_name}.' if employee_name else ''}"
            f"{f' Item: {item_label}.' if item_label else ''}"
        )
        return subject, message

    if event_type == "inventory.product_delete_approval_requested":
        subject = explicit_subject or f"Approval Hapus Produk: {warehouse_name}"
        message = explicit_message or (
            f"Ada {item_count} permintaan hapus master produk yang menunggu approval di {warehouse_name}."
            f"{f' Pengaju: {employee_name}.' if employee_name else ''}"
        )
        return subject, message

    if event_type == "inventory.approval_approved":
        item_label = " / ".join(part for part in [sku, product_name, variant_label] if part)
        subject = explicit_subject or f"Approval {approval_type} Disetujui"
        message = explicit_message or (
            f"{approval_type} di {warehouse_name} disetujui oleh {approver_name}."
            f"{f' Pengaju: {requester_name}.' if requester_name else ''}"
            f"{f' Item: {item_label}.' if item_label else ''}"
            f"{f' Qty: {qty_label}.' if qty_label else ''}"
        )
        return subject, message

    if event_type == "inventory.product_approval_approved":
        item_label = " / ".join(part for part in [sku, product_name, variant_label] if part)
        subject = explicit_subject or f"Approval {approval_type} Disetujui"
        message = explicit_message or (
            f"{approval_type} di {warehouse_name} disetujui oleh {approver_name}."
            f"{f' Pengaju: {requester_name}.' if requester_name else ''}"
            f"{f' Item: {item_label}.' if item_label else ''}"
        )
        return subject, message

    if event_type == "inventory.approval_rejected":
        item_label = " / ".join(part for part in [sku, product_name, variant_label] if part)
        subject = explicit_subject or f"Approval {approval_type} Ditolak"
        message = explicit_message or (
            f"{approval_type} di {warehouse_name} ditolak oleh {approver_name}."
            f"{f' Pengaju: {requester_name}.' if requester_name else ''}"
            f"{f' Item: {item_label}.' if item_label else ''}"
            f"{f' Qty: {qty_label}.' if qty_label else ''}"
            f"{f' Alasan: {reason}.' if reason else ''}"
        )
        return subject, message

    if event_type == "inventory.product_approval_rejected":
        item_label = " / ".join(part for part in [sku, product_name, variant_label] if part)
        subject = explicit_subject or f"Approval {approval_type} Ditolak"
        message = explicit_message or (
            f"{approval_type} di {warehouse_name} ditolak oleh {approver_name}."
            f"{f' Pengaju: {requester_name}.' if requester_name else ''}"
            f"{f' Item: {item_label}.' if item_label else ''}"
            f"{f' Alasan: {reason}.' if reason else ''}"
        )
        return subject, message

    subject = explicit_subject or f"Notifikasi {event_type}"
    message = explicit_message or "Ada aktivitas baru yang perlu dicek."
    return subject, message


def send_role_based_notification(event_type, payload):
    normalized_event = str(event_type or "").strip().lower()
    payload = payload or {}
    audience_policy = get_event_notification_policy(normalized_event)
    roles = tuple(payload.get("roles") or ()) if "roles" in payload else audience_policy["roles"]
    usernames = tuple(payload.get("usernames") or ()) if "usernames" in payload else audience_policy["usernames"]
    user_ids = tuple(payload.get("user_ids") or ()) if "user_ids" in payload else audience_policy.get("user_ids", ())
    warehouse_id = payload.get("warehouse_id")
    exclude_user_ids = payload.get("exclude_user_ids") or ()
    link_url = str(payload.get("link_url") or "").strip()
    subject, message = _build_event_subject_message(normalized_event, payload)
    document_url = str(payload.get("document_url") or "").strip()

    recipients = _role_recipients_for_event(
        roles,
        usernames=usernames,
        user_ids=user_ids,
        warehouse_id=warehouse_id,
        exclude_user_ids=exclude_user_ids,
    )
    results = {
        "event_type": normalized_event,
        "roles": list(roles),
        "usernames": list(usernames or ()),
        "user_ids": list(user_ids or ()),
        "subject": subject,
        "message": message,
        "deliveries": [],
        "suppressed": False,
    }

    if should_suppress_super_admin_notifications(
        event_type=normalized_event,
        link_url=link_url,
    ):
        results["suppressed"] = True
        return results

    for recipient in recipients:
        if _notification_exists_recent(
            get_db(),
            recipient["phone"],
            "wa_role_event",
            subject,
            message,
        ):
            continue

        if document_url:
            delivery = send_whatsapp_document(recipient["phone"], f"*{subject}*\n\n{message}", document_url)
            channel = "wa_role_document"
        else:
            delivery = send_whatsapp_text(recipient["phone"], f"*{subject}*\n\n{message}")
            channel = "wa_role_event"

        record_whatsapp_delivery(
            recipient["user_id"],
            recipient["role"],
            recipient["phone"],
            subject,
            message,
            delivery,
            channel=channel,
        )
        results["deliveries"].append(
            {
                "user_id": recipient["user_id"],
                "role": recipient["role"],
                "phone": recipient["phone"],
                "ok": delivery.get("ok"),
                "error": delivery.get("error"),
                "provider": delivery.get("provider"),
                "link_url": link_url,
            }
        )

    return results


def send_user_whatsapp_notification(user_id, subject, message, *, warehouse_id=None, channel="wa_user_event"):
    try:
        safe_user_id = int(user_id or 0)
    except (TypeError, ValueError):
        safe_user_id = 0
    normalized_subject = str(subject or "").strip()
    normalized_message = str(message or "").strip()
    if safe_user_id <= 0 or not normalized_subject or not normalized_message:
        return {
            "user_id": safe_user_id,
            "subject": normalized_subject,
            "message": normalized_message,
            "deliveries": [],
        }

    recipients = _event_recipients_for_audience(
        (),
        user_ids=(safe_user_id,),
        warehouse_id=warehouse_id,
    )
    results = {
        "user_id": safe_user_id,
        "subject": normalized_subject,
        "message": normalized_message,
        "deliveries": [],
    }

    for recipient in recipients:
        if _notification_exists_recent(
            get_db(),
            recipient["phone"],
            channel,
            normalized_subject,
            normalized_message,
        ):
            continue

        delivery = send_whatsapp_text(
            recipient["phone"],
            f"*{normalized_subject}*\n\n{normalized_message}",
        )
        record_whatsapp_delivery(
            recipient["user_id"],
            recipient["role"],
            recipient["phone"],
            normalized_subject,
            normalized_message,
            delivery,
            channel=channel,
        )
        results["deliveries"].append(
            {
                "user_id": recipient["user_id"],
                "role": recipient["role"],
                "phone": recipient["phone"],
                "ok": delivery.get("ok"),
                "error": delivery.get("error"),
                "provider": delivery.get("provider"),
            }
        )

    return results
