HRIS_MODULES = (
    {
        "slug": "dashboard",
        "label": "Dashboard",
        "summary": "Ringkasan announcement aktif dan snapshot jadwal tim yang sudah tersambung ke HRIS.",
        "source": "custom/dashboard",
        "status": "Overview",
    },
    {
        "slug": "employee",
        "label": "Employee",
        "summary": "Data induk karyawan, struktur organisasi, jabatan, dan profil kerja.",
        "source": "horilla-1.0/employee",
        "status": "Core HR",
    },
    {
        "slug": "attendance",
        "label": "Attendance",
        "summary": "Presensi, validasi kehadiran, aktivitas clock in-out, dan overtime.",
        "source": "horilla-1.0/attendance",
        "status": "Time Tracking",
        "hidden": True,
    },
    {
        "slug": "leave",
        "label": "Leave",
        "summary": "Cuti, izin, approval leave, dan saldo kebijakan cuti karyawan.",
        "source": "horilla-1.0/leave",
        "status": "Policy",
    },
    {
        "slug": "payroll",
        "label": "Payroll",
        "summary": "Struktur gaji, komponen payroll, payslip, dan pemrosesan penggajian.",
        "source": "horilla-1.0/payroll",
        "status": "Compensation",
    },
    {
        "slug": "recruitment",
        "label": "Recruitment",
        "summary": "Vacancy, pipeline kandidat, interview flow, dan status rekrutmen.",
        "source": "horilla-1.0/recruitment",
        "status": "Hiring",
    },
    {
        "slug": "onboarding",
        "label": "Onboarding",
        "summary": "Checklist, handoff, dan tahapan masuk karyawan baru.",
        "source": "horilla-1.0/onboarding",
        "status": "Lifecycle",
    },
    {
        "slug": "offboarding",
        "label": "Offboarding",
        "summary": "Resign flow, clearance, serah terima, dan checklist keluar.",
        "source": "horilla-1.0/offboarding",
        "status": "Lifecycle",
    },
    {
        "slug": "pms",
        "label": "Performance",
        "summary": "Penilaian, objective review, feedback, dan performance cycle.",
        "source": "horilla-1.0/pms",
        "status": "Performance",
    },
    {
        "slug": "helpdesk",
        "label": "Helpdesk",
        "summary": "Ticket internal, support request, dan SLA operasional karyawan.",
        "source": "horilla-1.0/helpdesk",
        "status": "Support",
    },
    {
        "slug": "asset",
        "label": "Asset",
        "summary": "Distribusi aset karyawan, allocation request, dan pengembalian barang.",
        "source": "horilla-1.0/asset",
        "status": "Assets",
    },
    {
        "slug": "project",
        "label": "Project",
        "summary": "Project board, assignment, dan visibilitas deliverable tim.",
        "source": "horilla-1.0/project",
        "status": "Execution",
    },
    {
        "slug": "report",
        "label": "Report",
        "summary": "Laporan HR lintas modul untuk insight operasional dan people analytics.",
        "source": "horilla-1.0/report",
        "status": "Analytics",
    },
    {
        "slug": "biometric",
        "label": "Attendance Geotag",
        "summary": "Rekap absensi berbasis lokasi yang menyatukan log geotag dan attendance harian.",
        "source": "horilla-1.0/biometric",
        "status": "Geo Attendance",
    },
    {
        "slug": "announcement",
        "label": "Announcement",
        "summary": "Pengumuman operasional, broadcast internal, dan komunikasi kebijakan per gudang.",
        "source": "custom/announcement",
        "status": "Communication",
    },
    {
        "slug": "documents",
        "label": "Documents",
        "summary": "Register dokumen kerja, SOP, policy, dan review dokumen operasional HRIS.",
        "source": "custom/documents",
        "status": "Knowledge",
    },
)


FULL_HRIS_ROLES = {"super_admin", "hr"}
OWNER_HRIS_SPECIAL_ROLES = {"owner"}
GLOBAL_HRIS_DASHBOARD_ROLES = {"owner", "super_admin", "hr", "admin", "leader", "staff"}
SELF_SERVICE_HRIS_ROLES = {"leader", "admin", "staff"}
SELF_SERVICE_HRIS_MODULES = {"helpdesk"}

