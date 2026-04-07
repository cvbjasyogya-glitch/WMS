import os
import re

from flask import current_app

from database import get_db
from services.announcement_center import user_matches_scope
from services.event_notification_policy import (
    get_event_notification_policy,
    row_matches_notification_aliases,
)
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
    normalized_recipient = _normalize_phone_number(recipient)
    if not normalized_recipient or not subject:
        return None

    db = get_db()
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


def _kirimi_credentials():
    return {
        "base_url": str(current_app.config.get("KIRIMI_BASE_URL") or "https://api.kirimi.id").strip().rstrip("/"),
        "user_code": str(current_app.config.get("KIRIMI_USER_CODE") or os.getenv("KIRIMI_USER_CODE") or "").strip(),
        "device_id": str(current_app.config.get("KIRIMI_DEVICE_ID") or os.getenv("KIRIMI_DEVICE_ID") or "").strip(),
        "secret": str(current_app.config.get("KIRIMI_SECRET") or os.getenv("KIRIMI_SECRET") or "").strip(),
        "timeout": max(3, int(current_app.config.get("KIRIMI_TIMEOUT_SECONDS") or os.getenv("KIRIMI_TIMEOUT_SECONDS") or 15)),
    }


def _send_via_kirimi(receiver, message, *, media_url=None):
    credentials = _kirimi_credentials()
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

    try:
        response = http_requests.post(
            f"{credentials['base_url']}/v1/send-message",
            json=payload,
            timeout=credentials["timeout"],
        )
    except Exception as exc:
        return {
            "ok": False,
            "provider": "kirimi",
            "receiver": receiver,
            "error": f"kirimi_request_error: {exc}",
        }

    raw_payload = None
    try:
        raw_payload = response.json()
    except ValueError:
        raw_payload = None

    if not getattr(response, "ok", False):
        return {
            "ok": False,
            "provider": "kirimi",
            "receiver": receiver,
            "status_code": getattr(response, "status_code", None),
            "response": raw_payload,
            "error": f"kirimi_http_{getattr(response, 'status_code', 'error')}",
        }

    if isinstance(raw_payload, dict):
        success_flag = raw_payload.get("success")
        status_value = raw_payload.get("status")
        if success_flag is False:
            return {
                "ok": False,
                "provider": "kirimi",
                "receiver": receiver,
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
                "status_code": getattr(response, "status_code", None),
                "response": raw_payload,
                "error": str(raw_payload.get("message") or normalized_status or "kirimi_send_failed"),
            }

    return {
        "ok": True,
        "provider": "kirimi",
        "receiver": receiver,
        "status_code": getattr(response, "status_code", None),
        "response": raw_payload,
        "message_id": (
            (raw_payload.get("message_id") if isinstance(raw_payload, dict) else None)
            or ((raw_payload.get("data") or {}).get("id") if isinstance(raw_payload, dict) and isinstance(raw_payload.get("data"), dict) else None)
        ),
        "error": "",
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


def send_whatsapp_text(target, message):
    receiver = _normalize_phone_number(target)
    if not receiver:
        return {
            "ok": None,
            "provider": "kirimi",
            "receiver": "",
            "error": "missing_target",
        }

    result = _send_via_kirimi(receiver, message)
    if result.get("ok") is None and result.get("error") == "kirimi_not_configured":
        return _send_text_fallback_fonnte(receiver, message)
    return result


def send_whatsapp_document(target, message, document_url):
    receiver = _normalize_phone_number(target)
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
    return _send_via_kirimi(receiver, message, media_url=safe_url)


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
        punch_label = str(payload.get("punch_label") or "Absensi").strip()
        location_label = str(payload.get("location_label") or "-").strip()
        duration_text = str(payload.get("duration_text") or "").strip()
        subject = explicit_subject or f"Absensi {punch_label}: {employee_name}"
        message = explicit_message or (
            f"{employee_name} melakukan {punch_label} di {warehouse_name}"
            f"{f' pukul {time_label}' if time_label else ''}. Titik: {location_label}."
        )
        if duration_text:
            message = f"{message} {duration_text}".strip()
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
    }

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
