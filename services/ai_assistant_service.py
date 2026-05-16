from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None


JAKARTA_TZ = ZoneInfo("Asia/Jakarta") if ZoneInfo else timezone(timedelta(hours=7))


AI_KNOWLEDGE_TOPICS = (
    {
        "key": "domain",
        "title": "Peta Domain CVBJAS",
        "keywords": ("domain", "portal", "sms", "recruitment", "barcode", "cvbjas", "mataram"),
        "summary": "Domain publik sudah dipisah per fungsi supaya routing dan cookie lebih jelas.",
        "bullets": (
            "Portal ERP: https://portal.cvbjas.com",
            "Recruitment kandidat: https://recruitment.cvbjas.com",
            "SMS storage: https://mataramsport.space/sms/",
            "Website utama: https://cvbjas.com",
            "Barcode studio: https://barcode.cvbjas.com",
            "Senaran: https://senaran.cvbjas.com",
        ),
    },
    {
        "key": "deploy",
        "title": "Deploy Aman VPS",
        "keywords": ("deploy", "pull", "restart", "vps", "gunicorn", "nginx", "service"),
        "summary": "Deploy portal sebaiknya tetap kecil: tarik kode, compile Python, lalu restart service terkait.",
        "bullets": (
            "Portal utama memakai gunicorn socket /run/wms/gunicorn.sock.",
            "Setelah ganti nginx, selalu jalankan sudo nginx -t sebelum reload.",
            "Kalau socket hilang, cek systemd wms.service dulu sebelum menyalahkan aplikasi.",
        ),
        "commands": (
            "cd /root/WMS",
            "git pull",
            "python3 -m py_compile app.py routes/*.py services/*.py",
            "sudo systemctl restart wms.service",
            "sudo nginx -t",
            "sudo systemctl reload nginx",
        ),
    },
    {
        "key": "recruitment",
        "title": "Recruitment",
        "keywords": ("recruitment", "kandidat", "tes", "assessment", "hr", "cv", "ktp", "pelanggaran"),
        "summary": "Recruitment memakai cookie sendiri, profil kandidat otomatis masuk review HR, dan tes harus sekali jalan.",
        "bullets": (
            "Dokumen wajib kandidat: CV dan KTP.",
            "Riwayat pelanggaran assessment disimpan untuk review HR.",
            "Tampilan kandidat harus ringan karena banyak akses dari HP.",
            "Tanggal dan jam tampilan recruitment mengikuti Asia/Jakarta.",
        ),
    },
    {
        "key": "sms_storage",
        "title": "SMS Storage",
        "keywords": ("sms", "storage", "arsip", "hr storage", "mataramsport.space"),
        "summary": "SMS storage berisi arsip dokumen dan ringkasan HR yang harus mudah dibaca manusia.",
        "bullets": (
            "Domain SMS sekarang diarahkan ke mataramsport.space.",
            "Jika domain beda root dari portal.cvbjas.com, SESSION_COOKIE_DOMAIN sebaiknya kosong.",
            "Snapshot kandidat lebih aman disimpan sebagai TXT rapi daripada JSON mentah.",
        ),
    },
    {
        "key": "senaran",
        "title": "Senaran",
        "keywords": ("senaran", "antrian", "sqlite", "member", "stringing"),
        "summary": "Senaran berjalan sebagai aplikasi terpisah dengan SQLite sendiri, tidak menyentuh PostgreSQL ERP.",
        "bullets": (
            "Folder repo: deploy/apps/senaran.cvbjas.com",
            "Database VPS: /var/lib/senaran/antrian.db",
            "Service: senaran.service, socket: /run/senaran/gunicorn.sock",
            "Halaman member dibuat lazy supaya mobile tidak berat.",
        ),
        "commands": (
            "cd /root/WMS",
            "git pull",
            "cd /root/WMS/deploy/apps/senaran.cvbjas.com",
            "python3 -m py_compile app.py init_db.py",
            "SENARAN_DATABASE=/var/lib/senaran/antrian.db python3 init_db.py",
            "sudo systemctl restart senaran.service",
        ),
    },
    {
        "key": "ops",
        "title": "Catatan Operasional",
        "keywords": ("bug", "error", "socket", "cache", "browser", "backup", "absen", "mobile"),
        "summary": "Saat ada bug live, pisahkan sumber masalah: aplikasi, nginx, systemd, socket, cache, atau browser.",
        "bullets": (
            "Service worker dan auto-update aplikasi sudah dimatikan.",
            "VPS RAM kecil, jadi hindari halaman berat dan query besar saat load awal.",
            "Absen intern boleh tetap submit meski lokasi gagal terdeteksi.",
            "Poin belanja member di-reset bulanan ke 0 sesuai kebutuhan operasional.",
        ),
    },
)


