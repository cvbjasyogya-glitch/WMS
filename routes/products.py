import re
from urllib.parse import urlencode

from flask import Blueprint, request, redirect, jsonify, flash, session
from database import get_db
from services.event_notification_policy import get_event_notification_policy
from services.notification_service import notify_operational_event, notify_roles
from services.pagination import build_pagination_state
from services.rbac import has_permission, is_scoped_role
from services.product_master_approval_service import (
    can_queue_product_master_approval,
    find_pending_product_delete_approvals,
    queue_product_delete_approvals,
)
from services.whatsapp_service import send_role_based_notification
from services.stock_service import add_stock
import csv
from importlib import import_module
import json
import uuid
from io import BytesIO, StringIO
import xml.etree.ElementTree as ET
import zipfile

products_bp = Blueprint("products", __name__, url_prefix="/products")

IMPORT_PROGRESS = {}
PRODUCT_STUDIO_REDIRECT_PATH = "/stock/"


def _can_manage_product_master():
    return has_permission(session.get("role"), "manage_product_master")


def _product_master_request_warehouse_id():
    try:
        return int(session.get("warehouse_id") or 0)
    except (TypeError, ValueError):
        return 0


def _queue_product_delete_requests(db, product_ids):
    warehouse_id = _product_master_request_warehouse_id()
    approval_ids = queue_product_delete_approvals(
        db,
        warehouse_id=warehouse_id,
        requested_by=session.get("user_id"),
        product_ids=product_ids,
    )
    if not approval_ids:
        raise ValueError("Produk tidak ditemukan atau sudah tidak tersedia.")

    try:
        delete_policy = get_event_notification_policy("inventory.product_delete_approval_requested")
        notify_roles(
            delete_policy["roles"],
            "Permintaan Hapus Master Produk",
            f"Ada {len(approval_ids)} produk yang menunggu approval hapus master.",
            warehouse_id=warehouse_id,
            usernames=delete_policy["usernames"],
            user_ids=delete_policy["user_ids"],
            send_whatsapp_channel=False,
            category="approval",
            link_url="/approvals",
            source_type="approval_queue",
        )
    except Exception as exc:
        print("PRODUCT DELETE APPROVAL NOTIFY ERROR:", exc)

    try:
        warehouse_row = None
        if warehouse_id:
            warehouse_row = db.execute("SELECT name FROM warehouses WHERE id=?", (warehouse_id,)).fetchone()
        send_role_based_notification(
            "inventory.product_delete_approval_requested",
            {
                "warehouse_id": warehouse_id,
                "warehouse_name": ((warehouse_row["name"] if warehouse_row else "") or f"Gudang {warehouse_id or '-'}").strip(),
                "requester_name": session.get("username") or "Admin",
                "item_count": len(approval_ids),
                "link_url": "/approvals",
            },
        )
    except Exception as exc:
        print("PRODUCT DELETE APPROVAL WHATSAPP ERROR:", exc)

    return approval_ids


def _products_json_error(message, status_code=403, **payload):
    response = {"status": "error", "message": message}
    response.update(payload)
    return jsonify(response), status_code


def _require_product_master_access(json_mode=False):
    if _can_manage_product_master():
        return None

    message = "Akses master produk hanya tersedia untuk admin, leader, owner, atau super admin."
    if json_mode or _is_ajax_request():
        return _products_json_error(message, 403)

    flash(message, "error")
    return redirect(f"{PRODUCT_STUDIO_REDIRECT_PATH}?workspace=products")


def _is_ajax_request():
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or "")
    )


def _products_success_response(message, **payload):
    if _is_ajax_request():
        response = {"status": "success", "message": message}
        response.update(payload)
        return jsonify(response), 200

    flash(message, "success")
    return redirect(f"{PRODUCT_STUDIO_REDIRECT_PATH}?workspace=products")


def _products_error_response(message, status_code=400, **payload):
    if _is_ajax_request():
        response = {"status": "error", "message": message}
        response.update(payload)
        return jsonify(response), status_code

    flash(message, "error")
    return redirect(f"{PRODUCT_STUDIO_REDIRECT_PATH}?workspace=products")


def _to_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_picker_query(raw_query):
    return " ".join(str(raw_query or "").strip().split())


def _normalize_picker_compact_query(raw_query):
    return re.sub(r"[^a-z0-9]+", "", str(raw_query or "").strip().lower())


def _build_picker_compact_expression(expression):
    compact_expression = f"lower({expression})"
    for needle in (" ", "-", "/", "_", ".", "+", "(", ")", ","):
        compact_expression = f"replace({compact_expression}, '{needle}', '')"
    return compact_expression


def _get_picker_search_fields():
    return [
        "p.sku",
        "p.name",
        "COALESCE(c.name, '')",
        "COALESCE(v.variant, '')",
        "COALESCE(v.variant_code, '')",
        "COALESCE(v.color, '')",
        "COALESCE(v.gtin, '')",
    ]


def _build_picker_search_conditions(query):
    if not query:
        return "", []

    search_fields = _get_picker_search_fields()
    compact_search_fields = [_build_picker_compact_expression(field) for field in search_fields]
    clauses = []
    params = []
    for term in query.split():
        raw_token = f"%{term}%"
        compact_term = _normalize_picker_compact_query(term)
        clauses.append(
            "("
            + " OR ".join([f"{field} LIKE ?" for field in search_fields] + ([f"{field} LIKE ?" for field in compact_search_fields] if compact_term else []))
            + ")"
        )
        params.extend([raw_token] * len(search_fields))
        if compact_term:
            params.extend([f"%{compact_term}%"] * len(compact_search_fields))

    return " AND ".join(clauses), params


