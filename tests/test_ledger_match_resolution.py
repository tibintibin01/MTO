import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "clients" / "desktop"))

from ui import ledger as ledger_module
from ui.ledger import LedgerPage


def _row(property_id, td_number, pin="", former_td=""):
    row = [None] * 21
    row[0] = property_id
    row[1] = td_number
    row[18] = pin
    row[20] = former_td
    return row


def _page():
    return LedgerPage.__new__(LedgerPage)


def test_current_td_wins_over_another_property_former_td():
    current = _row(10, "06-0009-01059")
    transferred = _row(20, "06-0009-02000", former_td="06-0009-01059")

    match, message = _page()._resolve_property_match(
        "06-0009-01059", [transferred, current]
    )

    assert match is current
    assert message is None


def test_exact_pin_wins_when_no_current_td_matches():
    pin_match = _row(30, "06-0009-03000", pin="123-45")
    owner_result = _row(40, "06-0009-04000")

    match, message = _page()._resolve_property_match(
        "123-45", [owner_result, pin_match]
    )

    assert match is pin_match
    assert message is None


def test_duplicate_former_td_remains_ambiguous():
    first = _row(50, "06-0009-05000", former_td="OLD-100")
    second = _row(60, "06-0009-06000", former_td="OLD-100")

    match, message = _page()._resolve_property_match("OLD-100", [first, second])

    assert match is None
    assert "Multiple properties share this former TD number" in message


def test_fresh_exact_current_td_lookup_returns_property_id(monkeypatch):
    calls = []

    def fake_find(term):
        calls.append(term)
        return {"id": 77, "td_number": "06-0009-01059"}

    monkeypatch.setattr(
        ledger_module.prop_svc,
        "find_property_by_td_number",
        fake_find,
    )

    property_id = _page()._find_exact_current_property_id("06-0009-01059")

    assert property_id == 77
    assert calls == ["06-0009-01059"]
