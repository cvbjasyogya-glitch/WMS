from decimal import Decimal, ROUND_FLOOR


MEMBER_TYPES = {"purchase", "stringing"}
MEMBER_TYPE_LABELS = {
    "purchase": "Member Pembelian",
    "stringing": "Member Senaran",
}

MEMBERSHIP_STATUSES = {"active", "inactive", "expired"}

MEMBER_RECORD_TYPES = {
    "join",
    "purchase",
    "renewal",
    "tier_update",
    "point_adjustment",
    "stringing_service",
    "reward_redemption",
    "note",
}

CRM_TRANSACTION_TYPES = {
    "purchase",
    "stringing_service",
    "stringing_reward_redemption",
}
CRM_TRANSACTION_TYPE_LABELS = {
    "purchase": "Belanja / Transaksi Normal",
    "stringing_service": "Senaran Berbayar",
    "stringing_reward_redemption": "Senaran Free Reward",
}

DEFAULT_STRINGING_REWARD_AMOUNT = 75000.0
STRINGING_PROGRESS_MIN_AMOUNT = 75000.0
PURCHASE_POINTS_DIVISOR = Decimal("10000")
STRINGING_REWARD_THRESHOLD = 6


def _to_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_currency(value):
    return "{:,.0f}".format(_to_float(value, 0)).replace(",", ".")


def normalize_member_type(value):
    member_type = (value or "").strip().lower()
    return member_type if member_type in MEMBER_TYPES else "purchase"


def normalize_membership_status(value):
    status = (value or "").strip().lower()
    return status if status in MEMBERSHIP_STATUSES else "active"


def normalize_member_record_type(value):
    record_type = (value or "").strip().lower()
    return record_type if record_type in MEMBER_RECORD_TYPES else "note"


def normalize_transaction_type(value):
    transaction_type = (value or "").strip().lower()
    return transaction_type if transaction_type in CRM_TRANSACTION_TYPES else "purchase"


def calculate_purchase_points(amount):
    safe_amount = Decimal(str(_to_float(amount, 0))).quantize(Decimal("0.01"))
    if safe_amount <= 0:
        return 0
    return int((safe_amount / PURCHASE_POINTS_DIVISOR).to_integral_value(rounding=ROUND_FLOOR))


def build_member_snapshot_from_row(row):
    member = dict(row or {})
    member["member_type"] = normalize_member_type(member.get("member_type"))
    member["requested_by_staff_id"] = _to_int(member.get("requested_by_staff_id"), 0) or None
    member["reward_unit_amount"] = _to_float(
        member.get("reward_unit_amount"),
        DEFAULT_STRINGING_REWARD_AMOUNT,
    )

    opening_points = _to_int(member.get("points"), 0)
    points_delta_total = _to_int(member.get("points_delta_total"), 0)
    member["current_points"] = opening_points + points_delta_total
    member["opening_points"] = opening_points
    member["points_delta_total"] = points_delta_total

    opening_visits = max(_to_int(member.get("opening_stringing_visits"), 0), 0)
    service_count_total = _to_int(member.get("service_count_total"), 0)
    total_stringing_visits = max(opening_visits + service_count_total, 0)
    member["opening_stringing_visits"] = opening_visits
    member["service_count_total"] = service_count_total
    member["total_stringing_visits"] = total_stringing_visits

    opening_reward_redeemed = max(_to_int(member.get("opening_reward_redeemed"), 0), 0)
    reward_redeemed_total = _to_int(member.get("reward_redeemed_total"), 0)
    total_reward_redeemed = max(opening_reward_redeemed + reward_redeemed_total, 0)
    member["opening_reward_redeemed"] = opening_reward_redeemed
    member["reward_redeemed_total"] = reward_redeemed_total
    member["total_reward_redeemed"] = total_reward_redeemed

    total_reward_earned = total_stringing_visits // STRINGING_REWARD_THRESHOLD
    available_reward_count = max(total_reward_earned - total_reward_redeemed, 0)
    progress_count = total_stringing_visits % STRINGING_REWARD_THRESHOLD
    remaining_visits = (
        STRINGING_REWARD_THRESHOLD
        if progress_count == 0
        else STRINGING_REWARD_THRESHOLD - progress_count
    )

    member["total_reward_earned"] = total_reward_earned
    member["available_reward_count"] = available_reward_count
    member["available_reward_value"] = round(
        available_reward_count * member["reward_unit_amount"],
        2,
    )
    member["stringing_progress_count"] = progress_count
    member["stringing_remaining_visits"] = remaining_visits
    member["stringing_progress_label"] = f"{progress_count}/{STRINGING_REWARD_THRESHOLD}"
    member["benefit_value_total"] = round(_to_float(member.get("benefit_value_total"), 0), 2)
    return member


