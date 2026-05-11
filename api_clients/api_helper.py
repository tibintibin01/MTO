import requests
import json

BASE_URL = "https://127.0.0.1:8001"
API_BASE_URL = BASE_URL # Alias for auth_service compatibility

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
        parts = token.split('.')
        if len(parts) != 3:
            return True
            
        payload_b64 = parts[1]
        # Add padding
        missing_padding = len(payload_b64) % 4
        if missing_padding:
            payload_b64 += '=' * (4 - missing_padding)
            
        payload_json = base64.b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        
        exp = payload.get('exp')
        if not exp:
            return False
            
        return time.time() > exp
    except Exception:
        return True # Default to expired if malformed

def set_token(token):
    """Sets the global bearer token for all subsequent API requests."""
    global _SESSION_TOKEN
    _SESSION_TOKEN = token

def api_request(method, endpoint, data=None, params=None, files=None, raw_response=False):
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
            json=data if not files else None, # JSON ignored if uploading files
            data=data if files else None,     # Form data used if files present
            params=params, 
            files=files,
            headers=headers,
            timeout=120,
            verify=False
        )
        
        if raw_response:
            return response

        response.raise_for_status()
        
        if response.content:
            return response.json()
        return True
    except requests.exceptions.RequestException as e:
        # Provide a more descriptive error message
        status_code = getattr(e.response, 'status_code', 'N/A')
        error_msg = f"API Communication Error (Status {status_code}): {str(e)}"
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
