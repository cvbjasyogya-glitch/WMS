from flask import Blueprint, current_app, flash, redirect, render_template, request, session

from database import get_db


account_bp = Blueprint("account", __name__, url_prefix="/account")


def _clamp_chat_volume(raw_value):
    try:
        volume_percent = int(float(raw_value))
    except (TypeError, ValueError):
        volume_percent = int(float(current_app.config.get("CHAT_SOUND_VOLUME_DEFAULT", 0.85)) * 100)
    volume_percent = max(0, min(volume_percent, 100))
    return round(volume_percent / 100.0, 2), volume_percent


@account_bp.route("/settings", methods=["GET", "POST"])
def settings():
    db = get_db()
    user_id = session.get("user_id")

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        notify_email = 1 if request.form.get("notify_email") == "on" else 0
        notify_whatsapp = 1 if request.form.get("notify_whatsapp") == "on" else 0
        chat_sound_volume, volume_percent = _clamp_chat_volume(request.form.get("chat_sound_volume"))

        db.execute(
            """
            UPDATE users
            SET email=?,
                phone=?,
                notify_email=?,
                notify_whatsapp=?,
                chat_sound_volume=?
            WHERE id=?
            """,
            (
                email or None,
                phone or None,
                notify_email,
                notify_whatsapp,
                chat_sound_volume,
                user_id,
            ),
        )
        db.commit()

        session["chat_sound_volume"] = chat_sound_volume
        flash(f"Pengaturan akun berhasil disimpan. Volume chat sekarang {volume_percent}%.", "success")
        return redirect("/account/settings")

    user = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.role,
            u.email,
            u.phone,
            u.notify_email,
            u.notify_whatsapp,
            u.chat_sound_volume,
            u.warehouse_id,
            w.name AS warehouse_name
        FROM users u
        LEFT JOIN warehouses w ON w.id = u.warehouse_id
        WHERE u.id=?
        """,
        (user_id,),
    ).fetchone()

    if not user:
        flash("Data akun tidak ditemukan.", "error")
        return redirect("/")

    user = dict(user)
    volume_percent = int(round(float(
        user["chat_sound_volume"]
        if user.get("chat_sound_volume") is not None
        else current_app.config.get("CHAT_SOUND_VOLUME_DEFAULT", 0.85)
    ) * 100))

    return render_template(
        "account_settings.html",
        account_user=user,
        chat_sound_volume_percent=volume_percent,
    )
