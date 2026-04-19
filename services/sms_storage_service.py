import json
import mimetypes
import os
import shutil
from datetime import datetime, timedelta
from zipfile import ZIP_DEFLATED, ZipFile

from flask import current_app


DEFAULT_SMS_FOLDERS = (
    "Arsip Prioritas",
    "Media Board",
    "Dropzone Masuk",
)
TEXT_PREVIEW_LIMIT_BYTES = 256 * 1024
INVALID_NAME_CHARS = '<>:"/\\|?*\x00'


def _config_int(name, default):
    raw_value = current_app.config.get(name, default)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(default)


def _now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _ensure_directory(path):
    os.makedirs(path, exist_ok=True)
    return path


def get_sms_storage_root():
    configured_root = str(current_app.config.get("SMS_STORAGE_ROOT") or "").strip()
    root_path = configured_root or os.path.join(current_app.instance_path, "sms_storage", "storage")
    return os.path.abspath(_ensure_directory(root_path))


def get_sms_data_root():
    configured_root = str(current_app.config.get("SMS_STORAGE_DATA_ROOT") or "").strip()
    root_path = configured_root or os.path.join(current_app.instance_path, "sms_storage", "data")
    return os.path.abspath(_ensure_directory(root_path))


def _get_sms_temp_root():
    return os.path.join(get_sms_data_root(), "tmp")


def _get_sms_trash_root():
    return os.path.join(get_sms_data_root(), "trash")


def _get_sms_trash_items_root():
    return os.path.join(_get_sms_trash_root(), "items")


def _get_sms_trash_index_path():
    return os.path.join(_get_sms_trash_root(), "index.json")


def _get_sms_activity_path():
    return os.path.join(get_sms_data_root(), "activity.json")


def _get_sms_download_temp_root():
    return os.path.join(_get_sms_temp_root(), "downloads")


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    return payload if isinstance(payload, type(default)) else default


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _cleanup_stale_download_archives():
    temp_root = _ensure_directory(_get_sms_download_temp_root())
    max_age = timedelta(hours=6)
    cutoff = datetime.utcnow() - max_age
    for entry in os.scandir(temp_root):
        try:
            modified = datetime.utcfromtimestamp(entry.stat().st_mtime)
        except OSError:
            continue
        if modified < cutoff:
            try:
                os.remove(entry.path)
            except OSError:
                continue


def ensure_sms_storage_structure():
    storage_root = get_sms_storage_root()
    data_root = get_sms_data_root()
    _ensure_directory(storage_root)
    _ensure_directory(data_root)
    _ensure_directory(_get_sms_temp_root())
    _ensure_directory(_get_sms_trash_root())
    _ensure_directory(_get_sms_trash_items_root())
    _ensure_directory(_get_sms_download_temp_root())

    if not os.path.exists(_get_sms_activity_path()):
        _write_json(_get_sms_activity_path(), [])
    if not os.path.exists(_get_sms_trash_index_path()):
        _write_json(_get_sms_trash_index_path(), [])

    for folder_name in DEFAULT_SMS_FOLDERS:
        _ensure_directory(os.path.join(storage_root, folder_name))

    welcome_file = os.path.join(storage_root, "Mulai di Sini.txt")
    if not os.path.exists(welcome_file):
        with open(welcome_file, "w", encoding="utf-8") as handle:
            handle.write(
                "\n".join(
                    [
                        "Selamat datang di SMS Cloud Storage.",
                        "",
                        "Fitur inti yang tersedia:",
                        "- upload file",
                        "- folder baru",
                        "- rename",
                        "- hapus ke trash",
                        "- restore dari trash",
                        "- preview file ringan",
                    ]
                )
            )

    _cleanup_stale_download_archives()


def format_bytes_compact(size_bytes):
    safe_size = int(max(0, size_bytes or 0))
    if safe_size == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(safe_size)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    precision = 0 if unit_index == 0 else (0 if value >= 100 else 1 if value >= 10 else 2)
    return f"{value:.{precision}f} {units[unit_index]}"