QUICK_PROMPTS = (
    "Cek status sistem sekarang",
    "Ingatkan command deploy portal",
    "Apa yang perlu dicek kalau nginx error?",
    "Ringkas flow recruitment",
    "Command deploy senaran",
)


def get_ai_knowledge():
    return [dict(topic) for topic in AI_KNOWLEDGE_TOPICS]


def get_quick_prompts():
    return list(QUICK_PROMPTS)


def _now_jakarta():
    return datetime.now(JAKARTA_TZ)


def _format_count(value):
    if value is None:
        return "-"
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def _safe_count(db, query, params=()):
    try:
        row = db.execute(query, params).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        return int(row[0] or 0)
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def _safe_select_one(db):
    try:
        db.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def _count_tone(value, warning_threshold=1):
    if value is None:
        return "muted"
    return "warn" if int(value) >= warning_threshold else "ok"


def _coalesce_hosts(app_config, key, default_hosts):
    raw_hosts = app_config.get(key) if app_config else None
    if isinstance(raw_hosts, str):
        raw_hosts = [raw_hosts]
    hosts = [str(host).strip() for host in (raw_hosts or []) if str(host).strip()]
    return hosts or list(default_hosts)


def build_monitor_snapshot(db, app_config=None):
    app_config = app_config or {}
    now = _now_jakarta()
    canonical_host = str(app_config.get("CANONICAL_HOST") or "portal.cvbjas.com").strip()
    recruitment_hosts = _coalesce_hosts(app_config, "RECRUITMENT_PUBLIC_HOSTS", ("recruitment.cvbjas.com",))
    sms_hosts = _coalesce_hosts(app_config, "SMS_PUBLIC_HOSTS", ("mataramsport.space",))

    database_ok = _safe_select_one(db)
    counts = {
        "users": _safe_count(db, "SELECT COUNT(*) FROM users"),
        "warehouses": _safe_count(db, "SELECT COUNT(*) FROM warehouses"),
        "pending_requests": _safe_count(db, "SELECT COUNT(*) FROM requests WHERE status='pending'"),
        "pending_owner_requests": _safe_count(db, "SELECT COUNT(*) FROM owner_requests WHERE status='pending'"),
        "pending_approvals": _safe_count(db, "SELECT COUNT(*) FROM approvals WHERE status='pending'"),
        "pending_career_accounts": _safe_count(
            db,
            "SELECT COUNT(*) FROM career_public_account_requests WHERE status='pending'",
        ),
        "active_recruitment_candidates": _safe_count(
            db,
            """
            SELECT COUNT(*)
            FROM recruitment_candidates
            WHERE COALESCE(status, 'active')='active'
            """,
        ),
        "submitted_assessments": _safe_count(
            db,
            """
            SELECT COUNT(*)
            FROM recruitment_candidates
            WHERE COALESCE(assessment_status, '')='submitted'
            """,
        ),
        "unread_web_notifications": _safe_count(
            db,
            "SELECT COUNT(*) FROM web_notifications WHERE COALESCE(is_read, 0)=0",
        ),
    }

    cards = (
        {
            "label": "Database",
            "value": "Online" if database_ok else "Perlu cek",
            "tone": "ok" if database_ok else "danger",
            "note": "Query ringan SELECT 1 berhasil." if database_ok else "Koneksi database gagal di request ini.",
        },
        {
            "label": "Portal",
            "value": canonical_host or "portal.cvbjas.com",
            "tone": "ok",
            "note": "Halaman AI ini dirender dari app portal yang sedang aktif.",
        },
        {
            "label": "Recruitment",
            "value": recruitment_hosts[0],
            "tone": "ok",
            "note": f"{_format_count(counts['active_recruitment_candidates'])} kandidat aktif, {_format_count(counts['submitted_assessments'])} assessment submit.",
        },
        {
            "label": "SMS Storage",
            "value": sms_hosts[0],
            "tone": "ok",
            "note": "Dipantau dari konfigurasi host publik, bukan ping eksternal.",
        },
        {
            "label": "Queue Internal",
            "value": _format_count((counts["pending_requests"] or 0) + (counts["pending_owner_requests"] or 0)),
            "tone": _count_tone((counts["pending_requests"] or 0) + (counts["pending_owner_requests"] or 0)),
            "note": "Gabungan request gudang dan request owner yang pending.",
        },
    )

    queue_checks = (
        {
            "label": "Approval pending",
            "value": _format_count(counts["pending_approvals"]),
            "tone": _count_tone(counts["pending_approvals"]),
        },
        {
            "label": "Request gudang pending",
            "value": _format_count(counts["pending_requests"]),
            "tone": _count_tone(counts["pending_requests"]),
        },
        {
            "label": "Request owner pending",
            "value": _format_count(counts["pending_owner_requests"]),
            "tone": _count_tone(counts["pending_owner_requests"]),
        },
        {
            "label": "Akun recruitment pending",
            "value": _format_count(counts["pending_career_accounts"]),
            "tone": _count_tone(counts["pending_career_accounts"]),
        },
        {
            "label": "Notifikasi web belum dibaca",
            "value": _format_count(counts["unread_web_notifications"]),
            "tone": _count_tone(counts["unread_web_notifications"], warning_threshold=20),
        },
    )

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_label": now.strftime("%d/%m/%Y %H:%M WIB"),
        "database_ok": database_ok,
        "counts": counts,
        "cards": cards,
        "queue_checks": queue_checks,
        "domains": {
            "portal": canonical_host,
            "recruitment": recruitment_hosts,
            "sms": sms_hosts,
            "main_site": "cvbjas.com",
            "barcode": "barcode.cvbjas.com",
            "senaran": "senaran.cvbjas.com",
        },
    }


