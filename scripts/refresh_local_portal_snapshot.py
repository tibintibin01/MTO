"""Refresh the local public portal snapshot without modifying database rows."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.services.portal_publish_service import (
    SNAPSHOT_SCHEMA_VERSION,
    _lookup_hash,
    generate_portal_snapshot,
    portal_snapshot_directory,
    save_portal_snapshot,
)
from utils.config import config as mto_config
from sqlalchemy.exc import SQLAlchemyError


def _published_at(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _snapshot_is_current(path: Path, secret: str, max_age_hours: float) -> bool:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        properties = snapshot.get("properties")
        if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION or not isinstance(
            properties, list
        ):
            return False
        if snapshot.get("record_count") != len(properties):
            return False
        sample = next(
            (
                row
                for row in properties
                if row.get("td_number") and row.get("td_lookup_hash")
            ),
            None,
        )
        if properties and (
            sample is None
            or _lookup_hash(sample["td_number"], secret) != sample["td_lookup_hash"]
        ):
            return False
        published = _published_at(snapshot.get("published_at"))
        if published is None:
            return False
        age_hours = (
            datetime.now(timezone.utc) - published.astimezone(timezone.utc)
        ).total_seconds() / 3600
        return age_hours <= max_age_hours
    except (OSError, ValueError, TypeError, StopIteration):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    secret = str(getattr(mto_config, "PORTAL_LOOKUP_SECRET", "") or "").strip()
    if len(secret) < 32:
        print(
            "[PORTAL] Snapshot refresh skipped: MTO_PORTAL_LOOKUP_SECRET is not configured."
        )
        return 2

    latest_path = Path(portal_snapshot_directory()) / "portal_snapshot_latest.json"
    if not args.force and _snapshot_is_current(latest_path, secret, args.max_age_hours):
        print(f"[PORTAL] Snapshot is current: {latest_path}")
        return 0

    print("[PORTAL] Generating a sanitized, read-only snapshot...")
    session = SessionLocal()
    try:
        try:
            snapshot = generate_portal_snapshot(session)
            file_info = save_portal_snapshot(snapshot)
        except SQLAlchemyError:
            print(
                "[PORTAL] Snapshot refresh failed: unable to connect to the configured database."
            )
            return 3
    finally:
        session.rollback()
        session.close()

    print(
        "[PORTAL] Snapshot refreshed: "
        f"records={snapshot['record_count']} path={file_info['latest_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
