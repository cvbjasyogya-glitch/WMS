ROLE_PERMISSIONS = {
    "super_admin": {
        "view_admin",
        "view_audit",
        "view_approvals",
        "view_crm",
        "manage_crm",
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
        "view_admin",
        "view_audit",
        "view_approvals",
        "view_crm",
        "manage_crm",
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
        "view_chat",
        "manage_chat",
        "view_schedule",
        "manage_schedule",
        "global_warehouse",
    },
    "leader": {
        "view_approvals",
        "view_crm",
        "manage_crm",
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
        "view_audit",
        "view_crm",
        "manage_crm",
        "view_chat",
        "manage_chat",
        "view_schedule",
        "request_stock_ops",
        "request_transfer",
        "scoped_warehouse",
    },
    "staff": {
        "view_chat",
        "manage_chat",
        "view_schedule",
        "request_stock_ops",
        "request_transfer",
        "scoped_warehouse",
    },
}


def get_permissions(role):
    return ROLE_PERMISSIONS.get(role or "", set())


def has_permission(role, permission):
    return permission in get_permissions(role)


def is_scoped_role(role):
    return has_permission(role, "scoped_warehouse")
