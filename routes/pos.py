import json
import sqlite3
import time
from datetime import date as date_cls, datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - fallback for older Python
    ZoneInfo = None
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, session

from database import get_db, is_postgresql_backend
from services.crm_loyalty import (
    CRM_TRANSACTION_TYPE_LABELS,
    DEFAULT_STRINGING_REWARD_AMOUNT,
    STRINGING_PROGRESS_MIN_AMOUNT,
    STRINGING_REWARD_THRESHOLD,
    build_auto_member_record,
    calculate_loyalty_fields,
    calculate_stringing_progress_units,
    ensure_crm_membership_multi_program_schema,
    find_matching_customer_identity,
    find_matching_member_identity,
    get_member_snapshot,
    normalize_customer_phone,
    normalize_member_type,
    normalize_transaction_type,
    reconcile_member_identity_duplicates,
)
from services.notification_service import notify_operational_event
from services.receipt_pdf_service import (
    build_pos_receipt_render_context,
    build_public_file_url,
    build_pos_receipt_branding,
    format_receipt_homebase_label,
    generate_pos_receipt_pdf,
)
from services.rbac import can_access_pos_terminal, can_assign_pos_staff, has_permission, is_scoped_role, normalize_role
from services.stock_service import add_stock
from services.whatsapp_service import (
    record_whatsapp_delivery,
    send_role_based_notification,
    send_whatsapp_document,
    send_whatsapp_text,
)


pos_bp = Blueprint("pos", __name__, url_prefix="/kasir")

PAYMENT_METHODS = ("cash", "qris", "transfer", "debit", "cv")
SPLIT_PAYMENT_METHOD = "split"
POS_ALL_PAYMENT_METHODS = PAYMENT_METHODS + (SPLIT_PAYMENT_METHOD,)
PAYMENT_METHOD_ALIASES = {
    "credit": "cv",
    "kredit": "cv",
}
POS_ASSIGNABLE_ROLE_LIST = ("owner", "super_admin", "leader", "admin", "staff")
INACTIVE_EMPLOYMENT_STATUSES = ("inactive", "terminated", "resigned", "former", "nonactive", "non-active")
POS_REVENUE_HIDDEN_LABEL = "-"
POS_DISPLAY_UTC_OFFSET_HOURS = 7
POS_DISPLAY_TIMEZONE = ZoneInfo("Asia/Jakarta") if ZoneInfo else timezone(timedelta(hours=POS_DISPLAY_UTC_OFFSET_HOURS))
POS_HIDDEN_ARCHIVE_SESSION_KEY = "pos_hidden_archive_unlocked_until"
POS_DB_LOCK_RETRY_ATTEMPTS = 2
POS_DB_LOCK_RETRY_DELAY_SECONDS = 0.35
POS_BULK_LOOKUP_CHUNK_SIZE = 400
POS_SOURCE_ACTOR_SQL = (
    "COALESCE("
    "NULLIF(TRIM(ps.source_sales_name), ''), "
    "NULLIF(TRIM(ps.source_cashier_name), '')"
    ")"
)
POS_LOCAL_ACTOR_SQL = (
    "COALESCE("
    "NULLIF(TRIM(e.full_name), ''), "
    "NULLIF(TRIM(u.username), '')"
    ")"
)
POS_CASHIER_NAME_SQL = (
    "COALESCE("
    f"{POS_SOURCE_ACTOR_SQL}, "
    f"{POS_LOCAL_ACTOR_SQL}, "
    "'Tanpa Staff'"
    ")"
)
POS_CASHIER_GROUP_KEY_SQL = (
    "CASE "
    f"WHEN {POS_SOURCE_ACTOR_SQL} IS NOT NULL THEN 'source:' || LOWER({POS_SOURCE_ACTOR_SQL}) "
    "WHEN ps.cashier_user_id IS NOT NULL THEN 'user:' || CAST(ps.cashier_user_id AS TEXT) "
    f"WHEN {POS_LOCAL_ACTOR_SQL} IS NOT NULL THEN 'local:' || LOWER({POS_LOCAL_ACTOR_SQL}) "
    "ELSE 'none' "
    "END"
)
POS_CASHIER_USERNAME_SQL = (
    "COALESCE("
    f"{POS_SOURCE_ACTOR_SQL}, "
    "NULLIF(TRIM(u.username), ''), "
    f"{POS_LOCAL_ACTOR_SQL}, "
    "'-'"
    ")"
)
POS_CASHIER_POSITION_SQL = (
    "COALESCE("
    f"CASE WHEN {POS_SOURCE_ACTOR_SQL} IS NOT NULL THEN 'Sales iPOS4' END, "
    "NULLIF(TRIM(e.position), ''), "
    "NULLIF(TRIM(u.role), ''), "
    "'Staff'"
    ")"
)

POS_PRINTER_DRIVER_RESOURCES = [
    {
        "vendor": "Windows / Microsoft",
        "driver_name": "Add or install a printer in Windows",
        "category": "System Driver",
        "supported_os": "Windows 10 / Windows 11",
        "download_url": "https://support.microsoft.com/en-us/windows/add-or-install-a-printer-in-windows-cc0724cf-793e-3542-d1ff-727e4978638b",
        "note": "Langkah paling aman untuk mendeteksi printer thermal sebelum install driver vendor.",
    },
    {
        "vendor": "Windows / Microsoft",
        "driver_name": "Download and install latest printer drivers",
        "category": "Driver Update",
        "supported_os": "Windows 10 / Windows 11",
        "download_url": "https://support.microsoft.com/en-us/windows/how-to-download-and-install-the-latest-printer-drivers-4ff66446-a2ab-b77f-46f4-a6d3fe4bf661",
        "note": "Panduan update driver via Windows Update jika printer sudah terdeteksi.",
    },
    {
        "vendor": "Epson",
        "driver_name": "TM-T88VI Support (APD Driver)",
        "category": "Thermal Receipt Driver",
        "supported_os": "Windows / Windows Server",
        "download_url": "https://epson.com/Support/Point-of-Sale/OmniLink-Printers/Epson-TM-T88VI-Series/s/SPT_C31CE94061?review-filter=Windows+10+64-bit",
        "note": "Halaman support resmi Epson berisi APD, Virtual Port Driver, dan utilitas model TM-T88VI.",
    },
    {
        "vendor": "Star Micronics",
        "driver_name": "TSP100 futurePRNT Software Full",
        "category": "Thermal Receipt Driver",
        "supported_os": "Windows / Linux / macOS",
        "download_url": "https://starmicronics.com/support/download/tsp100-futureprnt-software-full/",
        "note": "Paket driver resmi untuk seri TSP100 termasuk tools setup, OPOS, dan JavaPOS.",
    },
    {
        "vendor": "Star Micronics",
        "driver_name": "USB Printer Setup Guide (Windows)",
        "category": "Setup Guide",
        "supported_os": "Windows 11 / Windows 10",
        "download_url": "https://starmicronics.com/help-center/knowledge-base/how-to-install-a-usb-printer-using-star-windows-software/",
        "note": "Panduan resmi instalasi driver Star USB di Windows sebelum test print iPOS.",
    },
    {
        "vendor": "BIXOLON",
        "driver_name": "BIXOLON Supports & Downloads (Driver)",
        "category": "Thermal Receipt Driver",
        "supported_os": "Windows / POS Middleware",
        "download_url": "https://www.bixolon.com/download_view.php?idx=133&s_key=Driver",
        "note": "Pusat unduhan driver resmi BIXOLON termasuk Windows Driver dan OPOS/JPOS.",
    },
    {
        "vendor": "Citizen",
        "driver_name": "Citizen Drivers & Tools (CT Series)",
        "category": "Thermal Receipt Driver",
        "supported_os": "Windows 11 / Windows 10 / Linux / macOS",
        "download_url": "https://www.citizen-systems.com/us/support/drivers-and-tools/CT-E301?cHash=01ea71ebf46ed57708417dee29fc301a",
        "note": "Portal resmi Citizen untuk Windows Driver, OPOS, JavaPOS, dan utilitas printer receipt.",
    },
    {
        "vendor": "XPrinter",
        "driver_name": "XPrinter Download Center",
        "category": "Thermal Receipt Driver",
        "supported_os": "Windows / Android / iOS / Linux",
        "download_url": "https://www.xprintertech.com/download.html",
        "note": "Halaman resmi XPrinter untuk driver bill product, SDK, user manual, dan test tool.",
    },
    {
        "vendor": "Rongta",
        "driver_name": "Rongta Driver Download Center",
        "category": "Thermal Receipt Driver",
        "supported_os": "Windows / macOS / Chrome",
        "download_url": "https://www.rongtatech.com/category/downloads/30",
        "note": "Pusat driver resmi Rongta untuk seri RP58/RP80/RP33x dan model thermal lainnya.",
    },
    {
        "vendor": "HPRT",
        "driver_name": "HPRT Printer Driver Download",
        "category": "Thermal Receipt Driver",
        "supported_os": "Windows / macOS",
        "download_url": "https://download.hprt.com/Downloads/",
        "note": "Portal resmi HPRT untuk driver printer POS, utility, dan model thermal receipt.",
    },
    {
        "vendor": "SUNMI",
        "driver_name": "SUNMI Windows Bluetooth Printer Driver Doc",
        "category": "Integration Guide",
        "supported_os": "Windows",
        "download_url": "https://developer.sunmi.com/docs/en-US/xeghjk491/zzzeghjk557/",
        "note": "Dokumentasi resmi SUNMI untuk koneksi printer dari Windows (khusus skenario Bluetooth/TCP).",
    },
    {
        "vendor": "SUNMI",
        "driver_name": "SUNMI TCP Printing with Windows Driver",
        "category": "Integration Guide",
        "supported_os": "Windows",
        "download_url": "https://developer.sunmi.com/docs/en-US/cdixeghjk491/xfzzeghjk557",
        "note": "Panduan resmi SUNMI untuk cetak TCP dari Windows ke perangkat printer yang kompatibel.",
    },
    {
        "vendor": "Zebra",
        "driver_name": "Printer Setup Utilities",
        "category": "Utility + Driver",
        "supported_os": "Windows / Android / iOS",
        "download_url": "https://qac-downloads.zebra.com/us/en/software/printer-software/zebra-setup-utility.html",
        "note": "Utility resmi Zebra untuk konfigurasi printer, pairing, dan initial setup.",
    },
]

POS_POSTGRESQL_CHECKOUT_SEQUENCE_TABLES = (
    "crm_customers",
    "crm_memberships",
    "crm_purchase_records",
    "crm_purchase_items",
    "crm_member_records",
    "pos_sales",
    "pos_negative_stock_overdrafts",
    "stock_history",
)


