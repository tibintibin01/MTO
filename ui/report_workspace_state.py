"""Pure report-view state: selected filters are never confused with loaded scope."""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


def captured_time_label(value):
    try:
        captured = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            return str(value)  # Do not silently reinterpret an unzoned timestamp.
        return captured.astimezone(timezone(timedelta(hours=8))).strftime(
            "%b %d, %Y %I:%M %p PHT"
        )
    except (TypeError, ValueError):
        return str(value or "")


@dataclass
class ReportViewState:
    status: str = "ready"
    selected: tuple = ()
    loaded: tuple = ()
    captured_at: str = ""
    payload: dict | None = None
    has_rows: bool = False

    def select(self, filters):
        self.selected = tuple(filters)
        if self.loaded:
            self.status = (
                ("loaded" if self.has_rows else "empty")
                if self.selected == self.loaded
                else "changed"
            )
        elif self.status != "ready":
            self.status = "ready"

    def begin(self, filters):
        self.selected = tuple(filters)
        self.status = "loading"

    def accept(self, filters, payload, *, has_rows=True):
        if tuple(filters) != self.selected:
            return False
        self.loaded = tuple(filters)
        self.payload = payload
        self.has_rows = has_rows
        self.captured_at = payload.get("captured_at_utc", "")
        self.status = "loaded" if has_rows else "empty"
        return True

    def fail(self):
        self.status = "error"
        self.payload = None
        self.loaded = ()
        self.captured_at = ""

    @property
    def can_export(self):
        return self.status == "loaded" and self.loaded == self.selected


def period_label(kind, filters):
    if not filters:
        return "No report loaded"
    if kind == "collection":
        month, year = filters[:2]
        label = f"Month {month} / {year}" if month != "All" else f"All months / {year}"
        label += f" · {filters[3]}" if len(filters) > 3 else ""
        return label + (
            f" · Search: {filters[2]}" if len(filters) > 2 and filters[2] else ""
        )
    year = filters[0]
    return (
        "All billing years / all recorded payment dates"
        if year == "All Years"
        else f"Balances at December 31, {year}"
    )
