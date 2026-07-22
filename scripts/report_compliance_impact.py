"""Generate a read-only JSON preview of proposed compliance classifications."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.services.compliance_impact_service import build_compliance_impact_report
from sqlalchemy.exc import SQLAlchemyError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--year", type=int, required=True, help="Obligation year to evaluate through."
    )
    parser.add_argument("--detail-limit", type=int, default=500)
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        try:
            report = build_compliance_impact_report(
                as_of_year=args.year,
                detail_limit=args.detail_limit,
                db_session=session,
            )
        except SQLAlchemyError:
            print(
                "[COMPLIANCE] Unable to connect to the configured database; no report was generated."
            )
            return 3
    finally:
        # No commit is ever issued by this command.
        session.rollback()
        session.close()

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"Compliance impact report written to: {args.output.resolve()}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
