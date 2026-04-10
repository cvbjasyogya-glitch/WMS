from flask import has_request_context, request, session

from services.rbac import normalize_role


PRIVATE_SUPER_ADMIN_BLUEPRINTS = {
    "approvals",
    "inbound",
    "outbound",
    "pos",
    "products",
    "request",
    "stock",
    "stock_opname",
    "transfers",
}

PRIVATE_SUPER_ADMIN_PATH_PREFIXES = (
    "/approvals",
    "/inbound",
    "/kasir",
    "/outbound",
    "/products",
    "/request",
    "/so",
    "/stock",
    "/transfers",
)

PRIVATE_SUPER_ADMIN_CATEGORIES = {
    "approval",
    "inventory",
    "owner_request",
    "request",
}

PRIVATE_SUPER_ADMIN_SOURCE_PREFIXES = (
    "approval_",
    "direct_transfer",
    "inbound_",
    "outbound_",
    "owner_request",
    "pos_",
    "product_",
    "stock_",
    "warehouse_",
)

PRIVATE_SUPER_ADMIN_EVENT_PREFIXES = (
    "inventory.",
    "request.",
)

PRIVATE_SUPER_ADMIN_EVENT_NAMES = {
    "attendance.cash_closing",
}


def _normalize_path(value):
    return str(value or "").strip().lower()


def is_private_super_admin_actor(actor_role=None):
    if actor_role is None and has_request_context():
        actor_role = session.get("role")
    return normalize_role(actor_role) == "super_admin"


def is_super_admin_private_activity(
    *,
    category=None,
    link_url=None,
    source_type=None,
    event_type=None,
    blueprint=None,
):
    normalized_category = str(category or "").strip().lower()
    normalized_link = _normalize_path(link_url)
    normalized_source = str(source_type or "").strip().lower()
    normalized_event = str(event_type or "").strip().lower()
    normalized_blueprint = str(blueprint or "").strip().lower()

    if has_request_context():
        normalized_blueprint = normalized_blueprint or str(request.blueprint or "").strip().lower()
        request_path = _normalize_path(request.path)
        if request_path.startswith(PRIVATE_SUPER_ADMIN_PATH_PREFIXES):
            return True

    if normalized_blueprint in PRIVATE_SUPER_ADMIN_BLUEPRINTS:
        return True

    if normalized_category in PRIVATE_SUPER_ADMIN_CATEGORIES:
        return True

    if normalized_link.startswith(PRIVATE_SUPER_ADMIN_PATH_PREFIXES):
        return True

    if normalized_source.startswith(PRIVATE_SUPER_ADMIN_SOURCE_PREFIXES):
        return True

    if normalized_event in PRIVATE_SUPER_ADMIN_EVENT_NAMES:
        return True

    if normalized_event.startswith(PRIVATE_SUPER_ADMIN_EVENT_PREFIXES):
        return True

    return False


def should_suppress_super_admin_notifications(
    *,
    actor_role=None,
    category=None,
    link_url=None,
    source_type=None,
    event_type=None,
    blueprint=None,
):
    return is_private_super_admin_actor(actor_role) and is_super_admin_private_activity(
        category=category,
        link_url=link_url,
        source_type=source_type,
        event_type=event_type,
        blueprint=blueprint,
    )


def can_view_super_admin_private_audit(viewer_role=None):
    return normalize_role(viewer_role) == "super_admin"
