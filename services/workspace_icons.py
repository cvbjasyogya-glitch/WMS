WORKSPACE_ICON_BASE_PATH = "/static/icons/workspace"
WORKSPACE_ICON_FALLBACK_KEY = "utility-generic"

HRIS_MODULE_ICON_KEYS = {
    "dashboard": "hris-dashboard",
    "employee": "hris-employee",
    "leave": "hris-leave",
    "approval": "wms-approvals",
    "payroll": "hris-payroll",
    "recruitment": "hris-recruitment",
    "onboarding": "hris-onboarding",
    "offboarding": "hris-offboarding",
    "pms": "hris-performance",
    "helpdesk": "hris-helpdesk",
    "report": "hris-report",
    "biometric": "hris-biometric",
    "announcement": "hris-announcement",
    "documents": "hris-documents",
}

WORKSPACE_ICON_KEYS = frozenset(
    {
        "coordination-pengumuman",
        "coordination-absen-foto",
        "coordination-libur",
        "coordination-report-harian",
        "coordination-jadwal",
        "coordination-chat-operasional",
        "coordination-crm",
        "wms-dashboard",
        "wms-info-produk",
        "wms-stok-produk",
        "wms-kasir",
        "wms-inbound",
        "wms-outbound",
        "wms-transfer",
        "wms-request-gudang",
        "wms-request-owner",
        "wms-stock-opname",
        "wms-approvals",
        "wms-audit-log",
        "hris-home",
        "hris-dashboard",
        "hris-employee",
        "hris-leave",
        "hris-payroll",
        "hris-recruitment",
        "hris-onboarding",
        "hris-offboarding",
        "hris-performance",
        "hris-helpdesk",
        "hris-report",
        "hris-biometric",
        "hris-announcement",
        "hris-documents",
        "utility-account-settings",
        "utility-admin",
        "utility-theme",
        "utility-install",
        "utility-logout",
        WORKSPACE_ICON_FALLBACK_KEY,
    }
)


def get_workspace_icon_asset(icon_key):
    safe_key = icon_key if icon_key in WORKSPACE_ICON_KEYS else WORKSPACE_ICON_FALLBACK_KEY
    return f"{WORKSPACE_ICON_BASE_PATH}/{safe_key}.svg"


def get_hris_workspace_icon_key(slug):
    return HRIS_MODULE_ICON_KEYS.get(slug, WORKSPACE_ICON_FALLBACK_KEY)
