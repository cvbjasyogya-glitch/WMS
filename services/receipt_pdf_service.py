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
        "logo_relative_path": "",
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

    return {
        "sale": safe_sale,
        "receipt_brand": receipt_brand,
        "store_name": store_name,
        "store_phone": store_phone,
        "receipt_layout": normalized_receipt_layout,
        "receipt_copy": normalized_receipt_copy,
        "receipt_copy_label": "Copy Toko" if normalized_receipt_copy == "store" else "Copy Customer",
        "receipt_followup_copy": normalized_followup_copy,
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

    renderer_layout = _normalize_receipt_layout(
        current_app.config.get("POS_RECEIPT_PDF_LAYOUT") or os.getenv("POS_RECEIPT_PDF_LAYOUT") or "a4",
        default="a4",
    )
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
    logo_url = f"/{logo_relative_path}" if logo_relative_path else ""
    logo_pdf_path = ""
    if logo_relative_path:
        candidate_path = os.path.join(current_app.root_path, *logo_relative_path.split("/"))
        if os.path.exists(candidate_path):
            logo_pdf_path = candidate_path

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
        f"Terima kasih sudah berbelanja di {business_name}.",
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


def _paginate_lines(lines, max_lines=54):
    pages = []
    current_page = []
    for line in lines:
        current_page.append(line)
        if len(current_page) >= max_lines:
            pages.append(current_page)
            current_page = []
    if current_page:
        pages.append(current_page)
    return pages or [["NOTA PEMBELIAN IPOS"]]


def _build_page_stream(lines, branding=None, logo_resource_name=None, logo_spec=None):
    branding = branding or {}
    accent_red, accent_green, accent_blue = _hex_to_pdf_rgb(branding.get("accent") or "#153e75")
    brand_name = branding.get("business_name") or "ERP Core POS"
    counter_label = branding.get("counter_label") or "iPOS Kasir"
    homebase_label = branding.get("homebase_label") or "-"
    brand_text_x = 168 if (logo_resource_name and logo_spec) else 40

    commands = [
        f"{accent_red} {accent_green} {accent_blue} rg",
        "36 808 523 4 re f",
    ]

    if logo_resource_name and logo_spec:
        logo_box_width = 116
        logo_box_height = 74
        logo_scale = min(logo_box_width / float(logo_spec["width"]), logo_box_height / float(logo_spec["height"]))
        logo_draw_width = logo_spec["width"] * logo_scale
        logo_draw_height = logo_spec["height"] * logo_scale
        logo_draw_x = 40 + ((logo_box_width - logo_draw_width) / 2)
        logo_draw_y = 736 + ((logo_box_height - logo_draw_height) / 2)
        commands.extend(
            [
                "q",
                f"{logo_draw_width:.2f} 0 0 {logo_draw_height:.2f} {logo_draw_x:.2f} {logo_draw_y:.2f} cm",
                f"/{logo_resource_name} Do",
                "Q",
            ]
        )

    commands.extend(
        [
            "BT",
            f"{accent_red} {accent_green} {accent_blue} rg",
            "/F1 16 Tf",
            f"1 0 0 1 {brand_text_x} 790 Tm",
            f"({_escape_pdf_text(brand_name)}) Tj",
            "/F1 10.5 Tf",
            f"1 0 0 1 {brand_text_x} 773 Tm",
            f"({_escape_pdf_text(counter_label)}) Tj",
            "0.1059 0.1529 0.2275 rg",
            "/F1 10 Tf",
            f"1 0 0 1 {brand_text_x} 758 Tm",
            f"({_escape_pdf_text(homebase_label)}) Tj",
            "/F1 10.4 Tf",
            "1 0 0 1 40 714 Tm",
        ]
    )

    y_position = 714
    line_height = 12.2
    for index, line in enumerate(lines):
        if index > 0:
            y_position -= line_height
            commands.append(f"1 0 0 1 40 {y_position:.1f} Tm")
        commands.append(f"({_escape_pdf_text(line)}) Tj")

    commands.append("ET")
    return "\n".join(commands).encode("latin-1", "replace")


def _build_pdf_document(lines, sale=None):
    pages = _paginate_lines(lines)
    sale = sale or {}
    branding = sale.get("receipt_brand") or build_pos_receipt_branding(sale)
    logo_spec = _load_pdf_logo_spec(branding)
    logo_object_number = None

    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
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

    for page_lines in pages:
        stream_bytes = _build_page_stream(
            page_lines,
            branding=branding,
            logo_resource_name="ImBrand" if logo_spec else None,
            logo_spec=logo_spec,
        )
        content_object_number = len(objects) + 1
        objects.append(
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream_bytes), stream_bytes)
        )
        page_object_number = len(objects) + 1
        resources = "/Font << /F1 3 0 R >>"
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

    pdf_bytes = _build_pdf_document(_build_receipt_lines(sale), sale=sale)
    with open(absolute_path, "wb") as file_handle:
        file_handle.write(pdf_bytes)

    return {
        "file_name": file_name,
        "absolute_path": absolute_path,
        "relative_path": file_name,
        "public_url": build_pos_receipt_pdf_public_url(file_name),
        "size_bytes": len(pdf_bytes),
    }
