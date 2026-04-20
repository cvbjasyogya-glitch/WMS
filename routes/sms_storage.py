import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from services.sms_storage_service import (
    build_recent_items_payload,
    build_shared_items_payload,
    build_starred_items_payload,
    build_storage_index_payload,
    build_shortcuts_payload,
    build_download_payload,
    build_preview_payload,
    create_shortcuts,
    create_folder,
    delete_items,
    empty_trash,
    ensure_sms_storage_structure,
    get_activity_feed,
    get_storage_stats,
    list_storage_items,
    list_trash_items,
    move_items,
    permanently_delete_trash_items,
    rename_item,
    restore_trash_item,
    restore_trash_items,
    remove_shortcuts,
    save_uploaded_files,
    set_shared_items,
    set_starred_items,
)


sms_storage_bp = Blueprint("sms_storage", __name__, url_prefix="/sms")


def _get_primary_sms_public_host():
    sms_hosts = current_app.config.get("SMS_PUBLIC_HOSTS") or []
    for host in sms_hosts:
        safe_host = str(host or "").strip().lstrip(".").rstrip(".")
        if safe_host:
            return safe_host
    return ""


def build_sms_public_url(endpoint, **values):
    target_path = url_for(endpoint, **values)
    sms_host = _get_primary_sms_public_host()
    if not sms_host:
        return target_path

    current_host = str(request.host or "").strip().split(":", 1)[0].lower()
    if current_host == sms_host.lower():
        return target_path

    target_scheme = (
        str(current_app.config.get("CANONICAL_SCHEME") or request.scheme or "https")
        .strip()
        .lower()
        or "https"
    )
    return f"{target_scheme}://{sms_host}{target_path}"


def build_sms_public_current_url():
    sms_host = _get_primary_sms_public_host()
    if not sms_host:
        return ""

    current_host = str(request.host or "").strip().split(":", 1)[0].lower()
    if current_host == sms_host.lower():
        return ""

    target_scheme = (
        str(current_app.config.get("CANONICAL_SCHEME") or request.scheme or "https")
        .strip()
        .lower()
        or "https"
    )
    target_path = request.full_path if request.query_string else request.path
    if target_path.endswith("?"):
        target_path = target_path[:-1]
    if not target_path.startswith("/"):
        target_path = f"/{target_path}"
    return f"{target_scheme}://{sms_host}{target_path or '/'}"


def _json_payload():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return request.form.to_dict(flat=True)


def _actor_label():
    return (session.get("username") or "").strip() or "ERP User"


@sms_storage_bp.before_request
def _prepare_sms_request():
    ensure_sms_storage_structure()
    if request.endpoint == "sms_storage.upload_files":
        try:
            request.max_content_length = int(
                current_app.config.get("SMS_STORAGE_MAX_UPLOAD_BYTES", 100 * 1024 * 1024 * 1024)
            )
        except (TypeError, ValueError, AttributeError):
            pass


@sms_storage_bp.get("/")
def home():
    initial_path = (request.args.get("path") or "").strip().replace("\\", "/").strip("/")
    stats = get_storage_stats()
    return render_template(
        "sms_storage.html",
        initial_path=initial_path,
        storage_stats=stats,
        storage_activity=get_activity_feed(),
        current_user_label=_actor_label(),
        current_user_quota_label=stats.get("quota_label"),
    )


@sms_storage_bp.get("/api/list")
def api_list():
    relative_path = request.args.get("path", "")
    return jsonify(
        {
            "status": "ok",
            **list_storage_items(relative_path),
        }
    )


@sms_storage_bp.get("/api/recent")
def api_recent():
    return jsonify(
        {
            "status": "ok",
            **build_recent_items_payload(),
        }
    )


@sms_storage_bp.get("/api/index")
def api_index():
    return jsonify(
        {
            "status": "ok",
            **build_storage_index_payload(),
        }
    )