def _build_picker_order_by(query, mode):
    if query:
        compact_query = _normalize_picker_compact_query(query)
        if not compact_query:
            exact_token = query.lower()
            prefix_token = f"{query.lower()}%"
            contains_token = f"%{query.lower()}%"
            return (
                """
                CASE
                    WHEN lower(p.sku) = ? THEN 0
                    WHEN lower(COALESCE(v.gtin, '')) = ? THEN 1
                    WHEN lower(COALESCE(v.variant_code, '')) = ? THEN 2
                    WHEN lower(p.name) = ? THEN 3
                    WHEN lower(COALESCE(v.variant, '')) = ? THEN 4
                    WHEN lower(COALESCE(v.color, '')) = ? THEN 5
                    WHEN lower(COALESCE(c.name, '')) = ? THEN 6
                    WHEN lower(p.sku) LIKE ? THEN 7
                    WHEN lower(COALESCE(v.gtin, '')) LIKE ? THEN 8
                    WHEN lower(COALESCE(v.variant_code, '')) LIKE ? THEN 9
                    WHEN lower(p.name) LIKE ? THEN 10
                    WHEN lower(COALESCE(v.variant, '')) LIKE ? THEN 11
                    WHEN lower(COALESCE(v.color, '')) LIKE ? THEN 12
                    WHEN lower(COALESCE(c.name, '')) LIKE ? THEN 13
                    WHEN lower(
                        p.sku || ' ' || p.name || ' ' || COALESCE(c.name, '') || ' ' ||
                        COALESCE(v.variant, '') || ' ' || COALESCE(v.variant_code, '') || ' ' ||
                        COALESCE(v.color, '') || ' ' || COALESCE(v.gtin, '')
                    ) LIKE ? THEN 14
                    ELSE 15
                END,
                CASE WHEN COALESCE(s.qty, 0) > 0 THEN 0 ELSE 1 END,
                COALESCE(s.qty, 0) DESC,
                p.name COLLATE NOCASE ASC,
                CASE WHEN lower(v.variant) = 'default' THEN 0 ELSE 1 END,
                v.variant COLLATE NOCASE ASC
                """,
                [exact_token] * 7 + [prefix_token] * 7 + [contains_token],
            )
        search_fields = _get_picker_search_fields()
        compact_fields = [_build_picker_compact_expression(field) for field in search_fields]
        combined_compact_field = _build_picker_compact_expression(
            "p.sku || ' ' || p.name || ' ' || COALESCE(c.name, '') || ' ' || "
            "COALESCE(v.variant, '') || ' ' || COALESCE(v.variant_code, '') || ' ' || "
            "COALESCE(v.color, '') || ' ' || COALESCE(v.gtin, '')"
        )
        exact_token = compact_query
        prefix_token = f"{compact_query}%"
        contains_token = f"%{compact_query}%"
        exact_checks = "\n".join(
            f"                WHEN {field} = ? THEN {index}"
            for index, field in enumerate(compact_fields)
        )
        prefix_checks = "\n".join(
            f"                WHEN {field} LIKE ? THEN {index + len(compact_fields)}"
            for index, field in enumerate(compact_fields)
        )
        combined_rank = len(compact_fields) * 2
        return (
            f"""
            CASE
{exact_checks}
{prefix_checks}
                WHEN {combined_compact_field} LIKE ? THEN {combined_rank}
                ELSE {combined_rank + 1}
            END,
            CASE WHEN COALESCE(s.qty, 0) > 0 THEN 0 ELSE 1 END,
            COALESCE(s.qty, 0) DESC,
            p.name COLLATE NOCASE ASC,
            CASE WHEN lower(v.variant) = 'default' THEN 0 ELSE 1 END,
            v.variant COLLATE NOCASE ASC
            """,
            [exact_token] * len(compact_fields) + [prefix_token] * len(compact_fields) + [contains_token],
        )

    if mode == "outbound":
        return (
            """
            CASE WHEN COALESCE(s.qty, 0) > 0 THEN 0 ELSE 1 END,
            COALESCE(s.qty, 0) DESC,
            p.name COLLATE NOCASE ASC,
            CASE WHEN lower(v.variant) = 'default' THEN 0 ELSE 1 END,
            v.variant COLLATE NOCASE ASC
            """,
            [],
        )

    return (
        """
        p.name COLLATE NOCASE ASC,
        CASE WHEN lower(v.variant) = 'default' THEN 0 ELSE 1 END,
        v.variant COLLATE NOCASE ASC
        """,
        [],
    )


def _to_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        if isinstance(value, bool):
            return int(value)
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return default


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_unit_label(value):
    cleaned = " ".join(str(value or "").strip().split())
    return cleaned or "pcs"


def _normalize_variant_mode(value):
    mode = str(value or "").strip().lower()
    return "non_variant" if mode == "non_variant" else "variant"


def _normalize_variant_name(value):
    value = (value or "").strip()
    if value.lower() in {"", "-", "default", "n/a", "na", "none"}:
        return "default"
    return value


def _normalize_variant_color(value):
    return " ".join(str(value or "").strip().split())


