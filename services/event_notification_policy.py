import re

from flask import has_app_context

from database import get_db
from services.rbac import normalize_role


SPECIAL_NOTIFICATION_USER_GROUPS = {
    "hris_priority_users": ("akmal", "edi"),
    "erp_global_users": ("rio",),
}

NOTIFICATION_POLICY_SECTION_META = {
    "hris": {
        "label": "HRIS",
        "summary": "Atur event absen, report, dan libur yang dipantau oleh tim HRIS lintas gudang.",
        "sort_order": 10,
    },
    "request": {
        "label": "Request & Owner",
        "summary": "Kontrol notifikasi request ke owner dan transfer antar gudang dari sisi monitoring.",
        "sort_order": 20,
    },
    "wms": {
        "label": "WMS",
        "summary": "Kelola fan-out approval dan aktivitas operasional gudang dari satu panel admin.",
        "sort_order": 30,
    },
}

ALLOWED_NOTIFICATION_RECIPIENT_ROLES = (
    "owner",
    "hr",
    "super_admin",
    "leader",
    "admin",
    "staff",
)

DEFAULT_EVENT_NOTIFICATION_POLICIES = {
    "attendance.activity": {
        "section": "hris",
        "label": "Absen Staff",
        "summary": "Masuk, pulang, edit absensi, dan aktivitas istirahat staff.",
        "roles": ("owner", "hr"),
        "user_groups": ("hris_priority_users", "erp_global_users"),
    },
    "report.daily_submitted": {
        "section": "hris",
        "label": "Daily Report Baru",
        "summary": "Laporan harian staff yang baru dikirim ke portal HRIS.",
        "roles": ("hr",),
        "user_groups": ("hris_priority_users", "erp_global_users"),
    },
    "report.live_submitted": {
        "section": "hris",
        "label": "Live Report Baru",
        "summary": "Live report yang baru dikirim dan perlu dipantau dari sisi HRIS.",
        "roles": ("hr",),
        "user_groups": ("hris_priority_users", "erp_global_users"),
    },
    "report.status_approved": {
        "section": "hris",
        "label": "Report Disetujui",
        "summary": "Status report ketika ditutup atau dianggap selesai ditinjau.",
        "roles": ("hr", "leader", "admin"),
        "user_groups": ("hris_priority_users", "erp_global_users"),
    },
    "report.status_rejected": {
        "section": "hris",
        "label": "Report Follow Up / Ditolak",
        "summary": "Status report ketika minta revisi atau follow up operasional.",
        "roles": ("hr", "leader", "admin"),
        "user_groups": ("hris_priority_users", "erp_global_users"),
    },
    "leave.status_approved": {
        "section": "hris",
        "label": "Libur Disetujui",
        "summary": "Persetujuan request libur dari portal HRIS.",
        "roles": ("hr", "leader", "admin"),
        "user_groups": ("hris_priority_users", "erp_global_users"),
    },
    "leave.status_rejected": {
        "section": "hris",
        "label": "Libur Ditolak",
        "summary": "Penolakan request libur agar jalur monitoring tetap jelas.",
        "roles": ("hr", "leader", "admin"),
        "user_groups": ("hris_priority_users", "erp_global_users"),
    },
    "request.owner_requested": {
        "section": "request",
        "label": "Request Ke Owner",
        "summary": "Request khusus owner yang dibuat dari WMS.",
        "roles": ("owner",),
        "user_groups": ("erp_global_users",),
    },
    "request.transfer_submitted": {
        "section": "request",
        "label": "Transfer Antar Gudang",
        "summary": "Request transfer antar gudang yang baru diajukan.",
        "roles": ("leader",),
        "user_groups": ("erp_global_users",),
    },
    "inventory.activity": {
        "section": "wms",
        "label": "Aktivitas WMS",
        "summary": "Aktivitas WMS umum seperti stok, produk, inbound, dan outbound.",
        "roles": ("leader",),
        "user_groups": ("erp_global_users",),
    },
    "inventory.inbound_approval_requested": {
        "section": "wms",
        "label": "Approval Inbound Baru",
        "summary": "Permintaan approval untuk proses inbound.",
        "roles": ("leader",),
        "user_groups": ("erp_global_users",),
    },
    "inventory.outbound_approval_requested": {
        "section": "wms",
        "label": "Approval Outbound Baru",
        "summary": "Permintaan approval untuk proses outbound.",
        "roles": ("leader",),
        "user_groups": ("erp_global_users",),
    },
    "inventory.adjust_approval_requested": {
        "section": "wms",
        "label": "Approval Adjust Stok Baru",
        "summary": "Permintaan approval untuk penyesuaian stok manual.",
        "roles": ("leader",),
        "user_groups": ("erp_global_users",),
    },
    "inventory.product_edit_approval_requested": {
        "section": "wms",
        "label": "Approval Edit Produk Baru",
        "summary": "Permintaan approval untuk edit master produk.",
        "roles": ("leader",),
        "user_groups": ("erp_global_users",),
    },
    "inventory.product_delete_approval_requested": {
        "section": "wms",
        "label": "Approval Hapus Produk Baru",
        "summary": "Permintaan approval untuk hapus produk dari master.",
        "roles": ("leader",),
        "user_groups": ("erp_global_users",),
    },
    "inventory.approval_approved": {
        "section": "wms",
        "label": "Approval WMS Disetujui",
        "summary": "Approval inbound, outbound, atau adjust yang disetujui.",
        "roles": ("leader", "admin"),
        "user_groups": ("erp_global_users",),
    },
    "inventory.approval_rejected": {
        "section": "wms",
        "label": "Approval WMS Ditolak",
        "summary": "Approval inbound, outbound, atau adjust yang ditolak.",
        "roles": ("leader", "admin"),
        "user_groups": ("erp_global_users",),
    },
    "inventory.product_approval_approved": {
        "section": "wms",
        "label": "Approval Produk Disetujui",
        "summary": "Persetujuan edit atau hapus produk dari studio produk.",
        "roles": ("leader", "admin"),
        "user_groups": ("erp_global_users",),
    },
    "inventory.product_approval_rejected": {
        "section": "wms",
        "label": "Approval Produk Ditolak",
        "summary": "Penolakan edit atau hapus produk dari studio produk.",
        "roles": ("leader", "admin"),
        "user_groups": ("erp_global_users",),
    },
}

