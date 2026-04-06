import os
import re
import textwrap
from datetime import datetime
from uuid import uuid4

from flask import current_app, has_request_context, request


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

    if has_request_context():
        return str(request.host_url or "").strip().rstrip("/")

    canonical_host = str(current_app.config.get("CANONICAL_HOST") or "").strip()
    if canonical_host:
        scheme = str(current_app.config.get("CANONICAL_SCHEME") or current_app.config.get("PREFERRED_URL_SCHEME") or "https").strip()
        return f"{scheme}://{canonical_host}".rstrip("/")

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


def _wrap_receipt_line(value, width=74):
    text = _normalize_ascii_text(value)
    if not text:
        return [""]
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [text]


def _build_receipt_lines(sale):
    sale = sale or {}
    lines = [
        "NOTA PENJUALAN POS",
        "",
        f"Receipt : {_normalize_ascii_text(sale.get('receipt_no') or '-')}",
        f"Tanggal : {_normalize_ascii_text(sale.get('created_datetime_label') or sale.get('sale_date') or '-')}",
        f"Gudang  : {_normalize_ascii_text(sale.get('warehouse_name') or '-')}",
        f"Kasir   : {_normalize_ascii_text(sale.get('cashier_name') or sale.get('cashier_username') or '-')}",
        f"Customer: {_normalize_ascii_text(sale.get('customer_name') or 'Walk-in Customer')}",
        f"WA      : {_normalize_ascii_text(sale.get('customer_phone_label') or sale.get('customer_phone') or '-')}",
        f"Status  : {_normalize_ascii_text(sale.get('status_label') or sale.get('status') or 'POSTED')}",
        f"Bayar   : {_normalize_ascii_text(sale.get('payment_method_label') or sale.get('payment_method') or 'CASH')}",
        "",
        "-" * 76,
        "ITEM",
        "-" * 76,
    ]

    for index, item in enumerate(sale.get("items") or [], start=1):
        item_name = (
            f"{index}. {item.get('sku') or '-'} | "
            f"{item.get('product_name') or 'Produk'} | "
            f"{item.get('variant_name') or 'default'}"
        )
        lines.extend(_wrap_receipt_line(item_name))
        active_qty = int(item.get("active_qty") or item.get("qty") or 0)
        active_total_label = item.get("active_line_total_label") or item.get("line_total_label") or "Rp 0"
        unit_price_label = item.get("unit_price_label") or "Rp 0"
        lines.append(f"    Qty aktif {active_qty} x {unit_price_label} = {active_total_label}")
        if int(item.get("void_qty") or 0) > 0:
            lines.append(
                f"    Void {int(item.get('void_qty') or 0)} | {item.get('void_amount_label') or 'Rp 0'}"
            )
        if item.get("void_note"):
            for wrapped_line in _wrap_receipt_line(f"    Catatan void: {item.get('void_note')}"):
                lines.append(wrapped_line)
        lines.append("")

    lines.extend(
        [
            "-" * 76,
            f"Subtotal : {_normalize_ascii_text(sale.get('subtotal_amount_label') or 'Rp 0')}",
            (
                f"Potongan : {_normalize_ascii_text(sale.get('discount_amount_label') or 'Rp 0')}"
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

    if sale.get("note"):
        lines.append("")
        lines.extend(_wrap_receipt_line(f"Catatan: {sale.get('note')}"))

    lines.extend(
        [
            "",
            "-" * 76,
            f"Generated backend: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "ERP Core Mataram Sports",
        ]
    )
    return lines


def _paginate_lines(lines, max_lines=46):
    pages = []
    current_page = []
    for line in lines:
        current_page.append(line)
        if len(current_page) >= max_lines:
            pages.append(current_page)
            current_page = []
    if current_page:
        pages.append(current_page)
    return pages or [["NOTA PENJUALAN POS"]]


def _build_page_stream(lines):
    y_position = 800
    line_height = 15
    commands = [
        "BT",
        "/F1 11 Tf",
        "1 0 0 1 40 800 Tm",
    ]

    for index, line in enumerate(lines):
        if index == 0:
            commands.append("/F1 15 Tf")
        elif index == 1:
            commands.append("/F1 11 Tf")
        if index > 0:
            y_position -= line_height
            commands.append(f"1 0 0 1 40 {y_position} Tm")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", "replace")


def _build_pdf_document(lines):
    pages = _paginate_lines(lines)
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_object_numbers = []

    for page_lines in pages:
        stream_bytes = _build_page_stream(page_lines)
        content_object_number = len(objects) + 1
        objects.append(
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream_bytes), stream_bytes)
        )
        page_object_number = len(objects) + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_object_number} 0 R >>"
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
    sale = sale or {}
    receipt_no = str(sale.get("receipt_no") or sale.get("id") or uuid4().hex).strip()
    safe_receipt = re.sub(r"[^A-Za-z0-9_-]+", "-", receipt_no).strip("-") or f"sale-{uuid4().hex[:8]}"
    file_name = f"receipt-{safe_receipt}-{uuid4().hex[:8]}.pdf"
    folder = get_pos_receipt_pdf_folder()
    absolute_path = os.path.join(folder, file_name)

    pdf_bytes = _build_pdf_document(_build_receipt_lines(sale))
    with open(absolute_path, "wb") as file_handle:
        file_handle.write(pdf_bytes)

    return {
        "file_name": file_name,
        "absolute_path": absolute_path,
        "relative_path": file_name,
        "public_url": build_pos_receipt_pdf_public_url(file_name),
        "size_bytes": len(pdf_bytes),
    }
