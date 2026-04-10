import re
from copy import deepcopy
from datetime import date as date_cls


KPI_WEEK_OPTIONS = ("W1", "W2", "W3", "W4")
KPI_REPORT_STATUSES = {"submitted", "reviewed", "follow_up"}
KPI_REPORT_STATUS_LABELS = {
    "submitted": "Menunggu Review",
    "reviewed": "Reviewed",
    "follow_up": "Perlu Follow Up",
}
KPI_WAREHOUSE_LABELS = {
    "mataram": "Mataram",
    "mega": "Mega",
    "stringers": "Stringers",
}
MONTH_LABELS = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def _metric(code, group, label, unit, target, weight):
    return {
        "code": code,
        "group": group,
        "label": label,
        "unit": unit,
        "target": float(target or 0),
        "weight": float(weight or 0),
    }


def _profile(
    key,
    display_name,
    warehouse_group,
    aliases,
    metrics,
    *,
    team_focus=None,
    minimum_pass_score=8,
    summary="",
):
    return {
        "key": key,
        "display_name": display_name,
        "warehouse_group": warehouse_group,
        "warehouse_label": KPI_WAREHOUSE_LABELS.get(warehouse_group, warehouse_group.title()),
        "aliases": list(aliases),
        "metrics": list(metrics),
        "team_focus": list(team_focus or []),
        "minimum_pass_score": float(minimum_pass_score or 0),
        "summary": summary.strip(),
    }