def _compose_variant_label(variant_value, color_value=""):
    normalized_variant = _normalize_variant_name(variant_value)
    normalized_color = _normalize_variant_color(color_value)

    if normalized_color:
        if normalized_variant == "default":
            return normalized_color
        return f"{normalized_variant} / {normalized_color}"

    return normalized_variant


def _row_has_content(row):
    return any(str(value or "").strip() for value in row.values())


def _merge_variant_rows(rows):
    merged = {}
    order = []

    for row in rows:
        key = row["variant"]
        if key not in merged:
            merged[key] = dict(row)
            order.append(key)
            continue

        merged_row = merged[key]
        merged_row["qty"] += row["qty"]
        merged_row["price_retail"] = row["price_retail"]
        merged_row["price_discount"] = row["price_discount"]
        merged_row["price_nett"] = row["price_nett"]
        if row["color"]:
            merged_row["color"] = row["color"]

        if row["variant_code"]:
            merged_row["variant_code"] = row["variant_code"]

        if row["no_gtin"]:
            merged_row["no_gtin"] = 1
            merged_row["gtin"] = ""
        elif row["gtin"]:
            merged_row["gtin"] = row["gtin"]
            merged_row["no_gtin"] = 0

    return [merged[key] for key in order]


def _infer_variant_mode(variant_rows, requested_mode=None):
    safe_mode = _normalize_variant_mode(requested_mode)
    if requested_mode:
        return safe_mode

    if len(variant_rows) == 1 and variant_rows[0]["variant"] == "default":
        return "non_variant"
    return "variant"


def _build_variant_rows(form, variant_mode="variant"):
    raw_payload = (form.get("variant_rows_json") or "").strip()
    safe_variant_mode = _normalize_variant_mode(variant_mode)

    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Format variasi manual tidak valid") from exc

        if not isinstance(payload, list):
            raise ValueError("Format variasi manual tidak valid")

        rows = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            raw_variant = str(item.get("variant") or "").strip()
            raw_qty = item.get("qty")
            raw_price_retail = item.get("price_retail")
            raw_price_discount = item.get("price_discount")
            raw_price_nett = item.get("price_nett")
            variant_code = str(item.get("variant_code") or "").strip()
            color = _normalize_variant_color(item.get("color"))
            gtin = str(item.get("gtin") or "").strip()
            no_gtin = 1 if _to_bool(item.get("no_gtin")) else 0

            if not any([
                raw_variant,
                color,
                str(raw_qty or "").strip(),
                str(raw_price_retail or "").strip(),
                str(raw_price_discount or "").strip(),
                str(raw_price_nett or "").strip(),
                variant_code,
                gtin,
                no_gtin,
            ]):
                continue

            rows.append({
                "variant": _compose_variant_label(raw_variant, color),
                "color": color,
                "qty": _to_int(raw_qty, 0),
                "price_retail": _to_float(raw_price_retail),
                "price_discount": _to_float(raw_price_discount),
                "price_nett": _to_float(raw_price_nett),
                "variant_code": variant_code,
                "gtin": "" if no_gtin else gtin,
                "no_gtin": no_gtin,
            })

        merged_rows = _merge_variant_rows(rows)
        if safe_variant_mode == "non_variant":
            if len(merged_rows) > 1:
                raise ValueError("Produk non-variant hanya boleh memiliki satu baris stok.")
            if not merged_rows:
                return []
            return [{
                **merged_rows[0],
                "variant": "default",
                "color": "",
            }]
        return merged_rows

    variants = form.get("variants", "")
    qty = _to_int(form.get("qty"), 0)
    price_retail = _to_float(form.get("price_retail"))
    price_discount = _to_float(form.get("price_discount"))
    price_nett = _to_float(form.get("price_nett"))
    variant_list = [v.strip() for v in variants.split(",") if v.strip()] or ["default"]
    if safe_variant_mode == "non_variant":
        variant_list = ["default"]

    return _merge_variant_rows([
        {
            "variant": _compose_variant_label(variant),
            "color": "",
            "qty": qty,
            "price_retail": price_retail,
            "price_discount": price_discount,
            "price_nett": price_nett,
            "variant_code": "",
            "gtin": "",
            "no_gtin": 0,
        }
        for variant in variant_list
    ])


def _resolve_products_warehouse(db):
    role = session.get("role")

    if is_scoped_role(role):
        warehouse_id = session.get("warehouse_id") or 1
    else:
        try:
            warehouse_id = int(request.args.get("warehouse") or session.get("warehouse_id") or 1)
        except (TypeError, ValueError):
            warehouse_id = 1

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    if warehouse:
        return warehouse["id"]

    fallback = db.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()
    return fallback["id"] if fallback else 1


def _resolve_import_warehouse(db, raw_warehouse_id, default_warehouse_id):
    role = session.get("role")
    if is_scoped_role(role):
        return session.get("warehouse_id") or default_warehouse_id

    warehouse_id = _to_int(raw_warehouse_id, default_warehouse_id)
    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    return warehouse["id"] if warehouse else default_warehouse_id


