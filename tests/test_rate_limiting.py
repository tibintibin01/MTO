# -*- coding: utf-8 -*-
import pytest
import os
import sys
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.database import Base
from backend.models import RateLimitBlock
import backend.services.rate_limit_service as rate_limit_svc
from slowapi import Limiter
from slowapi.util import get_remote_address

@pytest.fixture()
def db():
    """Isolated in-memory SQLite database for service unit testing."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    
    @event.listens_for(eng, "connect")
    def enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
    eng.dispose()

def test_log_rate_limit_block(db):
    """Test that rate limit blocks are correctly logged to the database."""
    block = rate_limit_svc.log_rate_limit_block(
        db_session=db,
        ip_address="192.168.1.50",
        username="testuser",
        endpoint="/api/test",
        limit_rule="5 per 1 minute",
        retry_after=60
    )
    
    assert block is not None
    assert block.id is not None
    assert block.ip_address == "192.168.1.50"
    assert block.username == "testuser"
    assert block.endpoint == "/api/test"
    assert block.limit_rule == "5 per 1 minute"
    assert block.retry_after == 60

def test_get_rate_limit_stats(db):
    """Test the compilation of rate limit statistics and metrics."""
    # Log multiple blocks
    rate_limit_svc.log_rate_limit_block(db, "192.168.1.50", "userA", "/api/route1", "5/min", 10)
    rate_limit_svc.log_rate_limit_block(db, "192.168.1.50", "userA", "/api/route2", "5/min", 10)
    rate_limit_svc.log_rate_limit_block(db, "192.168.1.51", "userB", "/api/route1", "10/min", 15)
    rate_limit_svc.log_rate_limit_block(db, "192.168.1.52", None, "/api/route1", "10/min", 15)

    stats = rate_limit_svc.get_rate_limit_stats(db)
    
    assert stats["total_blocks"] == 4
    assert stats["blocks_today"] == 4
    
    # Top blocked IP should be 192.168.1.50 with count 2
    assert stats["top_blocked_ips"][0]["ip_address"] == "192.168.1.50"
    assert stats["top_blocked_ips"][0]["count"] == 2
    
    # Top blocked user should be userA with count 2
    assert stats["top_blocked_users"][0]["username"] == "userA"
    assert stats["top_blocked_users"][0]["count"] == 2
    
    # Top blocked endpoint should be /api/route1 with count 3
    assert stats["blocks_by_endpoint"][0]["endpoint"] == "/api/route1"
    assert stats["blocks_by_endpoint"][0]["count"] == 3

def test_get_rate_limit_blocks_pagination(db):
    """Test retrieving rate limit logs with pagination cursor."""
    for i in range(15):
        rate_limit_svc.log_rate_limit_block(db, f"192.168.1.{i}", f"user{i}", "/api/test", "5/min", 5)
        
    blocks, next_cursor = rate_limit_svc.get_rate_limit_blocks(db, limit=10)
    assert len(blocks) == 10
    assert next_cursor is not None
    
    # The list is in descending order, so the first block in list should be the last one inserted (id 15)
    assert blocks[0]["username"] == "user14"
    
    # Fetch next page using the cursor
    blocks_page2, next_cursor2 = rate_limit_svc.get_rate_limit_blocks(db, limit=10, cursor=next_cursor)
    assert len(blocks_page2) == 5
    assert next_cursor2 is None
    assert blocks_page2[0]["username"] == "user4"

def test_reset_client_rate_limits_memory():
    """Test resetting client rate limits in in-memory storage."""
    from backend.deps import limiter, user_limiter
    
    # Create request keys in limiter & user_limiter storage
    # We clear them first to ensure clean state
    limiter._storage.storage.clear()
    user_limiter._storage.storage.clear()
    
    # Set keys manually in storage dict
    limiter._storage.storage["LIMITER/192.168.1.200//api/test/10/1/minute"] = (10, datetime.now() + timedelta(minutes=1))
    limiter._storage.storage["LIMITER/192.168.1.200//api/other/5/1/minute"] = (5, datetime.now() + timedelta(minutes=1))
    limiter._storage.storage["LIMITER/192.168.1.201//api/test/10/1/minute"] = (1, datetime.now() + timedelta(minutes=1))
    
    user_limiter._storage.storage["LIMITER/user:testuser//api/test/10/1/minute"] = (10, datetime.now() + timedelta(minutes=1))
    user_limiter._storage.storage["LIMITER/ip:192.168.1.200//api/test/10/1/minute"] = (2, datetime.now() + timedelta(minutes=1))

    # Reset IP 192.168.1.200
    cleared_ip = rate_limit_svc.reset_client_rate_limits("192.168.1.200")
    # Should clear 2 keys in limiter and 1 fallback key in user_limiter = 3 keys
    assert cleared_ip == 3
    
    # Check that 192.168.1.200 keys are gone but others remain
    limiter_keys = list(limiter._storage.storage.keys())
    user_limiter_keys = list(user_limiter._storage.storage.keys())
    
    assert "LIMITER/192.168.1.200//api/test/10/1/minute" not in limiter_keys
    assert "LIMITER/192.168.1.200//api/other/5/1/minute" not in limiter_keys
    assert "LIMITER/192.168.1.201//api/test/10/1/minute" in limiter_keys
    
    assert "LIMITER/ip:192.168.1.200//api/test/10/1/minute" not in user_limiter_keys
    assert "LIMITER/user:testuser//api/test/10/1/minute" in user_limiter_keys

    # Reset user testuser
    cleared_user = rate_limit_svc.reset_client_rate_limits("testuser")
    assert cleared_user == 1
    assert "LIMITER/user:testuser//api/test/10/1/minute" not in list(user_limiter._storage.storage.keys())

def test_stacked_limiters_monkey_patch():
    """
    Test that our monkey patch on slowapi.Limiter allows multiple stacked rate
    limiters to execute successfully on the same endpoint.
    """
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from slowapi.errors import RateLimitExceeded
    from backend.exception_handlers import rate_limit_handler
    
    # Create independent limiters for this test
    # Apply the patch if not already applied (it is applied in deps, but we can verify here)
    lim1 = Limiter(key_func=get_remote_address)
    lim2 = Limiter(key_func=lambda request: "custom-user")
    
    # Ensure they are using separate memory storages
    lim1._storage.storage.clear()
    lim2._storage.storage.clear()
    
    app_test = FastAPI()
    app_test.state.limiter = lim1
    app_test.state.user_limiter = lim2
    app_test.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    
    @app_test.get("/test-limit")
    @lim1.limit("2/minute")
    @lim2.limit("2/minute")
    def route(request: Request):
        return {"status": "ok"}
        
    client = TestClient(app_test)
    
    # Call 1st time
    r1 = client.get("/test-limit")
    assert r1.status_code == 200
    
    # Call 2nd time
    r2 = client.get("/test-limit")
    assert r2.status_code == 200
    
    # Both limiters should have 2 hits each
    assert len(lim1._storage.storage) > 0
    assert len(lim2._storage.storage) > 0
    
    # Call 3rd time - should trigger rate limiting (429)
    r3 = client.get("/test-limit")
    assert r3.status_code == 429
    assert r3.json()["code"] == "RATE_LIMITED"