# Backward-compatible alias for older imports/tests.
EVENT_NOTIFICATION_POLICIES = DEFAULT_EVENT_NOTIFICATION_POLICIES


def _normalize_event_type(value):
    return str(value or "").strip().lower()


def _normalize_alias(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_alias_list(values):
    normalized = []
    seen = set()
    for value in values or ():
        alias = _normalize_alias(value)
        if not alias or alias in seen:
            continue
        seen.add(alias)
        normalized.append(alias)
    return tuple(normalized)


def _normalize_role_list(values):
    normalized = []
    seen = set()
    for value in values or ():
        role = normalize_role(value)
        if not role or role not in ALLOWED_NOTIFICATION_RECIPIENT_ROLES or role in seen:
            continue
        seen.add(role)
        normalized.append(role)
    return tuple(normalized)


def _normalize_user_id_list(values):
    normalized = []
    seen = set()
    for value in values or ():
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        normalized.append(user_id)
    return tuple(normalized)


def _expand_user_groups(group_names):
    aliases = []
    for group_name in group_names or ():
        aliases.extend(SPECIAL_NOTIFICATION_USER_GROUPS.get(str(group_name or "").strip(), ()))
    return aliases


def _resolve_notification_users_by_ids(user_ids):
    normalized_user_ids = _normalize_user_id_list(user_ids)
    if not normalized_user_ids or not has_app_context():
        return []

    db = get_db()
    rows = db.execute(
        f"""
        SELECT
            u.id,
            u.username,
            u.role,
            u.warehouse_id,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'User') AS display_name,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), '') AS full_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        WHERE u.id IN ({','.join('?' for _ in normalized_user_ids)})
        ORDER BY u.id ASC
        """,
        normalized_user_ids,
    ).fetchall()
    rows_by_id = {int(row["id"]): dict(row) for row in rows}
    return [rows_by_id[user_id] for user_id in normalized_user_ids if user_id in rows_by_id]


def _default_policy_payload(event_type):
    normalized_event = _normalize_event_type(event_type)
    raw_policy = DEFAULT_EVENT_NOTIFICATION_POLICIES.get(normalized_event, {})
    section_key = raw_policy.get("section") or "wms"
    section_meta = NOTIFICATION_POLICY_SECTION_META.get(
        section_key,
        {
            "label": section_key.upper(),
            "summary": "",
            "sort_order": 999,
        },
    )
    default_roles = _normalize_role_list(raw_policy.get("roles", ()))
    default_usernames = _normalize_alias_list(
        list(raw_policy.get("usernames", ()))
        + list(_expand_user_groups(raw_policy.get("user_groups", ())))
    )
    return {
        "event_type": normalized_event,
        "section": section_key,
        "section_label": section_meta["label"],
        "section_summary": section_meta["summary"],
        "section_sort_order": int(section_meta.get("sort_order", 999)),
        "label": str(raw_policy.get("label") or normalized_event).strip(),
        "summary": str(raw_policy.get("summary") or "").strip(),
        "default_roles": default_roles,
        "default_usernames": default_usernames,
    }


def _load_custom_notification_policy(event_type):
    normalized_event = _normalize_event_type(event_type)
    if not normalized_event or not has_app_context():
        return None

    db = get_db()
    master_row = db.execute(
        """
        SELECT event_type, updated_by, updated_at
        FROM notification_event_policies
        WHERE event_type=?
        """,
        (normalized_event,),
    ).fetchone()
    if not master_row:
        return None

    role_rows = db.execute(
        """
        SELECT role
        FROM notification_event_policy_roles
        WHERE event_type=?
        ORDER BY role ASC
        """,
        (normalized_event,),
    ).fetchall()
    user_rows = db.execute(
        """
        SELECT user_id
        FROM notification_event_policy_users
        WHERE event_type=?
        ORDER BY user_id ASC
        """,
        (normalized_event,),
    ).fetchall()
    user_ids = tuple(int(row["user_id"]) for row in user_rows if row["user_id"] is not None)
    resolved_users = _resolve_notification_users_by_ids(user_ids)

    return {
        "roles": _normalize_role_list(row["role"] for row in role_rows),
        "user_ids": user_ids,
        "selected_users": resolved_users,
        "updated_by": master_row["updated_by"],
        "updated_at": master_row["updated_at"],
        "is_custom": True,
    }


def get_event_notification_catalog():
    catalog = []
    for event_type in DEFAULT_EVENT_NOTIFICATION_POLICIES:
        catalog.append(_default_policy_payload(event_type))
    return sorted(catalog, key=lambda item: (item["section_sort_order"], item["label"], item["event_type"]))


def list_event_notification_policies():
    return [get_event_notification_policy(item["event_type"]) for item in get_event_notification_catalog()]


def get_event_notification_policy(event_type):
    default_policy = _default_policy_payload(event_type)
    custom_policy = _load_custom_notification_policy(default_policy["event_type"])

    if custom_policy:
        roles = custom_policy["roles"]
        usernames = ()
        user_ids = custom_policy["user_ids"]
        selected_users = custom_policy["selected_users"]
        is_custom = True
        updated_by = custom_policy["updated_by"]
        updated_at = custom_policy["updated_at"]
    else:
        roles = default_policy["default_roles"]
        usernames = default_policy["default_usernames"]
        user_ids = ()
        selected_users = []
        is_custom = False
        updated_by = None
        updated_at = None

    return {
        **default_policy,
        "roles": roles,
        "usernames": usernames,
        "user_ids": user_ids,
        "selected_users": selected_users,
        "is_custom": is_custom,
        "updated_by": updated_by,
        "updated_at": updated_at,
    }


def get_event_notification_roles(event_type):
    return get_event_notification_policy(event_type)["roles"]


def get_event_notification_usernames(event_type):
    return get_event_notification_policy(event_type)["usernames"]


def get_event_notification_user_ids(event_type):
    return get_event_notification_policy(event_type)["user_ids"]


def save_event_notification_policy(event_type, roles=None, user_ids=None, updated_by=None):
    normalized_event = _normalize_event_type(event_type)
    if normalized_event not in DEFAULT_EVENT_NOTIFICATION_POLICIES:
        raise ValueError("notification_event_not_supported")

    normalized_roles = _normalize_role_list(roles)
    normalized_user_ids = _normalize_user_id_list(user_ids)

    db = get_db()
    if normalized_user_ids:
        existing_rows = db.execute(
            f"SELECT id FROM users WHERE id IN ({','.join('?' for _ in normalized_user_ids)})",
            normalized_user_ids,
        ).fetchall()
        existing_user_ids = {int(row["id"]) for row in existing_rows}
        missing_ids = [str(user_id) for user_id in normalized_user_ids if user_id not in existing_user_ids]
        if missing_ids:
            raise ValueError(f"notification_users_not_found:{','.join(missing_ids)}")

    db.execute(
        """
        INSERT INTO notification_event_policies(event_type, updated_by, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(event_type)
        DO UPDATE SET
            updated_by=excluded.updated_by,
            updated_at=CURRENT_TIMESTAMP
        """,
        (normalized_event, updated_by),
    )
    db.execute(
        "DELETE FROM notification_event_policy_roles WHERE event_type=?",
        (normalized_event,),
    )
    db.execute(
        "DELETE FROM notification_event_policy_users WHERE event_type=?",
        (normalized_event,),
    )

    if normalized_roles:
        db.executemany(
            """
            INSERT INTO notification_event_policy_roles(event_type, role)
            VALUES (?, ?)
            """,
            [(normalized_event, role) for role in normalized_roles],
        )
    if normalized_user_ids:
        db.executemany(
            """
            INSERT INTO notification_event_policy_users(event_type, user_id)
            VALUES (?, ?)
            """,
            [(normalized_event, user_id) for user_id in normalized_user_ids],
        )

    db.commit()
    return get_event_notification_policy(normalized_event)


def reset_event_notification_policy(event_type):
    normalized_event = _normalize_event_type(event_type)
    if normalized_event not in DEFAULT_EVENT_NOTIFICATION_POLICIES:
        raise ValueError("notification_event_not_supported")

    db = get_db()
    db.execute(
        "DELETE FROM notification_event_policy_roles WHERE event_type=?",
        (normalized_event,),
    )
    db.execute(
        "DELETE FROM notification_event_policy_users WHERE event_type=?",
        (normalized_event,),
    )
    db.execute(
        "DELETE FROM notification_event_policies WHERE event_type=?",
        (normalized_event,),
    )
    db.commit()
    return get_event_notification_policy(normalized_event)


def row_matches_notification_aliases(row, aliases):
    normalized_aliases = set(_normalize_alias_list(aliases))
    if not normalized_aliases:
        return False

    for field_name in ("username", "display_name", "full_name"):
        raw_value = str((row or {}).get(field_name) or "").strip()
        if not raw_value:
            continue
        if _normalize_alias(raw_value) in normalized_aliases:
            return True
        tokens = [_normalize_alias(token) for token in re.split(r"[^a-z0-9]+", raw_value.lower())]
        if normalized_aliases.intersection(token for token in tokens if token):
            return True
    return False
