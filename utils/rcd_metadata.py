"""Report identity is separate from receipt dates and financial calculations."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
import unicodedata

PHILIPPINE_TIMEZONE = timezone(timedelta(hours=8))


def report_identifier_format(value):
    """Keep text identifiers intact, including in previews that coerce digit text."""
    text = str(value)
    return (
        "0" * len(text)
        if text.isascii() and text.isdigit() and len(text) <= 15
        else "@"
    )


def philippine_report_date() -> date:
    """Use the office date even when the desktop or API runs in another zone."""
    return datetime.now(PHILIPPINE_TIMEZONE).date()


@dataclass(frozen=True)
class RcdMetadata:
    report_number: str
    accountable_officer: str
    report_date: date


def _report_text(value, label, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError(f"{label} must be a single line without control characters.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{label} must be {limit} characters or fewer.")
    return value


def resolve_rcd_metadata(
    report_number="", accountable_officer="", report_date=None, *, required=False
) -> RcdMetadata:
    """Validate editable fields without assigning an official report sequence.

    Older clients may omit the newly added identity fields. New desktop exports
    require them. The date is captured as a value, never a volatile Excel formula.
    """
    number = _report_text(report_number, "Report number", 64)
    officer = _report_text(accountable_officer, "Accountable officer", 120)
    if required and (not number or not officer):
        raise ValueError("Enter the report number and accountable officer's name.")

    if report_date is None:
        selected_date = philippine_report_date()
    elif isinstance(report_date, date) and not isinstance(report_date, datetime):
        selected_date = report_date
    elif isinstance(report_date, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", report_date
    ):
        try:
            selected_date = date.fromisoformat(report_date)
        except ValueError as exc:
            raise ValueError("Enter a valid report date as YYYY-MM-DD.") from exc
    else:
        raise ValueError("Enter a valid report date as YYYY-MM-DD.")
    return RcdMetadata(number, officer, selected_date)
