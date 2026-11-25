"""Plain-language report labels shared by the desktop and export renderers."""

RECEIVABLES_COVERAGE_LABEL = "Receivables Coverage (including advance payments)"
RECEIVABLES_COVERAGE_HELP = (
    "Cash applied plus earlier advance payments applied, divided by this report's total collectible. "
    "This is not a taxpayer count or a current-year-only cash collection rate."
)
RECORDED_CREDIT_BALANCE_LABEL = "Recorded Credit Balance"
RECORDED_CREDIT_BALANCE_HELP = (
    "Payments above recorded charges on individual billings. "
    "Credits do not automatically settle other accounts or years. "
    "Not a discount or approved refund."
)
BARANGAY_APPLIED_RATE_HELP = (
    "Applied / Due = payments applied divided by total due, not remaining unpaid. "
    "Credits stay separate and do not settle other billings. Payments include credits, so the "
    "rate can exceed 100%. A dash means there is no positive total due."
)
