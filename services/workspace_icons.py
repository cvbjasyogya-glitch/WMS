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

WORKSPACE_ICON_SYMBOLS = {
    "coordination-pengumuman": "\U0001f4e3",
    "coordination-absen-foto": "\U0001f552",
    "coordination-libur": "\U0001f4dd",
    "coordination-report-harian": "\U0001f4c4",
    "coordination-jadwal": "\U0001f4c5",
    "coordination-chat-operasional": "\U0001f4ac",
    "coordination-crm": "\U0001f4ac",
    "wms-dashboard": "\u25a6",
    "wms-info-produk": "\U0001f4e6",
    "wms-stok-produk": "\U0001f4e6",
    "wms-kasir": "\U0001f9fe",
    "wms-inbound": "\u2199",
    "wms-outbound": "\u2197",
    "wms-transfer": "\u21c4",
    "wms-request-gudang": "\U0001f4dd",
    "wms-request-owner": "\U0001f4b3",
    "wms-stock-opname": "\u25a6",
    "wms-approvals": "\u2713",
    "wms-audit-log": "i",
    "hris-home": "\u2302",
    "hris-dashboard": "\u25a6",
    "hris-employee": "\U0001f465",
    "hris-leave": "\U0001f4dd",
    "hris-payroll": "\U0001f4b3",
    "hris-recruitment": "\U0001f50e",
    "hris-onboarding": "\U0001f4c4",
    "hris-offboarding": "\U0001f4c4",
    "hris-performance": "\U0001f4ca",
    "hris-helpdesk": "\U0001f3a7",
    "hris-report": "\U0001f4ca",
    "hris-biometric": "\U0001f552",
    "hris-announcement": "\U0001f4e3",
    "hris-documents": "\U0001f4c4",
    "group-coordination": "\U0001f4c5",
    "group-workspace": "\U0001f4c1",
    "group-wms": "\U0001f4e6",
    "group-hris": "\U0001f465",
    "group-system": "\u2699",
    "utility-account-settings": "\u2699",
    "utility-admin": "\u2699",
    "utility-theme": "\u2600",
    "utility-install": "\u2193",
    "utility-logout": "\u2192",
    WORKSPACE_ICON_FALLBACK_KEY: "\u25a6",
}

WORKSPACE_ICON_STYLE_CLASSES = {
    "hris-home": "app-icon-hris",
    "hris-dashboard": "app-icon-hris",
    "hris-employee": "app-icon-hris",
    "hris-leave": "app-icon-permission",
    "hris-payroll": "app-icon-finance",
    "hris-recruitment": "app-icon-hris",
    "hris-onboarding": "app-icon-sales",
    "hris-offboarding": "app-icon-sales",
    "hris-performance": "app-icon-report",
    "hris-helpdesk": "app-icon-hris",
    "hris-report": "app-icon-report",
    "hris-biometric": "app-icon-attendance",
    "hris-announcement": "app-icon-info",
    "hris-documents": "app-icon-sales",
    "coordination-pengumuman": "app-icon-info",
    "coordination-absen-foto": "app-icon-attendance",
    "coordination-libur": "app-icon-permission",
    "coordination-report-harian": "app-icon-sales",
    "coordination-jadwal": "app-icon-attendance",
    "coordination-chat-operasional": "app-icon-crm",
    "coordination-crm": "app-icon-crm",
    "wms-dashboard": "app-icon-wms",
    "wms-info-produk": "app-icon-wms",
    "wms-stok-produk": "app-icon-wms",
    "wms-kasir": "app-icon-pos",
    "wms-inbound": "app-icon-wms",
    "wms-outbound": "app-icon-wms",
    "wms-transfer": "app-icon-wms",
    "wms-request-gudang": "app-icon-permission",
    "wms-request-owner": "app-icon-finance",
    "wms-stock-opname": "app-icon-wms",
    "wms-approvals": "app-icon-permission",
    "wms-audit-log": "app-icon-hris",
    "group-workspace": "app-icon-drive",
    "group-wms": "app-icon-wms",
    "group-hris": "app-icon-hris",
    "group-system": "app-icon-setting",
    "utility-account-settings": "app-icon-setting",
    "utility-admin": "app-icon-setting",
    WORKSPACE_ICON_FALLBACK_KEY: "app-icon-wms",
}


def get_workspace_icon_asset(icon_key):
    safe_key = icon_key if icon_key in WORKSPACE_ICON_KEYS else WORKSPACE_ICON_FALLBACK_KEY
    return f"{WORKSPACE_ICON_BASE_PATH}/{safe_key}.svg"


def get_workspace_icon_symbol(icon_key):
    safe_key = icon_key if icon_key in WORKSPACE_ICON_SYMBOLS else WORKSPACE_ICON_FALLBACK_KEY
    return WORKSPACE_ICON_SYMBOLS[safe_key]


def get_workspace_icon_class(icon_key):
    safe_key = icon_key if icon_key in WORKSPACE_ICON_STYLE_CLASSES else WORKSPACE_ICON_FALLBACK_KEY
    return WORKSPACE_ICON_STYLE_CLASSES[safe_key]


def get_hris_workspace_icon_key(slug):
    return HRIS_MODULE_ICON_KEYS.get(slug, WORKSPACE_ICON_FALLBACK_KEY)
