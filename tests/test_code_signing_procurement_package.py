from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"
RUNBOOK = DOCS / "ORIGINAL_PHASE_5_SECURITY_RUNBOOK.md"
PACKAGE = DOCS / "ORIGINAL_PHASE_5_CODE_SIGNING_PROCUREMENT_PACKAGE.md"
VENDOR_TEMPLATE = (
    DOCS / "templates" / "ORIGINAL_PHASE_5_CODE_SIGNING_VENDOR_RESPONSE.md"
)
ACCEPTANCE_TEMPLATE = (
    DOCS / "templates" / "ORIGINAL_PHASE_5_CODE_SIGNING_DELIVERY_ACCEPTANCE.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_procurement_package_preserves_mandatory_trust_controls():
    content = _read(PACKAGE)

    for required in (
        "publicly trusted **Organization Validation (OV) code-signing",
        "exact legally validated name",
        "non-exportable",
        "1.3.6.1.5.5.7.3.3",
        "CA/Browser Forum",
        "RFC 3161",
        "Philippines",
        "No vendor is preferred or selected",
        "does not authorize a purchase",
    ):
        assert required in content


def test_vendor_response_requires_every_fail_closed_control():
    content = _read(VENDOR_TEMPLATE)

    assert "For every item, answer **Yes** or **No**" in content
    assert "Any **No** answer" in content
    for required in (
        "Publicly trusted for Microsoft Authenticode",
        "Philippine local government entity",
        "non-exportable hardware token",
        "Documented 24-hour revocation channel",
        "without exporting a PFX/private key",
    ):
        assert required in content


def test_delivery_acceptance_is_read_only_and_clears_selection():
    content = _read(ACCEPTANCE_TEMPLATE)

    assert "does not authorize production artifact signing" in content
    assert "--require-ready --confirm-managed-key-custody" in content
    assert "set MTO_CODE_SIGNING_CERT_THUMBPRINT=" in content
    assert "No artifact was signed during this read-only check" in content
    assert "disposable test-artifact signing" in content
    assert "Each action requires an explicit approval" in content
    assert "New-SelfSignedCertificate" not in content
    assert "signtool sign" not in content.lower()


def test_runbook_references_all_local_procurement_materials():
    runbook = _read(RUNBOOK)

    for document in (PACKAGE, VENDOR_TEMPLATE, ACCEPTANCE_TEMPLATE):
        assert document.is_file()
        assert document.name in runbook
