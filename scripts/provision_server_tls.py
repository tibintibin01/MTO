"""Provision an internal CA and authenticated TLS identity for the MTO LAN API."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.tls_config import (  # noqa: E402
    CertificateIdentity,
    ServerTLSConfig,
    validate_server_tls_config,
)
from scripts.configure_r2_backup import _harden_directory, _harden_file  # noqa: E402


CONFIRMATION = "PROVISION PHASE 2 AUTHENTICATED TLS"


@dataclass(frozen=True)
class CertificateBundle:
    ca_certificate: bytes
    ca_private_key: bytes
    server_certificate: bytes
    server_private_key: bytes


def default_tls_directory() -> Path:
    if os.name == "nt":
        return Path(os.getenv("PROGRAMDATA", "C:/ProgramData")) / "MTO" / "tls"
    return Path("/var/lib/mto/tls")


def validate_tls_directory(directory: Path) -> Path:
    resolved = directory.expanduser().resolve()
    if os.name == "nt":
        protected_root = (
            Path(os.getenv("PROGRAMDATA", "C:/ProgramData")) / "MTO"
        ).resolve()
    else:
        protected_root = Path("/var/lib/mto").resolve()
    try:
        resolved.relative_to(protected_root)
    except ValueError as exc:
        raise ValueError(
            f"TLS material must remain under the protected server path {protected_root}."
        ) from exc
    return resolved


def running_as_administrator() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def normalize_server_names(values: list[str]) -> tuple[str, ...]:
    names: list[str] = []
    for value in values:
        for item in value.split(","):
            name = item.strip().rstrip(".")
            if not name:
                continue
            if "*" in name or "/" in name or "://" in name or " " in name:
                raise ValueError(f"Invalid server identity: {name!r}")
            try:
                normalized = str(ipaddress.ip_address(name))
            except ValueError:
                if (
                    "." not in name
                    and name.lower() != "localhost"
                    and not name.replace("-", "").isalnum()
                ):
                    raise ValueError(f"Invalid DNS server identity: {name!r}")
                normalized = name.lower()
            if normalized not in names:
                names.append(normalized)
    if not names:
        raise ValueError(
            "At least one --server-name DNS name or IP address is required."
        )
    if not any(name not in {"localhost", "127.0.0.1", "::1"} for name in names):
        raise ValueError(
            "A LAN-reachable server IP address or DNS name is required in addition to loopback."
        )
    return tuple(names)


def _distinguished_name(common_name: str, organizational_unit: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PH"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Municipality of Dipaculao"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def create_certificate_bundle(
    server_names: tuple[str, ...],
    *,
    now: datetime | None = None,
    ca_key_size: int = 4096,
    server_key_size: int = 3072,
) -> CertificateBundle:
    """Create a five-year internal CA and a 397-day server certificate."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    valid_from = current_time - timedelta(minutes=5)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=ca_key_size)
    ca_subject = _distinguished_name("MTO LAN Root CA", "Municipal Treasury Office")
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(current_time + timedelta(days=1825))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(
        public_exponent=65537, key_size=server_key_size
    )
    primary_name = next(
        (
            name
            for name in server_names
            if name not in {"localhost", "127.0.0.1", "::1"}
        ),
        server_names[0],
    )
    subject = _distinguished_name(primary_name, "MTO Treasury API")
    san_values: list[x509.GeneralName] = []
    for name in server_names:
        try:
            san_values.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            san_values.append(x509.DNSName(name))

    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(current_time + timedelta(days=397))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    return CertificateBundle(
        ca_certificate=ca_certificate.public_bytes(serialization.Encoding.PEM),
        ca_private_key=ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        server_certificate=server_certificate.public_bytes(serialization.Encoding.PEM),
        server_private_key=server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def _atomic_write(path: Path, content: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f"{path.stem}-", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _harden_file(temporary_path)
        os.replace(temporary_path, path)
        _harden_file(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _backup_existing(directory: Path, paths: tuple[Path, ...]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_directory = directory / "previous" / timestamp
    backup_directory.mkdir(parents=True, exist_ok=False)
    _harden_directory(backup_directory.parent)
    _harden_directory(backup_directory)
    for path in existing:
        target = backup_directory / path.name
        shutil.copy2(path, target)
        _harden_file(target)
    return backup_directory


def _write_report(path: Path, identity: CertificateIdentity, directory: Path) -> None:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tls_directory": str(directory),
        "fingerprint_sha256": identity.fingerprint_sha256,
        "server_names": list(identity.server_names),
        "not_valid_after": identity.not_valid_after.isoformat(),
        "private_keys_displayed": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def provision(
    directory: Path,
    server_names: tuple[str, ...],
    *,
    replace: bool,
    report_path: Path,
) -> CertificateIdentity:
    directory = validate_tls_directory(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _harden_directory(directory)

    ca_certificate = directory / "mto-lan-ca.pem"
    ca_private_key = directory / "mto-lan-ca-key.pem"
    server_certificate = directory / "server-cert.pem"
    server_private_key = directory / "server-key.pem"
    paths = (ca_certificate, ca_private_key, server_certificate, server_private_key)
    if any(path.exists() for path in paths) and not replace:
        raise RuntimeError(
            "TLS material already exists. Re-run with --replace only during an approved CA rotation."
        )
    if replace:
        _backup_existing(directory, paths)

    bundle = create_certificate_bundle(server_names)
    _atomic_write(ca_certificate, bundle.ca_certificate)
    _atomic_write(ca_private_key, bundle.ca_private_key)
    _atomic_write(server_certificate, bundle.server_certificate)
    _atomic_write(server_private_key, bundle.server_private_key)

    config = ServerTLSConfig(
        enabled=True,
        required=True,
        directory=directory,
        certificate_file=server_certificate,
        private_key_file=server_private_key,
        ca_certificate_file=ca_certificate,
        server_names=server_names,
    )
    identity = validate_server_tls_config(config)
    assert identity is not None
    _write_report(report_path, identity, directory)
    return identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--server-name", action="append", required=True)
    parser.add_argument("--tls-dir", type=Path, default=default_tls_directory())
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "logs" / "remediation-phase-2-tls-provisioning.json",
    )
    args = parser.parse_args()

    try:
        server_names = normalize_server_names(args.server_name)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        directory = validate_tls_directory(args.tls_dir)
    except ValueError as exc:
        parser.error(str(exc))

    if args.preflight:
        existing = sum(
            (directory / name).exists()
            for name in (
                "mto-lan-ca.pem",
                "mto-lan-ca-key.pem",
                "server-cert.pem",
                "server-key.pem",
            )
        )
        is_administrator = running_as_administrator()
        blockers = []
        if existing and not args.replace:
            blockers.append(
                "Existing TLS material requires an explicitly approved "
                "--replace rotation."
            )
        if not is_administrator:
            blockers.append(
                "Administrator/root context is required to enforce private-key ACLs."
            )
        if blockers:
            print("PHASE 2 AUTHENTICATED TLS PREFLIGHT: BLOCKED")
            for blocker in blockers:
                print(f"- {blocker}")
            return 1

        print("PHASE 2 AUTHENTICATED TLS PREFLIGHT: PASS")
        print(f"- Protected TLS directory: {directory}")
        print(f"- Required certificate identities: {', '.join(server_names)}")
        print(f"- Existing managed TLS files: {existing}")
        print("- Administrator/root context: YES")
        print("- No certificate, key, configuration, or service was changed.")
        return 0

    print("This operation creates or rotates the MTO LAN certificate authority.")
    print("The CA private key must never be copied to a client or committed to Git.")
    if not running_as_administrator():
        print("PHASE 2 AUTHENTICATED TLS PROVISIONING: FAILED")
        print(
            "- Run this command as Administrator/root so private-key ACLs can be enforced."
        )
        return 1

    if input(f"Type {CONFIRMATION} to continue: ").strip() != CONFIRMATION:
        print("TLS provisioning cancelled.")
        return 2

    try:
        identity = provision(
            directory,
            server_names,
            replace=args.replace,
            report_path=args.report.resolve(),
        )
    except Exception as exc:
        print(f"PHASE 2 AUTHENTICATED TLS PROVISIONING: FAILED\n\n- {exc}")
        return 1

    print("PHASE 2 AUTHENTICATED TLS PROVISIONING: PASS")
    print(f"- Certificate SHA-256: {identity.fingerprint_sha256}")
    print(f"- Server identities: {', '.join(identity.server_names)}")
    print(f"- Certificate expires: {identity.not_valid_after.isoformat()}")
    print(f"- Public client CA: {directory / 'mto-lan-ca.pem'}")
    print(f"- Privacy-safe report: {args.report.resolve()}")
    print("  Secret values and private keys were not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
