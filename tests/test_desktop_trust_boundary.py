from scripts.verify_desktop_trust_boundary import (
    verify_distribution,
    verify_pyz_manifest,
    verify_source_boundary,
    verify_spec_boundary,
)


def test_desktop_source_boundary_is_clean():
    assert verify_source_boundary() == []


def test_desktop_spec_boundary_is_clean():
    assert verify_spec_boundary() == []


def test_distribution_rejects_legacy_env_file(tmp_path):
    (tmp_path / ".env").write_text("MTO_DB_PASSWORD=unsafe", encoding="utf-8")

    errors = verify_distribution(tmp_path)

    assert errors
    assert ".env" in errors[0]


def test_distribution_accepts_executable_and_endpoint_config(tmp_path):
    (tmp_path / "Treasury.exe").write_bytes(b"desktop-binary")
    (tmp_path / "server_config.json").write_text(
        '{"server_url":"http://127.0.0.1:8001"}', encoding="utf-8"
    )

    assert verify_distribution(tmp_path) == []


def test_pyz_manifest_rejects_server_module(tmp_path):
    manifest = tmp_path / "PYZ-00.toc"
    manifest.write_text(
        repr(
            (
                "PYZ-00.pyz",
                [
                    ("api_clients.api_helper", "safe.py", "PYMODULE"),
                    ("backend.database", "unsafe.py", "PYMODULE"),
                ],
            )
        ),
        encoding="utf-8",
    )

    errors = verify_pyz_manifest(manifest)

    assert errors
    assert "backend.database" in errors[0]


def test_pyz_manifest_rejects_server_credential_rotation_module(tmp_path):
    manifest = tmp_path / "PYZ-00.toc"
    manifest.write_text(
        repr(
            (
                "PYZ-00.pyz",
                [
                    ("api_clients.api_helper", "safe.py", "PYMODULE"),
                    (
                        "scripts.rotate_server_credentials",
                        "unsafe.py",
                        "PYMODULE",
                    ),
                ],
            )
        ),
        encoding="utf-8",
    )

    errors = verify_pyz_manifest(manifest)

    assert errors
    assert "scripts.rotate_server_credentials" in errors[0]


def test_pyz_manifest_accepts_client_modules(tmp_path):
    manifest = tmp_path / "PYZ-00.toc"
    manifest.write_text(
        repr(
            (
                "PYZ-00.pyz",
                [
                    ("api_clients.api_helper", "safe.py", "PYMODULE"),
                    ("ui.property", "safe.py", "PYMODULE"),
                ],
            )
        ),
        encoding="utf-8",
    )

    assert verify_pyz_manifest(manifest) == []
