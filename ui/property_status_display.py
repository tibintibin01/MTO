"""Validate the year-aware count contract; never present legacy totals as active."""

STATUS_KEYS = (
    "active",
    "inactive_replaced",
    "future_effective",
    "archived",
    "needs_review",
)


def validated_property_status(summary):
    value = summary.get("property_status_counts") if isinstance(summary, dict) else None
    if (
        not isinstance(value, dict)
        or type(value.get("format_version")) is not int
        or value["format_version"] != 1
    ):
        return None
    year = value.get("as_of_tax_year")
    if type(year) is not int or not 1900 <= year <= 2299:
        return None
    keys = (*STATUS_KEYS, "registered_records", "total_records")
    if any(type(value.get(key)) is not int or value[key] < 0 for key in keys):
        return None
    if sum(value[key] for key in STATUS_KEYS) != value["total_records"]:
        return None
    if value["registered_records"] != value["total_records"] - value["archived"]:
        return None
    return {key: value[key] for key in ("as_of_tax_year", *keys)}