def build_product_studio_context(
    db,
    warehouse_id,
    search="",
    page=1,
    base_path="/stock/",
    extra_params=None,
    page_param="product_page",
):
    search = (search or "").strip()

    try:
        page = int(page or 1)
        if page < 1:
            page = 1
    except (TypeError, ValueError):
        page = 1

    limit = 10
    offset = (page - 1) * limit
    search_param = f"%{search}%"

    data_raw = db.execute(
        """
        SELECT
            p.id,
            p.sku,
            p.name,
            COALESCE(NULLIF(TRIM(p.unit_label), ''), 'pcs') AS unit_label,
            COALESCE(NULLIF(TRIM(p.variant_mode), ''), 'variant') AS variant_mode,
            COALESCE(c.name, '-') as category,
            COALESCE((
                SELECT SUM(qty)
                FROM stock
                WHERE product_id = p.id AND warehouse_id = ?
            ),0) as qty,
            MIN(b.created_at) as first_in,
            COALESCE(
                CAST((JULIANDAY('now') - JULIANDAY(MIN(b.created_at))) AS INTEGER),
                0
            ) as age_days
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN stock_batches b
            ON p.id = b.product_id
            AND b.warehouse_id = ?
            AND b.remaining_qty > 0
        WHERE
            (? = '' OR
             p.name LIKE ? OR
             p.sku LIKE ? OR
             c.name LIKE ?)
        GROUP BY p.id
        ORDER BY age_days DESC
        LIMIT ? OFFSET ?
        """,
        (
            warehouse_id,
            warehouse_id,
            search,
            search_param,
            search_param,
            search_param,
            limit,
            offset,
        ),
    ).fetchall()

    total = db.execute(
        """
        SELECT COUNT(*) as total
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE
            (? = '' OR
             p.name LIKE ? OR
             p.sku LIKE ? OR
             c.name LIKE ?)
        """,
        (
            search,
            search_param,
            search_param,
            search_param,
        ),
    ).fetchone()["total"]

    total_pages = max(1, (total + limit - 1) // limit)
    pagination_params = dict(extra_params or {})
    pagination_params["product_search"] = search

    pagination = build_pagination_state(
        base_path,
        page,
        total_pages,
        pagination_params,
        group_size=5,
        page_param=page_param,
    )

    return {
        "data": [dict(r) for r in data_raw],
        "search": search,
        "page": page,
        "total_pages": total_pages,
        "total_items": total,
        "pagination": pagination,
    }


def _resolve_picker_warehouse(db, raw_warehouse_id):
    default_warehouse_id = session.get("warehouse_id") or 1
    fallback = db.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()
    if fallback:
        default_warehouse_id = fallback["id"]

    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id") or default_warehouse_id

    warehouse_id = _to_int(raw_warehouse_id, session.get("warehouse_id") or default_warehouse_id)
    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    return warehouse["id"] if warehouse else default_warehouse_id


def _xlsx_column_index(cell_ref):
    letters = "".join(ch for ch in (cell_ref or "") if ch.isalpha()).upper()
    total = 0
    for ch in letters:
        total = total * 26 + (ord(ch) - 64)
    return max(total - 1, 0)


def _xlsx_cell_value(cell, shared_strings, namespace):
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        texts = [node.text or "" for node in cell.findall(".//a:t", namespace)]
        return "".join(texts)

    value_node = cell.find("a:v", namespace)
    value = value_node.text if value_node is not None else ""

    if cell_type == "s" and value:
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return ""

    return value or ""


def _read_xlsx_dataset(file):
    namespace = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }

    file.stream.seek(0)
    raw = file.stream.read()
    workbook_bytes = BytesIO(raw)

    with zipfile.ZipFile(workbook_bytes) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relation_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relations.findall("rel:Relationship", namespace)
        }

        sheets = workbook.find("a:sheets", namespace)
        if sheets is None or not list(sheets):
            raise ValueError("Sheet tidak ditemukan")

        first_sheet = list(sheets)[0]
        relation_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = relation_map.get(relation_id)
        if not target:
            raise ValueError("Sheet target tidak valid")

        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("a:si", namespace):
                texts = [node.text or "" for node in item.findall(".//a:t", namespace)]
                shared_strings.append("".join(texts))

        sheet_path = "xl/" + target.lstrip("/")
        worksheet = ET.fromstring(archive.read(sheet_path))
        sheet_data = worksheet.find("a:sheetData", namespace)
        if sheet_data is None:
            raise ValueError("Data sheet kosong")

        grid_rows = []
        for row in sheet_data.findall("a:row", namespace):
            values = []
            for cell in row.findall("a:c", namespace):
                index = _xlsx_column_index(cell.attrib.get("r", "A1"))
                while len(values) <= index:
                    values.append("")
                values[index] = _xlsx_cell_value(cell, shared_strings, namespace)
            grid_rows.append(values)

    if not grid_rows:
        raise ValueError("Data kosong")

    header_row = [str(value or "").strip() for value in grid_rows[0]]
    active_columns = []
    for idx, header in enumerate(header_row):
        normalized = header.strip().lower()
        if normalized:
            active_columns.append((idx, normalized))

    if not active_columns:
        raise ValueError("Header tidak valid")

    rows = []
    for source_row in grid_rows[1:]:
        row = {}
        for idx, normalized in active_columns:
            row[normalized] = source_row[idx] if idx < len(source_row) else ""
        if _row_has_content(row):
            rows.append(row)

    file.stream.seek(0)
    return [column for _, column in active_columns], rows


