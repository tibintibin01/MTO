"""New workspace controls use synthetic accounts only, never office records."""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Property, PropertyBilling, Payment, PaymentBilling
from backend.services.report_credit_service import (
    build_credit_accounts_report,
    build_credit_account_ledger,
    CreditScopeChanged,
)
from backend.services.report_payload_service import (
    build_receivables_report,
    build_collection_report,
)
from ui.report_workspace_state import ReportViewState, period_label, captured_time_label

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "desktop"))
from ui.reports import ReportsPage
from ui.report_credit_accounts import CreditAccountsWindow


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def add_account(
    db, *, td="DEMO-SAME", year=2026, cash=2500, barangay="NORTH", paid_on=None
):
    prop = Property(
        td_number=td,
        owner_name="SYNTHETIC OWNER",
        barangay=barangay,
        assessed_value=100000,
        effectivity_date="2023",
    )
    db.add(prop)
    db.flush()
    bill = PropertyBilling(
        property_id=prop.id,
        tax_year=year,
        assessed_value=100000,
        penalty=0,
        discount=0,
        amount_paid=cash,
    )
    db.add(bill)
    db.flush()
    payment = Payment(
        property_id=prop.id,
        amount=cash,
        date_paid=paid_on or datetime(2026, 10, 14),
        tax_year=str(year),
        or_number=f"DEMO-OR-{prop.id}",
    )
    db.add(payment)
    db.flush()
    db.add(
        PaymentBilling(
            payment_id=payment.id, billing_id=bill.id, tax_year=year, amount_paid=cash
        )
    )
    db.commit()
    return prop, bill, payment


def test_complete_credit_list_includes_cent_and_duplicate_td_isolation(db):
    a, _, _ = add_account(db)
    b, _, _ = add_account(db, cash=2000.01, barangay="SOUTH")
    c, _, _ = add_account(db, cash=0, barangay="SOUTH")
    parent = build_receivables_report(2026, db)
    scope = parent["credit_scope"]
    assert scope["credit_total"] == "500.01"
    assert scope["account_count"] == scope["billing_count"] == 2
    assert parent["summary"]["ending_credit"] == pytest.approx(500.01)
    result = build_credit_accounts_report(
        2026, db, limit=1, expected_signature=scope["signature"]
    )
    assert result["count"] == 2 and result["has_more"]
    assert result["items"][0]["property_id"] == a.id
    second = build_credit_accounts_report(
        2026, db, limit=1, offset=1, expected_signature=scope["signature"]
    )
    assert second["items"][0]["property_id"] == b.id
    assert second["items"][0]["credit"] == "0.01"
    ledger = build_credit_account_ledger(b.id, 2026, db, scope["signature"])
    assert ledger["property_id"] != c.id
    assert ledger["items"][0]["credit"] == "0.01"
    assert ledger["items"][0]["receivable"] == "0.00"


def test_credit_cutoff_deleted_scope_and_escaped_search(db):
    a, _, _ = add_account(db, td="DEMO-100%", paid_on=datetime(2027, 1, 1))
    b, _, _ = add_account(db, td="DEMO-100_", barangay=" SOUTH ")
    c, _, _ = add_account(db, td="DEMO-DELETED")
    c.deleted_at = datetime(2026, 1, 1)
    db.commit()
    assert build_credit_accounts_report(2026, db)["count"] == 1
    all_years = build_credit_accounts_report(None, db)
    assert all_years["count"] == 2
    assert (
        build_credit_accounts_report(2026, db, barangay="SOUTH")["items"][0][
            "property_id"
        ]
        == b.id
    )
    assert (
        build_credit_accounts_report(None, db, search="%")["items"][0]["property_id"]
        == a.id
    )
    assert build_credit_accounts_report(2026, db, search="_")["count"] == 1
    assert (
        build_credit_accounts_report(2026, db, search="NOT PRESENT")["credit_total"]
        == "0.00"
    )
    with pytest.raises(LookupError):
        build_credit_account_ledger(c.id, 2026, db)


def test_drift_blocks_details_even_when_credit_total_is_unchanged(db):
    _, _, p1 = add_account(db, td="DEMO-A")
    _, _, p2 = add_account(db, td="DEMO-B")
    signature = build_receivables_report(2026, db)["credit_scope"]["signature"]
    links = db.query(PaymentBilling).order_by(PaymentBilling.payment_id).all()
    links[0].amount_paid += 100
    links[1].amount_paid -= 100
    p1.amount += 100
    p2.amount -= 100
    db.commit()
    assert build_credit_accounts_report(2026, db)["credit_total"] == "1000.00"
    with pytest.raises(CreditScopeChanged):
        build_credit_accounts_report(2026, db, expected_signature=signature)
    with pytest.raises(CreditScopeChanged):
        build_credit_account_ledger(p1.property_id, 2026, db, signature)


