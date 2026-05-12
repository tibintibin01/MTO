"""
Thin proxy for the modular PDF generation engine.
Delegates calls to specialized generator modules in backend/generators/.
"""
from backend.generators.receipt_gen import generate_or_receipt
from backend.generators.soa_gen import generate_statement_of_account, bulk_generate_soa
from backend.generators.notice_gen import generate_delinquency_notice
from backend.generators.dossier_gen import generate_property_dossier

# Re-exporting for system-wide compatibility
__all__ = [
    "generate_or_receipt",
    "generate_statement_of_account",
    "bulk_generate_soa",
    "generate_delinquency_notice",
    "generate_property_dossier",
]
