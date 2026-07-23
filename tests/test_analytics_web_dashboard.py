from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "backend" / "static" / "analytics.html").read_text(encoding="utf-8")
DESKTOP = (ROOT / "ui" / "analytics_dashboard.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "backend" / "routes" / "billing.py").read_text(encoding="utf-8")


def test_web_dashboard_uses_the_desktop_operational_analytics_contract():
    assert 'const API_PATH="/analytics/operational"' in HTML
    assert "Total collected" in HTML
    assert "Payment transactions" in HTML
    assert "Properties paid" in HTML
    assert "Average receipt" in HTML
    assert "Recent receipts in selected period" in HTML
    assert "future_dated_payments" in HTML


def test_web_dashboard_is_self_contained_and_does_not_load_third_party_code():
    assert "cdn.jsdelivr.net" not in HTML
    assert "fonts.googleapis.com" not in HTML
    assert "<script src=" not in HTML
    assert '<link rel="stylesheet"' not in HTML


def test_analytics_token_is_handed_off_in_a_fragment_and_then_scrubbed():
    assert "/analytics#t={quote(token, safe='')}" in DESKTOP
    assert "/analytics?t={token}" not in DESKTOP
    assert 'hash.get("t")' in HTML
    assert 'query.get("t")' in HTML  # backward compatibility for old links
    assert "history.replaceState" in HTML
    assert "sessionStorage.setItem" in HTML


def test_analytics_page_cannot_be_cached_or_indexed():
    assert '"Cache-Control": "no-store, max-age=0"' in ROUTES
    assert '"Pragma": "no-cache"' in ROUTES
    assert '"X-Robots-Tag": "noindex, nofollow"' in ROUTES