def test_credit_read_does_not_change_financial_records(db):
    prop, bill, _ = add_account(db)
    statements = []
    listener = lambda connection, cursor, statement, parameters, context, executemany: statements.append(
        statement.strip().upper()
    )
    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        build_credit_accounts_report(2026, db)
        build_credit_account_ledger(prop.id, 2026, db)
        build_receivables_report(2026, db)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert not any(
        s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "ALTER", "CREATE"))
        for s in statements
    )
    db.refresh(bill)
    assert bill.amount_paid == 2500 and bill.penalty == bill.discount == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"year": 1800},
        {"year": 2101},
        {"year": 2026, "limit": 0},
        {"year": 2026, "offset": -1},
        {"year": 2026, "search": "X" * 101},
    ],
)
def test_credit_inputs_are_bounded(db, kwargs):
    with pytest.raises(ValueError):
        build_credit_accounts_report(db_session=db, **kwargs)


def test_collection_totals_search_and_cursor_cover_all_pages(db):
    add_account(db, td="DEMO-A", cash=100)
    add_account(db, td="DEMO-B", cash=200)
    first = build_collection_report("10", "2026", db, limit=1)
    assert first["total_count"] == 2 and float(first["cash_total"]) == 300
    add_account(db, td="DEMO-NEW", cash=300)
    second = build_collection_report(
        "10", "2026", db, limit=1, cursor=first["next_cursor"], anchor=first["anchor"]
    )
    assert second["total_count"] == 2 and float(second["cash_total"]) == 300
    assert second["items"][0][2] == "DEMO-A"
    assert not second["has_more"]
    filtered = build_collection_report("10", "2026", db, search="DEMO-B")
    assert filtered["total_count"] == 1 and float(filtered["cash_total"]) == 200
    assert filtered["captured_at_utc"]


def test_collection_oldest_order_remains_paged_and_pinned(db):
    add_account(db, td="DEMO-FIRST", cash=100)
    add_account(db, td="DEMO-LAST", cash=200)
    first = build_collection_report("All", "2026", db, limit=1, order="oldest")
    assert first["items"][0][2] == "DEMO-FIRST"
    add_account(db, td="DEMO-LATER", cash=300)
    second = build_collection_report(
        "All",
        "2026",
        db,
        limit=1,
        order="oldest",
        anchor=first["anchor"],
        cursor=first["next_cursor"],
    )
    assert second["items"][0][2] == "DEMO-LAST" and not second["has_more"]
    assert second["total_count"] == 2
    with pytest.raises(ValueError):
        build_collection_report("All", "2026", db, order="unsafe")


