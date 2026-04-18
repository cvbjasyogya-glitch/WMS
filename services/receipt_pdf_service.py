import base64
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
from uuid import uuid4

from flask import current_app, has_request_context, render_template, request


_POS_RECEIPT_BRANDS = {
    "default": {
        "business_name": "ERP Core POS",
        "accent": "#1f5a97",
        "accent_dark": "#163f6b",
        "accent_soft": "#eef4fb",
        "ambient_tint": "rgba(31, 90, 151, 0.10)",
        "logo_relative_path": "static/brand/mataram-logo.png",
    },
    "mataram": {
        "business_name": "Mataram Sports",
        "accent": "#5fa236",
        "accent_dark": "#3d6f20",
        "accent_soft": "#eef7e8",
        "ambient_tint": "rgba(95, 162, 54, 0.12)",
        "logo_relative_path": "static/brand/receipt-logo-mataram.jpg",
    },
    "mega": {
        "business_name": "Mega Sports",
        "accent": "#1956b5",
        "accent_dark": "#143f86",
        "accent_soft": "#ecf3ff",
        "ambient_tint": "rgba(25, 86, 181, 0.11)",
        "logo_relative_path": "static/brand/receipt-logo-mega.jpg",
    },
}


def _resolve_receipt_brand_config(prefix, brand_key, fallback=""):
    config = current_app.config
    scoped_value = str(config.get(f"{prefix}_{str(brand_key or '').upper()}") or "").strip()
    if scoped_value:
        return scoped_value
    shared_value = str(config.get(prefix) or "").strip()
    if shared_value:
        return shared_value
    return str(fallback or "").strip()


def _normalize_ascii_text(value):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    return text.encode("latin-1", "replace").decode("latin-1")