MODULE_VIEW_ROLE_MAP = {
    "dashboard": set(GLOBAL_HRIS_DASHBOARD_ROLES),
    "employee": set(FULL_HRIS_ROLES),
    "attendance": set(FULL_HRIS_ROLES),
    "leave": set(FULL_HRIS_ROLES),
    "payroll": set(FULL_HRIS_ROLES),
    "recruitment": set(FULL_HRIS_ROLES),
    "onboarding": set(FULL_HRIS_ROLES),
    "offboarding": set(FULL_HRIS_ROLES),
    "pms": set(FULL_HRIS_ROLES),
    "helpdesk": set(FULL_HRIS_ROLES | SELF_SERVICE_HRIS_ROLES),
    "asset": set(FULL_HRIS_ROLES),
    "project": set(FULL_HRIS_ROLES),
    "report": set(FULL_HRIS_ROLES),
    "biometric": set(FULL_HRIS_ROLES | OWNER_HRIS_SPECIAL_ROLES),
    "announcement": set(FULL_HRIS_ROLES),
    "documents": set(FULL_HRIS_ROLES),
}

MODULE_MANAGE_ROLE_MAP = {
    "dashboard": set(FULL_HRIS_ROLES),
    "employee": set(FULL_HRIS_ROLES),
    "attendance": set(FULL_HRIS_ROLES),
    "leave": set(FULL_HRIS_ROLES),
    "payroll": set(FULL_HRIS_ROLES),
    "recruitment": set(FULL_HRIS_ROLES),
    "onboarding": set(FULL_HRIS_ROLES),
    "offboarding": set(FULL_HRIS_ROLES),
    "pms": set(FULL_HRIS_ROLES),
    "helpdesk": set(FULL_HRIS_ROLES | SELF_SERVICE_HRIS_ROLES),
    "asset": set(FULL_HRIS_ROLES),
    "project": set(FULL_HRIS_ROLES),
    "report": set(FULL_HRIS_ROLES),
    "biometric": set(FULL_HRIS_ROLES | OWNER_HRIS_SPECIAL_ROLES),
    "announcement": set(FULL_HRIS_ROLES),
    "documents": set(FULL_HRIS_ROLES),
}


def _find_module(slug):
    for module in HRIS_MODULES:
        if module["slug"] == slug:
            return module
    return None


def can_view_hris_module(role, slug):
    module = _find_module(slug)
    if module is None:
        return False
    return (role or "") in MODULE_VIEW_ROLE_MAP.get(slug, set())


def can_manage_hris_module(role, slug):
    module = _find_module(slug)
    if module is None:
        return False
    return (role or "") in MODULE_MANAGE_ROLE_MAP.get(slug, set())


def role_can_see_hris_navigation(role):
    return (role or "") in (FULL_HRIS_ROLES | OWNER_HRIS_SPECIAL_ROLES)


def is_self_service_hris_module(role, slug):
    return (role or "") in SELF_SERVICE_HRIS_ROLES and slug in SELF_SERVICE_HRIS_MODULES


def role_has_hris_access(role):
    return any(can_view_hris_module(role, module["slug"]) for module in HRIS_MODULES)


def get_hris_modules(role=None):
    modules = []
    for module in HRIS_MODULES:
        item = dict(module)
        item["can_view"] = can_view_hris_module(role, item["slug"]) if role is not None else True
        item["can_manage"] = can_manage_hris_module(role, item["slug"]) if role is not None else False
        if item.get("hidden"):
            continue
        if role is None or item["can_view"]:
            modules.append(item)
    return modules


def get_hris_navigation_modules(role=None):
    if role is not None and not role_can_see_hris_navigation(role):
        return []
    return get_hris_modules(role)


def get_hris_module(slug, role=None):
    module = _find_module(slug)
    if module is None:
        return None

    item = dict(module)
    item["can_view"] = can_view_hris_module(role, slug) if role is not None else True
    item["can_manage"] = can_manage_hris_module(role, slug) if role is not None else False

    if role is not None and not item["can_view"]:
        return None
    return item
