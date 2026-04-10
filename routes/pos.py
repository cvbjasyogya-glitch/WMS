from datetime import date as date_cls, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, session

from database import get_db
from services.crm_loyalty import (
    CRM_TRANSACTION_TYPE_LABELS,
    DEFAULT_STRINGING_REWARD_AMOUNT,
    STRINGING_REWARD_THRESHOLD,
    build_auto_member_record,
    calculate_loyalty_fields,
    get_member_snapshot,
    normalize_transaction_type,
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
from services.stock_service import add_stock, remove_stock
from services.whatsapp_service import (
    record_whatsapp_delivery,
    send_role_based_notification,
    send_whatsapp_document,
    send_whatsapp_text,
)


pos_bp = Blueprint("pos", __name__, url_prefix="/kasir")

PAYMENT_METHODS = ("cash", "qris", "transfer", "debit", "credit")
POS_ASSIGNABLE_ROLE_LIST = ("owner", "super_admin", "leader", "admin", "staff")
INACTIVE_EMPLOYMENT_STATUSES = ("inactive", "terminated", "resigned", "former", "nonactive", "non-active")
POS_REVENUE_HIDDEN_LABEL = "-"

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


def _normalize_pos_phone(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = f"62{digits[1:]}"
    elif not digits.startswith("62") and len(digits) >= 8:
        digits = f"62{digits.lstrip('0')}"
    return digits


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

    if not receipt_url:
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
        receipt_print_url = build_public_file_url(f"/kasir/receipt/{receipt_no}/print")
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
    member_id = _to_int(safe_sale.get("member_id"), 0)
    purchase_id = _to_int(safe_sale.get("purchase_id"), 0)
    if member_id <= 0 or purchase_id <= 0:
        return []

    snapshot = get_member_snapshot(db, member_id)
    if not snapshot:
        return []

    loyalty_record = _fetch_pos_loyalty_record(db, purchase_id, member_id) or {}
    member_type = str(safe_sale.get("member_type") or snapshot.get("member_type") or "").strip().lower()
    member_code = str(safe_sale.get("member_code") or snapshot.get("member_code") or "").strip()
    transaction_type = normalize_transaction_type(safe_sale.get("transaction_type"))
    lines = []
    if member_code:
        lines.append(f"- Member: {member_code}")

    if member_type == "purchase":
        earned_points = max(_to_int(loyalty_record.get("points_delta"), 0), 0)
        current_points = max(_to_int(snapshot.get("current_points"), 0), 0)
        lines.append(f"- Poin transaksi ini: +{earned_points} poin")
        lines.append(f"- Total poin aktif: {current_points} poin")
        return lines

    progress_label = _build_pos_stringing_progress_label(snapshot, transaction_type, loyalty_record)
    available_reward_count = max(_to_int(snapshot.get("available_reward_count"), 0), 0)
    reward_value_label = _format_pos_currency_label(snapshot.get("reward_unit_amount") or DEFAULT_STRINGING_REWARD_AMOUNT)

    if transaction_type == "stringing_reward_redemption":
        benefit_value = _currency(loyalty_record.get("benefit_value") or snapshot.get("reward_unit_amount") or DEFAULT_STRINGING_REWARD_AMOUNT)
        lines.append(f"- Free senar terpakai: 1x ({_format_pos_currency_label(benefit_value)})")
        lines.append(f"- Progress senar berikutnya: {progress_label}")
        if available_reward_count > 0:
            lines.append(f"- Free senar tersisa: {available_reward_count}x")
        return lines

    lines.append(f"- Progress senar: {progress_label}")
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


def _normalize_sale_date(raw_value):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return date_cls.today().isoformat()
    try:
        return date_cls.fromisoformat(raw_value).isoformat()
    except ValueError:
        return date_cls.today().isoformat()


def _normalize_payment_method(raw_value):
    method = (raw_value or "").strip().lower()
    return method if method in PAYMENT_METHODS else "cash"


def _format_payment_method_label(raw_value):
    method = _normalize_payment_method(raw_value)
    if method == "transfer":
        return "TF"
    return method.upper()


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
        today = date_cls.today()
        return f"{today.year:04d}-{today.month:02d}"

    try:
        normalized = date_cls.fromisoformat(f"{safe_value}-01")
        return f"{normalized.year:04d}-{normalized.month:02d}"
    except ValueError:
        today = date_cls.today()
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
    return normalize_role(session.get("role")) in {"owner", "super_admin"}


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


def _fetch_pos_customers(db, warehouse_id):
    return [
        dict(row)
        for row in db.execute(
            """
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
                ON m.customer_id = c.id
               AND m.status='active'
            WHERE c.warehouse_id=?
            ORDER BY c.customer_name ASC
            LIMIT 300
            """,
            (warehouse_id,),
        ).fetchall()
    ]


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
        WHERE warehouse_id=? AND sale_date=? AND COALESCE(status, 'posted') <> 'voided'
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    total_revenue = db.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND COALESCE(status, 'posted') <> 'voided'
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    total_items = db.execute(
        """
        SELECT COALESCE(SUM(total_items), 0) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND COALESCE(status, 'posted') <> 'voided'
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    cashier_total = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND cashier_user_id=? AND COALESCE(status, 'posted') <> 'voided'
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
        """
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
            u.username AS cashier_name
        FROM pos_sales ps
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        WHERE ps.warehouse_id=? AND ps.sale_date=?
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


def _format_pos_time_label(raw_value):
    safe_value = str(raw_value or "").strip()
    if len(safe_value) >= 16:
        return safe_value[11:16]
    return "-"


def _normalize_pos_cash_closing_date(value):
    safe_value = str(value or "").strip()
    if not safe_value:
        return date_cls.today().isoformat()
    try:
        return date_cls.fromisoformat(safe_value).isoformat()
    except ValueError:
        return date_cls.today().isoformat()


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
        int(cash_amount or 0) + int(debit_amount or 0) + int(mb_amount or 0) + int(cv_amount or 0),
        0,
    )
    message_lines = [
        f'Laporan "{warehouse_label}" {_format_pos_cash_closing_date_label(closing_date)}',
        "",
        _build_pos_cash_closing_summary_line("Tunai", cash_amount),
        _build_pos_cash_closing_summary_line("Debet", debit_amount),
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
        closing_date or date_cls.today().isoformat(),
        cash_amount=0,
        debit_amount=0,
        mb_amount=0,
        cv_amount=0,
        expense_amount=0,
        cash_on_hand_amount=0,
        combined_total_amount=0,
        note="",
    )


def _resolve_pos_cash_closing_bucket_key(payment_method):
    normalized_method = _normalize_payment_method(payment_method)
    if normalized_method == "cash":
        return "cash_amount"
    if normalized_method == "debit":
        return "debit_amount"
    if normalized_method == "transfer":
        return "mb_amount"
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


def _fetch_pos_cash_closing_method_totals(db, closing_date, *, warehouse_id=None, cashier_user_id=None):
    safe_date = _normalize_pos_cash_closing_date(closing_date)
    params = [safe_date]
    where_clauses = ["ps.sale_date=?"]
    if _to_int(warehouse_id, 0) > 0:
        where_clauses.append("ps.warehouse_id=?")
        params.append(int(warehouse_id))
    if _to_int(cashier_user_id, 0) > 0:
        where_clauses.append("ps.cashier_user_id=?")
        params.append(int(cashier_user_id))

    rows = db.execute(
        f"""
        SELECT
            LOWER(COALESCE(ps.payment_method, 'cash')) AS payment_method,
            COALESCE(SUM(ps.total_amount), 0) AS total_amount
        FROM pos_sales ps
        WHERE {" AND ".join(where_clauses)}
        GROUP BY LOWER(COALESCE(ps.payment_method, 'cash'))
        """,
        params,
    ).fetchall()

    totals = {
        "cash_amount": 0,
        "debit_amount": 0,
        "mb_amount": 0,
        "cv_amount": 0,
    }
    for row in rows:
        bucket_key = _resolve_pos_cash_closing_bucket_key(row["payment_method"])
        totals[bucket_key] += max(int(round(float(row["total_amount"] or 0))), 0)
    totals["reported_total_amount"] = (
        totals["cash_amount"]
        + totals["debit_amount"]
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
        """,
        [safe_date, *warehouse_ids],
    ).fetchone()
    return max(int(round(float((row["total_amount"] if row else 0) or 0))), 0)


def _build_pos_cash_closing_defaults(db, warehouse_name, closing_date, *, warehouse_id=None, cashier_user_id=None):
    safe_date = _normalize_pos_cash_closing_date(closing_date)
    method_totals = _fetch_pos_cash_closing_method_totals(
        db,
        safe_date,
        warehouse_id=warehouse_id,
        cashier_user_id=cashier_user_id,
    )
    combined_total_amount = _fetch_pos_cash_closing_combined_total(db, safe_date)
    expense_amount = 0
    cash_on_hand_amount = max(method_totals["cash_amount"] - expense_amount, 0)
    defaults = {
        "closing_date": safe_date,
        "cash_amount": method_totals["cash_amount"],
        "debit_amount": method_totals["debit_amount"],
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


def _fetch_pos_cash_closing_reports(db, warehouse_id=None, cashier_user_id=None, limit=8):
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
        line_total = _currency(row["line_total"] or 0)
        item_map.setdefault(purchase_id, []).append(
            {
                "sku": row["sku"],
                "product_name": row["product_name"],
                "variant_name": row["variant_name"],
                "qty": int(row["qty"] or 0),
                "unit_price": unit_price,
                "line_total": line_total,
                "unit_price_label": _format_pos_currency_label(unit_price),
                "line_total_label": _format_pos_currency_label(line_total),
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
):
    safe_limit = max(1, min(_to_int(limit, 60), 200))
    params = [date_from, date_to]
    query = """
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.note,
            ps.created_at,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS cashier_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS cashier_username,
            COALESCE(NULLIF(TRIM(e.position), ''), COALESCE(NULLIF(TRIM(u.role), ''), 'Staff')) AS cashier_position,
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
            )
        """
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
        items = item_map.get(int(row["purchase_id"]), [])
        total_amount = _currency(row.get("total_amount") or 0)
        paid_amount = _currency(row.get("paid_amount") or 0)
        change_amount = _currency(row.get("change_amount") or 0)
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
                "created_time_label": created_time_label,
                "created_datetime_label": f"{row['sale_date']} {created_time_label}" if created_time_label != "-" else row["sale_date"],
                "customer_phone_label": row["customer_phone"] if row.get("customer_phone") and row["customer_phone"] != "-" else "Tanpa nomor",
                "cashier_identity_label": f"{row['cashier_name']} · {row['cashier_position']}",
                "items": items,
                "item_preview_lines": item_preview_lines,
                "item_preview_more": max(len(items) - len(item_preview_lines), 0),
                "receipt_print_url": f"/kasir/receipt/{row['receipt_no']}/print",
                "receipt_pdf_url": f"/kasir/receipt/{row['receipt_no']}/print?autoprint=1",
            }
        )

    return normalized_rows


def _build_pos_sale_log_summary(rows, period_label):
    total_items = sum(int(row.get("total_items") or 0) for row in rows)
    total_revenue = sum(float(row.get("total_amount") or 0) for row in rows)
    customer_total = len({int(row.get("customer_id") or 0) for row in rows if _to_int(row.get("customer_id"), 0) > 0})
    staff_total = len({int(row.get("cashier_user_id") or 0) for row in rows if _to_int(row.get("cashier_user_id"), 0) > 0})
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
    query = """
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.note,
            ps.created_at,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS cashier_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS cashier_username,
            COALESCE(NULLIF(TRIM(e.position), ''), COALESCE(NULLIF(TRIM(u.role), ''), 'Staff')) AS cashier_position,
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

    row = db.execute(query, params).fetchone()
    if not row:
        return None

    sale = dict(row)
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
    query = """
        SELECT
            ps.cashier_user_id,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS staff_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS username,
            COALESCE(NULLIF(TRIM(e.position), ''), 'Staff') AS position,
            COALESCE(NULLIF(TRIM(home_w.name), ''), '-') AS home_warehouse_name,
            COUNT(ps.id) AS total_transactions,
            COALESCE(SUM(ps.total_items), 0) AS total_items,
            COALESCE(SUM(ps.total_amount), 0) AS total_revenue,
            COALESCE(AVG(ps.total_amount), 0) AS average_ticket,
            COUNT(DISTINCT ps.customer_id) AS total_customers,
            COUNT(DISTINCT ps.warehouse_id) AS total_warehouses,
            GROUP_CONCAT(DISTINCT sale_w.name) AS warehouse_names,
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
            ps.cashier_user_id,
            staff_name,
            username,
            position,
            home_warehouse_name
        ORDER BY total_revenue DESC, total_transactions DESC, staff_name COLLATE NOCASE ASC
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

    existing = db.execute(
        """
        SELECT id, warehouse_id, customer_name, phone
        FROM crm_customers
        WHERE warehouse_id=?
          AND customer_name=?
          AND COALESCE(phone, '')=?
        LIMIT 1
        """,
        (warehouse_id, safe_name, safe_phone),
    ).fetchone()
    if existing:
        return existing

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


def _validate_and_build_items(db, warehouse_id, raw_items, *, free_reward_mode=False):
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("Keranjang kasir masih kosong.")

    prepared = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        product_id = _to_int(raw_item.get("product_id"), 0)
        variant_id = _to_int(raw_item.get("variant_id"), 0)
        qty = _to_int(raw_item.get("qty"), 0)
        unit_price = _to_decimal(raw_item.get("unit_price"), "0")

        if product_id <= 0 or variant_id <= 0 or qty <= 0:
            raise ValueError("Item kasir tidak valid. Periksa produk, variant, dan qty.")

        product = db.execute(
            """
            SELECT
                p.id AS product_id,
                p.sku,
                p.name AS product_name,
                v.id AS variant_id,
                COALESCE(v.variant, 'default') AS variant_name,
                COALESCE(v.price_nett, 0) AS price_nett,
                COALESCE(v.price_discount, 0) AS price_discount,
                COALESCE(v.price_retail, 0) AS price_retail,
                COALESCE(s.qty, 0) AS stock_qty
            FROM products p
            JOIN product_variants v
                ON v.id = ?
               AND v.product_id = p.id
            LEFT JOIN stock s
                ON s.product_id = p.id
               AND s.variant_id = v.id
               AND s.warehouse_id = ?
            WHERE p.id = ?
            LIMIT 1
            """,
            (variant_id, warehouse_id, product_id),
        ).fetchone()

        if not product:
            raise ValueError("Produk atau variant tidak ditemukan.")

        available_qty = int(product["stock_qty"] or 0)
        if available_qty < qty:
            label_variant = product["variant_name"] or "default"
            raise ValueError(
                f"Stok tidak cukup untuk {product['sku']} / {label_variant}. Tersedia {available_qty}, diminta {qty}."
            )

        if free_reward_mode:
            unit_price = Decimal("0.00")
        elif unit_price <= 0:
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
                "variant_name": product["variant_name"] or "default",
                "qty": qty,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    if not prepared:
        raise ValueError("Keranjang kasir masih kosong.")

    return prepared


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
        line_total = _currency(row["line_total"] or 0)
        void_amount = _currency(row["void_amount"] or 0)
        active_line_total = max(line_total - void_amount, 0)

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
                "unit_price": unit_price,
                "line_total": line_total,
                "void_amount": void_amount,
                "active_line_total": active_line_total,
                "void_note": row["void_note"],
                "unit_price_label": _format_pos_currency_label(unit_price),
                "line_total_label": _format_pos_currency_label(line_total),
                "void_amount_label": _format_pos_currency_label(void_amount),
                "active_line_total_label": _format_pos_currency_label(active_line_total),
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
):
    safe_limit = max(1, min(_to_int(limit, 60), 200))
    params = [date_from, date_to]
    query = """
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
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
            ps.note,
            ps.created_at,
            pr.member_id,
            pr.transaction_type,
            COALESCE(NULLIF(TRIM(m.member_code), ''), '') AS member_code,
            COALESCE(NULLIF(TRIM(m.member_type), ''), '') AS member_type,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS cashier_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS cashier_username,
            COALESCE(NULLIF(TRIM(e.position), ''), COALESCE(NULLIF(TRIM(u.role), ''), 'Staff')) AS cashier_position,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        LEFT JOIN crm_purchase_records pr ON pr.id = ps.purchase_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
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
            )
        """
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
        items = item_map.get(int(row["purchase_id"]), [])
        total_amount = _currency(row.get("total_amount") or 0)
        paid_amount = _currency(row.get("paid_amount") or 0)
        change_amount = _currency(row.get("change_amount") or 0)
        subtotal_amount = _currency(row.get("subtotal_amount") or 0)
        discount_amount = _currency(row.get("discount_amount") or 0)
        tax_amount = _currency(row.get("tax_amount") or 0)
        created_time_label = _format_pos_time_label(row.get("created_at"))
        item_preview_lines = items[:3]
        sale_status = _build_pos_sale_status_payload(row.get("status"))

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
                "created_time_label": created_time_label,
                "created_datetime_label": f"{row['sale_date']} {created_time_label}" if created_time_label != "-" else row["sale_date"],
                "customer_phone_label": row["customer_phone"] if row.get("customer_phone") and row["customer_phone"] != "-" else "Tanpa nomor",
                "cashier_identity_label": f"{row['cashier_name']} - {row['cashier_position']}",
                "items": items,
                "item_preview_lines": item_preview_lines,
                "item_preview_more": max(len(items) - len(item_preview_lines), 0),
                "has_voidable_items": any(item.get("can_void") for item in items),
                "receipt_print_url": f"/kasir/receipt/{row['receipt_no']}/print",
                "receipt_pdf_url": row.get("receipt_pdf_url") or f"/kasir/receipt/{row['receipt_no']}/print?autoprint=1",
                "receipt_pdf_public_url": row.get("receipt_pdf_url") or "",
                "receipt_whatsapp_status": str(row.get("receipt_whatsapp_status") or "pending").strip().lower(),
                "receipt_whatsapp_error": row.get("receipt_whatsapp_error") or "",
                "receipt_whatsapp_sent_at": row.get("receipt_whatsapp_sent_at"),
                **sale_status,
            }
        )

    return normalized_rows


def _fetch_pos_sale_detail_by_receipt(db, receipt_no):
    safe_receipt = str(receipt_no or "").strip()
    if not safe_receipt:
        return None

    params = [safe_receipt]
    query = """
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
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
            ps.note,
            ps.created_at,
            pr.member_id,
            pr.transaction_type,
            COALESCE(NULLIF(TRIM(m.member_code), ''), '') AS member_code,
            COALESCE(NULLIF(TRIM(m.member_type), ''), '') AS member_type,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS cashier_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS cashier_username,
            COALESCE(NULLIF(TRIM(e.position), ''), COALESCE(NULLIF(TRIM(u.role), ''), 'Staff')) AS cashier_position,
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
        query += " AND ps.warehouse_id=?"
        params.append(session.get("warehouse_id"))

    query += " LIMIT 1"

    row = db.execute(query, params).fetchone()
    if not row:
        return None

    sale = dict(row)
    items = _fetch_pos_sale_item_map(db, [sale["purchase_id"]]).get(int(sale["purchase_id"]), [])
    total_amount = _currency(sale.get("total_amount") or 0)
    paid_amount = _currency(sale.get("paid_amount") or 0)
    change_amount = _currency(sale.get("change_amount") or 0)
    subtotal_amount = _currency(sale.get("subtotal_amount") or 0)
    discount_amount = _currency(sale.get("discount_amount") or 0)
    tax_amount = _currency(sale.get("tax_amount") or 0)
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
        "created_time_label": created_time_label,
        "created_datetime_label": f"{sale['sale_date']} {created_time_label}" if created_time_label != "-" else sale["sale_date"],
        "customer_phone_label": sale["customer_phone"] if sale.get("customer_phone") and sale["customer_phone"] != "-" else "Tanpa nomor",
        "cashier_identity_label": f"{sale['cashier_name']} - {sale['cashier_position']}",
        "receipt_pdf_public_url": sale.get("receipt_pdf_url") or "",
        "receipt_whatsapp_status": str(sale.get("receipt_whatsapp_status") or "pending").strip().lower(),
        "receipt_whatsapp_error": sale.get("receipt_whatsapp_error") or "",
        "receipt_whatsapp_sent_at": sale.get("receipt_whatsapp_sent_at"),
        **_build_pos_sale_status_payload(sale.get("status")),
    }
    return _attach_pos_loyalty_summary(db, sale_detail)