def sanitize_entry_name(name):
    safe_name = str(name or "").strip()
    if not safe_name:
        raise ValueError("Nama tidak boleh kosong.")

    translated = []
    for char in safe_name:
        if char in INVALID_NAME_CHARS or ord(char) < 32:
            translated.append("-")
        else:
            translated.append(char)
    normalized = "".join(translated).strip().rstrip(".")
    if normalized in {"", ".", ".."}:
        raise ValueError("Nama tidak valid.")
    return normalized


def resolve_storage_path(relative_path=""):
    ensure_sms_storage_structure()
    cleaned = str(relative_path or "").replace("\\", "/").strip().strip("/")
    normalized = os.path.normpath(cleaned).replace("\\", "/").strip(".")
    if normalized in {".."} or normalized.startswith("../"):
        raise ValueError("Path tidak valid.")

    root_path = get_sms_storage_root()
    absolute_path = os.path.abspath(os.path.join(root_path, normalized))
    if absolute_path != root_path and not absolute_path.startswith(root_path + os.sep):
        raise ValueError("Akses path ditolak.")
    return {
        "root_path": root_path,
        "absolute_path": absolute_path,
        "relative_path": "" if absolute_path == root_path else os.path.relpath(absolute_path, root_path).replace("\\", "/"),
    }


def _path_exists(relative_path):
    try:
        resolved = resolve_storage_path(relative_path)
    except ValueError:
        return False
    return os.path.exists(resolved["absolute_path"])


def _guess_mime_type(file_name):
    mime_type, _ = mimetypes.guess_type(file_name)
    return mime_type or "application/octet-stream"


def get_file_category(file_name):
    extension = os.path.splitext(str(file_name or "").lower())[1]
    if extension in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
        return "image"
    if extension in {".txt", ".md", ".json", ".csv", ".html", ".css", ".js"}:
        return "text"
    if extension in {".zip", ".rar", ".7z"}:
        return "archive"
    if extension in {".mp4", ".webm", ".mov"}:
        return "video"
    if extension in {".mp3", ".wav", ".ogg"}:
        return "audio"
    if extension in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}:
        return "document"
    return "other"


def is_previewable(file_name, size_bytes):
    category = get_file_category(file_name)
    if category in {"image", "video", "audio", "document"}:
        return True
    if category == "text" and int(size_bytes or 0) <= TEXT_PREVIEW_LIMIT_BYTES:
        return True
    return False


def build_breadcrumbs(relative_path):
    crumbs = [{"label": "Root", "path": ""}]
    safe_path = str(relative_path or "").strip().strip("/")
    if not safe_path:
        return crumbs

    cursor = ""
    for segment in safe_path.split("/"):
        cursor = f"{cursor}/{segment}".strip("/")
        crumbs.append({"label": segment, "path": cursor})
    return crumbs


def _stat_item(relative_path, absolute_path, is_dir):
    stat_result = os.stat(absolute_path)
    size_bytes = 0 if is_dir else int(stat_result.st_size or 0)
    item_name = os.path.basename(absolute_path)
    return {
        "name": item_name,
        "path": relative_path,
        "is_dir": bool(is_dir),
        "size_bytes": size_bytes,
        "size_label": "-" if is_dir else format_bytes_compact(size_bytes),
        "mime_type": None if is_dir else _guess_mime_type(item_name),
        "category": "folder" if is_dir else get_file_category(item_name),
        "updated_at": datetime.utcfromtimestamp(stat_result.st_mtime).isoformat() + "Z",
        "previewable": False if is_dir else is_previewable(item_name, size_bytes),
    }


