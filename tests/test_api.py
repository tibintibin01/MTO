from fastapi.testclient import TestClient
from backend.main import app
import pytest

client = TestClient(app)

def test_health_check():
    """Verify the API is online and responding."""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()

def test_deep_healthz():
    """Verify the enterprise deep health probe is active and responsive."""
    response = client.get("/healthz")
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["status"] == "healthy"
    assert "database" in json_data
    assert "cache" in json_data
    assert "storage" in json_data
    assert "vault" in json_data


def test_invalid_login():
    """Verify the security bouncer rejects bad credentials."""
    payload = {"username": "wrong_user", "password": "wrong_password"}
    # Note: Use X-Requested-With for CSRF bypass in tests
    response = client.post("/token", data=payload, headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 401

def test_cors_headers():
    """Verify that CORS protection is active."""
    headers = {"Origin": "http://localhost", "X-Requested-With": "XMLHttpRequest"}
    response = client.get("/", headers=headers)
    assert response.status_code == 200
    # CORS headers are added by middleware, TestClient should see them
    assert "access-control-allow-origin" in response.headers

def test_backup_status_access_denied():
    """Verify that sensitive info requires a token."""
    response = client.get("/system/backup/status")
    assert response.status_code == 401  # Unauthorized