KPI_PROFILE_CATALOG = [
    _profile(
        "mataram-ella",
        "Efriella Cahya Putri",
        "mataram",
        ["efriella cahya putri", "ella", "efriella"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 56, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 2000000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 24000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 12, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 12, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 8, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_direktur_konten", "Spesifik Job", "Direktur of Konten", "Poin", 100, 0.05),
        ],
        team_focus=["Konten Tim", "Online Tim", "Offline Activity"],
        minimum_pass_score=8,
        summary="Format target KPI April Mataram untuk area live, offline, konten, dan peran konten.",
    ),
    _profile(
        "mataram-naufal",
        "Muhammad Naufal Ash-Shiddiq",
        "mataram",
        ["muhammad naufal ash shiddiq", "naufal", "m naufal"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 28, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 400000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 20000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 8, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 8, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 4, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_8_produk_fb", "Spesifik Job", "8 Produk FB", "Poin", 100, 0.05),
            _metric("job_cek_produk_harian", "Spesifik Job", "Cek Produk 10 produk/hari", "Poin", 150, 0.05),
        ],
        team_focus=["Konten Tim", "Online Tim", "Offline Activity"],
        minimum_pass_score=9,
        summary="Target KPI April Mataram untuk staff marketing offline dengan job khusus produk Facebook.",
    ),
    _profile(
        "mataram-yuni",
        "Bu Wahyuni",
        "mataram",
        ["bu wahyuni", "wahyuni", "yuni", "bu yuni"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 28, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 400000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 48000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 10, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 10, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 8, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_kontrol_staff_genz", "Spesifik Job", "Kontrolling staff genZ", "Poin", 100, 0.10),
        ],
        team_focus=["Konten Tim", "Online Tim", "Offline Activity"],
        minimum_pass_score=8,
        summary="Target KPI April Mataram untuk leader operasional dan pengawasan staff.",
    ),
    _profile(
        "mataram-prapti",
        "Bu Prapti",
        "mataram",
        ["bu prapti", "prapti"],
        [
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 48000000, 0.50),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 3, 0.15),
            _metric("job_co_stringer_raket", "Spesifik Job", "Co Stringer (Raket)", "Poin", 120, 0.15),
        ],
        team_focus=["Raket", "Konten Tim"],
        minimum_pass_score=3,
        summary="Target KPI khusus Mataram untuk fokus offline dan koordinasi stringer raket.",
    ),
    _profile(
        "mataram-febrio",
        "Febrio Dwi Putra",
        "mataram",
        ["febrio dwi putra", "febrio", "rio"],
        [
            _metric("offline_cv_transaksi", "Offline & CV", "Transaksi CV", "Transaksi", 2, 0.05),
            _metric("offline_cv_hpp", "Offline & CV", "Rp (HPP CV)", "Rp", 10000000, 0.20),
            _metric("offline_income", "Offline & CV", "Rp (Offline Income)", "Rp", 10000000, 0.20),
            _metric("offline_ulasan", "Offline & CV", "Ulasan (Mtr/CV)", "Ulasan", 10, 0.05),
            _metric("offline_crm", "Offline & CV", "CRM", "CRM", 4, 0.05),
            _metric("offline_slow", "Offline & CV", "Slow Moving", "Barang", 3, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_proposal", "Spesifik Job", "10 proposal offline / 1000 proposal online", "Poin", 100, 0.05),
            _metric("job_it_dev", "Spesifik Job", "IT Dev", "Poin", 100, 0.05),
        ],
        team_focus=["Konten Tim", "Offline Activity", "Proposal"],
        minimum_pass_score=9,
        summary="Target KPI April Mataram untuk CV, offline income, proposal, dan IT dev.",
    ),
    _profile(
        "mataram-fera",
        "Ferani Gifta Salsabila",
        "mataram",
        ["ferani gifta salsabila", "fera", "ferani"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 56, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 2000000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 24000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 12, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 15, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 8, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_pkwt_staff", "Spesifik Job", "PKWT Staff Kebiasaan", "Poin", 100, 0.10),
        ],
        team_focus=["Konten Tim", "Online Tim", "Offline Activity"],
        minimum_pass_score=8,
        summary="Target KPI April Mataram untuk live talent dengan CRM lebih tinggi dan fokus kebiasaan staff.",
    ),
    _profile(
        "mataram-muji",
        "Pak Muji",
        "stringers",
        ["pak muji", "muji"],
        [
            _metric("raket_badminton", "Raket", "Badminton", "Raket", 300, 0.50),
            _metric("raket_tenis", "Raket", "Tenis", "Raket", 10, 0.10),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_satpam_mataram", "Spesifik Job", "Menjadi Satpam di Mataram", "Poin", 100, 0.05),
            _metric(
                "job_awasi_customer",
                "Spesifik Job",
                "Mengawasi customer saat toko rame",
                "Poin",
                100,
                0.05,
            ),
        ],
        team_focus=["Raket", "Konten", "Satpam Toko"],
        minimum_pass_score=8,
        summary="Format KPI April untuk stringer Mataram dengan fokus raket dan penjagaan toko.",
    ),
    _profile(
        "mega-caca",
        "Cahyaningtyas Kusuma Dewi",
        "mega",
        ["cahyaningtyas kusuma dewi", "cahyaningtyas", "caca"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 28, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 400000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 38000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 12, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 12, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 12, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_admin", "Spesifik Job", "Admin", "Poin", 100, 0.05),
            _metric("job_leader_konten", "Spesifik Job", "Menjadi Leader Konten Yang Baik", "Poin", 100, 0.05),
        ],
        team_focus=["Konten Tim", "Online Shop Tim", "Offline Activity"],
        minimum_pass_score=9,
        summary="Target KPI April Mega untuk leader konten dan admin harian.",
    ),
    _profile(
        "mega-afif",
        "Afif Vanieda Saputra",
        "mega",
        ["afif vanieda saputra", "afif"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 28, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 400000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 38000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 12, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 12, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 12, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_leader", "Spesifik Job", "Menjadi Leader Yang Baik", "Poin", 100, 0.05),
            _metric("job_bantu_stringer", "Spesifik Job", "Membantu String Bu Ika (Raket)", "Poin", 125, 0.05),
        ],
        team_focus=["Konten Tim", "Online Shop Tim", "Offline Activity"],
        minimum_pass_score=9,
        summary="Target KPI April Mega untuk leader toko dan bantuan stringer raket.",
    ),
    _profile(
        "mega-lifia",
        "Dwi Lifia Ningrum",
        "mega",
        ["dwi lifia ningrum", "lifia", "livia"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 28, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 400000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 28000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 12, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 12, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 12, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_admin", "Spesifik Job", "Admin", "Poin", 100, 0.05),
            _metric("job_belajar_admin", "Spesifik Job", "Belajar Admin Lebih Dalam", "Poin", 100, 0.05),
        ],
        team_focus=["Konten Tim", "Online Shop Tim", "Offline Activity"],
        minimum_pass_score=9,
        summary="Target KPI April Mega untuk admin dan penguatan skill operasional admin.",
    ),
    _profile(
        "mega-ziza",
        "Aziza Sil Qotimah",
        "mega",
        ["aziza sil qotimah", "ziza", "aziza"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 84, 0.10),
            _metric("live_rp", "Live", "Live Rp", "Rp", 9000000, 0.10),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 12000000, 0.20),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 12, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 12, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 12, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_transfer_knowledge", "Spesifik Job", "Transfer Knowledge", "Poin", 100, 0.05),
            _metric("job_shopee_tt", "Spesifik Job", "Shopee & TT Ditingkatkan", "Poin", 100, 0.05),
        ],
        team_focus=["Konten Tim", "Online Shop Tim", "Offline Activity"],
        minimum_pass_score=9,
        summary="Target KPI April Mega untuk live utama, transfer knowledge, dan peningkatan marketplace.",
    ),
    _profile(
        "mega-afzaal",
        "Muhammad Afzaal Fazlullah",
        "mega",
        ["muhammad afzaal fazlullah", "afzaal", "fazlullah"],
        [
            _metric("live_jam", "Live", "Live Jam", "Jam", 28, 0.05),
            _metric("live_rp", "Live", "Live Rp", "Rp", 400000, 0.05),
            _metric("offline_rp", "Offline", "Offline Rp", "Rp", 38000000, 0.30),
            _metric("offline_ulasan", "Offline", "Offline Ulasan", "Ulasan", 12, 0.08),
            _metric("offline_crm", "Offline", "Offline CRM", "CRM", 12, 0.07),
            _metric("offline_slow", "Offline", "Offline Slow Moving", "Barang", 12, 0.05),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_bantu_stringer", "Spesifik Job", "Membantu String Bu Ika (Raket)", "Poin", 125, 0.05),
            _metric(
                "job_profesionalisme",
                "Spesifik Job",
                "Meningkatkan profesionalisme dan fokus selama jam kerja",
                "Poin",
                100,
                0.05,
            ),
        ],
        team_focus=["Konten Tim", "Online Shop Tim", "Offline Activity"],
        minimum_pass_score=9,
        summary="Target KPI April Mega untuk operasional toko dan penguatan profesionalisme kerja.",
    ),
    _profile(
        "stringers-ika",
        "Ika Budi N.",
        "stringers",
        ["ika budi n", "ika budi", "ika", "bu ika"],
        [
            _metric("raket_badminton", "Raket", "Badminton", "Raket", 300, 0.50),
            _metric("raket_tenis", "Raket", "Tenis", "Raket", 10, 0.10),
            _metric("konten_individu", "Konten", "Konten Individu", "Konten", 4, 0.10),
            _metric("job_bantu_marketing", "Spesifik Job", "Membantu Marketing Mega", "Poin", 100, 0.05),
            _metric("job_bantu_live", "Spesifik Job", "Membantu Live Mega", "Poin", 100, 0.05),
        ],
        team_focus=["Raket", "Konten", "Marketing Mega"],
        minimum_pass_score=8,
        summary="Format KPI April untuk stringer Mega dengan bantuan marketing dan live.",
    ),
]


