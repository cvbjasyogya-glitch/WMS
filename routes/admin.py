from flask import Blueprint, flash, redirect, render_template, request, session
from werkzeug.security import generate_password_hash

from database import get_db
from services.event_notification_policy import (
    ALLOWED_NOTIFICATION_RECIPIENT_ROLES,
    list_event_notification_policies,
    reset_event_notification_policy,
    row_matches_notification_aliases,
    save_event_notification_policy,
)
from services.rbac import (
    SELF_PROTECTED_PERMISSION_DENIES,
    get_permission_label,
    get_permissions,
    get_role_permissions,
    has_permission,
    is_scoped_role,
    list_permission_groups,
    load_user_permission_overrides,
    normalize_role,
    save_user_permission_overrides,
)


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ALLOWED_ROLES = ["super_admin", "owner", "hr", "leader", "admin", "staff", "intern", "free_lance"]
ROLE_GUIDE = [
    {
        "role": "super_admin",
        "label": "Super Admin",
        "scope": "Lintas Gudang",
        "summary": "Kontrol penuh atas WMS, HRIS, penjadwalan, audit, approvals, dan panel admin.",
    },
    {
        "role": "owner",
        "label": "Owner",
        "scope": "Lintas Gudang",
        "summary": "Akses strategis lintas gudang untuk approval, audit, dan monitoring akses inti sistem.",
    },
    {
        "role": "hr",
        "label": "HR",
        "scope": "Lintas Gudang",
        "summary": "Fokus pada HRIS dan penjadwalan lintas gudang tanpa akses admin sistem penuh.",
    },
    {
        "role": "leader",
        "label": "Leader",
        "scope": "1 Gudang",
        "summary": "Memproses approval gudang, direct stock ops, direct transfer, dan monitoring tim sendiri.",
    },
    {
        "role": "admin",
        "label": "Admin Gudang",
        "scope": "1 Gudang",
        "summary": "Menjalankan operasional gudang harian dan mengajukan approval sesuai gudang penugasan.",
    },
    {
        "role": "staff",
        "label": "Staff",
        "scope": "1 Gudang",
        "summary": "Akses operasional terbatas untuk request, view schedule, dan alur kerja gudang harian.",
    },
    {
        "role": "intern",
        "label": "Intern",
        "scope": "1 Gudang",
        "summary": "Fokus pada menu koordinasi tanpa akses WMS, CRM, atau chat.",
    },
    {
        "role": "free_lance",
        "label": "Free Lance",
        "scope": "1 Gudang",
        "summary": "Hanya bisa mengakses portal absen operasional sesuai homebase penugasan.",
    },
]

NOTIFICATION_ROLE_LABELS = {
    "owner": "Owner",
    "hr": "HR",
    "super_admin": "Super Admin",
    "leader": "Leader",
    "admin": "Admin",
    "staff": "Staff",
    "intern": "Intern",
    "free_lance": "Free Lance",
}


def _admin_role_bucket(role):
    normalized = normalize_role(role)
    if normalized == "staff_intern":
        return "intern"
    return normalized


def require_admin():
    if normalize_role(session.get("role")) == "super_admin":
        return True
    if not has_permission(session.get("role"), "view_admin"):
        flash("Akses ditolak", "error")
        return False
    return True


def require_super_admin():
    if normalize_role(session.get("role")) != "super_admin":
        flash("Pengaturan hak akses khusus hanya bisa diatur oleh super admin.", "error")
        return False
    return True


def _admin_redirect(section="access"):
    if section == "warehouses":
        return redirect("/admin/warehouses")
    if section == "notifications":
        return redirect("/admin/notifications")
    if section == "permissions":
        return redirect("/admin/permissions")
    return redirect("/admin/")


