"""Desktop client for the administrative tax-year readiness check."""

from api_clients.api_helper import api_request


def get_tax_year_readiness():
    """Fetch the read-only December/January rollover status."""
    return api_request(
        "GET",
        "/system/tax-year-readiness",
        queue_offline=False,
        timeout=15,
    )
