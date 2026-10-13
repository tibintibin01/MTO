"""Operator-run aggregate review only. No repair, upload, or task changes."""

import argparse
import json
from pathlib import Path

from backend.database import SessionLocal
from backend.services.report_accuracy_impact_service import (
    review_report_accuracy_impact,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="Optional privacy-safe JSON report path"
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        result = review_report_accuracy_impact(db)
    encoded = json.dumps(result, indent=2)
    if args.output:
        # Preserve earlier evidence; even an operator-supplied path is never overwritten.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
    print(encoded)
    return 2 if result["status"] == "REVIEW_REQUIRED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