def _format_notification_user_label(user):
    display_name = (
        str(user.get("employee_name") or user.get("display_name") or user.get("full_name") or user.get("username") or "User").strip()
    )
    username = str(user.get("username") or "").strip()
    role = NOTIFICATION_ROLE_LABELS.get(str(user.get("role") or "").strip(), str(user.get("role") or "").strip() or "User")
    warehouse_name = str(user.get("warehouse_name") or "").strip()

    parts = [display_name]
    meta = []
    if username and username.lower() != display_name.lower():
        meta.append(f"@{username}")
    meta.append(role)
    if warehouse_name:
        meta.append(warehouse_name)
    if meta:
        parts.append(" | ".join(meta))
    return " - ".join(parts)


def _resolve_default_notification_users(users, aliases):
    aliases = tuple(aliases or ())
    if not aliases:
        return []

    matched = []
    used_ids = set()
    for user in users:
        user_row = {
            "username": user.get("username"),
            "display_name": user.get("employee_name") or user.get("username"),
            "full_name": user.get("employee_name") or user.get("username"),
        }
        if not row_matches_notification_aliases(user_row, aliases):
            continue
        user_id = user.get("id")
        if user_id in used_ids:
            continue
        used_ids.add(user_id)
        matched.append(
            {
                "id": user_id,
                "label": _format_notification_user_label(user),
            }
        )
    return matched


def _build_notification_policy_sections(users):
    role_options = [
        {
            "value": role,
            "label": NOTIFICATION_ROLE_LABELS.get(role, role.replace("_", " ").title()),
        }
        for role in ALLOWED_NOTIFICATION_RECIPIENT_ROLES
    ]
    user_options = [
        {
            "id": user["id"],
            "label": _format_notification_user_label(user),
        }
        for user in sorted(
            users,
            key=lambda item: (
                str(item.get("employee_name") or item.get("username") or "").lower(),
                int(item.get("id") or 0),
            ),
        )
    ]

    sections = {}
    custom_count = 0
    explicit_user_target_count = 0

    for policy in list_event_notification_policies():
        if policy["is_custom"]:
            custom_count += 1
        explicit_user_target_count += len(policy.get("user_ids") or ())

        section_key = policy["section"]
        section_bucket = sections.setdefault(
            section_key,
            {
                "key": section_key,
                "label": policy["section_label"],
                "summary": policy["section_summary"],
                "sort_order": policy["section_sort_order"],
                "policies": [],
            },
        )

        default_users = _resolve_default_notification_users(users, policy.get("default_usernames"))
        selected_users = [
            {
                "id": int(user.get("id") or 0),
                "label": _format_notification_user_label(user),
            }
            for user in policy.get("selected_users") or ()
            if user.get("id")
        ]
        effective_user_labels = selected_users if policy["is_custom"] else default_users

        section_bucket["policies"].append(
            {
                **policy,
                "default_users": default_users,
                "selected_user_labels": selected_users,
                "effective_user_labels": effective_user_labels,
                "role_labels": [NOTIFICATION_ROLE_LABELS.get(role, role) for role in policy["roles"]],
            }
        )

    return {
        "sections": sorted(sections.values(), key=lambda item: (item["sort_order"], item["label"])),
        "role_options": role_options,
        "user_options": user_options,
        "summary": {
            "total_events": sum(len(section["policies"]) for section in sections.values()),
            "custom_events": custom_count,
            "specific_users": explicit_user_target_count,
        },
    }


