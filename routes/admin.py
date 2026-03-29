from flask import Blueprint, render_template, request, redirect, flash, session
from database import get_db
from services.rbac import has_permission, is_scoped_role
from werkzeug.security import generate_password_hash

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Only roles for now (include owner)
ALLOWED_ROLES = ["super_admin", "owner", "leader", "admin", "staff"]


def require_admin():
    if not has_permission(session.get("role"), "view_admin"):
        flash("Akses ditolak", "error")
        return False
    return True


# ==========================
# ADMIN PAGE
# ==========================
@admin_bp.route("/")
def admin_page():

    if not require_admin():
        return redirect("/")

    db = get_db()

    users_raw = db.execute("""
    SELECT u.id, u.username, u.role, u.email, u.phone, u.notify_email, u.notify_whatsapp, u.warehouse_id, w.name as warehouse_name
    FROM users u
    LEFT JOIN warehouses w ON u.warehouse_id = w.id
    ORDER BY u.id DESC
    """).fetchall()

    users = [dict(u) for u in users_raw]

    warehouses = db.execute("""
    SELECT * FROM warehouses ORDER BY id DESC
    """).fetchall()

    health = {
        "unassigned_scoped_users": db.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role IN ('leader', 'admin', 'staff') AND warehouse_id IS NULL
            """
        ).fetchone()[0],
        "pending_requests": db.execute(
            "SELECT COUNT(*) FROM requests WHERE status='pending'"
        ).fetchone()[0],
        "pending_approvals": db.execute(
            "SELECT COUNT(*) FROM approvals WHERE status='pending'"
        ).fetchone()[0],
        "failed_notifications": db.execute(
            """
            SELECT COUNT(*)
            FROM notifications
            WHERE status='failed'
              AND created_at >= datetime('now', '-7 day')
            """
        ).fetchone()[0],
    }

    return render_template(
        "admin.html",
        users=users,
        warehouses=warehouses,
        health=health,
    )


# ==========================
# ADD USER
# ==========================
@admin_bp.route("/add_user", methods=["POST"])
def add_user():

    if not require_admin():
        return redirect("/")

    db = get_db()

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "").strip()
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    notify_email = 1 if request.form.get("notify_email") == 'on' else 0
    notify_whatsapp = 1 if request.form.get("notify_whatsapp") == 'on' else 0
    warehouse_id = request.form.get("warehouse_id") or None
    if warehouse_id:
        try:
            warehouse_id = int(warehouse_id)
        except Exception:
            warehouse_id = None

    if not username or not password:
        flash("Username & password wajib diisi", "error")
        return redirect("/admin")

    if role not in ALLOWED_ROLES:
        flash("Role tidak valid", "error")
        return redirect("/admin")

    if is_scoped_role(role) and not warehouse_id:
        flash("Role scoped wajib assign gudang", "error")
        return redirect("/admin")

    if not is_scoped_role(role):
        warehouse_id = None

    exist = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exist:
        flash("Username sudah digunakan", "error")
        return redirect("/admin")

    # try to include email/phone if columns exist
    try:
        db.execute("""
        INSERT INTO users(username,password,role,email,phone,notify_email,notify_whatsapp,warehouse_id)
        VALUES (?,?,?,?,?,?,?,?)
        """, (username, generate_password_hash(password), role, email or None, phone or None, notify_email, notify_whatsapp, warehouse_id))
    except Exception:
        db.execute("""
        INSERT INTO users(username,password,role)
        VALUES (?,?,?)
        """, (username, generate_password_hash(password), role))

    db.commit()
    flash("User berhasil ditambahkan", "success")

    return redirect("/admin")


# ==========================
# UPDATE USER
# ==========================
@admin_bp.route("/update_user/<int:id>", methods=["POST"])
def update_user(id):

    if not require_admin():
        return redirect("/")

    db = get_db()

    user_exist = db.execute("SELECT id FROM users WHERE id=?", (id,)).fetchone()
    if not user_exist:
        flash("User tidak ditemukan", "error")
        return redirect("/admin")

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "").strip()
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    notify_email = 1 if request.form.get("notify_email") == 'on' else 0
    notify_whatsapp = 1 if request.form.get("notify_whatsapp") == 'on' else 0
    warehouse_id = request.form.get("warehouse_id") or None
    if warehouse_id:
        try:
            warehouse_id = int(warehouse_id)
        except Exception:
            warehouse_id = None

    if role not in ALLOWED_ROLES:
        flash("Role tidak valid", "error")
        return redirect("/admin")

    if is_scoped_role(role) and not warehouse_id:
        flash("Role scoped wajib assign gudang", "error")
        return redirect("/admin")

    if not is_scoped_role(role):
        warehouse_id = None

    if password:
        try:
            db.execute("""
            UPDATE users SET username=?, password=?, role=?, email=?, phone=?, notify_email=?, notify_whatsapp=?, warehouse_id=?
            WHERE id=?
            """, (username, generate_password_hash(password), role, email or None, phone or None, notify_email, notify_whatsapp, warehouse_id, id))
        except Exception:
            db.execute("""
            UPDATE users SET username=?, password=?, role=?
            WHERE id=?
            """, (username, generate_password_hash(password), role, id))
    else:
        try:
            db.execute("""
            UPDATE users SET username=?, role=?, email=?, phone=?, notify_email=?, notify_whatsapp=?, warehouse_id=?
            WHERE id=?
            """, (username, role, email or None, phone or None, notify_email, notify_whatsapp, warehouse_id, id))
        except Exception:
            db.execute("""
            UPDATE users SET username=?, role=?
            WHERE id=?
            """, (username, role, id))

    db.commit()
    flash("User diupdate", "success")

    return redirect("/admin")


# ==========================
# DELETE USER
# ==========================
@admin_bp.route("/delete_user/<int:id>", methods=["POST"])
def delete_user(id):

    if not require_admin():
        return redirect("/")

    db = get_db()

    current_user_id = session.get("user_id")

    if id == current_user_id:
        flash("Tidak bisa hapus diri sendiri", "error")
        return redirect("/admin")

    # protect last super_admin
    admin_count = db.execute("""
    SELECT COUNT(*) as total FROM users
    WHERE role = 'super_admin'
    """).fetchone()["total"]

    user = db.execute("SELECT role FROM users WHERE id=?", (id,)).fetchone()

    if user and user["role"] == "super_admin" and admin_count <= 1:
        flash("Tidak bisa hapus admin terakhir", "error")
        return redirect("/admin")

    db.execute("DELETE FROM users WHERE id=?", (id,))
    db.commit()

    flash("User dihapus", "success")
    return redirect("/admin")


# ==========================
# ADD WAREHOUSE
# ==========================
@admin_bp.route("/add_warehouse", methods=["POST"])
def add_warehouse():

    if not require_admin():
        return redirect("/")

    db = get_db()

    name = (request.form.get("name") or "").strip()

    if not name:
        flash("Nama gudang wajib diisi", "error")
        return redirect("/admin")

    exist = db.execute("SELECT id FROM warehouses WHERE name=?", (name,)).fetchone()
    if exist:
        flash("Nama gudang sudah ada", "error")
        return redirect("/admin")

    db.execute("INSERT INTO warehouses(name) VALUES (?)", (name,))
    db.commit()

    flash("Gudang ditambahkan", "success")
    return redirect("/admin")


# ==========================
# DELETE WAREHOUSE
# ==========================
@admin_bp.route("/delete_warehouse/<int:id>", methods=["POST"])
def delete_warehouse(id):

    if not require_admin():
        return redirect("/")

    db = get_db()

    used = db.execute("""
    SELECT COUNT(*) as total FROM stock
    WHERE warehouse_id=?
    """, (id,)).fetchone()["total"]

    if used > 0:
        flash("Gudang masih dipakai stock", "error")
        return redirect("/admin")

    db.execute("DELETE FROM warehouses WHERE id=?", (id,))
    db.commit()

    flash("Gudang dihapus", "success")
    return redirect("/admin")
