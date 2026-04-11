from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from typing import Any
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import webbrowser

import requests

try:
    import win32print
except ImportError:  # pragma: no cover - optional on non-Windows/build hosts
    win32print = None


APP_VERSION = "0.1.0"

DEFAULT_CONFIG: dict[str, Any] = {
    "app_name": "Kasir ERP Desktop",
    "base_url": "https://erp.cvbjasyogya.cloud",
    "modules": {
        "login": "/login?source=desktop-kasir",
        "workspace": "/workspace/?source=desktop-kasir",
        "kasir": "/kasir/?source=desktop-kasir",
        "gudang": "/stock/?source=desktop-kasir",
        "notifications": "/notifications/?source=desktop-kasir",
    },
    "window": {
        "width": 1440,
        "height": 920,
        "resizable": True,
        "fullscreen": False,
        "confirm_close": True,
        "text_select": True,
    },
    "webview": {
        "debug": False,
        "private_mode": False,
        "storage_subdir": "webview-data",
    },
    "browser": {
        "mode": "auto",
        "preferred": "edge",
        "edge_path": "",
        "chrome_path": "",
        "app_mode": True,
        "kiosk_printing": True,
        "user_data_subdir": "browser-profile",
        "extra_args": [],
    },
    "bridge": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 17844,
        "cors_origin": "*",
    },
    "network": {
        "healthcheck_path": "/login",
        "timeout_seconds": 8,
    },
    "printer": {
        "preferred_printer_name": "Xprinter",
        "native_driver_print_enabled": True,
        "paper_width_chars": 32,
        "raw_encoding": "cp437",
        "cut_after_print": True,
        "note": "Masih pondasi desktop. Printer native bisa dikembangkan dari bridge ini.",
    },
}


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {key: _deep_merge(base.get(key), value) for key, value in override.items()}
        for key, value in base.items():
            if key not in merged:
                merged[key] = value
        return merged
    if override is None:
        return base
    return override


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _app_data_root() -> Path:
    appdata = str(os.getenv("APPDATA") or "").strip()
    if appdata:
        return Path(appdata) / "KasirERPDesktop"
    return _runtime_root() / "runtime"


def _normalize_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def _append_query_params(url: str, params: dict[str, Any] | None = None) -> str:
    safe_url = str(url or "").strip()
    if not safe_url:
        return ""

    parts = urlsplit(safe_url)
    query_pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in (params or {}).items():
        safe_key = str(key or "").strip()
        safe_value = str(value or "").strip()
        if safe_key and safe_value:
            query_pairs[safe_key] = safe_value
    query_string = urlencode(query_pairs, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query_string, parts.fragment))


def build_target_url(config: dict[str, Any], target: str) -> str:
    safe_target = str(target or "kasir").strip() or "kasir"
    module_value = (config.get("modules") or {}).get(safe_target, safe_target)
    safe_value = str(module_value or "").strip()
    if safe_value.startswith(("http://", "https://")):
        return safe_value

    base_url = _normalize_base_url(str(config.get("base_url") or ""))
    if not safe_value.startswith("/"):
        safe_value = f"/{safe_value}"
    return f"{base_url}{safe_value}"


def _write_default_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def load_config(config_path: str | None = None) -> tuple[dict[str, Any], Path]:
    runtime_root = _runtime_root()
    resolved_path = Path(config_path).expanduser().resolve() if config_path else runtime_root / "kasir_config.json"

    if not resolved_path.exists():
        _write_default_config(resolved_path)

    try:
        loaded = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        loaded = {}

    merged = _deep_merge(DEFAULT_CONFIG, loaded if isinstance(loaded, dict) else {})
    return merged, resolved_path


def _configure_logger(app_data_root: Path) -> logging.Logger:
    log_dir = app_data_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kasir-desktop.log"

    logger = logging.getLogger("kasir_desktop")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def _configured_path(path_value: Any) -> str:
    safe_value = str(path_value or "").strip().strip('"')
    return safe_value


def _detect_browser_executable(config: dict[str, Any]) -> tuple[str, str]:
    browser_config = config.get("browser") or {}
    preferred = str(browser_config.get("preferred") or "edge").strip().lower()
    configured_candidates = {
        "edge": [
            _configured_path(browser_config.get("edge_path")),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            shutil.which("msedge"),
        ],
        "chrome": [
            _configured_path(browser_config.get("chrome_path")),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            shutil.which("chrome"),
        ],
    }

    ordered_names = ["edge", "chrome"] if preferred == "edge" else ["chrome", "edge"]
    for browser_name in ordered_names:
        for candidate in configured_candidates.get(browser_name, []):
            safe_candidate = str(candidate or "").strip()
            if safe_candidate and Path(safe_candidate).exists():
                return browser_name, safe_candidate
    return "", ""


