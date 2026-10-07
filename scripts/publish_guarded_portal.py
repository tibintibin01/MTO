"""Entry point for the owned SYSTEM publisher; no legacy upload fallback."""

import argparse
import json

from backend.services.guarded_portal_publish_service import execute_guarded_publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("operator", "scheduled", "verify"), required=True
    )
    args = parser.parse_args()
    result = execute_guarded_publication(args.mode)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