@sms_storage_bp.get("/api/starred")
def api_starred():
    return jsonify(
        {
            "status": "ok",
            **build_starred_items_payload(),
        }
    )


@sms_storage_bp.post("/api/starred")
def api_toggle_starred():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths")
    if not isinstance(paths, list):
        single_path = (payload.get("path") or "").strip()
        paths = [single_path] if single_path else []
    changed = set_starred_items(
        paths,
        starred=payload.get("starred", True),
        actor=_actor_label(),
    )
    return jsonify(
        {
            "status": "ok",
            "changed_paths": changed,
            "starred": bool(payload.get("starred", True)),
            **build_starred_items_payload(),
        }
    )


@sms_storage_bp.get("/api/shared")
def api_shared():
    return jsonify(
        {
            "status": "ok",
            **build_shared_items_payload(),
        }
    )


@sms_storage_bp.post("/api/shared")
def api_toggle_shared():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths")
    if not isinstance(paths, list):
        single_path = (payload.get("path") or "").strip()
        paths = [single_path] if single_path else []
    changed = set_shared_items(
        paths,
        shared=payload.get("shared", True),
        actor=_actor_label(),
    )
    return jsonify(
        {
            "status": "ok",
            "changed_paths": changed,
            "shared": bool(payload.get("shared", True)),
            **build_shared_items_payload(),
        }
    )


@sms_storage_bp.get("/api/shortcuts")
def api_shortcuts():
    return jsonify(
        {
            "status": "ok",
            **build_shortcuts_payload(),
        }
    )


@sms_storage_bp.post("/api/shortcuts")
def api_create_shortcuts():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths")
    if not isinstance(paths, list):
        single_path = (payload.get("path") or "").strip()
        paths = [single_path] if single_path else []
    created = create_shortcuts(
        paths,
        parent_path=payload.get("parent_path") or payload.get("parentPath") or "",
        actor=_actor_label(),
    )
    return jsonify(
        {
            "status": "ok",
            "created": created,
            **build_shortcuts_payload(),
        }
    )


@sms_storage_bp.delete("/api/shortcuts")
def api_delete_shortcuts():
    payload = request.get_json(silent=True) or {}
    shortcut_ids = payload.get("ids")
    if not isinstance(shortcut_ids, list):
        shortcut_ids = []
    paths = payload.get("paths")
    if not isinstance(paths, list):
        paths = []
    removed = remove_shortcuts(
        relative_paths=paths,
        shortcut_ids=shortcut_ids,
        actor=_actor_label(),
    )
    return jsonify(
        {
            "status": "ok",
            "removed": removed,
            **build_shortcuts_payload(),
        }
    )


@sms_storage_bp.get("/api/stats")
def api_stats():
    return jsonify({"status": "ok", "stats": get_storage_stats()})


@sms_storage_bp.get("/api/activity")
def api_activity():
    return jsonify({"status": "ok", "activity": get_activity_feed()})


@sms_storage_bp.get("/api/trash")
def api_trash():
    items = list_trash_items()
    file_count = len([item for item in items if item.get("kind") == "file"])
    folder_count = len([item for item in items if item.get("kind") == "folder"])
    return jsonify(
        {
            "status": "ok",
            "current_path": "",
            "currentPath": "",
            "parent_path": "",
            "parentPath": "",
            "breadcrumbs": [{"label": "Trash", "path": ""}],
            "summary": {
                "file_count": file_count,
                "folder_count": folder_count,
                "fileCount": file_count,
                "folderCount": folder_count,
            },
            "items": items,
        }
    )


@sms_storage_bp.post("/api/folders")
def api_create_folder():
    payload = _json_payload()
    folder = create_folder(
        payload.get("path"),
        payload.get("name"),
        actor=_actor_label(),
    )
    return jsonify({"status": "ok", "item": folder})