def _browser_profile_dir(app_data_root: Path, config: dict[str, Any]) -> Path:
    browser_config = config.get("browser") or {}
    subdir = str(browser_config.get("user_data_subdir") or "browser-profile").strip() or "browser-profile"
    profile_dir = app_data_root / subdir
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def _build_external_browser_command(
    browser_name: str,
    browser_path: str,
    config: dict[str, Any],
    app_data_root: Path,
    target_url: str,
) -> list[str]:
    browser_config = config.get("browser") or {}
    window_config = config.get("window") or {}
    profile_dir = _browser_profile_dir(app_data_root, config)
    command = [browser_path]

    if browser_name in {"edge", "chrome"}:
        command.extend(
            [
                "--no-first-run",
                "--disable-session-crashed-bubble",
                f"--user-data-dir={profile_dir}",
            ]
        )
        if bool(browser_config.get("kiosk_printing", True)):
            command.append("--kiosk-printing")
        if bool(window_config.get("fullscreen", False)):
            command.append("--start-fullscreen")
        else:
            width = int(window_config.get("width") or 1440)
            height = int(window_config.get("height") or 920)
            command.append(f"--window-size={width},{height}")

        extra_args = browser_config.get("extra_args") or []
        if isinstance(extra_args, list):
            command.extend(str(arg).strip() for arg in extra_args if str(arg).strip())

        if bool(browser_config.get("app_mode", True)):
            command.append(f"--app={target_url}")
        else:
            command.extend(["--new-window", target_url])
    else:
        command.append(target_url)

    return command


def _launch_external_browser(
    config: dict[str, Any],
    app_data_root: Path,
    target_url: str,
    logger: logging.Logger,
) -> int:
    browser_name, browser_path = _detect_browser_executable(config)
    if browser_path:
        command = _build_external_browser_command(browser_name, browser_path, config, app_data_root, target_url)
        logger.info("Launching external browser mode: %s -> %s", browser_name, target_url)
        process = subprocess.Popen(command, cwd=str(_runtime_root()))
        process.wait()
        return 0

    logger.warning("Chromium browser tidak ditemukan. Membuka default browser tanpa mode app.")
    if not webbrowser.open(target_url, new=1):
        logger.error("Gagal membuka browser default untuk %s", target_url)
        return 1
    return 0


def _powershell_json(command: str, timeout_seconds: int = 8) -> Any:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "powershell_error").strip())
    output = str(completed.stdout or "").strip()
    return json.loads(output) if output else None


def _powershell_output(command: str, timeout_seconds: int = 8) -> str:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "powershell_error").strip())
    return str(completed.stdout or "").strip()


def _escape_powershell_single_quote(value: Any) -> str:
    return str(value or "").replace("'", "''")