def test_credit_private_api_auth_permissions_validation_and_drift(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routes.billing import router
    from backend.deps import get_current_user, get_db, read_only

    prop, _, payment = add_account(db)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/billing/credit-accounts?year=2026").status_code == 401
        app.dependency_overrides[get_current_user] = lambda: {"role": "NO SUCH ROLE"}
        assert client.get("/billing/credit-accounts?year=2026").status_code == 403
        for role in read_only.allowed_roles:
            app.dependency_overrides[get_current_user] = lambda r=role: {"role": r}
            response = client.get("/billing/credit-accounts?year=2026")
            assert response.status_code == 200
            assert response.json()["read_only"]
        assert client.get("/billing/credit-accounts?limit=201").status_code == 422
        assert client.get("/billing/credit-accounts?year=1800").status_code == 422
        assert client.get("/billing/credit-accounts?offset=-1").status_code == 422
        assert client.get("/billing/report-details?order=UNSAFE").status_code == 422
        assert client.get("/billing/report-details?month=13").status_code == 422
        scope = client.get("/billing/credit-accounts?year=2026").json()["scope"]
        ledger = client.get(
            f"/billing/credit-accounts/{prop.id}/ledger?year=2026&expected_signature={scope['signature']}"
        )
        assert ledger.status_code == 200 and ledger.json()["property_id"] == prop.id
        assert client.get("/billing/credit-accounts/999999/ledger").status_code == 404
        payment.amount += 1
        db.query(PaymentBilling).first().amount_paid += 1
        db.commit()
        assert (
            client.get(
                f"/billing/credit-accounts?year=2026&expected_signature={scope['signature']}"
            ).status_code
            == 409
        )
        assert (
            client.get(
                f"/billing/credit-accounts/{prop.id}/ledger?year=2026&expected_signature={scope['signature']}"
            ).status_code
            == 409
        )


def test_capture_time_is_explicitly_philippine_time_not_local_machine_time():
    assert (
        captured_time_label("2026-10-14T01:02:57+00:00") == "Oct 14, 2026 09:02 AM PHT"
    )
    assert captured_time_label("UNZONED FIXTURE") == "UNZONED FIXTURE"


def test_closing_report_page_discards_pending_callbacks():
    page = ReportsPage.__new__(ReportsPage)
    page._report_generations = {"receivables": 1}
    page._report_pending = {("receivables", 1)}
    page.container = SimpleNamespace(
        after=MagicMock(side_effect=RuntimeError("test page closed"))
    )
    callback = MagicMock()
    page._post_report_result("receivables", 1, callback)
    page._schedule_report_finish("receivables", 1)
    callback.assert_not_called()
    assert not page._report_pending


def test_resize_handlers_do_not_reconfigure_unchanged_geometry():
    # Redundant configure updates caused recursive scrollbar redraw at narrow
    # widths in native Tk QA. Keep the handlers idempotent and scale-aware.
    values = {"wraplength": 500, "width": 900}
    calls = []

    def configure(**options):
        calls.append(options)
        values.update(options)

    widget = SimpleNamespace(
        cget=lambda key: values[key],
        configure=configure,
        _get_widget_scaling=lambda: 1.25,
    )
    ReportsPage._wrap_report_label(widget, 500)
    ReportsPage._wrap_report_label(widget, 500)
    assert calls == [{"wraplength": 400}]
    page = ReportsPage.__new__(ReportsPage)
    page.tabview = SimpleNamespace(
        _segmented_button=widget, _get_widget_scaling=lambda: 1.25
    )
    page._fit_report_navigation(SimpleNamespace(width=1000))
    page._fit_report_navigation(SimpleNamespace(width=1000))
    assert calls[-1] == {"width": 780} and len(calls) == 2


def test_report_states_keep_selected_and_loaded_context_separate():
    state = ReportViewState()
    state.begin(("2026",))
    assert not state.can_export
    assert state.accept(("2026",), {"captured_at_utc": "DEMO"})
    state.select(("2025",))
    assert state.status == "changed" and state.loaded == ("2026",)
    assert not state.can_export
    assert not state.accept(("2026",), {})
    state.select(("2026",))
    assert state.can_export
    state.fail()
    state.select(("2026",))
    assert not state.can_export
    state.begin(("2026",))
    state.accept(("2026",), {}, has_rows=False)
    state.select(("2025",))
    state.select(("2026",))
    assert state.status == "empty" and not state.can_export
    assert "December 31, 2026" in period_label("receivables", ("2026",))


def test_export_guard_rejects_unloaded_changed_and_search_rcd():
    page = ReportsPage.__new__(ReportsPage)
    page._workspace_states = {"collection": ReportViewState()}
    page._selected_filters = lambda kind: ("10", "2026", "")
    with patch("ui.reports.messagebox.showinfo"):
        assert not page._workspace_export_allowed("collection")
        state = page._workspace_states["collection"]
        state.begin(("10", "2026", ""))
        state.accept(state.selected, {})
        assert page._workspace_export_allowed("collection")
        state.begin(("10", "2026", "DEMO"))
        state.accept(state.selected, {})
        page._selected_filters = lambda kind: state.selected
        assert not page._workspace_export_allowed("collection")


def test_credit_open_ledger_uses_exact_id_not_td():
    view = SimpleNamespace(
        tree=MagicMock(),
        rows={"row": {"property_id": 6, "td_number": "DEMO-SAME"}},
        year=2026,
        signature="DEMO",
    )
    view.tree.selection.return_value = ("row",)
    with patch("ui.report_credit_accounts.ReadOnlyAccountLedger") as open_ledger:
        CreditAccountsWindow.open_ledger(view)
    open_ledger.assert_called_once_with(view, 6, 2026, "DEMO")


def test_new_private_endpoints_retain_read_only_permission_dependency():
    from backend.routes.billing import router
    from backend.deps import read_only

    routes = [r for r in router.routes if "credit-accounts" in r.path]
    assert len(routes) == 2
    for route in routes:
        assert route.methods == {"GET"}
        assert read_only in [
            dependency.call for dependency in route.dependant.dependencies
        ]
