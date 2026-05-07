import requests
import json

BASE_URL = "http://127.0.0.1:8001"
API_BASE_URL = BASE_URL # Alias for auth_service compatibility

_SESSION_TOKEN = None

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
        headers["Authorization"] = f"Bearer {_SESSION_TOKEN}"

    try:
        # If 'files' is provided, requests uses 'multipart/form-data'
        # If 'data' is provided, it uses 'application/json'
        response = requests.request(
            method, 
            url, 
            json=data if not files else None, # JSON ignored if uploading files
            data=data if files else None,     # Form data used if files present
            params=params, 
            files=files,
            headers=headers,
            timeout=120
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