def _fetch_pos_sale_detail_by_id(db, sale_id):
    safe_sale_id = _to_int(sale_id, 0)
    if safe_sale_id <= 0:
        return None

    params = [safe_sale_id]
    query = """
        SELECT receipt_no
        FROM pos_sales
        WHERE id=?
    """
    if is_scoped_role(session.get("role")):
        query += " AND warehouse_id=?"
        params.append(session.get("warehouse_id"))
    query += " LIMIT 1"

    row = db.execute(query, params).fetchone()
    if not row:
        return None
    return _fetch_pos_sale_detail_by_receipt(db, row["receipt_no"])


def _fetch_pos_staff_sales_rows(db, date_from, date_to, selected_warehouse=None):
    params = [date_from, date_to]
    query = """
        SELECT
            ps.cashier_user_id,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS staff_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS username,
            COALESCE(NULLIF(TRIM(e.position), ''), 'Staff') AS position,
            COALESCE(NULLIF(TRIM(home_w.name), ''), '-') AS home_warehouse_name,
            COUNT(ps.id) AS total_transactions,
            COALESCE(SUM(ps.total_items), 0) AS total_items,
            COALESCE(SUM(ps.total_amount), 0) AS total_revenue,
            COALESCE(AVG(ps.total_amount), 0) AS average_ticket,
            COUNT(DISTINCT ps.customer_id) AS total_customers,
            COUNT(DISTINCT ps.warehouse_id) AS total_warehouses,
            GROUP_CONCAT(DISTINCT sale_w.name) AS warehouse_names,
            MIN(ps.sale_date) AS first_sale_date,
            MAX(ps.sale_date) AS last_sale_date
        FROM pos_sales ps
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses home_w ON home_w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        LEFT JOIN warehouses sale_w ON sale_w.id = ps.warehouse_id
        WHERE ps.sale_date BETWEEN ? AND ?
          AND COALESCE(ps.status, 'posted') <> 'voided'
    """
    if selected_warehouse:
        query += " AND ps.warehouse_id=?"
        params.append(selected_warehouse)

    query += """
        GROUP BY
            ps.cashier_user_id,
            staff_name,
            username,
            position,
            home_warehouse_name
        ORDER BY total_revenue DESC, total_transactions DESC, staff_name COLLATE NOCASE ASC
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
    sale_date = _normalize_sale_date(request.args.get("sale_date"))
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None

    warehouses = db.execute(
        "SELECT id, name FROM warehouses ORDER BY name"
    ).fetchall()
    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
    )
    pos_staff_options = _fetch_pos_staff_options(db, selected_warehouse)
    selected_pos_staff_option = next(
        (option for option in pos_staff_options if option["id"] == _to_int(session.get("user_id"), 0)),
        pos_staff_options[0] if pos_staff_options else None,
    )

    if selected_pos_staff_option is None:
        selected_pos_staff_option = {
            "id": _to_int(session.get("user_id"), 0),
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
        pos_staff_options=pos_staff_options,
        selected_pos_staff_id=selected_pos_staff_option["id"],
        selected_pos_staff_label=selected_pos_staff_option["display_name"],
        pos_auto_print_after_checkout=bool(current_app.config.get("POS_AUTO_PRINT_AFTER_CHECKOUT")),
        can_view_pos_revenue=can_view_pos_revenue,
        summary=summary,
        recent_sales=_fetch_recent_sales(db, selected_warehouse, sale_date),
        sales_log_rows=sales_log_rows,
        sales_log_summary=sales_log_summary,
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

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
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
    weekly_summary = _mask_pos_staff_sales_summary(
        _build_pos_staff_sales_summary(weekly_rows, week_period["label"]),
        can_view_pos_revenue,
    )
    monthly_summary = _mask_pos_staff_sales_summary(
        _build_pos_staff_sales_summary(monthly_rows, month_period["label"]),
        can_view_pos_revenue,
    )
    weekly_rows = _mask_pos_staff_sales_rows(weekly_rows, can_view_pos_revenue)
    monthly_rows = _mask_pos_staff_sales_rows(monthly_rows, can_view_pos_revenue)

    return render_template(
        "pos_staff_sales_report.html",
        warehouses=warehouses,
        scoped_warehouse=scoped_warehouse,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        week_period=week_period,
        month_period=month_period,
        can_view_pos_revenue=can_view_pos_revenue,
        weekly_rows=weekly_rows,
        monthly_rows=monthly_rows,
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
    cash_closing_actor = _fetch_pos_cash_closing_actor(db, selected_warehouse, selected_cashier_user_id)
    cash_closing_reports = _fetch_pos_cash_closing_reports(
        db,
        warehouse_id=selected_warehouse,
        cashier_user_id=selected_cashier_user_id,
        limit=8,
    )
    cash_closing_default_date = date_range["date_to"]
    cash_closing_defaults = _build_pos_cash_closing_defaults(
        db,
        selected_warehouse_name,
        cash_closing_default_date,
        warehouse_id=selected_warehouse,
        cashier_user_id=cash_closing_actor.get("user_id"),
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
        cash_closing_actor=cash_closing_actor,
        cash_closing_reports=cash_closing_reports,
        cash_closing_default_date=cash_closing_default_date,
        cash_closing_defaults=cash_closing_defaults,
        cash_closing_preview_text=cash_closing_defaults["preview_text"],
        cash_closing_return_url=_build_pos_cash_closing_return_url(),
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
    cashier_user_id = _to_int(request.args.get("cashier_user_id"), 0) or None
    closing_date = _normalize_pos_cash_closing_date(request.args.get("closing_date"))
    defaults = _build_pos_cash_closing_defaults(
        db,
        warehouse_name,
        closing_date,
        warehouse_id=warehouse_id,
        cashier_user_id=cashier_user_id,
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
    cashier_actor = _fetch_pos_cash_closing_actor(db, warehouse_id, request.form.get("cashier_user_id"))
    closing_date = _normalize_pos_cash_closing_date(request.form.get("closing_date"))
    cash_amount = _parse_pos_cash_closing_amount(request.form.get("cash_amount"))
    debit_amount = _parse_pos_cash_closing_amount(request.form.get("debit_amount"))
    mb_amount = _parse_pos_cash_closing_amount(request.form.get("mb_amount"))
    cv_amount = _parse_pos_cash_closing_amount(request.form.get("cv_amount"))
    expense_amount = _parse_pos_cash_closing_amount(request.form.get("expense_amount"))
    cash_on_hand_amount = max(cash_amount - expense_amount, 0)
    combined_total_amount = _parse_pos_cash_closing_amount(request.form.get("combined_total_amount"))
    note = (request.form.get("note") or "").strip()
    return_url = _sanitize_pos_cash_closing_return_url(request.form.get("return_url"))

    if not any(
        (
            cash_amount,
            debit_amount,
            mb_amount,
            cv_amount,
            expense_amount,
            cash_on_hand_amount,
            combined_total_amount,
        )
    ):
        flash("Isi minimal satu nominal sebelum mengirim tutup kasir.", "error")
        return redirect(f"{return_url}#tutup-kasir")

    reported_total_amount = cash_amount + debit_amount + mb_amount + cv_amount
    summary_message = _build_pos_cash_closing_summary_message(
        warehouse_name,
        closing_date,
        cash_amount=cash_amount,
        debit_amount=debit_amount,
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
        f"{_format_pos_cash_closing_date_label(closing_date)} | {cashier_actor['display_name']}"
    )

    cursor = db.execute(
        """
        INSERT INTO cash_closing_reports(
            user_id,
            employee_id,
            warehouse_id,
            closing_date,
            cash_amount,
            debit_amount,
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
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cashier_actor.get("user_id"),
            cashier_actor.get("employee_id"),
            warehouse_id,
            closing_date,
            cash_amount,
            debit_amount,
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
                "roles": ("owner",),
                "usernames": ("edi", "akmal"),
                "warehouse_id": warehouse_id,
                "employee_name": cashier_actor["display_name"],
                "warehouse_name": warehouse_name,
                "subject": subject,
                "message": summary_message,
                "link_url": f"{return_url}#tutup-kasir",
            },
        )
        deliveries = wa_result.get("deliveries") or []
        delivery_count = len(deliveries)
        success_count = sum(1 for item in deliveries if item.get("ok"))
        error_messages = []
        for item in deliveries:
            error_text = str(item.get("error") or "").strip()
            if error_text and error_text not in error_messages:
                error_messages.append(error_text)
        wa_error = " | ".join(error_messages)
        if delivery_count <= 0:
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
        flash("Tutup kasir tersimpan dan WA owner / super admin berhasil dikirim.", "success")
    elif wa_status == "partial":
        flash("Tutup kasir tersimpan, tapi WA owner / super admin hanya terkirim sebagian.", "warning")
    elif wa_status == "failed":
        flash("Tutup kasir tersimpan, tapi kirim WA owner / super admin gagal. Cek nomor atau gateway WA.", "error")
    else:
        flash("Tutup kasir tersimpan. Belum ada owner / super admin tujuan yang menerima WA untuk laporan ini.", "warning")
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

    return render_template(
        "pos_receipt_print.html",
        **build_pos_receipt_render_context(
            sale,
            receipt_layout=receipt_layout,
            receipt_copy=receipt_copy,
            receipt_followup_copy=receipt_followup_copy,
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

    try:
        regenerated_sale, regenerated_pdf = _generate_backend_pos_receipt_pdf(db, sale_detail["receipt_no"])
        sale_detail = regenerated_sale
        sale_detail["receipt_pdf_public_url"] = regenerated_pdf.get("public_url") or ""
    except Exception as exc:
        print("POS RECEIPT RESEND PDF ERROR:", exc)
        return _json_error("Gagal menyiapkan PDF nota untuk kirim ulang. Coba lagi beberapa detik.", 500)

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
        restored = add_stock(
            sale_item["product_id"],
            sale_item["variant_id"],
            sale_item["warehouse_id"],
            requested_void_qty,
            note=f"VOID POS {sale_item['receipt_no']} - {sale_item['sku']} / {sale_item['variant_name']}",
            cost=restore_cost,
        )
        if not restored:
            raise ValueError("Stok gagal dikembalikan saat proses void item.")

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


@pos_bp.post("/checkout")
def pos_checkout():
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    if not has_permission(session.get("role"), "manage_pos"):
        return _json_error("Role ini belum punya izin melakukan checkout kasir.", 403)

    payload = request.get_json(silent=True) or {}
    db = get_db()

    warehouse_id = _resolve_pos_warehouse(db, payload.get("warehouse_id"))
    sale_date = _normalize_sale_date(payload.get("sale_date"))
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

    if not customer_name:
        return _json_error("Nama customer wajib diisi.", 400)
    if not customer_phone:
        return _json_error("No HP customer wajib diisi dengan angka yang valid.", 400)

    try:
        items = _validate_and_build_items(
            db,
            warehouse_id,
            payload.get("items"),
            free_reward_mode=transaction_type == "stringing_reward_redemption",
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

    paid_amount = _to_decimal(payload.get("paid_amount"), str(financials["total_amount"]))
    if paid_amount < financials["total_amount"]:
        return _json_error("Nominal bayar kurang dari total transaksi.", 400)

    change_amount = (paid_amount - financials["total_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    member_id = None
    member_snapshot = None
    receipt_no = (payload.get("receipt_no") or "").strip()

    try:
        db.execute("BEGIN")
        customer = _resolve_or_create_customer(
            db,
            warehouse_id,
            customer_id,
            customer_name,
            customer_phone,
        )

        active_member = db.execute(
            """
            SELECT *
            FROM crm_memberships
            WHERE customer_id=? AND status='active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (customer["id"],),
        ).fetchone()
        if active_member:
            member_id = active_member["id"]
            member_snapshot = get_member_snapshot(db, member_id)

        if transaction_type == "stringing_reward_redemption" and not member_id:
            raise ValueError("Free reward senaran hanya bisa dipakai oleh customer dengan member aktif.")

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
                transaction_type,
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
                unit_price,
                line_total,
                note
            )
            VALUES (?,?,?,?,?,?,?)
            """,
            [
                (
                    purchase_id,
                    item["product_id"],
                    item["variant_id"],
                    item["qty"],
                    _currency(item["unit_price"]),
                    _currency(item["line_total"]),
                    "POS Checkout",
                )
                for item in items
            ],
        )

        if member_id:
            auto_record = build_auto_member_record(
                member_snapshot or dict(active_member),
                member_snapshot or dict(active_member),
                purchase_id=purchase_id,
                warehouse_id=warehouse_id,
                record_date=sale_date,
                reference_no=receipt_no,
                amount=_currency(financials["total_amount"]),
                transaction_type=transaction_type,
                note=note or "",
                handled_by=session.get("user_id"),
                source_label="POS / iPos",
            )
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
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                purchase_id,
                customer["id"],
                warehouse_id,
                selected_cashier["id"],
                sale_date,
                receipt_no,
                payment_method,
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

        for item in items:
            removed = remove_stock(
                item["product_id"],
                item["variant_id"],
                warehouse_id,
                item["qty"],
                note=f"POS {receipt_no}",
            )
            if not removed:
                raise ValueError(
                    f"Gagal memotong stok {item['sku']} / {item['variant_name']}. Silakan refresh data stok."
                )

        db.commit()

    except ValueError as exc:
        db.rollback()
        return _json_error(str(exc), 400)
    except Exception:
        db.rollback()
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

    return jsonify(
        {
            "status": "success",
            "message": "Checkout kasir berhasil disimpan.",
            "sale_id": sale_id,
            "receipt_no": receipt_no,
            "purchase_id": purchase_id,
            "customer_name": customer["customer_name"],
            "total_items": financials["total_items"],
            "subtotal_amount": _currency(financials["subtotal_amount"]),
            "discount_amount": _currency(financials["discount_amount"]),
            "tax_amount": _currency(financials["tax_amount"]),
            "total_amount": _currency(financials["total_amount"]),
            "paid_amount": _currency(paid_amount),
            "change_amount": _currency(change_amount),
            "receipt_print_url": (
                f"/kasir/receipt/{receipt_no}/print"
                f"?layout=thermal&copy=customer&followup_copy=store&autoprint=1&autoclose=1"
            ),
            "receipt_pdf_public_url": (receipt_pdf_meta or {}).get("public_url") or "",
            "receipt_whatsapp_status": _resolve_pos_receipt_whatsapp_status(receipt_delivery),
            "receipt_whatsapp_error": str((receipt_delivery or {}).get("error") or "").strip(),
        }
    )
