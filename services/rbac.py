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


def normalize_role(role):
    normalized = (role or "").strip().lower()
    return ROLE_ALIASES.get(normalized, normalized)


def get_permissions(role):
    return ROLE_PERMISSIONS.get(normalize_role(role), set())


def has_permission(role, permission):
    return permission in get_permissions(role)


def is_scoped_role(role):
    return has_permission(role, "scoped_warehouse")


def can_access_pos_terminal(role):
    return normalize_role(role) in POS_TERMINAL_ROLES


def can_assign_pos_staff(role):
    return normalize_role(role) in POS_ASSIGNABLE_ROLES