def get_member_snapshot(db, member_id):
    row = db.execute(
        """
        SELECT
            m.*,
            COALESCE(SUM(mr.points_delta), 0) AS points_delta_total,
            COALESCE(SUM(mr.service_count_delta), 0) AS service_count_total,
            COALESCE(SUM(mr.reward_redeemed_delta), 0) AS reward_redeemed_total,
            COALESCE(SUM(mr.benefit_value), 0) AS benefit_value_total
        FROM crm_memberships m
        LEFT JOIN crm_member_records mr ON mr.member_id = m.id
        WHERE m.id=?
        GROUP BY m.id
        """,
        (member_id,),
    ).fetchone()
    if not row:
        return None
    return build_member_snapshot_from_row(row)


def calculate_loyalty_fields(member, amount, transaction_type, *, active=True):
    member_type = normalize_member_type(member.get("member_type"))
    transaction_type = normalize_transaction_type(transaction_type)
    safe_amount = round(_to_float(amount, 0), 2) if active else 0.0

    fields = {
        "record_type": "purchase",
        "points_delta": 0,
        "service_count_delta": 0,
        "reward_redeemed_delta": 0,
        "benefit_value": 0.0,
    }

    if member_type == "purchase":
        fields["points_delta"] = calculate_purchase_points(safe_amount)
        return fields

    if transaction_type == "stringing_service":
        fields["record_type"] = "stringing_service"
        fields["service_count_delta"] = (
            1 if active and safe_amount >= STRINGING_PROGRESS_MIN_AMOUNT else 0
        )
        return fields

    if transaction_type == "stringing_reward_redemption":
        fields["record_type"] = "reward_redemption"
        fields["reward_redeemed_delta"] = 1 if active else 0
        fields["benefit_value"] = (
            round(
                _to_float(member.get("reward_unit_amount"), DEFAULT_STRINGING_REWARD_AMOUNT),
                2,
            )
            if active
            else 0.0
        )
        return fields

    return fields


def build_auto_member_record(
    member,
    snapshot,
    *,
    purchase_id,
    warehouse_id,
    record_date,
    reference_no,
    amount,
    transaction_type,
    note="",
    handled_by=None,
    source_label="CRM",
):
    member_snapshot = build_member_snapshot_from_row({**dict(member or {}), **dict(snapshot or {})})
    fields = calculate_loyalty_fields(member_snapshot, amount, transaction_type, active=True)
    note_parts = []
    base_note = (note or "").strip()
    if base_note:
        note_parts.append(base_note)

    if member_snapshot["member_type"] == "purchase":
        if fields["points_delta"] > 0:
            note_parts.append(f"Otomatis dari {source_label}: +{fields['points_delta']} poin.")
        else:
            note_parts.append(f"Otomatis dari {source_label}: belum ada tambahan poin.")
    elif fields["record_type"] == "stringing_service":
        if fields["service_count_delta"] <= 0:
            note_parts.append(
                "Otomatis dari "
                f"{source_label}: nominal senaran di bawah Rp {_format_currency(STRINGING_PROGRESS_MIN_AMOUNT)}, "
                "member tetap aktif tetapi progres belum bertambah."
            )
        else:
            next_visit_total = member_snapshot["total_stringing_visits"] + fields["service_count_delta"]
            if next_visit_total // STRINGING_REWARD_THRESHOLD > member_snapshot["total_reward_earned"]:
                note_parts.append(
                    "Otomatis dari "
                    f"{source_label}: kunjungan senaran ke-{next_visit_total}, free 1x "
                    f"senilai Rp {_format_currency(member_snapshot['reward_unit_amount'])} siap dipakai."
                )
            else:
                remaining = (
                    STRINGING_REWARD_THRESHOLD
                    if next_visit_total % STRINGING_REWARD_THRESHOLD == 0
                    else STRINGING_REWARD_THRESHOLD - (next_visit_total % STRINGING_REWARD_THRESHOLD)
                )
                note_parts.append(
                    f"Otomatis dari {source_label}: kunjungan senaran ke-{next_visit_total}, "
                    f"sisa {remaining} lagi menuju free 1x."
                )
    elif fields["record_type"] == "reward_redemption":
        if member_snapshot["available_reward_count"] <= 0:
            raise ValueError("Member senaran ini belum punya free senar yang bisa dipakai.")
        note_parts.append(
            "Otomatis dari "
            f"{source_label}: free senar 1x dipakai senilai Rp {_format_currency(fields['benefit_value'])}."
        )
    else:
        note_parts.append(f"Otomatis dari {source_label}: transaksi tercatat tanpa perubahan loyalty khusus.")

    return {
        "member_id": member_snapshot["id"],
        "purchase_id": purchase_id,
        "warehouse_id": warehouse_id,
        "record_date": record_date,
        "record_type": fields["record_type"],
        "reference_no": reference_no or None,
        "amount": round(_to_float(amount, 0), 2),
        "points_delta": fields["points_delta"],
        "service_count_delta": fields["service_count_delta"],
        "reward_redeemed_delta": fields["reward_redeemed_delta"],
        "benefit_value": fields["benefit_value"],
        "note": " ".join(part for part in note_parts if part).strip() or None,
        "handled_by": handled_by,
    }
