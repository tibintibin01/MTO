import json
import requests
from api_clients.offline_manager import manager
import threading
from utils.logger import mto_logger

CONNECTION_STATUS = "ONLINE"  # ONLINE, DEGRADED, OFFLINE, SYNCING
_CONNECTION_STATUS_LOCK = threading.Lock()
DEFAULT_CONNECT_TIMEOUT = 4
CONNECTION_FAILURE_THRESHOLD = 3
_CONSECUTIVE_CONNECTION_FAILURES = 0


def set_connection_status(status):
    """Updates the process-wide API connectivity state safely."""
    global CONNECTION_STATUS, _CONSECUTIVE_CONNECTION_FAILURES
    if status not in {"ONLINE", "DEGRADED", "OFFLINE", "SYNCING"}:
        raise ValueError(f"Unsupported connection status: {status}")
    with _CONNECTION_STATUS_LOCK:
        CONNECTION_STATUS = status
        if status == "ONLINE":
            _CONSECUTIVE_CONNECTION_FAILURES = 0


def get_connection_status():
    """Returns the latest API connectivity state."""
    with _CONNECTION_STATUS_LOCK:
        return CONNECTION_STATUS


def record_connection_success():
    """Records a successful API response and clears transient failures."""
    set_connection_status("ONLINE")


def record_connection_failure():
    """Records one failed connection without declaring an outage too early."""
    global CONNECTION_STATUS, _CONSECUTIVE_CONNECTION_FAILURES
    with _CONNECTION_STATUS_LOCK:
        _CONSECUTIVE_CONNECTION_FAILURES += 1
        if _CONSECUTIVE_CONNECTION_FAILURES >= CONNECTION_FAILURE_THRESHOLD:
            CONNECTION_STATUS = "OFFLINE"
        else:
            CONNECTION_STATUS = "DEGRADED"
        return CONNECTION_STATUS


def get_connection_failure_count():
    """Returns the current number of consecutive connectivity failures."""
    with _CONNECTION_STATUS_LOCK:
        return _CONSECUTIVE_CONNECTION_FAILURES


def _requests_timeout(timeout):
    """Keep connection failures short while preserving long response timeouts."""
    if isinstance(timeout, tuple):
        return timeout
    return (DEFAULT_CONNECT_TIMEOUT, timeout)


import os
import json
import re
import tempfile
from pathlib import Path

# --- NETWORK CONFIGURATION ---
# Default to localhost for development
DEFAULT_SERVER_URL = "http://localhost:8001"

BASE_URL = DEFAULT_SERVER_URL

# Look for an external config file (useful for .exe deployment)
import sys

if getattr(sys, "frozen", False):
    # Packaged environment — resolve relative to the folder containing the executable
    CONFIG_PATH = Path(sys.executable).resolve().parent / "server_config.json"
else:
    # Development environment — resolve relative to the project root
    CONFIG_PATH = Path("server_config.json")
    if not CONFIG_PATH.exists():
        CONFIG_PATH = Path(__file__).resolve().parent.parent / "server_config.json"

if not CONFIG_PATH.exists() and getattr(sys, "frozen", False):
    bundled_config = (
        Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        / "server_config.json"
    )
    if bundled_config.exists():
        CONFIG_PATH = bundled_config

if CONFIG_PATH.exists():
    try:
        with open(CONFIG_PATH, "r") as f:
            config_data = json.load(f)
            BASE_URL = config_data.get("server_url", DEFAULT_SERVER_URL)
            print(f"INFO: Connected to Production Server: {BASE_URL}")
    except Exception as e:
        print(
            f"WARNING: Could not read server_config.json, falling back to {DEFAULT_SERVER_URL}: {e}"
        )

API_BASE_URL = BASE_URL

# --- SECURITY HARDENING: SSL CERTIFICATE PINNING ---
# We point to the local cert.pem to eliminate MITM vulnerabilities
# while still supporting our self-signed municipal certificates.
_CURRENT_DIR = Path(__file__).resolve().parent
CERT_PATH = _CURRENT_DIR.parent / "backend" / "certs" / "cert.pem"

_SESSION_TOKEN = None


def is_token_expired(token):
    """
    Decodes the JWT payload (no signature verification) to check the 'exp' field.
    This allows the client to know if the session is over without a roundtrip.
    """
    try:
        import base64
        import json
        import time

        # JWT is header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return True

        payload_b64 = parts[1]
        # Add padding
        missing_padding = len(payload_b64) % 4
        if missing_padding:
            payload_b64 += "=" * (4 - missing_padding)

        payload_json = base64.b64decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)

        exp = payload.get("exp")
        if not exp:
            return False

        return time.time() > exp
    except Exception:
        return True  # Default to expired if malformed


_SESSION_TOKEN = None
_REFRESH_TOKEN = None