def _escape_pdf_text(value):
    text = _normalize_ascii_text(value)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _resolve_public_base_url():
    configured = str(current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured

    canonical_host = str(current_app.config.get("CANONICAL_HOST") or "").strip()
    if canonical_host:
        scheme = str(current_app.config.get("CANONICAL_SCHEME") or current_app.config.get("PREFERRED_URL_SCHEME") or "https").strip()
        return f"{scheme}://{canonical_host}".rstrip("/")

    if has_request_context():
        return str(request.host_url or "").strip().rstrip("/")

    return ""


def get_pos_receipt_pdf_folder():
    folder = current_app.config.get("POS_RECEIPT_PDF_FOLDER") or os.path.join(
        current_app.root_path,
        "static",
        "uploads",
        "pos_receipts",
    )
    os.makedirs(folder, exist_ok=True)
    return folder


def get_pos_receipt_pdf_url_prefix():
    return str(current_app.config.get("POS_RECEIPT_PDF_URL_PREFIX") or "/static/uploads/pos_receipts").rstrip("/")


def build_public_file_url(path):
    safe_path = str(path or "").strip()
    if not safe_path:
        return ""
    if safe_path.startswith(("http://", "https://")):
        return safe_path
    if not safe_path.startswith("/"):
        safe_path = f"/{safe_path}"
    base_url = _resolve_public_base_url()
    return f"{base_url}{safe_path}" if base_url else safe_path


def build_pos_receipt_pdf_public_url(file_name):
    safe_name = str(file_name or "").strip().lstrip("/\\")
    if not safe_name:
        return ""
    return build_public_file_url(f"{get_pos_receipt_pdf_url_prefix()}/{safe_name}")


def _normalize_receipt_layout(value, default="a4"):
    normalized = str(value or "").strip().lower()
    if normalized == "thermal":
        return "thermal"
    default_value = str(default or "a4").strip().lower()
    return "thermal" if default_value == "thermal" else "a4"


def _normalize_receipt_copy(value, default="customer"):
    normalized = str(value or "").strip().lower()
    if normalized == "store":
        return "store"
    default_value = str(default or "customer").strip().lower()
    return "store" if default_value == "store" else "customer"


def _normalize_receipt_performance_mode(value, default="auto"):
    normalized = str(value or "").strip().lower()
    if normalized in {"lite", "full"}:
        return normalized
    default_value = str(default or "auto").strip().lower()
    if default_value in {"lite", "full"}:
        return default_value
    return "auto"


def _encode_asset_as_data_uri(path):
    safe_path = str(path or "").strip()
    if not safe_path or not os.path.exists(safe_path):
        return ""
    mime_type, _ = mimetypes.guess_type(safe_path)
    safe_mime = mime_type or "application/octet-stream"
    with open(safe_path, "rb") as file_handle:
        encoded = base64.b64encode(file_handle.read()).decode("ascii")
    return f"data:{safe_mime};base64,{encoded}"


def _resolve_receipt_brand_html_assets(receipt_brand):
    brand = dict(receipt_brand or {})
    logo_pdf_path = str(brand.get("logo_pdf_path") or "").strip()
    if logo_pdf_path:
        embedded_logo = _encode_asset_as_data_uri(logo_pdf_path)
        if embedded_logo:
            brand["logo_url"] = embedded_logo

    social_qr_value = str(brand.get("social_qr_image_url") or "").strip()
    if social_qr_value and not social_qr_value.startswith(("data:", "http://", "https://")):
        local_candidate = social_qr_value
        if social_qr_value.startswith("/"):
            local_candidate = os.path.join(current_app.root_path, social_qr_value.lstrip("/\\").replace("/", os.sep))
        embedded_qr = _encode_asset_as_data_uri(local_candidate)
        if embedded_qr:
            brand["social_qr_image_url"] = embedded_qr
    return brand


def build_pos_receipt_render_context(
    sale=None,
    *,
    receipt_layout="a4",
    receipt_copy="customer",
    receipt_followup_copy="",
    receipt_performance_mode="auto",
    auto_print=False,
    auto_close=False,
    pdf_mode=False,
    embed_assets=False,
):
    safe_sale = dict(sale or {})
    receipt_brand = dict(safe_sale.get("receipt_brand") or build_pos_receipt_branding(safe_sale))
    if embed_assets:
        receipt_brand = _resolve_receipt_brand_html_assets(receipt_brand)

    default_store_name = str(current_app.config.get("STORE_NAME") or "CV BERKAH JAYA ABADI SPORTS").strip()
    store_name = str(receipt_brand.get("business_name") or default_store_name).strip()
    store_phone = str(receipt_brand.get("customer_service_phone") or current_app.config.get("STORE_PHONE") or "").strip()
    normalized_receipt_layout = _normalize_receipt_layout(receipt_layout, default="a4")
    normalized_receipt_copy = _normalize_receipt_copy(receipt_copy, default="customer")
    normalized_followup_copy = ""
    requested_followup_copy = str(receipt_followup_copy or "").strip().lower()
    if normalized_receipt_layout == "thermal" and requested_followup_copy in {"customer", "store"}:
        normalized_followup_copy = _normalize_receipt_copy(requested_followup_copy, default="customer")
        if normalized_followup_copy == normalized_receipt_copy:
            normalized_followup_copy = ""
    normalized_performance_mode = _normalize_receipt_performance_mode(
        receipt_performance_mode,
        default="full" if pdf_mode else "auto",
    )

    return {
        "sale": safe_sale,
        "receipt_brand": receipt_brand,
        "store_name": store_name,
        "store_phone": store_phone,
        "receipt_layout": normalized_receipt_layout,
        "receipt_copy": normalized_receipt_copy,
        "receipt_copy_label": "Copy Toko" if normalized_receipt_copy == "store" else "Copy Customer",
        "receipt_followup_copy": normalized_followup_copy,
        "receipt_performance_mode": normalized_performance_mode,
        "auto_print": bool(auto_print),
        "auto_close": bool(auto_close),
        "pdf_mode": bool(pdf_mode),
    }


def _find_pos_receipt_pdf_browser():
    configured_browser = str(
        current_app.config.get("POS_RECEIPT_PDF_BROWSER")
        or os.getenv("POS_RECEIPT_PDF_BROWSER")
        or ""
    ).strip()
    candidates = []
    if configured_browser:
        candidates.append(configured_browser)

    for executable_name in (
        "msedge",
        "microsoft-edge",
        "google-chrome",
        "chrome",
        "chromium-browser",
        "chromium",
    ):
        detected = shutil.which(executable_name)
        if detected:
            candidates.append(detected)

    for env_name, relative_path in (
        ("ProgramFiles(x86)", os.path.join("Microsoft", "Edge", "Application", "msedge.exe")),
        ("ProgramFiles", os.path.join("Microsoft", "Edge", "Application", "msedge.exe")),
        ("ProgramFiles(x86)", os.path.join("Google", "Chrome", "Application", "chrome.exe")),
        ("ProgramFiles", os.path.join("Google", "Chrome", "Application", "chrome.exe")),
    ):
        base_path = str(os.getenv(env_name) or "").strip()
        if not base_path:
            continue
        candidates.append(os.path.join(base_path, relative_path))

    seen_paths = set()
    for candidate in candidates:
        safe_candidate = str(candidate or "").strip().strip('"')
        if not safe_candidate or safe_candidate in seen_paths:
            continue
        seen_paths.add(safe_candidate)
        resolved = shutil.which(safe_candidate)
        if resolved:
            return resolved
        if os.path.exists(safe_candidate):
            return safe_candidate
    return ""


def _render_pos_receipt_pdf_via_browser(sale, absolute_path):
    browser_executable = _find_pos_receipt_pdf_browser()
    if not browser_executable:
        return False, "browser_not_found"

    # PDF yang dikirim ke customer selalu dipaksa ke dokumen tunggal A4.
    # Layout thermal tetap dipakai untuk print kasir interaktif, tapi tidak stabil
    # untuk file PDF customer karena mudah terpotong / terpecah beberapa halaman.
    renderer_layout = "a4"
    browser_timeout = max(
        10,
        int(
            current_app.config.get("POS_RECEIPT_PDF_BROWSER_TIMEOUT_SECONDS")
            or os.getenv("POS_RECEIPT_PDF_BROWSER_TIMEOUT_SECONDS")
            or 25
        ),
    )
    public_base_url = _resolve_public_base_url() or "http://localhost"
    if not public_base_url.endswith("/"):
        public_base_url = f"{public_base_url}/"

    with current_app.test_request_context("/kasir/receipt/__pdf__", base_url=public_base_url):
        html_payload = render_template(
            "pos_receipt_print.html",
            **build_pos_receipt_render_context(
                sale,
                receipt_layout=renderer_layout,
                receipt_performance_mode="full",
                auto_print=False,
                auto_close=False,
                pdf_mode=True,
                embed_assets=True,
            ),
        )

    last_error = "browser_render_failed"
    temp_root = get_pos_receipt_pdf_folder()
    temp_dir = os.path.join(temp_root, f".tmp-html-render-{uuid4().hex}")
    os.makedirs(temp_dir, exist_ok=True)
    try:
        html_path = os.path.join(temp_dir, "receipt.html")
        with open(html_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(html_payload)

        html_uri = Path(html_path).resolve().as_uri()
        command_variants = (
            ["--print-to-pdf-no-header"],
            ["--no-pdf-header-footer"],
            [],
        )
        for extra_flags in command_variants:
            if os.path.exists(absolute_path):
                os.remove(absolute_path)
            command = [
                browser_executable,
                "--headless",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                f"--print-to-pdf={absolute_path}",
                *extra_flags,
                html_uri,
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=browser_timeout,
                    check=False,
                )
            except Exception as exc:
                last_error = f"browser_render_error: {exc}"
                continue

            if completed.returncode == 0 and os.path.exists(absolute_path) and os.path.getsize(absolute_path) > 0:
                return True, ""

            stderr = str(completed.stderr or "").strip()
            stdout = str(completed.stdout or "").strip()
            last_error = stderr or stdout or f"browser_exit_{completed.returncode}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return False, last_error


def _wrap_receipt_line(value, width=74):
    text = _normalize_ascii_text(value)
    if not text:
        return [""]
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [text]


def _append_receipt_label_lines(lines, label, value, width=68, label_width=9):
    safe_lines = lines if isinstance(lines, list) else []
    prefix = f"{str(label or '').strip():<{label_width}}: "
    wrapped = _wrap_receipt_line(value, width=max(12, width - len(prefix)))
    for index, part in enumerate(wrapped):
        safe_lines.append(f"{prefix if index == 0 else ' ' * len(prefix)}{part}")
    return safe_lines


def _append_receipt_prefixed_lines(lines, prefix, value, width=68):
    safe_lines = lines if isinstance(lines, list) else []
    safe_prefix = str(prefix or "")
    wrapped = _wrap_receipt_line(value, width=max(12, width - len(safe_prefix)))
    for index, part in enumerate(wrapped):
        safe_lines.append(f"{safe_prefix if index == 0 else ' ' * len(safe_prefix)}{part}")
    return safe_lines


def format_receipt_homebase_label(warehouse_name):
    text = str(warehouse_name or "").strip()
    if not text:
        return "-"
    text = re.sub(r"\b(homebase|gudang)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "-"


def _resolve_pos_receipt_brand_key(warehouse_id=None, warehouse_name=None):
    normalized_name = str(warehouse_name or "").strip().lower()
    warehouse_number = 0
    try:
        warehouse_number = int(warehouse_id or 0)
    except (TypeError, ValueError):
        warehouse_number = 0

    if warehouse_number == 2 or "mega" in normalized_name:
        return "mega"
    if warehouse_number == 1 or "mataram" in normalized_name:
        return "mataram"
    return "default"


def build_pos_receipt_branding(sale=None):
    sale = sale or {}
    brand_key = _resolve_pos_receipt_brand_key(sale.get("warehouse_id"), sale.get("warehouse_name"))
    brand = dict(_POS_RECEIPT_BRANDS.get(brand_key) or _POS_RECEIPT_BRANDS["default"])
    logo_relative_path = str(brand.get("logo_relative_path") or "").strip().lstrip("/\\")
    if not logo_relative_path:
        logo_relative_path = "static/brand/mataram-logo.png"
    logo_url = f"/{logo_relative_path}" if logo_relative_path else ""
    logo_pdf_path = ""
    if logo_relative_path:
        candidate_path = os.path.join(current_app.root_path, *logo_relative_path.split("/"))
        if os.path.exists(candidate_path):
            logo_pdf_path = candidate_path
        else:
            logo_url = ""

    homebase_label = format_receipt_homebase_label(sale.get("warehouse_name"))
    business_name = str(brand.get("business_name") or "ERP Core POS").strip()
    business_address = str(
        _resolve_receipt_brand_config(
            "POS_RECEIPT_ADDRESS",
            brand_key,
            "",
        )
    ).strip()
    business_address = (
        format_receipt_homebase_label(business_address)
        if business_address
        else ""
    )
    customer_service_phone = _resolve_receipt_brand_config(
        "POS_RECEIPT_CUSTOMER_SERVICE",
        brand_key,
        current_app.config.get("STORE_PHONE") or "",
    )
    footer_identity = _resolve_receipt_brand_config(
        "POS_RECEIPT_FOOTER_IDENTITY",
        brand_key,
        f"{business_name} | {homebase_label}" if homebase_label != "-" else business_name,
    )
    footer_note = _resolve_receipt_brand_config(
        "POS_RECEIPT_FOOTER_NOTE",
        brand_key,
        f"Simpan nota ini untuk klaim garansi dan layanan {business_name}.",
    )
    return_policy = _resolve_receipt_brand_config(
        "POS_RECEIPT_RETURN_POLICY",
        brand_key,
        "Barang yang telah dibayarkan tidak dapat dikembalikan, kecuali produk tertentu sesuai perjanjian.",
    )
    thank_you_text = _resolve_receipt_brand_config(
        "POS_RECEIPT_THANK_YOU_TEXT",
        brand_key,
        "Terima kasih atas kunjungan Anda.",
    )
    feedback_line = _resolve_receipt_brand_config(
        "POS_RECEIPT_FEEDBACK_LINE",
        brand_key,
        f"Kritik & Saran: {customer_service_phone or current_app.config.get('STORE_PHONE') or '-'}",
    )
    social_label = _resolve_receipt_brand_config(
        "POS_RECEIPT_SOCIAL_LABEL",
        brand_key,
        "Social Media Kami di:",
    )
    social_media_url = _resolve_receipt_brand_config(
        "POS_RECEIPT_SOCIAL_URL",
        brand_key,
        "",
    )
    social_qr_image_value = _resolve_receipt_brand_config(
        "POS_RECEIPT_SOCIAL_QR_IMAGE",
        brand_key,
        "",
    )
    social_qr_image_url = (
        "/" + social_qr_image_value.lstrip("/\\")
        if social_qr_image_value and not social_qr_image_value.startswith(("http://", "https://", "/"))
        else social_qr_image_value
    )
    return {
        **brand,
        "key": brand_key,
        "homebase_label": homebase_label,
        "receipt_title": "Nota Pembelian iPOS",
        "counter_label": "iPOS Kasir",
        "logo_url": logo_url,
        "logo_pdf_path": logo_pdf_path,
        "business_address": business_address,
        "customer_service_phone": customer_service_phone,
        "footer_identity": footer_identity,
        "footer_note": footer_note,
        "return_policy": return_policy,
        "thank_you_text": thank_you_text,
        "feedback_line": feedback_line,
        "social_label": social_label,
        "social_media_url": social_media_url,
        "social_qr_image_url": social_qr_image_url,
    }


def _hex_to_pdf_rgb(hex_color):
    safe_hex = str(hex_color or "").strip().lstrip("#")
    if len(safe_hex) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", safe_hex):
        safe_hex = "153e75"
    red = int(safe_hex[0:2], 16) / 255
    green = int(safe_hex[2:4], 16) / 255
    blue = int(safe_hex[4:6], 16) / 255
    return f"{red:.4f}", f"{green:.4f}", f"{blue:.4f}"


def _extract_jpeg_dimensions(image_bytes):
    if not image_bytes or len(image_bytes) < 4 or not image_bytes.startswith(b"\xff\xd8"):
        return 0, 0

    index = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }

    while index < len(image_bytes):
        while index < len(image_bytes) and image_bytes[index] != 0xFF:
            index += 1
        while index < len(image_bytes) and image_bytes[index] == 0xFF:
            index += 1
        if index >= len(image_bytes):
            break

        marker = image_bytes[index]
        index += 1
        if marker in (0xD8, 0xD9):
            continue
        if index + 1 >= len(image_bytes):
            break

        segment_length = int.from_bytes(image_bytes[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(image_bytes):
            break

        if marker in sof_markers and index + 7 <= len(image_bytes):
            height = int.from_bytes(image_bytes[index + 3 : index + 5], "big")
            width = int.from_bytes(image_bytes[index + 5 : index + 7], "big")
            return width, height
        index += segment_length

    return 0, 0


def _load_pdf_logo_spec(branding):
    logo_path = str((branding or {}).get("logo_pdf_path") or "").strip()
    if not logo_path or not os.path.exists(logo_path):
        return None

    try:
        with open(logo_path, "rb") as file_handle:
            image_bytes = file_handle.read()
    except OSError:
        return None

    width, height = _extract_jpeg_dimensions(image_bytes)
    if width <= 0 or height <= 0:
        return None

    return {
        "bytes": image_bytes,
        "width": width,
        "height": height,
    }


def _build_receipt_lines(sale):
    sale = sale or {}
    branding = sale.get("receipt_brand") or build_pos_receipt_branding(sale)
    homebase_label = branding.get("homebase_label") or format_receipt_homebase_label(sale.get("warehouse_name"))
    business_address = branding.get("business_address") or sale.get("store_address") or ""
    customer_service_phone = branding.get("customer_service_phone") or sale.get("store_phone") or current_app.config.get("STORE_PHONE") or ""
    footer_note = branding.get("footer_note") or f"Terima kasih sudah berbelanja di {branding.get('business_name') or 'ERP Core POS'}."
    separator = "-" * 68
    lines = []
    _append_receipt_label_lines(lines, "Receipt", sale.get("receipt_no") or "-", width=68)
    _append_receipt_label_lines(
        lines,
        "Tanggal",
        sale.get("created_datetime_label") or sale.get("sale_date") or "-",
        width=68,
    )
    if business_address:
        _append_receipt_label_lines(lines, "Alamat", business_address, width=68)
    _append_receipt_label_lines(
        lines,
        "Kasir",
        sale.get("cashier_receipt_label") or sale.get("cashier_username") or sale.get("cashier_name") or "-",
        width=68,
    )
    _append_receipt_label_lines(lines, "Customer", sale.get("customer_name") or "Walk-in Customer", width=68)
    _append_receipt_label_lines(
        lines,
        "WhatsApp",
        sale.get("customer_phone_label") or sale.get("customer_phone") or "-",
        width=68,
    )
    _append_receipt_label_lines(
        lines,
        "Bayar",
        (
            f"{sale.get('payment_method_label') or sale.get('payment_method') or 'CASH'}"
            f" | Status {sale.get('status_label') or sale.get('status') or 'POSTED'}"
        ),
        width=68,
    )
    lines.extend([separator, "ITEM", separator])

    for index, item in enumerate(sale.get("items") or [], start=1):
        product_name = item.get("product_name") or "Produk"
        variant_name = item.get("variant_name") or "default"
        sku = item.get("sku") or "-"
        lines.extend(_wrap_receipt_line(f"{index}. {product_name}", width=66))
        lines.extend(_wrap_receipt_line(f"    {variant_name} | {sku}", width=66))
        active_qty = int(item.get("active_qty") or item.get("qty") or 0)
        active_total_label = item.get("active_line_total_label") or item.get("line_total_label") or "Rp 0"
        unit_price_label = item.get("unit_price_label") or "Rp 0"
        lines.append(f"    Qty {active_qty} x {unit_price_label} = {active_total_label}")
        if item.get("has_discount") and active_qty > 0:
            unit_discount_label = item.get("unit_discount_label") or "Rp 0"
            total_discount_label = item.get("total_discount_label") or "Rp 0"
            retail_label = item.get("retail_price_label") or "Rp 0"
            lines.append(
                f"    Diskon item {unit_discount_label} x {active_qty} = {total_discount_label} (Retail {retail_label})"
            )
        if int(item.get("void_qty") or 0) > 0:
            lines.append(
                f"    Void {int(item.get('void_qty') or 0)} | {item.get('void_amount_label') or 'Rp 0'}"
            )
        if item.get("void_note"):
            for wrapped_line in _wrap_receipt_line(f"    Catatan void: {item.get('void_note')}", width=66):
                lines.append(wrapped_line)

    lines.extend(
        [
            separator,
            f"Subtotal : {_normalize_ascii_text(sale.get('subtotal_amount_label') or 'Rp 0')}",
            (
                f"Diskon   : {_normalize_ascii_text(sale.get('discount_amount_label') or 'Rp 0')}"
                f" ({_normalize_ascii_text(sale.get('discount_rule_label') or '-')})"
            ),
            (
                f"Pajak    : {_normalize_ascii_text(sale.get('tax_amount_label') or 'Rp 0')}"
                f" ({_normalize_ascii_text(sale.get('tax_rule_label') or '-')})"
            ),
            f"Total    : {_normalize_ascii_text(sale.get('total_amount_label') or 'Rp 0')}",
            f"Bayar    : {_normalize_ascii_text(sale.get('paid_amount_label') or 'Rp 0')}",
            f"Kembali  : {_normalize_ascii_text(sale.get('change_amount_label') or 'Rp 0')}",
        ]
    )
    if sale.get("has_payment_breakdown") and sale.get("payment_breakdown_label"):
        _append_receipt_label_lines(
            lines,
            "Split",
            sale.get("payment_breakdown_label"),
            width=68,
        )

    loyalty_lines = [str(line or "").strip() for line in (sale.get("loyalty_summary_lines") or []) if str(line or "").strip()]
    if loyalty_lines:
        lines.extend(
            [
                separator,
                _normalize_ascii_text(sale.get("loyalty_summary_title") or "UPDATE CRM CUSTOMER"),
            ]
        )
        for loyalty_line in loyalty_lines:
            lines.extend(_wrap_receipt_line(loyalty_line, width=66))

    if sale.get("note"):
        lines.append(separator)
        _append_receipt_label_lines(lines, "Catatan", sale.get("note"), width=68)

    lines.append(separator)
    if customer_service_phone:
        _append_receipt_prefixed_lines(lines, "Customer Service: ", customer_service_phone, width=68)
    _append_receipt_prefixed_lines(lines, "", footer_note, width=68)
    return lines


def _estimate_pdf_text_width(value, font_size=10.0, bold=False):
    text = _normalize_ascii_text(value)
    if not text:
        return 0.0
    average_width = 0.58 if bold else 0.54
    return float(len(text)) * float(font_size) * average_width


def _append_pdf_rect(commands, x, y, width, height, *, fill_hex="#ffffff", stroke_hex="#d7e2ec", line_width=1.0):
    fill_red, fill_green, fill_blue = _hex_to_pdf_rgb(fill_hex)
    stroke_red, stroke_green, stroke_blue = _hex_to_pdf_rgb(stroke_hex)
    commands.extend(
        [
            f"{line_width:.2f} w",
            f"{stroke_red} {stroke_green} {stroke_blue} RG",
            f"{fill_red} {fill_green} {fill_blue} rg",
            f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re B",
        ]
    )


def _append_pdf_line(commands, x1, y1, x2, y2, *, stroke_hex="#d7e2ec", line_width=0.8, dashed=False):
    stroke_red, stroke_green, stroke_blue = _hex_to_pdf_rgb(stroke_hex)
    commands.extend(
        [
            f"{line_width:.2f} w",
            f"{stroke_red} {stroke_green} {stroke_blue} RG",
            "[3 3] 0 d" if dashed else "[] 0 d",
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S",
            "[] 0 d",
        ]
    )


def _append_pdf_text(
    commands,
    x,
    y,
    lines,
    *,
    font_name="F1",
    font_size=10.0,
    color_hex="#14273a",
    leading=None,
    align="left",
    box_width=None,
):
    safe_lines = [_normalize_ascii_text(line) for line in (lines or [])]
    if not safe_lines:
        return

    leading = float(leading or (font_size + 2.0))
    red, green, blue = _hex_to_pdf_rgb(color_hex)
    commands.extend(
        [
            "BT",
            f"{red} {green} {blue} rg",
            f"/{font_name} {float(font_size):.2f} Tf",
        ]
    )

    baseline = float(y)
    is_bold = font_name == "F2"
    for line in safe_lines:
        draw_x = float(x)
        if box_width is not None and align != "left":
            estimated_width = _estimate_pdf_text_width(line, font_size=font_size, bold=is_bold)
            if align == "right":
                draw_x = float(x) + max(float(box_width) - estimated_width, 0.0)
            elif align == "center":
                draw_x = float(x) + max((float(box_width) - estimated_width) / 2.0, 0.0)
        commands.append(f"1 0 0 1 {draw_x:.2f} {baseline:.2f} Tm")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
        baseline -= leading

    commands.append("ET")


def _append_pdf_chip(
    commands,
    x,
    top,
    text,
    *,
    fill_hex,
    stroke_hex,
    text_hex,
    font_name="F2",
    font_size=9.3,
    padding_x=12.0,
    height=26.0,
):
    safe_text = _normalize_ascii_text(text) or "-"
    chip_width = max(88.0, _estimate_pdf_text_width(safe_text, font_size=font_size, bold=(font_name == "F2")) + (padding_x * 2.0))
    _append_pdf_rect(
        commands,
        x,
        top - height,
        chip_width,
        height,
        fill_hex=fill_hex,
        stroke_hex=stroke_hex,
        line_width=0.9,
    )
    _append_pdf_text(
        commands,
        x + padding_x,
        top - 16.8,
        [safe_text],
        font_name=font_name,
        font_size=font_size,
        color_hex=text_hex,
    )
    return chip_width


def _build_receipt_pdf_info_rows(sale):
    sale = sale or {}
    created_stamp = " ".join(
        part
        for part in [
            str(sale.get("sale_date") or "").strip(),
            str(sale.get("created_time_label") or "").strip(),
        ]
        if part
    ).strip() or "-"
    return [
        [
            {"label": "NO NOTA", "value": sale.get("receipt_no") or "-", "span": 1},
            {"label": "TANGGAL", "value": created_stamp, "span": 1},
        ],
        [
            {"label": "PELANGGAN", "value": sale.get("customer_name") or "Walk-in Customer", "span": 1},
            {"label": "WHATSAPP", "value": sale.get("customer_phone_label") or sale.get("customer_phone") or "-", "span": 1},
        ],
        [
            {
                "label": "KASIR / SALES",
                "value": sale.get("cashier_receipt_label") or sale.get("cashier_username") or sale.get("cashier_name") or "-",
                "span": 2,
            }
        ],
    ]


def _measure_receipt_pdf_info_row_height(row):
    max_height = 52.0
    for card in row:
        wrap_width = 34 if int(card.get("span") or 1) == 1 else 78
        value_lines = _wrap_receipt_line(card.get("value"), width=wrap_width) or ["-"]
        max_height = max(max_height, 32.0 + (len(value_lines) * 12.0))
    return max_height


def _estimate_receipt_pdf_first_page_item_top(sale):
    current_top = 610.0
    row_gap = 10.0
    for row in _build_receipt_pdf_info_rows(sale):
        current_top -= _measure_receipt_pdf_info_row_height(row) + row_gap
    return current_top - 6.0


def _build_receipt_pdf_item_blocks(sale):
    blocks = []
    for item in sale.get("items") or []:
        product_name = item.get("product_name") or item.get("name") or item.get("sku") or "Produk"
        variant_name = item.get("variant_name") or "Default"
        sku = item.get("sku") or "-"
        active_qty = int(item.get("active_qty") or item.get("qty") or 0)
        unit_price_label = item.get("unit_price_label") or "Rp 0"
        total_label = item.get("active_line_total_label") or item.get("line_total_label") or "Rp 0"

        title_lines = _wrap_receipt_line(product_name, width=54) or ["Produk"]
        meta_lines = _wrap_receipt_line(f"{variant_name} / {sku}", width=62) or ["-"]
        detail_lines = []
        if active_qty > 1:
            detail_lines.extend(_wrap_receipt_line(f"{active_qty} x {unit_price_label}", width=42))
        if item.get("has_discount") and active_qty > 0:
            unit_discount_label = item.get("unit_discount_label") or "Rp 0"
            total_discount_label = item.get("total_discount_label") or "Rp 0"
            retail_label = item.get("retail_price_label") or "Rp 0"
            detail_lines.extend(
                _wrap_receipt_line(
                    f"Diskon item {unit_discount_label} x {active_qty} = {total_discount_label} (Retail {retail_label})",
                    width=54,
                )
            )
        if int(item.get("void_qty") or 0) > 0:
            detail_lines.extend(
                _wrap_receipt_line(
                    f"Void {int(item.get('void_qty') or 0)} | {item.get('void_amount_label') or 'Rp 0'}",
                    width=54,
                )
            )
        if item.get("void_note"):
            detail_lines.extend(_wrap_receipt_line(f"Catatan void: {item.get('void_note')}", width=54))

        block_height = max(
            78.0,
            24.0 + (len(title_lines) * 13.0) + (len(meta_lines) * 10.6) + (len(detail_lines) * 10.0) + 24.0,
        )
        blocks.append(
            {
                "title_lines": title_lines,
                "meta_lines": meta_lines,
                "detail_lines": detail_lines,
                "qty_text": str(active_qty),
                "price_text": total_label,
                "height": block_height,
            }
        )
    return blocks


def _build_receipt_pdf_summary_model(sale, branding):
    sale = sale or {}
    branding = branding or {}
    note_lines = _wrap_receipt_line(
        sale.get("note") or "Terima kasih sudah berbelanja. Simpan nota ini sebagai bukti pembelian.",
        width=80,
    ) or ["-"]
    footer_title_lines = _wrap_receipt_line(
        branding.get("footer_note") or f"Simpan nota ini untuk klaim garansi dan layanan {branding.get('business_name') or 'ERP Core POS'}.",
        width=78,
    ) or ["-"]
    footer_detail_lines = []
    business_address = branding.get("business_address") or sale.get("store_address") or ""
    if business_address:
        footer_detail_lines.extend(_wrap_receipt_line(business_address, width=80))
    customer_service = branding.get("customer_service_phone") or sale.get("store_phone") or current_app.config.get("STORE_PHONE") or ""
    if customer_service:
        footer_detail_lines.extend(_wrap_receipt_line(f"Customer Service: {customer_service}", width=80))

    loyalty_lines = [
        str(line or "").strip().lstrip("- ").strip()
        for line in (sale.get("loyalty_summary_lines") or [])
        if str(line or "").strip()
    ]
    total_rows = [
        ("Subtotal", sale.get("subtotal_amount_label") or "Rp 0"),
        ("Diskon", sale.get("discount_amount_label") or "Rp 0"),
        ("Pajak", sale.get("tax_amount_label") or "Rp 0"),
        ("Total", sale.get("total_amount_label") or "Rp 0"),
        ("Bayar", sale.get("paid_amount_label") or "Rp 0"),
        ("Kembalian", sale.get("change_amount_label") or "Rp 0"),
    ]
    if sale.get("has_payment_breakdown") and sale.get("payment_breakdown_label"):
        total_rows.append(("Split Bayar", sale.get("payment_breakdown_label") or "-"))

    totals_height = 26.0 + (len(total_rows) * 19.0) + 18.0
    loyalty_height = 0.0
    if loyalty_lines:
        loyalty_height = 24.0 + 16.0 + (len(loyalty_lines) * 11.5) + 16.0
    note_height = 24.0 + 14.0 + (len(note_lines) * 11.6) + 16.0
    footer_height = 24.0 + (len(footer_title_lines) * 12.4) + (len(footer_detail_lines) * 11.2) + 18.0

    reserved_height = totals_height + note_height + footer_height + 20.0
    if loyalty_height:
        reserved_height += loyalty_height + 10.0

    return {
        "total_rows": total_rows,
        "totals_height": totals_height,
        "note_lines": note_lines,
        "note_height": note_height,
        "loyalty_lines": loyalty_lines,
        "loyalty_height": loyalty_height,
        "footer_title_lines": footer_title_lines,
        "footer_detail_lines": footer_detail_lines,
        "footer_height": footer_height,
        "reserved_height": reserved_height,
    }


def _build_receipt_pdf_pages(sale, summary_model):
    first_page_item_top = _estimate_receipt_pdf_first_page_item_top(sale)
    continuation_item_top = 706.0
    vertical_gap = 10.0
    bottom_limit = 40.0 + max(180.0, float(summary_model.get("reserved_height") or 0.0))
    item_blocks = _build_receipt_pdf_item_blocks(sale)

    pages = [
        {
            "is_first": True,
            "items": [],
            "cursor_top": first_page_item_top,
            "show_summary": False,
        }
    ]
    current_page = pages[0]

    for block in item_blocks:
        if current_page["cursor_top"] - float(block["height"]) < bottom_limit:
            current_page = {
                "is_first": False,
                "items": [],
                "cursor_top": continuation_item_top,
                "show_summary": False,
            }
            pages.append(current_page)
        placed_block = dict(block)
        placed_block["top"] = current_page["cursor_top"]
        current_page["items"].append(placed_block)
        current_page["cursor_top"] -= float(block["height"]) + vertical_gap

    pages[-1]["show_summary"] = True
    return pages


def _draw_receipt_pdf_logo(commands, logo_resource_name, logo_spec, x, y, width, height):
    if not (logo_resource_name and logo_spec):
        return
    logo_scale = min(width / float(logo_spec["width"]), height / float(logo_spec["height"]))
    logo_draw_width = float(logo_spec["width"]) * logo_scale
    logo_draw_height = float(logo_spec["height"]) * logo_scale
    logo_draw_x = float(x) + ((float(width) - logo_draw_width) / 2.0)
    logo_draw_y = float(y) + ((float(height) - logo_draw_height) / 2.0)
    commands.extend(
        [
            "q",
            f"{logo_draw_width:.2f} 0 0 {logo_draw_height:.2f} {logo_draw_x:.2f} {logo_draw_y:.2f} cm",
            f"/{logo_resource_name} Do",
            "Q",
        ]
    )


def _draw_receipt_pdf_first_page(commands, sale, branding, logo_resource_name=None, logo_spec=None):
    content_left = 40.0
    content_width = 515.0
    accent = branding.get("accent") or "#153e75"
    accent_dark = branding.get("accent_dark") or accent
    border = "#d7e2ec"
    ink = "#13263c"
    muted = "#6d7d8e"

    _append_pdf_rect(commands, 40.0, 804.0, 515.0, 4.0, fill_hex=accent, stroke_hex=accent, line_width=0.0)
    _append_pdf_rect(commands, 40.0, 708.0, 102.0, 86.0, fill_hex="#ffffff", stroke_hex=border, line_width=1.0)
    _draw_receipt_pdf_logo(commands, logo_resource_name, logo_spec, 52.0, 720.0, 78.0, 62.0)

    _append_pdf_text(commands, 164.0, 780.0, [branding.get("counter_label") or "iPOS Kasir"], font_name="F2", font_size=10.2, color_hex=accent, leading=12.0)
    _append_pdf_text(commands, 164.0, 758.0, [branding.get("business_name") or "ERP Core POS"], font_name="F2", font_size=22.0, color_hex=accent_dark, leading=24.0)
    _append_pdf_text(commands, 164.0, 736.0, [branding.get("receipt_title") or "Nota Pembelian iPOS"], font_name="F2", font_size=11.4, color_hex=accent, leading=13.0)
    _append_pdf_text(
        commands,
        164.0,
        719.0,
        [" | ".join(part for part in [str(sale.get("sale_date") or "").strip(), str(sale.get("created_time_label") or "").strip()] if part) or "-"],
        font_name="F1",
        font_size=9.6,
        color_hex=muted,
        leading=11.0,
    )

    chip_top = 685.0
    first_chip_width = _append_pdf_chip(
        commands,
        40.0,
        chip_top,
        sale.get("receipt_no") or "-",
        fill_hex=branding.get("accent_soft") or "#eef4fb",
        stroke_hex=border,
        text_hex=accent_dark,
    )
    _append_pdf_chip(
        commands,
        52.0 + first_chip_width,
        chip_top,
        sale.get("status_label") or sale.get("status") or "POSTED",
        fill_hex="#ffffff",
        stroke_hex=border,
        text_hex=accent_dark,
    )
    _append_pdf_text(commands, 40.0, 649.0, [sale.get("payment_method_label") or sale.get("payment_method") or "CASH"], font_name="F2", font_size=11.0, color_hex=ink)
    _append_pdf_text(commands, 40.0, 631.0, [sale.get("cashier_receipt_label") or sale.get("cashier_name") or "-"], font_name="F1", font_size=10.0, color_hex=ink)
    _append_pdf_line(commands, 40.0, 615.0, 555.0, 615.0, stroke_hex="#c4d3e0", line_width=0.9, dashed=True)

    grid_gap = 12.0
    row_gap = 10.0
    current_top = 602.0
    half_width = (content_width - grid_gap) / 2.0

    for row in _build_receipt_pdf_info_rows(sale):
        row_height = _measure_receipt_pdf_info_row_height(row)
        cursor_x = content_left
        for card in row:
            span = int(card.get("span") or 1)
            card_width = content_width if span >= 2 else half_width
            card_bottom = current_top - row_height
            _append_pdf_rect(
                commands,
                cursor_x,
                card_bottom,
                card_width,
                row_height,
                fill_hex="#ffffff",
                stroke_hex=border,
                line_width=0.95,
            )
            _append_pdf_text(commands, cursor_x + 14.0, current_top - 17.0, [card.get("label") or "-"], font_name="F2", font_size=8.2, color_hex=ink, leading=10.0)
            wrap_width = 34 if span == 1 else 78
            value_lines = _wrap_receipt_line(card.get("value"), width=wrap_width) or ["-"]
            _append_pdf_text(
                commands,
                cursor_x + 14.0,
                current_top - 35.0,
                value_lines,
                font_name="F2",
                font_size=10.8,
                color_hex=ink,
                leading=12.0,
            )
            cursor_x += card_width + grid_gap
        current_top -= row_height + row_gap


def _draw_receipt_pdf_continuation_page(commands, sale, branding, page_number, page_count, logo_resource_name=None, logo_spec=None):
    accent = branding.get("accent") or "#153e75"
    accent_dark = branding.get("accent_dark") or accent
    border = "#d7e2ec"
    muted = "#6d7d8e"

    _append_pdf_rect(commands, 40.0, 804.0, 515.0, 4.0, fill_hex=accent, stroke_hex=accent, line_width=0.0)
    _append_pdf_rect(commands, 40.0, 728.0, 76.0, 56.0, fill_hex="#ffffff", stroke_hex=border, line_width=0.95)
    _draw_receipt_pdf_logo(commands, logo_resource_name, logo_spec, 48.0, 736.0, 60.0, 40.0)
    _append_pdf_text(commands, 130.0, 777.0, [branding.get("business_name") or "ERP Core POS"], font_name="F2", font_size=17.0, color_hex=accent_dark, leading=19.0)
    _append_pdf_text(commands, 130.0, 757.0, [branding.get("receipt_title") or "Nota Pembelian iPOS"], font_name="F1", font_size=10.4, color_hex=accent, leading=12.0)
    _append_pdf_text(commands, 130.0, 742.0, [f"Receipt {sale.get('receipt_no') or '-'}"], font_name="F2", font_size=10.0, color_hex="#13263c", leading=12.0)
    _append_pdf_text(commands, 430.0, 776.0, [f"Halaman {page_number}/{page_count}"], font_name="F2", font_size=9.6, color_hex=muted, align="right", box_width=125.0)
    _append_pdf_line(commands, 40.0, 718.0, 555.0, 718.0, stroke_hex="#c4d3e0", line_width=0.9, dashed=True)


def _draw_receipt_pdf_items(commands, page):
    content_left = 40.0
    content_width = 515.0
    border = "#d7e2ec"
    ink = "#13263c"
    muted = "#6d7d8e"

    for item in page.get("items") or []:
        top = float(item.get("top") or 0.0)
        height = float(item.get("height") or 78.0)
        bottom = top - height
        _append_pdf_rect(commands, content_left, bottom, content_width, height, fill_hex="#fbfdff", stroke_hex=border, line_width=0.95)

        text_top = top - 18.0
        _append_pdf_text(commands, 56.0, text_top, item.get("title_lines") or ["Produk"], font_name="F2", font_size=11.2, color_hex=ink, leading=13.0)
        text_top -= (len(item.get("title_lines") or ["Produk"]) * 13.0) + 4.0
        _append_pdf_text(commands, 56.0, text_top, item.get("meta_lines") or ["-"], font_name="F1", font_size=9.6, color_hex=muted, leading=10.8)
        text_top -= (len(item.get("meta_lines") or ["-"]) * 10.8) + 4.0
        if item.get("detail_lines"):
            _append_pdf_text(commands, 56.0, text_top, item.get("detail_lines"), font_name="F1", font_size=9.0, color_hex=ink, leading=10.0)

        _append_pdf_text(commands, 56.0, bottom + 17.0, [item.get("qty_text") or "0"], font_name="F2", font_size=10.6, color_hex=ink)
        _append_pdf_text(
            commands,
            56.0,
            bottom + 17.0,
            [item.get("price_text") or "Rp 0"],
            font_name="F2",
            font_size=11.0,
            color_hex=ink,
            align="right",
            box_width=483.0,
        )


def _draw_receipt_pdf_summary(commands, sale, branding, page, summary_model):
    accent = branding.get("accent") or "#153e75"
    border = "#d7e2ec"
    ink = "#13263c"
    content_left = 40.0
    content_width = 515.0
    section_gap = 10.0
    section_top = float(page.get("cursor_top") or 300.0)

    totals_height = float(summary_model.get("totals_height") or 160.0)
    totals_bottom = section_top - totals_height
    _append_pdf_rect(commands, content_left, totals_bottom, content_width, totals_height, fill_hex="#ffffff", stroke_hex=border, line_width=0.95)

    row_y = section_top - 24.0
    for label, value in summary_model.get("total_rows") or []:
        is_total = str(label).strip().lower() == "total"
        row_color = accent if is_total else ink
        font_name = "F2" if is_total else "F1"
        font_size = 12.4 if is_total else 10.8
        _append_pdf_text(commands, 56.0, row_y, [label], font_name=font_name, font_size=font_size, color_hex=row_color)
        _append_pdf_text(commands, 56.0, row_y, [value], font_name="F2", font_size=font_size, color_hex=row_color, align="right", box_width=483.0)
        row_y -= 19.0

    section_top = totals_bottom - section_gap

    if summary_model.get("loyalty_lines"):
        loyalty_height = float(summary_model.get("loyalty_height") or 0.0)
        loyalty_bottom = section_top - loyalty_height
        _append_pdf_rect(commands, content_left, loyalty_bottom, content_width, loyalty_height, fill_hex="#ffffff", stroke_hex=border, line_width=0.95)
        _append_pdf_text(
            commands,
            56.0,
            section_top - 18.0,
            [sale.get("loyalty_summary_title") or "UPDATE CRM CUSTOMER"],
            font_name="F2",
            font_size=10.2,
            color_hex=ink,
            leading=12.0,
        )
        _append_pdf_text(
            commands,
            56.0,
            section_top - 38.0,
            summary_model.get("loyalty_lines"),
            font_name="F1",
            font_size=9.4,
            color_hex="#6d7d8e",
            leading=11.2,
        )
        section_top = loyalty_bottom - section_gap

    note_height = float(summary_model.get("note_height") or 0.0)
    note_bottom = section_top - note_height
    _append_pdf_rect(commands, content_left, note_bottom, content_width, note_height, fill_hex="#ffffff", stroke_hex=border, line_width=0.95)
    _append_pdf_text(commands, 56.0, section_top - 17.0, ["CATATAN"], font_name="F2", font_size=8.8, color_hex=ink, leading=10.0)
    _append_pdf_text(commands, 56.0, section_top - 34.0, summary_model.get("note_lines") or ["-"], font_name="F1", font_size=9.6, color_hex=ink, leading=11.2)
    section_top = note_bottom - section_gap

    footer_height = float(summary_model.get("footer_height") or 0.0)
    footer_bottom = section_top - footer_height
    _append_pdf_rect(commands, content_left, footer_bottom, content_width, footer_height, fill_hex="#ffffff", stroke_hex=border, line_width=0.95)
    _append_pdf_text(
        commands,
        56.0,
        section_top - 18.0,
        summary_model.get("footer_title_lines") or ["-"],
        font_name="F2",
        font_size=10.6,
        color_hex=accent,
        leading=12.4,
    )
    _append_pdf_text(
        commands,
        56.0,
        section_top - (22.0 + (len(summary_model.get("footer_title_lines") or ["-"]) * 12.4)),
        summary_model.get("footer_detail_lines") or [],
        font_name="F1",
        font_size=9.6,
        color_hex=ink,
        leading=11.2,
    )


def _build_page_stream(page, sale=None, branding=None, logo_resource_name=None, logo_spec=None, page_number=1, page_count=1):
    sale = sale or {}
    branding = branding or {}
    summary_model = _build_receipt_pdf_summary_model(sale, branding)
    commands = []

    if page.get("is_first"):
        _draw_receipt_pdf_first_page(commands, sale, branding, logo_resource_name=logo_resource_name, logo_spec=logo_spec)
    else:
        _draw_receipt_pdf_continuation_page(
            commands,
            sale,
            branding,
            page_number,
            page_count,
            logo_resource_name=logo_resource_name,
            logo_spec=logo_spec,
        )

    _draw_receipt_pdf_items(commands, page)
    if page.get("show_summary"):
        _draw_receipt_pdf_summary(commands, sale, branding, page, summary_model)

    _append_pdf_text(
        commands,
        430.0,
        24.0,
        [f"Halaman {page_number}/{page_count}"],
        font_name="F1",
        font_size=8.6,
        color_hex="#8191a2",
        align="right",
        box_width=125.0,
    )
    return "\n".join(commands).encode("latin-1", "replace")


def _build_pdf_document(sale=None):
    sale = sale or {}
    branding = sale.get("receipt_brand") or build_pos_receipt_branding(sale)
    summary_model = _build_receipt_pdf_summary_model(sale, branding)
    pages = _build_receipt_pdf_pages(sale, summary_model)
    logo_spec = _load_pdf_logo_spec(branding)
    logo_object_number = None

    objects = [
        b"",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    if logo_spec:
        logo_object_number = len(objects) + 1
        objects.append(
            (
                f"<< /Type /XObject /Subtype /Image /Width {logo_spec['width']} /Height {logo_spec['height']} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(logo_spec['bytes'])} >>\n"
                "stream\n"
            ).encode("ascii")
            + logo_spec["bytes"]
            + b"\nendstream"
        )
    page_object_numbers = []
    page_count = len(pages)

    for page_index, page in enumerate(pages, start=1):
        stream_bytes = _build_page_stream(
            page,
            sale=sale,
            branding=branding,
            logo_resource_name="ImBrand" if logo_spec else None,
            logo_spec=logo_spec,
            page_number=page_index,
            page_count=page_count,
        )
        content_object_number = len(objects) + 1
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream_bytes), stream_bytes))
        page_object_number = len(objects) + 1
        resources = "/Font << /F1 3 0 R /F2 4 0 R >>"
        if logo_object_number:
            resources += f" /XObject << /ImBrand {logo_object_number} 0 R >>"
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << {resources} >> /Contents {content_object_number} 0 R >>"
            ).encode("ascii")
        )
        page_object_numbers.append(page_object_number)

    page_kids = " ".join(f"{object_number} 0 R" for object_number in page_object_numbers)
    objects[1] = f"<< /Type /Pages /Count {len(page_object_numbers)} /Kids [{page_kids}] >>".encode("ascii")
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        if not obj.endswith(b"\n"):
            output.extend(b"\n")
        output.extend(b"endobj\n")

    xref_position = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_position}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(output)