def _load_admin_context():
    db = get_db()

    users_raw = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.role,
            u.email,
            u.phone,
            u.notify_email,
            u.notify_whatsapp,
            u.warehouse_id,
            u.employee_id,
            w.name AS warehouse_name,
            e.employee_code,
            e.full_name AS employee_name
        FROM users u
        LEFT JOIN warehouses w ON u.warehouse_id = w.id
        LEFT JOIN employees e ON u.employee_id = e.id
        ORDER BY u.id DESC
        """
    ).fetchall()
    users = [dict(user) for user in users_raw]

    employees_raw = db.execute(
        """
        SELECT
            e.id,
            e.employee_code,
            e.full_name,
            e.warehouse_id,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        ORDER BY e.full_name COLLATE NOCASE ASC, e.id DESC
        """
    ).fetchall()
    employees = [dict(employee) for employee in employees_raw]

    warehouses_raw = db.execute(
        """
        SELECT
            w.id,
            w.name,
            COUNT(DISTINCT u.id) AS assigned_users,
            COUNT(DISTINCT CASE WHEN u.role IN ('leader', 'admin', 'staff', 'staff_intern', 'intern', 'free_lance') THEN u.id END) AS scoped_users,
            COUNT(DISTINCT s.id) AS stock_rows,
            COUNT(DISTINCT e.id) AS employee_rows
        FROM warehouses w
        LEFT JOIN users u ON u.warehouse_id = w.id
        LEFT JOIN stock s ON s.warehouse_id = w.id
        LEFT JOIN employees e ON e.warehouse_id = w.id
        GROUP BY w.id, w.name
        ORDER BY w.id DESC
        """
    ).fetchall()
    warehouses = [dict(warehouse) for warehouse in warehouses_raw]

    role_guide = []
    for role_item in ROLE_GUIDE:
        role_guide.append(
            {
                **role_item,
                "count": sum(1 for user in users if _admin_role_bucket(user["role"]) == role_item["role"]),
            }
        )

    health = {
        "unassigned_scoped_users": db.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role IN ('leader', 'admin', 'staff', 'staff_intern', 'intern', 'free_lance') AND warehouse_id IS NULL
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
        "global_roles": sum(1 for user in users if not is_scoped_role(user["role"])),
        "scoped_roles": sum(1 for user in users if is_scoped_role(user["role"])),
    }

    warehouse_summary = {
        "total": len(warehouses),
        "with_stock": sum(1 for warehouse in warehouses if warehouse["stock_rows"]),
        "assigned_users": sum(warehouse["assigned_users"] for warehouse in warehouses),
        "employee_rows": sum(warehouse["employee_rows"] for warehouse in warehouses),
    }

    return {
        "users": users,
        "warehouses": warehouses,
        "employees": employees,
        "health": health,
        "role_guide": role_guide,
        "warehouse_summary": warehouse_summary,
    }


def _build_permission_admin_context(users):
    db = get_db()
    user_ids = [int(user["id"]) for user in users if user.get("id")]
    override_map = load_user_permission_overrides(db, user_ids)

    permission_groups = []
    total_custom_users = 0
    total_grants = 0
    total_denies = 0

    for group in list_permission_groups():
        permission_groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "permissions": [dict(permission) for permission in group["permissions"]],
            }
        )

    permission_users = []
    for user in users:
        user_id = int(user["id"])
        override_snapshot = override_map.get(user_id, {"allow": set(), "deny": set()})
        grants = set(override_snapshot.get("allow") or set())
        denies = set(override_snapshot.get("deny") or set())
        if grants or denies:
            total_custom_users += 1
        total_grants += len(grants)
        total_denies += len(denies)

        base_permissions = get_role_permissions(user["role"])
        effective_permissions = get_permissions(user["role"], grants=grants, denies=denies)

        group_cards = []
        for group in permission_groups:
            permission_rows = []
            active_count = 0
            for permission in group["permissions"]:
                permission_key = permission["key"]
                is_role_default = permission_key in base_permissions
                is_granted = permission_key in grants
                is_denied = permission_key in denies
                is_effective = permission_key in effective_permissions
                if is_effective:
                    active_count += 1
                permission_rows.append(
                    {
                        **permission,
                        "is_role_default": is_role_default,
                        "is_granted": is_granted,
                        "is_denied": is_denied,
                        "is_effective": is_effective,
                    }
                )
            group_cards.append(
                {
                    "key": group["key"],
                    "label": group["label"],
                    "permissions": permission_rows,
                    "active_count": active_count,
                    "total_count": len(permission_rows),
                }
            )

        permission_users.append(
            {
                **user,
                "role_permission_count": len(base_permissions),
                "effective_permission_count": len(effective_permissions),
                "custom_grants": sorted(grants),
                "custom_denies": sorted(denies),
                "custom_grant_labels": [get_permission_label(permission) for permission in sorted(grants)],
                "custom_deny_labels": [get_permission_label(permission) for permission in sorted(denies)],
                "permission_groups": group_cards,
            }
        )

    return {
        "permission_groups": permission_groups,
        "permission_users": permission_users,
        "permission_summary": {
            "managed_permissions": sum(len(group["permissions"]) for group in permission_groups),
            "custom_users": total_custom_users,
            "custom_grants": total_grants,
            "custom_denies": total_denies,
        },
    }


def _resolve_employee_link(db, role, warehouse_id, raw_employee_id):
    employee_id = raw_employee_id or None
    if not employee_id:
        return None

    try:
        employee_id = int(employee_id)
    except Exception:
        return None

    employee = db.execute(
        "SELECT id, warehouse_id FROM employees WHERE id=?",
        (employee_id,),
    ).fetchone()
    if not employee:
        return None

    if is_scoped_role(role) and warehouse_id and employee["warehouse_id"] != warehouse_id:
        return "__invalid_scope__"

    return employee["id"]


@admin_bp.route("/")
def admin_page():
    if not require_admin():
        return redirect("/")

    return render_template(
        "admin.html",
        admin_section="access",
        **_load_admin_context(),
    )


@admin_bp.route("/permissions")
def permission_admin_page():
    if not require_admin():
        return redirect("/")
    if not require_super_admin():
        return _admin_redirect()

    admin_context = _load_admin_context()
    permission_context = _build_permission_admin_context(admin_context["users"])
    return render_template(
        "admin_permissions.html",
        admin_section="permissions",
        **permission_context,
        **admin_context,
    )


@admin_bp.route("/permissions/<int:user_id>", methods=["POST"])
def update_user_permissions(user_id):
    if not require_admin():
        return redirect("/")
    if not require_super_admin():
        return _admin_redirect()

    db = get_db()
    user = db.execute(
        "SELECT id, username, role FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not user:
        flash("User target permission tidak ditemukan.", "error")
        return _admin_redirect("permissions")

    grant_permissions = set(request.form.getlist("grant_permissions"))
    deny_permissions = set(request.form.getlist("deny_permissions"))
    if grant_permissions & deny_permissions:
        flash("Permission yang sama tidak boleh masuk grant dan cabut akses sekaligus.", "error")
        return _admin_redirect("permissions")

    current_user_id = session.get("user_id")
    if current_user_id == user_id and deny_permissions.intersection(SELF_PROTECTED_PERMISSION_DENIES):
        flash("Akun login sendiri tidak boleh mencabut akses workspace atau admin dari panel ini.", "error")
        return _admin_redirect("permissions")

    try:
        save_user_permission_overrides(
            db,
            user_id,
            allow_permissions=grant_permissions,
            deny_permissions=deny_permissions,
            updated_by=current_user_id,
        )
    except ValueError:
        flash("Konfigurasi hak akses tidak valid.", "error")
        return _admin_redirect("permissions")

    db.commit()
    flash(f"Hak akses khusus untuk {user['username']} berhasil diperbarui.", "success")
    return _admin_redirect("permissions")


@admin_bp.route("/warehouses")
def warehouse_admin_page():
    if not require_admin():
        return redirect("/")

    return render_template(
        "admin_warehouses.html",
        admin_section="warehouses",
        **_load_admin_context(),
    )


@admin_bp.route("/notifications")
def admin_notification_page():
    if not require_admin():
        return redirect("/")

    admin_context = _load_admin_context()
    notification_context = _build_notification_policy_sections(admin_context["users"])
    return render_template(
        "admin_notifications.html",
        admin_section="notifications",
        notification_sections=notification_context["sections"],
        notification_role_options=notification_context["role_options"],
        notification_user_options=notification_context["user_options"],
        notification_summary=notification_context["summary"],
        **admin_context,
    )


@admin_bp.route("/notifications/<event_type>", methods=["POST"])
def update_notification_policy(event_type):
    if not require_admin():
        return redirect("/")

    roles = request.form.getlist("roles")
    user_ids = request.form.getlist("user_ids")
    try:
        save_event_notification_policy(
            event_type,
            roles=roles,
            user_ids=user_ids,
            updated_by=session.get("user_id"),
        )
    except ValueError:
        flash("Event notifikasi tidak valid atau user pilihan tidak ditemukan.", "error")
        return _admin_redirect("notifications")

    flash("Klasifikasi notif berhasil diperbarui.", "success")
    return _admin_redirect("notifications")


@admin_bp.route("/notifications/<event_type>/reset", methods=["POST"])
def reset_notification_policy_route(event_type):
    if not require_admin():
        return redirect("/")

    try:
        reset_event_notification_policy(event_type)
    except ValueError:
        flash("Event notifikasi tidak valid.", "error")
        return _admin_redirect("notifications")

    flash("Klasifikasi notif dikembalikan ke default.", "success")
    return _admin_redirect("notifications")


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
    notify_email = 1 if request.form.get("notify_email") == "on" else 0
    notify_whatsapp = 1 if request.form.get("notify_whatsapp") == "on" else 0
    warehouse_id = request.form.get("warehouse_id") or None
    employee_id = request.form.get("employee_id") or None
    if warehouse_id:
        try:
            warehouse_id = int(warehouse_id)
        except Exception:
            warehouse_id = None

    if not username or not password:
        flash("Username & password wajib diisi", "error")
        return _admin_redirect()

    if role not in ALLOWED_ROLES:
        flash("Role tidak valid", "error")
        return _admin_redirect()

    if is_scoped_role(role) and not warehouse_id:
        flash("Role scoped wajib assign gudang", "error")
        return _admin_redirect()

    if not is_scoped_role(role):
        warehouse_id = None

    employee_id = _resolve_employee_link(db, role, warehouse_id, employee_id)
    if employee_id == "__invalid_scope__":
        flash("Karyawan yang ditautkan harus berasal dari gudang yang sama dengan akun scoped", "error")
        return _admin_redirect()

    exist = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exist:
        flash("Username sudah digunakan", "error")
        return _admin_redirect()

    try:
        db.execute(
            """
            INSERT INTO users(username,password,role,email,phone,notify_email,notify_whatsapp,warehouse_id,employee_id)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                username,
                generate_password_hash(password),
                role,
                email or None,
                phone or None,
                notify_email,
                notify_whatsapp,
                warehouse_id,
                employee_id,
            ),
        )
    except Exception:
        db.execute(
            """
            INSERT INTO users(username,password,role)
            VALUES (?,?,?)
            """,
            (username, generate_password_hash(password), role),
        )

    db.commit()
    flash("User berhasil ditambahkan", "success")
    return _admin_redirect()


