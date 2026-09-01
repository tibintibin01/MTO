import inspect

from backend.routes import billing, health, payments, properties
from backend.middleware.security import request_timeout_for_path


def test_database_heavy_routes_run_in_fastapi_threadpool():
    route_functions = [
        billing.get_billing_summary,
        billing.get_property_statement,
        billing.get_assessment_roll,
        billing.get_receivables_summary,
        billing.get_reconciliation_metrics,
        billing.get_reconciliation_diagnostics,
        billing.get_delinquent_list,
        billing.get_collections_worklist,
        billing.get_compliant_list,
        billing.generate_notice_preview,
        billing.get_compliant_summary,
        billing.get_compliant_impact_preview,
        billing.get_receivables_by_barangay,
        billing.generate_computation_pdf,
        billing.generate_tax_bill_pdf,
        billing.generate_statement_pdf,
        billing.generate_bulk_soa_pdf,
        billing.generate_notice_pdf,
        properties.list_properties,
        properties.resolve_payment_target,
        properties.get_delinquent_accounts,
        properties.get_property,
        properties.create_property,
        properties.update_property,
        properties.delete_property,
        payments.get_recent_payments,
        payments.get_payment_records,
        payments.get_payment_details,
        payments.save_receipt_record,
        payments.get_payment_ledger,
        payments.update_payment,
        payments.delete_payment,
        health.health_check,
        health.get_system_stats,
    ]

    coroutine_routes = [
        function.__name__
        for function in route_functions
        if inspect.iscoroutinefunction(function)
    ]

    assert coroutine_routes == [], (
        "Synchronous database work must use plain def route handlers so FastAPI "
        f"runs it in its worker pool. Offending routes: {coroutine_routes}"
    )


def test_pdf_route_keeps_async_thread_offloading():
    assert inspect.iscoroutinefunction(payments.generate_receipt_pdf)


def test_property_document_routes_have_bounded_extended_timeout():
    assert request_timeout_for_path("/properties/4/computation-pdf") == 90
    assert request_timeout_for_path("/properties/4/tax-bill-pdf") == 90
    assert request_timeout_for_path("/properties/4/statement-pdf") == 90
    assert request_timeout_for_path("/properties/4/notice-pdf") == 90
    assert request_timeout_for_path("/properties/4/notice-preview") == 90
    assert request_timeout_for_path("/properties/4") == 30
    assert request_timeout_for_path("/billing/collections") == 90
    assert request_timeout_for_path("/health") == 30