KPI_FALLBACK_PROFILE_KEYS = {
    "mataram": "mataram-naufal",
    "mega": "mega-afif",
    "stringers": "stringers-ika",
}


def normalize_person_key(value):
    safe_value = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    return safe_value


def normalize_kpi_period_label(value, fallback_date=None):
    safe_value = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", safe_value):
        return safe_value
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", safe_value):
        return safe_value[:7]

    active_date = fallback_date or date_cls.today()
    return active_date.strftime("%Y-%m")


def format_kpi_period_label(period_label):
    safe_label = normalize_kpi_period_label(period_label)
    try:
        year, month = safe_label.split("-", 1)
        month_value = int(month)
        return f"{MONTH_LABELS.get(month_value, month_value)} {year}"
    except (AttributeError, TypeError, ValueError):
        return safe_label


def get_current_kpi_week_key(active_date=None):
    today_value = active_date or date_cls.today()
    day_value = int(today_value.day)
    if day_value <= 7:
        return "W1"
    if day_value <= 14:
        return "W2"
    if day_value <= 21:
        return "W3"
    return "W4"


def normalize_kpi_week_key(value, default=None):
    safe_value = str(value or "").strip().upper()
    if safe_value in KPI_WEEK_OPTIONS:
        return safe_value
    return default or get_current_kpi_week_key()


