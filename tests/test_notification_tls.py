import ssl

import ui.notifications as notifications


def test_websocket_requires_certificate_and_hostname_verification(monkeypatch):
    monkeypatch.setattr(notifications, "CERT_PATH", None)

    options = notifications.websocket_ssl_options()

    assert options["cert_reqs"] == ssl.CERT_REQUIRED
    assert options["check_hostname"] is True
    assert "ca_certs" not in options


def test_websocket_uses_configured_public_ca(monkeypatch, tmp_path):
    ca_path = tmp_path / "mto-lan-ca.pem"
    ca_path.write_text("public CA", encoding="utf-8")
    monkeypatch.setattr(notifications, "CERT_PATH", ca_path)

    options = notifications.websocket_ssl_options()

    assert options["ca_certs"] == str(ca_path)
