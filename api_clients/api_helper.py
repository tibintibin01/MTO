import json
import requests
from api_clients.offline_manager import manager
import threading

CONNECTION_STATUS = "ONLINE" # ONLINE, OFFLINE, SYNCING

BASE_URL = "https://127.0.0.1:8001"
API_BASE_URL = BASE_URL  # Alias for auth_service compatibility

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

    try:
        # If 'files' is provided, requests uses 'multipart/form-data'
        # If 'data' is provided, it uses 'application/json'
        # verify=False is used because we are using a self-signed certificate for local dev
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        response = requests.request(
            method,
            url,
            json=data if not files else None,  # JSON ignored if uploading files
            data=data if files else None,  # Form data used if files present
            params=params,
            files=files,
            headers=headers,
            timeout=120,
            verify=False,
        )

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