def get_windows_printer_snapshot(timeout_seconds: int = 8) -> dict[str, Any]:
    if os.name != "nt":
        return {
            "ok": False,
            "default_printer": "",
            "printers": [],
            "error": "windows_only",
        }

    try:
        printers_payload = _powershell_json(
            "Get-Printer | Select-Object Name,DriverName,PortName,PrinterStatus | ConvertTo-Json -Compress",
            timeout_seconds=timeout_seconds,
        )
        default_payload = _powershell_json(
            "(Get-CimInstance Win32_Printer | Where-Object { $_.Default } | "
            "Select-Object -First 1 Name,DriverName,PortName) | ConvertTo-Json -Compress",
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return {
            "ok": False,
            "default_printer": "",
            "printers": [],
            "error": str(exc),
        }

    if isinstance(printers_payload, dict):
        printers = [printers_payload]
    elif isinstance(printers_payload, list):
        printers = printers_payload
    else:
        printers = []

    default_name = ""
    if isinstance(default_payload, dict):
        default_name = str(default_payload.get("Name") or "").strip()

    return {
        "ok": True,
        "default_printer": default_name,
        "printers": printers,
        "error": "",
    }


def resolve_preferred_printer_name(snapshot: dict[str, Any], preferred_name: str) -> str:
    printers = snapshot.get("printers") or []
    safe_preferred = str(preferred_name or "").strip().lower()
    if not safe_preferred:
        return ""

    exact_match = ""
    fuzzy_match = ""
    for printer in printers:
        candidate_name = str((printer or {}).get("Name") or "").strip()
        normalized = candidate_name.lower()
        if not normalized:
            continue
        if normalized == safe_preferred:
            exact_match = candidate_name
            break
        if not fuzzy_match and safe_preferred in normalized:
            fuzzy_match = candidate_name

    return exact_match or fuzzy_match


def set_windows_default_printer(printer_name: str, timeout_seconds: int = 8) -> dict[str, Any]:
    safe_name = str(printer_name or "").strip()
    if not safe_name:
        return {"ok": False, "printer_name": "", "error": "missing_printer_name"}
    if os.name != "nt":
        return {"ok": False, "printer_name": safe_name, "error": "windows_only"}

    escaped_name = _escape_powershell_single_quote(safe_name)
    try:
        payload = _powershell_json(
            (
                f"$printer = Get-CimInstance Win32_Printer | Where-Object {{ $_.Name -eq '{escaped_name}' }} | "
                "Select-Object -First 1; "
                "if (-not $printer) { throw 'printer_not_found' }; "
                "Invoke-CimMethod -InputObject $printer -MethodName SetDefaultPrinter | Out-Null; "
                "@{ Name = $printer.Name } | ConvertTo-Json -Compress"
            ),
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return {"ok": False, "printer_name": safe_name, "error": str(exc)}

    if isinstance(payload, dict):
        return {
            "ok": True,
            "printer_name": str(payload.get("Name") or safe_name).strip(),
            "error": "",
        }
    return {"ok": True, "printer_name": safe_name, "error": ""}


def _normalize_receipt_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.replace("\r", " ").split()).strip()


def _coerce_receipt_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _truncate_receipt_text(value: str, width: int) -> str:
    safe_width = max(8, int(width or 32))
    safe_value = _normalize_receipt_text(value)
    if len(safe_value) <= safe_width:
        return safe_value
    return safe_value[: max(1, safe_width - 1)].rstrip() + "-"


def _wrap_receipt_text(value: Any, width: int) -> list[str]:
    safe_width = max(8, int(width or 32))
    safe_value = _normalize_receipt_text(value)
    if not safe_value:
        return [""]

    words = safe_value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        candidate = f"{current} {word}"
        if len(candidate) <= safe_width:
            current = candidate
            continue
        lines.append(current)
        current = word

    if current:
        lines.append(current)

    return lines or [safe_value[:safe_width]]


def _receipt_kv_line(label: Any, value: Any, width: int) -> list[str]:
    safe_width = max(8, int(width or 32))
    safe_label = _truncate_receipt_text(label, max(4, safe_width // 2))
    safe_value = _normalize_receipt_text(value)
    if not safe_value:
        return [_truncate_receipt_text(safe_label, safe_width)]

    max_value_width = max(8, safe_width - len(safe_label) - 1)
    wrapped_values = _wrap_receipt_text(safe_value, max_value_width)
    lines = []
    first_value = wrapped_values[0]
    spacing = max(1, safe_width - len(safe_label) - len(first_value))
    lines.append(f"{safe_label}{' ' * spacing}{first_value}")
    indent = " " * min(len(safe_label), safe_width // 2)
    for extra in wrapped_values[1:]:
        lines.append(f"{indent} {extra}")
    return lines


def _receipt_separator(width: int, char: str = "-") -> str:
    safe_width = max(8, int(width or 32))
    return (char or "-") * safe_width


def _receipt_compact_pair_line(left: Any, right: Any, width: int) -> str:
    safe_width = max(8, int(width or 32))
    safe_left = _normalize_receipt_text(left)
    safe_right = _normalize_receipt_text(right)
    if not safe_right:
        return _truncate_receipt_text(safe_left, safe_width)
    if not safe_left:
        return _truncate_receipt_text(safe_right, safe_width)

    safe_right = _truncate_receipt_text(safe_right, max(6, safe_width // 2))
    remaining = max(6, safe_width - len(safe_right) - 1)
    safe_left = _truncate_receipt_text(safe_left, remaining)
    spacing = max(1, safe_width - len(safe_left) - len(safe_right))
    return f"{safe_left}{' ' * spacing}{safe_right}"


def _receipt_compact_value_text(label: Any, value: Any, width: int) -> str:
    safe_width = max(8, int(width or 32))
    safe_label = _normalize_receipt_text(label)
    safe_value = _normalize_receipt_text(value)
    raw_text = f"{safe_label} {safe_value}".strip() if safe_value else safe_label
    return _truncate_receipt_text(raw_text, safe_width)


def build_thermal_receipt_text(payload: dict[str, Any], width: int = 32) -> str:
    safe_width = max(24, min(64, int(width or 32)))
    items = payload.get("items") or []
    loyalty_lines = payload.get("loyalty_lines") or []

    lines: list[str] = []
    store_name = _normalize_receipt_text(payload.get("store_name"))
    copy_label = _normalize_receipt_text(payload.get("copy_label"))
    business_address = _normalize_receipt_text(payload.get("business_address"))
    receipt_copy = _normalize_receipt_text(payload.get("receipt_copy")).lower()
    is_store_copy = receipt_copy == "store"
    payment_method = _normalize_receipt_text(payload.get("payment_method")).lower()
    payment_breakdown_label = _normalize_receipt_text(payload.get("payment_breakdown_label"))
    paid_amount_label = _normalize_receipt_text(payload.get("paid_amount_label")) or "Rp 0"
    paid_cash = paid_amount_label if payment_method == "cash" else "Rp 0"
    paid_credit = paid_amount_label if payment_method == "credit" else "Rp 0"
    paid_debit = paid_amount_label if payment_method == "debit" else "Rp 0"
    paid_qris = paid_amount_label if payment_method == "qris" else "Rp 0"

    if is_store_copy:
        if store_name or copy_label:
            lines.append(_receipt_compact_pair_line(store_name, copy_label, safe_width))
    else:
        if copy_label:
            lines.extend(_wrap_receipt_text(copy_label, safe_width))
        if store_name:
            lines.extend(_wrap_receipt_text(store_name, safe_width))
    if business_address and not is_store_copy:
        lines.extend(_wrap_receipt_text(business_address, safe_width))

    lines.append(_receipt_separator(safe_width))
    for key, value in (
        ("No", payload.get("receipt_no")),
        ("Kasir", payload.get("cashier_name")),
        ("Pel", payload.get("customer_name")),
        ("Tanggal", payload.get("sale_datetime")),
    ):
        if is_store_copy and key == "Tanggal":
            continue
        lines.extend(_receipt_kv_line(key, value, safe_width))
    if is_store_copy:
        lines.extend(_receipt_kv_line("Waktu", payload.get("sale_datetime"), safe_width))

    lines.append(_receipt_separator(safe_width))
    for item in items:
        product_name = _normalize_receipt_text(item.get("product_name"))
        variant = _normalize_receipt_text(item.get("variant_name"))
        sku = _normalize_receipt_text(item.get("sku"))
        if product_name:
            if is_store_copy and sku:
                compact_product = f"{product_name} | {sku}"
                if len(compact_product) <= safe_width:
                    lines.append(compact_product)
                else:
                    lines.extend(_wrap_receipt_text(product_name, safe_width))
            else:
                lines.extend(_wrap_receipt_text(product_name, safe_width))
        variant_parts = []
        if variant and (not is_store_copy or variant.lower() != "default"):
            variant_parts.append(variant)
        if sku and not (is_store_copy and product_name and len(f"{product_name} | {sku}") <= safe_width):
            variant_parts.append(f"Kode: {sku}" if is_store_copy else sku)
        variant_line = " / ".join(part for part in variant_parts if part)
        if variant_line:
            lines.extend(_wrap_receipt_text(variant_line, safe_width))

        qty_text = str(item.get("active_qty") or "0")
        price_text = _normalize_receipt_text(item.get("unit_price_label"))
        total_text = _normalize_receipt_text(
            item.get("active_line_total_label") or item.get("line_total_label")
        )
        calc_left = f"{qty_text} x {price_text}".strip()
        lines.extend(_receipt_kv_line(calc_left, total_text, safe_width))

        void_qty = _coerce_receipt_int(item.get("void_qty"))
        if void_qty > 0:
            void_text = f"Void {void_qty}"
            void_amount = _normalize_receipt_text(item.get("void_amount_label"))
            lines.extend(_receipt_kv_line(void_text, void_amount, safe_width))

        if not is_store_copy:
            lines.append("")

    if items:
        while lines and lines[-1] == "":
            lines.pop()

    lines.append(_receipt_separator(safe_width))
    if is_store_copy:
        lines.extend(_receipt_kv_line("Qty", payload.get("total_items"), safe_width))
        lines.extend(_receipt_kv_line("Grand Total", payload.get("total_amount_label"), safe_width))
        summary_columns = [
            (
                ("Potongan", payload.get("discount_amount_label")),
                ("Pajak", payload.get("tax_amount_label")),
            ),
            (
                ("Tunai", paid_cash),
                ("QRIS", paid_qris),
            ),
            (
                ("K. Kredit", paid_credit),
                ("K. Debit", paid_debit),
            ),
            (
                ("Kembali", payload.get("change_amount_label")),
                ("Metode", payload.get("payment_method_label")),
            ),
        ]
        left_width = max(10, (safe_width - 1) // 2)
        right_width = max(10, safe_width - left_width - 1)
        for left_entry, right_entry in summary_columns:
            left_text = _receipt_compact_value_text(left_entry[0], left_entry[1], left_width)
            right_text = _receipt_compact_value_text(right_entry[0], right_entry[1], right_width)
            lines.append(f"{left_text.ljust(left_width)} {right_text}".rstrip())
        if payment_breakdown_label:
            lines.extend(_receipt_kv_line("Split", payment_breakdown_label, safe_width))
    else:
        for key, value in (
            ("Qty", payload.get("total_items")),
            ("Subtotal", payload.get("subtotal_amount_label")),
            ("Potongan", payload.get("discount_amount_label")),
            ("Pajak", payload.get("tax_amount_label")),
            ("Grand Total", payload.get("total_amount_label")),
            ("Bayar", payload.get("paid_amount_label")),
            ("Kembali", payload.get("change_amount_label")),
            ("Metode", payload.get("payment_method_label")),
        ):
            lines.extend(_receipt_kv_line(key, value, safe_width))
        if payment_breakdown_label:
            lines.extend(_receipt_kv_line("Split", payment_breakdown_label, safe_width))

    if loyalty_lines and not is_store_copy:
        lines.append(_receipt_separator(safe_width))
        loyalty_title = _normalize_receipt_text(payload.get("loyalty_summary_title"))
        if loyalty_title:
            lines.extend(_wrap_receipt_text(loyalty_title, safe_width))
        for entry in loyalty_lines:
            clean_entry = _normalize_receipt_text(entry).lstrip("- ").strip()
            if clean_entry:
                lines.extend(_wrap_receipt_text(f"* {clean_entry}", safe_width))

    footer_lines = [
        payload.get("store_copy_note"),
        payload.get("thank_you_text"),
        payload.get("feedback_line"),
        payload.get("social_label"),
        payload.get("social_media_url"),
    ]
    footer_lines = [line for line in footer_lines if _normalize_receipt_text(line)]
    if footer_lines and not is_store_copy:
        lines.append(_receipt_separator(safe_width))
        for line in footer_lines:
            lines.extend(_wrap_receipt_text(line, safe_width))

    return "\n".join(line.rstrip() for line in lines if line is not None).strip()


def print_raw_receipt_to_windows_printer(
    printer_name: str,
    receipt_text: str,
    *,
    encoding: str = "cp437",
    cut_after_print: bool = True,
    job_name: str = "Kasir ERP Receipt",
) -> dict[str, Any]:
    safe_name = str(printer_name or "").strip()
    if not safe_name:
        return {"ok": False, "printer_name": "", "error": "missing_printer_name"}
    if os.name != "nt":
        return {"ok": False, "printer_name": safe_name, "error": "windows_only"}
    if win32print is None:
        return {"ok": False, "printer_name": safe_name, "error": "pywin32_missing"}

    safe_encoding = str(encoding or "cp437").strip() or "cp437"
    try:
        payload = (receipt_text or "").replace("\r\n", "\n").replace("\r", "\n")
        encoded_body = payload.encode(safe_encoding, errors="replace")
    except LookupError:
        safe_encoding = "cp437"
        encoded_body = (receipt_text or "").encode(safe_encoding, errors="replace")

    raw_bytes = b"\x1b@" + encoded_body + b"\n\n\n\n"
    if cut_after_print:
        raw_bytes += b"\x1dV\x00"

    printer_handle = None
    try:
        printer_handle = win32print.OpenPrinter(safe_name)
        job_id = win32print.StartDocPrinter(printer_handle, 1, (job_name, None, "RAW"))
        try:
            win32print.StartPagePrinter(printer_handle)
            bytes_written = win32print.WritePrinter(printer_handle, raw_bytes)
            win32print.EndPagePrinter(printer_handle)
        finally:
            win32print.EndDocPrinter(printer_handle)
    except Exception as exc:
        return {"ok": False, "printer_name": safe_name, "error": str(exc)}
    finally:
        if printer_handle is not None:
            try:
                win32print.ClosePrinter(printer_handle)
            except Exception:
                pass

    return {
        "ok": True,
        "printer_name": safe_name,
        "bytes_written": int(bytes_written or 0),
        "encoding": safe_encoding,
        "error": "",
    }


class DesktopRuntime:
    def __init__(self, config: dict[str, Any], logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.current_target = "kasir"
        self.bridge_base_url = ""
        self._printer_lock = threading.Lock()
        self._restore_default_printer_name = ""
        self._active_printer_name = ""

    def attach_bridge_base_url(self, bridge_base_url: str) -> None:
        self.bridge_base_url = str(bridge_base_url or "").strip().rstrip("/")

    def build_runtime_url(self, target: str) -> str:
        url = build_target_url(self.config, target)
        return _append_query_params(
            url,
            {
                "source": "desktop-kasir",
                "desktop_bridge": self.bridge_base_url,
            },
        )

    def get_app_info(self) -> dict[str, Any]:
        return {
            "ok": True,
            "app_name": str(self.config.get("app_name") or "Kasir ERP Desktop"),
            "version": APP_VERSION,
            "base_url": _normalize_base_url(str(self.config.get("base_url") or "")),
            "current_target": self.current_target,
            "preferred_printer_name": str(((self.config.get("printer") or {}).get("preferred_printer_name") or "")).strip(),
            "bridge_base_url": self.bridge_base_url,
            "supports_native_bridge": True,
            "supports_native_receipt_print": bool(os.name == "nt" and win32print is not None),
            "runtime_mode": "desktop-http-bridge",
        }

    def ping_erp(self) -> dict[str, Any]:
        health_target = str((self.config.get("network") or {}).get("healthcheck_path") or "login").strip()
        timeout_seconds = int((self.config.get("network") or {}).get("timeout_seconds") or 8)
        health_url = build_target_url(self.config, health_target)
        started = time.perf_counter()
        try:
            response = requests.get(health_url, timeout=timeout_seconds, allow_redirects=True)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "ok": bool(response.ok),
                "url": health_url,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "error": "" if response.ok else f"http_{response.status_code}",
            }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "ok": False,
                "url": health_url,
                "status_code": None,
                "latency_ms": latency_ms,
                "error": str(exc),
            }

    def get_printer_snapshot(self) -> dict[str, Any]:
        return get_windows_printer_snapshot()

    def get_default_printer(self) -> dict[str, Any]:
        snapshot = self.get_printer_snapshot()
        return {
            "ok": bool(snapshot.get("ok")),
            "default_printer": str(snapshot.get("default_printer") or "").strip(),
            "error": str(snapshot.get("error") or "").strip(),
        }

    def activate_preferred_printer(self, printer_name: str = "") -> dict[str, Any]:
        with self._printer_lock:
            snapshot = self.get_printer_snapshot()
            if not snapshot.get("ok"):
                return {
                    "ok": False,
                    "printer_name": "",
                    "error": str(snapshot.get("error") or "printer_snapshot_failed"),
                }

            configured_name = str(((self.config.get("printer") or {}).get("preferred_printer_name") or "")).strip()
            desired_name = str(printer_name or configured_name).strip()
            if not desired_name:
                return {"ok": False, "printer_name": "", "error": "missing_preferred_printer_name"}

            matched_name = resolve_preferred_printer_name(snapshot, desired_name)
            if not matched_name:
                available_names = [
                    str((printer or {}).get("Name") or "").strip()
                    for printer in (snapshot.get("printers") or [])
                    if str((printer or {}).get("Name") or "").strip()
                ]
                return {
                    "ok": False,
                    "printer_name": "",
                    "error": "preferred_printer_not_found",
                    "preferred_printer_name": desired_name,
                    "available_printers": available_names,
                }

            current_default = str(snapshot.get("default_printer") or "").strip()
            if current_default.lower() == matched_name.lower():
                self._active_printer_name = matched_name
                return {
                    "ok": True,
                    "printer_name": matched_name,
                    "previous_default_printer": current_default,
                    "changed_default": False,
                    "error": "",
                }

            switch_result = set_windows_default_printer(
                matched_name,
                timeout_seconds=int((self.config.get("network") or {}).get("timeout_seconds") or 8),
            )
            if not switch_result.get("ok"):
                return {
                    "ok": False,
                    "printer_name": matched_name,
                    "error": str(switch_result.get("error") or "set_default_failed"),
                }

            self._restore_default_printer_name = current_default
            self._active_printer_name = matched_name
            self.logger.info("Preferred printer activated: %s (previous default: %s)", matched_name, current_default or "-")
            return {
                "ok": True,
                "printer_name": matched_name,
                "previous_default_printer": current_default,
                "changed_default": True,
                "error": "",
            }

    def restore_default_printer(self) -> dict[str, Any]:
        with self._printer_lock:
            previous_default = str(self._restore_default_printer_name or "").strip()
            active_printer = str(self._active_printer_name or "").strip()
            if not previous_default or previous_default.lower() == active_printer.lower():
                self._restore_default_printer_name = ""
                self._active_printer_name = ""
                return {
                    "ok": True,
                    "printer_name": previous_default or active_printer,
                    "restored": False,
                    "error": "",
                }

            restore_result = set_windows_default_printer(
                previous_default,
                timeout_seconds=int((self.config.get("network") or {}).get("timeout_seconds") or 8),
            )
            if not restore_result.get("ok"):
                return {
                    "ok": False,
                    "printer_name": previous_default,
                    "restored": False,
                    "error": str(restore_result.get("error") or "restore_default_failed"),
                }

            self.logger.info("Default printer restored: %s", previous_default)
            self._restore_default_printer_name = ""
            self._active_printer_name = ""
            return {
                "ok": True,
                "printer_name": previous_default,
                "restored": True,
                "error": "",
            }

    def print_receipt(self, payload: dict[str, Any], printer_name: str = "") -> dict[str, Any]:
        printer_config = self.config.get("printer") or {}
        if not bool(printer_config.get("native_driver_print_enabled", True)):
            return {"ok": False, "printer_name": "", "error": "native_driver_print_disabled"}

        snapshot = self.get_printer_snapshot()
        if not snapshot.get("ok"):
            return {
                "ok": False,
                "printer_name": "",
                "error": str(snapshot.get("error") or "printer_snapshot_failed"),
            }

        configured_name = str(printer_config.get("preferred_printer_name") or "").strip()
        desired_name = str(printer_name or configured_name).strip()
        if not desired_name:
            return {"ok": False, "printer_name": "", "error": "missing_preferred_printer_name"}

        matched_name = resolve_preferred_printer_name(snapshot, desired_name)
        if not matched_name:
            available_names = [
                str((printer or {}).get("Name") or "").strip()
                for printer in (snapshot.get("printers") or [])
                if str((printer or {}).get("Name") or "").strip()
            ]
            return {
                "ok": False,
                "printer_name": "",
                "error": "preferred_printer_not_found",
                "preferred_printer_name": desired_name,
                "available_printers": available_names,
            }

        receipt_text = build_thermal_receipt_text(
            payload if isinstance(payload, dict) else {},
            width=_coerce_receipt_int(printer_config.get("paper_width_chars"), 32),
        )
        if not receipt_text:
            return {"ok": False, "printer_name": matched_name, "error": "receipt_payload_empty"}

        result = print_raw_receipt_to_windows_printer(
            matched_name,
            receipt_text,
            encoding=str(printer_config.get("raw_encoding") or "cp437").strip() or "cp437",
            cut_after_print=bool(printer_config.get("cut_after_print", True)),
            job_name=f"Kasir ERP {str((payload or {}).get('receipt_no') or 'Receipt').strip()}",
        )
        if result.get("ok"):
            self.logger.info(
                "Native thermal receipt printed to %s (%s bytes)",
                matched_name,
                result.get("bytes_written", 0),
            )
        return result


class NativeBridge:
    def __init__(self, runtime: DesktopRuntime, logger: logging.Logger):
        self.runtime = runtime
        self.logger = logger
        self.window = None

    def attach_window(self, window: Any) -> None:
        self.window = window

    def get_app_info(self) -> dict[str, Any]:
        return self.runtime.get_app_info()

    def ping_erp(self) -> dict[str, Any]:
        return self.runtime.ping_erp()

    def open_module(self, module_name: str = "kasir") -> dict[str, Any]:
        target = str(module_name or "kasir").strip() or "kasir"
        url = self.runtime.build_runtime_url(target)
        self.runtime.current_target = target
        if self.window is not None:
            self.window.load_url(url)
        self.logger.info("Open module requested: %s -> %s", target, url)
        return {"ok": True, "target": target, "url": url}

    def open_url(self, url: str) -> dict[str, Any]:
        safe_url = str(url or "").strip()
        if not safe_url:
            return {"ok": False, "error": "missing_url"}
        self.runtime.current_target = safe_url
        runtime_url = _append_query_params(
            safe_url,
            {
                "source": "desktop-kasir",
                "desktop_bridge": self.runtime.bridge_base_url,
            },
        )
        if self.window is not None:
            self.window.load_url(runtime_url)
        self.logger.info("Open URL requested: %s", runtime_url)
        return {"ok": True, "url": runtime_url}

    def reload_page(self) -> dict[str, Any]:
        if self.window is None:
            return {"ok": False, "error": "window_not_ready"}
        self.window.evaluate_js("window.location.reload();")
        return {"ok": True}

    def print_current_page(self) -> dict[str, Any]:
        if self.window is None:
            return {"ok": False, "error": "window_not_ready"}
        self.window.evaluate_js("window.print();")
        return {"ok": True}

    def get_printer_snapshot(self) -> dict[str, Any]:
        return self.runtime.get_printer_snapshot()

    def get_default_printer(self) -> dict[str, Any]:
        return self.runtime.get_default_printer()

    def activate_preferred_printer(self, printer_name: str = "") -> dict[str, Any]:
        return self.runtime.activate_preferred_printer(printer_name)

    def restore_default_printer(self) -> dict[str, Any]:
        return self.runtime.restore_default_printer()

    def print_receipt(self, payload: dict[str, Any], printer_name: str = "") -> dict[str, Any]:
        return self.runtime.print_receipt(payload, printer_name)

    def shutdown(self) -> dict[str, Any]:
        if self.window is not None:
            self.window.destroy()
        return {"ok": True}


def _start_local_bridge_server(
    runtime: DesktopRuntime,
    config: dict[str, Any],
    logger: logging.Logger,
) -> tuple[ThreadingHTTPServer | None, threading.Thread | None, str]:
    bridge_config = config.get("bridge") or {}
    if not bool(bridge_config.get("enabled", True)):
        return None, None, ""

    host = str(bridge_config.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(bridge_config.get("port") or 17844)
    cors_origin = str(bridge_config.get("cors_origin") or "*").strip() or "*"

    class DesktopBridgeHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload: dict[str, Any], status_code: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Requested-With")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length") or 0)
            if content_length <= 0:
                return {}
            raw_body = self.rfile.read(content_length)
            if not raw_body:
                return {}
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except Exception:
                return {}
            return payload if isinstance(payload, dict) else {}

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send_json({"ok": True}, status_code=204)

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_json({"ok": True, "status": "online", "app": runtime.get_app_info()})
                return
            if path == "/app/info":
                self._send_json(runtime.get_app_info())
                return
            if path == "/printer/snapshot":
                self._send_json(runtime.get_printer_snapshot())
                return
            if path == "/printer/default":
                self._send_json(runtime.get_default_printer())
                return
            self._send_json({"ok": False, "error": "not_found"}, status_code=404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            payload = self._read_json_body()
            if path == "/printer/activate-preferred":
                self._send_json(runtime.activate_preferred_printer(payload.get("printer_name") or ""))
                return
            if path == "/printer/restore-default":
                self._send_json(runtime.restore_default_printer())
                return
            if path == "/printer/print-receipt":
                self._send_json(runtime.print_receipt(payload, payload.get("printer_name") or ""))
                return
            self._send_json({"ok": False, "error": "not_found"}, status_code=404)

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.info("Desktop bridge %s - %s", self.address_string(), fmt % args)

    try:
        server = ThreadingHTTPServer((host, port), DesktopBridgeHandler)
    except OSError as exc:
        logger.warning("Desktop bridge gagal dijalankan di %s:%s -> %s", host, port, exc)
        return None, None, ""

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="kasir-desktop-bridge")
    thread.start()
    bridge_base_url = f"http://{host}:{server.server_address[1]}"
    logger.info("Desktop bridge aktif di %s", bridge_base_url)
    return server, thread, bridge_base_url


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kasir ERP Desktop Windows wrapper")
    parser.add_argument("--config", default="", help="Path ke kasir_config.json")
    parser.add_argument("--target", default="kasir", help="Modul awal: kasir, gudang, workspace, login, atau URL/path custom")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app_data_root = _app_data_root()
    app_data_root.mkdir(parents=True, exist_ok=True)
    logger = _configure_logger(app_data_root)
    config, config_path = load_config(args.config or None)
    logger.info("Kasir desktop starting with config: %s", config_path)
    browser_mode = str(((config.get("browser") or {}).get("mode") or "auto")).strip().lower()
    runtime = DesktopRuntime(config=config, logger=logger)
    bridge_server = None
    bridge_thread = None
    bridge_base_url = ""
    try:
        bridge_server, bridge_thread, bridge_base_url = _start_local_bridge_server(runtime, config, logger)
        runtime.attach_bridge_base_url(bridge_base_url)
        initial_url = runtime.build_runtime_url(args.target)

        if browser_mode != "external":
            try:
                import webview
            except ImportError:
                webview = None
                if browser_mode == "webview":
                    logger.warning("pywebview belum tersedia. Fallback ke external browser mode.")
            else:
                storage_path = app_data_root / str((config.get("webview") or {}).get("storage_subdir") or "webview-data")
                storage_path.mkdir(parents=True, exist_ok=True)

                bridge = NativeBridge(runtime=runtime, logger=logger)
                window = webview.create_window(
                    str(config.get("app_name") or "Kasir ERP Desktop"),
                    url=initial_url,
                    js_api=bridge,
                    width=int(((config.get("window") or {}).get("width") or 1440)),
                    height=int(((config.get("window") or {}).get("height") or 920)),
                    resizable=bool((config.get("window") or {}).get("resizable", True)),
                    fullscreen=bool((config.get("window") or {}).get("fullscreen", False)),
                    confirm_close=bool((config.get("window") or {}).get("confirm_close", True)),
                    text_select=bool((config.get("window") or {}).get("text_select", True)),
                )
                bridge.attach_window(window)

                logger.info("Opening ERP target via pywebview: %s", initial_url)
                webview.start(
                    debug=bool((config.get("webview") or {}).get("debug", False)),
                    private_mode=bool((config.get("webview") or {}).get("private_mode", False)),
                    storage_path=str(storage_path),
                )
                return 0

        return _launch_external_browser(
            config=config,
            app_data_root=app_data_root,
            target_url=initial_url,
            logger=logger,
        )
    finally:
        if bridge_server is not None:
            bridge_server.shutdown()
            bridge_server.server_close()
        if bridge_thread is not None:
            bridge_thread.join(timeout=1.5)


if __name__ == "__main__":
    raise SystemExit(run())