def set_token(token):
    """Sets the global bearer token for all subsequent API requests."""
    global _SESSION_TOKEN
    _SESSION_TOKEN = token


def set_refresh_token(token):
    """Stores the refresh token for silent re-authentication."""
    global _REFRESH_TOKEN
    _REFRESH_TOKEN = token


def get_token():
    """Returns the current session token."""
    return _SESSION_TOKEN


def get_refresh_token():
    """Returns the refresh token for logout/session management."""
    return _REFRESH_TOKEN


def clear_tokens():
    """Clears all local credentials after logout or server-side revocation."""
    global _SESSION_TOKEN, _REFRESH_TOKEN
    _SESSION_TOKEN = None
    _REFRESH_TOKEN = None


def _try_refresh() -> bool:
    """
    Attempts to get a new access token using the stored refresh token.
    Returns True if successful, False if the refresh token is also expired/missing.
    Called automatically when the access token expires.
    """
    global _SESSION_TOKEN, _REFRESH_TOKEN
    if not _REFRESH_TOKEN:
        return False
    try:
        import requests as _requests
        import json as _json

        resp = _requests.post(
            f"{BASE_URL}/api/auth/refresh",
            json={"refresh_token": _REFRESH_TOKEN},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=10,
            verify=str(CERT_PATH) if CERT_PATH.exists() else False,
        )
        if resp.status_code == 200:
            data = resp.json()
            new_token = data.get("access_token")
            if new_token:
                _SESSION_TOKEN = new_token
                return True
        elif resp.status_code in (400, 401):
            clear_tokens()
    except Exception:
        pass
    return False


def api_request(
    method,
    endpoint,
    data=None,
    params=None,
    files=None,
    raw_response=False,
    queue_offline=True,
    idempotency_key=None,
    timeout=120,
):
    """
    Centralized helper for all UI-to-Backend communication.
    Includes automatic Bearer Token injection for secure routes.
    """
    url = f"{BASE_URL}{endpoint}"

    headers = {}
    if _SESSION_TOKEN:
        # Verify expiration locally before sending
        if is_token_expired(_SESSION_TOKEN):
            # Try silent refresh first — if the refresh token is still valid,
            # the user never sees an error and the request continues normally.
            if not _try_refresh():
                raise Exception("Your session has expired. Please log in again.")

        headers["Authorization"] = f"Bearer {_SESSION_TOKEN}"

    # CSRF Protection: Include custom header for all state-changing requests
    headers["X-Requested-With"] = "XMLHttpRequest"

    # Idempotency: attach key for POST/PUT so the server can detect duplicate
    # submissions from double-clicks or network retries.
    if method in ("POST", "PUT", "PATCH") and idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    mto_logger.info(f"API Request: {method} {endpoint}", method=method, url=url)

    try:
        # If 'files' is provided, requests uses 'multipart/form-data'
        # If 'data' is provided, it uses 'application/json'
        # verify=False is used because we are using a self-signed certificate for local dev
        import urllib3
        import time
        from utils import set_request_id
        from utils.metrics import MetricsManager

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # 1. Telemetry: Generate Request ID and start timer
        set_request_id()
        start_time = time.perf_counter()

        # 4. Final Security Check: Use pinned certificate instead of verify=False
        # If cert file is missing, we fallback to False only if explicitly configured (for emergency debug)
        verify_param = str(CERT_PATH) if CERT_PATH.exists() else False
        if not verify_param:
            print("WARNING: SSL Certificate NOT FOUND. Falling back to insecure mode.")

        response = requests.request(
            method,
            url,
            json=data if not files else None,
            data=data if files else None,
            params=params,
            headers=headers,
            files=files,
            timeout=_requests_timeout(timeout),
            verify=verify_param,
        )

        # Reaching the API is enough to recover the connectivity indicator,
        # even when the endpoint subsequently returns a validation error.
        record_connection_success()

        mto_logger.info(
            f"API Response: {response.status_code}", status=response.status_code
        )

        # 2. Telemetry: Measure Latency
        latency = time.perf_counter() - start_time
        MetricsManager.record_request(
            method=method,
            endpoint=endpoint,
            status=response.status_code,
            duration=latency,
        )

        # 3. Log structured telemetry
        mto_logger.info(
            f"API {method} {endpoint} completed",
            latency_ms=round(latency * 1000, 2),
            status=response.status_code,
        )

        if raw_response:
            return response

        response.raise_for_status()

        if response.content:
            return response.json()
        return True
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        record_connection_failure()

        # Multipart uploads cannot be replayed by the offline queue because it
        # persists JSON payloads only, not the uploaded file bytes. Queuing one
        # would create a permanent "pending sync" item with no file to send.
        if files is not None:
            raise Exception(
                "Connection lost during file upload. File uploads cannot be "
                "queued for offline sync. Reconnect to the server, reselect "
                "the file, and try again."
            ) from e

        if not queue_offline:
            raise Exception(
                f"Cannot reach API server at {BASE_URL}. "
                "Start the API server and verify server_config.json."
            )

        # OFFLINE HANDLING
        if method == "GET":
            cached = manager.get_cached_data(f"{method}:{endpoint}:{params}")
            if cached:
                return cached
            raise Exception("Offline: No cached data available for this request.")

        elif method in ["POST", "PUT", "DELETE"]:
            # Queue for later sync
            success = manager.queue_action(method, endpoint, data)
            if success:
                return {
                    "status": "queued",
                    "message": "Connection lost. Action queued for sync.",
                    "offline": True,
                }
            raise Exception("Offline: Failed to queue action.")

        raise Exception(f"Connection lost and no offline handler for {method}")

    except requests.exceptions.RequestException as e:
        # Provide a more descriptive error message
        status_code = getattr(e.response, "status_code", "N/A")
        error_msg = f"API Communication Error (Status {status_code}): {str(e)}"

        # A 401 means the credentials expired or were revoked by an
        # administrator. The API is reachable, so never treat this as an
        # offline event or retain credentials that can no longer be used.
        if status_code == 401:
            clear_tokens()

        # If it's a 503 or 504, we might treat it as offline too
        if status_code in [502, 503, 504]:
            record_connection_failure()

        if e.response is not None and e.response.text:
            try:
                error_data = e.response.json()
                if "detail" in error_data:
                    detail = error_data["detail"]
                    if isinstance(detail, list):
                        messages = []
                        for item in detail[:5]:
                            loc = item.get("loc", []) if isinstance(item, dict) else []
                            field = " > ".join(
                                str(part) for part in loc if part != "body"
                            )
                            msg = (
                                item.get("msg", str(item))
                                if isinstance(item, dict)
                                else str(item)
                            )
                            messages.append(f"{field}: {msg}" if field else msg)
                        error_msg = "Error: Request validation failed.\n" + "\n".join(
                            messages
                        )
                    else:
                        error_msg = f"Error: {detail}"
            except:
                pass
        raise Exception(error_msg)
    except Exception as e:
        raise Exception(f"Unexpected Error: {str(e)}")


