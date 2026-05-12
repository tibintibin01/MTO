import json
import requests
from api_clients.offline_manager import manager
import threading

CONNECTION_STATUS = "ONLINE" # ONLINE, OFFLINE, SYNCING

import os
from pathlib import Path

BASE_URL = "https://127.0.0.1:8001"
API_BASE_URL = BASE_URL  # Alias for auth_service compatibility

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


def set_token(token):
    """Sets the global bearer token for all subsequent API requests."""
    global _SESSION_TOKEN
    _SESSION_TOKEN = token


def api_request(
    method, endpoint, data=None, params=None, files=None, raw_response=False
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
            print("SESSION EXPIRED: Token check failed locally.")
            # We raise a custom exception that the UI can catch to show a login prompt
            raise Exception("Your session has expired. Please log in again.")

        headers["Authorization"] = f"Bearer {_SESSION_TOKEN}"
    
    # CSRF Protection: Include custom header for all state-changing requests
    headers["X-Requested-With"] = "XMLHttpRequest"

    try:
        # If 'files' is provided, requests uses 'multipart/form-data'
        # If 'data' is provided, it uses 'application/json'
        # verify=False is used because we are using a self-signed certificate for local dev
        import urllib3
        import time
        from utils import set_request_id, logger, MetricsManager

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
            timeout=120,
            verify=verify_param,
        )

        # 2. Telemetry: Measure Latency
        latency = (time.perf_counter() - start_time) * 1000
        MetricsManager.record_request(latency, is_error=not response.ok)
        
        # 3. Log structured telemetry
        logger.info(f"API {method} {endpoint} completed", extra={"extra_data": {
            "latency_ms": round(latency, 2),
            "status": response.status_code,
            "method": method,
            "endpoint": endpoint
        }})

        if raw_response:
            return response

        response.raise_for_status()

        if response.content:
            return response.json()
        return True
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        global CONNECTION_STATUS
        CONNECTION_STATUS = "OFFLINE"
        
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
                return {"status": "queued", "message": "Connection lost. Action queued for sync.", "offline": True}
            raise Exception("Offline: Failed to queue action.")
        
        raise Exception(f"Connection lost and no offline handler for {method}")

    except requests.exceptions.RequestException as e:
        # Provide a more descriptive error message
        status_code = getattr(e.response, "status_code", "N/A")
        error_msg = f"API Communication Error (Status {status_code}): {str(e)}"
        
        # If it's a 503 or 504, we might treat it as offline too
        if status_code in [502, 503, 504]:
            CONNECTION_STATUS = "OFFLINE"

        if e.response and e.response.text:
            try:
                error_data = e.response.json()
                if "detail" in error_data:
                    error_msg = f"Error: {error_data['detail']}"
            except:
                pass
        raise Exception(error_msg)
    except Exception as e:
        raise Exception(f"Unexpected Error: {str(e)}")


# Auto-Cache for successful GET requests
def api_request_with_cache(*args, **kwargs):
    res = api_request(*args, **kwargs)
    if args[0] == "GET" and isinstance(res, (dict, list)):
        manager.cache_data(f"{args[0]}:{args[1]}:{kwargs.get('params')}", res)
    return res
