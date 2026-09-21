"""Authoritative product and protocol versions for MTO Treasury.

The product version is the immutable release identity and must match the
production Git tag. The API and minimum-client versions are compatibility
contracts; they change only when that contract changes, independently of a
normal product release.
"""

PRODUCT_NAME = "MTO Treasury System"
PRODUCT_VERSION = "2.1.2"

API_VERSION = "1.0"
MIN_CLIENT_VERSION = "1.0"
