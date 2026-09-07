"""Wait for the MTO API over an authenticated connection."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from scripts.tls_health import health_url, ssl_context_for_health_url  # noqa: E402


def wait_until_ready(
    *,
    timeout_seconds: int,
    url: str | None = None,
    ca_certificate: Path | None = None,
) -> bool:
    target = url or health_url()
    context = ssl_context_for_health_url(target, ca_certificate=ca_certificate)
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request = Request(target, method="GET")
            with urlopen(request, timeout=3, context=context) as response:
                if response.status == 200:
                    return True
                last_error = RuntimeError(f"readiness returned HTTP {response.status}")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(2)
    if last_error is not None:
        print(f"Last readiness error: {last_error}", file=sys.stderr)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--health-url")
    parser.add_argument("--ca-certificate", type=Path)
    args = parser.parse_args()
    if not 5 <= args.timeout_seconds <= 300:
        parser.error("--timeout-seconds must be between 5 and 300")

    print("Waiting for the updated MTO API to become ready...")
    try:
        ready = wait_until_ready(
            timeout_seconds=args.timeout_seconds,
            url=args.health_url,
            ca_certificate=args.ca_certificate,
        )
    except Exception as exc:
        print(f"MTO API readiness configuration failed: {exc}", file=sys.stderr)
        return 1
    if ready:
        print("MTO API authenticated readiness check passed.")
        return 0
    print(
        f"MTO API did not become ready within {args.timeout_seconds} seconds.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
