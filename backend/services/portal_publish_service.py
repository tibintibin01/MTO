"""One-way public portal snapshot publishing.

The office database remains the source of truth. This service exports a
sanitized, read-only snapshot that the public web portal can consume without
receiving database credentials or write access.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import (
    Payment,
    PaymentBilling,
    Property,
    PropertyAssessmentHistory,
    PropertyBilling,
    TaxPolicy,
)
from backend.services.assessment_value_service import (
    assessed_value_for_year,
    assessment_versions,
    year_from_value as assessment_year,
)
from backend.services.billing_service import calculate_current_billing_amounts
from utils.config import config as mto_config
from utils.logger import mto_logger

DATA_START_YEAR = 2023
SNAPSHOT_SCHEMA_VERSION = 2


def _peso(value: Any) -> float:
    return round(float(value or 0), 2)


def _mask_owner_name(name: str) -> str:
    if not name or not str(name).strip():
        return "Taxpayer"
    parts = [p for p in str(name).strip().split() if p]
    masked = [p[0] + ("*" * 3 if len(p) > 1 else "") for p in parts]
    return " ".join(masked) if masked else "Taxpayer"


def _mask_pin(pin: str) -> str | None:
    if not pin:
        return None
    value = str(pin)
    if len(value) > 8:
        return value[:4] + "****" + value[-4:]
    return "PIN-****"


def _mask_or(or_number: str) -> str | None:
    if not or_number:
        return None
    value = str(or_number)
    return value[:3] + "****" if len(value) > 3 else "***"


def _lookup_hash(value: str, secret: str) -> str | None:
    if not value or not secret:
        return None
    normalized = str(value).strip().upper()
    return hmac.new(
        secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _owner_lookup_values(owner_name: str) -> set[str]:
    """
    Builds privacy-preserving owner search tokens.

    The public snapshot never contains raw owner names. Instead, the web portal
    hashes a citizen's search term with the same secret and compares it against
    these indexed hashes. We index token prefixes only up to 5 characters plus
    the complete token to keep the snapshot small enough for Vercel uploads.
    """
    if not owner_name:
        return set()
    normalized = str(owner_name).upper()
    tokens = re.findall(r"[A-Z0-9]+", normalized)
    values: set[str] = set()
    for token in tokens:
        if len(token) < 3:
            continue
        for length in range(3, min(5, len(token)) + 1):
            values.add(token[:length])
        values.add(token)
    return values


def _owner_lookup_hash(value: str, secret: str) -> str | None:
    digest = _lookup_hash(value, secret)
    # 96 bits is compact but still far beyond the collision risk acceptable for
    # a 16k-record municipal lookup index.
    return digest[:24] if digest else None


def _add_owner_index(
    owner_index: dict[str, list[int]], record_index: int, owner_name: str, secret: str
) -> None:
    if not secret:
        return
    for value in _owner_lookup_values(owner_name):
        digest = _owner_lookup_hash(value, secret)
        if digest:
            owner_index[digest].append(record_index)


def _status_from_balance(years: list[dict], balance: float) -> str:
    if not years:
        return "PENDING"
    if balance > 0:
        return "DELINQUENT"
    return "UPDATED"


def _snapshot_checksum(snapshot_without_checksum: dict) -> str:
    payload = json.dumps(
        snapshot_without_checksum,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def portal_snapshot_directory() -> str:
    """Returns the configured portal-only data directory."""
    configured = str(getattr(mto_config, "PORTAL_SNAPSHOT_DIR", "") or "").strip()
    if configured:
        return os.path.realpath(os.path.expanduser(configured))
    return os.path.realpath(os.path.join(mto_config.BACKUP_DIR, "portal_snapshots"))


def _atomic_write(path: str, payload: bytes) -> None:
    """Replaces a snapshot without exposing a partially written latest file."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(prefix=".portal_snapshot_", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def generate_portal_snapshot(db_session: Session) -> dict:
    """Builds a sanitized public portal snapshot from the office database."""
    published_at = datetime.now(timezone.utc).isoformat()
    as_of_year = datetime.now(timezone.utc).year
    lookup_secret = getattr(mto_config, "PORTAL_LOOKUP_SECRET", "") or ""

    policies = {
        int(p.tax_year): (
            float(p.basic_rate or 0.01),
            float(p.sef_rate or 0.01),
            float(p.penalty_rate or 0.02),
        )
        for p in db_session.query(TaxPolicy).all()
    }

    billing_rows = (
        db_session.query(PropertyBilling)
        .join(Property, Property.id == PropertyBilling.property_id)
        .filter(
            Property.deleted_at == None,
            PropertyBilling.tax_year >= DATA_START_YEAR,
            PropertyBilling.tax_year <= as_of_year,
        )
        .order_by(PropertyBilling.tax_year.asc())
        .all()
    )
    billings_by_property: dict[int, list[PropertyBilling]] = defaultdict(list)
    for billing in billing_rows:
        billings_by_property[int(billing.property_id)].append(billing)

    # For a payment linked to exactly one billing year, the receipt itself is
    # the authoritative historical amount. Legacy imports may leave the link
    # and billing summary stale after an assessment correction.
    receipt_values_by_billing: dict[int, dict[str, float]] = defaultdict(
        lambda: {"paid": 0.0, "penalty": 0.0, "discount": 0.0}
    )
    if billing_rows:
        billing_ids = [int(row.id) for row in billing_rows]
        linked_rows = (
            db_session.query(PaymentBilling, Payment)
            .join(Payment, Payment.id == PaymentBilling.payment_id)
            .filter(PaymentBilling.billing_id.in_(billing_ids))
            .all()
        )
        payment_ids = list({int(payment.id) for _link, payment in linked_rows})
        link_counts = {}
        if payment_ids:
            link_counts = dict(
                db_session.query(
                    PaymentBilling.payment_id, func.count(PaymentBilling.id)
                )
                .filter(PaymentBilling.payment_id.in_(payment_ids))
                .group_by(PaymentBilling.payment_id)
                .all()
            )
        for link, payment in linked_rows:
            summary = receipt_values_by_billing[int(link.billing_id)]
            if int(link_counts.get(payment.id, 0) or 0) == 1:
                summary["paid"] += _peso(payment.amount)
                summary["penalty"] += _peso(payment.penalty)
                summary["discount"] += _peso(payment.discount)
            else:
                summary["paid"] += _peso(link.amount_paid)

    payments_by_property: dict[int, list[Payment]] = defaultdict(list)
    payment_rows = (
        db_session.query(Payment)
        .join(Property, Property.id == Payment.property_id)
        .filter(Property.deleted_at == None)
        .order_by(Payment.date_paid.desc(), Payment.id.desc())
        .all()
    )
    for payment in payment_rows:
        payments_by_property[int(payment.property_id)].append(payment)

    histories_by_property: dict[int, list[PropertyAssessmentHistory]] = defaultdict(
        list
    )
    history_rows = (
        db_session.query(PropertyAssessmentHistory)
        .join(Property, Property.id == PropertyAssessmentHistory.property_id)
        .filter(Property.deleted_at == None)
        .order_by(
            PropertyAssessmentHistory.property_id.asc(),
            PropertyAssessmentHistory.id.asc(),
        )
        .all()
    )
    for history in history_rows:
        histories_by_property[int(history.property_id)].append(history)

    properties = (
        db_session.query(Property)
        .filter(Property.deleted_at == None)
        .order_by(Property.td_number.asc())
        .all()
    )

    records = []
    owner_lookup_index: dict[str, list[int]] = defaultdict(list)
    for prop in properties:
        years = []
        total_due = 0.0
        total_paid = 0.0
        total_balance = 0.0
        total_credit = 0.0

        for billing in billings_by_property.get(int(prop.id), []):
            tax_year = int(billing.tax_year)
            basic_rate, sef_rate, penalty_rate = policies.get(
                tax_year, (0.01, 0.01, 0.02)
            )
            assessed = _peso(billing.assessed_value)
            basic = round(assessed * basic_rate, 2)
            sef = round(assessed * sef_rate, 2)
            penalty = _peso(billing.penalty)
            discount = _peso(billing.discount)
            paid = _peso(billing.amount_paid)
            receipt_values = receipt_values_by_billing.get(int(billing.id))
            if receipt_values:
                paid = round(receipt_values["paid"], 2)
                # Keep legacy billing values when old receipts did not retain
                # penalty/discount components separately.
                if receipt_values["penalty"] > 0:
                    penalty = round(receipt_values["penalty"], 2)
                if receipt_values["discount"] > 0:
                    discount = round(receipt_values["discount"], 2)
            current = calculate_current_billing_amounts(
                assessed_value=assessed,
                tax_year=tax_year,
                paid=paid,
                recorded_penalty=penalty,
                discount=discount,
                basic_rate=basic_rate,
                sef_rate=sef_rate,
                penalty_rate=penalty_rate,
            )
            penalty = float(current["penalty"])
            due = float(current["total_due"])
            balance = float(current["balance"])
            credit = round(max(0.0, paid - due), 2)
            total_due += due
            total_paid += paid
            total_balance += balance
            total_credit += credit
            years.append(
                {
                    "tax_year": tax_year,
                    "assessed_value": assessed,
                    "basic": basic,
                    "sef": sef,
                    "penalty": penalty,
                    "discount": discount,
                    "total_due": due,
                    "amount_paid": paid,
                    "balance": balance,
                    "credit": credit,
                    "status": (
                        "Paid"
                        if paid >= due and due > 0
                        else "Partial" if paid > 0 else "Unpaid"
                    ),
                }
            )

        total_due = round(total_due, 2)
        total_paid = round(total_paid, 2)
        # Credits remain attached to their billing year until formally applied.
        # Never let an excess payment silently erase another year's receivable.
        balance = round(total_balance, 2)
        total_credit = round(total_credit, 2)
        payments = payments_by_property.get(int(prop.id), [])
        versions = assessment_versions(
            prop,
            db_session,
            history_rows=histories_by_property.get(int(prop.id), []),
        )
        effective_assessed = assessed_value_for_year(
            prop, as_of_year, db_session, versions=versions
        )
        if effective_assessed is None:
            # Legacy records without a dated assessment retain their master AV.
            effective_assessed = prop.assessed_value
        master_effective_year = assessment_year(prop.effectivity_date or prop.tax_year)
        future_assessment = None
        if master_effective_year and master_effective_year > as_of_year:
            future_assessment = {
                "assessed_value": _peso(prop.assessed_value),
                "effective_year": master_effective_year,
            }
        last_payment = None
        if payments:
            latest = payments[0]
            last_payment = {
                "date_paid": (
                    latest.date_paid.strftime("%Y-%m-%d") if latest.date_paid else None
                ),
                "period": latest.tax_year,
                "amount": _peso(latest.amount),
            }

        record_index = len(records)
        _add_owner_index(
            owner_lookup_index, record_index, prop.owner_name, lookup_secret
        )
        records.append(
            {
                "td_number": prop.td_number,
                # Opaque public selector used only after a duplicate TDN/PIN
                # lookup. It prevents exposing the internal database ID while
                # keeping every account's billing and payments isolated.
                "public_account_key": _lookup_hash(f"PROPERTY:{prop.id}", lookup_secret),
                "td_lookup_hash": _lookup_hash(prop.td_number, lookup_secret),
                "pin_masked": _mask_pin(prop.pin),
                "pin_lookup_hash": _lookup_hash(prop.pin, lookup_secret),
                "owner_name": _mask_owner_name(prop.owner_name),
                "barangay": prop.barangay,
                "location": prop.location,
                "kind": prop.kind_of_property,
                "assessed_value": _peso(effective_assessed),
                "assessment_as_of_year": as_of_year,
                "future_assessment": future_assessment,
                "status": _status_from_balance(years, balance),
                "balance": balance,
                "total_credit": total_credit,
                "total_due": total_due,
                "total_paid": total_paid,
                "billing_breakdown": years,
                "payment_history": [
                    {
                        "or_number": _mask_or(p.or_number),
                        "date_paid": (
                            p.date_paid.strftime("%Y-%m-%d") if p.date_paid else None
                        ),
                        "amount": _peso(p.amount),
                        "period": p.tax_year,
                    }
                    for p in payments
                ],
                "last_payment": last_payment,
            }
        )

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source": "MTO Treasury System",
        "published_at": published_at,
        "data_start_year": DATA_START_YEAR,
        "record_count": len(records),
        "properties": records,
        "owner_lookup_index": {
            key: value for key, value in sorted(owner_lookup_index.items())
        },
    }
    checksum = _snapshot_checksum(snapshot)
    snapshot["checksum"] = checksum
    return snapshot


