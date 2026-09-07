"""Fail-closed TLS configuration and certificate validation for the MTO API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
from typing import Mapping

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import (
    dsa,
    ec,
    ed25519,
    ed448,
    padding,
    rsa,
)
from cryptography.x509.oid import ExtendedKeyUsageOID


class TLSConfigurationError(RuntimeError):
    """Raised when the API cannot establish an authenticated TLS endpoint."""


@dataclass(frozen=True)
class ServerTLSConfig:
    enabled: bool
    required: bool
    directory: Path
    certificate_file: Path
    private_key_file: Path
    ca_certificate_file: Path
    server_names: tuple[str, ...]


@dataclass(frozen=True)
class CertificateIdentity:
    fingerprint_sha256: str
    server_names: tuple[str, ...]
    not_valid_after: datetime


def _default_tls_directory(environment: Mapping[str, str]) -> Path:
    if os.name == "nt":
        program_data = environment.get("PROGRAMDATA", "C:/ProgramData")
        return Path(program_data) / "MTO" / "tls"
    return Path("/var/lib/mto/tls")


def _enabled(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise TLSConfigurationError(f"Invalid boolean TLS setting: {value!r}")


def _path(value: str | None, default: Path) -> Path:
    if value and value.strip():
        return Path(value.strip()).expanduser().resolve()
    return default.resolve()


def _server_names(value: str | None) -> tuple[str, ...]:
    names: list[str] = []
    for item in (value or "").split(","):
        name = item.strip().rstrip(".")
        if not name:
            continue
        if "*" in name or "/" in name or "://" in name:
            raise TLSConfigurationError(f"Invalid TLS server identity: {name!r}")
        normalized = name.lower()
        if normalized not in names:
            names.append(normalized)
    return tuple(names)


def load_server_tls_config(
    environment: Mapping[str, str] | None = None,
) -> ServerTLSConfig:
    """Load paths and policy without reading any certificate or key material."""
    env = environment if environment is not None else os.environ
    deployment = env.get("MTO_ENVIRONMENT", env.get("ENVIRONMENT", "development"))
    production = deployment.strip().lower() == "production"
    required = production or _enabled(env.get("MTO_REQUIRE_TLS"), default=False)

    directory = _path(env.get("MTO_TLS_DIR"), _default_tls_directory(env))
    certificate_file = _path(
        env.get("MTO_TLS_CERT_FILE"), directory / "server-cert.pem"
    )
    private_key_file = _path(env.get("MTO_TLS_KEY_FILE"), directory / "server-key.pem")
    ca_certificate_file = _path(
        env.get("MTO_TLS_CA_FILE"), directory / "mto-lan-ca.pem"
    )
    names = _server_names(env.get("MTO_TLS_SERVER_NAMES"))

    configured_files_exist = all(
        item.is_file()
        for item in (certificate_file, private_key_file, ca_certificate_file)
    )
    enabled = required or configured_files_exist

    if enabled and not names:
        raise TLSConfigurationError(
            "MTO_TLS_SERVER_NAMES must list every approved DNS name or IP address "
            "used to reach the API (for example: "
            "192.0.2.10,localhost,127.0.0.1)."
        )

    if required:
        if os.name == "nt":
            protected_root = (
                Path(env.get("PROGRAMDATA", "C:/ProgramData")) / "MTO"
            ).resolve()
        else:
            protected_root = Path("/var/lib/mto").resolve()
        try:
            directory.relative_to(protected_root)
        except ValueError as exc:
            raise TLSConfigurationError(
                "MTO_TLS_DIR must remain inside the protected server path "
                f"{protected_root}."
            ) from exc

        try:
            private_key_file.relative_to(directory)
        except ValueError as exc:
            raise TLSConfigurationError(
                "MTO_TLS_KEY_FILE must remain inside the protected MTO_TLS_DIR."
            ) from exc

    return ServerTLSConfig(
        enabled=enabled,
        required=required,
        directory=directory,
        certificate_file=certificate_file,
        private_key_file=private_key_file,
        ca_certificate_file=ca_certificate_file,
        server_names=names,
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _read_certificate(path: Path, label: str) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except FileNotFoundError as exc:
        raise TLSConfigurationError(f"{label} was not found: {path}") from exc
    except (OSError, ValueError) as exc:
        raise TLSConfigurationError(
            f"{label} is unreadable or invalid: {path}"
        ) from exc


def _read_private_key(path: Path):
    try:
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    except FileNotFoundError as exc:
        raise TLSConfigurationError(f"TLS private key was not found: {path}") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise TLSConfigurationError(
            f"TLS private key is unreadable, encrypted, or invalid: {path}"
        ) from exc


def _verify_ca_signature(
    certificate: x509.Certificate, ca_certificate: x509.Certificate
) -> None:
    public_key = ca_certificate.public_key()
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                padding.PKCS1v15(),
                certificate.signature_hash_algorithm,
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                ec.ECDSA(certificate.signature_hash_algorithm),
            )
        elif isinstance(public_key, dsa.DSAPublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                certificate.signature_hash_algorithm,
            )
        elif isinstance(public_key, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
            public_key.verify(certificate.signature, certificate.tbs_certificate_bytes)
        else:
            raise TLSConfigurationError("Unsupported CA public-key algorithm.")
    except TLSConfigurationError:
        raise
    except Exception as exc:
        raise TLSConfigurationError(
            "The server certificate is not signed by the configured MTO LAN CA."
        ) from exc


def _certificate_names(certificate: x509.Certificate) -> tuple[str, ...]:
    try:
        san = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
    except x509.ExtensionNotFound as exc:
        raise TLSConfigurationError(
            "The server certificate has no Subject Alternative Name extension."
        ) from exc

    values = [
        item.lower().rstrip(".") for item in san.get_values_for_type(x509.DNSName)
    ]
    values.extend(str(item) for item in san.get_values_for_type(x509.IPAddress))
    return tuple(dict.fromkeys(values))


def validate_server_tls_config(
    config: ServerTLSConfig,
    *,
    now: datetime | None = None,
) -> CertificateIdentity | None:
    """Validate the chain, key, identity, purpose, and validity before binding."""
    if not config.enabled:
        return None

    certificate = _read_certificate(config.certificate_file, "TLS server certificate")
    ca_certificate = _read_certificate(
        config.ca_certificate_file, "MTO LAN CA certificate"
    )
    private_key = _read_private_key(config.private_key_file)
    current_time = _utc(now or datetime.now(timezone.utc))

    for item, label in (
        (ca_certificate, "MTO LAN CA certificate"),
        (certificate, "TLS server certificate"),
    ):
        if current_time < _utc(item.not_valid_before) or current_time >= _utc(
            item.not_valid_after
        ):
            raise TLSConfigurationError(f"{label} is not currently valid.")

    try:
        constraints = ca_certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound as exc:
        raise TLSConfigurationError(
            "The configured CA certificate lacks CA constraints."
        ) from exc
    if not constraints.ca:
        raise TLSConfigurationError(
            "The configured CA certificate is not a certificate authority."
        )
    _verify_ca_signature(ca_certificate, ca_certificate)

    try:
        leaf_constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound as exc:
        raise TLSConfigurationError(
            "The server certificate lacks CA constraints."
        ) from exc
    if leaf_constraints.ca:
        raise TLSConfigurationError(
            "A CA certificate cannot be used as the API server identity."
        )

    if certificate.issuer != ca_certificate.subject:
        raise TLSConfigurationError(
            "The server certificate issuer does not match the configured MTO LAN CA."
        )
    _verify_ca_signature(certificate, ca_certificate)

    try:
        extended_usage = certificate.extensions.get_extension_for_class(
            x509.ExtendedKeyUsage
        ).value
    except x509.ExtensionNotFound as exc:
        raise TLSConfigurationError(
            "The server certificate lacks the TLS server-authentication purpose."
        ) from exc
    if ExtendedKeyUsageOID.SERVER_AUTH not in extended_usage:
        raise TLSConfigurationError(
            "The certificate is not authorized for TLS server authentication."
        )

    certificate_public = certificate.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if certificate_public != private_public:
        raise TLSConfigurationError(
            "TLS server certificate and private key do not match."
        )

    certificate_names = _certificate_names(certificate)
    missing = []
    for required_name in config.server_names:
        try:
            normalized = str(ipaddress.ip_address(required_name))
        except ValueError:
            normalized = required_name.lower().rstrip(".")
        if normalized not in certificate_names:
            missing.append(required_name)
    if missing:
        raise TLSConfigurationError(
            "TLS server certificate is missing required identity value(s): "
            + ", ".join(missing)
        )

    if os.name != "nt" and config.private_key_file.stat().st_mode & 0o077:
        raise TLSConfigurationError(
            "TLS private key permissions are too broad; expected owner-only access."
        )

    from cryptography.hazmat.primitives import hashes

    return CertificateIdentity(
        fingerprint_sha256=certificate.fingerprint(hashes.SHA256()).hex(),
        server_names=certificate_names,
        not_valid_after=_utc(certificate.not_valid_after),
    )
