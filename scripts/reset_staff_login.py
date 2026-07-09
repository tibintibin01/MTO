"""Reset or unlock a staff login from the server PC.

Usage:
    python scripts/reset_staff_login.py kevin
    python scripts/reset_staff_login.py kevin --unlock-only

The password is read from the terminal without echoing it, so it does not need
to be pasted into chat, a batch file, or command history.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.models import User  # noqa: E402
from backend.services.validation_service import validate_password_complexity  # noqa: E402
from utils import hash_password  # noqa: E402


def _read_new_password() -> str:
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match. No changes were made.")
    validate_password_complexity(first)
    return first


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unlock or reset an MTO staff login account."
    )
    parser.add_argument("username", help="Username to unlock/reset, for example: kevin")
    parser.add_argument(
        "--unlock-only",
        action="store_true",
        help="Clear failed attempts and lockout without changing the password.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Also mark the account active. Use only when you intentionally want to re-enable it.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        user = (
            db.query(User)
            .filter(User.username == args.username, User.deleted_at == None)  # noqa: E711
            .first()
        )
        if not user:
            raise SystemExit(f"User not found: {args.username}")

        if not args.unlock_only:
            user.password = hash_password(_read_new_password())
            user.password_changed_at = None

        user.failed_attempts = 0
        user.lockout_until = None
        if args.activate:
            user.is_active = True
        db.commit()

    action = "Unlocked" if args.unlock_only else "Reset password and cleared lockout"
    if args.activate:
        action += " and activated"
    print(f"{action} staff login for: {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