def _to_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_decimal(value, default="0"):
    try:
        if value in (None, ""):
            value = default
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal(default).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _currency(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ensure_postgresql_id_sequence(db, table_name):
    default_row = db.execute(
        """
        SELECT column_default
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name=?
          AND column_name='id'
        """,
        (table_name,),
    ).fetchone()
    try:
        column_default = str(default_row["column_default"] or "").lower()
    except Exception:
        column_default = ""
    if "nextval(" in column_default:
        return

    sequence_name = f"{table_name}_id_seq"
    db.execute(f"CREATE SEQUENCE IF NOT EXISTS {sequence_name}")
    db.execute(f"ALTER SEQUENCE {sequence_name} OWNED BY {table_name}.id")
    db.execute(
        f"ALTER TABLE {table_name} ALTER COLUMN id SET DEFAULT nextval('{sequence_name}')"
    )
    db.execute(
        f"SELECT setval('{sequence_name}', COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, false)"
    )


def _ensure_pos_checkout_postgresql_sequences(db):
    if not is_postgresql_backend(current_app.config):
        return

    runtime_state = current_app.extensions.setdefault("pos_runtime_state", {})
    cache_key = "checkout_sequences_ready"
    if runtime_state.get(cache_key):
        return

    for table_name in POS_POSTGRESQL_CHECKOUT_SEQUENCE_TABLES:
        _ensure_postgresql_id_sequence(db, table_name)

    runtime_state[cache_key] = True


def _ensure_pos_checkout_trace_schema(db):
    runtime_state = current_app.extensions.setdefault("pos_runtime_state", {})
    backend = "postgresql" if is_postgresql_backend(current_app.config) else "sqlite"
    cache_key = f"checkout_trace_schema_ready:{backend}"
    if runtime_state.get(cache_key):
        return

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_checkout_traces(
            id INTEGER PRIMARY KEY,
            client_token TEXT NOT NULL UNIQUE,
            sale_id INTEGER,
            purchase_id INTEGER,
            receipt_no TEXT,
            warehouse_id INTEGER,
            cashier_user_id INTEGER,
            sale_date TEXT,
            customer_name TEXT,
            customer_phone TEXT,
            total_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'success',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    if is_postgresql_backend(current_app.config):
        _ensure_postgresql_id_sequence(db, "pos_checkout_traces")

    runtime_state[cache_key] = True


def _fetch_pos_checkout_trace(db, client_token):
    safe_token = str(client_token or "").strip()
    if not safe_token:
        return None

    try:
        return db.execute(
            """
            SELECT
                id,
                client_token,
                sale_id,
                purchase_id,
                receipt_no,
                warehouse_id,
                cashier_user_id,
                sale_date,
                customer_name,
                customer_phone,
                total_amount,
                status,
                created_at,
                updated_at
            FROM pos_checkout_traces
            WHERE client_token=?
            LIMIT 1
            """,
            (safe_token,),
        ).fetchone()
    except Exception:
        return None


def _record_pos_checkout_trace(
    db,
    *,
    client_token,
    sale_id,
    purchase_id,
    receipt_no,
    warehouse_id,
    cashier_user_id,
    sale_date,
    customer_name,
    customer_phone,
    total_amount,
    status="success",
):
    safe_token = str(client_token or "").strip()
    if not safe_token:
        return

    db.execute(
        """
        INSERT INTO pos_checkout_traces(
            client_token,
            sale_id,
            purchase_id,
            receipt_no,
            warehouse_id,
            cashier_user_id,
            sale_date,
            customer_name,
            customer_phone,
            total_amount,
            status,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(client_token) DO UPDATE SET
            sale_id=excluded.sale_id,
            purchase_id=excluded.purchase_id,
            receipt_no=excluded.receipt_no,
            warehouse_id=excluded.warehouse_id,
            cashier_user_id=excluded.cashier_user_id,
            sale_date=excluded.sale_date,
            customer_name=excluded.customer_name,
            customer_phone=excluded.customer_phone,
            total_amount=excluded.total_amount,
            status=excluded.status,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            safe_token,
            sale_id,
            purchase_id,
            receipt_no,
            warehouse_id,
            cashier_user_id,
            sale_date,
            customer_name,
            customer_phone,
            _currency(total_amount or 0),
            str(status or "success").strip().lower() or "success",
        ),
    )


def _normalize_pos_phone(value):
    return normalize_customer_phone(value)


def _record_pos_receipt_delivery_state(
    db,
    sale_id,
    *,
    pdf_relative_path=None,
    pdf_public_url=None,
    receipt_whatsapp_status=None,
    receipt_whatsapp_error=None,
    mark_sent=False,
):
    fields = []
    params = []

    if pdf_relative_path is not None:
        fields.append("receipt_pdf_path=?")
        params.append(pdf_relative_path)
    if pdf_public_url is not None:
        fields.append("receipt_pdf_url=?")
        params.append(pdf_public_url)
    if receipt_whatsapp_status is not None:
        fields.append("receipt_whatsapp_status=?")
        params.append(receipt_whatsapp_status)
    if receipt_whatsapp_error is not None:
        fields.append("receipt_whatsapp_error=?")
        params.append(receipt_whatsapp_error)
    if mark_sent:
        fields.append("receipt_whatsapp_sent_at=CURRENT_TIMESTAMP")

    if not fields:
        return

    fields.append("updated_at=CURRENT_TIMESTAMP")
    params.append(sale_id)
    db.execute(
        f"UPDATE pos_sales SET {', '.join(fields)} WHERE id=?",
        params,
    )


def _prepare_pos_receipt_sale(sale):
    prepared_sale = dict(sale or {})
    receipt_brand = build_pos_receipt_branding(prepared_sale)
    prepared_sale["receipt_brand"] = receipt_brand
    prepared_sale["warehouse_receipt_label"] = (
        receipt_brand.get("homebase_label")
        or format_receipt_homebase_label(prepared_sale.get("warehouse_name"))
    )
    prepared_sale["cashier_receipt_label"] = (
        str(
            prepared_sale.get("cashier_username")
            or prepared_sale.get("cashier_name")
            or prepared_sale.get("cashier_identity_label")
            or "-"
        ).strip()
        or "-"
    )
    return prepared_sale


def _generate_backend_pos_receipt_pdf(db, receipt_no):
    sale = _fetch_pos_sale_detail_by_receipt(db, receipt_no)
    if sale is None:
        raise ValueError("Data nota POS tidak ditemukan untuk generate PDF backend.")
    sale = _prepare_pos_receipt_sale(sale)

    pdf_meta = generate_pos_receipt_pdf(sale)
    _record_pos_receipt_delivery_state(
        db,
        sale["id"],
        pdf_relative_path=pdf_meta["relative_path"],
        pdf_public_url=pdf_meta["public_url"],
    )
    db.commit()
    sale["receipt_pdf_path"] = pdf_meta["relative_path"]
    sale["receipt_pdf_public_url"] = pdf_meta["public_url"]
    return sale, pdf_meta


def _send_pos_receipt_to_customer(db, sale):
    sale = sale or {}
    sale_id = _to_int(sale.get("id"), 0)
    target_phone = _normalize_pos_phone(sale.get("customer_phone"))
    receipt_url = (sale.get("receipt_pdf_public_url") or sale.get("receipt_pdf_url") or "").strip()
    receipt_no = (sale.get("receipt_no") or "-").strip()
    customer_name = (sale.get("customer_name") or "Pelanggan").strip()
    total_amount_label = sale.get("total_amount_label") or _format_pos_currency_label(sale.get("total_amount") or 0)
    subject = f"Nota POS {receipt_no}"
    loyalty_lines = list(sale.get("loyalty_summary_lines") or [])
    if not loyalty_lines:
        loyalty_lines = _build_pos_receipt_loyalty_lines(db, sale)
    receipt_brand = sale.get("receipt_brand") or build_pos_receipt_branding(sale)
    receipt_brand_name = receipt_brand.get("business_name") or "ERP Core POS"
    message_lines = [
        f"Halo {customer_name},",
        f"Terima kasih sudah berbelanja di {receipt_brand_name}.",
        f"Nota pembelian Anda dengan nomor {receipt_no} sudah kami siapkan.",
        f"Total belanja: {total_amount_label}.",
        "File nota PDF kami lampirkan di pesan ini.",
    ]
    if loyalty_lines:
        message_lines.append("")
        message_lines.append(f"{sale.get('loyalty_summary_title') or 'Update CRM Customer'}:")
        message_lines.extend(loyalty_lines)
    message = "\n".join(message_lines).strip()

    if sale_id <= 0:
        return {"ok": None, "error": "missing_sale_id"}

    if not target_phone:
        result = {"ok": None, "error": "customer_phone_missing", "provider": "kirimi"}
        _record_pos_receipt_delivery_state(
            db,
            sale_id,
            receipt_whatsapp_status="skipped",
            receipt_whatsapp_error="customer_phone_missing",
        )
        record_whatsapp_delivery(None, None, "", subject, message, result, channel="wa_document")
        db.commit()
        return result

    receipt_print_url = build_public_file_url(f"/kasir/receipt/{receipt_no}/print")
    if not receipt_url:
        if receipt_print_url:
            fallback_message = "\n".join(
                [
                    message,
                    "",
                    "File PDF belum siap, tetapi nota bisa dibuka melalui link berikut:",
                    receipt_print_url,
                ]
            ).strip()
            fallback_delivery = send_whatsapp_text(
                target_phone,
                fallback_message,
                warehouse_id=sale.get("warehouse_id"),
                warehouse_name=sale.get("warehouse_name"),
            )
            fallback_error = str(fallback_delivery.get("error") or "").strip()
            status_value = "sent" if fallback_delivery.get("ok") else ("skipped" if fallback_delivery.get("ok") is None else "failed")
            _record_pos_receipt_delivery_state(
                db,
                sale_id,
                receipt_whatsapp_status=status_value,
                receipt_whatsapp_error=(fallback_error if fallback_error else ""),
                mark_sent=bool(fallback_delivery.get("ok")),
            )
            record_whatsapp_delivery(None, None, target_phone, subject, fallback_message, fallback_delivery, channel="wa_text")
            db.commit()
            return fallback_delivery

        result = {"ok": None, "error": "receipt_public_url_missing", "provider": "kirimi"}
        _record_pos_receipt_delivery_state(
            db,
            sale_id,
            receipt_whatsapp_status="failed",
            receipt_whatsapp_error="receipt_public_url_missing",
        )
        record_whatsapp_delivery(None, None, target_phone, subject, message, result, channel="wa_document")
        db.commit()
        return result

    delivery = send_whatsapp_document(
        target_phone,
        message,
        receipt_url,
        warehouse_id=sale.get("warehouse_id"),
        warehouse_name=sale.get("warehouse_name"),
    )
    if delivery.get("ok") is not True:
        fallback_links = [receipt_url]
        if receipt_print_url and receipt_print_url not in fallback_links:
            fallback_links.append(receipt_print_url)
        fallback_message = "\n".join(
            [
                message,
                "",
                "Jika file PDF belum muncul otomatis, Anda bisa membuka nota melalui link berikut:",
                *fallback_links,
            ]
        ).strip()
        fallback_delivery = send_whatsapp_text(
            target_phone,
            fallback_message,
            warehouse_id=sale.get("warehouse_id"),
            warehouse_name=sale.get("warehouse_name"),
        )
        if fallback_delivery.get("ok") is True:
            delivery = dict(fallback_delivery)
            delivery["error"] = ""
    delivery_error = str(delivery.get("error") or "").strip()
    if delivery_error == "missing_target":
        delivery_error = "customer_phone_missing"
        delivery["error"] = delivery_error
    persisted_delivery_error = delivery_error[:500]
    if delivery.get("ok") is True and not persisted_delivery_error:
        persisted_delivery_error = ""
    status_value = "sent" if delivery.get("ok") else ("skipped" if delivery.get("ok") is None else "failed")
    _record_pos_receipt_delivery_state(
        db,
        sale_id,
        receipt_whatsapp_status=status_value,
        receipt_whatsapp_error=(
            persisted_delivery_error
            if (delivery.get("ok") is True or persisted_delivery_error)
            else None
        ),
        mark_sent=bool(delivery.get("ok")),
    )
    record_whatsapp_delivery(None, None, target_phone, subject, message, delivery, channel="wa_document")
    db.commit()
    return delivery


def _resolve_pos_receipt_whatsapp_status(delivery):
    if delivery is None:
        return "pending"
    if delivery.get("ok") is True:
        return "sent"
    if delivery.get("ok") is None:
        return "skipped"
    return "failed"


def _resolve_pos_receipt_whatsapp_feedback(status, error_code):
    safe_status = str(status or "pending").strip().lower()
    safe_error = str(error_code or "").strip().lower()
    if safe_status == "sent":
        return "Nota customer berhasil dikirim via WhatsApp."
    if safe_status == "skipped":
        if safe_error in {"customer_phone_missing", "missing_target"}:
            return "Nota belum terkirim karena nomor customer kosong atau tidak valid."
        if safe_error == "receipt_public_url_missing":
            return "Nota belum terkirim karena file PDF belum siap."
        return f"Nota belum terkirim ({safe_error or 'skipped'})."
    if safe_status == "failed":
        return f"Kirim WA nota gagal ({safe_error or 'unknown_error'})."
    return "Status kirim nota masih pending."


def _fetch_pos_loyalty_record(db, purchase_id, member_id):
    safe_purchase_id = _to_int(purchase_id, 0)
    safe_member_id = _to_int(member_id, 0)
    if safe_purchase_id <= 0 or safe_member_id <= 0:
        return None

    row = db.execute(
        """
        SELECT
            record_type,
            points_delta,
            service_count_delta,
            reward_redeemed_delta,
            benefit_value
        FROM crm_member_records
        WHERE purchase_id=? AND member_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (safe_purchase_id, safe_member_id),
    ).fetchone()
    return dict(row) if row else None


def _fetch_pos_loyalty_records_for_purchase(db, purchase_id):
    safe_purchase_id = _to_int(purchase_id, 0)
    if safe_purchase_id <= 0:
        return []

    rows = db.execute(
        """
        SELECT
            mr.member_id,
            mr.record_type,
            mr.points_delta,
            mr.service_count_delta,
            mr.reward_redeemed_delta,
            mr.benefit_value,
            mr.amount,
            pr.transaction_type,
            COALESCE(NULLIF(TRIM(m.member_code), ''), '') AS member_code,
            COALESCE(NULLIF(TRIM(m.member_type), ''), '') AS member_type
        FROM crm_member_records mr
        LEFT JOIN crm_purchase_records pr ON pr.id = mr.purchase_id
        LEFT JOIN crm_memberships m ON m.id = mr.member_id
        WHERE mr.purchase_id=?
        ORDER BY mr.id ASC
        """,
        (safe_purchase_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _build_pos_stringing_progress_label(snapshot, transaction_type, loyalty_record):
    progress_count = max(_to_int((snapshot or {}).get("stringing_progress_count"), 0), 0)
    if (
        normalize_transaction_type(transaction_type) == "stringing_service"
        and _to_int((loyalty_record or {}).get("service_count_delta"), 0) > 0
        and progress_count == 0
    ):
        progress_count = STRINGING_REWARD_THRESHOLD
    return f"{progress_count}/{STRINGING_REWARD_THRESHOLD}"


def _build_pos_receipt_loyalty_lines(db, sale):
    safe_sale = sale or {}
    purchase_id = _to_int(safe_sale.get("purchase_id"), 0)
    if purchase_id <= 0:
        return []

    loyalty_records = _fetch_pos_loyalty_records_for_purchase(db, purchase_id)
    if not loyalty_records:
        return []

    lines = []
    for loyalty_record in loyalty_records:
        member_id = _to_int(loyalty_record.get("member_id"), 0)
        if member_id <= 0:
            continue
        snapshot = get_member_snapshot(db, member_id)
        if not snapshot:
            continue

        member_type = str(
            loyalty_record.get("member_type")
            or safe_sale.get("member_type")
            or snapshot.get("member_type")
            or ""
        ).strip().lower()
        member_code = str(
            loyalty_record.get("member_code")
            or safe_sale.get("member_code")
            or snapshot.get("member_code")
            or ""
        ).strip()
        transaction_type = normalize_transaction_type(
            loyalty_record.get("record_type")
            if loyalty_record.get("record_type") == "reward_redemption"
            else loyalty_record.get("transaction_type") or safe_sale.get("transaction_type")
        )

        if member_type == "purchase":
            if member_code:
                lines.append(f"- Member Pembelian: {member_code}")
            earned_points = max(_to_int(loyalty_record.get("points_delta"), 0), 0)
            current_points = max(_to_int(snapshot.get("current_points"), 0), 0)
            lines.append(f"- Poin transaksi ini: +{earned_points} poin")
            lines.append(f"- Total poin aktif: {current_points} poin")
            continue

        if member_code:
            lines.append(f"- Member Senaran: {member_code}")
        progress_label = _build_pos_stringing_progress_label(snapshot, transaction_type, loyalty_record)
        available_reward_count = max(_to_int(snapshot.get("available_reward_count"), 0), 0)
        reward_value_label = _format_pos_currency_label(snapshot.get("reward_unit_amount") or DEFAULT_STRINGING_REWARD_AMOUNT)
        service_count_delta = max(_to_int((loyalty_record or {}).get("service_count_delta"), 0), 0)

        if transaction_type == "stringing_reward_redemption":
            benefit_value = _currency(
                loyalty_record.get("benefit_value")
                or snapshot.get("reward_unit_amount")
                or DEFAULT_STRINGING_REWARD_AMOUNT
            )
            lines.append(f"- Free senar terpakai: 1x ({_format_pos_currency_label(benefit_value)})")
            lines.append(f"- Progress senar berikutnya: {progress_label}")
            if available_reward_count > 0:
                lines.append(f"- Free senar tersisa: {available_reward_count}x")
            continue

        lines.append(f"- Progress senar: {progress_label}")
        if transaction_type == "stringing_service" and service_count_delta <= 0:
            lines.append(
                f"- Progress belum bertambah karena nominal senaran di bawah {_format_pos_currency_label(STRINGING_PROGRESS_MIN_AMOUNT)}"
            )
        if available_reward_count > 0:
            lines.append(f"- Free senar siap dipakai: {available_reward_count}x ({reward_value_label})")
        else:
            remaining_visits = max(_to_int(snapshot.get("stringing_remaining_visits"), STRINGING_REWARD_THRESHOLD), 0)
            lines.append(f"- Sisa {remaining_visits} lagi menuju free 1x")
    return lines


def _attach_pos_loyalty_summary(db, sale):
    safe_sale = dict(sale or {})
    loyalty_lines = _build_pos_receipt_loyalty_lines(db, safe_sale)
    safe_sale["loyalty_summary_title"] = "Update CRM Customer"
    safe_sale["loyalty_summary_lines"] = loyalty_lines
    safe_sale["has_loyalty_summary"] = bool(loyalty_lines)
    return safe_sale


def _get_pos_today():
    return datetime.now(POS_DISPLAY_TIMEZONE).date()


def _normalize_sale_date(raw_value):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return _get_pos_today().isoformat()
    try:
        return date_cls.fromisoformat(raw_value).isoformat()
    except ValueError:
        return _get_pos_today().isoformat()


def _resolve_active_pos_sale_date(raw_value=None, *, allow_historical=False):
    normalized_date = _normalize_sale_date(raw_value)
    allow_manual_override = current_app.config.get("POS_ALLOW_MANUAL_SALE_DATE")
    if allow_manual_override is None:
        allow_manual_override = bool(current_app.testing)
    if allow_historical or allow_manual_override:
        return normalized_date
    return _get_pos_today().isoformat()


def _normalize_editable_pos_sale_date(raw_value):
    safe_value = str(raw_value or "").strip()
    if not safe_value:
        raise ValueError("Tanggal transaksi wajib diisi.")
    try:
        parsed_date = date_cls.fromisoformat(safe_value)
    except ValueError as exc:
        raise ValueError("Tanggal transaksi tidak valid.") from exc

    today = _get_pos_today()
    if parsed_date > today:
        raise ValueError("Tanggal transaksi tidak boleh melebihi hari ini.")
    return parsed_date.isoformat()


def _is_sqlite_lock_error(exc):
    message = str(exc or "").strip().lower()
    return (
        "database is locked" in message
        or "database schema is locked" in message
        or "database table is locked" in message
    )


def _normalize_payment_method(raw_value, *, allow_split=True):
    method = (raw_value or "").strip().lower()
    method = PAYMENT_METHOD_ALIASES.get(method, method)
    allowed_methods = POS_ALL_PAYMENT_METHODS if allow_split else PAYMENT_METHODS
    return method if method in allowed_methods else "cash"


def _format_payment_method_label(raw_value):
    method = _normalize_payment_method(raw_value)
    if method == SPLIT_PAYMENT_METHOD:
        return "SPLIT"
    if method == "transfer":
        return "TF"
    if method == "cv":
        return "CV"
    return method.upper()


def _normalize_pos_payment_breakdown(raw_value):
    payload = raw_value
    if isinstance(raw_value, str):
        safe_value = raw_value.strip()
        if not safe_value:
            return []
        try:
            payload = json.loads(safe_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    if isinstance(payload, dict):
        payload = [
            {"method": key, "amount": value}
            for key, value in payload.items()
        ]

    if not isinstance(payload, (list, tuple)):
        return []

    aggregated_amounts = {method: Decimal("0.00") for method in PAYMENT_METHODS}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        method = _normalize_payment_method(entry.get("method"), allow_split=False)
        amount = _to_decimal(entry.get("amount"), "0")
        if amount <= 0:
            continue
        aggregated_amounts[method] = (
            aggregated_amounts[method] + amount
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    normalized_entries = []
    for method in PAYMENT_METHODS:
        amount = aggregated_amounts[method]
        if amount <= 0:
            continue
        normalized_amount = _currency(amount)
        normalized_entries.append(
            {
                "method": method,
                "method_label": _format_payment_method_label(method),
                "amount": normalized_amount,
                "amount_label": _format_pos_currency_label(normalized_amount),
            }
        )
    return normalized_entries


def _serialize_pos_payment_breakdown(entries):
    normalized_entries = _normalize_pos_payment_breakdown(entries)
    if not normalized_entries:
        return None
    return json.dumps(
        [
            {
                "method": entry["method"],
                "amount": _currency(entry["amount"]),
            }
            for entry in normalized_entries
        ],
        separators=(",", ":"),
    )


def _build_pos_payment_breakdown_label(entries):
    normalized_entries = _normalize_pos_payment_breakdown(entries)
    if not normalized_entries:
        return ""
    return " + ".join(
        f"{entry['method_label']} {entry['amount_label']}"
        for entry in normalized_entries
    )


def _build_pos_sale_payment_meta(payment_method, paid_amount, raw_breakdown):
    normalized_method = _normalize_payment_method(payment_method)
    normalized_entries = _normalize_pos_payment_breakdown(raw_breakdown)
    has_payment_breakdown = (
        normalized_method == SPLIT_PAYMENT_METHOD
        and len(normalized_entries) >= 2
    )
    return {
        "payment_breakdown_entries": normalized_entries if has_payment_breakdown else [],
        "payment_breakdown_label": (
            _build_pos_payment_breakdown_label(normalized_entries)
            if has_payment_breakdown
            else ""
        ),
        "has_payment_breakdown": has_payment_breakdown,
        "effective_paid_amount": _currency(
            sum(
                _to_decimal(entry.get("amount"), "0")
                for entry in (normalized_entries if has_payment_breakdown else [])
            )
            if has_payment_breakdown
            else _to_decimal(paid_amount, "0")
        ),
    }


def _normalize_adjustment_type(raw_value):
    safe_value = str(raw_value or "").strip().lower()
    return safe_value if safe_value in {"amount", "percent"} else "amount"


def _calculate_adjustment_amount(base_amount, adjustment_type, raw_value, *, clamp_to_base=False):
    base_decimal = _to_decimal(base_amount, "0")
    value_decimal = _to_decimal(raw_value, "0")
    safe_type = _normalize_adjustment_type(adjustment_type)

    if value_decimal <= 0 or base_decimal <= 0:
        return Decimal("0.00")

    if safe_type == "percent":
        if clamp_to_base:
            value_decimal = min(value_decimal, Decimal("100.00"))
        amount = (base_decimal * value_decimal / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        amount = value_decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if clamp_to_base:
        amount = min(amount, base_decimal)

    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_pos_sale_financials(items, discount_type="amount", discount_value=0, tax_type="amount", tax_value=0):
    subtotal_amount = sum((item["line_total"] for item in items), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    discount_amount = _calculate_adjustment_amount(
        subtotal_amount,
        discount_type,
        discount_value,
        clamp_to_base=True,
    )
    taxable_base = max(subtotal_amount - discount_amount, Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax_amount = _calculate_adjustment_amount(
        taxable_base,
        tax_type,
        tax_value,
        clamp_to_base=False,
    )
    total_amount = (taxable_base + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_items = sum(int(item.get("qty") or 0) for item in items)

    return {
        "total_items": total_items,
        "subtotal_amount": subtotal_amount,
        "discount_type": _normalize_adjustment_type(discount_type),
        "discount_value": _to_decimal(discount_value, "0"),
        "discount_amount": discount_amount,
        "tax_type": _normalize_adjustment_type(tax_type),
        "tax_value": _to_decimal(tax_value, "0"),
        "tax_amount": tax_amount,
        "total_amount": total_amount,
    }


def _normalize_sale_month(raw_value):
    safe_value = str(raw_value or "").strip()
    if not safe_value:
        today = _get_pos_today()
        return f"{today.year:04d}-{today.month:02d}"

    try:
        normalized = date_cls.fromisoformat(f"{safe_value}-01")
        return f"{normalized.year:04d}-{normalized.month:02d}"
    except ValueError:
        today = _get_pos_today()
        return f"{today.year:04d}-{today.month:02d}"


def _json_error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def _require_pos_access(json_mode=False):
    if can_access_pos_terminal(session.get("role")):
        return None

    message = "Akses kasir hanya tersedia untuk owner, super admin, dan leader."
    if json_mode:
        return _json_error(message, 403)

    flash(message, "error")
    return redirect("/workspace/")


def _can_view_pos_revenue():
    return has_permission(session.get("role"), "view_pos")


def _can_manage_pos_hidden_archive():
    return normalize_role(session.get("role")) == "super_admin"


def _can_archive_pos_sale():
    return normalize_role(session.get("role")) == "super_admin"


def _get_pos_hidden_archive_password():
    configured = str(current_app.config.get("POS_HIDDEN_ARCHIVE_PASSWORD") or "").strip()
    return configured or "susu"


def _get_pos_hidden_archive_unlock_seconds():
    return max(_to_int(current_app.config.get("POS_HIDDEN_ARCHIVE_UNLOCK_SECONDS"), 1800), 300)


def _is_pos_hidden_archive_unlocked():
    if not _can_manage_pos_hidden_archive():
        return False

    unlocked_until = _to_int(session.get(POS_HIDDEN_ARCHIVE_SESSION_KEY), 0)
    if unlocked_until <= 0:
        return False
    return unlocked_until >= int(datetime.now(timezone.utc).timestamp())


def _unlock_pos_hidden_archive():
    session[POS_HIDDEN_ARCHIVE_SESSION_KEY] = int(datetime.now(timezone.utc).timestamp()) + _get_pos_hidden_archive_unlock_seconds()
    session.modified = True


def _lock_pos_hidden_archive():
    session.pop(POS_HIDDEN_ARCHIVE_SESSION_KEY, None)
    session.modified = True


def _sanitize_pos_hidden_archive_return_url(raw_value):
    safe_value = str(raw_value or "").strip()
    if safe_value.startswith("/kasir/hidden-archive"):
        return safe_value
    return "/kasir/hidden-archive"


def _sanitize_pos_sales_action_return_url(raw_value):
    safe_value = str(raw_value or "").strip()
    if safe_value.startswith("/kasir/log") or safe_value.startswith("/kasir/hidden-archive"):
        return safe_value
    return "/kasir/log"


def _mask_pos_sale_item_financials(item):
    masked_item = dict(item or {})
    for numeric_key in ("unit_price", "line_total", "void_amount", "active_line_total"):
        if numeric_key in masked_item:
            masked_item[numeric_key] = 0
    for label_key in ("unit_price_label", "line_total_label", "void_amount_label", "active_line_total_label"):
        if label_key in masked_item:
            masked_item[label_key] = POS_REVENUE_HIDDEN_LABEL
    return masked_item


def _mask_pos_sale_log_rows(rows, can_view_revenue):
    if can_view_revenue:
        return rows

    masked_rows = []
    for row in rows:
        masked_row = dict(row or {})
        for numeric_key in ("total_amount", "paid_amount", "change_amount", "subtotal_amount", "discount_amount", "tax_amount"):
            if numeric_key in masked_row:
                masked_row[numeric_key] = 0
        for label_key in (
            "total_amount_label",
            "paid_amount_label",
            "change_amount_label",
            "subtotal_amount_label",
            "discount_amount_label",
            "tax_amount_label",
        ):
            if label_key in masked_row:
                masked_row[label_key] = POS_REVENUE_HIDDEN_LABEL
        if "items" in masked_row:
            masked_row["items"] = [_mask_pos_sale_item_financials(item) for item in masked_row.get("items") or []]
        if "item_preview_lines" in masked_row:
            masked_row["item_preview_lines"] = [
                _mask_pos_sale_item_financials(item)
                for item in masked_row.get("item_preview_lines") or []
            ]
        masked_rows.append(masked_row)
    return masked_rows


def _mask_pos_sale_log_summary(summary, can_view_revenue):
    if can_view_revenue:
        return summary

    masked_summary = dict(summary or {})
    masked_summary["total_revenue"] = 0
    masked_summary["total_revenue_label"] = POS_REVENUE_HIDDEN_LABEL
    masked_summary["average_ticket_label"] = POS_REVENUE_HIDDEN_LABEL
    return masked_summary


def _mask_pos_staff_sales_rows(rows, can_view_revenue):
    if can_view_revenue:
        return rows

    masked_rows = []
    for row in rows:
        masked_row = dict(row or {})
        masked_row["total_revenue"] = 0
        masked_row["average_ticket"] = 0
        masked_row["total_revenue_label"] = POS_REVENUE_HIDDEN_LABEL
        masked_row["average_ticket_label"] = POS_REVENUE_HIDDEN_LABEL
        masked_rows.append(masked_row)
    return masked_rows


def _mask_pos_staff_sales_summary(summary, can_view_revenue):
    if can_view_revenue:
        return summary

    masked_summary = dict(summary or {})
    masked_summary["total_revenue"] = 0
    masked_summary["total_revenue_label"] = POS_REVENUE_HIDDEN_LABEL
    masked_summary["average_ticket_label"] = POS_REVENUE_HIDDEN_LABEL
    masked_summary["top_staff_revenue_label"] = POS_REVENUE_HIDDEN_LABEL
    return masked_summary


def _default_warehouse_id(db):
    warehouse = db.execute(
        "SELECT id FROM warehouses ORDER BY id LIMIT 1"
    ).fetchone()
    return warehouse["id"] if warehouse else 1


def _resolve_pos_warehouse(db, raw_warehouse_id):
    default_warehouse = _default_warehouse_id(db)

    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id") or default_warehouse

    selected = _to_int(raw_warehouse_id, session.get("warehouse_id") or default_warehouse)
    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (selected,),
    ).fetchone()
    return warehouse["id"] if warehouse else default_warehouse


def _resolve_pos_report_warehouse(db, raw_warehouse_id):
    if is_scoped_role(session.get("role")):
        return _resolve_pos_warehouse(db, raw_warehouse_id)

    safe_value = str(raw_warehouse_id or "").strip()
    if not safe_value:
        return None

    selected = _to_int(safe_value, None)
    if selected is None:
        return None

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (selected,),
    ).fetchone()
    return warehouse["id"] if warehouse else None


POS_CUSTOMER_SMART_SELECT_LIMIT = 80
POS_CUSTOMER_INITIAL_OPTION_LIMIT = 120


def _coerce_pos_customer_option_limit(limit, default=POS_CUSTOMER_SMART_SELECT_LIMIT):
    safe_limit = _to_int(limit, default)
    if safe_limit <= 0:
        safe_limit = default
    return max(10, min(safe_limit, 250))


def _fetch_pos_customers(db, warehouse_id, search="", limit=POS_CUSTOMER_INITIAL_OPTION_LIMIT):
    safe_warehouse_id = _to_int(warehouse_id, 0)
    if safe_warehouse_id <= 0:
        return []

    params = [safe_warehouse_id]
    query = """
        SELECT
            c.id,
            c.customer_name,
            c.contact_person,
            c.phone,
            m.member_code,
            m.member_type,
            m.reward_unit_amount
        FROM crm_customers c
        LEFT JOIN crm_memberships m
            ON m.id = (
                SELECT cm.id
                FROM crm_memberships cm
                WHERE cm.customer_id = c.id
                  AND cm.status='active'
                ORDER BY cm.id DESC
                LIMIT 1
            )
        WHERE c.warehouse_id=?
    """

    search_term = str(search or "").strip()
    if search_term:
        like_term = f"%{search_term}%"
        compact_term = f"%{normalize_customer_phone(search_term) or search_term.replace(' ', '')}%"
        query += """
            AND (
                LOWER(COALESCE(c.customer_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(c.contact_person, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(c.phone, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(m.member_code, '')) LIKE LOWER(?)
                OR REPLACE(REPLACE(REPLACE(LOWER(COALESCE(c.customer_name, '')), ' ', ''), '-', ''), '/', '') LIKE LOWER(?)
                OR REPLACE(REPLACE(REPLACE(LOWER(COALESCE(m.member_code, '')), ' ', ''), '-', ''), '/', '') LIKE LOWER(?)
                OR REPLACE(REPLACE(REPLACE(COALESCE(c.phone, ''), ' ', ''), '-', ''), '+', '') LIKE ?
            )
        """
        params.extend([like_term, like_term, like_term, like_term, compact_term, compact_term, compact_term])

    query += " ORDER BY c.customer_name ASC, c.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(_coerce_pos_customer_option_limit(limit, default=POS_CUSTOMER_INITIAL_OPTION_LIMIT))

    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_pos_categories(db, warehouse_id):
    rows = db.execute(
        """
        SELECT DISTINCT c.name
        FROM products p
        JOIN product_variants v ON v.product_id = p.id
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN stock s
            ON s.product_id = p.id
           AND s.variant_id = v.id
           AND s.warehouse_id = ?
        WHERE COALESCE(c.name, '') <> ''
        ORDER BY c.name ASC
        """,
        (warehouse_id,),
    ).fetchall()
    return [row["name"] for row in rows if row["name"]]


def _build_pos_staff_option(row, warehouse_id):
    if row is None:
        return None

    role = row["role"]
    if not can_assign_pos_staff(role):
        return None

    employment_status = str(row["employment_status"] or "").strip().lower()
    if employment_status in {"inactive", "terminated", "resigned", "former", "nonactive", "non-active"}:
        return None

    assigned_warehouse_id = _to_int(
        row["employee_warehouse_id"],
        _to_int(row["user_warehouse_id"], 0),
    )
    if warehouse_id is not None:
        if assigned_warehouse_id <= 0:
            return None
        if int(assigned_warehouse_id) != int(warehouse_id):
            return None

    display_name = (row["full_name"] or row["username"] or "").strip() or f"User {row['id']}"
    meta_parts = []
    if row["position"]:
        meta_parts.append(str(row["position"]).strip())
    if row["warehouse_name"]:
        meta_parts.append(str(row["warehouse_name"]).strip())

    label = display_name
    if meta_parts:
        label = f"{display_name} | {' · '.join(part for part in meta_parts if part)}"

    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": display_name,
        "label": label,
        "role": role,
        "warehouse_id": assigned_warehouse_id or None,
    }


def _fetch_pos_staff_options(db, warehouse_id):
    params = [*POS_ASSIGNABLE_ROLE_LIST, *INACTIVE_EMPLOYMENT_STATUSES]
    query = """
        SELECT
            u.id,
            u.username,
            u.role,
            u.warehouse_id AS user_warehouse_id,
            u.employee_id,
            e.full_name,
            e.position,
            e.warehouse_id AS employee_warehouse_id,
            e.employment_status,
            w.name AS warehouse_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        WHERE u.role IN (?, ?, ?, ?, ?)
          AND COALESCE(NULLIF(LOWER(TRIM(e.employment_status)), ''), 'active') NOT IN (?, ?, ?, ?, ?, ?)
    """

    if warehouse_id is not None:
        query += " AND COALESCE(e.warehouse_id, u.warehouse_id) = ?"
        params.append(warehouse_id)

    query += " ORDER BY COALESCE(NULLIF(TRIM(e.full_name), ''), u.username) ASC, u.id ASC"
    rows = db.execute(query, tuple(params)).fetchall()

    options = []
    for row in rows:
        option = _build_pos_staff_option(row, warehouse_id)
        if option:
            options.append(option)
    return options


def _resolve_pos_cashier_option(db, warehouse_id, raw_user_id):
    selected_user_id = _to_int(raw_user_id, session.get("user_id") or 0)
    row = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.role,
            u.warehouse_id AS user_warehouse_id,
            u.employee_id,
            e.full_name,
            e.position,
            e.warehouse_id AS employee_warehouse_id,
            e.employment_status,
            w.name AS warehouse_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        WHERE u.id=?
        LIMIT 1
        """,
        (selected_user_id,),
    ).fetchone()
    option = _build_pos_staff_option(row, warehouse_id)
    if not option:
        raise ValueError("Kasir / Sales yang dipilih tidak valid untuk gudang aktif.")
    return option


def _fetch_pos_summary(db, warehouse_id, sale_date):
    total_tx = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND COALESCE(status, 'posted') <> 'voided' AND COALESCE(is_hidden_archive, 0)=0
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    total_revenue = db.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND COALESCE(status, 'posted') <> 'voided' AND COALESCE(is_hidden_archive, 0)=0
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    total_items = db.execute(
        """
        SELECT COALESCE(SUM(total_items), 0) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND COALESCE(status, 'posted') <> 'voided' AND COALESCE(is_hidden_archive, 0)=0
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    cashier_total = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND cashier_user_id=? AND COALESCE(status, 'posted') <> 'voided' AND COALESCE(is_hidden_archive, 0)=0
        """,
        (warehouse_id, sale_date, session.get("user_id")),
    ).fetchone()["total"]

    return {
        "total_tx": int(total_tx or 0),
        "total_revenue": _currency(total_revenue or 0),
        "total_items": int(total_items or 0),
        "cashier_total": int(cashier_total or 0),
    }


def _fetch_recent_sales(db, warehouse_id, sale_date):
    rows = db.execute(
        f"""
        SELECT
            ps.id,
            ps.receipt_no,
            ps.sale_date,
            ps.payment_method,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            c.customer_name,
            {POS_CASHIER_NAME_SQL} AS cashier_name
        FROM pos_sales ps
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        WHERE ps.warehouse_id=? AND ps.sale_date=?
          AND COALESCE(ps.is_hidden_archive, 0)=0
        ORDER BY ps.id DESC
        LIMIT 20
        """,
        (warehouse_id, sale_date),
    ).fetchall()
    return [dict(row) for row in rows]


def _normalize_pos_log_date_range(raw_date_from, raw_date_to):
    date_from = date_cls.fromisoformat(_normalize_sale_date(raw_date_from))
    date_to = date_cls.fromisoformat(_normalize_sale_date(raw_date_to))
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "label": _format_pos_period_label(date_from.isoformat(), date_to.isoformat()),
    }


def _parse_pos_timestamp(raw_value):
    safe_value = str(raw_value or "").strip()
    if not safe_value:
        return None

    normalized = safe_value.replace("T", " ")
    if len(normalized) >= 19 and len(normalized) >= 11 and normalized[10].isdigit():
        normalized = f"{normalized[:10]} {normalized[10:]}"
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    if len(normalized) == 16:
        normalized = f"{normalized}:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _format_pos_time_label(raw_value):
    parsed = _parse_pos_timestamp(raw_value)
    if not parsed:
        return "-"

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_time = parsed.astimezone(POS_DISPLAY_TIMEZONE)
    return local_time.strftime("%H:%M:%S")


def _normalize_pos_cash_closing_date(value):
    safe_value = str(value or "").strip()
    if not safe_value:
        return _get_pos_today().isoformat()
    try:
        return date_cls.fromisoformat(safe_value).isoformat()
    except ValueError:
        return _get_pos_today().isoformat()


def _parse_pos_cash_closing_amount(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return 0
    normalized = (
        raw_value.replace("Rp", "")
        .replace("rp", "")
        .replace(".", "")
        .replace(",", "")
        .replace(" ", "")
    )
    digits = []
    for index, char in enumerate(normalized):
        if char.isdigit():
            digits.append(char)
        elif char == "-" and index == 0:
            digits.append(char)
    try:
        parsed = int("".join(digits))
    except ValueError:
        return 0
    return max(parsed, 0)


def _format_pos_cash_closing_amount(value, zero_label="-"):
    try:
        amount = int(round(float(value or 0)))
    except (TypeError, ValueError):
        amount = 0
    amount = max(amount, 0)
    if amount <= 0:
        return zero_label
    return f"{amount:,}".replace(",", ".")


def _round_pos_cash_on_hand(amount, step=50000, threshold=25000):
    try:
        safe_amount = int(round(float(amount or 0)))
    except (TypeError, ValueError):
        safe_amount = 0
    safe_amount = max(safe_amount, 0)
    if step <= 0:
        return safe_amount
    remainder = safe_amount % step
    if remainder >= threshold:
        return safe_amount + (step - remainder)
    return safe_amount - remainder


def _format_pos_cash_closing_date_label(value):
    safe_value = _normalize_pos_cash_closing_date(value)
    try:
        return date_cls.fromisoformat(safe_value).strftime("%d/%m/%Y")
    except ValueError:
        return safe_value


def _build_pos_cash_closing_summary_line(label, amount, zero_label="-"):
    return f"{label:<11} = {_format_pos_cash_closing_amount(amount, zero_label=zero_label)}"


def _build_pos_cash_closing_summary_message(
    warehouse_name,
    closing_date,
    *,
    cash_amount=0,
    debit_amount=0,
    qris_amount=0,
    mb_amount=0,
    cv_amount=0,
    expense_amount=0,
    cash_on_hand_amount=0,
    combined_total_amount=0,
    note="",
):
    warehouse_label = format_receipt_homebase_label(warehouse_name)
    if warehouse_label == "-":
        warehouse_label = "Mataram"
    total_amount = max(
        int(cash_amount or 0)
        + int(debit_amount or 0)
        + int(qris_amount or 0)
        + int(mb_amount or 0)
        + int(cv_amount or 0),
        0,
    )
    message_lines = [
        f'Laporan "{warehouse_label}" {_format_pos_cash_closing_date_label(closing_date)}',
        "",
        _build_pos_cash_closing_summary_line("Tunai", cash_amount),
        _build_pos_cash_closing_summary_line("Debet", debit_amount),
        _build_pos_cash_closing_summary_line("QRIS", qris_amount),
        _build_pos_cash_closing_summary_line("Mb", mb_amount),
        _build_pos_cash_closing_summary_line("CV", cv_amount),
        "------------------------------",
        _build_pos_cash_closing_summary_line("Tot.", total_amount, zero_label="0"),
        _build_pos_cash_closing_summary_line("Pengeluaran", expense_amount),
        _build_pos_cash_closing_summary_line("T.Uang", cash_on_hand_amount),
        "",
        f"Total Mataram dan Mega = {_format_pos_cash_closing_amount(combined_total_amount)}",
    ]
    safe_note = str(note or "").strip()
    if safe_note:
        message_lines.extend(["", f"Catatan: {safe_note}"])
    message_lines.extend(["", "Alhamdulillah"])
    return "\n".join(message_lines)


def _build_pos_cash_closing_preview_seed(warehouse_name, closing_date=None):
    return _build_pos_cash_closing_summary_message(
        warehouse_name,
        closing_date or _get_pos_today().isoformat(),
        cash_amount=0,
        debit_amount=0,
        qris_amount=0,
        mb_amount=0,
        cv_amount=0,
        expense_amount=0,
        cash_on_hand_amount=0,
        combined_total_amount=0,
        note="",
    )


def _resolve_pos_cash_closing_bucket_key(payment_method):
    normalized_method = _normalize_payment_method(payment_method, allow_split=False)
    if normalized_method == "cash":
        return "cash_amount"
    if normalized_method == "debit":
        return "debit_amount"
    if normalized_method == "qris":
        return "qris_amount"
    if normalized_method == "transfer":
        return "mb_amount"
    if normalized_method == "cv":
        return "cv_amount"
    return "cv_amount"


def _resolve_pos_cash_closing_combined_warehouse_ids(db):
    rows = db.execute("SELECT id, name FROM warehouses ORDER BY id ASC").fetchall()
    prioritized_ids = []
    fallback_ids = []
    for row in rows:
        warehouse_id = _to_int(row["id"], 0)
        if warehouse_id <= 0:
            continue
        fallback_ids.append(warehouse_id)
        warehouse_name = str(row["name"] or "").strip().lower()
        if "mataram" in warehouse_name or "mega" in warehouse_name:
            prioritized_ids.append(warehouse_id)
    return prioritized_ids or fallback_ids


def _fetch_pos_cash_closing_method_totals(db, closing_date, *, warehouse_id=None):
    safe_date = _normalize_pos_cash_closing_date(closing_date)
    params = [safe_date]
    where_clauses = ["ps.sale_date=?"]
    if _to_int(warehouse_id, 0) > 0:
        where_clauses.append("ps.warehouse_id=?")
        params.append(int(warehouse_id))

    rows = db.execute(
        f"""
        SELECT
            LOWER(COALESCE(ps.payment_method, 'cash')) AS payment_method,
            COALESCE(ps.total_amount, 0) AS total_amount,
            ps.payment_breakdown_json
        FROM pos_sales ps
        WHERE {" AND ".join(where_clauses)}
          AND COALESCE(ps.is_hidden_archive, 0)=0
        """,
        params,
    ).fetchall()

    totals = {
        "cash_amount": 0,
        "debit_amount": 0,
        "qris_amount": 0,
        "mb_amount": 0,
        "cv_amount": 0,
    }
    for row in rows:
        split_entries = _normalize_pos_payment_breakdown(row["payment_breakdown_json"])
        if split_entries:
            for split_entry in split_entries:
                bucket_key = _resolve_pos_cash_closing_bucket_key(split_entry["method"])
                totals[bucket_key] += max(int(round(float(split_entry["amount"] or 0))), 0)
            continue

        fallback_method = row["payment_method"]
        if _normalize_payment_method(fallback_method) == SPLIT_PAYMENT_METHOD:
            fallback_method = "cash"
        bucket_key = _resolve_pos_cash_closing_bucket_key(fallback_method)
        totals[bucket_key] += max(int(round(float(row["total_amount"] or 0))), 0)
    totals["reported_total_amount"] = (
        totals["cash_amount"]
        + totals["debit_amount"]
        + totals["qris_amount"]
        + totals["mb_amount"]
        + totals["cv_amount"]
    )
    return totals


def _fetch_pos_cash_closing_combined_total(db, closing_date):
    safe_date = _normalize_pos_cash_closing_date(closing_date)
    warehouse_ids = _resolve_pos_cash_closing_combined_warehouse_ids(db)
    if not warehouse_ids:
        return 0
    placeholders = ",".join("?" for _ in warehouse_ids)
    row = db.execute(
        f"""
        SELECT COALESCE(SUM(ps.total_amount), 0) AS total_amount
        FROM pos_sales ps
        WHERE ps.sale_date=?
          AND ps.warehouse_id IN ({placeholders})
          AND COALESCE(ps.is_hidden_archive, 0)=0
        """,
        [safe_date, *warehouse_ids],
    ).fetchone()
    return max(int(round(float((row["total_amount"] if row else 0) or 0))), 0)


def _build_pos_cash_closing_defaults(db, warehouse_name, closing_date, *, warehouse_id=None):
    safe_date = _normalize_pos_cash_closing_date(closing_date)
    method_totals = _fetch_pos_cash_closing_method_totals(
        db,
        safe_date,
        warehouse_id=warehouse_id,
    )
    combined_total_amount = _fetch_pos_cash_closing_combined_total(db, safe_date)
    expense_amount = 0
    cash_on_hand_amount = _round_pos_cash_on_hand(
        max(method_totals["cash_amount"] - expense_amount, 0)
    )
    defaults = {
        "closing_date": safe_date,
        "cash_amount": method_totals["cash_amount"],
        "debit_amount": method_totals["debit_amount"],
        "qris_amount": method_totals["qris_amount"],
        "mb_amount": method_totals["mb_amount"],
        "cv_amount": method_totals["cv_amount"],
        "reported_total_amount": method_totals["reported_total_amount"],
        "expense_amount": expense_amount,
        "cash_on_hand_amount": cash_on_hand_amount,
        "combined_total_amount": combined_total_amount,
    }
    for key in (
        "cash_amount",
        "debit_amount",
        "qris_amount",
        "mb_amount",
        "cv_amount",
        "reported_total_amount",
        "expense_amount",
        "cash_on_hand_amount",
        "combined_total_amount",
    ):
        defaults[f"{key}_label"] = _format_pos_cash_closing_amount(defaults[key], zero_label="0")
    defaults["preview_text"] = _build_pos_cash_closing_summary_message(
        warehouse_name,
        safe_date,
        cash_amount=defaults["cash_amount"],
        debit_amount=defaults["debit_amount"],
        qris_amount=defaults["qris_amount"],
        mb_amount=defaults["mb_amount"],
        cv_amount=defaults["cv_amount"],
        expense_amount=defaults["expense_amount"],
        cash_on_hand_amount=defaults["cash_on_hand_amount"],
        combined_total_amount=defaults["combined_total_amount"],
        note="",
    )
    return defaults


def _build_pos_cash_closing_wa_status_meta(status):
    safe_status = str(status or "").strip().lower()
    status_map = {
        "sent": {"label": "WA Terkirim", "badge_class": "green"},
        "partial": {"label": "WA Sebagian", "badge_class": "orange"},
        "failed": {"label": "WA Gagal", "badge_class": "red"},
        "skipped": {"label": "WA Belum Terkirim", "badge_class": ""},
        "pending": {"label": "WA Pending", "badge_class": ""},
    }
    return status_map.get(safe_status, status_map["pending"])


def _fetch_pos_cash_closing_actor(db, warehouse_id, raw_user_id=None):
    candidate_ids = []
    selected_user_id = _to_int(raw_user_id, 0)
    session_user_id = _to_int(session.get("user_id"), 0)
    if selected_user_id > 0:
        candidate_ids.append(selected_user_id)
    if session_user_id > 0 and session_user_id not in candidate_ids:
        candidate_ids.append(session_user_id)

    for candidate_id in candidate_ids:
        row = db.execute(
            """
            SELECT
                u.id,
                u.username,
                u.role,
                u.warehouse_id AS user_warehouse_id,
                u.employee_id,
                e.full_name,
                e.position,
                e.warehouse_id AS employee_warehouse_id,
                e.employment_status,
                w.name AS warehouse_name
            FROM users u
            LEFT JOIN employees e ON e.id = u.employee_id
            LEFT JOIN warehouses w ON w.id = COALESCE(e.warehouse_id, u.warehouse_id)
            WHERE u.id=?
            LIMIT 1
            """,
            (candidate_id,),
        ).fetchone()
        if not row:
            continue
        option = _build_pos_staff_option(row, warehouse_id)
        if option:
            return {
                "user_id": option["id"],
                "employee_id": _to_int(row["employee_id"], 0) or None,
                "display_name": option["display_name"],
                "label": option["label"],
                "position": str(row["position"] or "").strip(),
                "warehouse_name": str(row["warehouse_name"] or "").strip(),
                "username": str(row["username"] or "").strip(),
            }
        if candidate_id == session_user_id:
            display_name = str(row["full_name"] or row["username"] or session.get("username") or "Kasir").strip() or "Kasir"
            return {
                "user_id": candidate_id,
                "employee_id": _to_int(row["employee_id"], 0) or None,
                "display_name": display_name,
                "label": display_name,
                "position": str(row["position"] or "").strip(),
                "warehouse_name": str(row["warehouse_name"] or "").strip(),
                "username": str(row["username"] or "").strip(),
            }

    fallback_name = str(session.get("username") or "Kasir").strip() or "Kasir"
    return {
        "user_id": session_user_id or None,
        "employee_id": None,
        "display_name": fallback_name,
        "label": fallback_name,
        "position": "",
        "warehouse_name": "",
        "username": fallback_name,
    }


def _build_pos_cash_closing_return_url():
    query_string = request.query_string.decode("utf-8", errors="ignore").strip()
    if query_string:
        return f"/kasir/log?{query_string}"
    return "/kasir/log"


def _sanitize_pos_cash_closing_return_url(raw_value):
    safe_value = str(raw_value or "").strip()
    if not safe_value.startswith("/kasir/log"):
        return "/kasir/log"
    return safe_value


def _has_pos_cash_closing_report(db, sale_row):
    if not sale_row:
        return False

    row = db.execute(
        """
        SELECT id
        FROM cash_closing_reports
        WHERE warehouse_id=?
          AND closing_date=?
        LIMIT 1
        """,
        (
            sale_row.get("warehouse_id"),
            sale_row.get("sale_date"),
        ),
    ).fetchone()
    return row is not None


def _sync_pos_cash_closing_report_snapshot(db, sale_row):
    if not sale_row:
        return False

    warehouse_id = _to_int(sale_row.get("warehouse_id"), 0)
    closing_date = _normalize_pos_cash_closing_date(sale_row.get("sale_date"))
    if warehouse_id <= 0 or not closing_date:
        return False

    existing_report = db.execute(
        """
        SELECT
            ccr.id,
            ccr.expense_amount,
            ccr.note,
            COALESCE(NULLIF(TRIM(w.name), ''), '') AS warehouse_name
        FROM cash_closing_reports ccr
        LEFT JOIN warehouses w ON w.id = ccr.warehouse_id
        WHERE ccr.warehouse_id=?
          AND ccr.closing_date=?
        LIMIT 1
        """,
        (warehouse_id, closing_date),
    ).fetchone()
    if existing_report is None:
        return False

    warehouse_name = (
        str(existing_report["warehouse_name"] or "").strip()
        or str(sale_row.get("warehouse_name") or "").strip()
        or f"WH {warehouse_id}"
    )
    method_totals = _fetch_pos_cash_closing_method_totals(
        db,
        closing_date,
        warehouse_id=warehouse_id,
    )
    combined_total_amount = _fetch_pos_cash_closing_combined_total(db, closing_date)
    expense_amount = max(_to_int(existing_report["expense_amount"], 0), 0)
    cash_on_hand_amount = _round_pos_cash_on_hand(
        max(method_totals["cash_amount"] - expense_amount, 0)
    )
    summary_message = _build_pos_cash_closing_summary_message(
        warehouse_name,
        closing_date,
        cash_amount=method_totals["cash_amount"],
        debit_amount=method_totals["debit_amount"],
        qris_amount=method_totals["qris_amount"],
        mb_amount=method_totals["mb_amount"],
        cv_amount=method_totals["cv_amount"],
        expense_amount=expense_amount,
        cash_on_hand_amount=cash_on_hand_amount,
        combined_total_amount=combined_total_amount,
        note=str(existing_report["note"] or "").strip(),
    )

    db.execute(
        """
        UPDATE cash_closing_reports
        SET
            cash_amount=?,
            debit_amount=?,
            qris_amount=?,
            mb_amount=?,
            cv_amount=?,
            reported_total_amount=?,
            cash_on_hand_amount=?,
            combined_total_amount=?,
            summary_message=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            method_totals["cash_amount"],
            method_totals["debit_amount"],
            method_totals["qris_amount"],
            method_totals["mb_amount"],
            method_totals["cv_amount"],
            method_totals["reported_total_amount"],
            cash_on_hand_amount,
            combined_total_amount,
            summary_message,
            existing_report["id"],
        ),
    )
    return True


def _fetch_pos_cash_closing_reports(
    db,
    warehouse_id=None,
    cashier_user_id=None,
    date_from=None,
    date_to=None,
    limit=8,
):
    safe_limit = max(1, min(_to_int(limit, 8), 40))
    params = []
    query = """
        SELECT
            ccr.id,
            ccr.user_id,
            ccr.employee_id,
            ccr.warehouse_id,
            ccr.closing_date,
            ccr.cash_amount,
            ccr.debit_amount,
            ccr.qris_amount,
            ccr.mb_amount,
            ccr.cv_amount,
            ccr.reported_total_amount,
            ccr.expense_amount,
            ccr.cash_on_hand_amount,
            ccr.combined_total_amount,
            ccr.note,
            ccr.summary_message,
            ccr.wa_status,
            ccr.wa_error,
            ccr.wa_delivery_count,
            ccr.wa_success_count,
            ccr.created_at,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS cashier_name,
            COALESCE(NULLIF(TRIM(e.position), ''), COALESCE(NULLIF(TRIM(u.role), ''), 'Staff')) AS cashier_position,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM cash_closing_reports ccr
        LEFT JOIN users u ON u.id = ccr.user_id
        LEFT JOIN employees e ON e.id = COALESCE(ccr.employee_id, u.employee_id)
        LEFT JOIN warehouses w ON w.id = ccr.warehouse_id
        WHERE 1=1
    """

    if warehouse_id:
        query += " AND ccr.warehouse_id=?"
        params.append(int(warehouse_id))

    if cashier_user_id:
        query += " AND ccr.user_id=?"
        params.append(int(cashier_user_id))

    if date_from:
        query += " AND ccr.closing_date >= ?"
        params.append(str(date_from))

    if date_to:
        query += " AND ccr.closing_date <= ?"
        params.append(str(date_to))

    query += """
        ORDER BY ccr.closing_date DESC, ccr.id DESC
        LIMIT ?
    """
    params.append(safe_limit)

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    report_items = []
    for row in rows:
        wa_meta = _build_pos_cash_closing_wa_status_meta(row.get("wa_status"))
        report_items.append(
            {
                "id": row["id"],
                "cash_amount": int(row.get("cash_amount") or 0),
                "debit_amount": int(row.get("debit_amount") or 0),
                "qris_amount": int(row.get("qris_amount") or 0),
                "mb_amount": int(row.get("mb_amount") or 0),
                "cv_amount": int(row.get("cv_amount") or 0),
                "expense_amount": int(row.get("expense_amount") or 0),
                "cash_on_hand_amount": int(row.get("cash_on_hand_amount") or 0),
                "combined_total_amount": int(row.get("combined_total_amount") or 0),
                "closing_date": str(row.get("closing_date") or "").strip(),
                "note": str(row.get("note") or "").strip(),
                "cashier_name": row["cashier_name"],
                "cashier_position": row["cashier_position"],
                "warehouse_name": row["warehouse_name"],
                "warehouse_label": format_receipt_homebase_label(row.get("warehouse_name")),
                "closing_date_label": _format_pos_cash_closing_date_label(row.get("closing_date")),
                "created_at_label": _format_pos_time_label(row.get("created_at")),
                "summary_message": (row.get("summary_message") or "").strip(),
                "wa_status": str(row.get("wa_status") or "pending").strip().lower() or "pending",
                "wa_status_label": wa_meta["label"],
                "wa_status_badge": wa_meta["badge_class"],
                "wa_error": str(row.get("wa_error") or "").strip(),
                "wa_delivery_count": int(row.get("wa_delivery_count") or 0),
                "wa_success_count": int(row.get("wa_success_count") or 0),
                "summary_total_label": _format_pos_cash_closing_amount(row.get("reported_total_amount"), zero_label="0"),
                "combined_total_label": _format_pos_cash_closing_amount(row.get("combined_total_amount")),
            }
        )
    return report_items


def _fetch_pos_sale_item_map(db, purchase_ids):
    normalized_ids = [int(purchase_id) for purchase_id in purchase_ids if _to_int(purchase_id, 0) > 0]
    if not normalized_ids:
        return {}

    placeholders = ",".join("?" for _ in normalized_ids)
    rows = db.execute(
        f"""
        SELECT
            cpi.purchase_id,
            COALESCE(NULLIF(TRIM(p.sku), ''), '-') AS sku,
            COALESCE(NULLIF(TRIM(p.name), ''), 'Produk') AS product_name,
            COALESCE(NULLIF(TRIM(pv.variant), ''), 'default') AS variant_name,
            COALESCE(cpi.qty, 0) AS qty,
            COALESCE(cpi.retail_price, 0) AS retail_price,
            COALESCE(cpi.unit_price, 0) AS unit_price,
            COALESCE(cpi.line_total, 0) AS line_total
        FROM crm_purchase_items cpi
        LEFT JOIN products p ON p.id = cpi.product_id
        LEFT JOIN product_variants pv ON pv.id = cpi.variant_id
        WHERE cpi.purchase_id IN ({placeholders})
        ORDER BY cpi.purchase_id ASC, cpi.id ASC
        """,
        normalized_ids,
    ).fetchall()

    item_map = {}
    for row in rows:
        purchase_id = int(row["purchase_id"])
        unit_price = _currency(row["unit_price"] or 0)
        retail_price = _currency(row["retail_price"] or 0)
        line_total = _currency(row["line_total"] or 0)
        unit_discount = max(retail_price - unit_price, 0)
        total_discount = max(unit_discount * int(row["qty"] or 0), 0)
        item_map.setdefault(purchase_id, []).append(
            {
                "sku": row["sku"],
                "product_name": row["product_name"],
                "variant_name": row["variant_name"],
                "qty": int(row["qty"] or 0),
                "retail_price": retail_price,
                "unit_price": unit_price,
                "line_total": line_total,
                "unit_discount": unit_discount,
                "total_discount": total_discount,
                "has_discount": unit_discount > 0,
                "retail_price_label": _format_pos_currency_label(retail_price),
                "unit_price_label": _format_pos_currency_label(unit_price),
                "line_total_label": _format_pos_currency_label(line_total),
                "unit_discount_label": _format_pos_currency_label(unit_discount),
                "total_discount_label": _format_pos_currency_label(total_discount),
                "summary_label": f"{row['sku']} · {row['product_name']} · {row['variant_name']} x{int(row['qty'] or 0)}",
            }
        )
    return item_map


def _fetch_pos_sale_logs(
    db,
    date_from,
    date_to,
    selected_warehouse=None,
    cashier_user_id=None,
    search_query="",
    limit=60,
    receipt_wa_status=None,
    archive_mode="visible",
):
    safe_limit = max(1, min(_to_int(limit, 60), 200))
    params = [date_from, date_to]
    query = f"""
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.source_cashier_name,
            ps.source_sales_name,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.payment_breakdown_json,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.note,
            ps.created_at,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            {POS_CASHIER_NAME_SQL} AS cashier_name,
            {POS_CASHIER_USERNAME_SQL} AS cashier_username,
            {POS_CASHIER_POSITION_SQL} AS cashier_position,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = ps.warehouse_id
        WHERE ps.sale_date BETWEEN ? AND ?
    """

    if selected_warehouse:
        query += " AND ps.warehouse_id=?"
        params.append(int(selected_warehouse))

    if cashier_user_id:
        query += " AND ps.cashier_user_id=?"
        params.append(int(cashier_user_id))

    safe_search_query = str(search_query or "").strip()
    if safe_search_query:
        search_pattern = f"%{safe_search_query}%"
        query += """
            AND (
                ps.receipt_no LIKE ?
                OR COALESCE(c.customer_name, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR COALESCE(e.full_name, u.username, '') LIKE ?
                OR COALESCE(ps.note, '') LIKE ?
                OR COALESCE(ps.hidden_archive_note, '') LIKE ?
            )
        """
        params.extend([search_pattern] * 6)

    safe_receipt_wa_status = str(receipt_wa_status or "").strip().lower()
    if safe_receipt_wa_status:
        query += " AND LOWER(COALESCE(ps.receipt_whatsapp_status, 'pending'))=?"
        params.append(safe_receipt_wa_status)

    query += """
        ORDER BY ps.sale_date DESC, ps.id DESC
        LIMIT ?
    """
    params.append(safe_limit)

    header_rows = [dict(row) for row in db.execute(query, params).fetchall()]
    item_map = _fetch_pos_sale_item_map(db, [row["purchase_id"] for row in header_rows])
    normalized_rows = []

    for row in header_rows:
        items = item_map.get(int(row["purchase_id"]), [])
        total_amount = _currency(row.get("total_amount") or 0)
        paid_amount = _currency(row.get("paid_amount") or 0)
        change_amount = _currency(row.get("change_amount") or 0)
        payment_meta = _build_pos_sale_payment_meta(
            row.get("payment_method"),
            paid_amount,
            row.get("payment_breakdown_json"),
        )
        payment_method_label = _format_payment_method_label(row.get("payment_method"))
        created_time_label = _format_pos_time_label(row.get("created_at"))
        item_preview_lines = items[:3]

        normalized_rows.append(
            {
                **row,
                "total_items": int(row.get("total_items") or 0),
                "total_amount": total_amount,
                "paid_amount": paid_amount,
                "change_amount": change_amount,
                "total_amount_label": _format_pos_currency_label(total_amount),
                "paid_amount_label": _format_pos_currency_label(paid_amount),
                "change_amount_label": _format_pos_currency_label(change_amount),
                "payment_method_label": payment_method_label,
                "has_payment_breakdown": payment_meta["has_payment_breakdown"],
                "payment_breakdown_entries": payment_meta["payment_breakdown_entries"],
                "payment_breakdown_label": payment_meta["payment_breakdown_label"],
                "created_time_label": created_time_label,
                "created_datetime_label": f"{row['sale_date']} {created_time_label}" if created_time_label != "-" else row["sale_date"],
                "customer_phone_label": row["customer_phone"] if row.get("customer_phone") and row["customer_phone"] != "-" else "Tanpa nomor",
                "cashier_identity_label": f"{row['cashier_name']} · {row['cashier_position']}",
                "items": items,
                "item_preview_lines": item_preview_lines,
                "item_preview_more": max(len(items) - len(item_preview_lines), 0),
                "receipt_print_url": f"/kasir/receipt/{row['receipt_no']}/print",
                "receipt_thermal_url": (
                    f"/kasir/receipt/{row['receipt_no']}/print"
                    f"?layout=thermal&copy=customer&autoprint=1&autoclose=1"
                ),
                "receipt_pdf_url": f"/kasir/receipt/{row['receipt_no']}/print?autoprint=1",
            }
        )

    return normalized_rows


def _build_pos_sale_log_summary(rows, period_label):
    total_items = sum(int(row.get("total_items") or 0) for row in rows)
    total_revenue = sum(float(row.get("total_amount") or 0) for row in rows)
    customer_total = len({int(row.get("customer_id") or 0) for row in rows if _to_int(row.get("customer_id"), 0) > 0})
    staff_total = len(
        {
            str(row.get("staff_group_key") or "").strip().lower()
            for row in rows
            if str(row.get("staff_group_key") or "").strip()
        }
    )
    return {
        "period_label": period_label,
        "transaction_total": len(rows),
        "total_items": total_items,
        "customer_total": customer_total,
        "staff_total": staff_total,
        "total_revenue": total_revenue,
        "total_revenue_label": _format_pos_currency_label(total_revenue),
        "average_ticket_label": _format_pos_currency_label(total_revenue / len(rows) if rows else 0),
    }


def _fetch_pos_sale_detail_by_receipt(db, receipt_no):
    safe_receipt = str(receipt_no or "").strip()
    if not safe_receipt:
        return None

    params = [safe_receipt]
    query = f"""
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.source_cashier_name,
            ps.source_sales_name,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.payment_breakdown_json,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.note,
            ps.created_at,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            {POS_CASHIER_NAME_SQL} AS cashier_name,
            {POS_CASHIER_USERNAME_SQL} AS cashier_username,
            {POS_CASHIER_POSITION_SQL} AS cashier_position,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = ps.warehouse_id
        WHERE ps.receipt_no=?
    """

    if is_scoped_role(session.get("role")):
        query += " AND ps.warehouse_id=?"
        params.append(session.get("warehouse_id"))

    query += " LIMIT 1"
    try:
        row = db.execute(query, params).fetchone()
    except Exception:
        legacy_query = f"""
            SELECT
                ps.id,
                ps.purchase_id,
                ps.customer_id,
                ps.cashier_user_id,
                ps.warehouse_id,
                ps.sale_date,
                ps.receipt_no,
                ps.payment_method,
                ps.payment_breakdown_json,
                ps.total_items,
                ps.total_amount,
                ps.paid_amount,
                ps.change_amount,
                ps.status,
                ps.receipt_pdf_path,
                ps.receipt_pdf_url,
                ps.receipt_whatsapp_status,
                ps.receipt_whatsapp_error,
                ps.receipt_whatsapp_sent_at,
                ps.note,
                ps.created_at,
                pr.member_id,
                pr.transaction_type,
                COALESCE(NULLIF(TRIM(m.member_code), ''), '') AS member_code,
                COALESCE(NULLIF(TRIM(m.member_type), ''), '') AS member_type,
                COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
                COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
                {POS_CASHIER_NAME_SQL} AS cashier_name,
                {POS_CASHIER_USERNAME_SQL} AS cashier_username,
                {POS_CASHIER_POSITION_SQL} AS cashier_position,
                COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
            FROM pos_sales ps
            LEFT JOIN crm_purchase_records pr ON pr.id = ps.purchase_id
            LEFT JOIN crm_memberships m ON m.id = pr.member_id
            JOIN crm_customers c ON c.id = ps.customer_id
            LEFT JOIN users u ON u.id = ps.cashier_user_id
            LEFT JOIN employees e ON e.id = u.employee_id
            LEFT JOIN warehouses w ON w.id = ps.warehouse_id
            WHERE ps.receipt_no=?
        """
        if is_scoped_role(session.get("role")):
            legacy_query += " AND ps.warehouse_id=?"
        legacy_query += " LIMIT 1"
        row = db.execute(legacy_query, params).fetchone()
    if not row:
        return None

    sale = dict(row)
    sale.setdefault("subtotal_amount", sale.get("total_amount") or 0)
    sale.setdefault("discount_type", "")
    sale.setdefault("discount_value", 0)
    sale.setdefault("discount_amount", 0)
    sale.setdefault("tax_type", "")
    sale.setdefault("tax_value", 0)
    sale.setdefault("tax_amount", 0)
    items = _fetch_pos_sale_item_map(db, [sale["purchase_id"]]).get(int(sale["purchase_id"]), [])
    total_amount = _currency(sale.get("total_amount") or 0)
    paid_amount = _currency(sale.get("paid_amount") or 0)
    change_amount = _currency(sale.get("change_amount") or 0)
    created_time_label = _format_pos_time_label(sale.get("created_at"))

    sale_detail = {
        **sale,
        "items": items,
        "total_items": int(sale.get("total_items") or 0),
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "change_amount": change_amount,
        "total_amount_label": _format_pos_currency_label(total_amount),
        "paid_amount_label": _format_pos_currency_label(paid_amount),
        "change_amount_label": _format_pos_currency_label(change_amount),
        "payment_method_label": _format_payment_method_label(sale.get("payment_method")),
        "created_time_label": created_time_label,
        "created_datetime_label": f"{sale['sale_date']} {created_time_label}" if created_time_label != "-" else sale["sale_date"],
        "customer_phone_label": sale["customer_phone"] if sale.get("customer_phone") and sale["customer_phone"] != "-" else "Tanpa nomor",
        "cashier_identity_label": f"{sale['cashier_name']} · {sale['cashier_position']}",
    }


def _format_pos_currency_label(value):
    return f"Rp {int(round(float(value or 0))):,}".replace(",", ".")


def _format_pos_adjustment_rule_label(adjustment_type, adjustment_value):
    safe_type = _normalize_adjustment_type(adjustment_type)
    safe_value = _to_decimal(adjustment_value, "0")
    if safe_value <= 0:
        return "-"
    if safe_type == "percent":
        normalized_value = safe_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if normalized_value == normalized_value.to_integral():
            return f"{int(normalized_value)}%"
        return f"{normalized_value.normalize()}%"
    return _format_pos_currency_label(safe_value)


def _format_pos_period_label(date_from, date_to):
    if not date_from:
        return "-"
    if date_from == date_to:
        return date_from
    return f"{date_from} s/d {date_to}"


def _format_pos_month_label(month_value):
    try:
        target = date_cls.fromisoformat(f"{month_value}-01")
    except ValueError:
        return month_value or "-"

    month_names = [
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
    ]
    return f"{month_names[target.month - 1]} {target.year}"


def _resolve_week_range(raw_reference_date):
    reference_date = date_cls.fromisoformat(_normalize_sale_date(raw_reference_date))
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)
    return {
        "reference_date": reference_date.isoformat(),
        "date_from": week_start.isoformat(),
        "date_to": week_end.isoformat(),
        "label": _format_pos_period_label(week_start.isoformat(), week_end.isoformat()),
    }


def _resolve_month_range(raw_month_value):
    month_value = _normalize_sale_month(raw_month_value)
    month_start = date_cls.fromisoformat(f"{month_value}-01")
    if month_start.month == 12:
        next_month_start = date_cls(month_start.year + 1, 1, 1)
    else:
        next_month_start = date_cls(month_start.year, month_start.month + 1, 1)
    month_end = next_month_start - timedelta(days=1)
    return {
        "month_value": month_value,
        "date_from": month_start.isoformat(),
        "date_to": month_end.isoformat(),
        "label": _format_pos_month_label(month_value),
    }


def _fetch_pos_staff_sales_rows(db, date_from, date_to, selected_warehouse=None):
    params = [date_from, date_to]
    query = f"""
        SELECT
            {POS_CASHIER_GROUP_KEY_SQL} AS staff_group_key,
            MIN(ps.cashier_user_id) AS cashier_user_id,
            {POS_CASHIER_NAME_SQL} AS staff_name,
            {POS_CASHIER_USERNAME_SQL} AS username,
            {POS_CASHIER_POSITION_SQL} AS position,
            COALESCE(MAX(NULLIF(TRIM(home_w.name), '')), '-') AS home_warehouse_name,
            COUNT(ps.id) AS total_transactions,
            COALESCE(SUM(ps.total_items), 0) AS total_items,
            COALESCE(SUM(ps.total_amount), 0) AS total_revenue,
            COALESCE(AVG(ps.total_amount), 0) AS average_ticket,
            COUNT(DISTINCT ps.customer_id) AS total_customers,
            COUNT(DISTINCT ps.warehouse_id) AS total_warehouses,
            GROUP_CONCAT(DISTINCT COALESCE(NULLIF(TRIM(sale_w.name), ''), '-')) AS warehouse_names,
            MIN(ps.sale_date) AS first_sale_date,
            MAX(ps.sale_date) AS last_sale_date
        FROM pos_sales ps
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses home_w ON home_w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        LEFT JOIN warehouses sale_w ON sale_w.id = ps.warehouse_id
        WHERE ps.sale_date BETWEEN ? AND ?
    """
    if selected_warehouse:
        query += " AND ps.warehouse_id=?"
        params.append(selected_warehouse)

    query += """
        GROUP BY
    """
    query += f"""
            {POS_CASHIER_GROUP_KEY_SQL},
            {POS_CASHIER_NAME_SQL},
            {POS_CASHIER_USERNAME_SQL},
            {POS_CASHIER_POSITION_SQL}
        ORDER BY total_revenue DESC, total_transactions DESC, LOWER(CAST({POS_CASHIER_NAME_SQL} AS TEXT)) ASC
    """

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    normalized_rows = []
    for index, row in enumerate(rows, start=1):
        total_revenue = _currency(row.get("total_revenue") or 0)
        average_ticket = _currency(row.get("average_ticket") or 0)
        warehouse_scope_label = (row.get("warehouse_names") or "").strip() or row.get("home_warehouse_name") or "-"
        normalized_rows.append(
            {
                **row,
                "rank": index,
                "total_transactions": int(row.get("total_transactions") or 0),
                "total_items": int(row.get("total_items") or 0),
                "total_customers": int(row.get("total_customers") or 0),
                "total_warehouses": int(row.get("total_warehouses") or 0),
                "total_revenue": total_revenue,
                "average_ticket": average_ticket,
                "total_revenue_label": _format_pos_currency_label(total_revenue),
                "average_ticket_label": _format_pos_currency_label(average_ticket),
                "warehouse_scope_label": warehouse_scope_label,
                "activity_label": _format_pos_period_label(row.get("first_sale_date"), row.get("last_sale_date")),
            }
        )
    return normalized_rows


def _build_pos_staff_sales_summary(rows, period_label):
    total_transactions = sum(int(row.get("total_transactions") or 0) for row in rows)
    total_items = sum(int(row.get("total_items") or 0) for row in rows)
    total_revenue = sum(float(row.get("total_revenue") or 0) for row in rows)
    top_staff = rows[0] if rows else None
    return {
        "period_label": period_label,
        "staff_total": len(rows),
        "total_transactions": total_transactions,
        "total_items": total_items,
        "total_revenue": total_revenue,
        "total_revenue_label": _format_pos_currency_label(total_revenue),
        "average_ticket_label": _format_pos_currency_label(total_revenue / total_transactions if total_transactions else 0),
        "top_staff_name": top_staff["staff_name"] if top_staff else "-",
        "top_staff_revenue_label": top_staff["total_revenue_label"] if top_staff else _format_pos_currency_label(0),
    }


def _build_next_receipt_no(db, sale_date):
    date_key = sale_date.replace("-", "")
    prefix = f"POS-{date_key}-"
    latest = db.execute(
        """
        SELECT receipt_no
        FROM pos_sales
        WHERE receipt_no LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"{prefix}%",),
    ).fetchone()

    if not latest or not latest["receipt_no"]:
        return f"{prefix}0001"

    tail = str(latest["receipt_no"]).replace(prefix, "", 1)
    next_seq = _to_int(tail, 0) + 1
    return f"{prefix}{str(next_seq).zfill(4)}"


def _resolve_or_create_customer(db, warehouse_id, customer_id, customer_name, customer_phone):
    safe_phone = _normalize_pos_phone(customer_phone)
    if customer_id > 0:
        customer = db.execute(
            """
            SELECT id, warehouse_id, customer_name, phone
            FROM crm_customers
            WHERE id=?
            """,
            (customer_id,),
        ).fetchone()
        if not customer or int(customer["warehouse_id"] or 0) != int(warehouse_id):
            raise ValueError("Customer tidak valid untuk gudang aktif.")
        current_phone = _normalize_pos_phone(customer["phone"])
        if safe_phone and safe_phone != current_phone:
            db.execute(
                """
                UPDATE crm_customers
                SET phone=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (safe_phone, customer_id),
            )
            customer = db.execute(
                """
                SELECT id, warehouse_id, customer_name, phone
                FROM crm_customers
                WHERE id=?
                """,
                (customer_id,),
            ).fetchone()
        return customer

    safe_name = (customer_name or "").strip() or "Walk-in Customer"
    existing_identity = find_matching_customer_identity(
        db,
        warehouse_id,
        phone=safe_phone,
        customer_name=safe_name,
    )
    if existing_identity:
        persisted_phone = str(existing_identity["phone"] or "").strip() or None
        next_phone = safe_phone or persisted_phone
        db.execute(
            """
            UPDATE crm_customers
            SET
                customer_name=?,
                contact_person=?,
                phone=?,
                customer_type='member',
                marketing_channel=COALESCE(NULLIF(marketing_channel, ''), 'pos'),
                note=COALESCE(NULLIF(note, ''), 'Merged by POS loyalty identity'),
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                safe_name,
                safe_name,
                safe_phone,
                existing_identity["id"],
            ),
        )
        return db.execute(
            """
            SELECT id, warehouse_id, customer_name, phone
            FROM crm_customers
            WHERE id=?
            """,
            (existing_identity["id"],),
        ).fetchone()

    cursor = db.execute(
        """
        INSERT INTO crm_customers(
            warehouse_id,
            customer_name,
            contact_person,
            phone,
            customer_type,
            marketing_channel,
            note
        )
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            warehouse_id,
            safe_name,
            safe_name if safe_name.lower() != "walk-in customer" else None,
            safe_phone or None,
            "retail",
            "pos",
            "Auto-created by POS checkout",
        ),
    )
    created = db.execute(
        """
        SELECT id, warehouse_id, customer_name, phone
        FROM crm_customers
        WHERE id=?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return created


def _resolve_pos_customer_identity(db, warehouse_id, customer_id, customer_name, customer_phone):
    safe_name = (customer_name or "").strip()
    safe_phone = _normalize_pos_phone(customer_phone)
    safe_customer_id = _to_int(customer_id, 0)

    if safe_customer_id > 0 and (not safe_name or not safe_phone):
        customer = db.execute(
            """
            SELECT customer_name, phone
            FROM crm_customers
            WHERE id=? AND warehouse_id=?
            """,
            (safe_customer_id, warehouse_id),
        ).fetchone()
        if customer:
            if not safe_name:
                safe_name = str(customer["customer_name"] or "").strip()
            if not safe_phone:
                safe_phone = _normalize_pos_phone(customer["phone"])

    return safe_name, safe_phone


def _fetch_active_customer_member(db, customer_id):
    safe_customer_id = _to_int(customer_id, 0)
    if safe_customer_id <= 0:
        return None
    return db.execute(
        """
        SELECT *
        FROM crm_memberships
        WHERE customer_id=? AND status='active'
        ORDER BY id DESC
        LIMIT 1
        """,
        (safe_customer_id,),
    ).fetchone()


def _fetch_active_customer_member_by_type(db, customer_id, member_type):
    safe_customer_id = _to_int(customer_id, 0)
    normalized_member_type = normalize_member_type(member_type)
    if safe_customer_id <= 0 or not normalized_member_type:
        return None
    return db.execute(
        """
        SELECT *
        FROM crm_memberships
        WHERE customer_id=? AND member_type=? AND status='active'
        ORDER BY id DESC
        LIMIT 1
        """,
        (safe_customer_id, normalized_member_type),
    ).fetchone()


POS_STRINGING_CATEGORY_KEYWORDS = (
    "senar",
    "string",
    "stringing",
)


def _normalize_pos_loyalty_keyword_text(value):
    return " ".join(str(value or "").strip().lower().split())


def _is_pos_stringing_loyalty_item(item):
    if not isinstance(item, dict):
        return False
    keyword_pool = " ".join(
        _normalize_pos_loyalty_keyword_text(item.get(field))
        for field in ("category_name", "product_name", "sku", "variant_name")
    )
    if not keyword_pool:
        return False
    return any(keyword in keyword_pool for keyword in POS_STRINGING_CATEGORY_KEYWORDS)


def _split_pos_loyalty_items(items, transaction_type=None):
    safe_transaction_type = normalize_transaction_type(transaction_type)
    safe_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    purchase_items = []
    stringing_items = []
    for item in safe_items:
        if _is_pos_stringing_loyalty_item(item):
            stringing_items.append(item)
        else:
            purchase_items.append(item)
    if (
        safe_transaction_type == "stringing_service"
        and safe_items
        and not stringing_items
    ):
        return [], list(safe_items)
    return purchase_items, stringing_items


def _sum_pos_loyalty_item_amount(items):
    total = Decimal("0.00")
    for item in items if isinstance(items, list) else []:
        total += _to_decimal(item.get("line_total") or 0, "0")
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _resolve_pos_member_for_type(
    db,
    customer,
    warehouse_id,
    sale_date,
    member_type,
    *,
    requested_by_user_id=None,
    allow_auto_create=True,
):
    safe_customer = dict(customer or {})
    normalized_member_type = normalize_member_type(member_type)
    if normalized_member_type not in {"purchase", "stringing"}:
        return None, None

    active_member = _fetch_active_customer_member_by_type(db, safe_customer.get("id"), normalized_member_type)
    if active_member:
        return active_member, get_member_snapshot(db, active_member["id"])

    matching_member = find_matching_member_identity(
        db,
        warehouse_id,
        normalized_member_type,
        phone=safe_customer.get("phone"),
        customer_name=safe_customer.get("customer_name"),
    )
    if matching_member:
        return matching_member, get_member_snapshot(db, matching_member["id"])

    if not allow_auto_create:
        return None, None

    if normalized_member_type == "purchase":
        created_member = _auto_create_pos_purchase_member(
            db,
            customer,
            warehouse_id,
            sale_date,
            requested_by_user_id=requested_by_user_id,
        )
    else:
        created_member = _auto_create_pos_stringing_member(
            db,
            customer,
            warehouse_id,
            sale_date,
            requested_by_user_id=requested_by_user_id,
        )
    if not created_member:
        return None, None
    return created_member, get_member_snapshot(db, created_member["id"])


def _derive_pos_loyalty_sale_transaction_type(transaction_type, items):
    safe_transaction_type = normalize_transaction_type(transaction_type)
    if safe_transaction_type == "stringing_reward_redemption":
        return safe_transaction_type
    purchase_items, stringing_items = _split_pos_loyalty_items(items, safe_transaction_type)
    if stringing_items and not purchase_items:
        return "stringing_service"
    return "purchase"


def _resolve_pos_loyalty_members_for_sale(
    db,
    customer,
    warehouse_id,
    sale_date,
    transaction_type,
    items,
    *,
    requested_by_user_id=None,
):
    safe_transaction_type = normalize_transaction_type(transaction_type)
    safe_customer = dict(customer or {})
    ensure_crm_membership_multi_program_schema(db)
    reconcile_member_identity_duplicates(db, warehouse_id=warehouse_id)

    purchase_items, stringing_items = _split_pos_loyalty_items(items, safe_transaction_type)
    resolved = {
        "purchase": {"member": None, "snapshot": None, "items": purchase_items},
        "stringing": {"member": None, "snapshot": None, "items": stringing_items},
    }

    if safe_transaction_type == "stringing_reward_redemption":
        stringing_member, stringing_snapshot = _resolve_pos_member_for_type(
            db,
            safe_customer,
            warehouse_id,
            sale_date,
            "stringing",
            requested_by_user_id=requested_by_user_id,
            allow_auto_create=False,
        )
        if not stringing_member:
            raise ValueError("Free reward senaran hanya bisa dipakai oleh customer dengan Member Senaran aktif.")
        resolved["stringing"]["member"] = stringing_member
        resolved["stringing"]["snapshot"] = stringing_snapshot
        return resolved

    if purchase_items:
        purchase_member, purchase_snapshot = _resolve_pos_member_for_type(
            db,
            safe_customer,
            warehouse_id,
            sale_date,
            "purchase",
            requested_by_user_id=requested_by_user_id,
        )
        resolved["purchase"]["member"] = purchase_member
        resolved["purchase"]["snapshot"] = purchase_snapshot

    if stringing_items:
        stringing_member, stringing_snapshot = _resolve_pos_member_for_type(
            db,
            safe_customer,
            warehouse_id,
            sale_date,
            "stringing",
            requested_by_user_id=requested_by_user_id,
        )
        resolved["stringing"]["member"] = stringing_member
        resolved["stringing"]["snapshot"] = stringing_snapshot

    return resolved


def _choose_primary_pos_loyalty_member(loyalty_members, transaction_type):
    safe_members = loyalty_members if isinstance(loyalty_members, dict) else {}
    safe_transaction_type = normalize_transaction_type(transaction_type)
    if safe_transaction_type in {"stringing_service", "stringing_reward_redemption"}:
        primary = (safe_members.get("stringing") or {}).get("member")
        if primary:
            return primary
    purchase_primary = (safe_members.get("purchase") or {}).get("member")
    if purchase_primary:
        return purchase_primary
    return (safe_members.get("stringing") or {}).get("member")


def _build_pos_loyalty_member_records(
    purchase_id,
    warehouse_id,
    sale_date,
    reference_no,
    note,
    handled_by,
    items,
    loyalty_members,
    *,
    source_label,
    transaction_type,
):
    safe_transaction_type = normalize_transaction_type(transaction_type)
    safe_loyalty_members = loyalty_members if isinstance(loyalty_members, dict) else {}
    purchase_items, stringing_items = _split_pos_loyalty_items(items, safe_transaction_type)
    records = []

    if safe_transaction_type == "stringing_reward_redemption":
        stringing_state = safe_loyalty_members.get("stringing") or {}
        stringing_member = stringing_state.get("member")
        stringing_snapshot = stringing_state.get("snapshot")
        if stringing_member:
            records.append(
                build_auto_member_record(
                    stringing_snapshot or dict(stringing_member),
                    stringing_snapshot or dict(stringing_member),
                    purchase_id=purchase_id,
                    warehouse_id=warehouse_id,
                    record_date=sale_date,
                    reference_no=reference_no,
                    amount=_currency(_sum_pos_loyalty_item_amount(items)),
                    transaction_type="stringing_reward_redemption",
                    note=note or "",
                    handled_by=handled_by,
                    source_label=source_label,
                    items=items,
                )
            )
        return records

    purchase_state = safe_loyalty_members.get("purchase") or {}
    purchase_member = purchase_state.get("member")
    purchase_snapshot = purchase_state.get("snapshot")
    if purchase_member and purchase_items:
        records.append(
            build_auto_member_record(
                purchase_snapshot or dict(purchase_member),
                purchase_snapshot or dict(purchase_member),
                purchase_id=purchase_id,
                warehouse_id=warehouse_id,
                record_date=sale_date,
                reference_no=reference_no,
                amount=_currency(_sum_pos_loyalty_item_amount(purchase_items)),
                transaction_type="purchase",
                note=note or "",
                handled_by=handled_by,
                source_label=source_label,
                items=purchase_items,
            )
        )

    stringing_state = safe_loyalty_members.get("stringing") or {}
    stringing_member = stringing_state.get("member")
    stringing_snapshot = stringing_state.get("snapshot")
    if stringing_member and stringing_items:
        records.append(
            build_auto_member_record(
                stringing_snapshot or dict(stringing_member),
                stringing_snapshot or dict(stringing_member),
                purchase_id=purchase_id,
                warehouse_id=warehouse_id,
                record_date=sale_date,
                reference_no=reference_no,
                amount=_currency(_sum_pos_loyalty_item_amount(stringing_items)),
                transaction_type="stringing_service",
                note=note or "",
                handled_by=handled_by,
                source_label=source_label,
                items=stringing_items,
            )
        )

    return records


def _build_next_pos_member_code(db, warehouse_id, *, member_type):
    safe_warehouse_id = max(_to_int(warehouse_id, 0), 0)
    normalized_member_type = normalize_member_type(member_type)
    prefix_map = {
        "purchase": "POS-POINT",
        "stringing": "POS-SENAR",
    }
    prefix = f"{prefix_map.get(normalized_member_type, 'POS-MEMBER')}-{safe_warehouse_id:02d}-"
    rows = db.execute(
        "SELECT member_code FROM crm_memberships WHERE member_code LIKE ?",
        (f"{prefix}%",),
    ).fetchall()

    latest_sequence = 0
    for row in rows:
        member_code = str(row["member_code"] or "").strip().upper()
        if not member_code.startswith(prefix):
            continue
        tail = member_code[len(prefix):]
        if tail.isdigit():
            latest_sequence = max(latest_sequence, int(tail))

    return f"{prefix}{latest_sequence + 1:04d}"


def _auto_create_pos_purchase_member(db, customer, warehouse_id, join_date, *, requested_by_user_id=None):
    safe_customer = dict(customer or {})
    customer_id = _to_int(safe_customer.get("id"), 0)
    if customer_id <= 0:
        raise ValueError("Customer tidak valid untuk auto member pembelian.")
    if not str(safe_customer.get("phone") or "").strip():
        return None

    member_code = _build_next_pos_member_code(db, warehouse_id, member_type="purchase")
    db.execute(
        """
        UPDATE crm_customers
        SET customer_type='member', updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (customer_id,),
    )
    cursor = db.execute(
        """
        INSERT INTO crm_memberships(
            customer_id,
            warehouse_id,
            member_code,
            member_type,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            requested_by_staff_id,
            reward_unit_amount,
            opening_stringing_visits,
            opening_reward_redeemed,
            benefit_note,
            note
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            customer_id,
            warehouse_id,
            member_code,
            "purchase",
            "regular",
            "active",
            join_date,
            None,
            0,
            _to_int(requested_by_user_id, 0) or None,
            DEFAULT_STRINGING_REWARD_AMOUNT,
            0,
            0,
            "Poin belanja aktif: 1 poin setiap total Rp 10.000.",
            "Auto-created by POS purchase member enrollment.",
        ),
    )
    return db.execute(
        """
        SELECT *
        FROM crm_memberships
        WHERE id=?
        """,
        (cursor.lastrowid,),
    ).fetchone()


def _auto_create_pos_stringing_member(db, customer, warehouse_id, join_date, *, requested_by_user_id=None):
    safe_customer = dict(customer or {})
    customer_id = _to_int(safe_customer.get("id"), 0)
    if customer_id <= 0:
        raise ValueError("Customer tidak valid untuk auto member senaran.")

    member_code = _build_next_pos_member_code(db, warehouse_id, member_type="stringing")
    threshold_label = _format_pos_currency_label(STRINGING_PROGRESS_MIN_AMOUNT)
    db.execute(
        """
        UPDATE crm_customers
        SET customer_type='member', updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (customer_id,),
    )
    cursor = db.execute(
        """
        INSERT INTO crm_memberships(
            customer_id,
            warehouse_id,
            member_code,
            member_type,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            requested_by_staff_id,
            reward_unit_amount,
            opening_stringing_visits,
            opening_reward_redeemed,
            benefit_note,
            note
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            customer_id,
            warehouse_id,
            member_code,
            "stringing",
            "regular",
            "active",
            join_date,
            None,
            0,
            _to_int(requested_by_user_id, 0) or None,
            DEFAULT_STRINGING_REWARD_AMOUNT,
            0,
            0,
            (
                f"Free senar 1x setiap {STRINGING_REWARD_THRESHOLD} progres "
                f"senaran berbayar minimal {threshold_label}."
            ),
            "Auto-created by POS Senaran Berbayar checkout.",
        ),
    )
    return db.execute(
        """
        SELECT *
        FROM crm_memberships
        WHERE id=?
        """,
        (cursor.lastrowid,),
    ).fetchone()


def _resolve_pos_loyalty_member(db, customer, warehouse_id, sale_date, transaction_type, *, requested_by_user_id=None):
    safe_transaction_type = normalize_transaction_type(transaction_type)
    safe_customer = dict(customer or {})
    reconcile_member_identity_duplicates(db, warehouse_id=warehouse_id)
    active_member = _fetch_active_customer_member(db, safe_customer.get("id"))

    if active_member:
        member_type = str(active_member["member_type"] or "").strip().lower()
        if safe_transaction_type in {"stringing_service", "stringing_reward_redemption"} and member_type != "stringing":
            raise ValueError("Jenis transaksi senaran hanya bisa dipakai untuk member senaran.")
        return active_member, get_member_snapshot(db, active_member["id"])

    if safe_transaction_type == "stringing_reward_redemption":
        raise ValueError("Free reward senaran hanya bisa dipakai oleh customer dengan member aktif.")

    matching_member = find_matching_member_identity(
        db,
        warehouse_id,
        "stringing" if safe_transaction_type != "purchase" else "purchase",
        phone=safe_customer.get("phone"),
        customer_name=safe_customer.get("customer_name"),
    )
    if matching_member:
        member = matching_member
        if safe_transaction_type in {"stringing_service", "stringing_reward_redemption"}:
            member_type = str(member["member_type"] or "").strip().lower()
            if member_type != "stringing":
                raise ValueError("Jenis transaksi senaran hanya bisa dipakai untuk member senaran.")
        return member, get_member_snapshot(db, member["id"])

    if safe_transaction_type == "purchase":
        created_member = _auto_create_pos_purchase_member(
            db,
            customer,
            warehouse_id,
            sale_date,
            requested_by_user_id=requested_by_user_id,
        )
        if not created_member:
            return None, None
        return created_member, get_member_snapshot(db, created_member["id"])

    if safe_transaction_type == "stringing_service":
        created_member = _auto_create_pos_stringing_member(
            db,
            customer,
            warehouse_id,
            sale_date,
            requested_by_user_id=requested_by_user_id,
        )
        return created_member, get_member_snapshot(db, created_member["id"])

    return None, None


def _is_pos_negative_stock_temp_enabled():
    return bool(current_app.config.get("POS_ALLOW_NEGATIVE_STOCK_TEMP"))


def _validate_and_build_items(
    db,
    warehouse_id,
    raw_items,
    *,
    free_reward_mode=False,
    stock_allowance_map=None,
    allow_negative_stock=False,
):
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("Keranjang kasir masih kosong.")

    normalized_raw_items = []
    prepared = []
    normalized_stock_allowance_map = {}
    for key, qty in dict(stock_allowance_map or {}).items():
        if not isinstance(key, (list, tuple)) or len(key) != 2:
            continue
        normalized_key = (_to_int(key[0], 0), _to_int(key[1], 0))
        allowance_qty = max(_to_int(qty, 0), 0)
        if normalized_key[0] <= 0 or normalized_key[1] <= 0 or allowance_qty <= 0:
            continue
        normalized_stock_allowance_map[normalized_key] = allowance_qty
    requested_qty_map = {}

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        product_id = _to_int(raw_item.get("product_id"), 0)
        variant_id = _to_int(raw_item.get("variant_id"), 0)
        qty = _to_int(raw_item.get("qty"), 0)
        raw_unit_price = raw_item.get("unit_price")
        raw_unit_price_text = str(raw_unit_price).strip() if raw_unit_price is not None else ""
        has_explicit_unit_price = raw_unit_price is not None and raw_unit_price_text != ""
        unit_price = _to_decimal(raw_unit_price, "0")
        retail_price = _to_decimal(raw_item.get("retail_price"), "0")

        if product_id <= 0 or variant_id <= 0 or qty <= 0:
            raise ValueError("Item kasir tidak valid. Periksa produk, variant, dan qty.")

        normalized_raw_items.append(
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "qty": qty,
                "has_explicit_unit_price": has_explicit_unit_price,
                "unit_price": unit_price,
                "retail_price": retail_price,
            }
        )

    if not normalized_raw_items:
        raise ValueError("Keranjang kasir masih kosong.")

    product_snapshot_map = _fetch_pos_product_snapshot_map(
        db,
        warehouse_id,
        [(item["product_id"], item["variant_id"]) for item in normalized_raw_items],
    )
    stock_snapshot_map = _fetch_pos_stock_balance_map(
        db,
        warehouse_id,
        [(item["product_id"], item["variant_id"]) for item in normalized_raw_items],
    )

    for raw_item in normalized_raw_items:
        product_id = raw_item["product_id"]
        variant_id = raw_item["variant_id"]
        qty = raw_item["qty"]
        unit_price = raw_item["unit_price"]
        retail_price = raw_item["retail_price"]
        has_explicit_unit_price = raw_item["has_explicit_unit_price"]
        product = product_snapshot_map.get((product_id, variant_id))
        if not product:
            raise ValueError("Produk atau variant tidak ditemukan.")

        item_key = (product_id, variant_id)
        stock_snapshot = _normalize_pos_stock_snapshot(stock_snapshot_map.get(item_key))
        available_qty = stock_snapshot["net_qty"] + max(normalized_stock_allowance_map.get(item_key, 0), 0)
        requested_qty = requested_qty_map.get(item_key, 0) + qty
        if available_qty < requested_qty and not allow_negative_stock:
            label_variant = product["variant_name"] or "default"
            raise ValueError(
                f"Stok tidak cukup untuk {product['sku']} / {label_variant}. Tersedia {available_qty}, diminta {requested_qty}."
            )
        requested_qty_map[item_key] = requested_qty

        if retail_price <= 0:
            retail_price = _to_decimal(
                product["price_nett"] or product["price_discount"] or product["price_retail"] or 0,
                "0",
            )

        if free_reward_mode:
            unit_price = Decimal("0.00")
        elif has_explicit_unit_price:
            if unit_price < 0:
                raise ValueError(f"Harga jual untuk {product['sku']} tidak boleh minus.")
        else:
            unit_price = _to_decimal(
                product["price_nett"] or product["price_discount"] or product["price_retail"] or 0,
                "0",
            )
            if unit_price <= 0:
                raise ValueError(f"Harga jual untuk {product['sku']} belum diatur.")

        line_total = (unit_price * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        prepared.append(
            {
                "product_id": int(product["product_id"]),
                "variant_id": int(product["variant_id"]),
                "sku": product["sku"],
                "product_name": product["product_name"],
                "category_name": product["category_name"] or "",
                "variant_name": product["variant_name"] or "default",
                "qty": qty,
                "retail_price": retail_price,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    if not prepared:
        raise ValueError("Keranjang kasir masih kosong.")

    return prepared


def _fetch_pos_stock_balance_snapshot(db, product_id, variant_id, warehouse_id):
    _ensure_pos_legacy_stock_batch_shadow(db, [(product_id, variant_id)], warehouse_id)
    row = db.execute(
        """
        SELECT
            COALESCE((
                SELECT SUM(remaining_qty)
                FROM stock_batches
                WHERE product_id=? AND variant_id=? AND warehouse_id=?
            ), 0) AS physical_qty,
            COALESCE((
                SELECT SUM(remaining_qty)
                FROM pos_negative_stock_overdrafts
                WHERE product_id=? AND variant_id=? AND warehouse_id=? AND COALESCE(remaining_qty, 0) > 0
            ), 0) AS overdraft_qty
        """,
        (
            product_id,
            variant_id,
            warehouse_id,
            product_id,
            variant_id,
            warehouse_id,
        ),
    ).fetchone()
    physical_qty = max(int(row["physical_qty"] or 0), 0) if row else 0
    overdraft_qty = max(int(row["overdraft_qty"] or 0), 0) if row else 0
    return {
        "net_qty": physical_qty - overdraft_qty,
        "positive_qty": physical_qty,
        "physical_qty": physical_qty,
        "overdraft_qty": overdraft_qty,
    }


def _sync_pos_stock_balance_snapshot(db, product_id, variant_id, warehouse_id):
    snapshot = _fetch_pos_stock_balance_snapshot(db, product_id, variant_id, warehouse_id)
    db.execute(
        """
        INSERT INTO stock(product_id, variant_id, warehouse_id, qty)
        VALUES (?,?,?,?)
        ON CONFLICT(product_id, variant_id, warehouse_id)
        DO UPDATE SET
            qty=excluded.qty,
            updated_at=CURRENT_TIMESTAMP
        """,
        (product_id, variant_id, warehouse_id, snapshot["net_qty"]),
    )
    return snapshot


def _record_pos_negative_stock_shortfall(db, product_id, variant_id, warehouse_id, qty, *, note=None):
    safe_qty = _to_int(qty, 0)
    if safe_qty <= 0:
        return None

    acting_user_id = _to_int(session.get("user_id"), 0) or None
    ip_address = request.remote_addr if request else None
    user_agent = request.headers.get("User-Agent") if request else None

    cursor = db.execute(
        """
        INSERT INTO pos_negative_stock_overdrafts(
            product_id,
            variant_id,
            warehouse_id,
            qty,
            remaining_qty,
            source_type,
            source_id,
            note,
            created_at
        )
        VALUES (?,?,?,?,?,?,?, ?, CURRENT_TIMESTAMP)
        """,
        (
            product_id,
            variant_id,
            warehouse_id,
            safe_qty,
            safe_qty,
            "pos_sale",
            None,
            note or "POS stok minus sementara",
        ),
    )
    overdraft_id = cursor.lastrowid

    db.execute(
        """
        INSERT INTO stock_history(
            product_id,
            variant_id,
            warehouse_id,
            action,
            type,
            qty,
            note,
            user_id,
            ip_address,
            user_agent
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            product_id,
            variant_id,
            warehouse_id,
            "OUTBOUND",
            "OUT",
            safe_qty,
            note or "POS stok minus sementara",
            acting_user_id,
            ip_address,
            user_agent,
        ),
    )
    return overdraft_id


def _resolve_pos_negative_stock_shortfall(db, product_id, variant_id, warehouse_id, qty, *, note=None):
    safe_qty = _to_int(qty, 0)
    if safe_qty <= 0:
        return {"resolved_qty": 0, "remaining_qty": 0}

    acting_user_id = _to_int(session.get("user_id"), 0) or None
    ip_address = request.remote_addr if request else None
    user_agent = request.headers.get("User-Agent") if request else None
    unresolved_qty = safe_qty
    resolved_qty = 0

    overdraft_rows = db.execute(
        """
        SELECT id, remaining_qty
        FROM pos_negative_stock_overdrafts
        WHERE product_id=? AND variant_id=? AND warehouse_id=? AND COALESCE(remaining_qty, 0) > 0
        ORDER BY datetime(created_at) ASC, id ASC
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchall()

    for overdraft_row in overdraft_rows:
        if unresolved_qty <= 0:
            break
        open_qty = max(_to_int(overdraft_row["remaining_qty"], 0), 0)
        if open_qty <= 0:
            continue
        settled_qty = min(open_qty, unresolved_qty)
        db.execute(
            """
            UPDATE pos_negative_stock_overdrafts
            SET
                remaining_qty = remaining_qty - ?,
                resolved_at = CASE
                    WHEN remaining_qty - ? <= 0 THEN CURRENT_TIMESTAMP
                    ELSE resolved_at
                END
            WHERE id=?
            """,
            (settled_qty, settled_qty, overdraft_row["id"]),
        )
        unresolved_qty -= settled_qty
        resolved_qty += settled_qty

    if resolved_qty > 0:
        db.execute(
            """
            INSERT INTO stock_history(
                product_id,
                variant_id,
                warehouse_id,
                action,
                type,
                qty,
                note,
                user_id,
                ip_address,
                user_agent
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                product_id,
                variant_id,
                warehouse_id,
                "POS_OVERDRAFT_SETTLEMENT",
                "IN",
                resolved_qty,
                note or "Pelunasan stok minus POS",
                acting_user_id,
                ip_address,
                user_agent,
            ),
        )

    return {
        "resolved_qty": resolved_qty,
        "remaining_qty": unresolved_qty,
    }


def _restore_pos_stock_after_reversal(db, product_id, variant_id, warehouse_id, qty, *, note=None, cost=0):
    safe_qty = _to_int(qty, 0)
    if safe_qty <= 0:
        return {"ok": False, "error": "Qty pengembalian stok tidak valid."}

    before_snapshot = _fetch_pos_stock_balance_snapshot(db, product_id, variant_id, warehouse_id)
    settled_overdraft = _resolve_pos_negative_stock_shortfall(
        db,
        product_id,
        variant_id,
        warehouse_id,
        safe_qty,
        note=f"{note or 'Reversal POS'} [settle overdraft]",
    )
    remaining_restore_qty = max(_to_int(settled_overdraft.get("remaining_qty"), 0), 0)
    if remaining_restore_qty > 0:
        restored = add_stock(
            product_id,
            variant_id,
            warehouse_id,
            remaining_restore_qty,
            note=note or "Reversal POS",
            cost=cost,
        )
        if not restored:
            return {"ok": False, "error": "Stok gagal dikembalikan saat proses reversal POS."}

    after_snapshot = _sync_pos_stock_balance_snapshot(db, product_id, variant_id, warehouse_id)
    return {
        "ok": True,
        "before_qty": before_snapshot["net_qty"],
        "after_qty": after_snapshot["net_qty"],
        "settled_overdraft_qty": settled_overdraft.get("resolved_qty", 0),
        "restored_physical_qty": remaining_restore_qty,
    }


def _remove_pos_stock_for_sale(db, product_id, variant_id, warehouse_id, qty, *, note=None, stock_snapshot=None):
    safe_qty = _to_int(qty, 0)
    if safe_qty <= 0:
        return {"ok": False, "error": "Qty stok keluar tidak valid."}

    before_snapshot = _normalize_pos_stock_snapshot(stock_snapshot)
    if not stock_snapshot:
        before_snapshot = _fetch_pos_stock_balance_snapshot(db, product_id, variant_id, warehouse_id)
    qty_from_positive_stock = min(safe_qty, before_snapshot["positive_qty"])
    negative_shortfall_qty = max(safe_qty - qty_from_positive_stock, 0)

    if negative_shortfall_qty > 0 and not _is_pos_negative_stock_temp_enabled():
        return {"ok": False, "error": "Stok tidak cukup untuk diproses."}

    if qty_from_positive_stock > 0:
        removed = _remove_pos_positive_stock_batches(
            db,
            product_id,
            variant_id,
            warehouse_id,
            qty_from_positive_stock,
            note=note or "POS checkout",
        )
        if not removed.get("ok"):
            return {"ok": False, "error": removed.get("error") or "Gagal memotong stok positif yang tersedia."}

    if negative_shortfall_qty > 0:
        _record_pos_negative_stock_shortfall(
            db,
            product_id,
            variant_id,
            warehouse_id,
            negative_shortfall_qty,
            note=f"{note or 'POS checkout'} [stok minus sementara]",
        )
    after_snapshot = {
        "positive_qty": max(before_snapshot["positive_qty"] - qty_from_positive_stock, 0),
        "physical_qty": max(before_snapshot["physical_qty"] - qty_from_positive_stock, 0),
        "overdraft_qty": before_snapshot["overdraft_qty"] + negative_shortfall_qty,
    }
    after_snapshot["net_qty"] = after_snapshot["physical_qty"] - after_snapshot["overdraft_qty"]
    _upsert_pos_stock_balance(db, product_id, variant_id, warehouse_id, after_snapshot["net_qty"])

    return {
        "ok": True,
        "before_qty": before_snapshot["net_qty"],
        "after_qty": after_snapshot["net_qty"],
        "removed_qty": qty_from_positive_stock,
        "negative_shortfall_qty": negative_shortfall_qty,
        "used_negative_stock": negative_shortfall_qty > 0 or after_snapshot["net_qty"] < 0,
        "after_snapshot": after_snapshot,
    }


def _build_pos_negative_stock_notification_message(receipt_no, cashier_name, affected_items):
    item_labels = []
    for item in affected_items:
        sku = str(item.get("sku") or "-").strip() or "-"
        variant_name = str(item.get("variant_name") or "default").strip() or "default"
        before_qty = _to_int(item.get("before_qty"), 0)
        after_qty = _to_int(item.get("after_qty"), 0)
        item_labels.append(f"{sku} / {variant_name} (stok {before_qty} -> {after_qty})")
    joined_items = "; ".join(item_labels) if item_labels else "barang tidak diketahui"
    safe_cashier_name = str(cashier_name or "Staff POS").strip() or "Staff POS"
    return f"Staff {safe_cashier_name} sedang memproses transaksi {receipt_no} dengan barang {joined_items}."


def _build_pos_sale_status_payload(raw_status):
    safe_status = str(raw_status or "posted").strip().lower()
    if safe_status == "voided":
        return {
            "status": "voided",
            "status_label": "VOIDED",
            "status_tone": "red",
        }
    if safe_status == "partial_void":
        return {
            "status": "partial_void",
            "status_label": "PARTIAL VOID",
            "status_tone": "orange",
        }
    return {
        "status": "posted",
        "status_label": "POSTED",
        "status_tone": "green",
    }


def _fetch_pos_sale_item_map(db, purchase_ids):
    normalized_ids = [int(purchase_id) for purchase_id in purchase_ids if _to_int(purchase_id, 0) > 0]
    if not normalized_ids:
        return {}

    placeholders = ",".join("?" for _ in normalized_ids)
    try:
        rows = db.execute(
            f"""
            SELECT
                cpi.id AS item_id,
                cpi.purchase_id,
                cpi.product_id,
                cpi.variant_id,
                COALESCE(NULLIF(TRIM(p.sku), ''), '-') AS sku,
                COALESCE(NULLIF(TRIM(p.name), ''), 'Produk') AS product_name,
                COALESCE(NULLIF(TRIM(pv.variant), ''), 'default') AS variant_name,
                COALESCE(cpi.qty, 0) AS qty,
                COALESCE(cpi.retail_price, 0) AS retail_price,
                COALESCE(cpi.unit_price, 0) AS unit_price,
                COALESCE(cpi.line_total, 0) AS line_total,
                COALESCE(cpi.void_qty, 0) AS void_qty,
                COALESCE(cpi.void_amount, 0) AS void_amount,
                COALESCE(cpi.void_note, '') AS void_note
            FROM crm_purchase_items cpi
            LEFT JOIN products p ON p.id = cpi.product_id
            LEFT JOIN product_variants pv ON pv.id = cpi.variant_id
            WHERE cpi.purchase_id IN ({placeholders})
            ORDER BY cpi.purchase_id ASC, cpi.id ASC
            """,
            normalized_ids,
        ).fetchall()
    except Exception:
        rows = db.execute(
            f"""
            SELECT
                cpi.id AS item_id,
                cpi.purchase_id,
                cpi.product_id,
                cpi.variant_id,
                COALESCE(NULLIF(TRIM(p.sku), ''), '-') AS sku,
                COALESCE(NULLIF(TRIM(p.name), ''), 'Produk') AS product_name,
                COALESCE(NULLIF(TRIM(pv.variant), ''), 'default') AS variant_name,
                COALESCE(cpi.qty, 0) AS qty,
                COALESCE(cpi.unit_price, 0) AS retail_price,
                COALESCE(cpi.unit_price, 0) AS unit_price,
                COALESCE(cpi.line_total, 0) AS line_total,
                COALESCE(cpi.void_qty, 0) AS void_qty,
                COALESCE(cpi.void_amount, 0) AS void_amount,
                COALESCE(cpi.void_note, '') AS void_note
            FROM crm_purchase_items cpi
            LEFT JOIN products p ON p.id = cpi.product_id
            LEFT JOIN product_variants pv ON pv.id = cpi.variant_id
            WHERE cpi.purchase_id IN ({placeholders})
            ORDER BY cpi.purchase_id ASC, cpi.id ASC
            """,
            normalized_ids,
        ).fetchall()

    item_map = {}
    for row in rows:
        purchase_id = int(row["purchase_id"])
        sold_qty = int(row["qty"] or 0)
        void_qty = max(0, int(row["void_qty"] or 0))
        active_qty = max(sold_qty - void_qty, 0)
        unit_price = _currency(row["unit_price"] or 0)
        retail_price = _currency(row["retail_price"] or 0)
        line_total = _currency(row["line_total"] or 0)
        void_amount = _currency(row["void_amount"] or 0)
        active_line_total = max(line_total - void_amount, 0)
        unit_discount = max(retail_price - unit_price, 0)
        total_discount = max(unit_discount * active_qty, 0)

        if active_qty <= 0:
            item_status = _build_pos_sale_status_payload("voided")
        elif void_qty > 0:
            item_status = _build_pos_sale_status_payload("partial_void")
        else:
            item_status = _build_pos_sale_status_payload("posted")

        item_map.setdefault(purchase_id, []).append(
            {
                "id": int(row["item_id"]),
                "product_id": int(row["product_id"] or 0),
                "variant_id": int(row["variant_id"] or 0),
                "sku": row["sku"],
                "product_name": row["product_name"],
                "variant_name": row["variant_name"],
                "qty": sold_qty,
                "void_qty": void_qty,
                "active_qty": active_qty,
                "retail_price": retail_price,
                "unit_price": unit_price,
                "line_total": line_total,
                "void_amount": void_amount,
                "active_line_total": active_line_total,
                "void_note": row["void_note"],
                "unit_discount": unit_discount,
                "total_discount": total_discount,
                "has_discount": unit_discount > 0 and active_qty > 0,
                "retail_price_label": _format_pos_currency_label(retail_price),
                "unit_price_label": _format_pos_currency_label(unit_price),
                "line_total_label": _format_pos_currency_label(line_total),
                "void_amount_label": _format_pos_currency_label(void_amount),
                "active_line_total_label": _format_pos_currency_label(active_line_total),
                "unit_discount_label": _format_pos_currency_label(unit_discount),
                "total_discount_label": _format_pos_currency_label(total_discount),
                "can_void": has_permission(session.get("role"), "manage_pos") and active_qty > 0,
                "voidable_qty": active_qty,
                "summary_label": f"{row['sku']} - {row['product_name']} - {row['variant_name']} x{active_qty}",
                "detail_label": f"{row['variant_name']} | Aktif {active_qty} dari {sold_qty}",
                **item_status,
            }
        )
    return item_map


def _fetch_pos_sale_logs(
    db,
    date_from,
    date_to,
    selected_warehouse=None,
    cashier_user_id=None,
    search_query="",
    limit=60,
    receipt_wa_status=None,
    archive_mode="visible",
):
    safe_limit = max(1, min(_to_int(limit, 60), 200))
    params = [date_from, date_to]
    query = f"""
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.payment_breakdown_json,
            ps.total_items,
            ps.subtotal_amount,
            ps.discount_type,
            ps.discount_value,
            ps.discount_amount,
            ps.tax_type,
            ps.tax_value,
            ps.tax_amount,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.status,
            ps.receipt_pdf_path,
            ps.receipt_pdf_url,
            ps.receipt_whatsapp_status,
            ps.receipt_whatsapp_error,
            ps.receipt_whatsapp_sent_at,
            COALESCE(ps.is_hidden_archive, 0) AS is_hidden_archive,
            ps.hidden_archive_at,
            ps.hidden_archive_note,
            ps.note,
            ps.created_at,
            pr.member_id,
            pr.transaction_type,
            COALESCE(NULLIF(TRIM(m.member_code), ''), '') AS member_code,
            COALESCE(NULLIF(TRIM(m.member_type), ''), '') AS member_type,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            {POS_CASHIER_GROUP_KEY_SQL} AS staff_group_key,
            {POS_CASHIER_NAME_SQL} AS cashier_name,
            {POS_CASHIER_USERNAME_SQL} AS cashier_username,
            {POS_CASHIER_POSITION_SQL} AS cashier_position,
            COALESCE(NULLIF(TRIM(hidden_archive_user.username), ''), 'System') AS hidden_archive_by_name,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        LEFT JOIN crm_purchase_records pr ON pr.id = ps.purchase_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN users hidden_archive_user ON hidden_archive_user.id = ps.hidden_archive_by
        LEFT JOIN warehouses w ON w.id = ps.warehouse_id
        WHERE ps.sale_date BETWEEN ? AND ?
    """

    normalized_archive_mode = str(archive_mode or "visible").strip().lower()
    if normalized_archive_mode == "hidden_only":
        query += " AND COALESCE(ps.is_hidden_archive, 0)=1"
    elif normalized_archive_mode != "all":
        query += " AND COALESCE(ps.is_hidden_archive, 0)=0"

    if selected_warehouse:
        query += " AND ps.warehouse_id=?"
        params.append(int(selected_warehouse))

    if cashier_user_id:
        query += " AND ps.cashier_user_id=?"
        params.append(int(cashier_user_id))

    safe_search_query = str(search_query or "").strip()
    if safe_search_query:
        search_pattern = f"%{safe_search_query}%"
        query += """
            AND (
                ps.receipt_no LIKE ?
                OR COALESCE(c.customer_name, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR {actor_name_sql} LIKE ?
                OR COALESCE(ps.note, '') LIKE ?
            )
        """.format(actor_name_sql=POS_CASHIER_NAME_SQL)
        params.extend([search_pattern] * 5)

    safe_receipt_wa_status = str(receipt_wa_status or "").strip().lower()
    if safe_receipt_wa_status:
        query += " AND LOWER(COALESCE(ps.receipt_whatsapp_status, 'pending'))=?"
        params.append(safe_receipt_wa_status)

    query += """
        ORDER BY ps.sale_date DESC, ps.id DESC
        LIMIT ?
    """
    params.append(safe_limit)

    header_rows = [dict(row) for row in db.execute(query, params).fetchall()]
    item_map = _fetch_pos_sale_item_map(db, [row["purchase_id"] for row in header_rows])
    normalized_rows = []

    for row in header_rows:
        is_hidden_archive = bool(_to_int(row.get("is_hidden_archive"), 0))
        items = item_map.get(int(row["purchase_id"]), [])
        total_amount = _currency(row.get("total_amount") or 0)
        paid_amount = _currency(row.get("paid_amount") or 0)
        change_amount = _currency(row.get("change_amount") or 0)
        subtotal_amount = _currency(row.get("subtotal_amount") or 0)
        discount_amount = _currency(row.get("discount_amount") or 0)
        tax_amount = _currency(row.get("tax_amount") or 0)
        payment_meta = _build_pos_sale_payment_meta(
            row.get("payment_method"),
            paid_amount,
            row.get("payment_breakdown_json"),
        )
        created_time_label = _format_pos_time_label(row.get("created_at"))
        item_preview_lines = items[:3]
        sale_status = _build_pos_sale_status_payload(row.get("status"))
        can_edit_transaction = (
            has_permission(session.get("role"), "manage_pos")
            and not is_hidden_archive
            and str(row.get("status") or "posted").strip().lower() == "posted"
            and not any(max(_to_int(item.get("void_qty"), 0), 0) > 0 for item in items)
            and any(max(_to_int(item.get("active_qty"), 0), 0) > 0 for item in items)
        )
        can_edit_sale_date = has_permission(session.get("role"), "manage_pos") and not is_hidden_archive

        normalized_rows.append(
            {
                **row,
                "total_items": int(row.get("total_items") or 0),
                "total_amount": total_amount,
                "paid_amount": paid_amount,
                "change_amount": change_amount,
                "subtotal_amount": subtotal_amount,
                "discount_amount": discount_amount,
                "tax_amount": tax_amount,
                "total_amount_label": _format_pos_currency_label(total_amount),
                "paid_amount_label": _format_pos_currency_label(paid_amount),
                "change_amount_label": _format_pos_currency_label(change_amount),
                "subtotal_amount_label": _format_pos_currency_label(subtotal_amount),
                "discount_amount_label": _format_pos_currency_label(discount_amount),
                "tax_amount_label": _format_pos_currency_label(tax_amount),
                "discount_rule_label": _format_pos_adjustment_rule_label(row.get("discount_type"), row.get("discount_value")),
                "tax_rule_label": _format_pos_adjustment_rule_label(row.get("tax_type"), row.get("tax_value")),
                "payment_method_label": _format_payment_method_label(row.get("payment_method")),
                "can_edit_transaction": can_edit_transaction,
                "can_edit_sale_date": can_edit_sale_date,
                "is_hidden_archive": is_hidden_archive,
                "hidden_archive_at": row.get("hidden_archive_at"),
                "hidden_archive_note": row.get("hidden_archive_note") or "",
                "hidden_archive_by_name": row.get("hidden_archive_by_name") or "System",
                "can_hidden_archive": _can_archive_pos_sale() and not is_hidden_archive,
                "can_restore_hidden_archive": _can_manage_pos_hidden_archive() and is_hidden_archive and _is_pos_hidden_archive_unlocked(),
                "has_payment_breakdown": payment_meta["has_payment_breakdown"],
                "payment_breakdown_entries": payment_meta["payment_breakdown_entries"],
                "payment_breakdown_label": payment_meta["payment_breakdown_label"],
                "created_time_label": created_time_label,
                "created_datetime_label": f"{row['sale_date']} {created_time_label}" if created_time_label != "-" else row["sale_date"],
                "customer_phone_label": row["customer_phone"] if row.get("customer_phone") and row["customer_phone"] != "-" else "Tanpa nomor",
                "cashier_identity_label": f"{row['cashier_name']} - {row['cashier_position']}",
                "staff_group_key": row.get("staff_group_key") or "",
                "can_edit_payment_method": has_permission(session.get("role"), "manage_pos")
                and not is_hidden_archive
                and str(row.get("status") or "posted").strip().lower() != "voided",
                "items": items,
                "item_preview_lines": item_preview_lines,
                "item_preview_more": max(len(items) - len(item_preview_lines), 0),
                "has_voidable_items": any(item.get("can_void") for item in items),
                "receipt_print_url": f"/kasir/receipt/{row['receipt_no']}/print",
                "receipt_thermal_url": (
                    f"/kasir/receipt/{row['receipt_no']}/print"
                    f"?layout=thermal&copy=customer&autoprint=1&autoclose=1"
                ),
                "receipt_pdf_url": row.get("receipt_pdf_url") or f"/kasir/receipt/{row['receipt_no']}/print?autoprint=1",
                "receipt_pdf_public_url": row.get("receipt_pdf_url") or "",
                "receipt_whatsapp_status": str(row.get("receipt_whatsapp_status") or "pending").strip().lower(),
                "receipt_whatsapp_error": row.get("receipt_whatsapp_error") or "",
                "receipt_whatsapp_sent_at": row.get("receipt_whatsapp_sent_at"),
                **sale_status,
            }
        )

    return normalized_rows


def _fetch_pos_sale_detail_by_receipt(db, receipt_no, *, allow_hidden_archive=False):
    safe_receipt = str(receipt_no or "").strip()
    if not safe_receipt:
        return None

    effective_allow_hidden_archive = bool(allow_hidden_archive) or (
        _can_manage_pos_hidden_archive() and _is_pos_hidden_archive_unlocked()
    )

    params = [safe_receipt]
    query = f"""
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.payment_breakdown_json,
            ps.total_items,
            ps.subtotal_amount,
            ps.discount_type,
            ps.discount_value,
            ps.discount_amount,
            ps.tax_type,
            ps.tax_value,
            ps.tax_amount,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.status,
            ps.receipt_pdf_path,
            ps.receipt_pdf_url,
            ps.receipt_whatsapp_status,
            ps.receipt_whatsapp_error,
            ps.receipt_whatsapp_sent_at,
            COALESCE(ps.is_hidden_archive, 0) AS is_hidden_archive,
            ps.hidden_archive_at,
            ps.hidden_archive_note,
            ps.note,
            ps.created_at,
            pr.member_id,
            pr.transaction_type,
            COALESCE(NULLIF(TRIM(m.member_code), ''), '') AS member_code,
            COALESCE(NULLIF(TRIM(m.member_type), ''), '') AS member_type,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            {POS_CASHIER_NAME_SQL} AS cashier_name,
            {POS_CASHIER_USERNAME_SQL} AS cashier_username,
            {POS_CASHIER_POSITION_SQL} AS cashier_position,
            COALESCE(NULLIF(TRIM(hidden_archive_user.username), ''), 'System') AS hidden_archive_by_name,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        LEFT JOIN crm_purchase_records pr ON pr.id = ps.purchase_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN users hidden_archive_user ON hidden_archive_user.id = ps.hidden_archive_by
        LEFT JOIN warehouses w ON w.id = ps.warehouse_id
        WHERE ps.receipt_no=?
    """

    if is_scoped_role(session.get("role")):
        query += " AND ps.warehouse_id=?"
        params.append(session.get("warehouse_id"))

    query += " LIMIT 1"

    row = db.execute(query, params).fetchone()
    if not row:
        return None

    sale = dict(row)
    if bool(_to_int(sale.get("is_hidden_archive"), 0)) and not effective_allow_hidden_archive:
        return None
    items = _fetch_pos_sale_item_map(db, [sale["purchase_id"]]).get(int(sale["purchase_id"]), [])
    total_amount = _currency(sale.get("total_amount") or 0)
    paid_amount = _currency(sale.get("paid_amount") or 0)
    change_amount = _currency(sale.get("change_amount") or 0)
    subtotal_amount = _currency(sale.get("subtotal_amount") or 0)
    discount_amount = _currency(sale.get("discount_amount") or 0)
    tax_amount = _currency(sale.get("tax_amount") or 0)
    payment_meta = _build_pos_sale_payment_meta(
        sale.get("payment_method"),
        paid_amount,
        sale.get("payment_breakdown_json"),
    )
    created_time_label = _format_pos_time_label(sale.get("created_at"))

    sale_detail = {
        **sale,
        "items": items,
        "total_items": int(sale.get("total_items") or 0),
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "change_amount": change_amount,
        "subtotal_amount": subtotal_amount,
        "discount_amount": discount_amount,
        "tax_amount": tax_amount,
        "total_amount_label": _format_pos_currency_label(total_amount),
        "paid_amount_label": _format_pos_currency_label(paid_amount),
        "change_amount_label": _format_pos_currency_label(change_amount),
        "subtotal_amount_label": _format_pos_currency_label(subtotal_amount),
        "discount_amount_label": _format_pos_currency_label(discount_amount),
        "tax_amount_label": _format_pos_currency_label(tax_amount),
        "discount_rule_label": _format_pos_adjustment_rule_label(sale.get("discount_type"), sale.get("discount_value")),
        "tax_rule_label": _format_pos_adjustment_rule_label(sale.get("tax_type"), sale.get("tax_value")),
        "payment_method_label": _format_payment_method_label(sale.get("payment_method")),
        "has_payment_breakdown": payment_meta["has_payment_breakdown"],
        "payment_breakdown_entries": payment_meta["payment_breakdown_entries"],
        "payment_breakdown_label": payment_meta["payment_breakdown_label"],
        "created_time_label": created_time_label,
        "created_datetime_label": f"{sale['sale_date']} {created_time_label}" if created_time_label != "-" else sale["sale_date"],
        "customer_phone_label": sale["customer_phone"] if sale.get("customer_phone") and sale["customer_phone"] != "-" else "Tanpa nomor",
        "cashier_identity_label": f"{sale['cashier_name']} - {sale['cashier_position']}",
        "is_hidden_archive": bool(_to_int(sale.get("is_hidden_archive"), 0)),
        "hidden_archive_at": sale.get("hidden_archive_at"),
        "hidden_archive_note": sale.get("hidden_archive_note") or "",
        "hidden_archive_by_name": sale.get("hidden_archive_by_name") or "System",
        "receipt_pdf_public_url": sale.get("receipt_pdf_url") or "",
        "receipt_whatsapp_status": str(sale.get("receipt_whatsapp_status") or "pending").strip().lower(),
        "receipt_whatsapp_error": sale.get("receipt_whatsapp_error") or "",
        "receipt_whatsapp_sent_at": sale.get("receipt_whatsapp_sent_at"),
        **_build_pos_sale_status_payload(sale.get("status")),
    }
    return _attach_pos_loyalty_summary(db, sale_detail)


def _fetch_pos_sale_detail_by_id(db, sale_id, *, allow_hidden_archive=False):
    safe_sale_id = _to_int(sale_id, 0)
    if safe_sale_id <= 0:
        return None

    effective_allow_hidden_archive = bool(allow_hidden_archive) or (
        _can_manage_pos_hidden_archive() and _is_pos_hidden_archive_unlocked()
    )
    params = [safe_sale_id]
    query = """
        SELECT receipt_no
        FROM pos_sales
        WHERE id=?
    """
    if not effective_allow_hidden_archive:
        query += " AND COALESCE(is_hidden_archive, 0)=0"
    if is_scoped_role(session.get("role")):
        query += " AND warehouse_id=?"
        params.append(session.get("warehouse_id"))
    query += " LIMIT 1"

    row = db.execute(query, params).fetchone()
    if not row:
        return None
    return _fetch_pos_sale_detail_by_receipt(
        db,
        row["receipt_no"],
        allow_hidden_archive=effective_allow_hidden_archive,
    )


def _build_pos_checkout_success_payload_from_sale_detail(sale_detail, *, message):
    safe_sale = dict(sale_detail or {})
    return {
        "status": "success",
        "message": str(message or "Checkout kasir berhasil disimpan."),
        "sale_id": _to_int(safe_sale.get("id"), 0),
        "receipt_no": safe_sale.get("receipt_no") or "",
        "purchase_id": _to_int(safe_sale.get("purchase_id"), 0),
        "sale_date": str(safe_sale.get("sale_date") or "").strip(),
        "customer_name": safe_sale.get("customer_name") or "",
        "total_items": _to_int(safe_sale.get("total_items"), 0),
        "subtotal_amount": _currency(safe_sale.get("subtotal_amount") or 0),
        "discount_amount": _currency(safe_sale.get("discount_amount") or 0),
        "tax_amount": _currency(safe_sale.get("tax_amount") or 0),
        "total_amount": _currency(safe_sale.get("total_amount") or 0),
        "paid_amount": _currency(safe_sale.get("paid_amount") or 0),
        "change_amount": _currency(safe_sale.get("change_amount") or 0),
        "payment_method": safe_sale.get("payment_method") or "cash",
        "payment_method_label": safe_sale.get("payment_method_label")
        or _format_payment_method_label(safe_sale.get("payment_method")),
        "payment_breakdown_label": safe_sale.get("payment_breakdown_label") or "",
        "receipt_print_url": (
            f"/kasir/receipt/{safe_sale.get('receipt_no')}/print"
            f"?layout=thermal&copy=customer&autoprint=1&autoclose=1"
        )
        if safe_sale.get("receipt_no")
        else "",
        "receipt_pdf_public_url": safe_sale.get("receipt_pdf_public_url") or "",
        "receipt_whatsapp_status": str(safe_sale.get("receipt_whatsapp_status") or "pending").strip().lower(),
        "receipt_whatsapp_error": str(safe_sale.get("receipt_whatsapp_error") or "").strip(),
        "status_label": safe_sale.get("status_label") or "POSTED",
        "status_tone": safe_sale.get("status_tone") or "success",
        "is_hidden_archive": bool(safe_sale.get("is_hidden_archive")),
        "hidden_archive_at": safe_sale.get("hidden_archive_at"),
    }


def _normalize_pos_item_keys(item_keys):
    normalized_keys = []
    seen_keys = set()
    for item_key in item_keys or []:
        if not isinstance(item_key, (list, tuple)) or len(item_key) != 2:
            continue
        normalized_key = (_to_int(item_key[0], 0), _to_int(item_key[1], 0))
        if normalized_key[0] <= 0 or normalized_key[1] <= 0 or normalized_key in seen_keys:
            continue
        seen_keys.add(normalized_key)
        normalized_keys.append(normalized_key)
    return normalized_keys


def _ensure_pos_legacy_stock_batch_shadow(db, item_keys, warehouse_id):
    normalized_keys = _normalize_pos_item_keys(item_keys)
    safe_warehouse_id = _to_int(warehouse_id, 0)
    if safe_warehouse_id <= 0 or not normalized_keys:
        return

    for product_id, variant_id in normalized_keys:
        open_batch = db.execute(
            """
            SELECT id
            FROM stock_batches
            WHERE product_id=? AND variant_id=? AND warehouse_id=? AND COALESCE(remaining_qty, 0) > 0
            LIMIT 1
            """,
            (product_id, variant_id, safe_warehouse_id),
        ).fetchone()
        if open_batch:
            continue

        stock_row = db.execute(
            """
            SELECT COALESCE(qty, 0) AS qty
            FROM stock
            WHERE product_id=? AND variant_id=? AND warehouse_id=?
            LIMIT 1
            """,
            (product_id, variant_id, safe_warehouse_id),
        ).fetchone()
        available_qty = max(_to_int(stock_row["qty"], 0), 0) if stock_row else 0
        if available_qty <= 0:
            continue

        db.execute(
            """
            INSERT INTO stock_batches(
                product_id,
                variant_id,
                warehouse_id,
                qty,
                remaining_qty,
                cost,
                created_at
            )
            VALUES (?,?,?,?,?,0,datetime('now'))
            """,
            (product_id, variant_id, safe_warehouse_id, available_qty, available_qty),
        )


def _chunk_pos_values(values, chunk_size=POS_BULK_LOOKUP_CHUNK_SIZE):
    safe_values = list(values or [])
    safe_chunk_size = max(1, _to_int(chunk_size, POS_BULK_LOOKUP_CHUNK_SIZE))
    for index in range(0, len(safe_values), safe_chunk_size):
        yield safe_values[index:index + safe_chunk_size]


def _build_pos_stock_allowance_map_from_items(items):
    allowance_map = {}
    for item in items or []:
        product_id = _to_int((item or {}).get("product_id"), 0)
        variant_id = _to_int((item or {}).get("variant_id"), 0)
        active_qty = max(_to_int((item or {}).get("active_qty"), 0), 0)
        if product_id <= 0 or variant_id <= 0 or active_qty <= 0:
            continue
        item_key = (product_id, variant_id)
        allowance_map[item_key] = allowance_map.get(item_key, 0) + active_qty
    return allowance_map


def _fetch_pos_product_snapshot_map(db, warehouse_id, item_keys):
    normalized_keys = _normalize_pos_item_keys(item_keys)
    if not normalized_keys:
        return {}

    snapshot_map = {}
    normalized_variant_ids = [variant_id for _, variant_id in normalized_keys]

    for variant_chunk in _chunk_pos_values(normalized_variant_ids):
        placeholders = ",".join("?" for _ in variant_chunk)
        rows = db.execute(
            f"""
            SELECT
                p.id AS product_id,
                pv.id AS variant_id,
                COALESCE(NULLIF(TRIM(p.sku), ''), '-') AS sku,
                COALESCE(NULLIF(TRIM(p.name), ''), 'Produk') AS product_name,
                COALESCE(NULLIF(TRIM(c.name), ''), '') AS category_name,
                COALESCE(NULLIF(TRIM(pv.variant), ''), 'default') AS variant_name,
                COALESCE(pv.price_nett, 0) AS price_nett,
                COALESCE(pv.price_discount, 0) AS price_discount,
                COALESCE(pv.price_retail, 0) AS price_retail,
                COALESCE(s.qty, 0) AS stock_qty
            FROM product_variants pv
            JOIN products p ON p.id = pv.product_id
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN stock s
                ON s.product_id = p.id
               AND s.variant_id = pv.id
               AND s.warehouse_id = ?
            WHERE pv.id IN ({placeholders})
            """,
            [warehouse_id, *variant_chunk],
        ).fetchall()
        for row in rows:
            snapshot_map[(int(row["product_id"] or 0), int(row["variant_id"] or 0))] = dict(row)

    return snapshot_map


def _fetch_pos_stock_balance_map(db, warehouse_id, item_keys):
    normalized_keys = _normalize_pos_item_keys(item_keys)
    if not normalized_keys:
        return {}

    _ensure_pos_legacy_stock_batch_shadow(db, normalized_keys, warehouse_id)

    balance_map = {
        item_key: {
            "net_qty": 0,
            "positive_qty": 0,
            "physical_qty": 0,
            "overdraft_qty": 0,
        }
        for item_key in normalized_keys
    }
    normalized_variant_ids = [variant_id for _, variant_id in normalized_keys]

    for variant_chunk in _chunk_pos_values(normalized_variant_ids):
        placeholders = ",".join("?" for _ in variant_chunk)
        physical_rows = db.execute(
            f"""
            SELECT
                product_id,
                variant_id,
                COALESCE(SUM(remaining_qty), 0) AS physical_qty
            FROM stock_batches
            WHERE warehouse_id=? AND variant_id IN ({placeholders})
            GROUP BY product_id, variant_id
            """,
            [warehouse_id, *variant_chunk],
        ).fetchall()
        for row in physical_rows:
            item_key = (int(row["product_id"] or 0), int(row["variant_id"] or 0))
            if item_key not in balance_map:
                continue
            physical_qty = max(_to_int(row["physical_qty"], 0), 0)
            balance_map[item_key]["positive_qty"] = physical_qty
            balance_map[item_key]["physical_qty"] = physical_qty

        overdraft_rows = db.execute(
            f"""
            SELECT
                product_id,
                variant_id,
                COALESCE(SUM(remaining_qty), 0) AS overdraft_qty
            FROM pos_negative_stock_overdrafts
            WHERE warehouse_id=? AND variant_id IN ({placeholders}) AND COALESCE(remaining_qty, 0) > 0
            GROUP BY product_id, variant_id
            """,
            [warehouse_id, *variant_chunk],
        ).fetchall()
        for row in overdraft_rows:
            item_key = (int(row["product_id"] or 0), int(row["variant_id"] or 0))
            if item_key not in balance_map:
                continue
            balance_map[item_key]["overdraft_qty"] = max(_to_int(row["overdraft_qty"], 0), 0)

    for snapshot in balance_map.values():
        snapshot["net_qty"] = snapshot["positive_qty"] - snapshot["overdraft_qty"]

    return balance_map


def _normalize_pos_stock_snapshot(snapshot):
    safe_snapshot = dict(snapshot or {})
    positive_qty = max(_to_int(safe_snapshot.get("positive_qty"), safe_snapshot.get("physical_qty", 0)), 0)
    physical_qty = max(_to_int(safe_snapshot.get("physical_qty"), positive_qty), 0)
    overdraft_qty = max(_to_int(safe_snapshot.get("overdraft_qty"), 0), 0)
    default_net_qty = physical_qty - overdraft_qty
    return {
        "net_qty": _to_int(safe_snapshot.get("net_qty"), default_net_qty),
        "positive_qty": positive_qty,
        "physical_qty": physical_qty,
        "overdraft_qty": overdraft_qty,
    }


def _upsert_pos_stock_balance(db, product_id, variant_id, warehouse_id, qty):
    db.execute(
        """
        INSERT INTO stock(product_id, variant_id, warehouse_id, qty)
        VALUES (?,?,?,?)
        ON CONFLICT(product_id, variant_id, warehouse_id)
        DO UPDATE SET
            qty=excluded.qty,
            updated_at=CURRENT_TIMESTAMP
        """,
        (product_id, variant_id, warehouse_id, qty),
    )


def _remove_pos_positive_stock_batches(db, product_id, variant_id, warehouse_id, qty, *, note=None):
    safe_qty = _to_int(qty, 0)
    if safe_qty <= 0:
        return {"ok": True, "removed_qty": 0}

    _ensure_pos_legacy_stock_batch_shadow(db, [(product_id, variant_id)], warehouse_id)

    acting_user_id = _to_int(session.get("user_id"), 0) or None
    ip_address = request.remote_addr if request else None
    user_agent = request.headers.get("User-Agent") if request else None
    remaining_qty = safe_qty

    batch_rows = db.execute(
        """
        SELECT id, remaining_qty
        FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=? AND remaining_qty > 0
        ORDER BY datetime(created_at) ASC, id ASC
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchall()

    for batch_row in batch_rows:
        if remaining_qty <= 0:
            break
        open_qty = max(_to_int(batch_row["remaining_qty"], 0), 0)
        if open_qty <= 0:
            continue
        take_qty = min(open_qty, remaining_qty)
        db.execute(
            """
            UPDATE stock_batches
            SET remaining_qty = remaining_qty - ?
            WHERE id=?
            """,
            (take_qty, batch_row["id"]),
        )
        db.execute(
            """
            INSERT INTO stock_movements(
                product_id,
                variant_id,
                warehouse_id,
                batch_id,
                qty,
                type,
                created_at
            )
            VALUES (?,?,?,?,?,'OUT',CURRENT_TIMESTAMP)
            """,
            (product_id, variant_id, warehouse_id, batch_row["id"], take_qty),
        )
        remaining_qty -= take_qty

    if remaining_qty > 0:
        return {"ok": False, "error": "Gagal memotong stok positif yang tersedia."}

    db.execute(
        """
        INSERT INTO stock_history(
            product_id,
            variant_id,
            warehouse_id,
            action,
            type,
            qty,
            note,
            user_id,
            ip_address,
            user_agent
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            product_id,
            variant_id,
            warehouse_id,
            "OUTBOUND",
            "OUT",
            safe_qty,
            note or "POS checkout",
            acting_user_id,
            ip_address,
            user_agent,
        ),
    )
    return {"ok": True, "removed_qty": safe_qty}


def _build_pos_edit_sale_payload(db, sale_detail):
    safe_sale = sale_detail or {}
    if not safe_sale:
        return None

    sale_status = str(safe_sale.get("status") or "posted").strip().lower()
    if sale_status != "posted":
        raise ValueError("Hanya transaksi POS yang masih POSTED yang bisa diedit.")

    raw_items = list(safe_sale.get("items") or [])
    if not raw_items:
        raise ValueError("Transaksi ini belum punya item aktif untuk diedit.")
    if any(max(_to_int(item.get("void_qty"), 0), 0) > 0 for item in raw_items):
        raise ValueError("Transaksi yang sudah pernah di-void tidak bisa diedit dari mode ini.")

    stock_allowance_map = _build_pos_stock_allowance_map_from_items(raw_items)
    if not stock_allowance_map:
        raise ValueError("Transaksi ini belum punya item aktif untuk diedit.")

    snapshot_map = _fetch_pos_product_snapshot_map(db, safe_sale["warehouse_id"], stock_allowance_map.keys())
    prepared_items = []
    missing_items = []

    for item in raw_items:
        product_id = _to_int(item.get("product_id"), 0)
        variant_id = _to_int(item.get("variant_id"), 0)
        active_qty = max(_to_int(item.get("active_qty"), 0), 0)
        if product_id <= 0 or variant_id <= 0 or active_qty <= 0:
            continue

        snapshot = snapshot_map.get((product_id, variant_id))
        if not snapshot:
            missing_items.append(
                f"{item.get('sku') or product_id} / {item.get('variant_name') or variant_id}"
            )
            continue

        unit_price = _currency(item.get("unit_price") or 0)
        retail_price = _currency(
            snapshot.get("price_nett")
            or snapshot.get("price_discount")
            or snapshot.get("price_retail")
            or unit_price
        )
        current_stock = _to_int(snapshot.get("stock_qty"), 0)

        prepared_items.append(
            {
                "key": f"{product_id}-{variant_id}",
                "product_id": product_id,
                "variant_id": variant_id,
                "sku": snapshot.get("sku") or item.get("sku") or "-",
                "name": snapshot.get("product_name") or item.get("product_name") or "Produk",
                "variant_label": snapshot.get("variant_name") or item.get("variant_name") or "default",
                "qty": active_qty,
                "unit_price": unit_price,
                "retail_price": retail_price,
                "stock": current_stock + active_qty,
                "current_stock": current_stock,
                "stock_allowance": active_qty,
            }
        )

    if missing_items:
        raise ValueError(
            "Sebagian item transaksi sudah tidak punya master produk aktif, jadi belum bisa diedit."
        )
    if not prepared_items:
        raise ValueError("Transaksi ini belum punya item aktif untuk diedit.")

    payment_breakdown_entries = list(safe_sale.get("payment_breakdown_entries") or [])
    return {
        "id": safe_sale["id"],
        "purchase_id": safe_sale["purchase_id"],
        "warehouse_id": safe_sale["warehouse_id"],
        "receipt_no": safe_sale["receipt_no"],
        "sale_date": safe_sale["sale_date"],
        "created_time_label": safe_sale.get("created_time_label") or "-",
        "created_datetime_label": safe_sale.get("created_datetime_label") or safe_sale.get("sale_date") or "-",
        "customer_id": _to_int(safe_sale.get("customer_id"), 0),
        "customer_name": safe_sale.get("customer_name") or "",
        "customer_phone": _normalize_pos_phone(safe_sale.get("customer_phone")),
        "transaction_type": normalize_transaction_type(safe_sale.get("transaction_type")),
        "cashier_user_id": _to_int(safe_sale.get("cashier_user_id"), 0),
        "payment_method": _normalize_payment_method(safe_sale.get("payment_method")),
        "paid_amount": _currency(safe_sale.get("paid_amount") or 0),
        "discount_type": _normalize_adjustment_type(safe_sale.get("discount_type")),
        "discount_value": _currency(safe_sale.get("discount_value") or 0),
        "tax_type": _normalize_adjustment_type(safe_sale.get("tax_type")),
        "tax_value": _currency(safe_sale.get("tax_value") or 0),
        "note": safe_sale.get("note") or "",
        "items": prepared_items,
        "is_split_payment": bool(safe_sale.get("has_payment_breakdown")),
        "payment_splits": [
            {
                "method": _normalize_payment_method(entry.get("method"), allow_split=False),
                "amount": _currency(entry.get("amount") or 0),
            }
            for entry in payment_breakdown_entries
            if _normalize_payment_method(entry.get("method"), allow_split=False) in PAYMENT_METHODS
            and _currency(entry.get("amount") or 0) > 0
        ],
        "stock_allowances": {
            f"{product_id}-{variant_id}": allowance_qty
            for (product_id, variant_id), allowance_qty in stock_allowance_map.items()
            if allowance_qty > 0
        },
    }


def _fetch_pos_staff_sales_rows(db, date_from, date_to, selected_warehouse=None):
    params = [date_from, date_to]
    query = f"""
        SELECT
            {POS_CASHIER_GROUP_KEY_SQL} AS staff_group_key,
            MIN(ps.cashier_user_id) AS cashier_user_id,
            {POS_CASHIER_NAME_SQL} AS staff_name,
            {POS_CASHIER_USERNAME_SQL} AS username,
            {POS_CASHIER_POSITION_SQL} AS position,
            COALESCE(MAX(NULLIF(TRIM(home_w.name), '')), '-') AS home_warehouse_name,
            COUNT(ps.id) AS total_transactions,
            COALESCE(SUM(ps.total_items), 0) AS total_items,
            COALESCE(SUM(ps.total_amount), 0) AS total_revenue,
            COALESCE(AVG(ps.total_amount), 0) AS average_ticket,
            COUNT(DISTINCT ps.customer_id) AS total_customers,
            COUNT(DISTINCT ps.warehouse_id) AS total_warehouses,
            GROUP_CONCAT(DISTINCT COALESCE(NULLIF(TRIM(sale_w.name), ''), '-')) AS warehouse_names,
            MIN(ps.sale_date) AS first_sale_date,
            MAX(ps.sale_date) AS last_sale_date
        FROM pos_sales ps
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses home_w ON home_w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        LEFT JOIN warehouses sale_w ON sale_w.id = ps.warehouse_id
        WHERE ps.sale_date BETWEEN ? AND ?
          AND COALESCE(ps.status, 'posted') <> 'voided'
          AND COALESCE(ps.is_hidden_archive, 0)=0
    """
    if selected_warehouse:
        query += " AND ps.warehouse_id=?"
        params.append(selected_warehouse)

    query += """
        GROUP BY
    """
    query += f"""
            {POS_CASHIER_GROUP_KEY_SQL},
            {POS_CASHIER_NAME_SQL},
            {POS_CASHIER_USERNAME_SQL},
            {POS_CASHIER_POSITION_SQL}
        ORDER BY total_revenue DESC, total_transactions DESC, LOWER(CAST({POS_CASHIER_NAME_SQL} AS TEXT)) ASC
    """

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    normalized_rows = []
    for index, row in enumerate(rows, start=1):
        total_revenue = _currency(row.get("total_revenue") or 0)
        average_ticket = _currency(row.get("average_ticket") or 0)
        warehouse_scope_label = (row.get("warehouse_names") or "").strip() or row.get("home_warehouse_name") or "-"
        normalized_rows.append(
            {
                **row,
                "rank": index,
                "total_transactions": int(row.get("total_transactions") or 0),
                "total_items": int(row.get("total_items") or 0),
                "total_customers": int(row.get("total_customers") or 0),
                "total_warehouses": int(row.get("total_warehouses") or 0),
                "total_revenue": total_revenue,
                "average_ticket": average_ticket,
                "total_revenue_label": _format_pos_currency_label(total_revenue),
                "average_ticket_label": _format_pos_currency_label(average_ticket),
                "warehouse_scope_label": warehouse_scope_label,
                "activity_label": _format_pos_period_label(row.get("first_sale_date"), row.get("last_sale_date")),
            }
        )
    return normalized_rows


def _fetch_pos_voidable_sale_item(db, item_id):
    params = [int(item_id)]
    query = """
        SELECT
            cpi.id AS item_id,
            cpi.purchase_id,
            cpi.product_id,
            cpi.variant_id,
            COALESCE(cpi.qty, 0) AS qty,
            COALESCE(cpi.unit_price, 0) AS unit_price,
            COALESCE(cpi.line_total, 0) AS line_total,
            COALESCE(cpi.void_qty, 0) AS void_qty,
            COALESCE(cpi.void_amount, 0) AS void_amount,
            ps.id AS sale_id,
            ps.warehouse_id,
            ps.receipt_no,
            ps.sale_date,
            ps.paid_amount,
            ps.discount_type,
            ps.discount_value,
            ps.tax_type,
            ps.tax_value,
            pr.member_id,
            pr.transaction_type,
            COALESCE(NULLIF(TRIM(p.sku), ''), '-') AS sku,
            COALESCE(NULLIF(TRIM(p.name), ''), 'Produk') AS product_name,
            COALESCE(NULLIF(TRIM(pv.variant), ''), 'default') AS variant_name
        FROM crm_purchase_items cpi
        JOIN pos_sales ps ON ps.purchase_id = cpi.purchase_id
        JOIN crm_purchase_records pr ON pr.id = cpi.purchase_id
        LEFT JOIN products p ON p.id = cpi.product_id
        LEFT JOIN product_variants pv ON pv.id = cpi.variant_id
        WHERE cpi.id=?
    """

    if is_scoped_role(session.get("role")):
        query += " AND ps.warehouse_id=?"
        params.append(session.get("warehouse_id"))

    query += " LIMIT 1"
    row = db.execute(query, params).fetchone()
    return dict(row) if row else None


def _resolve_pos_stock_restore_cost(db, product_id, variant_id, warehouse_id):
    row = db.execute(
        """
        SELECT cost
        FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=? AND COALESCE(cost, 0) > 0
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT 1
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchone()
    return _currency(row["cost"] if row else 0)


def _apply_pos_sale_rollup_updates(db, sale_row, acting_user_id):
    purchase_items = [
        dict(row)
        for row in db.execute(
            """
            SELECT
                id,
                qty,
                unit_price,
                line_total,
                COALESCE(void_qty, 0) AS void_qty,
                COALESCE(void_amount, 0) AS void_amount
            FROM crm_purchase_items
            WHERE purchase_id=?
            ORDER BY id ASC
            """,
            (sale_row["purchase_id"],),
        ).fetchall()
    ]

    active_items = []
    any_void = False
    for item in purchase_items:
        sold_qty = int(item.get("qty") or 0)
        void_qty = max(0, int(item.get("void_qty") or 0))
        active_qty = max(sold_qty - void_qty, 0)
        active_line_total = (
            _to_decimal(item.get("line_total"), "0")
            - _to_decimal(item.get("void_amount"), "0")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if void_qty > 0:
            any_void = True

        if active_qty <= 0 or active_line_total <= 0:
            continue

        active_items.append(
            {
                "qty": active_qty,
                "line_total": active_line_total,
            }
        )

    financials = _build_pos_sale_financials(
        active_items,
        discount_type=sale_row.get("discount_type"),
        discount_value=sale_row.get("discount_value"),
        tax_type=sale_row.get("tax_type"),
        tax_value=sale_row.get("tax_value"),
    )

    paid_amount = _to_decimal(sale_row.get("paid_amount"), "0")
    change_amount = max(paid_amount - financials["total_amount"], Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if financials["total_items"] <= 0:
        next_status = "voided"
    elif any_void:
        next_status = "partial_void"
    else:
        next_status = "posted"

    db.execute(
        """
        UPDATE pos_sales
        SET
            total_items=?,
            subtotal_amount=?,
            discount_type=?,
            discount_value=?,
            discount_amount=?,
            tax_type=?,
            tax_value=?,
            tax_amount=?,
            total_amount=?,
            change_amount=?,
            status=?,
            voided_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE voided_at END,
            voided_by=CASE WHEN ? THEN ? ELSE voided_by END,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            financials["total_items"],
            _currency(financials["subtotal_amount"]),
            financials["discount_type"],
            _currency(financials["discount_value"]),
            _currency(financials["discount_amount"]),
            financials["tax_type"],
            _currency(financials["tax_value"]),
            _currency(financials["tax_amount"]),
            _currency(financials["total_amount"]),
            _currency(change_amount),
            next_status,
            1 if any_void else 0,
            1 if any_void else 0,
            acting_user_id,
            sale_row.get("sale_id") or sale_row.get("id"),
        ),
    )

    db.execute(
        """
        UPDATE crm_purchase_records
        SET
            items_count=?,
            total_amount=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            financials["total_items"],
            _currency(financials["total_amount"]),
            sale_row["purchase_id"],
        ),
    )

    if _to_int(sale_row.get("member_id"), 0) > 0:
        member_snapshot = get_member_snapshot(db, sale_row["member_id"])
        if member_snapshot:
            loyalty_fields = calculate_loyalty_fields(
                member_snapshot,
                _currency(financials["total_amount"]),
                sale_row.get("transaction_type"),
                active=financials["total_items"] > 0,
                items=items,
            )
            db.execute(
                """
                UPDATE crm_member_records
                SET
                    amount=?,
                    points_delta=?,
                    service_count_delta=?,
                    reward_redeemed_delta=?,
                    benefit_value=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE purchase_id=?
                """,
                (
                    _currency(financials["total_amount"]),
                    loyalty_fields["points_delta"],
                    loyalty_fields["service_count_delta"],
                    loyalty_fields["reward_redeemed_delta"],
                    loyalty_fields["benefit_value"],
                    sale_row["purchase_id"],
                ),
            )

    return {
        **financials,
        "paid_amount": paid_amount,
        "change_amount": change_amount,
        **_build_pos_sale_status_payload(next_status),
    }


@pos_bp.route("/")
def pos_page():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    can_view_pos_revenue = _can_view_pos_revenue()
    selected_warehouse = _resolve_pos_warehouse(db, request.args.get("warehouse"))
    requested_edit_sale_id = _to_int(request.args.get("edit_sale_id"), 0)
    sale_date = _resolve_active_pos_sale_date(request.args.get("sale_date"))
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None
    editing_sale_payload = None

    warehouses = db.execute(
        "SELECT id, name FROM warehouses ORDER BY name"
    ).fetchall()
    if requested_edit_sale_id > 0:
        editing_sale = _fetch_pos_sale_detail_by_id(db, requested_edit_sale_id)
        if editing_sale is None:
            flash("Transaksi POS yang ingin diedit tidak ditemukan atau tidak bisa diakses.", "error")
        else:
            try:
                editing_sale_payload = _build_pos_edit_sale_payload(db, editing_sale)
                selected_warehouse = _to_int(editing_sale_payload.get("warehouse_id"), selected_warehouse) or selected_warehouse
                sale_date = str(editing_sale_payload.get("sale_date") or sale_date)
            except ValueError as exc:
                flash(str(exc), "error")

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
    )
    pos_staff_options = _fetch_pos_staff_options(db, selected_warehouse)
    preferred_staff_user_id = (
        _to_int((editing_sale_payload or {}).get("cashier_user_id"), 0)
        or _to_int(session.get("user_id"), 0)
    )
    selected_pos_staff_option = next(
        (option for option in pos_staff_options if option["id"] == preferred_staff_user_id),
        pos_staff_options[0] if pos_staff_options else None,
    )

    if selected_pos_staff_option is None:
        selected_pos_staff_option = {
            "id": preferred_staff_user_id,
            "username": session.get("username", "-"),
            "display_name": session.get("username", "-"),
            "label": session.get("username", "-"),
            "role": session.get("role"),
            "warehouse_id": selected_warehouse,
        }
        pos_staff_options = [selected_pos_staff_option]

    sales_log_rows = _fetch_pos_sale_logs(
        db,
        sale_date,
        sale_date,
        selected_warehouse=selected_warehouse,
        limit=24,
    )
    summary = _fetch_pos_summary(db, selected_warehouse, sale_date)
    if not can_view_pos_revenue:
        summary["total_revenue"] = 0
    sales_log_summary = _mask_pos_sale_log_summary(
        _build_pos_sale_log_summary(sales_log_rows, sale_date),
        can_view_pos_revenue,
    )
    sales_log_rows = _mask_pos_sale_log_rows(sales_log_rows, can_view_pos_revenue)

    return render_template(
        "pos.html",
        payment_methods=PAYMENT_METHODS,
        printer_driver_resources=POS_PRINTER_DRIVER_RESOURCES,
        warehouses=warehouses,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        scoped_warehouse=scoped_warehouse,
        sale_date=sale_date,
        customer_options=_fetch_pos_customers(db, selected_warehouse),
        transaction_type_labels=CRM_TRANSACTION_TYPE_LABELS,
        default_stringing_reward_amount=DEFAULT_STRINGING_REWARD_AMOUNT,
        stringing_progress_min_amount=STRINGING_PROGRESS_MIN_AMOUNT,
        pos_staff_options=pos_staff_options,
        selected_pos_staff_id=selected_pos_staff_option["id"],
        selected_pos_staff_label=selected_pos_staff_option["display_name"],
        pos_auto_print_after_checkout=bool(current_app.config.get("POS_AUTO_PRINT_AFTER_CHECKOUT")),
        can_view_pos_revenue=can_view_pos_revenue,
        editing_sale=editing_sale_payload,
        summary=summary,
        recent_sales=_fetch_recent_sales(db, selected_warehouse, sale_date),
        sales_log_rows=sales_log_rows,
        sales_log_summary=sales_log_summary,
    )


@pos_bp.get("/options/customers")
def pos_customer_options():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    selected_warehouse = _resolve_pos_warehouse(db, request.args.get("warehouse"))
    search = str(request.args.get("q") or "").strip()
    limit = _coerce_pos_customer_option_limit(request.args.get("limit"))
    customers = _fetch_pos_customers(db, selected_warehouse, search=search, limit=limit)

    return jsonify(
        {
            "items": [
                {
                    "id": customer["id"],
                    "label": " | ".join(
                        part
                        for part in (
                            str(customer.get("customer_name") or "").strip(),
                            str(customer.get("phone") or "").strip(),
                            str(customer.get("member_code") or "").strip(),
                        )
                        if part
                    ),
                    "customer_name": customer["customer_name"],
                    "phone": customer.get("phone") or "",
                    "member_code": customer.get("member_code") or "",
                    "member_type": customer.get("member_type") or "",
                    "reward_unit_amount": customer.get("reward_unit_amount") or DEFAULT_STRINGING_REWARD_AMOUNT,
                }
                for customer in customers
            ]
        }
    )


@pos_bp.get("/printer-drivers")
def pos_printer_driver_center():
    denied = _require_pos_access()
    if denied:
        return denied

    return render_template(
        "pos_printer_drivers.html",
        driver_resources=POS_PRINTER_DRIVER_RESOURCES,
    )


@pos_bp.get("/staff-sales")
def pos_staff_sales_report():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    can_view_pos_revenue = _can_view_pos_revenue()
    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None
    selected_warehouse = _resolve_pos_warehouse(db, request.args.get("warehouse"))
    week_period = _resolve_week_range(request.args.get("week_date"))
    month_period = _resolve_month_range(request.args.get("month"))
    manual_period = _normalize_pos_log_date_range(
        request.args.get("date_from") or week_period["date_from"],
        request.args.get("date_to") or week_period["date_to"],
    )

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
    )

    manual_rows = _fetch_pos_staff_sales_rows(
        db,
        manual_period["date_from"],
        manual_period["date_to"],
        selected_warehouse=selected_warehouse,
    )
    weekly_rows = _fetch_pos_staff_sales_rows(
        db,
        week_period["date_from"],
        week_period["date_to"],
        selected_warehouse=selected_warehouse,
    )
    monthly_rows = _fetch_pos_staff_sales_rows(
        db,
        month_period["date_from"],
        month_period["date_to"],
        selected_warehouse=selected_warehouse,
    )
    manual_summary = _mask_pos_staff_sales_summary(
        _build_pos_staff_sales_summary(manual_rows, manual_period["label"]),
        can_view_pos_revenue,
    )
    weekly_summary = _mask_pos_staff_sales_summary(
        _build_pos_staff_sales_summary(weekly_rows, week_period["label"]),
        can_view_pos_revenue,
    )
    monthly_summary = _mask_pos_staff_sales_summary(
        _build_pos_staff_sales_summary(monthly_rows, month_period["label"]),
        can_view_pos_revenue,
    )
    manual_rows = _mask_pos_staff_sales_rows(manual_rows, can_view_pos_revenue)
    weekly_rows = _mask_pos_staff_sales_rows(weekly_rows, can_view_pos_revenue)
    monthly_rows = _mask_pos_staff_sales_rows(monthly_rows, can_view_pos_revenue)

    return render_template(
        "pos_staff_sales_report.html",
        warehouses=warehouses,
        scoped_warehouse=scoped_warehouse,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        manual_period=manual_period,
        week_period=week_period,
        month_period=month_period,
        can_view_pos_revenue=can_view_pos_revenue,
        manual_rows=manual_rows,
        weekly_rows=weekly_rows,
        monthly_rows=monthly_rows,
        manual_summary=manual_summary,
        weekly_summary=weekly_summary,
        monthly_summary=monthly_summary,
    )


@pos_bp.get("/log")
def pos_sales_log_page():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    can_view_pos_revenue = _can_view_pos_revenue()
    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None
    selected_warehouse = _resolve_pos_warehouse(db, request.args.get("warehouse"))
    date_range = _normalize_pos_log_date_range(request.args.get("date_from"), request.args.get("date_to"))
    cashier_filter_id = _to_int(request.args.get("cashier_user_id"), 0)
    selected_cashier_user_id = cashier_filter_id if cashier_filter_id > 0 else None
    wa_failed_only = str(request.args.get("wa_failed") or "").strip().lower() in {"1", "true", "yes", "on"}
    cashier_filter_options = _fetch_pos_staff_options(db, selected_warehouse)
    if selected_cashier_user_id and not any(option["id"] == selected_cashier_user_id for option in cashier_filter_options):
        selected_cashier_user_id = None

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
    )

    sales_log_rows = _fetch_pos_sale_logs(
        db,
        date_range["date_from"],
        date_range["date_to"],
        selected_warehouse=selected_warehouse,
        cashier_user_id=selected_cashier_user_id,
        search_query=request.args.get("search"),
        limit=120,
        receipt_wa_status="failed" if wa_failed_only else "",
    )
    sales_log_summary = _mask_pos_sale_log_summary(
        _build_pos_sale_log_summary(sales_log_rows, date_range["label"]),
        can_view_pos_revenue,
    )
    sales_log_rows = _mask_pos_sale_log_rows(sales_log_rows, can_view_pos_revenue)
    cash_closing_actor = _fetch_pos_cash_closing_actor(db, selected_warehouse)
    cash_closing_default_date = date_range["date_to"]
    cash_closing_defaults = _build_pos_cash_closing_defaults(
        db,
        selected_warehouse_name,
        cash_closing_default_date,
        warehouse_id=selected_warehouse,
    )

    return render_template(
        "pos_sales_log.html",
        warehouses=warehouses,
        scoped_warehouse=scoped_warehouse,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        cashier_filter_options=cashier_filter_options,
        selected_cashier_user_id=selected_cashier_user_id,
        wa_failed_only=wa_failed_only,
        search_query=str(request.args.get("search") or "").strip(),
        date_range=date_range,
        can_view_pos_revenue=can_view_pos_revenue,
        sales_log_rows=sales_log_rows,
        sales_log_summary=sales_log_summary,
        payment_methods=PAYMENT_METHODS,
        payment_method_labels={method: _format_payment_method_label(method) for method in PAYMENT_METHODS},
        cash_closing_actor=cash_closing_actor,
        cash_closing_default_date=cash_closing_default_date,
        cash_closing_defaults=cash_closing_defaults,
        cash_closing_preview_text=cash_closing_defaults["preview_text"],
        cash_closing_return_url=_build_pos_cash_closing_return_url(),
        can_edit_cash_closing=str(session.get("role") or "").strip().lower() == "super_admin",
    )


@pos_bp.get("/hidden-archive")
def pos_hidden_archive_page():
    denied = _require_pos_access()
    if denied:
        return denied

    if not _can_manage_pos_hidden_archive():
        flash("Hidden Archive POS hanya tersedia untuk super admin.", "error")
        return redirect("/kasir/log")

    db = get_db()
    can_view_pos_revenue = _can_view_pos_revenue()
    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None
    selected_warehouse = _resolve_pos_warehouse(db, request.args.get("warehouse"))
    date_range = _normalize_pos_log_date_range(request.args.get("date_from"), request.args.get("date_to"))
    cashier_filter_id = _to_int(request.args.get("cashier_user_id"), 0)
    selected_cashier_user_id = cashier_filter_id if cashier_filter_id > 0 else None
    cashier_filter_options = _fetch_pos_staff_options(db, selected_warehouse)
    if selected_cashier_user_id and not any(option["id"] == selected_cashier_user_id for option in cashier_filter_options):
        selected_cashier_user_id = None

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
    )
    query_string = request.query_string.decode("utf-8", errors="ignore").strip()
    current_return_url = f"/kasir/hidden-archive?{query_string}" if query_string else "/kasir/hidden-archive"
    archive_unlocked = _is_pos_hidden_archive_unlocked()
    unlock_timeout_minutes = max(_get_pos_hidden_archive_unlock_seconds() // 60, 5)

    sales_log_rows = []
    sales_log_summary = _mask_pos_sale_log_summary(
        _build_pos_sale_log_summary([], date_range["label"]),
        can_view_pos_revenue,
    )
    if archive_unlocked:
        sales_log_rows = _fetch_pos_sale_logs(
            db,
            date_range["date_from"],
            date_range["date_to"],
            selected_warehouse=selected_warehouse,
            cashier_user_id=selected_cashier_user_id,
            search_query=request.args.get("search"),
            limit=120,
            archive_mode="hidden_only",
        )
        sales_log_summary = _mask_pos_sale_log_summary(
            _build_pos_sale_log_summary(sales_log_rows, date_range["label"]),
            can_view_pos_revenue,
        )
        sales_log_rows = _mask_pos_sale_log_rows(sales_log_rows, can_view_pos_revenue)

    return render_template(
        "pos_hidden_archive.html",
        archive_unlocked=archive_unlocked,
        unlock_timeout_minutes=unlock_timeout_minutes,
        hidden_archive_return_url=current_return_url,
        warehouses=warehouses,
        scoped_warehouse=scoped_warehouse,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        cashier_filter_options=cashier_filter_options,
        selected_cashier_user_id=selected_cashier_user_id,
        search_query=str(request.args.get("search") or "").strip(),
        date_range=date_range,
        can_view_pos_revenue=can_view_pos_revenue,
        sales_log_rows=sales_log_rows,
        sales_log_summary=sales_log_summary,
    )


@pos_bp.post("/hidden-archive/unlock")
def pos_hidden_archive_unlock():
    denied = _require_pos_access()
    if denied:
        return denied

    if not _can_manage_pos_hidden_archive():
        flash("Hidden Archive POS hanya tersedia untuk super admin.", "error")
        return redirect("/kasir/log")

    return_url = _sanitize_pos_hidden_archive_return_url(request.form.get("return_url"))
    archive_password = str(request.form.get("archive_password") or "").strip()
    if archive_password != _get_pos_hidden_archive_password():
        _lock_pos_hidden_archive()
        flash("Password Hidden Archive tidak cocok.", "error")
        return redirect(return_url)

    _unlock_pos_hidden_archive()
    flash("Hidden Archive berhasil dibuka.", "success")
    return redirect(return_url)


@pos_bp.post("/hidden-archive/lock")
def pos_hidden_archive_lock():
    denied = _require_pos_access()
    if denied:
        return denied

    if not _can_manage_pos_hidden_archive():
        flash("Hidden Archive POS hanya tersedia untuk super admin.", "error")
        return redirect("/kasir/log")

    _lock_pos_hidden_archive()
    flash("Hidden Archive dikunci lagi.", "info")
    return redirect(_sanitize_pos_hidden_archive_return_url(request.form.get("return_url")))


@pos_bp.post("/sale/<int:sale_id>/archive")
def pos_archive_sale(sale_id):
    denied = _require_pos_access(json_mode=request.is_json)
    if denied:
        return denied

    if not _can_archive_pos_sale():
        if request.is_json:
            return _json_error("Hanya super admin yang bisa menghapus transaksi ke Hidden Archive.", 403)
        flash("Hanya super admin yang bisa menghapus transaksi ke Hidden Archive.", "error")
        return redirect(_sanitize_pos_sales_action_return_url(request.form.get("return_url")))

    request_data = request.get_json(silent=True) or {} if request.is_json else request.form
    return_url = _sanitize_pos_sales_action_return_url(request_data.get("return_url"))
    db = get_db()
    sale = _fetch_pos_sale_detail_by_id(db, sale_id, allow_hidden_archive=True)
    if sale is None:
        if request.is_json:
            return _json_error("Transaksi POS tidak ditemukan atau tidak bisa diakses.", 404)
        flash("Transaksi POS tidak ditemukan atau tidak bisa diakses.", "error")
        return redirect(return_url)

    if sale.get("is_hidden_archive"):
        message = f"Transaksi {sale['receipt_no']} sudah dihapus dari log penjualan dan ada di Hidden Archive."
        if request.is_json:
            return jsonify({"status": "success", "message": message, "sale_id": sale["id"], "receipt_no": sale["receipt_no"], "unchanged": True})
        return redirect(return_url)

    archive_note = str(request_data.get("note") or "").strip() or None
    try:
        db.execute(
            """
            UPDATE pos_sales
            SET
                is_hidden_archive=1,
                hidden_archive_at=CURRENT_TIMESTAMP,
                hidden_archive_by=?,
                hidden_archive_note=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (_to_int(session.get("user_id"), 0) or None, archive_note, sale["id"]),
        )
        _sync_pos_cash_closing_report_snapshot(db, sale)
        db.commit()
    except Exception:
        db.rollback()
        if request.is_json:
            return _json_error("Transaksi gagal dipindahkan ke Hidden Archive. Coba lagi beberapa detik.", 500)
        flash("Transaksi gagal dipindahkan ke Hidden Archive. Coba lagi beberapa detik.", "error")
        return redirect(return_url)

    success_message = (
        f"Transaksi {sale['receipt_no']} dihapus dari log penjualan "
        "dan dipindahkan ke Hidden Archive."
    )
    if request.is_json:
        return jsonify({"status": "success", "message": success_message, "sale_id": sale["id"], "receipt_no": sale["receipt_no"]})

    return redirect(return_url)


@pos_bp.post("/sale/<int:sale_id>/unarchive")
def pos_unarchive_sale(sale_id):
    denied = _require_pos_access(json_mode=request.is_json)
    if denied:
        return denied

    if not _can_manage_pos_hidden_archive():
        if request.is_json:
            return _json_error("Hanya super admin yang bisa memulihkan transaksi Hidden Archive.", 403)
        flash("Hanya super admin yang bisa memulihkan transaksi Hidden Archive.", "error")
        return redirect(_sanitize_pos_sales_action_return_url(request.form.get("return_url")))

    if not _is_pos_hidden_archive_unlocked():
        if request.is_json:
            return _json_error("Hidden Archive masih terkunci. Masukkan password global dulu.", 403)
        flash("Hidden Archive masih terkunci. Masukkan password global dulu.", "error")
        return redirect(_sanitize_pos_hidden_archive_return_url(request.form.get("return_url")))

    request_data = request.get_json(silent=True) or {} if request.is_json else request.form
    return_url = _sanitize_pos_sales_action_return_url(request_data.get("return_url"))
    db = get_db()
    sale = _fetch_pos_sale_detail_by_id(db, sale_id, allow_hidden_archive=True)
    if sale is None:
        if request.is_json:
            return _json_error("Transaksi POS tidak ditemukan atau tidak bisa diakses.", 404)
        flash("Transaksi POS tidak ditemukan atau tidak bisa diakses.", "error")
        return redirect(return_url)

    if not sale.get("is_hidden_archive"):
        message = f"Transaksi {sale['receipt_no']} sudah aktif di log POS biasa."
        if request.is_json:
            return jsonify({"status": "success", "message": message, "sale_id": sale["id"], "receipt_no": sale["receipt_no"], "unchanged": True})
        return redirect(return_url)

    try:
        db.execute(
            """
            UPDATE pos_sales
            SET
                is_hidden_archive=0,
                hidden_archive_at=NULL,
                hidden_archive_by=NULL,
                hidden_archive_note=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (sale["id"],),
        )
        _sync_pos_cash_closing_report_snapshot(db, sale)
        db.commit()
    except Exception:
        db.rollback()
        if request.is_json:
            return _json_error("Transaksi gagal dipulihkan dari Hidden Archive. Coba lagi beberapa detik.", 500)
        flash("Transaksi gagal dipulihkan dari Hidden Archive. Coba lagi beberapa detik.", "error")
        return redirect(return_url)

    success_message = f"Transaksi {sale['receipt_no']} dikembalikan ke log POS biasa."
    if request.is_json:
        return jsonify({"status": "success", "message": success_message, "sale_id": sale["id"], "receipt_no": sale["receipt_no"]})

    return redirect(return_url)


def _fetch_recent_pos_sales(db, limit=18):
    safe_limit = max(1, min(_to_int(limit, 18), 50))
    params = []
    query = """
        SELECT
            ps.receipt_no,
            ps.sale_date,
            ps.created_at,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        LEFT JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN warehouses w ON w.id = ps.warehouse_id
        WHERE 1=1
    """
    query += " AND COALESCE(ps.is_hidden_archive, 0)=0"
    if is_scoped_role(session.get("role")):
        query += " AND ps.warehouse_id=?"
        params.append(session.get("warehouse_id"))
    query += " ORDER BY ps.created_at DESC, ps.id DESC LIMIT ?"
    params.append(safe_limit)
    rows = db.execute(query, params).fetchall()
    recent = []
    for row in rows:
        recent.append(
            {
                "receipt_no": row["receipt_no"],
                "sale_date": row["sale_date"],
                "created_time_label": _format_pos_time_label(row["created_at"]),
                "customer_name": row["customer_name"],
                "warehouse_name": row["warehouse_name"],
            }
        )
    return recent


def _safe_pos_branding(sale_detail):
    try:
        return build_pos_receipt_branding(sale_detail or {})
    except Exception:
        current_app.logger.exception("Failed to build POS branding payload for invoice/surat jalan")
        return {
            "business_name": current_app.config.get("STORE_NAME") or "POS",
            "business_address": "",
            "customer_service_phone": current_app.config.get("STORE_PHONE") or "",
            "footer_note": "",
            "feedback_line": "",
            "social_label": "",
            "social_media_url": "",
            "logo_url": "/static/brand/mataram-logo.png",
            "logo_pdf_path": "",
        }


@pos_bp.get("/invoice")
def pos_invoice_page():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    receipt_no = str(request.args.get("receipt_no") or "").strip()
    sale_detail = None
    recent_sales = []
    if receipt_no:
        try:
            sale_detail = _fetch_pos_sale_detail_by_receipt(db, receipt_no)
        except Exception:
            current_app.logger.exception("POS invoice: failed to fetch sale detail")
        if sale_detail is None:
            flash("Nota POS tidak ditemukan. Pastikan nomor receipt benar.", "error")
    try:
        recent_sales = _fetch_recent_pos_sales(db)
    except Exception:
        current_app.logger.exception("POS invoice: failed to load recent sales")
        recent_sales = []
    branding = _safe_pos_branding(sale_detail)

    return render_template(
        "pos_invoice.html",
        receipt_no=receipt_no,
        sale_detail=sale_detail,
        recent_sales=recent_sales,
        branding=branding,
    )


@pos_bp.get("/invoice/manual")
def pos_invoice_manual_page():
    denied = _require_pos_access()
    if denied:
        return denied

    now = datetime.now(POS_DISPLAY_TIMEZONE)
    date_label = now.strftime("%Y-%m-%d")
    branding = _safe_pos_branding({})
    return render_template(
        "pos_invoice_manual.html",
        invoice_date=date_label,
        due_date=date_label,
        branding=branding,
    )


@pos_bp.get("/surat-jalan/manual")
def pos_delivery_note_manual_page():
    denied = _require_pos_access()
    if denied:
        return denied

    now = datetime.now(POS_DISPLAY_TIMEZONE)
    date_label = now.strftime("%Y-%m-%d")
    branding = _safe_pos_branding({})
    return render_template(
        "pos_delivery_note_manual.html",
        document_date=date_label,
        branding=branding,
    )


@pos_bp.get("/invoice/<receipt_no>/print")
def pos_invoice_print(receipt_no):
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    sale_detail = _fetch_pos_sale_detail_by_receipt(db, receipt_no)
    if sale_detail is None:
        abort(404)
    branding = _safe_pos_branding(sale_detail)
    return render_template("pos_invoice_print.html", sale=sale_detail, branding=branding)


@pos_bp.get("/surat-jalan")
def pos_delivery_note_page():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    receipt_no = str(request.args.get("receipt_no") or "").strip()
    sale_detail = None
    recent_sales = []
    if receipt_no:
        try:
            sale_detail = _fetch_pos_sale_detail_by_receipt(db, receipt_no)
        except Exception:
            current_app.logger.exception("POS surat jalan: failed to fetch sale detail")
        if sale_detail is None:
            flash("Nota POS tidak ditemukan. Pastikan nomor receipt benar.", "error")
    try:
        recent_sales = _fetch_recent_pos_sales(db)
    except Exception:
        current_app.logger.exception("POS surat jalan: failed to load recent sales")
        recent_sales = []
    branding = _safe_pos_branding(sale_detail)

    return render_template(
        "pos_delivery_note.html",
        receipt_no=receipt_no,
        sale_detail=sale_detail,
        recent_sales=recent_sales,
        branding=branding,
    )


@pos_bp.get("/surat-jalan/<receipt_no>/print")
def pos_delivery_note_print(receipt_no):
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    sale_detail = _fetch_pos_sale_detail_by_receipt(db, receipt_no)
    if sale_detail is None:
        abort(404)
    branding = _safe_pos_branding(sale_detail)
    return render_template("pos_delivery_note_print.html", sale=sale_detail, branding=branding)


@pos_bp.get("/cash-closing/history")
def pos_cash_closing_history_page():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None
    selected_warehouse = _resolve_pos_warehouse(db, request.args.get("warehouse"))
    date_range = _normalize_pos_log_date_range(request.args.get("date_from"), request.args.get("date_to"))

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
    )

    cash_closing_reports = _fetch_pos_cash_closing_reports(
        db,
        warehouse_id=selected_warehouse,
        date_from=date_range["date_from"],
        date_to=date_range["date_to"],
        limit=40,
    )

    return render_template(
        "pos_cash_closing_history.html",
        warehouses=warehouses,
        scoped_warehouse=scoped_warehouse,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        date_range=date_range,
        cash_closing_reports=cash_closing_reports,
        can_view_pos_revenue=_can_view_pos_revenue(),
    )


@pos_bp.post("/sale/<int:sale_id>/payment-method")
def pos_update_sale_payment_method(sale_id):
    denied = _require_pos_access(json_mode=request.is_json)
    if denied:
        return denied

    if request.is_json:
        request_data = request.get_json(silent=True) or {}
    else:
        request_data = request.form

    if not has_permission(session.get("role"), "manage_pos"):
        if request.is_json:
            return _json_error("Role ini belum punya izin mengganti metode pembayaran POS.", 403)
        flash("Role ini belum punya izin mengganti metode pembayaran POS.", "error")
        return redirect(_sanitize_pos_cash_closing_return_url(request_data.get("return_url")))

    db = get_db()
    sale = _fetch_pos_sale_detail_by_id(db, sale_id)
    if sale is None:
        if request.is_json:
            return _json_error("Transaksi POS tidak ditemukan atau tidak bisa diakses.", 404)
        flash("Transaksi POS tidak ditemukan atau tidak bisa diakses.", "error")
        return redirect(_sanitize_pos_cash_closing_return_url(request_data.get("return_url")))

    sale_status = str(sale.get("status") or "posted").strip().lower()
    if sale_status == "voided":
        if request.is_json:
            return _json_error("Transaksi yang sudah void penuh tidak bisa diganti metode pembayarannya.", 400)
        flash("Transaksi yang sudah void penuh tidak bisa diganti metode pembayarannya.", "error")
        return redirect(_sanitize_pos_cash_closing_return_url(request_data.get("return_url")))

    raw_payment_method = request_data.get("payment_method")
    requested_payment_method = _normalize_payment_method(raw_payment_method, allow_split=False)
    if requested_payment_method not in PAYMENT_METHODS:
        if request.is_json:
            return _json_error("Metode pembayaran tidak valid.", 400)
        flash("Metode pembayaran tidak valid.", "error")
        return redirect(_sanitize_pos_cash_closing_return_url(request_data.get("return_url")))

    current_payment_method = _normalize_payment_method(sale.get("payment_method"))
    if requested_payment_method == current_payment_method:
        message = f"Metode pembayaran transaksi {sale['receipt_no']} sudah { _format_payment_method_label(current_payment_method) }."
        if request.is_json:
            return jsonify(
                {
                    "status": "success",
                    "message": message,
                    "sale_id": sale["id"],
                    "receipt_no": sale["receipt_no"],
                    "payment_method": current_payment_method,
                    "payment_method_label": _format_payment_method_label(current_payment_method),
                    "unchanged": True,
                }
            )
        flash(message, "info")
        return redirect(_sanitize_pos_cash_closing_return_url(request_data.get("return_url")))

    has_cash_closing_report = _has_pos_cash_closing_report(db, sale)
    try:
        db.execute(
            """
            UPDATE pos_sales
            SET payment_method=?,
                payment_breakdown_json=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (requested_payment_method, sale["id"]),
        )
        db.commit()
    except Exception:
        db.rollback()
        if request.is_json:
            return _json_error("Metode pembayaran gagal diperbarui. Coba ulangi beberapa detik lagi.", 500)
        flash("Metode pembayaran gagal diperbarui. Coba ulangi beberapa detik lagi.", "error")
        return redirect(_sanitize_pos_cash_closing_return_url(request_data.get("return_url")))

    success_message = (
        f"Metode pembayaran {sale['receipt_no']} diubah dari "
        f"{_format_payment_method_label(current_payment_method)} ke "
        f"{_format_payment_method_label(requested_payment_method)}."
    )
    if has_cash_closing_report:
        success_message += " Laporan tutup kasir yang sudah tersimpan tidak otomatis ikut diperbarui."

    if request.is_json:
        return jsonify(
            {
                "status": "success",
                "message": success_message,
                "sale_id": sale["id"],
                "receipt_no": sale["receipt_no"],
                "payment_method": requested_payment_method,
                "payment_method_label": _format_payment_method_label(requested_payment_method),
                "had_cash_closing_report": has_cash_closing_report,
            }
        )

    flash(success_message, "success")
    return redirect(_sanitize_pos_cash_closing_return_url(request_data.get("return_url")))


@pos_bp.post("/sale/<int:sale_id>/sale-date")
def pos_update_sale_date(sale_id):
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    if not has_permission(session.get("role"), "manage_pos"):
        return _json_error("Role ini belum punya izin mengubah tanggal transaksi POS.", 403)

    payload = request.get_json(silent=True) or {}
    db = get_db()
    ensure_crm_membership_multi_program_schema(db)
    sale = _fetch_pos_sale_detail_by_id(db, sale_id)
    if sale is None:
        return _json_error("Transaksi POS tidak ditemukan atau tidak bisa diakses.", 404)

    purchase_id = _to_int(sale.get("purchase_id"), 0)
    if purchase_id <= 0:
        return _json_error("Transaksi POS ini belum punya relasi data pembelian yang bisa dikoreksi.", 400)

    try:
        requested_sale_date = _normalize_editable_pos_sale_date(payload.get("sale_date"))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    current_sale_date = _normalize_sale_date(sale.get("sale_date"))
    if requested_sale_date == current_sale_date:
        return jsonify(
            {
                "status": "success",
                "message": f"Tanggal transaksi {sale['receipt_no']} sudah {current_sale_date}.",
                "sale_id": sale["id"],
                "receipt_no": sale["receipt_no"],
                "sale_date": current_sale_date,
                "unchanged": True,
            }
        )

    old_sale_snapshot = {**dict(sale), "sale_date": current_sale_date}
    new_sale_snapshot = {**dict(sale), "sale_date": requested_sale_date}
    had_old_cash_closing_report = _has_pos_cash_closing_report(db, old_sale_snapshot)
    had_new_cash_closing_report = _has_pos_cash_closing_report(db, new_sale_snapshot)

    try:
        db.execute("BEGIN")
        db.execute(
            """
            UPDATE pos_sales
            SET
                sale_date=?,
                receipt_pdf_path=NULL,
                receipt_pdf_url=NULL,
                receipt_whatsapp_status='pending',
                receipt_whatsapp_error=NULL,
                receipt_whatsapp_sent_at=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (requested_sale_date, sale["id"]),
        )
        db.execute(
            """
            UPDATE crm_purchase_records
            SET
                purchase_date=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (requested_sale_date, purchase_id),
        )
        db.execute(
            """
            UPDATE crm_member_records
            SET record_date=?
            WHERE purchase_id=?
            """,
            (requested_sale_date, purchase_id),
        )
        _sync_pos_cash_closing_report_snapshot(db, old_sale_snapshot)
        _sync_pos_cash_closing_report_snapshot(db, new_sale_snapshot)
        db.commit()
    except Exception:
        db.rollback()
        current_app.logger.exception("POS sale date update failed")
        return _json_error("Tanggal transaksi gagal diperbarui. Coba ulangi beberapa detik lagi.", 500)

    success_message = (
        f"Tanggal transaksi {sale['receipt_no']} dipindah dari {current_sale_date} ke {requested_sale_date}. "
        "No nota dan jam awal tetap dipertahankan."
    )
    if had_old_cash_closing_report or had_new_cash_closing_report:
        success_message += " Rekap tutup kasir terkait ikut disinkronkan otomatis."

    return jsonify(
        {
            "status": "success",
            "message": success_message,
            "sale_id": sale["id"],
            "receipt_no": sale["receipt_no"],
            "sale_date": requested_sale_date,
            "previous_sale_date": current_sale_date,
            "had_cash_closing_report": had_old_cash_closing_report or had_new_cash_closing_report,
        }
    )


@pos_bp.get("/cash-closing/defaults")
def pos_cash_closing_defaults():
    denied = _require_pos_access()
    if denied:
        return jsonify({"status": "error", "message": "Akses POS ditolak."}), 403

    db = get_db()
    warehouse_id = _resolve_pos_warehouse(db, request.args.get("warehouse_id"))
    warehouse = db.execute(
        "SELECT name FROM warehouses WHERE id=? LIMIT 1",
        (warehouse_id,),
    ).fetchone()
    warehouse_name = warehouse["name"] if warehouse else f"WH {warehouse_id}"
    closing_date = _normalize_pos_cash_closing_date(request.args.get("closing_date"))
    defaults = _build_pos_cash_closing_defaults(
        db,
        warehouse_name,
        closing_date,
        warehouse_id=warehouse_id,
    )
    return jsonify({"status": "success", "defaults": defaults})


@pos_bp.post("/cash-closing/submit")
def pos_cash_closing_submit():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    warehouse_id = _resolve_pos_warehouse(db, request.form.get("warehouse_id"))
    warehouse = db.execute(
        "SELECT name FROM warehouses WHERE id=? LIMIT 1",
        (warehouse_id,),
    ).fetchone()
    warehouse_name = warehouse["name"] if warehouse else f"WH {warehouse_id}"
    editing_report_id = _to_int(request.form.get("cash_closing_report_id"), 0) or None
    cashier_actor = _fetch_pos_cash_closing_actor(db, warehouse_id, request.form.get("cashier_user_id"))
    closing_date = _normalize_pos_cash_closing_date(request.form.get("closing_date"))
    cash_amount = _parse_pos_cash_closing_amount(request.form.get("cash_amount"))
    debit_amount = _parse_pos_cash_closing_amount(request.form.get("debit_amount"))
    qris_amount = _parse_pos_cash_closing_amount(request.form.get("qris_amount"))
    mb_amount = _parse_pos_cash_closing_amount(request.form.get("mb_amount"))
    cv_amount = _parse_pos_cash_closing_amount(request.form.get("cv_amount"))
    expense_amount = _parse_pos_cash_closing_amount(request.form.get("expense_amount"))
    cash_on_hand_amount = _round_pos_cash_on_hand(max(cash_amount - expense_amount, 0))
    combined_total_amount = _parse_pos_cash_closing_amount(request.form.get("combined_total_amount"))
    note = (request.form.get("note") or "").strip()
    return_url = _sanitize_pos_cash_closing_return_url(request.form.get("return_url"))

    existing_report = None
    if editing_report_id:
        if str(session.get("role") or "").strip().lower() != "super_admin":
            flash("Hanya super admin yang bisa mengedit laporan tutup kasir yang sudah tersimpan.", "error")
            return redirect(f"{return_url}#tutup-kasir")
        existing_report = db.execute(
            """
            SELECT
                id,
                user_id,
                employee_id,
                warehouse_id,
                closing_date,
                wa_status,
                wa_error,
                wa_delivery_count,
                wa_success_count
            FROM cash_closing_reports
            WHERE id=?
            LIMIT 1
            """,
            (editing_report_id,),
        ).fetchone()
        if existing_report is None:
            flash("Laporan tutup kasir yang ingin diedit tidak ditemukan.", "error")
            return redirect(f"{return_url}#tutup-kasir")
        if _to_int(existing_report["warehouse_id"], 0) != warehouse_id:
            flash("Laporan tutup kasir hanya bisa diedit dari homebase yang sama.", "error")
            return redirect(f"{return_url}#tutup-kasir")

    if not any(
        (
            cash_amount,
            debit_amount,
            qris_amount,
            mb_amount,
            cv_amount,
            expense_amount,
            cash_on_hand_amount,
            combined_total_amount,
        )
    ):
        flash("Isi minimal satu nominal sebelum mengirim tutup kasir.", "error")
        return redirect(f"{return_url}#tutup-kasir")

    reported_total_amount = cash_amount + debit_amount + qris_amount + mb_amount + cv_amount
    summary_message = _build_pos_cash_closing_summary_message(
        warehouse_name,
        closing_date,
        cash_amount=cash_amount,
        debit_amount=debit_amount,
        qris_amount=qris_amount,
        mb_amount=mb_amount,
        cv_amount=cv_amount,
        expense_amount=expense_amount,
        cash_on_hand_amount=cash_on_hand_amount,
        combined_total_amount=combined_total_amount,
        note=note,
    )
    warehouse_label = format_receipt_homebase_label(warehouse_name)
    if warehouse_label == "-":
        warehouse_label = warehouse_name or "Gudang"
    submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = (
        f"Tutup Kasir {warehouse_label} "
        f"{_format_pos_cash_closing_date_label(closing_date)}"
    )

    if existing_report is not None:
        db.execute(
            """
            UPDATE cash_closing_reports
            SET closing_date=?,
                cash_amount=?,
                debit_amount=?,
                qris_amount=?,
                mb_amount=?,
                cv_amount=?,
                reported_total_amount=?,
                expense_amount=?,
                cash_on_hand_amount=?,
                combined_total_amount=?,
                note=?,
                summary_message=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                closing_date,
                cash_amount,
                debit_amount,
                qris_amount,
                mb_amount,
                cv_amount,
                reported_total_amount,
                expense_amount,
                cash_on_hand_amount,
                combined_total_amount,
                note,
                summary_message,
                existing_report["id"],
            ),
        )
        db.commit()
        flash(
            "Laporan tutup kasir berhasil diperbarui. WA yang sudah pernah terkirim tidak otomatis dikirim ulang.",
            "success",
        )
        return redirect(f"{return_url}#tutup-kasir")

    cursor = db.execute(
        """
        INSERT INTO cash_closing_reports(
            user_id,
            employee_id,
            warehouse_id,
            closing_date,
            cash_amount,
            debit_amount,
            qris_amount,
            mb_amount,
            cv_amount,
            reported_total_amount,
            expense_amount,
            cash_on_hand_amount,
            combined_total_amount,
            note,
            summary_message,
            wa_status,
            created_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cashier_actor.get("user_id"),
            cashier_actor.get("employee_id"),
            warehouse_id,
            closing_date,
            cash_amount,
            debit_amount,
            qris_amount,
            mb_amount,
            cv_amount,
            reported_total_amount,
            expense_amount,
            cash_on_hand_amount,
            combined_total_amount,
            note,
            summary_message,
            "pending",
            submitted_at,
            submitted_at,
        ),
    )
    report_id = cursor.lastrowid
    db.commit()

    wa_status = "pending"
    wa_error = ""
    delivery_count = 0
    success_count = 0

    try:
        wa_result = send_role_based_notification(
            "attendance.cash_closing",
            {
                "roles": ("leader",),
                "warehouse_id": warehouse_id,
                "employee_name": cashier_actor["display_name"],
                "warehouse_name": warehouse_name,
                "subject": subject,
                "message": summary_message,
                "link_url": f"{return_url}#tutup-kasir",
            },
        )
        deliveries = wa_result.get("deliveries") or []
        if wa_result.get("suppressed"):
            wa_status = "suppressed"
        delivery_count = len(deliveries)
        success_count = sum(1 for item in deliveries if item.get("ok"))
        error_messages = []
        for item in deliveries:
            error_text = str(item.get("error") or "").strip()
            if error_text and error_text not in error_messages:
                error_messages.append(error_text)
        wa_error = " | ".join(error_messages)
        if wa_status == "suppressed":
            wa_status = "suppressed"
        elif delivery_count <= 0:
            wa_status = "skipped"
        elif success_count >= delivery_count:
            wa_status = "sent"
        elif success_count > 0:
            wa_status = "partial"
        else:
            wa_status = "failed"
    except Exception as exc:
        wa_status = "failed"
        wa_error = str(exc).strip()

    db.execute(
        """
        UPDATE cash_closing_reports
        SET wa_status=?,
            wa_error=?,
            wa_delivery_count=?,
            wa_success_count=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            wa_status,
            wa_error,
            delivery_count,
            success_count,
            report_id,
        ),
    )
    db.commit()

    if wa_status == "sent":
        flash("Tutup kasir tersimpan dan WA leader berhasil dikirim.", "success")
    elif wa_status == "partial":
        flash("Tutup kasir tersimpan, tapi WA leader hanya terkirim sebagian.", "warning")
    elif wa_status == "failed":
        flash("Tutup kasir tersimpan, tapi kirim WA leader gagal. Cek nomor atau gateway WA.", "error")
    elif wa_status == "suppressed":
        flash("Tutup kasir tersimpan tanpa broadcast WA karena aksi dilakukan oleh super admin.", "success")
    else:
        flash("Tutup kasir tersimpan. Belum ada leader tujuan yang menerima WA untuk laporan ini.", "warning")
    return redirect(f"{return_url}#tutup-kasir")


@pos_bp.get("/receipt/<receipt_no>/print")
def pos_receipt_print(receipt_no):
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    sale = _fetch_pos_sale_detail_by_receipt(db, receipt_no)
    if sale is None:
        flash("Nota penjualan tidak ditemukan atau tidak bisa diakses.", "error")
        return redirect("/kasir/log")
    sale = _prepare_pos_receipt_sale(sale)
    requested_layout = str(request.args.get("layout") or "").strip().lower()
    receipt_layout = "thermal" if requested_layout == "thermal" else "a4"
    requested_copy = str(request.args.get("copy") or "").strip().lower()
    receipt_copy = "store" if receipt_layout == "thermal" and requested_copy == "store" else "customer"
    requested_followup_copy = str(request.args.get("followup_copy") or "").strip().lower()
    receipt_followup_copy = (
        requested_followup_copy
        if receipt_layout == "thermal"
        and requested_followup_copy in {"customer", "store"}
        and requested_followup_copy != receipt_copy
        else ""
    )
    requested_performance_mode = str(request.args.get("perf") or "").strip().lower()
    receipt_performance_mode = requested_performance_mode if requested_performance_mode in {"lite", "full"} else "auto"

    return render_template(
        "pos_receipt_print.html",
        **build_pos_receipt_render_context(
            sale,
            receipt_layout=receipt_layout,
            receipt_copy=receipt_copy,
            receipt_followup_copy=receipt_followup_copy,
            receipt_performance_mode=receipt_performance_mode,
            auto_print=request.args.get("autoprint") == "1",
            auto_close=request.args.get("autoclose") == "1",
            pdf_mode=False,
            embed_assets=False,
        ),
    )


@pos_bp.get("/receipt/<receipt_no>/pdf")
def pos_receipt_pdf(receipt_no):
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    try:
        sale, pdf_meta = _generate_backend_pos_receipt_pdf(db, receipt_no)
    except ValueError:
        flash("PDF nota penjualan tidak ditemukan atau tidak bisa diakses.", "error")
        return redirect("/kasir/log")
    except Exception as exc:
        print("POS RECEIPT VIEW PDF ERROR:", exc)
        flash("PDF nota gagal disiapkan. Coba lagi beberapa detik.", "error")
        return redirect("/kasir/log")

    response = send_file(
        pdf_meta["absolute_path"],
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"{sale['receipt_no']}.pdf",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@pos_bp.post("/sale/<int:sale_id>/resend-receipt")
def pos_resend_receipt_to_customer(sale_id):
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    if not has_permission(session.get("role"), "manage_pos"):
        return _json_error("Role ini belum punya izin kirim ulang nota POS.", 403)

    db = get_db()
    sale_detail = _fetch_pos_sale_detail_by_id(db, sale_id)
    if sale_detail is None:
        return _json_error("Transaksi POS tidak ditemukan atau tidak bisa diakses.", 404)

    pdf_regeneration_error = ""
    try:
        regenerated_sale, regenerated_pdf = _generate_backend_pos_receipt_pdf(db, sale_detail["receipt_no"])
        sale_detail = regenerated_sale
        sale_detail["receipt_pdf_public_url"] = regenerated_pdf.get("public_url") or ""
    except Exception as exc:
        print("POS RECEIPT RESEND PDF ERROR:", exc)
        pdf_regeneration_error = str(exc or "").strip()

    try:
        sale_detail = _prepare_pos_receipt_sale(sale_detail)
        delivery = _send_pos_receipt_to_customer(db, sale_detail)
    except Exception as exc:
        print("POS RECEIPT RESEND WA ERROR:", exc)
        return _json_error("Kirim ulang nota WA gagal diproses. Coba ulangi beberapa detik lagi.", 500)

    receipt_whatsapp_status = _resolve_pos_receipt_whatsapp_status(delivery)
    receipt_whatsapp_error = str((delivery or {}).get("error") or "").strip()

    return jsonify(
        {
            "status": "success",
            "message": _resolve_pos_receipt_whatsapp_feedback(receipt_whatsapp_status, receipt_whatsapp_error),
            "sale_id": sale_detail["id"],
            "receipt_no": sale_detail["receipt_no"],
            "customer_name": sale_detail.get("customer_name") or "Pelanggan",
            "customer_phone_label": sale_detail.get("customer_phone_label") or "Tanpa nomor",
            "receipt_pdf_public_url": sale_detail.get("receipt_pdf_public_url") or "",
            "receipt_whatsapp_status": receipt_whatsapp_status,
            "receipt_whatsapp_error": receipt_whatsapp_error,
            "receipt_pdf_regeneration_error": pdf_regeneration_error,
        }
    )


@pos_bp.post("/sales-item/<int:item_id>/void")
def pos_void_sale_item(item_id):
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    if not has_permission(session.get("role"), "manage_pos"):
        return _json_error("Role ini belum punya izin melakukan void item POS.", 403)

    db = get_db()
    payload = request.get_json(silent=True) or {}
    sale_item = _fetch_pos_voidable_sale_item(db, item_id)
    if sale_item is None:
        return _json_error("Item penjualan tidak ditemukan atau tidak bisa diakses.", 404)

    sold_qty = int(sale_item.get("qty") or 0)
    already_void_qty = max(0, int(sale_item.get("void_qty") or 0))
    active_qty = max(sold_qty - already_void_qty, 0)
    if active_qty <= 0:
        return _json_error("Item ini sudah di-void sepenuhnya.", 400)

    requested_void_qty = _to_int(payload.get("void_qty"), active_qty)
    if requested_void_qty <= 0:
        return _json_error("Qty void harus lebih dari 0.", 400)
    if requested_void_qty > active_qty:
        return _json_error(f"Qty void melebihi sisa item aktif. Maksimal {active_qty}.", 400)

    acting_user_id = _to_int(session.get("user_id"), 0)
    void_note = (payload.get("note") or "").strip() or None
    unit_price = _to_decimal(sale_item.get("unit_price"), "0")
    void_amount_delta = (unit_price * Decimal(requested_void_qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    restore_cost = _resolve_pos_stock_restore_cost(
        db,
        sale_item["product_id"],
        sale_item["variant_id"],
        sale_item["warehouse_id"],
    )

    try:
        db.execute("BEGIN")
        restored = _restore_pos_stock_after_reversal(
            db,
            sale_item["product_id"],
            sale_item["variant_id"],
            sale_item["warehouse_id"],
            requested_void_qty,
            note=f"VOID POS {sale_item['receipt_no']} - {sale_item['sku']} / {sale_item['variant_name']}",
            cost=restore_cost,
        )
        if not restored.get("ok"):
            raise ValueError(restored.get("error") or "Stok gagal dikembalikan saat proses void item.")

        db.execute(
            """
            UPDATE crm_purchase_items
            SET
                void_qty=COALESCE(void_qty, 0) + ?,
                void_amount=COALESCE(void_amount, 0) + ?,
                voided_at=CURRENT_TIMESTAMP,
                voided_by=?,
                void_note=?
            WHERE id=?
            """,
            (
                requested_void_qty,
                _currency(void_amount_delta),
                acting_user_id or None,
                void_note,
                item_id,
            ),
        )

        sale_totals = _apply_pos_sale_rollup_updates(db, sale_item, acting_user_id or None)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _json_error(str(exc), 400)
    except Exception:
        db.rollback()
        return _json_error("Void item gagal diproses. Coba ulangi beberapa detik lagi.", 500)

    try:
        notify_operational_event(
            f"Void POS {sale_item['receipt_no']}",
            (
                f"{sale_item['sku']} | Void {requested_void_qty} pcs | "
                f"Omzet sekarang {_format_pos_currency_label(sale_totals['total_amount'])}"
            ),
            warehouse_id=sale_item["warehouse_id"],
            category="inventory",
            link_url=f"/kasir/log?warehouse={sale_item['warehouse_id']}&date_from={sale_item['sale_date']}&date_to={sale_item['sale_date']}",
            source_type="pos_void",
            source_id=item_id,
            push_title="Void item POS diproses",
            push_body=f"{sale_item['receipt_no']} | {sale_item['sku']} | Qty {requested_void_qty}",
        )
    except Exception as exc:
        print("POS VOID NOTIFICATION ERROR:", exc)

    return jsonify(
        {
            "status": "success",
            "message": f"Item {sale_item['sku']} berhasil di-void sebanyak {requested_void_qty}.",
            "receipt_no": sale_item["receipt_no"],
            "sale_date": sale_item["sale_date"],
            "void_qty": requested_void_qty,
            "active_qty": max(active_qty - requested_void_qty, 0),
            "total_items": sale_totals["total_items"],
            "subtotal_amount": _currency(sale_totals["subtotal_amount"]),
            "discount_amount": _currency(sale_totals["discount_amount"]),
            "tax_amount": _currency(sale_totals["tax_amount"]),
            "total_amount": _currency(sale_totals["total_amount"]),
            "change_amount": _currency(sale_totals["change_amount"]),
            "status_label": sale_totals["status_label"],
            "sale_status": sale_totals["status"],
        }
    )


@pos_bp.post("/sale/<int:sale_id>/edit")
def pos_edit_sale(sale_id):
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    if not has_permission(session.get("role"), "manage_pos"):
        return _json_error("Role ini belum punya izin mengedit transaksi POS.", 403)

    payload = request.get_json(silent=True) or {}
    db = get_db()
    _ensure_pos_checkout_postgresql_sequences(db)
    ensure_crm_membership_multi_program_schema(db)
    sale = _fetch_pos_sale_detail_by_id(db, sale_id)
    if sale is None:
        return _json_error("Transaksi POS tidak ditemukan atau tidak bisa diakses.", 404)

    try:
        _build_pos_edit_sale_payload(db, sale)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    warehouse_id = _to_int(sale.get("warehouse_id"), 0)
    sale_date = str(sale.get("sale_date") or "").strip() or _get_pos_today().isoformat()
    payment_method = _normalize_payment_method(payload.get("payment_method"))
    discount_type = _normalize_adjustment_type(payload.get("discount_type"))
    discount_value = _to_decimal(payload.get("discount_value"), "0")
    tax_type = _normalize_adjustment_type(payload.get("tax_type"))
    tax_value = _to_decimal(payload.get("tax_value"), "0")
    note = (payload.get("note") or "").strip() or None
    transaction_type = normalize_transaction_type(payload.get("transaction_type"))
    customer_id = _to_int(payload.get("customer_id"), 0)
    customer_name = (payload.get("customer_name") or "").strip()
    customer_phone = _normalize_pos_phone(payload.get("customer_phone"))
    try:
        selected_cashier = _resolve_pos_cashier_option(db, warehouse_id, payload.get("cashier_user_id"))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    customer_name, customer_phone = _resolve_pos_customer_identity(
        db,
        warehouse_id,
        customer_id,
        customer_name,
        customer_phone,
    )

    if not customer_name:
        return _json_error("Nama customer wajib diisi.", 400)
    if not customer_phone:
        return _json_error("No HP customer wajib diisi dengan angka yang valid.", 400)

    stock_allowance_map = _build_pos_stock_allowance_map_from_items(sale.get("items") or [])
    try:
        allow_negative_stock = _is_pos_negative_stock_temp_enabled()
        items = _validate_and_build_items(
            db,
            warehouse_id,
            payload.get("items"),
            free_reward_mode=transaction_type == "stringing_reward_redemption",
            stock_allowance_map=stock_allowance_map,
            allow_negative_stock=allow_negative_stock,
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    financials = _build_pos_sale_financials(
        items,
        discount_type=discount_type,
        discount_value=discount_value,
        tax_type=tax_type,
        tax_value=tax_value,
    )

    payment_breakdown_entries = _normalize_pos_payment_breakdown(payload.get("payment_splits"))
    payment_breakdown_json = None
    if payment_method == SPLIT_PAYMENT_METHOD or payment_breakdown_entries:
        payment_method = SPLIT_PAYMENT_METHOD
        if len(payment_breakdown_entries) < 2:
            return _json_error("Split transaksi minimal harus memakai 2 metode pembayaran.", 400)

        split_total_amount = sum(
            (_to_decimal(entry.get("amount"), "0") for entry in payment_breakdown_entries),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if split_total_amount != financials["total_amount"]:
            return _json_error("Total split pembayaran harus pas sama total transaksi.", 400)

        paid_amount = split_total_amount
        change_amount = Decimal("0.00")
        payment_breakdown_json = _serialize_pos_payment_breakdown(payment_breakdown_entries)
    else:
        paid_amount = _to_decimal(payload.get("paid_amount"), str(financials["total_amount"]))
        if paid_amount < financials["total_amount"]:
            return _json_error("Nominal bayar kurang dari total transaksi.", 400)

        change_amount = (paid_amount - financials["total_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    original_active_items = [
        {
            "product_id": _to_int(item.get("product_id"), 0),
            "variant_id": _to_int(item.get("variant_id"), 0),
            "sku": item.get("sku") or "-",
            "variant_name": item.get("variant_name") or "default",
            "qty": max(_to_int(item.get("active_qty"), 0), 0),
        }
        for item in (sale.get("items") or [])
        if max(_to_int(item.get("active_qty"), 0), 0) > 0
    ]

    member_id = None
    loyalty_members = {}
    resolved_transaction_type = transaction_type

    try:
        db.execute("BEGIN")
        customer = _resolve_or_create_customer(
            db,
            warehouse_id,
            customer_id,
            customer_name,
            customer_phone,
        )

        db.execute(
            "DELETE FROM crm_member_records WHERE purchase_id=?",
            (sale["purchase_id"],),
        )

        loyalty_members = _resolve_pos_loyalty_members_for_sale(
            db,
            customer,
            warehouse_id,
            sale_date,
            transaction_type,
            items,
            requested_by_user_id=session.get("user_id"),
        )
        resolved_transaction_type = _derive_pos_loyalty_sale_transaction_type(transaction_type, items)
        primary_member = _choose_primary_pos_loyalty_member(loyalty_members, resolved_transaction_type)
        if primary_member:
            member_id = primary_member["id"]

        for original_item in original_active_items:
            restore_cost = _resolve_pos_stock_restore_cost(
                db,
                original_item["product_id"],
                original_item["variant_id"],
                warehouse_id,
            )
            restored = _restore_pos_stock_after_reversal(
                db,
                original_item["product_id"],
                original_item["variant_id"],
                warehouse_id,
                original_item["qty"],
                note=(
                    f"EDIT POS {sale['receipt_no']} rollback - "
                    f"{original_item['sku']} / {original_item['variant_name']}"
                ),
                cost=restore_cost,
            )
            if not restored.get("ok"):
                raise ValueError(restored.get("error") or "Stok transaksi lama gagal dikembalikan saat proses edit.")

        db.execute(
            "DELETE FROM crm_purchase_items WHERE purchase_id=?",
            (sale["purchase_id"],),
        )
        db.executemany(
            """
            INSERT INTO crm_purchase_items(
                purchase_id,
                product_id,
                variant_id,
                qty,
                retail_price,
                unit_price,
                line_total,
                note
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    sale["purchase_id"],
                    item["product_id"],
                    item["variant_id"],
                    item["qty"],
                    _currency(item.get("retail_price") or 0),
                    _currency(item["unit_price"]),
                    _currency(item["line_total"]),
                    "POS Edit Transaksi",
                )
                for item in items
            ],
        )

        for item in items:
            removed = _remove_pos_stock_for_sale(
                db,
                item["product_id"],
                item["variant_id"],
                warehouse_id,
                item["qty"],
                note=f"EDIT POS {sale['receipt_no']}",
            )
            if not removed.get("ok"):
                raise ValueError(
                    removed.get("error")
                    or f"Gagal memotong stok {item['sku']} / {item['variant_name']} saat edit transaksi."
                )

        db.execute(
            """
            UPDATE crm_purchase_records
            SET
                customer_id=?,
                member_id=?,
                warehouse_id=?,
                purchase_date=?,
                invoice_no=?,
                channel='pos',
                transaction_type=?,
                items_count=?,
                total_amount=?,
                note=?,
                handled_by=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                customer["id"],
                member_id,
                warehouse_id,
                sale_date,
                sale["receipt_no"],
                resolved_transaction_type,
                financials["total_items"],
                _currency(financials["total_amount"]),
                note,
                session.get("user_id"),
                sale["purchase_id"],
            ),
        )

        auto_records = _build_pos_loyalty_member_records(
            sale["purchase_id"],
            warehouse_id,
            sale_date,
            sale["receipt_no"],
            note,
            session.get("user_id"),
            items,
            loyalty_members,
            source_label="POS / iPos Edit",
            transaction_type=transaction_type,
        )
        for auto_record in auto_records:
            db.execute(
                """
                INSERT INTO crm_member_records(
                    member_id,
                    purchase_id,
                    warehouse_id,
                    record_date,
                    record_type,
                    reference_no,
                    amount,
                    points_delta,
                    service_count_delta,
                    reward_redeemed_delta,
                    benefit_value,
                    note,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    auto_record["member_id"],
                    auto_record["purchase_id"],
                    auto_record["warehouse_id"],
                    auto_record["record_date"],
                    auto_record["record_type"],
                    auto_record["reference_no"],
                    auto_record["amount"],
                    auto_record["points_delta"],
                    auto_record["service_count_delta"],
                    auto_record["reward_redeemed_delta"],
                    auto_record["benefit_value"],
                    auto_record["note"],
                    auto_record["handled_by"],
                ),
            )

        db.execute(
            """
            UPDATE pos_sales
            SET
                customer_id=?,
                warehouse_id=?,
                cashier_user_id=?,
                sale_date=?,
                receipt_no=?,
                payment_method=?,
                payment_breakdown_json=?,
                total_items=?,
                subtotal_amount=?,
                discount_type=?,
                discount_value=?,
                discount_amount=?,
                tax_type=?,
                tax_value=?,
                tax_amount=?,
                total_amount=?,
                paid_amount=?,
                change_amount=?,
                status='posted',
                voided_at=NULL,
                voided_by=NULL,
                receipt_pdf_path=NULL,
                receipt_pdf_url=NULL,
                receipt_whatsapp_status='pending',
                receipt_whatsapp_error=NULL,
                receipt_whatsapp_sent_at=NULL,
                note=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                customer["id"],
                warehouse_id,
                selected_cashier["id"],
                sale_date,
                sale["receipt_no"],
                payment_method,
                payment_breakdown_json,
                financials["total_items"],
                _currency(financials["subtotal_amount"]),
                financials["discount_type"],
                _currency(financials["discount_value"]),
                _currency(financials["discount_amount"]),
                financials["tax_type"],
                _currency(financials["tax_value"]),
                _currency(financials["tax_amount"]),
                _currency(financials["total_amount"]),
                _currency(paid_amount),
                _currency(change_amount),
                note,
                sale["id"],
            ),
        )

        db.commit()
    except ValueError as exc:
        db.rollback()
        return _json_error(str(exc), 400)
    except Exception:
        db.rollback()
        return _json_error("Edit transaksi kasir gagal disimpan. Coba ulangi beberapa detik lagi.", 500)

    return jsonify(
        {
            "status": "success",
            "message": "Transaksi berhasil diperbarui tanpa mengubah nomor nota dan waktu transaksi awal.",
            "sale_id": sale["id"],
            "receipt_no": sale["receipt_no"],
            "purchase_id": sale["purchase_id"],
            "sale_date": sale_date,
            "created_time_label": sale.get("created_time_label") or "-",
            "total_items": financials["total_items"],
            "subtotal_amount": _currency(financials["subtotal_amount"]),
            "discount_amount": _currency(financials["discount_amount"]),
            "tax_amount": _currency(financials["tax_amount"]),
            "total_amount": _currency(financials["total_amount"]),
            "paid_amount": _currency(paid_amount),
            "change_amount": _currency(change_amount),
            "payment_method": payment_method,
            "payment_method_label": _format_payment_method_label(payment_method),
            "payment_breakdown_label": _build_pos_payment_breakdown_label(payment_breakdown_entries),
            "receipt_print_url": (
                f"/kasir/receipt/{sale['receipt_no']}/print"
                f"?layout=thermal&copy=customer&autoprint=1&autoclose=1"
            ),
            "receipt_whatsapp_status": "pending",
            "receipt_whatsapp_error": "",
        }
    )


@pos_bp.post("/checkout")
def pos_checkout():
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    if not has_permission(session.get("role"), "manage_pos"):
        return _json_error("Role ini belum punya izin melakukan checkout kasir.", 403)

    payload = request.get_json(silent=True) or {}
    db = get_db()
    _ensure_pos_checkout_postgresql_sequences(db)
    _ensure_pos_checkout_trace_schema(db)
    ensure_crm_membership_multi_program_schema(db)

    warehouse_id = _resolve_pos_warehouse(db, payload.get("warehouse_id"))
    requested_sale_date = _normalize_sale_date(payload.get("sale_date"))
    sale_date = _resolve_active_pos_sale_date(requested_sale_date)
    sale_date_adjusted = requested_sale_date != sale_date
    if sale_date_adjusted:
        current_app.logger.warning(
            "POS checkout sale_date adjusted from %s to %s for warehouse_id=%s cashier_user_id=%s",
            requested_sale_date,
            sale_date,
            warehouse_id,
            payload.get("cashier_user_id"),
        )
    payment_method = _normalize_payment_method(payload.get("payment_method"))
    discount_type = _normalize_adjustment_type(payload.get("discount_type"))
    discount_value = _to_decimal(payload.get("discount_value"), "0")
    tax_type = _normalize_adjustment_type(payload.get("tax_type"))
    tax_value = _to_decimal(payload.get("tax_value"), "0")
    note = (payload.get("note") or "").strip() or None
    transaction_type = normalize_transaction_type(payload.get("transaction_type"))
    customer_id = _to_int(payload.get("customer_id"), 0)
    customer_name = (payload.get("customer_name") or "").strip()
    customer_phone = _normalize_pos_phone(payload.get("customer_phone"))
    try:
        selected_cashier = _resolve_pos_cashier_option(db, warehouse_id, payload.get("cashier_user_id"))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    customer_name, customer_phone = _resolve_pos_customer_identity(
        db,
        warehouse_id,
        customer_id,
        customer_name,
        customer_phone,
    )

    if not customer_name:
        return _json_error("Nama customer wajib diisi.", 400)
    if not customer_phone:
        return _json_error("No HP customer wajib diisi dengan angka yang valid.", 400)

    try:
        allow_negative_stock = _is_pos_negative_stock_temp_enabled()
        items = _validate_and_build_items(
            db,
            warehouse_id,
            payload.get("items"),
            free_reward_mode=transaction_type == "stringing_reward_redemption",
            allow_negative_stock=allow_negative_stock,
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    financials = _build_pos_sale_financials(
        items,
        discount_type=discount_type,
        discount_value=discount_value,
        tax_type=tax_type,
        tax_value=tax_value,
    )

    payment_breakdown_entries = _normalize_pos_payment_breakdown(payload.get("payment_splits"))
    payment_breakdown_json = None
    if payment_method == SPLIT_PAYMENT_METHOD or payment_breakdown_entries:
        payment_method = SPLIT_PAYMENT_METHOD
        if len(payment_breakdown_entries) < 2:
            return _json_error("Split transaksi minimal harus memakai 2 metode pembayaran.", 400)

        split_total_amount = sum(
            (_to_decimal(entry.get("amount"), "0") for entry in payment_breakdown_entries),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if split_total_amount != financials["total_amount"]:
            return _json_error("Total split pembayaran harus pas sama total transaksi.", 400)

        paid_amount = split_total_amount
        change_amount = Decimal("0.00")
        payment_breakdown_json = _serialize_pos_payment_breakdown(payment_breakdown_entries)
    else:
        paid_amount = _to_decimal(payload.get("paid_amount"), str(financials["total_amount"]))
        if paid_amount < financials["total_amount"]:
            return _json_error("Nominal bayar kurang dari total transaksi.", 400)

        change_amount = (paid_amount - financials["total_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    member_id = None
    loyalty_members = {}
    resolved_transaction_type = transaction_type
    receipt_no = (payload.get("receipt_no") or "").strip()
    client_checkout_token = str(payload.get("client_checkout_token") or "").strip()
    negative_stock_alert_items = []
    max_retries = max(
        0,
        int(current_app.config.get("POS_DB_LOCK_RETRY_ATTEMPTS", POS_DB_LOCK_RETRY_ATTEMPTS) or 0),
    )
    retry_delay = max(
        0.0,
        float(
            current_app.config.get(
                "POS_DB_LOCK_RETRY_DELAY_SECONDS",
                POS_DB_LOCK_RETRY_DELAY_SECONDS,
            )
            or 0.0
        ),
    )

    if client_checkout_token:
        existing_trace = _fetch_pos_checkout_trace(db, client_checkout_token)
        existing_sale_id = _to_int(existing_trace["sale_id"], 0) if existing_trace else 0
        if existing_sale_id > 0:
            existing_sale = _fetch_pos_sale_detail_by_id(db, existing_sale_id, allow_hidden_archive=True)
            if existing_sale is not None:
                return jsonify(
                    _build_pos_checkout_success_payload_from_sale_detail(
                        existing_sale,
                        message="Checkout kasir sebelumnya sudah tersimpan.",
                    )
                )

    for attempt in range(max_retries + 1):
        try:
            negative_stock_alert_items = []
            db.execute("BEGIN IMMEDIATE")
            customer = _resolve_or_create_customer(
                db,
                warehouse_id,
                customer_id,
                customer_name,
                customer_phone,
            )

            loyalty_members = _resolve_pos_loyalty_members_for_sale(
                db,
                customer,
                warehouse_id,
                sale_date,
                transaction_type,
                items,
                requested_by_user_id=session.get("user_id"),
            )
            resolved_transaction_type = _derive_pos_loyalty_sale_transaction_type(transaction_type, items)
            primary_member = _choose_primary_pos_loyalty_member(loyalty_members, resolved_transaction_type)
            if primary_member:
                member_id = primary_member["id"]

            if not receipt_no:
                receipt_no = _build_next_receipt_no(db, sale_date)

            duplicate_receipt = db.execute(
                "SELECT id FROM pos_sales WHERE receipt_no=? LIMIT 1",
                (receipt_no,),
            ).fetchone()
            if duplicate_receipt:
                receipt_no = _build_next_receipt_no(db, sale_date)

            purchase_cursor = db.execute(
                """
                INSERT INTO crm_purchase_records(
                    customer_id,
                    member_id,
                    warehouse_id,
                    purchase_date,
                    invoice_no,
                    channel,
                    transaction_type,
                    items_count,
                    total_amount,
                    note,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    customer["id"],
                    member_id,
                    warehouse_id,
                    sale_date,
                    receipt_no,
                    "pos",
                    resolved_transaction_type,
                    financials["total_items"],
                    _currency(financials["total_amount"]),
                    note,
                    session.get("user_id"),
                ),
            )
            purchase_id = purchase_cursor.lastrowid

            db.executemany(
                """
                INSERT INTO crm_purchase_items(
                    purchase_id,
                    product_id,
                    variant_id,
                    qty,
                    retail_price,
                    unit_price,
                    line_total,
                    note
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        purchase_id,
                        item["product_id"],
                        item["variant_id"],
                        item["qty"],
                        _currency(item.get("retail_price") or 0),
                        _currency(item["unit_price"]),
                        _currency(item["line_total"]),
                        "POS Checkout",
                    )
                    for item in items
                ],
            )

            auto_records = _build_pos_loyalty_member_records(
                purchase_id,
                warehouse_id,
                sale_date,
                receipt_no,
                note,
                session.get("user_id"),
                items,
                loyalty_members,
                source_label="POS / iPos",
                transaction_type=transaction_type,
            )
            for auto_record in auto_records:
                db.execute(
                    """
                    INSERT INTO crm_member_records(
                        member_id,
                        purchase_id,
                        warehouse_id,
                        record_date,
                        record_type,
                        reference_no,
                        amount,
                        points_delta,
                        service_count_delta,
                        reward_redeemed_delta,
                        benefit_value,
                        note,
                        handled_by
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        auto_record["member_id"],
                        auto_record["purchase_id"],
                        auto_record["warehouse_id"],
                        auto_record["record_date"],
                        auto_record["record_type"],
                        auto_record["reference_no"],
                        auto_record["amount"],
                        auto_record["points_delta"],
                        auto_record["service_count_delta"],
                        auto_record["reward_redeemed_delta"],
                        auto_record["benefit_value"],
                        auto_record["note"],
                        auto_record["handled_by"],
                    ),
                )

            pos_cursor = db.execute(
                """
                INSERT INTO pos_sales(
                    purchase_id,
                    customer_id,
                    warehouse_id,
                    cashier_user_id,
                    sale_date,
                    receipt_no,
                    payment_method,
                    payment_breakdown_json,
                    total_items,
                    subtotal_amount,
                    discount_type,
                    discount_value,
                    discount_amount,
                    tax_type,
                    tax_value,
                    tax_amount,
                    total_amount,
                    paid_amount,
                    change_amount,
                    status,
                    note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    purchase_id,
                    customer["id"],
                    warehouse_id,
                    selected_cashier["id"],
                    sale_date,
                    receipt_no,
                    payment_method,
                    payment_breakdown_json,
                    financials["total_items"],
                    _currency(financials["subtotal_amount"]),
                    financials["discount_type"],
                    _currency(financials["discount_value"]),
                    _currency(financials["discount_amount"]),
                    financials["tax_type"],
                    _currency(financials["tax_value"]),
                    _currency(financials["tax_amount"]),
                    _currency(financials["total_amount"]),
                    _currency(paid_amount),
                    _currency(change_amount),
                    "posted",
                    note,
                ),
            )
            sale_id = pos_cursor.lastrowid
            stock_snapshot_map = _fetch_pos_stock_balance_map(
                db,
                warehouse_id,
                [(item["product_id"], item["variant_id"]) for item in items],
            )

            for item in items:
                item_key = (item["product_id"], item["variant_id"])
                removed = _remove_pos_stock_for_sale(
                    db,
                    item["product_id"],
                    item["variant_id"],
                    warehouse_id,
                    item["qty"],
                    note=f"POS {receipt_no}",
                    stock_snapshot=stock_snapshot_map.get(item_key),
                )
                if not removed.get("ok"):
                    raise ValueError(
                        removed.get("error")
                        or f"Gagal memotong stok {item['sku']} / {item['variant_name']}. Silakan refresh data stok."
                    )
                if removed.get("after_snapshot"):
                    stock_snapshot_map[item_key] = removed["after_snapshot"]
                if removed.get("used_negative_stock"):
                    negative_stock_alert_items.append(
                        {
                            "sku": item["sku"],
                            "variant_name": item["variant_name"],
                            "before_qty": removed.get("before_qty"),
                            "after_qty": removed.get("after_qty"),
                        }
                    )

            if client_checkout_token:
                _record_pos_checkout_trace(
                    db,
                    client_token=client_checkout_token,
                    sale_id=sale_id,
                    purchase_id=purchase_id,
                    receipt_no=receipt_no,
                    warehouse_id=warehouse_id,
                    cashier_user_id=selected_cashier["id"],
                    sale_date=sale_date,
                    customer_name=customer["customer_name"],
                    customer_phone=(customer["phone"] if "phone" in customer.keys() else "") or customer_phone,
                    total_amount=financials["total_amount"],
                    status="success",
                )

            db.commit()
            break
        except ValueError as exc:
            db.rollback()
            return _json_error(str(exc), 400)
        except sqlite3.OperationalError as exc:
            db.rollback()
            if _is_sqlite_lock_error(exc) and attempt < max_retries:
                current_app.logger.warning(
                    "POS checkout hit SQLite lock, retry %s/%s",
                    attempt + 1,
                    max_retries,
                )
                time.sleep(retry_delay)
                continue
            if _is_sqlite_lock_error(exc):
                current_app.logger.warning("POS checkout failed after SQLite lock retries")
                return _json_error(
                    "Checkout kasir gagal disimpan karena database sedang sibuk di server. Coba ulangi beberapa detik lagi.",
                    503,
                )
            current_app.logger.exception("POS checkout database error")
            return _json_error("Checkout kasir gagal disimpan. Coba ulangi beberapa detik lagi.", 500)
        except Exception:
            db.rollback()
            current_app.logger.exception("POS checkout failed unexpectedly")
            return _json_error("Checkout kasir gagal disimpan. Coba ulangi beberapa detik lagi.", 500)

    sale_detail = None
    receipt_pdf_meta = None
    receipt_delivery = None

    try:
        sale_detail, receipt_pdf_meta = _generate_backend_pos_receipt_pdf(db, receipt_no)
    except Exception as exc:
        print("POS RECEIPT PDF ERROR:", exc)

    try:
        if sale_detail is not None:
            receipt_delivery = _send_pos_receipt_to_customer(db, sale_detail)
    except Exception as exc:
        print("POS RECEIPT WHATSAPP ERROR:", exc)

    try:
        notify_operational_event(
            f"Transaksi POS {receipt_no}",
            (
                f"{customer['customer_name']} | {financials['total_items']} item | "
                f"Total Rp {int(_currency(financials['total_amount'])):,}".replace(",", ".")
            ),
            warehouse_id=warehouse_id,
            category="inventory",
            link_url="/kasir/",
            source_type="pos_sale",
            source_id=sale_id,
            push_title="Checkout POS berhasil",
            push_body=f"{receipt_no} | {financials['total_items']} item",
        )
    except Exception as exc:
        print("POS NOTIFICATION ERROR:", exc)

    if negative_stock_alert_items and normalize_role(selected_cashier.get("role")) == "staff":
        try:
            cashier_name = (
                selected_cashier.get("display_name")
                or selected_cashier.get("label")
                or selected_cashier.get("username")
                or "Staff POS"
            )
            notify_operational_event(
                f"Alert stok minus iPOS {receipt_no}",
                _build_pos_negative_stock_notification_message(receipt_no, cashier_name, negative_stock_alert_items),
                warehouse_id=warehouse_id,
                include_actor=False,
                recipient_roles=("owner",),
                category="inventory",
                link_url=f"/kasir/log?warehouse={warehouse_id}&date_from={sale_date}&date_to={sale_date}",
                source_type="pos_negative_stock",
                source_id=sale_id,
                push_title="Alert stok minus iPOS",
                push_body=(
                    f"{cashier_name} | {negative_stock_alert_items[0]['sku']} | "
                    f"stok {negative_stock_alert_items[0]['after_qty']}"
                ),
            )
        except Exception as exc:
            print("POS NEGATIVE STOCK NOTIFICATION ERROR:", exc)

    success_message = "Checkout kasir berhasil disimpan."
    if sale_date_adjusted:
        success_message += " Tanggal transaksi otomatis disesuaikan ke hari ini karena halaman kasir masih membawa tanggal lama."

    return jsonify(
        {
            "status": "success",
            "message": success_message,
            "sale_id": sale_id,
            "receipt_no": receipt_no,
            "purchase_id": purchase_id,
            "sale_date": sale_date,
            "sale_date_adjusted": sale_date_adjusted,
            "customer_name": customer["customer_name"],
            "total_items": financials["total_items"],
            "subtotal_amount": _currency(financials["subtotal_amount"]),
            "discount_amount": _currency(financials["discount_amount"]),
            "tax_amount": _currency(financials["tax_amount"]),
            "total_amount": _currency(financials["total_amount"]),
            "paid_amount": _currency(paid_amount),
            "change_amount": _currency(change_amount),
            "payment_method": payment_method,
            "payment_method_label": _format_payment_method_label(payment_method),
            "payment_breakdown_label": _build_pos_payment_breakdown_label(payment_breakdown_entries),
            "receipt_print_url": (
                f"/kasir/receipt/{receipt_no}/print"
                f"?layout=thermal&copy=customer&autoprint=1&autoclose=1"
            ),
            "receipt_pdf_public_url": (receipt_pdf_meta or {}).get("public_url") or "",
            "receipt_whatsapp_status": _resolve_pos_receipt_whatsapp_status(receipt_delivery),
            "receipt_whatsapp_error": str((receipt_delivery or {}).get("error") or "").strip(),
        }
    )


@pos_bp.get("/checkout-trace/<client_token>")
def pos_checkout_trace(client_token):
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    db = get_db()
    _ensure_pos_checkout_trace_schema(db)
    trace_row = _fetch_pos_checkout_trace(db, client_token)
    if trace_row is None:
        return jsonify({"status": "not_found", "found": False, "message": "Belum ada checkout tersimpan untuk token ini."})

    sale_id = _to_int(trace_row["sale_id"], 0)
    if sale_id <= 0:
        return jsonify({"status": "pending", "found": False, "message": "Checkout masih diproses server."})

    sale_detail = _fetch_pos_sale_detail_by_id(db, sale_id, allow_hidden_archive=True)
    if sale_detail is None:
        return jsonify(
            {
                "status": "not_found",
                "found": False,
                "message": "Trace checkout ada, tapi transaksi POS belum bisa dibuka.",
                "sale_id": sale_id,
                "receipt_no": trace_row["receipt_no"],
            }
        )

    payload = _build_pos_checkout_success_payload_from_sale_detail(
        sale_detail,
        message="Checkout kasir sebelumnya sudah ditemukan lagi.",
    )
    payload["found"] = True
    payload["client_checkout_token"] = str(client_token or "").strip()
    return jsonify(payload)
