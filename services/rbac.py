from flask import has_request_context, session


ROLE_ALIASES = {
    "superadmin": "super_admin",
    "super admin": "super_admin",
    "super-admin": "super_admin",
    "freelance": "free_lance",
    "free lance": "free_lance",
    "free-lance": "free_lance",
}

POS_TERMINAL_ROLES = {"owner", "super_admin", "leader"}
POS_ASSIGNABLE_ROLES = {"owner", "super_admin", "leader", "admin", "staff"}

ROLE_PERMISSIONS = {
    "super_admin": {
        "view_workspace",
        "view_wms",
        "view_product_lookup",
        "view_announcements",
        "view_meetings",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_admin",
        "view_audit",
        "view_approvals",
        "view_crm",
        "manage_crm",
        "view_pos",
        "manage_pos",
        "manage_product_master",
        "view_chat",
        "manage_chat",
        "view_schedule",
        "manage_schedule",
        "approve_requests",
        "approve_stock_ops",
        "direct_stock_ops",
        "direct_transfer",
        "global_warehouse",
    },
    "owner": {
        "view_workspace",
        "view_wms",
        "view_product_lookup",
        "view_announcements",
        "view_meetings",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_admin",
        "view_audit",
        "view_approvals",
        "view_crm",
        "manage_crm",
        "view_pos",
        "manage_pos",
        "manage_product_master",
        "view_chat",
        "manage_chat",
        "view_schedule",
        "approve_requests",
        "approve_stock_ops",
        "direct_stock_ops",
        "direct_transfer",
        "global_warehouse",
    },
    "hr": {
        "view_workspace",
        "view_product_lookup",
        "view_announcements",
        "view_meetings",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_chat",
        "manage_chat",
        "view_schedule",
        "manage_schedule",
        "global_warehouse",
    },
    "leader": {
        "view_workspace",
        "view_wms",
        "view_product_lookup",
        "view_announcements",
        "view_meetings",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_approvals",
        "view_crm",
        "manage_crm",
        "view_pos",
        "manage_pos",
        "manage_product_master",
        "view_chat",
        "manage_chat",
        "view_schedule",
        "approve_requests",
        "approve_stock_ops",
        "direct_stock_ops",
        "direct_transfer",
        "scoped_warehouse",
    },
    "admin": {
        "view_workspace",
        "view_wms",
        "view_product_lookup",
        "view_announcements",
        "view_meetings",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_audit",
        "view_crm",
        "manage_crm",
        "view_pos",
        "manage_pos",
        "manage_product_master",
        "view_chat",
        "manage_chat",
        "view_schedule",
        "request_stock_ops",
        "request_transfer",
        "scoped_warehouse",
    },
    "staff": {
        "view_workspace",
        "view_wms",
        "view_product_lookup",
        "view_announcements",
        "view_meetings",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_chat",
        "manage_chat",
        "view_schedule",
        "view_pos",
        "manage_pos",
        "request_stock_ops",
        "request_transfer",
        "scoped_warehouse",
    },
    "intern": {
        "view_workspace",
        "view_announcements",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_schedule",
        "scoped_warehouse",
    },
    "staff_intern": {
        "view_workspace",
        "view_announcements",
        "access_attendance_portal",
        "access_leave_portal",
        "access_overtime_portal",
        "access_daily_report_portal",
        "access_kpi_portal",
        "view_schedule",
        "scoped_warehouse",
    },
    "free_lance": {
        "access_attendance_portal",
        "scoped_warehouse",
    },
}

