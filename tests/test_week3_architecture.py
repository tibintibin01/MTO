# -*- coding: utf-8 -*-
import pytest
import os
import json
import uuid
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import TaxPolicy, Job, Property, PropertyBilling, PaymentBilling
from backend.services.billing_service import sync_property_billing, get_property_billing_history, get_total_due
from backend.services.import_service import save_import_cache, load_import_cache, prune_old_import_cache
from backend.services.job_service import submit_job, _job_submitted_event, _try_claim_job

@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    @event.listens_for(eng, "connect")
    def enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()

@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()

def test_tax_policy_custom_rates_and_fallbacks(db):
    """Test that billing calculations fetch custom rates from TaxPolicy and fallback correctly."""
    # Insert a property to satisfy the FK constraint
    prop = Property(
        id=1,
        td_number="TD-TEST-WEEK3",
        owner_name="JUAN DELA CRUZ",
        assessed_value=100000.00,
        penalty=0.0,
        discount=0.0
    )
    db.add(prop)
    db.commit()

    # 1. Test fallback behavior (no TaxPolicy configured)
    res_fallback = sync_property_billing(
        cur=None,
        property_id=prop.id,
        tax_year=2026,
        assessed_value=100000.00,
        penalty=50.00,
        discount=10.00,
        db_session=db
    )
    # Expected with 1% basic, 1% sef = 2% total. 2000.00 + 50.00 - 10.00 = 2040.00
    assert res_fallback["basic_amount"] == 1000.00
    assert res_fallback["sef_amount"] == 1000.00
    assert res_fallback["total_amount"] == 2040.00

    # 2. Configure a custom TaxPolicy
    custom_policy = TaxPolicy(
        tax_year=2026,
        basic_rate=Decimal("0.0150"), # 1.5%
        sef_rate=Decimal("0.0050"),   # 0.5%
        penalty_rate=Decimal("0.0200") # 2%
    )
    db.add(custom_policy)
    db.commit()

    res_custom = sync_property_billing(
        cur=None,
        property_id=prop.id,
        tax_year=2026,
        assessed_value=100000.00,
        penalty=50.00,
        discount=10.00,
        db_session=db
    )
    # Expected: 1.5% of 100,000 = 1500.00 basic. 0.5% of 100,000 = 500.00 sef. Total = 2000 + 50 - 10 = 2040.
    assert res_custom["basic_amount"] == 1500.00
    assert res_custom["sef_amount"] == 500.00
    assert res_custom["total_amount"] == 2040.00


def test_import_caching_utilities():
    """Test save_import_cache, load_import_cache, and prune_old_import_cache utilities."""
    sample_data = [{"td_number": "TD-TEST-1", "owner_name": "Alice"}, {"td_number": "TD-TEST-2", "owner_name": "Bob"}]
    
    # 1. Save data to cache
    token = save_import_cache(sample_data)
    assert token is not None
    assert len(token) > 0
    
    # 2. Check if cache file exists
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "import_cache")
    file_path = os.path.join(cache_dir, f"import_{token}.json")
    assert os.path.exists(file_path)
    
    # 3. Load from cache (should delete immediately after load)
    loaded_data = load_import_cache(token)
    assert loaded_data == sample_data
    assert not os.path.exists(file_path)
    
    # 4. Pruning test
    token2 = save_import_cache(sample_data)
    file_path2 = os.path.join(cache_dir, f"import_{token2}.json")
    assert os.path.exists(file_path2)
    # Force older timestamp
    old_time = time.time() - 4000 # older than 1 hour
    os.utime(file_path2, (old_time, old_time))
    prune_old_import_cache(max_age_seconds=3600)
    assert not os.path.exists(file_path2)


def test_job_worker_wake_signal(db):
    """Test that submit_job sets the job submitted threading.Event wake signal."""
    # Ensure event is cleared
    _job_submitted_event.clear()
    assert not _job_submitted_event.is_set()
    
    # Submit job
    submit_job(
        job_type="backup",
        submitted_by="test_user",
        payload={"dummy": "value"},
        db_session=db
    )
    
    # Verify the event got set immediately
    assert _job_submitted_event.is_set()
