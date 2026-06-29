"""Configure one-way publishing from the office API to the public portal.

Run this script on the API server. It updates the ignored root ``.env`` file,
generates cryptographically strong shared secrets when needed, and prints the
values that an administrator must add to the Vercel project environment.
"""

from __future__ import annotations

import argparse
import os
import secrets
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_PUBLISH_URL = (
    "https://mto-portal-dipaculao.vercel.app/api/portal-snapshot/publish"
)
PLACEHOLDER_MARKERS = ("change", "replace", "generate", "example", "placeholder", "<")


def _read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def _usable_secret(value: str) -> bool:
    clean = (value or "").strip()
    return len(clean) >= 32 and not any(marker in clean.lower() for marker in PLACEHOLDER_MARKERS)


def _set_values(lines: list[str], updates: dict[str, str]) -> list[str]:
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)

    if remaining:
        if output and output[-1].strip():
            output.append("")
        output.append("# One-way public portal publishing")
        output.extend(f"{key}={value}" for key, value in remaining.items())
    return output


def _atomic_write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure secure portal snapshot publishing.")
    parser.add_argument("--url", default=DEFAULT_PUBLISH_URL, help="Production publish endpoint.")
    parser.add_argument(
        "--rotate-secrets",
        action="store_true",
        help="Generate new publish and lookup secrets even when valid values already exist.",
    )
    args = parser.parse_args()

    lines, current = _read_env(ENV_PATH)
    publish_token = current.get("MTO_PORTAL_PUBLISH_TOKEN", "")
    lookup_secret = current.get("MTO_PORTAL_LOOKUP_SECRET", "")
    if args.rotate_secrets or not _usable_secret(publish_token):
        publish_token = secrets.token_urlsafe(48)
    if args.rotate_secrets or not _usable_secret(lookup_secret):
        lookup_secret = secrets.token_urlsafe(48)

    updates = {
        "MTO_PORTAL_PUBLISH_URL": args.url.strip(),
        "MTO_PORTAL_PUBLISH_TOKEN": publish_token,
        "MTO_PORTAL_LOOKUP_SECRET": lookup_secret,
    }
    _atomic_write(ENV_PATH, _set_values(lines, updates))

    print(f"Configured server file: {ENV_PATH}")
    print("\nAdd these Environment Variables to the Vercel project (Production):")
    print(f"MTO_PORTAL_PUBLISH_TOKEN={publish_token}")
    print(f"MTO_PORTAL_LOOKUP_SECRET={lookup_secret}")
    print("\nKeep these values private. Do not commit or send them in chat/email.")
    print("After saving them in Vercel: redeploy the portal, then restart the MTO API server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