PERMISSION_CATALOG = (
    {
        "group": "workspace",
        "group_label": "Workspace & Menu",
        "permissions": (
            ("view_workspace", "Workspace", "Akses shell workspace dan navigasi utama."),
            ("view_wms", "Menu WMS", "Bisa membuka stok, produk, inbound, outbound, transfer, dan request gudang."),
            ("view_product_lookup", "Info Produk", "Bisa membuka halaman lookup produk tanpa akses operasional penuh."),
            ("view_crm", "CRM", "Bisa membuka modul CRM customer, pembelian, dan member."),
            ("view_pos", "POS / Kasir", "Bisa membuka modul kasir dan laporan penjualan."),
            ("view_schedule", "Schedule", "Bisa membuka papan schedule."),
            ("view_chat", "Chat", "Bisa membuka chat internal."),
            ("view_announcements", "Pengumuman", "Bisa membuka pusat pengumuman."),
            ("view_meetings", "Meetings", "Bisa membuka modul meetings."),
            ("view_approvals", "Approvals", "Bisa membuka approval center."),
            ("view_audit", "Audit", "Bisa membuka audit trail."),
            ("view_admin", "Admin", "Bisa membuka panel admin."),
        ),
    },
    {
        "group": "portal",
        "group_label": "Portal Self Service",
        "permissions": (
            ("access_attendance_portal", "Portal Absen", "Bisa membuka portal absensi."),
            ("access_leave_portal", "Portal Cuti", "Bisa mengakses pengajuan cuti."),
            ("access_overtime_portal", "Portal Lembur", "Bisa mengakses pengajuan lembur."),
            ("access_daily_report_portal", "Portal Laporan Harian", "Bisa mengirim laporan harian."),
            ("access_kpi_portal", "Portal KPI", "Bisa membuka KPI portal."),
        ),
    },
    {
        "group": "manage",
        "group_label": "Aksi & Operasional",
        "permissions": (
            ("manage_crm", "Kelola CRM", "Bisa tambah, edit, hapus, dan import data CRM."),
            ("manage_pos", "Kelola POS", "Bisa checkout, void, dan aksi kasir lainnya."),
            ("manage_product_master", "Kelola Master Produk", "Bisa ubah master produk, import, dan delete massal."),
            ("manage_chat", "Kelola Chat", "Bisa kirim pesan dan aksi manajemen chat."),
            ("manage_schedule", "Kelola Schedule", "Bisa mengatur schedule tim."),
            ("approve_requests", "Approve Request", "Bisa memproses request gudang/owner."),
            ("approve_stock_ops", "Approve Stock Ops", "Bisa memproses approval stock operation."),
            ("direct_stock_ops", "Direct Stock Ops", "Bisa langsung melakukan stock op tanpa approval."),
            ("request_stock_ops", "Request Stock Ops", "Bisa membuat request stock op."),
            ("direct_transfer", "Direct Transfer", "Bisa langsung memproses transfer gudang."),
            ("request_transfer", "Request Transfer", "Bisa membuat request transfer."),
        ),
    },
)

IMMUTABLE_ROLE_PERMISSIONS = {"global_warehouse", "scoped_warehouse"}
SELF_PROTECTED_PERMISSION_DENIES = {"view_workspace", "view_admin"}

PERMISSION_GROUPS = []
PERMISSION_GROUPS_BY_KEY = {}
PERMISSION_LABELS = {}
PERMISSION_DESCRIPTIONS = {}

for group in PERMISSION_CATALOG:
    permission_items = []
    for permission_key, permission_label, permission_description in group["permissions"]:
        PERMISSION_LABELS[permission_key] = permission_label
        PERMISSION_DESCRIPTIONS[permission_key] = permission_description
        permission_items.append(
            {
                "key": permission_key,
                "label": permission_label,
                "description": permission_description,
            }
        )
    group_payload = {
        "key": group["group"],
        "label": group["group_label"],
        "permissions": tuple(permission_items),
    }
    PERMISSION_GROUPS.append(group_payload)
    PERMISSION_GROUPS_BY_KEY[group["group"]] = group_payload

PERMISSION_GROUPS = tuple(PERMISSION_GROUPS)
MANAGEABLE_PERMISSION_KEYS = tuple(
    permission["key"]
    for group in PERMISSION_GROUPS
    for permission in group["permissions"]
)
MANAGEABLE_PERMISSION_KEY_SET = set(MANAGEABLE_PERMISSION_KEYS)


def normalize_role(role):
    normalized = (role or "").strip().lower()
    return ROLE_ALIASES.get(normalized, normalized)


def get_role_permissions(role):
    return set(ROLE_PERMISSIONS.get(normalize_role(role), set()))


def list_permission_groups():
    return PERMISSION_GROUPS


def get_permission_label(permission):
    return PERMISSION_LABELS.get(permission, permission.replace("_", " ").title())


def get_permission_description(permission):
    return PERMISSION_DESCRIPTIONS.get(permission, "")