@sms_storage_bp.post("/api/upload")
def upload_files():
    target_path = request.form.get("path", "")
    file_items = request.files.getlist("files")
    if not file_items and request.files.get("file"):
        file_items = [request.files["file"]]
    if not file_items:
        return jsonify({"status": "error", "message": "Tidak ada file yang dipilih."}), 400

    uploaded = save_uploaded_files(target_path, file_items, actor=_actor_label())
    return jsonify({"status": "ok", "items": uploaded})


@sms_storage_bp.post("/api/rename")
def api_rename():
    payload = _json_payload()
    item = rename_item(
        payload.get("path"),
        payload.get("new_name"),
        actor=_actor_label(),
    )
    return jsonify({"status": "ok", "item": item})


@sms_storage_bp.post("/api/move")
def api_move():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths")
    if not isinstance(paths, list):
        single_path = (payload.get("path") or "").strip()
        paths = [single_path] if single_path else []
    moved = move_items(
        paths,
        payload.get("destination_path") or payload.get("destinationPath") or "",
        actor=_actor_label(),
    )
    return jsonify({"status": "ok", "items": moved})


@sms_storage_bp.post("/api/delete")
def api_delete():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths")
    if not isinstance(paths, list):
        single_path = (payload.get("path") or request.form.get("path") or "").strip()
        paths = [single_path] if single_path else []
    deleted = delete_items(paths, actor=_actor_label())
    return jsonify({"status": "ok", "items": deleted})


@sms_storage_bp.post("/api/trash/restore")
def api_restore_trash():
    payload = _json_payload()
    item = restore_trash_item(payload.get("item_id"), actor=_actor_label())
    return jsonify({"status": "ok", "item": item})


@sms_storage_bp.post("/api/restore")
def api_restore_trash_items():
    payload = request.get_json(silent=True) or {}
    item_ids = payload.get("ids")
    if not isinstance(item_ids, list):
        single_id = (payload.get("id") or "").strip()
        item_ids = [single_id] if single_id else []
    restored = restore_trash_items(item_ids, actor=_actor_label())
    return jsonify({"status": "ok", "restored": restored})


@sms_storage_bp.post("/api/trash/empty")
def api_empty_trash():
    removed_count = empty_trash(actor=_actor_label())
    return jsonify({"status": "ok", "removed_count": removed_count})


@sms_storage_bp.delete("/api/trash")
def api_delete_trash_items():
    payload = request.get_json(silent=True) or {}
    item_ids = payload.get("ids")
    if not isinstance(item_ids, list):
        item_ids = []
    deleted = permanently_delete_trash_items(item_ids, actor=_actor_label())
    return jsonify({"status": "ok", "deleted": deleted})


@sms_storage_bp.get("/api/download")
def api_download():
    payload = build_download_payload(request.args.get("path", ""))
    response = send_file(
        payload["path"],
        as_attachment=True,
        download_name=payload["download_name"],
        conditional=True,
    )
    if payload.get("cleanup_after"):
        @response.call_on_close
        def _cleanup_temp_download():
            try:
                os.remove(payload["path"])
            except OSError:
                return
    return response


@sms_storage_bp.get("/api/preview")
def api_preview():
    payload = build_preview_payload(request.args.get("path", ""))
    return send_file(
        payload["path"],
        mimetype=payload["mime_type"],
        as_attachment=False,
        conditional=True,
    )


@sms_storage_bp.errorhandler(FileNotFoundError)
def _handle_sms_file_not_found(error):
    return jsonify({"status": "error", "message": str(error) or "Item tidak ditemukan."}), 404


@sms_storage_bp.errorhandler(FileExistsError)
def _handle_sms_file_exists(error):
    return jsonify({"status": "error", "message": str(error) or "Nama sudah dipakai."}), 409


@sms_storage_bp.errorhandler(ValueError)
def _handle_sms_value_error(error):
    return jsonify({"status": "error", "message": str(error) or "Permintaan tidak valid."}), 400
