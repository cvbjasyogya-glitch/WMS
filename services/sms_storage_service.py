import json
import mimetypes
import os
import shutil
from datetime import datetime, timedelta, timezone
from zipfile import ZIP_DEFLATED, ZipFile

from flask import current_app, has_request_context, session


DEFAULT_SMS_FOLDERS = (
    "Arsip Prioritas",
    "Media Board",
    "Dropzone Masuk",
)
DEFAULT_SMS_USER_QUOTA_BYTES = 500 * 1024 * 1024
TEXT_PREVIEW_LIMIT_BYTES = 256 * 1024
INVALID_NAME_CHARS = '<>:"/\\|?*\x00'


def _config_int(name, default):
    raw_value = current_app.config.get(name, default)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(default)


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_directory(path):
    os.makedirs(path, exist_ok=True)
    return path


def _get_sms_user_namespace():
    if not has_request_context():
        return "shared"
    raw_user_id = session.get("user_id")
    if raw_user_id is None:
        return "shared"
    return f"user_{str(raw_user_id).strip() or 'shared'}"


def _get_current_sms_user_id():
    if not has_request_context():
        return 0
    try:
        return int(session.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def _get_current_sms_username():
    if not has_request_context():
        return ""
    return str(session.get("username") or "").strip()


def get_sms_storage_base_root():
    configured_root = str(current_app.config.get("SMS_STORAGE_ROOT") or "").strip()
    root_path = configured_root or os.path.join(current_app.instance_path, "sms_storage", "storage")
    return os.path.abspath(_ensure_directory(root_path))


def get_sms_storage_root():
    root_path = os.path.join(get_sms_storage_base_root(), _get_sms_user_namespace())
    return os.path.abspath(_ensure_directory(root_path))


def get_sms_data_base_root():
    configured_root = str(current_app.config.get("SMS_STORAGE_DATA_ROOT") or "").strip()
    root_path = configured_root or os.path.join(current_app.instance_path, "sms_storage", "data")
    return os.path.abspath(_ensure_directory(root_path))


def get_sms_data_root():
    root_path = os.path.join(get_sms_data_base_root(), _get_sms_user_namespace())
    return os.path.abspath(_ensure_directory(root_path))


def get_sms_storage_root_for_user(user_id):
    try:
        safe_user_id = int(user_id or 0)
    except (TypeError, ValueError):
        safe_user_id = 0
    if safe_user_id <= 0:
        raise ValueError("User storage tidak valid.")
    root_path = os.path.join(get_sms_storage_base_root(), f"user_{safe_user_id}")
    return os.path.abspath(_ensure_directory(root_path))


def _get_sms_shared_registry_path():
    return os.path.join(get_sms_data_base_root(), "_shared_registry.json")


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


def _get_sms_starred_path():
    return os.path.join(get_sms_data_root(), "starred.json")


def _get_sms_shared_path():
    return os.path.join(get_sms_data_root(), "shared.json")


def _get_sms_shortcuts_path():
    return os.path.join(get_sms_data_root(), "shortcuts.json")


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
    cutoff = datetime.now(timezone.utc) - max_age
    for entry in os.scandir(temp_root):
        try:
            modified = datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        if modified < cutoff:
            try:
                os.remove(entry.path)
            except OSError:
                continue


def _get_sms_user_quota_bytes():
    return _config_int("SMS_STORAGE_PER_USER_QUOTA_BYTES", DEFAULT_SMS_USER_QUOTA_BYTES)


def _normalize_storage_relative_path(relative_path):
    return str(relative_path or "").replace("\\", "/").strip().strip("/")


def _write_starred_paths(paths):
    normalized = []
    seen = set()
    for path in paths or []:
        safe_path = _normalize_storage_relative_path(path)
        if not safe_path or safe_path in seen:
            continue
        normalized.append(safe_path)
        seen.add(safe_path)
    _write_json(_get_sms_starred_path(), normalized)


def _read_starred_paths():
    ensure_sms_storage_structure()
    saved_paths = _load_json(_get_sms_starred_path(), [])
    normalized = []
    seen = set()
    for path in saved_paths:
        safe_path = _normalize_storage_relative_path(path)
        if not safe_path or safe_path in seen:
            continue
        normalized.append(safe_path)
        seen.add(safe_path)
    return normalized


def _load_starred_paths():
    saved_paths = _read_starred_paths()
    normalized = []
    changed = False
    for path in saved_paths:
        if not _path_exists(path):
            changed = True
            continue
        normalized.append(path)
    if changed or normalized != saved_paths:
        _write_starred_paths(normalized)
    return normalized


def _load_starred_lookup():
    return set(_load_starred_paths())


def _remove_starred_prefix(relative_path):
    safe_path = _normalize_storage_relative_path(relative_path)
    if not safe_path:
        return
    starred_paths = _load_starred_paths()
    filtered_paths = [
        path for path in starred_paths
        if path != safe_path and not path.startswith(f"{safe_path}/")
    ]
    if filtered_paths != starred_paths:
        _write_starred_paths(filtered_paths)


def _replace_starred_prefix(old_relative_path, new_relative_path):
    old_prefix = _normalize_storage_relative_path(old_relative_path)
    new_prefix = _normalize_storage_relative_path(new_relative_path)
    if not old_prefix or not new_prefix or old_prefix == new_prefix:
        return
    starred_paths = _read_starred_paths()
    updated_paths = []
    changed = False
    for path in starred_paths:
        if path == old_prefix or path.startswith(f"{old_prefix}/"):
            suffix = path[len(old_prefix):].lstrip("/")
            replacement = "/".join(filter(None, [new_prefix, suffix]))
            if replacement:
                updated_paths.append(replacement)
            changed = True
            continue
        updated_paths.append(path)
    if changed:
        _write_starred_paths(updated_paths)


def _write_shared_paths(paths):
    normalized = []
    seen = set()
    for path in paths or []:
        safe_path = _normalize_storage_relative_path(path)
        if not safe_path or safe_path in seen:
            continue
        normalized.append(safe_path)
        seen.add(safe_path)
    _write_json(_get_sms_shared_path(), normalized)


def _read_shared_paths():
    ensure_sms_storage_structure()
    saved_paths = _load_json(_get_sms_shared_path(), [])
    normalized = []
    seen = set()
    for path in saved_paths:
        safe_path = _normalize_storage_relative_path(path)
        if not safe_path or safe_path in seen:
            continue
        normalized.append(safe_path)
        seen.add(safe_path)
    return normalized


def _load_shared_paths():
    saved_paths = _read_shared_paths()
    normalized = []
    changed = False
    for path in saved_paths:
        if not _path_exists(path):
            changed = True
            continue
        normalized.append(path)
    if changed or normalized != saved_paths:
        _write_shared_paths(normalized)
    return normalized


def _load_shared_lookup():
    shared_lookup = set(_load_shared_paths())
    shared_lookup.update(_load_outgoing_shared_paths())
    return shared_lookup


def _remove_shared_prefix(relative_path):
    safe_path = _normalize_storage_relative_path(relative_path)
    if not safe_path:
        return
    shared_paths = _load_shared_paths()
    filtered_paths = [
        path for path in shared_paths
        if path != safe_path and not path.startswith(f"{safe_path}/")
    ]
    if filtered_paths != shared_paths:
        _write_shared_paths(filtered_paths)


def _replace_shared_prefix(old_relative_path, new_relative_path):
    old_prefix = _normalize_storage_relative_path(old_relative_path)
    new_prefix = _normalize_storage_relative_path(new_relative_path)
    if not old_prefix or not new_prefix or old_prefix == new_prefix:
        return
    shared_paths = _read_shared_paths()
    updated_paths = []
    changed = False
    for path in shared_paths:
        if path == old_prefix or path.startswith(f"{old_prefix}/"):
            suffix = path[len(old_prefix):].lstrip("/")
            replacement = "/".join(filter(None, [new_prefix, suffix]))
            if replacement:
                updated_paths.append(replacement)
            changed = True
            continue
        updated_paths.append(path)
    if changed:
        _write_shared_paths(updated_paths)


def _normalize_share_recipient(entry):
    if not isinstance(entry, dict):
        return None
    try:
        user_id = int(entry.get("user_id") or entry.get("userId") or 0)
    except (TypeError, ValueError):
        user_id = 0
    username = str(entry.get("username") or "").strip()
    if user_id <= 0 or not username:
        return None
    return {
        "user_id": user_id,
        "userId": user_id,
        "username": username,
    }


def _normalize_share_entry(entry):
    if not isinstance(entry, dict):
        return None
    entry_id = str(entry.get("id") or "").strip() or f"share-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{os.urandom(3).hex()}"
    try:
        owner_user_id = int(entry.get("owner_user_id") or entry.get("ownerUserId") or 0)
    except (TypeError, ValueError):
        owner_user_id = 0
    owner_username = str(entry.get("owner_username") or entry.get("ownerUsername") or "").strip()
    target_path = _normalize_storage_relative_path(entry.get("target_path") or entry.get("targetPath"))
    if owner_user_id <= 0 or not owner_username or not target_path:
        return None
    recipients = []
    seen_recipient_ids = set()
    for recipient in entry.get("recipients") or []:
        safe_recipient = _normalize_share_recipient(recipient)
        if not safe_recipient or safe_recipient["user_id"] in seen_recipient_ids:
            continue
        recipients.append(safe_recipient)
        seen_recipient_ids.add(safe_recipient["user_id"])
    if not recipients:
        return None
    timestamp = _now_iso()
    created_at = str(entry.get("created_at") or entry.get("createdAt") or "").strip() or timestamp
    updated_at = str(entry.get("updated_at") or entry.get("updatedAt") or "").strip() or created_at
    label = str(entry.get("label") or "").strip() or os.path.basename(target_path) or "Shared Item"
    return {
        "id": entry_id,
        "owner_user_id": owner_user_id,
        "ownerUserId": owner_user_id,
        "owner_username": owner_username,
        "ownerUsername": owner_username,
        "target_path": target_path,
        "targetPath": target_path,
        "label": label,
        "recipients": recipients,
        "created_at": created_at,
        "createdAt": created_at,
        "updated_at": updated_at,
        "updatedAt": updated_at,
    }


def _write_share_registry(entries):
    normalized = []
    seen_entry_ids = set()
    for entry in entries or []:
        safe_entry = _normalize_share_entry(entry)
        if not safe_entry or safe_entry["id"] in seen_entry_ids:
            continue
        normalized.append(safe_entry)
        seen_entry_ids.add(safe_entry["id"])
    _write_json(_get_sms_shared_registry_path(), normalized)


def _read_share_registry():
    ensure_sms_storage_structure()
    saved_entries = _load_json(_get_sms_shared_registry_path(), [])
    normalized = []
    seen_entry_ids = set()
    for entry in saved_entries:
        safe_entry = _normalize_share_entry(entry)
        if not safe_entry or safe_entry["id"] in seen_entry_ids:
            continue
        normalized.append(safe_entry)
        seen_entry_ids.add(safe_entry["id"])
    return normalized


def _resolve_user_storage_path(user_id, relative_path=""):
    safe_relative_path = _normalize_storage_relative_path(relative_path)
    base_root = get_sms_storage_root_for_user(user_id)
    if not safe_relative_path:
        return base_root
    absolute_path = os.path.abspath(os.path.join(base_root, safe_relative_path))
    if absolute_path != base_root and not absolute_path.startswith(base_root + os.sep):
        raise ValueError("Akses share ditolak.")
    return absolute_path


def _path_exists_for_user(user_id, relative_path):
    try:
        absolute_path = _resolve_user_storage_path(user_id, relative_path)
    except ValueError:
        return False
    return os.path.exists(absolute_path)


def _load_share_registry():
    saved_entries = _read_share_registry()
    normalized = []
    changed = False
    for entry in saved_entries:
        if not _path_exists_for_user(entry["owner_user_id"], entry["target_path"]):
            changed = True
            continue
        recipients = []
        seen_recipient_ids = set()
        for recipient in entry.get("recipients") or []:
            safe_recipient = _normalize_share_recipient(recipient)
            if not safe_recipient or safe_recipient["user_id"] in seen_recipient_ids:
                changed = True
                continue
            recipients.append(safe_recipient)
            seen_recipient_ids.add(safe_recipient["user_id"])
        if not recipients:
            changed = True
            continue
        if recipients != (entry.get("recipients") or []):
            changed = True
        normalized.append({**entry, "recipients": recipients})
    if changed or normalized != saved_entries:
        _write_share_registry(normalized)
    return normalized


def _load_outgoing_shared_paths(owner_user_id=None):
    try:
        safe_owner_user_id = int(owner_user_id or _get_current_sms_user_id() or 0)
    except (TypeError, ValueError):
        safe_owner_user_id = 0
    if safe_owner_user_id <= 0:
        return []
    shared_paths = []
    seen_paths = set()
    for entry in _load_share_registry():
        if int(entry["owner_user_id"]) != safe_owner_user_id:
            continue
        target_path = _normalize_storage_relative_path(entry.get("target_path"))
        if not target_path or target_path in seen_paths:
            continue
        shared_paths.append(target_path)
        seen_paths.add(target_path)
    return shared_paths


def _build_outgoing_share_recipient_map(owner_user_id=None):
    try:
        safe_owner_user_id = int(owner_user_id or _get_current_sms_user_id() or 0)
    except (TypeError, ValueError):
        safe_owner_user_id = 0
    if safe_owner_user_id <= 0:
        return {}
    payload = {}
    for entry in _load_share_registry():
        if int(entry["owner_user_id"]) != safe_owner_user_id:
            continue
        target_path = _normalize_storage_relative_path(entry.get("target_path"))
        if not target_path:
            continue
        payload[target_path] = {
            "share_id": entry["id"],
            "shareId": entry["id"],
            "shared_recipients": [dict(recipient or {}) for recipient in entry.get("recipients") or []],
            "sharedRecipients": [dict(recipient or {}) for recipient in entry.get("recipients") or []],
            "shared_direction": "outgoing",
            "sharedDirection": "outgoing",
            "can_manage_share": True,
            "canManageShare": True,
            "shared_external": False,
            "sharedExternal": False,
            "shared_owner_user_id": int(entry["owner_user_id"]),
            "sharedOwnerUserId": int(entry["owner_user_id"]),
            "shared_owner_username": entry.get("owner_username") or "",
            "sharedOwnerUsername": entry.get("owner_username") or "",
        }
    return payload


def _remove_share_registry_prefix(relative_path, owner_user_id=None):
    safe_path = _normalize_storage_relative_path(relative_path)
    try:
        safe_owner_user_id = int(owner_user_id or _get_current_sms_user_id() or 0)
    except (TypeError, ValueError):
        safe_owner_user_id = 0
    if not safe_path or safe_owner_user_id <= 0:
        return
    registry = _load_share_registry()
    filtered_entries = []
    changed = False
    for entry in registry:
        if int(entry["owner_user_id"]) != safe_owner_user_id:
            filtered_entries.append(entry)
            continue
        target_path = _normalize_storage_relative_path(entry.get("target_path"))
        if target_path == safe_path or target_path.startswith(f"{safe_path}/"):
            changed = True
            continue
        filtered_entries.append(entry)
    if changed:
        _write_share_registry(filtered_entries)


def _replace_share_registry_prefix(old_relative_path, new_relative_path, owner_user_id=None):
    old_prefix = _normalize_storage_relative_path(old_relative_path)
    new_prefix = _normalize_storage_relative_path(new_relative_path)
    try:
        safe_owner_user_id = int(owner_user_id or _get_current_sms_user_id() or 0)
    except (TypeError, ValueError):
        safe_owner_user_id = 0
    if not old_prefix or not new_prefix or old_prefix == new_prefix or safe_owner_user_id <= 0:
        return
    registry = _read_share_registry()
    updated_entries = []
    changed = False
    for entry in registry:
        if int(entry["owner_user_id"]) != safe_owner_user_id:
            updated_entries.append(entry)
            continue
        target_path = _normalize_storage_relative_path(entry.get("target_path"))
        if target_path == old_prefix or target_path.startswith(f"{old_prefix}/"):
            suffix = target_path[len(old_prefix):].lstrip("/")
            replacement = "/".join(filter(None, [new_prefix, suffix]))
            entry = {
                **entry,
                "target_path": replacement,
                "targetPath": replacement,
                "label": os.path.basename(replacement) or entry.get("label") or "Shared Item",
                "updated_at": _now_iso(),
                "updatedAt": _now_iso(),
            }
            changed = True
        updated_entries.append(entry)
    if changed:
        _write_share_registry(updated_entries)


def _get_accessible_share_entry(share_id):
    safe_share_id = str(share_id or "").strip()
    if not safe_share_id:
        raise FileNotFoundError("Share tidak ditemukan.")
    current_user_id = _get_current_sms_user_id()
    if current_user_id <= 0:
        raise FileNotFoundError("Share tidak ditemukan.")
    for entry in _load_share_registry():
        if entry["id"] != safe_share_id:
            continue
        if int(entry["owner_user_id"]) == current_user_id:
            return entry
        if any(int(recipient["user_id"]) == current_user_id for recipient in entry.get("recipients") or []):
            return entry
    raise FileNotFoundError("Share tidak ditemukan.")


def _resolve_share_target(entry, relative_path=""):
    if not entry:
        raise FileNotFoundError("Share tidak ditemukan.")
    safe_relative_path = _normalize_storage_relative_path(relative_path)
    share_root = _resolve_user_storage_path(entry["owner_user_id"], entry["target_path"])
    if not safe_relative_path:
        return share_root
    absolute_path = os.path.abspath(os.path.join(share_root, safe_relative_path))
    if absolute_path != share_root and not absolute_path.startswith(share_root + os.sep):
        raise ValueError("Akses share ditolak.")
    return absolute_path


def _stat_shared_item(entry, relative_path=""):
    target_path = _resolve_share_target(entry, relative_path)
    if not os.path.exists(target_path):
        raise FileNotFoundError("Item share tidak ditemukan.")
    is_dir = os.path.isdir(target_path)
    stat_result = os.stat(target_path)
    size_bytes = 0 if is_dir else int(stat_result.st_size or 0)
    item_name = os.path.basename(target_path)
    updated_at = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    extension = "" if is_dir else os.path.splitext(item_name)[1].lstrip(".").lower()
    category = "folder" if is_dir else get_file_category(item_name)
    share_relative_path = _normalize_storage_relative_path(relative_path)
    return {
        "id": f"share:{entry['id']}:{share_relative_path or '_root'}",
        "name": item_name,
        "path": share_relative_path,
        "is_dir": bool(is_dir),
        "kind": "folder" if is_dir else "file",
        "size_bytes": size_bytes,
        "size": None if is_dir else size_bytes,
        "size_label": "-" if is_dir else format_bytes_compact(size_bytes),
        "mime_type": None if is_dir else _guess_mime_type(item_name),
        "category": category,
        "extension": extension,
        "updated_at": updated_at,
        "updatedAt": updated_at,
        "previewable": False if is_dir else is_previewable(item_name, size_bytes),
        "starred": False,
        "shared": True,
        "shared_external": True,
        "sharedExternal": True,
        "share_id": entry["id"],
        "shareId": entry["id"],
        "share_relative_path": share_relative_path,
        "shareRelativePath": share_relative_path,
        "shared_owner_user_id": int(entry["owner_user_id"]),
        "sharedOwnerUserId": int(entry["owner_user_id"]),
        "shared_owner_username": entry.get("owner_username") or "",
        "sharedOwnerUsername": entry.get("owner_username") or "",
        "shared_direction": "incoming",
        "sharedDirection": "incoming",
        "can_manage_share": False,
        "canManageShare": False,
        "shortcut": False,
        "trashed": False,
    }


def _normalize_shortcut_entry(entry):
    if not isinstance(entry, dict):
        return None
    target_path = _normalize_storage_relative_path(entry.get("target_path") or entry.get("targetPath"))
    if not target_path:
        return None
    entry_id = str(entry.get("id") or "").strip() or f"shortcut-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{os.urandom(3).hex()}"
    timestamp = _now_iso()
    label = str(entry.get("label") or "").strip() or os.path.basename(target_path)
    parent_path = _normalize_storage_relative_path(entry.get("parent_path") or entry.get("parentPath"))
    created_at = str(entry.get("created_at") or entry.get("createdAt") or "").strip() or timestamp
    updated_at = str(entry.get("updated_at") or entry.get("updatedAt") or "").strip() or created_at
    return {
        "id": entry_id,
        "target_path": target_path,
        "parent_path": parent_path,
        "label": label,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _write_shortcuts(entries):
    normalized = []
    seen_ids = set()
    for entry in entries or []:
        safe_entry = _normalize_shortcut_entry(entry)
        if not safe_entry or safe_entry["id"] in seen_ids:
            continue
        normalized.append(safe_entry)
        seen_ids.add(safe_entry["id"])
    _write_json(_get_sms_shortcuts_path(), normalized)


def _read_shortcuts():
    ensure_sms_storage_structure()
    saved_entries = _load_json(_get_sms_shortcuts_path(), [])
    normalized = []
    seen_ids = set()
    for entry in saved_entries:
        safe_entry = _normalize_shortcut_entry(entry)
        if not safe_entry or safe_entry["id"] in seen_ids:
            continue
        normalized.append(safe_entry)
        seen_ids.add(safe_entry["id"])
    return normalized


def _load_shortcuts():
    saved_entries = _read_shortcuts()
    normalized = []
    changed = False
    seen_targets = set()
    for entry in saved_entries:
        target_path = entry["target_path"]
        target_key = (
            target_path,
            _normalize_storage_relative_path(entry.get("parent_path") or ""),
        )
        if target_key in seen_targets:
            changed = True
            continue
        if not _path_exists(target_path):
            changed = True
            continue
        normalized.append(entry)
        seen_targets.add(target_key)
    if changed or normalized != saved_entries:
        _write_shortcuts(normalized)
    return normalized


def _remove_shortcuts_prefix(relative_path):
    safe_path = _normalize_storage_relative_path(relative_path)
    if not safe_path:
        return
    shortcuts = _load_shortcuts()
    filtered_entries = [
        entry for entry in shortcuts
        if entry["target_path"] != safe_path and not entry["target_path"].startswith(f"{safe_path}/")
    ]
    if filtered_entries != shortcuts:
        _write_shortcuts(filtered_entries)


def _replace_shortcuts_prefix(old_relative_path, new_relative_path):
    old_prefix = _normalize_storage_relative_path(old_relative_path)
    new_prefix = _normalize_storage_relative_path(new_relative_path)
    if not old_prefix or not new_prefix or old_prefix == new_prefix:
        return
    shortcuts = _read_shortcuts()
    updated_entries = []
    changed = False
    for entry in shortcuts:
        target_path = entry["target_path"]
        if target_path == old_prefix or target_path.startswith(f"{old_prefix}/"):
            suffix = target_path[len(old_prefix):].lstrip("/")
            replacement = "/".join(filter(None, [new_prefix, suffix]))
            entry = {
                **entry,
                "target_path": replacement,
                "updated_at": _now_iso(),
            }
            if entry.get("label") == os.path.basename(target_path):
                entry["label"] = os.path.basename(replacement) or entry["label"]
            changed = True
        updated_entries.append(entry)
    if changed:
        _write_shortcuts(updated_entries)


def _sort_storage_items(items):
    return sorted(
        items,
        key=lambda item: (
            item.get("kind") != "folder",
            str(item.get("name") or "").lower(),
        ),
    )


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
    if not os.path.exists(_get_sms_starred_path()):
        _write_json(_get_sms_starred_path(), [])
    if not os.path.exists(_get_sms_shared_path()):
        _write_json(_get_sms_shared_path(), [])
    if not os.path.exists(_get_sms_shortcuts_path()):
        _write_json(_get_sms_shortcuts_path(), [])

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


def _stat_item(relative_path, absolute_path, is_dir, starred_paths=None, shared_paths=None, shared_recipient_map=None):
    stat_result = os.stat(absolute_path)
    size_bytes = 0 if is_dir else int(stat_result.st_size or 0)
    item_name = os.path.basename(absolute_path)
    updated_at = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    extension = "" if is_dir else os.path.splitext(item_name)[1].lstrip(".").lower()
    category = "folder" if is_dir else get_file_category(item_name)
    relative_key = _normalize_storage_relative_path(relative_path)
    starred_lookup = starred_paths if starred_paths is not None else _load_starred_lookup()
    shared_lookup = shared_paths if shared_paths is not None else _load_shared_lookup()
    recipient_lookup = shared_recipient_map if shared_recipient_map is not None else _build_outgoing_share_recipient_map()
    share_meta = dict(recipient_lookup.get(relative_key) or {})
    return {
        "name": item_name,
        "path": relative_path,
        "is_dir": bool(is_dir),
        "kind": "folder" if is_dir else "file",
        "size_bytes": size_bytes,
        "size": None if is_dir else size_bytes,
        "size_label": "-" if is_dir else format_bytes_compact(size_bytes),
        "mime_type": None if is_dir else _guess_mime_type(item_name),
        "category": category,
        "extension": extension,
        "updated_at": updated_at,
        "updatedAt": updated_at,
        "previewable": False if is_dir else is_previewable(item_name, size_bytes),
        "starred": relative_key in starred_lookup,
        "shared": relative_key in shared_lookup,
        "shortcut": False,
        "trashed": False,
        **share_meta,
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
    starred_paths = _load_starred_lookup()
    shared_paths = _load_shared_lookup()
    shared_recipient_map = _build_outgoing_share_recipient_map()
    for entry in sorted(os.scandir(absolute_path), key=lambda item: (not item.is_dir(), item.name.lower())):
        if entry.name == ".gitkeep":
            continue
        entry_relative = "/".join(filter(None, [resolved["relative_path"], entry.name]))
        entry_item = _stat_item(
            entry_relative,
            entry.path,
            entry.is_dir(),
            starred_paths=starred_paths,
            shared_paths=shared_paths,
            shared_recipient_map=shared_recipient_map,
        )
        items.append(entry_item)
        if entry_item["is_dir"]:
            folder_count += 1
        else:
            file_count += 1

    return {
        "current_path": resolved["relative_path"],
        "currentPath": resolved["relative_path"],
        "parent_path": os.path.dirname(resolved["relative_path"]).replace("\\", "/").strip("/"),
        "parentPath": os.path.dirname(resolved["relative_path"]).replace("\\", "/").strip("/"),
        "breadcrumbs": build_breadcrumbs(resolved["relative_path"]),
        "items": items,
        "summary": {
            "file_count": file_count,
            "folder_count": folder_count,
            "fileCount": file_count,
            "folderCount": folder_count,
        },
    }


def _walk_storage():
    root_path = get_sms_storage_root()
    total_size = 0
    total_files = 0
    total_folders = 0
    for current_root, dirs, files in os.walk(root_path):
        visible_dirs = [directory for directory in dirs if directory != ".gitkeep"]
        total_folders += len(visible_dirs)
        total_files += len(files)
        for file_name in files:
            if file_name == ".gitkeep":
                total_files -= 1
                continue
            file_path = os.path.join(current_root, file_name)
            try:
                total_size += os.path.getsize(file_path)
            except OSError:
                continue
    return total_files, total_folders, total_size


def _collect_storage_catalog():
    root_path = get_sms_storage_root()
    items = []
    starred_paths = _load_starred_lookup()
    shared_paths = _load_shared_lookup()
    shared_recipient_map = _build_outgoing_share_recipient_map()
    for current_root, dirs, files in os.walk(root_path):
        dirs[:] = [directory for directory in dirs if directory != ".gitkeep"]
        files = [file_name for file_name in files if file_name != ".gitkeep"]
        relative_root = os.path.relpath(current_root, root_path).replace("\\", "/")
        if relative_root == ".":
            relative_root = ""
        for directory in dirs:
            relative_path = "/".join(filter(None, [relative_root, directory]))
            items.append(
                _stat_item(
                    relative_path,
                    os.path.join(current_root, directory),
                    True,
                    starred_paths=starred_paths,
                    shared_paths=shared_paths,
                    shared_recipient_map=shared_recipient_map,
                )
            )
        for file_name in files:
            relative_path = "/".join(filter(None, [relative_root, file_name]))
            items.append(
                _stat_item(
                    relative_path,
                    os.path.join(current_root, file_name),
                    False,
                    starred_paths=starred_paths,
                    shared_paths=shared_paths,
                    shared_recipient_map=shared_recipient_map,
                )
            )
    return items


def build_recent_items_payload(limit=60):
    items = [item for item in _collect_storage_catalog() if not item.get("is_dir")]
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    limited_items = items[: max(1, int(limit or 60))]
    return {
        "current_path": "",
        "currentPath": "",
        "parent_path": "",
        "parentPath": "",
        "breadcrumbs": [{"label": "Recent", "path": ""}],
        "summary": {
            "file_count": len(limited_items),
            "folder_count": 0,
            "fileCount": len(limited_items),
            "folderCount": 0,
        },
        "items": limited_items,
    }


def build_storage_index_payload():
    items = _sort_storage_items(_collect_storage_catalog())
    file_count = len([item for item in items if item.get("kind") == "file"])
    folder_count = len([item for item in items if item.get("kind") == "folder"])
    return {
        "current_path": "",
        "currentPath": "",
        "parent_path": "",
        "parentPath": "",
        "breadcrumbs": [{"label": "Semua File", "path": ""}],
        "summary": {
            "file_count": file_count,
            "folder_count": folder_count,
            "fileCount": file_count,
            "folderCount": folder_count,
        },
        "items": items,
    }


def build_starred_items_payload(limit=None):
    starred_paths = _load_starred_paths()
    catalog_lookup = {
        _normalize_storage_relative_path(item.get("path")): item
        for item in _collect_storage_catalog()
    }
    items = [catalog_lookup[path] for path in starred_paths if path in catalog_lookup]
    if limit is not None:
        items = items[: max(1, int(limit or 0))]
    file_count = len([item for item in items if item.get("kind") == "file"])
    folder_count = len([item for item in items if item.get("kind") == "folder"])
    return {
        "current_path": "",
        "currentPath": "",
        "parent_path": "",
        "parentPath": "",
        "breadcrumbs": [{"label": "Starred", "path": ""}],
        "summary": {
            "file_count": file_count,
            "folder_count": folder_count,
            "fileCount": file_count,
            "folderCount": folder_count,
        },
        "items": items,
    }


def _build_outgoing_shared_item(entry, catalog_lookup):
    target_path = _normalize_storage_relative_path(entry.get("target_path"))
    if not target_path or target_path not in catalog_lookup:
        return None
    target_item = dict(catalog_lookup[target_path] or {})
    recipients = [dict(recipient or {}) for recipient in entry.get("recipients") or []]
    return {
        **target_item,
        "shared": True,
        "share_id": entry["id"],
        "shareId": entry["id"],
        "shared_external": False,
        "sharedExternal": False,
        "shared_direction": "outgoing",
        "sharedDirection": "outgoing",
        "shared_recipients": recipients,
        "sharedRecipients": recipients,
        "shared_owner_user_id": int(entry["owner_user_id"]),
        "sharedOwnerUserId": int(entry["owner_user_id"]),
        "shared_owner_username": entry.get("owner_username") or "",
        "sharedOwnerUsername": entry.get("owner_username") or "",
        "can_manage_share": True,
        "canManageShare": True,
    }


def build_shared_items_payload(limit=None):
    current_user_id = _get_current_sms_user_id()
    catalog_lookup = {
        _normalize_storage_relative_path(item.get("path")): item
        for item in _collect_storage_catalog()
    }
    items = []
    seen_keys = set()

    for entry in _load_share_registry():
        if current_user_id > 0 and int(entry["owner_user_id"]) == current_user_id:
            outgoing_item = _build_outgoing_shared_item(entry, catalog_lookup)
            if not outgoing_item:
                continue
            item_key = str(outgoing_item.get("id") or outgoing_item.get("path") or "")
            if item_key in seen_keys:
                continue
            items.append(outgoing_item)
            seen_keys.add(item_key)
            continue
        if current_user_id > 0 and any(int(recipient["user_id"]) == current_user_id for recipient in entry.get("recipients") or []):
            incoming_item = _stat_shared_item(entry)
            item_key = str(incoming_item.get("id") or incoming_item.get("path") or "")
            if item_key in seen_keys:
                continue
            items.append(incoming_item)
            seen_keys.add(item_key)

    for path in _load_shared_paths():
        if path not in catalog_lookup:
            continue
        owned_item = dict(catalog_lookup[path] or {})
        item_key = str(owned_item.get("id") or owned_item.get("path") or "")
        if item_key in seen_keys:
            continue
        items.append(owned_item)
        seen_keys.add(item_key)

    items = sorted(
        items,
        key=lambda item: str(item.get("updatedAt") or item.get("updated_at") or ""),
        reverse=True,
    )
    if limit is not None:
        items = items[: max(1, int(limit or 0))]
    file_count = len([item for item in items if item.get("kind") == "file"])
    folder_count = len([item for item in items if item.get("kind") == "folder"])
    return {
        "current_path": "",
        "currentPath": "",
        "parent_path": "",
        "parentPath": "",
        "breadcrumbs": [{"label": "Shared", "path": ""}],
        "summary": {
            "file_count": file_count,
            "folder_count": folder_count,
            "fileCount": file_count,
            "folderCount": folder_count,
        },
        "items": items,
    }


def build_shared_folder_payload(share_id, relative_path=""):
    entry = _get_accessible_share_entry(share_id)
    target_path = _resolve_share_target(entry, relative_path)
    if not os.path.isdir(target_path):
        raise FileNotFoundError("Folder shared tidak ditemukan.")

    base_relative_path = _normalize_storage_relative_path(relative_path)
    items = []
    file_count = 0
    folder_count = 0
    for item_entry in sorted(os.scandir(target_path), key=lambda item: (not item.is_dir(), item.name.lower())):
        if item_entry.name == ".gitkeep":
            continue
        item_relative_path = "/".join(filter(None, [base_relative_path, item_entry.name]))
        shared_item = _stat_shared_item(entry, item_relative_path)
        items.append(shared_item)
        if shared_item["kind"] == "folder":
            folder_count += 1
        else:
            file_count += 1

    breadcrumbs = [{"label": "Shared", "path": ""}]
    root_label = f"{entry.get('label') or os.path.basename(entry.get('target_path') or '')} - {entry.get('owner_username') or 'Owner'}"
    breadcrumbs.append({"label": root_label, "path": ""})
    cursor = ""
    for segment in [part for part in base_relative_path.split("/") if part]:
        cursor = "/".join(filter(None, [cursor, segment]))
        breadcrumbs.append({"label": segment, "path": cursor})

    return {
        "current_path": base_relative_path,
        "currentPath": base_relative_path,
        "parent_path": os.path.dirname(base_relative_path).replace("\\", "/").strip("/"),
        "parentPath": os.path.dirname(base_relative_path).replace("\\", "/").strip("/"),
        "breadcrumbs": breadcrumbs,
        "summary": {
            "file_count": file_count,
            "folder_count": folder_count,
            "fileCount": file_count,
            "folderCount": folder_count,
        },
        "items": items,
        "share_id": entry["id"],
        "shareId": entry["id"],
        "shared_owner_username": entry.get("owner_username") or "",
        "sharedOwnerUsername": entry.get("owner_username") or "",
        "shared_label": entry.get("label") or os.path.basename(entry.get("target_path") or "") or "Shared Item",
        "sharedLabel": entry.get("label") or os.path.basename(entry.get("target_path") or "") or "Shared Item",
    }


def build_shortcuts_payload(limit=None):
    shortcuts = _load_shortcuts()
    catalog_lookup = {
        _normalize_storage_relative_path(item.get("path")): item
        for item in _collect_storage_catalog()
    }
    items = []
    for entry in shortcuts:
        target_path = entry["target_path"]
        if target_path not in catalog_lookup:
            continue
        target_item = catalog_lookup[target_path]
        items.append(
            {
                **target_item,
                "id": f"shortcut:{entry['id']}",
                "name": entry.get("label") or target_item.get("name"),
                "shortcut": True,
                "shortcut_id": entry["id"],
                "shortcutId": entry["id"],
                "shortcut_target_path": target_path,
                "shortcutTargetPath": target_path,
                "shortcut_parent_path": entry.get("parent_path") or "",
                "shortcutParentPath": entry.get("parent_path") or "",
                "shortcut_created_at": entry.get("created_at") or "",
                "shortcutCreatedAt": entry.get("created_at") or "",
                "shortcut_updated_at": entry.get("updated_at") or "",
                "shortcutUpdatedAt": entry.get("updated_at") or "",
                "original_name": target_item.get("name"),
                "originalName": target_item.get("name"),
            }
        )
    if limit is not None:
        items = items[: max(1, int(limit or 0))]
    file_count = len([item for item in items if item.get("kind") == "file"])
    folder_count = len([item for item in items if item.get("kind") == "folder"])
    return {
        "current_path": "",
        "currentPath": "",
        "parent_path": "",
        "parentPath": "",
        "breadcrumbs": [{"label": "Shortcuts", "path": ""}],
        "summary": {
            "file_count": file_count,
            "folder_count": folder_count,
            "fileCount": file_count,
            "folderCount": folder_count,
        },
        "items": items,
    }


def get_storage_stats():
    ensure_sms_storage_structure()
    total_files, total_folders, total_size = _walk_storage()
    trash_items = list_trash_items()
    starred_count = len(_load_starred_paths())
    shared_count = len(build_shared_items_payload(limit=5000).get("items") or [])
    shortcut_count = len(_load_shortcuts())
    quota_bytes = _get_sms_user_quota_bytes()
    usage_percent = min(100, round((total_size / quota_bytes) * 100, 2)) if quota_bytes > 0 else None
    remaining_bytes = max(0, quota_bytes - total_size) if quota_bytes > 0 else 0
    category_breakdown = {
        "image": 0,
        "text": 0,
        "document": 0,
        "archive": 0,
        "video": 0,
        "audio": 0,
        "other": 0,
    }
    latest_update = None
    for item in _collect_storage_catalog():
        updated_at = item.get("updatedAt")
        if updated_at and (latest_update is None or updated_at > latest_update):
            latest_update = updated_at
        if item.get("kind") == "file":
            category = item.get("category") or "other"
            category_breakdown[category] = int(category_breakdown.get(category) or 0) + 1
    return {
        "total_files": total_files,
        "totalFiles": total_files,
        "total_folders": total_folders,
        "totalFolders": total_folders,
        "total_size_bytes": total_size,
        "totalBytes": total_size,
        "total_size_label": format_bytes_compact(total_size),
        "quota_bytes": quota_bytes,
        "quotaBytes": quota_bytes,
        "quota_label": format_bytes_compact(quota_bytes),
        "remaining_bytes": remaining_bytes,
        "remainingBytes": remaining_bytes,
        "remaining_label": format_bytes_compact(remaining_bytes),
        "usage_percent": usage_percent,
        "usagePercent": usage_percent,
        "storage_mode": "quota",
        "storageMode": "quota",
        "max_upload_bytes": _config_int("SMS_STORAGE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024 * 1024),
        "max_upload_label": format_bytes_compact(_config_int("SMS_STORAGE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024 * 1024)),
        "trash_count": len(trash_items),
        "trashCount": len(trash_items),
        "starred_count": starred_count,
        "starredCount": starred_count,
        "shared_count": shared_count,
        "sharedCount": shared_count,
        "shortcut_count": shortcut_count,
        "shortcutCount": shortcut_count,
        "latest_update": latest_update,
        "latestUpdate": latest_update,
        "category_breakdown": category_breakdown,
        "categoryBreakdown": category_breakdown,
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
            "id": f"act-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
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
    return _stat_item(
        entry_path,
        target_path,
        True,
        starred_paths=_load_starred_lookup(),
        shared_paths=_load_shared_lookup(),
        shared_recipient_map=_build_outgoing_share_recipient_map(),
    )


def save_uploaded_files(relative_path, file_storages, actor=""):
    resolved = resolve_storage_path(relative_path)
    if not os.path.isdir(resolved["absolute_path"]):
        raise FileNotFoundError("Folder upload tidak ditemukan.")

    max_upload_bytes = _config_int("SMS_STORAGE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024 * 1024)
    quota_bytes = _get_sms_user_quota_bytes()
    current_usage_bytes = get_storage_stats()["total_size_bytes"]
    uploaded_items = []
    for file_storage in file_storages or []:
        file_name = sanitize_entry_name(os.path.basename(file_storage.filename or ""))
        target_path = _allocate_unique_target(resolved["absolute_path"], file_name)
        file_storage.save(target_path)
        size_bytes = os.path.getsize(target_path)
        if size_bytes > max_upload_bytes:
            os.remove(target_path)
            raise ValueError(f"Ukuran file melebihi batas {format_bytes_compact(max_upload_bytes)}.")
        if quota_bytes > 0 and current_usage_bytes + size_bytes > quota_bytes:
            os.remove(target_path)
            remaining_bytes = max(0, quota_bytes - current_usage_bytes)
            raise ValueError(
                f"Batas storage per user {format_bytes_compact(quota_bytes)} terlampaui. "
                f"Sisa ruang {format_bytes_compact(remaining_bytes)}."
            )
        entry_relative = "/".join(
            filter(None, [resolved["relative_path"], os.path.basename(target_path)])
        )
        uploaded_items.append(_stat_item(entry_relative, target_path, False))
        record_activity("upload", entry_relative, f"Upload {file_name}", actor)
        current_usage_bytes += size_bytes
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
        return _stat_item(
            resolved["relative_path"],
            source_path,
            os.path.isdir(source_path),
            starred_paths=_load_starred_lookup(),
            shared_paths=_load_shared_lookup(),
            shared_recipient_map=_build_outgoing_share_recipient_map(),
        )
    if os.path.exists(target_path):
        raise FileExistsError("Nama baru sudah dipakai.")

    os.rename(source_path, target_path)
    new_relative = "/".join(
        filter(None, [os.path.dirname(resolved["relative_path"]).replace("\\", "/").strip("/"), desired_name])
    )
    _replace_starred_prefix(resolved["relative_path"], new_relative)
    _replace_shared_prefix(resolved["relative_path"], new_relative)
    _replace_share_registry_prefix(resolved["relative_path"], new_relative)
    _replace_shortcuts_prefix(resolved["relative_path"], new_relative)
    record_activity("rename", new_relative, f"Rename dari {os.path.basename(source_path)}", actor)
    return _stat_item(
        new_relative,
        target_path,
        os.path.isdir(target_path),
        starred_paths=_load_starred_lookup(),
        shared_paths=_load_shared_lookup(),
        shared_recipient_map=_build_outgoing_share_recipient_map(),
    )


def move_items(relative_paths, destination_path, actor=""):
    destination = resolve_storage_path(destination_path)
    destination_absolute = destination["absolute_path"]
    if not os.path.isdir(destination_absolute):
        raise FileNotFoundError("Folder tujuan tidak ditemukan.")

    items_to_move = _collapse_nested_paths(relative_paths)
    if not items_to_move:
        raise ValueError("Tidak ada item yang dipilih untuk dipindahkan.")

    prepared_moves = []
    for relative_path in items_to_move:
        source = resolve_storage_path(relative_path)
        source_absolute = source["absolute_path"]
        if not os.path.exists(source_absolute):
            raise FileNotFoundError("Item yang ingin dipindahkan tidak ditemukan.")
        if source["relative_path"] == "":
            raise ValueError("Root tidak bisa dipindahkan.")
        if os.path.abspath(destination_absolute) == os.path.abspath(source_absolute):
            raise ValueError("Tujuan pindah tidak boleh sama dengan item asal.")
        if os.path.isdir(source_absolute):
            source_prefix = os.path.abspath(source_absolute) + os.sep
            if os.path.abspath(destination_absolute).startswith(source_prefix):
                raise ValueError("Folder tidak bisa dipindah ke dalam dirinya sendiri.")
        prepared_moves.append(source)

    moved_items = []
    for source in prepared_moves:
        source_absolute = source["absolute_path"]
        target_path = _allocate_unique_target(destination_absolute, os.path.basename(source_absolute))
        shutil.move(source_absolute, target_path)
        moved_relative = os.path.relpath(target_path, get_sms_storage_root()).replace("\\", "/")
        _replace_starred_prefix(source["relative_path"], moved_relative)
        _replace_shared_prefix(source["relative_path"], moved_relative)
        _replace_share_registry_prefix(source["relative_path"], moved_relative)
        _replace_shortcuts_prefix(source["relative_path"], moved_relative)
        record_activity("move", moved_relative, f"Dipindahkan dari {source['relative_path']}", actor)
        moved_items.append(
            _stat_item(
                moved_relative,
                target_path,
                os.path.isdir(target_path),
                starred_paths=_load_starred_lookup(),
                shared_paths=_load_shared_lookup(),
                shared_recipient_map=_build_outgoing_share_recipient_map(),
            )
        )
    return moved_items


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
    normalized_records = []
    for record in records:
        deleted_at = record.get("deleted_at") or record.get("deletedAt") or ""
        kind = record.get("kind") or ("folder" if record.get("is_dir") else "file")
        category = record.get("category") or ("folder" if kind == "folder" else get_file_category(record.get("name") or ""))
        extension = record.get("extension")
        if extension is None:
            extension = "" if kind == "folder" else os.path.splitext(record.get("name") or "")[1].lstrip(".").lower()
        size_bytes = int(record.get("size_bytes") or record.get("size") or 0)
        normalized_records.append(
            {
                **record,
                "kind": kind,
                "category": category,
                "extension": extension,
                "size": None if kind == "folder" else size_bytes,
                "size_bytes": size_bytes,
                "size_label": record.get("size_label") or ("-" if kind == "folder" else format_bytes_compact(size_bytes)),
                "updatedAt": deleted_at,
                "deletedAt": deleted_at,
                "starred": False,
                "shared": False,
                "shortcut": False,
                "trashed": True,
                "previewable": False,
            }
        )
    return sorted(normalized_records, key=lambda item: item.get("deleted_at", ""), reverse=True)


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

        entry_id = f"trash-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{os.urandom(4).hex()}"
        trash_name = f"{entry_id}-{os.path.basename(source_path)}"
        trash_path = os.path.join(trash_root, trash_name)
        shutil.move(source_path, trash_path)
        _remove_starred_prefix(resolved["relative_path"])
        _remove_shared_prefix(resolved["relative_path"])
        _remove_share_registry_prefix(resolved["relative_path"])
        _remove_shortcuts_prefix(resolved["relative_path"])
        record = {
            "id": entry_id,
            "name": os.path.basename(source_path),
            "original_path": resolved["relative_path"],
            "trash_name": trash_name,
            "is_dir": os.path.isdir(trash_path),
            "kind": "folder" if os.path.isdir(trash_path) else "file",
            "category": "folder" if os.path.isdir(trash_path) else get_file_category(os.path.basename(source_path)),
            "extension": "" if os.path.isdir(trash_path) else os.path.splitext(os.path.basename(source_path))[1].lstrip(".").lower(),
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
    return _stat_item(
        restored_relative,
        restored_target,
        os.path.isdir(restored_target),
        starred_paths=_load_starred_lookup(),
        shared_paths=_load_shared_lookup(),
        shared_recipient_map=_build_outgoing_share_recipient_map(),
    )


def set_starred_items(relative_paths, starred=True, actor=""):
    desired_state = bool(starred)
    starred_paths = _load_starred_paths()
    changed_paths = []
    for relative_path in relative_paths or []:
        safe_path = _normalize_storage_relative_path(relative_path)
        if not safe_path or not _path_exists(safe_path):
            continue
        if desired_state:
            if safe_path in starred_paths:
                starred_paths = [path for path in starred_paths if path != safe_path]
            starred_paths.insert(0, safe_path)
            changed_paths.append(safe_path)
            record_activity("star", safe_path, "Ditandai berbintang", actor)
            continue
        if safe_path in starred_paths:
            starred_paths = [path for path in starred_paths if path != safe_path]
            changed_paths.append(safe_path)
            record_activity("unstar", safe_path, "Dihapus dari berbintang", actor)
    _write_starred_paths(starred_paths)
    return changed_paths


def set_shared_items(relative_paths, shared=True, actor=""):
    desired_state = bool(shared)
    shared_paths = _load_shared_paths()
    changed_paths = []
    for relative_path in relative_paths or []:
        safe_path = _normalize_storage_relative_path(relative_path)
        if not safe_path or not _path_exists(safe_path):
            continue
        if desired_state:
            if safe_path in shared_paths:
                shared_paths = [path for path in shared_paths if path != safe_path]
            shared_paths.insert(0, safe_path)
            changed_paths.append(safe_path)
            record_activity("share", safe_path, "Ditandai sebagai shared", actor)
            continue
        if safe_path in shared_paths:
            shared_paths = [path for path in shared_paths if path != safe_path]
            changed_paths.append(safe_path)
            record_activity("unshare", safe_path, "Dihapus dari shared", actor)
    _write_shared_paths(shared_paths)
    return changed_paths


def share_items_with_users(relative_paths, recipient_users, actor=""):
    owner_user_id = _get_current_sms_user_id()
    owner_username = _get_current_sms_username()
    if owner_user_id <= 0 or not owner_username:
        raise ValueError("Session SMS tidak valid untuk berbagi item.")

    normalized_recipients = []
    seen_recipient_ids = set()
    for recipient in recipient_users or []:
        safe_recipient = _normalize_share_recipient(recipient)
        if not safe_recipient:
            continue
        if safe_recipient["user_id"] == owner_user_id or safe_recipient["user_id"] in seen_recipient_ids:
            continue
        normalized_recipients.append(safe_recipient)
        seen_recipient_ids.add(safe_recipient["user_id"])

    registry = _load_share_registry()
    changed_paths = []
    for relative_path in relative_paths or []:
        safe_path = _normalize_storage_relative_path(relative_path)
        if not safe_path or not _path_exists(safe_path):
            continue
        existing_entry = next(
            (
                entry
                for entry in registry
                if int(entry["owner_user_id"]) == owner_user_id
                and _normalize_storage_relative_path(entry.get("target_path")) == safe_path
            ),
            None,
        )
        if normalized_recipients:
            payload = {
                "id": existing_entry["id"] if existing_entry else "",
                "owner_user_id": owner_user_id,
                "owner_username": owner_username,
                "target_path": safe_path,
                "label": os.path.basename(safe_path) or "Shared Item",
                "recipients": normalized_recipients,
                "created_at": existing_entry.get("created_at") if existing_entry else _now_iso(),
                "updated_at": _now_iso(),
            }
            safe_entry = _normalize_share_entry(payload)
            if not safe_entry:
                continue
            if existing_entry:
                registry = [safe_entry if entry["id"] == existing_entry["id"] else entry for entry in registry]
            else:
                registry.insert(0, safe_entry)
            changed_paths.append(safe_path)
            record_activity(
                "share",
                safe_path,
                f"Dibagikan ke {len(normalized_recipients)} user",
                actor,
            )
            continue

        if existing_entry:
            registry = [entry for entry in registry if entry["id"] != existing_entry["id"]]
            changed_paths.append(safe_path)
            record_activity("unshare", safe_path, "Akses share dicabut", actor)

    _write_share_registry(registry)
    set_shared_items(relative_paths, shared=bool(normalized_recipients), actor=actor)
    return changed_paths


def create_shortcuts(relative_paths, parent_path="", actor=""):
    shortcuts = _load_shortcuts()
    existing_targets = {
        (
            entry["target_path"],
            _normalize_storage_relative_path(entry.get("parent_path") or ""),
        )
        for entry in shortcuts
    }
    created_entries = []
    safe_parent_path = _normalize_storage_relative_path(parent_path)
    for relative_path in relative_paths or []:
        safe_path = _normalize_storage_relative_path(relative_path)
        entry_key = (safe_path, safe_parent_path)
        if not safe_path or not _path_exists(safe_path) or entry_key in existing_targets:
            continue
        entry = _normalize_shortcut_entry(
            {
                "target_path": safe_path,
                "parent_path": safe_parent_path,
                "label": os.path.basename(safe_path),
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        )
        if not entry:
            continue
        shortcuts.insert(0, entry)
        existing_targets.add(entry_key)
        created_entries.append(entry)
        record_activity("shortcut", safe_path, "Shortcut dibuat", actor)
    _write_shortcuts(shortcuts)
    return created_entries


def remove_shortcuts(relative_paths=None, shortcut_ids=None, actor=""):
    target_paths = {
        _normalize_storage_relative_path(path)
        for path in (relative_paths or [])
        if _normalize_storage_relative_path(path)
    }
    target_ids = {
        str(shortcut_id or "").strip()
        for shortcut_id in (shortcut_ids or [])
        if str(shortcut_id or "").strip()
    }
    if not target_paths and not target_ids:
        return []

    shortcuts = _load_shortcuts()
    remaining_entries = []
    removed_entries = []
    for entry in shortcuts:
        if entry["target_path"] in target_paths or entry["id"] in target_ids:
            removed_entries.append(entry)
            record_activity("shortcut-remove", entry["target_path"], "Shortcut dihapus", actor)
            continue
        remaining_entries.append(entry)
    if removed_entries:
        _write_shortcuts(remaining_entries)
    return removed_entries


def restore_trash_items(item_ids, actor=""):
    restored_items = []
    for item_id in item_ids or []:
        if not str(item_id or "").strip():
            continue
        restored_items.append(restore_trash_item(item_id, actor=actor))
    return restored_items


def permanently_delete_trash_items(item_ids, actor=""):
    trash_items = list_trash_items()
    target_ids = {str(item_id or "").strip() for item_id in item_ids or [] if str(item_id or "").strip()}
    if not target_ids:
        return []

    deleted_items = []
    remaining_items = []
    for item in trash_items:
        if str(item.get("id")) not in target_ids:
            remaining_items.append(item)
            continue
        trash_path = os.path.join(_get_sms_trash_items_root(), item.get("trash_name") or "")
        if os.path.isdir(trash_path):
            shutil.rmtree(trash_path, ignore_errors=True)
        elif os.path.exists(trash_path):
            try:
                os.remove(trash_path)
            except OSError:
                pass
        deleted_items.append(item)
        record_activity("trash-delete", item.get("original_path") or item.get("name") or "", "Dihapus permanen dari trash", actor)
    _write_trash_items(remaining_items)
    return deleted_items


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

    archive_name = f"{os.path.basename(target_path) or 'folder'}-{int(datetime.now(timezone.utc).timestamp())}.zip"
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


def build_shared_download_payload(share_id, relative_path=""):
    entry = _get_accessible_share_entry(share_id)
    target_path = _resolve_share_target(entry, relative_path)
    if not os.path.exists(target_path):
        raise FileNotFoundError("Item shared tidak ditemukan.")

    if os.path.isfile(target_path):
        return {
            "path": target_path,
            "download_name": os.path.basename(target_path),
            "cleanup_after": False,
        }

    archive_name = f"{os.path.basename(target_path) or 'shared-folder'}-{int(datetime.now(timezone.utc).timestamp())}.zip"
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


def build_shared_preview_payload(share_id, relative_path=""):
    entry = _get_accessible_share_entry(share_id)
    target_path = _resolve_share_target(entry, relative_path)
    if not os.path.isfile(target_path):
        raise FileNotFoundError("File preview shared tidak ditemukan.")

    file_name = os.path.basename(target_path)
    size_bytes = os.path.getsize(target_path)
    if not is_previewable(file_name, size_bytes):
        raise ValueError("File shared ini tidak mendukung preview.")

    return {
        "path": target_path,
        "mime_type": _guess_mime_type(file_name),
        "category": get_file_category(file_name),
        "size_bytes": size_bytes,
    }
