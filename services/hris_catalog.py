HRIS_MODULES = (
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
        "label": "Biometric",
        "summary": "Integrasi biometric device dan sinkronisasi data kehadiran.",
        "source": "horilla-1.0/biometric",
        "status": "Integration",
    },
)


def get_hris_modules():
    return [dict(module) for module in HRIS_MODULES]


def get_hris_module(slug):
    for module in HRIS_MODULES:
        if module["slug"] == slug:
            return dict(module)
    return None
