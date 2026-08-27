"""Shared Assessment Roll labels for Assessor-authorized duplicate TD accounts."""

VERIFIED_DUPLICATE_LABEL = "VERIFIED DUPLICATE"
VERIFIED_DUPLICATE_TUPLE_INDEX = 23


def is_verified_duplicate_assessment_row(row):
    """Return whether an Assessment Roll row is a verified duplicate TD account."""
    if isinstance(row, dict):
        raw_value = row.get(
            "duplicate_td_verified",
            row.get("verified_duplicate_td", False),
        )
    else:
        raw_value = (
            row[VERIFIED_DUPLICATE_TUPLE_INDEX]
            if row is not None and len(row) > VERIFIED_DUPLICATE_TUPLE_INDEX
            else False
        )

    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(raw_value)


def assessment_roll_duplicate_status(row):
    """Return the user-facing status text for an Assessment Roll row."""
    if is_verified_duplicate_assessment_row(row):
        return VERIFIED_DUPLICATE_LABEL
    return ""


def assessment_roll_excel_values(item):
    """Return one Excel row and whether it needs verified-duplicate styling."""
    eff_year = item[21] if len(item) > 21 else ""
    if eff_year and len(str(eff_year)) >= 4:
        eff_year = str(eff_year)[:4]

    lot = item[4] if len(item) > 4 and item[4] else ""
    block = item[19] if len(item) > 19 and item[19] else ""
    lot_blk = f"{lot} / {block}" if lot and block else (lot or block or "")
    location = (
        item[22] if len(item) > 22 and item[22] else (item[6] if len(item) > 6 else "")
    )
    duplicate_status = assessment_roll_duplicate_status(item)

    return (
        [
            item[1] or "",
            item[18] if len(item) > 18 and item[18] else "",
            lot_blk,
            item[2] or "",
            location,
            item[7] if len(item) > 7 and item[7] else "",
            float(item[9] or 0),
            item[20] if len(item) > 20 and item[20] else "",
            eff_year or "",
            duplicate_status,
        ],
        bool(duplicate_status),
    )
