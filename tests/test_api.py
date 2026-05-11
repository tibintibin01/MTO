import pytest
import httpx
from datetime import datetime

# Configuration for testing
BASE_URL = "https://127.0.0.1:8001"


@pytest.mark.asyncio
async def test_health_check():
    """Verify the API is online and responding."""
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(f"{BASE_URL}/")
        assert response.status_code == 200
        assert "message" in response.json()


@pytest.mark.asyncio
async def test_invalid_login():
    """Verify the security bouncer rejects bad credentials."""
    async with httpx.AsyncClient(verify=False) as client:
        payload = {"username": "wrong_user", "password": "wrong_password"}
        response = await client.post(f"{BASE_URL}/token", data=payload)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_cors_headers():
    """Verify that CORS protection is active."""
    async with httpx.AsyncClient(verify=False) as client:
        # Simulate a request from a browser
        headers = {"Origin": "http://localhost"}
        response = await client.get(f"{BASE_URL}/", headers=headers)
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


@pytest.mark.asyncio
async def test_backup_status_access_denied():
    """Verify that sensitive info requires a token."""
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(f"{BASE_URL}/system/backup/status")
        assert response.status_code == 401  # Unauthorized