@admin_bp.route("/update_user/<int:id>", methods=["POST"])
def update_user(id):
    if not require_admin():
        return redirect("/")

    db = get_db()

    user_exist = db.execute("SELECT id FROM users WHERE id=?", (id,)).fetchone()
    if not user_exist:
        flash("User tidak ditemukan", "error")
        return _admin_redirect()

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "").strip()
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    notify_email = 1 if request.form.get("notify_email") == "on" else 0
    notify_whatsapp = 1 if request.form.get("notify_whatsapp") == "on" else 0
    warehouse_id = request.form.get("warehouse_id") or None
    employee_id = request.form.get("employee_id") or None
    if warehouse_id:
        try:
            warehouse_id = int(warehouse_id)
        except Exception:
            warehouse_id = None

    if role not in ALLOWED_ROLES:
        flash("Role tidak valid", "error")
        return _admin_redirect()

    if is_scoped_role(role) and not warehouse_id:
        flash("Role scoped wajib assign gudang", "error")
        return _admin_redirect()

    if not is_scoped_role(role):
        warehouse_id = None

    employee_id = _resolve_employee_link(db, role, warehouse_id, employee_id)
    if employee_id == "__invalid_scope__":
        flash("Karyawan yang ditautkan harus berasal dari gudang yang sama dengan akun scoped", "error")
        return _admin_redirect()

    if password:
        try:
            db.execute(
                """
                UPDATE users
                SET username=?, password=?, role=?, email=?, phone=?, notify_email=?, notify_whatsapp=?, warehouse_id=?, employee_id=?
                WHERE id=?
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    email or None,
                    phone or None,
                    notify_email,
                    notify_whatsapp,
                    warehouse_id,
                    employee_id,
                    id,
                ),
            )
        except Exception:
            db.execute(
                """
                UPDATE users SET username=?, password=?, role=?
                WHERE id=?
                """,
                (username, generate_password_hash(password), role, id),
            )
    else:
        try:
            db.execute(
                """
                UPDATE users
                SET username=?, role=?, email=?, phone=?, notify_email=?, notify_whatsapp=?, warehouse_id=?, employee_id=?
                WHERE id=?
                """,
                (
                    username,
                    role,
                    email or None,
                    phone or None,
                    notify_email,
                    notify_whatsapp,
                    warehouse_id,
                    employee_id,
                    id,
                ),
            )
        except Exception:
            db.execute(
                """
                UPDATE users SET username=?, role=?
                WHERE id=?
                """,
                (username, role, id),
            )

    db.commit()
    flash("User diupdate", "success")
    return _admin_redirect()


@admin_bp.route("/delete_user/<int:id>", methods=["POST"])
def delete_user(id):
    if not require_super_admin():
        return redirect("/")

    db = get_db()
    current_user_id = session.get("user_id")

    if id == current_user_id:
        flash("Tidak bisa hapus diri sendiri", "error")
        return _admin_redirect()

    admin_count = db.execute(
        """
        SELECT COUNT(*) as total FROM users
        WHERE role = 'super_admin'
        """
    ).fetchone()["total"]

    user = db.execute("SELECT role FROM users WHERE id=?", (id,)).fetchone()
    if user and user["role"] == "super_admin" and admin_count <= 1:
        flash("Tidak bisa hapus admin terakhir", "error")
        return _admin_redirect()

    db.execute("DELETE FROM users WHERE id=?", (id,))
    db.commit()

    flash("User dihapus", "success")
    return _admin_redirect()


@admin_bp.route("/add_warehouse", methods=["POST"])
def add_warehouse():
    if not require_admin():
        return redirect("/")

    db = get_db()
    name = (request.form.get("name") or "").strip()

    if not name:
        flash("Nama gudang wajib diisi", "error")
        return _admin_redirect("warehouses")

    exist = db.execute("SELECT id FROM warehouses WHERE name=?", (name,)).fetchone()
    if exist:
        flash("Nama gudang sudah ada", "error")
        return _admin_redirect("warehouses")

    db.execute("INSERT INTO warehouses(name) VALUES (?)", (name,))
    db.commit()

    flash("Gudang ditambahkan", "success")
    return _admin_redirect("warehouses")


@admin_bp.route("/delete_warehouse/<int:id>", methods=["POST"])
def delete_warehouse(id):
    if not require_admin():
        return redirect("/")

    db = get_db()

    used = db.execute(
        """
        SELECT COUNT(*) as total FROM stock
        WHERE warehouse_id=?
        """,
        (id,),
    ).fetchone()["total"]

    if used > 0:
        flash("Gudang masih dipakai stock", "error")
        return _admin_redirect("warehouses")

    db.execute("DELETE FROM warehouses WHERE id=?", (id,))
    db.commit()

    flash("Gudang dihapus", "success")
    return _admin_redirect("warehouses")