def save_portal_snapshot(snapshot: dict) -> dict:
    """Saves timestamped and latest snapshot files on the office server."""
    base_dir = portal_snapshot_directory()
    os.makedirs(base_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    timestamped_path = os.path.join(base_dir, f"portal_snapshot_{stamp}.json")
    latest_path = os.path.join(base_dir, "portal_snapshot_latest.json")

    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    payload_bytes = payload.encode("utf-8")
    gzip_payload = gzip.compress(payload_bytes)
    timestamped_gzip_path = timestamped_path + ".gz"
    latest_gzip_path = latest_path + ".gz"

    _atomic_write(timestamped_path, payload_bytes)
    _atomic_write(latest_path, payload_bytes)
    _atomic_write(timestamped_gzip_path, gzip_payload)
    _atomic_write(latest_gzip_path, gzip_payload)

    return {
        "snapshot_path": timestamped_path,
        "latest_path": latest_path,
        "gzip_path": timestamped_gzip_path,
        "latest_gzip_path": latest_gzip_path,
        "bytes": len(payload_bytes),
        "gzip_bytes": len(gzip_payload),
    }


def publish_portal_snapshot(db_session: Session, dry_run: bool = False) -> dict:
    """
    Generates, saves, and optionally uploads the public portal snapshot.

    Upload only runs when MTO_PORTAL_PUBLISH_URL and MTO_PORTAL_PUBLISH_TOKEN
    are configured. This keeps the initial rollout safe and reviewable.
    """
    snapshot = generate_portal_snapshot(db_session)
    file_info = save_portal_snapshot(snapshot)

    result = {
        "status": "preview" if dry_run else "saved",
        "uploaded": False,
        "record_count": snapshot["record_count"],
        "checksum": snapshot["checksum"],
        "published_at": snapshot["published_at"],
        **file_info,
    }

    if dry_run:
        return result

    publish_url = getattr(mto_config, "PORTAL_PUBLISH_URL", "") or ""
    publish_token = getattr(mto_config, "PORTAL_PUBLISH_TOKEN", "") or ""
    if not publish_url or not publish_token:
        missing_configuration = []
        if not publish_url:
            missing_configuration.append("MTO_PORTAL_PUBLISH_URL")
        if not publish_token:
            missing_configuration.append("MTO_PORTAL_PUBLISH_TOKEN")
        result["status"] = "saved_not_uploaded"
        result["missing_configuration"] = missing_configuration
        result["message"] = (
            "Snapshot saved locally. Missing server configuration: "
            + ", ".join(missing_configuration)
            + ". Run python scripts/configure_portal_publish.py on the API server, "
            "then restart the API."
        )
        return result

    with open(file_info["latest_gzip_path"], "rb") as f:
        upload_payload = f.read()
    payload_hash = hashlib.sha256(upload_payload).hexdigest()

    response = requests.post(
        publish_url,
        data=upload_payload,
        headers={
            "Authorization": f"Bearer {publish_token}",
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "X-MTO-Snapshot-Checksum": snapshot["checksum"],
            "X-MTO-Snapshot-Records": str(snapshot["record_count"]),
            "X-MTO-Payload-Sha256": payload_hash,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        mto_logger.error(
            f"Portal snapshot upload failed: HTTP {response.status_code} {response.text[:300]}"
        )
        result["status"] = "upload_failed"
        result["message"] = f"Upload failed: HTTP {response.status_code}"
        return result

    result["status"] = "uploaded"
    result["uploaded"] = True
    result["message"] = "Portal snapshot uploaded successfully."
    return result