def generate_pos_receipt_pdf(sale):
    sale = dict(sale or {})
    sale.setdefault("receipt_brand", build_pos_receipt_branding(sale))
    sale.setdefault("warehouse_receipt_label", sale["receipt_brand"].get("homebase_label") or "-")
    receipt_no = str(sale.get("receipt_no") or sale.get("id") or uuid4().hex).strip()
    safe_receipt = re.sub(r"[^A-Za-z0-9_-]+", "-", receipt_no).strip("-") or f"sale-{uuid4().hex[:8]}"
    file_name = f"receipt-{safe_receipt}-{uuid4().hex[:8]}.pdf"
    folder = get_pos_receipt_pdf_folder()
    absolute_path = os.path.join(folder, file_name)
    renderer_mode = str(
        current_app.config.get("POS_RECEIPT_PDF_RENDERER")
        or os.getenv("POS_RECEIPT_PDF_RENDERER")
        or "auto"
    ).strip().lower()

    if renderer_mode != "legacy":
        rendered, render_error = _render_pos_receipt_pdf_via_browser(sale, absolute_path)
        if rendered:
            return {
                "file_name": file_name,
                "absolute_path": absolute_path,
                "relative_path": file_name,
                "public_url": build_pos_receipt_pdf_public_url(file_name),
                "size_bytes": os.path.getsize(absolute_path),
            }
        current_app.logger.warning(
            "POS receipt HTML PDF render fallback triggered for %s: %s",
            receipt_no,
            render_error,
        )

    pdf_bytes = _build_pdf_document(sale=sale)
    with open(absolute_path, "wb") as file_handle:
        file_handle.write(pdf_bytes)

    return {
        "file_name": file_name,
        "absolute_path": absolute_path,
        "relative_path": file_name,
        "public_url": build_pos_receipt_pdf_public_url(file_name),
        "size_bytes": len(pdf_bytes),
    }