def normalize_kpi_report_status(value):
    safe_value = str(value or "").strip().lower()
    return safe_value if safe_value in KPI_REPORT_STATUSES else "submitted"


def get_kpi_profiles(warehouse_group=None):
    safe_group = str(warehouse_group or "").strip().lower()
    profiles = []
    for profile in KPI_PROFILE_CATALOG:
        if safe_group and profile["warehouse_group"] != safe_group:
            continue
        profiles.append(deepcopy(profile))
    return profiles


def get_kpi_profile_by_key(profile_key):
    safe_key = str(profile_key or "").strip().lower()
    for profile in KPI_PROFILE_CATALOG:
        if profile["key"] == safe_key:
            return deepcopy(profile)
    return None


def _resolve_warehouse_group(warehouse_name="", work_location="", position=""):
    haystack = " ".join([str(warehouse_name or ""), str(work_location or ""), str(position or "")]).lower()
    if "stringer" in haystack or "raket" in haystack:
        return "stringers"
    if "mega" in haystack:
        return "mega"
    return "mataram"


def resolve_kpi_profile(employee_name="", warehouse_name="", work_location="", position=""):
    employee_key = normalize_person_key(employee_name)
    for profile in KPI_PROFILE_CATALOG:
        alias_keys = [normalize_person_key(alias) for alias in profile.get("aliases", [])]
        if employee_key and employee_key in alias_keys:
            return deepcopy(profile)

    warehouse_group = _resolve_warehouse_group(warehouse_name, work_location, position)
    fallback_key = KPI_FALLBACK_PROFILE_KEYS.get(warehouse_group, "mataram-naufal")
    return get_kpi_profile_by_key(fallback_key)


def build_kpi_metric_entries(profile, actual_values_by_code=None):
    actual_values_by_code = actual_values_by_code or {}
    metric_entries = []
    for metric in profile.get("metrics", []):
        raw_actual = actual_values_by_code.get(metric["code"])
        try:
            actual_value = float(str(raw_actual or "").replace(",", "").strip() or 0)
        except (TypeError, ValueError):
            actual_value = 0.0
        target_value = float(metric.get("target") or 0)
        weight_value = float(metric.get("weight") or 0)
        if target_value > 0:
            achievement_ratio = min(max(actual_value / target_value, 0), 1)
        else:
            achievement_ratio = 0
        score_value = round(achievement_ratio * 10 * weight_value, 4)
        metric_entries.append(
            {
                **metric,
                "actual_value": actual_value,
                "achievement_ratio": round(achievement_ratio, 4),
                "score_value": score_value,
                "is_achieved": actual_value >= target_value if target_value > 0 else False,
            }
        )
    return metric_entries


def summarize_kpi_metric_entries(metric_entries):
    safe_entries = list(metric_entries or [])
    total_weight = round(sum(float(item.get("weight") or 0) for item in safe_entries), 4)
    weighted_score = round(sum(float(item.get("score_value") or 0) for item in safe_entries), 4)
    completion_count = sum(
        1 for item in safe_entries if float(item.get("actual_value") or 0) > 0
    )
    achieved_count = sum(1 for item in safe_entries if item.get("is_achieved"))
    total_metrics = len(safe_entries)
    completion_ratio = round((completion_count / total_metrics), 4) if total_metrics else 0
    return {
        "total_weight": total_weight,
        "weighted_score": weighted_score,
        "completion_ratio": completion_ratio,
        "completion_count": completion_count,
        "achieved_count": achieved_count,
        "total_metrics": total_metrics,
    }