def list_storage_items(relative_path=""):
    ensure_sms_storage_structure()
    resolved = resolve_storage_path(relative_path)
    absolute_path = resolved["absolute_path"]
    if not os.path.isdir(absolute_path):
        raise FileNotFoundError("Folder tidak ditemukan.")

    items = []
    file_count = 0
    folder_count = 0
    for entry in sorted(os.scandir(absolute_path), key=lambda item: (not item.is_dir(), item.name.lower())):
        entry_relative = "/".join(filter(None, [resolved["relative_path"], entry.name]))
        entry_item = _stat_item(entry_relative, entry.path, entry.is_dir())
        items.append(entry_item)
        if entry_item["is_dir"]:
            folder_count += 1
        else:
            file_count += 1

    return {
        "current_path": resolved["relative_path"],
        "breadcrumbs": build_breadcrumbs(resolved["relative_path"]),
        "items": items,
        "summary": {
            "file_count": file_count,
            "folder_count": folder_count,
        },
    }


def _walk_storage():
    root_path = get_sms_storage_root()
    total_size = 0
    total_files = 0
    total_folders = 0
    for current_root, dirs, files in os.walk(root_path):
        total_folders += len(dirs)
        total_files += len(files)
        for file_name in files:
            file_path = os.path.join(current_root, file_name)
            try:
                total_size += os.path.getsize(file_path)
            except OSError:
                continue
    return total_files, total_folders, total_size


