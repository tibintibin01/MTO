import sys
import os
import requests

# Add to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.auth_service import verify_user_login
from services.property_service import search_properties

def test_api_flow():
    print("Testing MTO API Connection...")
    # 1. Test login (use root/admin if you have it, or just check if it hits the API)
    # Since I don't know the password, I'll just check if it sends a request.
    try:
        user = verify_user_login("admin", "password")
        if user:
            print(f"Logged in as: {user['username']}")
            # 2. Test search
            results = search_properties("")
            print(f"Found {len(results)} properties.")
        else:
            print("Login failed (Invalid credentials or server down)")
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    test_api_flow()