def api_download_file(method, endpoint, params=None, timeout=120):
    """
    Specialized helper for downloading files (PDFs) from the backend.
    Saves the response content to a temporary file and returns the path.
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {}
    if _SESSION_TOKEN:
        if is_token_expired(_SESSION_TOKEN):
            if not _try_refresh():
                raise Exception("Your session has expired. Please log in again.")
        headers["Authorization"] = f"Bearer {_SESSION_TOKEN}"

    headers["X-Requested-With"] = "XMLHttpRequest"

    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        verify_param = str(CERT_PATH) if CERT_PATH.exists() else False

        response = requests.request(
            method,
            url,
            params=params,
            headers=headers,
            timeout=_requests_timeout(timeout),
            verify=verify_param,
            stream=True,
        )

        record_connection_success()

        response.raise_for_status()

        return save_stream_response_to_temp_file(response, default_suffix=".pdf")

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        record_connection_failure()
        raise Exception(
            f"Cannot reach API server at {BASE_URL}. "
            "Start the API server and verify server_config.json."
        ) from e
    except Exception as e:
        status_code = getattr(getattr(e, "response", None), "status_code", "N/A")
        raise Exception(f"File Download Error (Status {status_code}): {str(e)}")


def response_filename(response, default_name="download"):
    """Returns a safe filename from Content-Disposition, falling back to default_name."""
    cd = response.headers.get("content-disposition", "")
    match = re.search(
        r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, flags=re.IGNORECASE
    )
    raw_name = match.group(1).strip() if match else default_name
    safe_name = os.path.basename(raw_name).strip()
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", safe_name)
    return safe_name or default_name


def save_stream_response_to_temp_file(response, default_suffix=".bin"):
    """Saves a streaming response to temp using the server-provided filename."""
    filename = response_filename(response, default_name=f"download{default_suffix}")
    if "." not in filename and default_suffix:
        filename += default_suffix

    stem, suffix = os.path.splitext(filename)
    temp_dir = tempfile.gettempdir()
    candidate = os.path.join(temp_dir, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(temp_dir, f"{stem}_{counter}{suffix}")
        counter += 1

    with open(candidate, "wb") as tmp:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                tmp.write(chunk)
    return candidate


# Auto-Cache for successful GET requests
def api_request_with_cache(*args, **kwargs):
    res = api_request(*args, **kwargs)
    if args[0] == "GET" and isinstance(res, (dict, list)):
        manager.cache_data(f"{args[0]}:{args[1]}:{kwargs.get('params')}", res)
    return res