def _normalize_message(message):
    return " ".join(str(message or "").strip().lower().split())


def _topic_matches(topic, normalized_message):
    return any(keyword in normalized_message for keyword in topic.get("keywords", ()))


def _status_answer(snapshot):
    if not snapshot:
        return "Status belum tersedia. Coba buka ulang halaman AI agar snapshot monitor dibuat ulang."

    lines = [
        f"Snapshot {snapshot['generated_label']}:",
        f"- Database: {'online' if snapshot.get('database_ok') else 'perlu cek'}",
    ]
    for check in snapshot.get("queue_checks", ()):
        lines.append(f"- {check['label']}: {check['value']}")
    lines.append("Catatan: ini monitor internal ringan, bukan ping eksternal internet.")
    return "\n".join(lines)


def _format_topic_answer(topic):
    lines = [f"{topic['title']}: {topic['summary']}"]
    for bullet in topic.get("bullets", ()):
        lines.append(f"- {bullet}")
    commands = topic.get("commands") or ()
    if commands:
        lines.append("")
        lines.append("Command:")
        lines.extend(commands)
    return "\n".join(lines)


def answer_assistant_message(message, snapshot=None):
    normalized = _normalize_message(message)
    if not normalized:
        return {
            "answer": "Tulis dulu yang mau dicek. Contoh: cek status sistem, command deploy portal, atau flow recruitment.",
            "suggestions": get_quick_prompts(),
            "matched_topics": [],
        }

    if any(keyword in normalized for keyword in ("status", "monitor", "pantau", "cek web", "cek sistem", "sehat")):
        return {
            "answer": _status_answer(snapshot),
            "suggestions": ("Ingatkan command deploy portal", "Apa yang perlu dicek kalau nginx error?", "Ringkas flow recruitment"),
            "matched_topics": ["monitor"],
        }

    matched_topics = [topic for topic in AI_KNOWLEDGE_TOPICS if _topic_matches(topic, normalized)]
    if matched_topics:
        selected_topics = matched_topics[:2]
        answer = "\n\n".join(_format_topic_answer(topic) for topic in selected_topics)
        return {
            "answer": answer,
            "suggestions": get_quick_prompts(),
            "matched_topics": [topic["key"] for topic in selected_topics],
        }

    return {
        "answer": (
            "Saya sudah punya knowledge awal untuk domain, deploy, recruitment, SMS storage, senaran, "
            "dan catatan operasional VPS. Untuk sekarang saya menjawab dari knowledge lokal supaya ringan "
            "dan aman. Coba tanya lebih spesifik, misalnya: command deploy portal atau status recruitment."
        ),
        "suggestions": get_quick_prompts(),
        "matched_topics": [],
    }