def _normalize_permission_keys(values):
    normalized = []
    for value in values or ():
        permission_key = str(value or "").strip()
        if permission_key and permission_key in MANAGEABLE_PERMISSION_KEY_SET:
            normalized.append(permission_key)
    return set(normalized)


def load_user_permission_overrides(db, user_ids=None):
    override_map = {}
    params = []
    query = """
        SELECT user_id, permission_key, access_state
        FROM user_permission_overrides
        WHERE 1=1
    """
    normalized_user_ids = []
    for user_id in user_ids or ():
        try:
            normalized_user_ids.append(int(user_id))
        except (TypeError, ValueError):
            continue

    if normalized_user_ids:
        placeholders = ",".join("?" for _ in normalized_user_ids)
        query += f" AND user_id IN ({placeholders})"
        params.extend(normalized_user_ids)

    try:
        rows = db.execute(query, params).fetchall()
    except Exception:
        return override_map

    for row in rows:
        try:
            user_id = int(row["user_id"])
        except (TypeError, ValueError):
            continue
        permission_key = str(row["permission_key"] or "").strip()
        access_state = str(row["access_state"] or "").strip().lower()
        if permission_key not in MANAGEABLE_PERMISSION_KEY_SET or access_state not in {"allow", "deny"}:
            continue
        bucket = override_map.setdefault(user_id, {"allow": set(), "deny": set()})
        bucket[access_state].add(permission_key)

    return override_map


def load_user_permission_override_snapshot(db, user_id):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return {"allow": set(), "deny": set()}
    snapshot = load_user_permission_overrides(db, [normalized_user_id]).get(
        normalized_user_id,
        {"allow": set(), "deny": set()},
    )
    return {
        "allow": set(snapshot.get("allow") or set()),
        "deny": set(snapshot.get("deny") or set()),
    }


def save_user_permission_overrides(db, user_id, *, allow_permissions=(), deny_permissions=(), updated_by=None):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("User override permission tidak valid.") from exc

    allow_set = _normalize_permission_keys(allow_permissions)
    deny_set = _normalize_permission_keys(deny_permissions) - allow_set

    db.execute("DELETE FROM user_permission_overrides WHERE user_id=?", (normalized_user_id,))

    for permission_key in sorted(allow_set):
        db.execute(
            """
            INSERT INTO user_permission_overrides(
                user_id,
                permission_key,
                access_state,
                updated_by
            )
            VALUES (?,?,?,?)
            """,
            (normalized_user_id, permission_key, "allow", updated_by),
        )

    for permission_key in sorted(deny_set):
        db.execute(
            """
            INSERT INTO user_permission_overrides(
                user_id,
                permission_key,
                access_state,
                updated_by
            )
            VALUES (?,?,?,?)
            """,
            (normalized_user_id, permission_key, "deny", updated_by),
        )

    return {"allow": allow_set, "deny": deny_set}


def _request_permission_override_sets():
    if not has_request_context():
        return set(), set()
    return (
        set(session.get("permission_grants") or ()),
        set(session.get("permission_denies") or ()),
    )


def request_has_custom_permission_grants():
    grants, _ = _request_permission_override_sets()
    return bool(grants)


def get_permissions(role, grants=None, denies=None):
    permissions = get_role_permissions(role)

    if grants is None and denies is None:
        if has_request_context() and normalize_role(role) == normalize_role(session.get("role")):
            grants, denies = _request_permission_override_sets()
        else:
            grants, denies = set(), set()
    else:
        grants = set(grants or ())
        denies = set(denies or ())

    permissions.update(permission_key for permission_key in grants if permission_key in MANAGEABLE_PERMISSION_KEY_SET)
    permissions.difference_update(permission_key for permission_key in denies if permission_key in MANAGEABLE_PERMISSION_KEY_SET)
    return permissions


def has_permission(role, permission, grants=None, denies=None):
    return permission in get_permissions(role, grants=grants, denies=denies)


def is_scoped_role(role):
    return has_permission(role, "scoped_warehouse")


def can_access_pos_terminal(role):
    return normalize_role(role) in POS_TERMINAL_ROLES


def can_assign_pos_staff(role):
    return normalize_role(role) in POS_ASSIGNABLE_ROLES