def get_storage_stats():
    ensure_sms_storage_structure()
    total_files, total_folders, total_size = _walk_storage()
    trash_items = list_trash_items()
    return {
        "total_files": total_files,
        "total_folders": total_folders,
        "total_size_bytes": total_size,
        "total_size_label": format_bytes_compact(total_size),
        "max_upload_bytes": _config_int("SMS_STORAGE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024 * 1024),
        "max_upload_label": format_bytes_compact(_config_int("SMS_STORAGE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024 * 1024)),
        "trash_count": len(trash_items),
    }


def read_activity():
    ensure_sms_storage_structure()
    return _load_json(_get_sms_activity_path(), [])


def get_activity_feed(limit=None):
    entries = read_activity()
    safe_limit = limit or _config_int("SMS_STORAGE_ACTIVITY_FEED_LIMIT", 10)
    return entries[: max(1, int(safe_limit))]


def record_activity(action, target_path, detail="", actor=""):
    ensure_sms_storage_structure()
    entries = read_activity()
    entries.insert(
        0,
        {
            "id": f"act-{int(datetime.utcnow().timestamp() * 1000)}",
            "action": str(action or "").strip() or "update",
            "target_path": str(target_path or "").strip(),
            "detail": str(detail or "").strip(),
            "actor": str(actor or "").strip(),
            "timestamp": _now_iso(),
        },
    )
    limit = _config_int("SMS_STORAGE_ACTIVITY_LIMIT", 40)
    _write_json(_get_sms_activity_path(), entries[: max(5, limit)])


def _allocate_unique_target(directory, desired_name):
    base_name = sanitize_entry_name(desired_name)
    stem, extension = os.path.splitext(base_name)
    candidate = os.path.join(directory, base_name)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem} ({counter}){extension}")
        counter += 1
    return candidate


def create_folder(relative_path, name, actor=""):
    resolved = resolve_storage_path(relative_path)
    if not os.path.isdir(resolved["absolute_path"]):
        raise FileNotFoundError("Folder tujuan tidak ditemukan.")

    folder_name = sanitize_entry_name(name)
    target_path = os.path.join(resolved["absolute_path"], folder_name)
    if os.path.exists(target_path):
        raise FileExistsError("Folder dengan nama yang sama sudah ada.")
    os.makedirs(target_path, exist_ok=False)
    entry_path = "/".join(filter(None, [resolved["relative_path"], folder_name]))
    record_activity("folder", entry_path, "Folder baru dibuat", actor)
    return _stat_item(entry_path, target_path, True)


def save_uploaded_files(relative_path, file_storages, actor=""):
    resolved = resolve_storage_path(relative_path)
    if not os.path.isdir(resolved["absolute_path"]):
        raise FileNotFoundError("Folder upload tidak ditemukan.")

    max_upload_bytes = _config_int("SMS_STORAGE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024 * 1024)
    uploaded_items = []
    for file_storage in file_storages or []:
        file_name = sanitize_entry_name(os.path.basename(file_storage.filename or ""))
        target_path = _allocate_unique_target(resolved["absolute_path"], file_name)
        file_storage.save(target_path)
        size_bytes = os.path.getsize(target_path)
        if size_bytes > max_upload_bytes:
            os.remove(target_path)
            raise ValueError(f"Ukuran file melebihi batas {format_bytes_compact(max_upload_bytes)}.")
        entry_relative = "/".join(
            filter(None, [resolved["relative_path"], os.path.basename(target_path)])
        )
        uploaded_items.append(_stat_item(entry_relative, target_path, False))
        record_activity("upload", entry_relative, f"Upload {file_name}", actor)
    return uploaded_items


def rename_item(relative_path, new_name, actor=""):
    resolved = resolve_storage_path(relative_path)
    source_path = resolved["absolute_path"]
    if not os.path.exists(source_path):
        raise FileNotFoundError("Item tidak ditemukan.")
    if resolved["relative_path"] == "":
        raise ValueError("Root tidak bisa diubah namanya.")

    parent_path = os.path.dirname(source_path)
    desired_name = sanitize_entry_name(new_name)
    target_path = os.path.join(parent_path, desired_name)
    if os.path.abspath(target_path) == os.path.abspath(source_path):
        return _stat_item(resolved["relative_path"], source_path, os.path.isdir(source_path))
    if os.path.exists(target_path):
        raise FileExistsError("Nama baru sudah dipakai.")

    os.rename(source_path, target_path)
    new_relative = "/".join(
        filter(None, [os.path.dirname(resolved["relative_path"]).replace("\\", "/").strip("/"), desired_name])
    )
    record_activity("rename", new_relative, f"Rename dari {os.path.basename(source_path)}", actor)
    return _stat_item(new_relative, target_path, os.path.isdir(target_path))


def _get_path_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total_size = 0
    for current_root, _, files in os.walk(path):
        for file_name in files:
            try:
                total_size += os.path.getsize(os.path.join(current_root, file_name))
            except OSError:
                continue
    return total_size


def _collapse_nested_paths(relative_paths):
    normalized = sorted(
        {str(item or "").replace("\\", "/").strip().strip("/") for item in relative_paths if str(item or "").strip()},
        key=lambda item: (len(item.split("/")), item.lower()),
    )
    collapsed = []
    for path_item in normalized:
        if any(path_item == parent or path_item.startswith(parent + "/") for parent in collapsed):
            continue
        collapsed.append(path_item)
    return collapsed


def list_trash_items():
    ensure_sms_storage_structure()
    records = _load_json(_get_sms_trash_index_path(), [])
    return sorted(records, key=lambda item: item.get("deleted_at", ""), reverse=True)


def _write_trash_items(items):
    _write_json(_get_sms_trash_index_path(), items)


def delete_items(relative_paths, actor=""):
    ensure_sms_storage_structure()
    trash_root = _ensure_directory(_get_sms_trash_items_root())
    items_to_delete = _collapse_nested_paths(relative_paths)
    deleted_items = []
    trash_items = list_trash_items()
    for relative_path in items_to_delete:
        resolved = resolve_storage_path(relative_path)
        source_path = resolved["absolute_path"]
        if not os.path.exists(source_path):
            continue
        if resolved["relative_path"] == "":
            raise ValueError("Root tidak bisa dihapus.")

        entry_id = f"trash-{int(datetime.utcnow().timestamp() * 1000)}-{os.urandom(4).hex()}"
        trash_name = f"{entry_id}-{os.path.basename(source_path)}"
        trash_path = os.path.join(trash_root, trash_name)
        shutil.move(source_path, trash_path)
        record = {
            "id": entry_id,
            "name": os.path.basename(source_path),
            "original_path": resolved["relative_path"],
            "trash_name": trash_name,
            "is_dir": os.path.isdir(trash_path),
            "size_bytes": _get_path_size(trash_path),
            "size_label": format_bytes_compact(_get_path_size(trash_path)),
            "deleted_at": _now_iso(),
            "actor": str(actor or "").strip(),
        }
        trash_items.insert(0, record)
        deleted_items.append(record)
        record_activity("delete", resolved["relative_path"], "Dipindahkan ke trash", actor)
    _write_trash_items(trash_items)
    return deleted_items


def restore_trash_item(item_id, actor=""):
    trash_items = list_trash_items()
    target_item = next((item for item in trash_items if str(item.get("id")) == str(item_id)), None)
    if not target_item:
        raise FileNotFoundError("Item trash tidak ditemukan.")

    trash_path = os.path.join(_get_sms_trash_items_root(), target_item["trash_name"])
    if not os.path.exists(trash_path):
        raise FileNotFoundError("File trash fisik tidak ditemukan.")

    original_path = resolve_storage_path(target_item.get("original_path") or "")
    original_parent = os.path.dirname(original_path["absolute_path"])
    _ensure_directory(original_parent)
    restored_target = _allocate_unique_target(original_parent, target_item.get("name") or os.path.basename(trash_path))
    shutil.move(trash_path, restored_target)
    trash_items = [item for item in trash_items if str(item.get("id")) != str(item_id)]
    _write_trash_items(trash_items)
    restored_relative = os.path.relpath(restored_target, get_sms_storage_root()).replace("\\", "/")
    record_activity("restore", restored_relative, "Dipulihkan dari trash", actor)
    return _stat_item(restored_relative, restored_target, os.path.isdir(restored_target))


def empty_trash(actor=""):
    removed_count = 0
    for item in list_trash_items():
        trash_path = os.path.join(_get_sms_trash_items_root(), item.get("trash_name") or "")
        if os.path.isdir(trash_path):
            shutil.rmtree(trash_path, ignore_errors=True)
            removed_count += 1
        elif os.path.exists(trash_path):
            try:
                os.remove(trash_path)
                removed_count += 1
            except OSError:
                continue
    _write_trash_items([])
    record_activity("trash", "", "Trash dikosongkan", actor)
    return removed_count


def build_download_payload(relative_path):
    resolved = resolve_storage_path(relative_path)
    target_path = resolved["absolute_path"]
    if not os.path.exists(target_path):
        raise FileNotFoundError("Item tidak ditemukan.")

    if os.path.isfile(target_path):
        return {
            "path": target_path,
            "download_name": os.path.basename(target_path),
            "cleanup_after": False,
        }

    archive_name = f"{os.path.basename(target_path) or 'folder'}-{int(datetime.utcnow().timestamp())}.zip"
    archive_path = os.path.join(_get_sms_download_temp_root(), archive_name)
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as zip_handle:
        for current_root, _, files in os.walk(target_path):
            for file_name in files:
                absolute_file = os.path.join(current_root, file_name)
                relative_file = os.path.relpath(absolute_file, target_path)
                zip_handle.write(absolute_file, arcname=os.path.join(os.path.basename(target_path), relative_file))
    return {
        "path": archive_path,
        "download_name": archive_name,
        "cleanup_after": True,
    }


def build_preview_payload(relative_path):
    resolved = resolve_storage_path(relative_path)
    target_path = resolved["absolute_path"]
    if not os.path.isfile(target_path):
        raise FileNotFoundError("File preview tidak ditemukan.")

    file_name = os.path.basename(target_path)
    size_bytes = os.path.getsize(target_path)
    if not is_previewable(file_name, size_bytes):
        raise ValueError("File ini tidak mendukung preview.")

    return {
        "path": target_path,
        "mime_type": _guess_mime_type(file_name),
        "category": get_file_category(file_name),
        "size_bytes": size_bytes,
    }