def _read_import_file(file):
    try:
        pandas_module = import_module("pandas")
    except ImportError as exc:
        raise RuntimeError(
            "Format Excel lama (.xls) membutuhkan dependency pandas di environment ini. "
            "Gunakan interpreter project yang benar atau pakai template .xlsx/.csv."
        ) from exc

    try:
        return pandas_module.read_excel(file)
    except Exception as exc:
        raise RuntimeError("Format Excel lama (.xls) belum bisa dibaca di server ini. Gunakan template .xlsx atau .csv.") from exc


def _read_csv_dataset(file):
    file.stream.seek(0)
    raw = file.stream.read()
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    else:
        text = str(raw)

    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter or ","
    except csv.Error:
        if ";" in sample and sample.count(";") >= sample.count(","):
            delimiter = ";"

    reader = csv.DictReader(StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("Format tidak valid")

    original_fields = list(reader.fieldnames)
    normalized_fields = [(field or "").strip().lower() for field in original_fields]
    rows = []

    for raw_row in reader:
        row = {}
        for original, normalized in zip(original_fields, normalized_fields):
            if normalized:
                row[normalized] = raw_row.get(original) or ""
        if _row_has_content(row):
            rows.append(row)

    file.stream.seek(0)
    return normalized_fields, rows


def _read_import_dataset(file):
    filename = (file.filename or "").lower()

    if filename.endswith(".xlsx"):
        return _read_xlsx_dataset(file)

    if filename.endswith(".csv"):
        return _read_csv_dataset(file)

    if filename.endswith(".xls"):
        df = _read_import_file(file)
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.fillna("")
        rows = [row for row in df.to_dict(orient="records") if _row_has_content(row)]
        return list(df.columns), rows

    raise RuntimeError(
        "Format file belum didukung. Gunakan template .xlsx atau .csv."
    )


def _upsert_variant(
    db,
    product_id,
    variant_name,
    price_retail,
    price_discount,
    price_nett,
    variant_code="",
    color="",
    gtin="",
    no_gtin=0,
):
    variant_name = _normalize_variant_name(variant_name)
    gtin = "" if no_gtin else (gtin or "").strip()
    variant_code = (variant_code or "").strip()
    color = _normalize_variant_color(color)

    existing = db.execute("""
        SELECT id
        FROM product_variants
        WHERE product_id=? AND variant=?
    """, (product_id, variant_name)).fetchone()

    if existing:
        db.execute("""
            UPDATE product_variants
            SET price_retail=?,
                price_discount=?,
                price_nett=?,
                variant_code=?,
                color=?,
                gtin=?,
                no_gtin=?
            WHERE id=?
        """, (
            price_retail,
            price_discount,
            price_nett,
            variant_code,
            color,
            gtin,
            no_gtin,
            existing["id"],
        ))
        return existing["id"]

    cur = db.execute("""
        INSERT INTO product_variants(
            product_id, variant, price_retail, price_discount, price_nett, variant_code, color, gtin, no_gtin
        )
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        product_id,
        variant_name,
        price_retail,
        price_discount,
        price_nett,
        variant_code,
        color,
        gtin,
        no_gtin,
    ))

    return cur.lastrowid


def _delete_product_bundle(db, product_ids):
    if not product_ids:
        return 0

    placeholders = ",".join(["?"] * len(product_ids))

    db.execute(f"DELETE FROM requests WHERE product_id IN ({placeholders})", product_ids)
    db.execute(f"DELETE FROM approvals WHERE product_id IN ({placeholders})", product_ids)
    db.execute(f"DELETE FROM stock_movements WHERE product_id IN ({placeholders})", product_ids)
    db.execute(f"DELETE FROM stock_history WHERE product_id IN ({placeholders})", product_ids)
    db.execute(f"DELETE FROM stock_batches WHERE product_id IN ({placeholders})", product_ids)
    db.execute(f"DELETE FROM stock WHERE product_id IN ({placeholders})", product_ids)
    db.execute(f"DELETE FROM product_variants WHERE product_id IN ({placeholders})", product_ids)
    result = db.execute(f"DELETE FROM products WHERE id IN ({placeholders})", product_ids)
    return result.rowcount if result.rowcount is not None else 0


@products_bp.route("/get_variants/<int:product_id>")
def get_variants(product_id):

    db = get_db()

    rows = db.execute("""
        SELECT id, variant, price_retail, price_discount, price_nett, variant_code, color, gtin, no_gtin
        FROM product_variants
        WHERE product_id=?
        ORDER BY CASE WHEN LOWER(variant)='default' THEN 0 ELSE 1 END, variant
    """, (product_id,)).fetchall()

    return jsonify([dict(r) for r in rows])


@products_bp.route("/picker")
def product_picker():

    db = get_db()
    warehouse_id = _resolve_picker_warehouse(db, request.args.get("warehouse_id"))
    page = max(_to_int(request.args.get("page"), 1), 1)
    page_size = max(1, min(_to_int(request.args.get("page_size"), 20), 60))
    offset = (page - 1) * page_size
    search = _normalize_picker_query(request.args.get("q"))
    category = (request.args.get("category") or "").strip()
    mode = (request.args.get("mode") or "").strip().lower()

    conditions = []
    params = [warehouse_id]
    count_params = []

    if search:
        search_clause, search_params = _build_picker_search_conditions(search)
        conditions.append(search_clause)
        params.extend(search_params)
        count_params.extend(search_params)

    if category:
        conditions.append("COALESCE(c.name, '') = ?")
        params.append(category)
        count_params.append(category)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_by, order_params = _build_picker_order_by(search, mode)

    rows = db.execute(f"""
        SELECT
            p.id AS product_id,
            v.id AS variant_id,
            p.sku,
            p.name,
            COALESCE(c.name, '-') AS category,
            COALESCE(v.variant, 'default') AS variant,
            COALESCE(v.variant_code, '') AS variant_code,
            COALESCE(v.color, '') AS color,
            COALESCE(v.gtin, '') AS gtin,
            COALESCE(v.price_retail, 0) AS price_retail,
            COALESCE(v.price_discount, 0) AS price_discount,
            COALESCE(v.price_nett, 0) AS price_nett,
            COALESCE(s.qty, 0) AS qty
        FROM products p
        JOIN product_variants v ON v.product_id = p.id
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN stock s
            ON s.product_id = p.id
            AND s.variant_id = v.id
            AND s.warehouse_id = ?
        {where_clause}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
    """, (*params, *order_params, page_size, offset)).fetchall()

    total = db.execute(f"""
        SELECT COUNT(*) AS total
        FROM products p
        JOIN product_variants v ON v.product_id = p.id
        LEFT JOIN categories c ON c.id = p.category_id
        {where_clause}
    """, count_params).fetchone()["total"]

    total_pages = max(1, (total + page_size - 1) // page_size)

    items = []
    for row in rows:
        item = dict(row)
        variant = item["variant"] or "default"
        item["variant_label"] = "Default" if variant.lower() == "default" else variant
        item["display_name"] = f'{item["sku"]} - {item["name"]}'
        items.append(item)

    return jsonify({
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": total_pages,
        "warehouse_id": warehouse_id,
    })


@products_bp.route("/")
def products():
    db = get_db()
    warehouse_id = _resolve_products_warehouse(db)
    params = {
        "workspace": "products",
        "warehouse": warehouse_id,
    }

    search = (request.args.get("search") or "").strip()
    if search:
        params["product_search"] = search

    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1

    if page > 1:
        params["product_page"] = page

    return redirect(f"{PRODUCT_STUDIO_REDIRECT_PATH}?{urlencode(params)}")


@products_bp.route("/bulk-delete", methods=["POST"])
def bulk_delete():
    denied = _require_product_master_access(json_mode=True)
    if denied:
        return denied

    db = get_db()
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("ids", [])
    ids = []

    for raw_id in raw_ids:
        try:
            ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    ids = sorted(set(ids))

    if not ids:
        return _products_json_error("Pilih minimal satu produk.", 400)

    try:
        if can_queue_product_master_approval(session.get("role")):
            pending_map = find_pending_product_delete_approvals(db, ids)
            queue_ids = [product_id for product_id in ids if product_id not in pending_map]

            if not queue_ids:
                existing_ids = [pending_map[product_id]["id"] for product_id in ids if product_id in pending_map]
                return jsonify({
                    "status": "success",
                    "approval_status": "pending",
                    "approval_existing": True,
                    "message": "Semua produk yang dipilih sudah menunggu approval hapus sebelumnya.",
                    "approval_ids": existing_ids,
                })

            db.execute("BEGIN")
            approval_ids = _queue_product_delete_requests(db, queue_ids)
            db.commit()
            existing_count = len(pending_map)
            total_pending_ids = [pending_map[product_id]["id"] for product_id in ids if product_id in pending_map] + approval_ids
            message = f"{len(approval_ids)} permintaan hapus produk dikirim dan menunggu approval leader / super admin."
            if existing_count:
                message = (
                    f"{len(approval_ids)} permintaan hapus baru dikirim. "
                    f"{existing_count} produk lain sudah punya approval pending."
                )
            return jsonify({
                "status": "success",
                "approval_status": "pending",
                "approval_existing": existing_count > 0,
                "message": message,
                "approval_ids": total_pending_ids,
            })

        db.execute("BEGIN")
        deleted_count = _delete_product_bundle(db, ids)
        db.commit()
        return jsonify({
            "status": "success",
            "message": f"{deleted_count} produk berhasil dihapus.",
            "deleted_count": deleted_count,
        })

    except Exception as e:
        db.rollback()
        print("BULK DELETE ERROR:", e)
        return _products_json_error("Gagal menghapus produk.", 500)


@products_bp.route("/import/preview", methods=["POST"])
def preview_import():
    denied = _require_product_master_access(json_mode=True)
    if denied:
        return denied

    file = request.files.get("file")

    if not file:
        return _products_json_error("File tidak ada", 400)

    try:
        _, rows = _read_import_dataset(file)
    except RuntimeError as e:
        return _products_json_error(str(e), 500)
    except Exception:
        return _products_json_error("Format tidak valid", 400)

    return jsonify({"status": "success", "rows": rows[:10]})


@products_bp.route("/add", methods=["POST"])
def add_product():
    denied = _require_product_master_access()
    if denied:
        return denied

    db = get_db()

    try:
        sku = request.form["sku"].strip()
        name = request.form["name"].strip()
        category_name = request.form["category_name"].strip()
        unit_label = _normalize_unit_label(request.form.get("unit_label"))
        requested_variant_mode = _normalize_variant_mode(request.form.get("variant_mode"))
        warehouse_id = int(request.form["warehouse_id"])
        variant_rows = _build_variant_rows(request.form, requested_variant_mode)
        variant_mode = _infer_variant_mode(variant_rows, requested_variant_mode)

    except Exception:
        return _products_error_response("Input tidak valid", 400)

    if is_scoped_role(session.get("role")):
        warehouse_id = session.get("warehouse_id") or warehouse_id

    if not variant_rows:
        return _products_error_response("Minimal isi satu variasi produk.", 400)

    if any(row["qty"] < 0 for row in variant_rows):
        return _products_error_response("Qty tidak boleh minus.", 400)

    try:
        db.execute("BEGIN")

        exist = db.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()

        if exist:
            db.rollback()
            return _products_error_response("SKU sudah ada", 409)

        category = db.execute("SELECT id FROM categories WHERE name=?", (category_name,)).fetchone()

        if category:
            category_id = category["id"]
        else:
            cur = db.execute("INSERT INTO categories(name) VALUES (?)", (category_name,))
            category_id = cur.lastrowid

        cur = db.execute(
            "INSERT INTO products (sku,name,category_id,unit_label,variant_mode) VALUES (?,?,?,?,?)",
            (sku, name, category_id, unit_label, variant_mode),
        )
        product_id = cur.lastrowid

        for row in variant_rows:
            variant_id = _upsert_variant(
                db,
                product_id,
                row["variant"],
                row["price_retail"],
                row["price_discount"],
                row["price_nett"],
                variant_code=row["variant_code"],
                color=row.get("color", ""),
                gtin=row["gtin"],
                no_gtin=row["no_gtin"],
            )

            if row["qty"] <= 0:
                continue

            ok = add_stock(product_id, variant_id, warehouse_id, row["qty"], note="Initial Stock")

            if not ok:
                raise Exception("Gagal add stock")

        db.commit()
        return _products_success_response(
            "Produk berhasil ditambahkan",
            product_id=product_id,
            sku=sku,
            unit_label=unit_label,
            variant_mode=variant_mode,
        )

    except Exception as e:
        db.rollback()
        print("ERROR ADD PRODUCT:", e)
        return _products_error_response(str(e), 500)


@products_bp.route("/delete/<int:id>", methods=["POST"])
def delete_product(id):
    denied = _require_product_master_access()
    if denied:
        return denied

    db = get_db()

    try:
        if can_queue_product_master_approval(session.get("role")):
            pending_map = find_pending_product_delete_approvals(db, [id])
            existing_pending = pending_map.get(id)
            if existing_pending:
                flash("Produk ini sudah memiliki approval hapus yang masih pending.", "success")
                return redirect(f"{PRODUCT_STUDIO_REDIRECT_PATH}?workspace=products")

            db.execute("BEGIN")
            approval_ids = _queue_product_delete_requests(db, [id])
            db.commit()
            flash(
                f"{len(approval_ids)} permintaan hapus produk dikirim dan menunggu approval leader / super admin.",
                "success",
            )
            return redirect(f"{PRODUCT_STUDIO_REDIRECT_PATH}?workspace=products")

        db.execute("BEGIN")
        deleted_count = _delete_product_bundle(db, [id])
        db.commit()
        if deleted_count:
            flash("Produk berhasil dihapus", "success")
        else:
            flash("Produk tidak ditemukan atau sudah terhapus", "error")

    except Exception as e:
        db.rollback()
        print("DELETE ERROR:", e)
        flash("Gagal menghapus produk", "error")

    return redirect(f"{PRODUCT_STUDIO_REDIRECT_PATH}?workspace=products")


@products_bp.route("/import/progress/<job_id>")
def import_progress(job_id):
    denied = _require_product_master_access(json_mode=True)
    if denied:
        return denied

    data = IMPORT_PROGRESS.get(job_id)

    if not data:
        return _products_json_error("Progress import tidak ditemukan", 404)

    percent = int((data["current"] / data["total"]) * 100) if data["total"] else 0

    return jsonify({
        "percent": percent,
        "current": data["current"],
        "total": data["total"],
        "status": data["status"]
    })


@products_bp.route("/import", methods=["POST"])
def import_products():
    denied = _require_product_master_access(json_mode=True)
    if denied:
        return denied

    db = get_db()
    file = request.files.get("file")

    if not file:
        return _products_json_error("File import belum dipilih.", 400)

    user_id = session.get("user_id")
    ip = request.remote_addr
    user_agent = request.headers.get("User-Agent")

    try:
        columns, rows = _read_import_dataset(file)
    except RuntimeError as e:
        return _products_json_error(str(e), 500)
    except Exception:
        return _products_json_error("Format tidak valid", 400)

    required = ["sku", "name", "category", "qty"]
    for col in required:
        if col not in columns:
            return _products_json_error(f"Kolom {col} tidak ada", 400)

    job_id = str(uuid.uuid4())

    IMPORT_PROGRESS[job_id] = {
        "total": len(rows),
        "current": 0,
        "status": "processing"
    }

    wh = db.execute("SELECT id FROM warehouses WHERE id=?", (session.get("warehouse_id"),)).fetchone()
    if not wh:
        wh = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
    default_warehouse_id = wh["id"] if wh else 1

    CHUNK_SIZE = 200
    imported_variant_count = 0
    imported_total_qty = 0
    affected_warehouse_ids = set()

    category_cache = {r["name"]: r["id"] for r in db.execute("SELECT id,name FROM categories")}
    product_cache = {r["sku"]: r["id"] for r in db.execute("SELECT id,sku FROM products")}

    for start in range(0, len(rows), CHUNK_SIZE):

        chunk = rows[start:start+CHUNK_SIZE]

        try:
            db.execute("BEGIN")

            variant_payloads = []
            chunk_variant_count = 0
            chunk_total_qty = 0
            chunk_warehouse_ids = set()

            for row in chunk:
                try:
                    sku = str(row.get("sku")).strip()
                    name = str(row.get("name")).strip()
                    category_name = str(row.get("category") or "").strip() or "Uncategorized"
                    variant = _normalize_variant_name(str(row.get("variant") or "default"))
                    color = _normalize_variant_color(row.get("color"))

                    qty = _to_int(row.get("qty"), 0)
                    warehouse_id = _resolve_import_warehouse(
                        db,
                        row.get("warehouse_id"),
                        default_warehouse_id,
                    )
                    if not sku or not name or qty < 0:
                        continue

                    price_retail = _to_float(row.get("price_retail"))
                    price_discount = _to_float(row.get("price_discount"))
                    price_nett = _to_float(row.get("price_nett"))
                    variant_code = str(row.get("variant_code") or "").strip()
                    gtin = str(row.get("gtin") or "").strip()
                    no_gtin = 1 if _to_bool(row.get("no_gtin")) else 0

                    if category_name in category_cache:
                        category_id = category_cache[category_name]
                    else:
                        cur = db.execute("INSERT INTO categories(name) VALUES (?)", (category_name,))
                        category_id = cur.lastrowid
                        category_cache[category_name] = category_id

                    if sku in product_cache:
                        product_id = product_cache[sku]
                        db.execute("""
                            UPDATE products
                            SET name=?, category_id=?
                            WHERE id=?
                        """, (name, category_id, product_id))
                    else:
                        cur = db.execute("INSERT INTO products(sku,name,category_id) VALUES (?,?,?)", (sku, name, category_id))
                        product_id = cur.lastrowid
                        product_cache[sku] = product_id

                    variant_id = _upsert_variant(
                        db,
                        product_id,
                        _compose_variant_label(variant, color),
                        price_retail,
                        price_discount,
                        price_nett,
                        variant_code=variant_code,
                        color=color,
                        gtin=gtin,
                        no_gtin=no_gtin,
                    )
                    if qty > 0:
                        variant_payloads.append((product_id, variant_id, warehouse_id, qty))

                except Exception as e:
                    print("ROW ERROR:", e)

                IMPORT_PROGRESS[job_id]["current"] += 1

            stock_final = []
            for p_id, v_id, warehouse_id, qty in variant_payloads:
                stock_final.append((p_id, v_id, warehouse_id, qty, qty))
                chunk_variant_count += 1
                chunk_total_qty += qty
                chunk_warehouse_ids.add(warehouse_id)

            db.executemany("""
            INSERT INTO stock_batches(product_id,variant_id,warehouse_id,qty,remaining_qty,cost,created_at)
            VALUES (?,?,?,?,?,0,datetime('now'))
            """, stock_final)

            db.executemany("""
            INSERT INTO stock_movements(product_id,variant_id,warehouse_id,batch_id,qty,type,created_at)
            VALUES (?,?,?,?,?,'IN',datetime('now'))
            """, [(s[0], s[1], s[2], None, s[3]) for s in stock_final])

            db.executemany("""
            INSERT INTO stock_history(product_id,variant_id,warehouse_id,action,type,qty,note,user_id,ip_address,user_agent)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, [
                (s[0], s[1], s[2], 'IMPORT', 'IN', s[3], 'Bulk Import', user_id, ip, user_agent)
                for s in stock_final
            ])

            db.execute("""
            INSERT INTO stock(product_id,variant_id,warehouse_id,qty)
            SELECT product_id,variant_id,warehouse_id,SUM(remaining_qty)
            FROM stock_batches
            GROUP BY product_id,variant_id,warehouse_id
            ON CONFLICT(product_id,variant_id,warehouse_id)
            DO UPDATE SET qty = excluded.qty
            """)

            db.commit()
            imported_variant_count += chunk_variant_count
            imported_total_qty += chunk_total_qty
            affected_warehouse_ids.update(chunk_warehouse_ids)

        except Exception as e:
            db.rollback()
            print("CHUNK ERROR:", e)

    IMPORT_PROGRESS[job_id]["status"] = "done"
    if imported_total_qty > 0:
        try:
            warehouse_id = next(iter(affected_warehouse_ids)) if len(affected_warehouse_ids) == 1 else None
            inventory_policy = get_event_notification_policy("inventory.activity")
            notify_operational_event(
                f"Import produk selesai: {imported_variant_count} varian",
                (
                    f"Bulk import menambahkan {imported_total_qty} stok ke "
                    f"{imported_variant_count} varian produk."
                ),
                warehouse_id=warehouse_id,
                category="inventory",
                link_url="/stock/?workspace=products",
                recipient_roles=inventory_policy["roles"],
                recipient_usernames=inventory_policy["usernames"],
                recipient_user_ids=inventory_policy["user_ids"],
                source_type="product_import_job",
                source_id=job_id,
                push_title="Import produk selesai",
                push_body=f"{imported_variant_count} varian | Qty {imported_total_qty}",
            )
        except Exception as exc:
            print("PRODUCT IMPORT NOTIFICATION ERROR:", exc)

    return jsonify({"job_id": job_id})
