from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from database import get_db
from services.ai_assistant_service import (
    answer_assistant_message,
    build_monitor_snapshot,
    get_ai_knowledge,
    get_quick_prompts,
)
from services.rbac import has_permission, normalize_role


ai_assistant_bp = Blueprint("ai_assistant", __name__, url_prefix="/ai")


def _can_use_ai_assistant():
    role = normalize_role(session.get("role"))
    return role not in {"intern", "staff_intern", "free_lance"} and has_permission(role, "view_workspace")


def _deny_ai_access():
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"status": "error", "message": "Akses AI assistant tidak tersedia untuk role ini."}), 403
    flash("Akses AI assistant tidak tersedia untuk role ini.", "error")
    return redirect(url_for("dashboard.workspace_gateway"))


@ai_assistant_bp.get("/")
def index():
    if not _can_use_ai_assistant():
        return _deny_ai_access()

    db = get_db()
    snapshot = build_monitor_snapshot(db, current_app.config)
    return render_template(
        "ai_assistant.html",
        status_snapshot=snapshot,
        knowledge_topics=get_ai_knowledge(),
        quick_prompts=get_quick_prompts(),
    )


@ai_assistant_bp.get("/api/status")
def status_api():
    if not _can_use_ai_assistant():
        return _deny_ai_access()

    db = get_db()
    return jsonify(
        {
            "status": "success",
            "snapshot": build_monitor_snapshot(db, current_app.config),
        }
    )


@ai_assistant_bp.post("/api/chat")
def chat_api():
    if not _can_use_ai_assistant():
        return _deny_ai_access()

    payload = request.get_json(silent=True) or {}
    message = payload.get("message") if isinstance(payload, dict) else ""
    if not message:
        message = request.form.get("message", "")

    db = get_db()
    snapshot = build_monitor_snapshot(db, current_app.config)
    answer = answer_assistant_message(message, snapshot=snapshot)
    return jsonify(
        {
            "status": "success",
            "answer": answer["answer"],
            "suggestions": answer.get("suggestions", []),
            "matched_topics": answer.get("matched_topics", []),
            "snapshot": snapshot,
        }
    )
