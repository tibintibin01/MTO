from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Job
from backend.services import job_service


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture()
def job_database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'job-reliability.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Job.__table__.create(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(job_service, "SessionLocal", factory)
    monkeypatch.setattr(job_service, "_cleanup_expired_idempotency_keys", lambda: None)
    monkeypatch.setattr(job_service, "_cleanup_expired_refresh_tokens", lambda: None)
    monkeypatch.setattr(
        "backend.services.import_service.prune_old_import_cache", lambda: None
    )
    yield factory
    engine.dispose()


def _insert_job(factory, identifier, *, status, started_at=None):
    with factory() as session:
        session.add(
            Job(
                id=identifier,
                job_type="pdf_soa",
                status=status,
                submitted_by="phase4-test",
                payload="{}",
                progress=5 if status == "RUNNING" else 0,
                created_at=_utcnow() - timedelta(minutes=20),
                started_at=started_at,
            )
        )
        session.commit()


def test_stale_unowned_running_job_is_returned_to_pending(job_database):
    started_at = _utcnow() - timedelta(
        minutes=job_service.STALE_THRESHOLD_MINUTES + 1
    )
    _insert_job(job_database, "stale-unowned", status="RUNNING", started_at=started_at)

    job_service._recover_stale_jobs()

    with job_database() as session:
        job = session.get(Job, "stale-unowned")
        assert job.status == "PENDING"
        assert job.started_at is None
        assert job.progress == 0
        assert job.progress_message == "Reset after stale timeout"


def test_active_long_running_job_must_not_be_requeued(job_database, monkeypatch):
    """Regression gate: maintenance must not duplicate work still owned by a worker."""
    identifier = "active-long-running-job"
    started_at = _utcnow() - timedelta(
        minutes=job_service.STALE_THRESHOLD_MINUTES + 1
    )
    _insert_job(job_database, identifier, status="RUNNING", started_at=started_at)
    active_thread = MagicMock()
    active_thread.is_alive.return_value = True
    monkeypatch.setattr(
        job_service,
        "_worker_heartbeats",
        {
            "slow-0-active": {
                "last_beat": datetime.now(),
                "pool": "slow",
                "status": "running",
                "current_job": identifier,
            }
        },
    )
    monkeypatch.setattr(
        job_service, "_worker_threads", {"slow-0-active": active_thread}
    )

    job_service._recover_stale_jobs()

    with job_database() as session:
        job = session.get(Job, identifier)
        assert job.status == "RUNNING"
        assert job.started_at == started_at


def test_live_worker_protection_uses_exact_job_id(job_database, monkeypatch):
    """An active job must not protect an abandoned job with the same prefix."""
    active_id = "12345678-active"
    abandoned_id = "12345678-abandoned"
    started_at = _utcnow() - timedelta(
        minutes=job_service.STALE_THRESHOLD_MINUTES + 1
    )
    _insert_job(job_database, active_id, status="RUNNING", started_at=started_at)
    _insert_job(job_database, abandoned_id, status="RUNNING", started_at=started_at)
    active_thread = MagicMock()
    active_thread.is_alive.return_value = True
    monkeypatch.setattr(
        job_service,
        "_worker_heartbeats",
        {
            "fast-0-active": {
                "last_beat": datetime.now(),
                "pool": "fast",
                "status": "running",
                "current_job": active_id,
            }
        },
    )
    monkeypatch.setattr(
        job_service, "_worker_threads", {"fast-0-active": active_thread}
    )

    job_service._recover_stale_jobs()

    with job_database() as session:
        assert session.get(Job, active_id).status == "RUNNING"
        assert session.get(Job, abandoned_id).status == "PENDING"


def test_dead_worker_job_is_recovered(job_database, monkeypatch):
    identifier = "dead-worker-job"
    started_at = _utcnow() - timedelta(
        minutes=job_service.STALE_THRESHOLD_MINUTES + 1
    )
    _insert_job(job_database, identifier, status="RUNNING", started_at=started_at)
    dead_thread = MagicMock()
    dead_thread.is_alive.return_value = False
    monkeypatch.setattr(
        job_service,
        "_worker_heartbeats",
        {
            "fast-0-dead": {
                "last_beat": datetime.now(),
                "pool": "fast",
                "status": "running",
                "current_job": identifier,
            }
        },
    )
    monkeypatch.setattr(
        job_service, "_worker_threads", {"fast-0-dead": dead_thread}
    )

    job_service._recover_stale_jobs()

    with job_database() as session:
        assert session.get(Job, identifier).status == "PENDING"


def test_live_long_job_is_protected_even_when_heartbeat_is_old(
    job_database, monkeypatch
):
    identifier = "live-old-heartbeat-job"
    started_at = _utcnow() - timedelta(
        minutes=job_service.STALE_THRESHOLD_MINUTES + 1
    )
    _insert_job(job_database, identifier, status="RUNNING", started_at=started_at)
    active_thread = MagicMock()
    active_thread.is_alive.return_value = True
    monkeypatch.setattr(
        job_service,
        "_worker_heartbeats",
        {
            "slow-0-active": {
                "last_beat": datetime.now()
                - timedelta(
                    seconds=job_service.HEARTBEAT_DEAD_THRESHOLD_SECONDS + 1
                ),
                "pool": "slow",
                "status": "running",
                "current_job": identifier,
            }
        },
    )
    monkeypatch.setattr(
        job_service, "_worker_threads", {"slow-0-active": active_thread}
    )

    job_service._recover_stale_jobs()

    with job_database() as session:
        assert session.get(Job, identifier).status == "RUNNING"


def test_worker_health_classifies_healthy_stale_and_dead(monkeypatch):
    now = datetime.now()
    healthy_thread = MagicMock()
    healthy_thread.is_alive.return_value = True
    stale_thread = MagicMock()
    stale_thread.is_alive.return_value = True
    dead_thread = MagicMock()
    dead_thread.is_alive.return_value = False
    monkeypatch.setattr(
        job_service,
        "_worker_heartbeats",
        {
            "fast-0": {
                "last_beat": now,
                "pool": "fast",
                "status": "idle",
                "current_job": None,
            },
            "slow-0": {
                "last_beat": now
                - timedelta(seconds=job_service.HEARTBEAT_STALE_THRESHOLD_SECONDS + 1),
                "pool": "slow",
                "status": "running",
                "current_job": "12345678",
            },
            "fast-1": {
                "last_beat": now,
                "pool": "fast",
                "status": "idle",
                "current_job": None,
            },
        },
    )
    monkeypatch.setattr(
        job_service,
        "_worker_threads",
        {
            "fast-0": healthy_thread,
            "slow-0": stale_thread,
            "fast-1": dead_thread,
        },
    )

    report = job_service.get_worker_health()

    states = {item["worker_id"]: item["state"] for item in report["workers"]}
    assert states == {"fast-0": "healthy", "fast-1": "dead", "slow-0": "stale"}
    assert report["overall"] == "dead"
    slow_worker = next(
        item for item in report["workers"] if item["worker_id"] == "slow-0"
    )
    assert slow_worker["current_job"] == "12345678"


def test_failed_handler_reaches_terminal_state(monkeypatch):
    updates = []
    job = Job(
        id="failure-terminal",
        job_type="pdf_soa",
        status="RUNNING",
        submitted_by="phase4-test",
        payload='{"property_id": 1}',
    )
    monkeypatch.setattr(
        job_service,
        "_update_job",
        lambda job_id, **values: updates.append((job_id, values)),
    )
    monkeypatch.setattr(
        job_service, "_handle_pdf", lambda _job, _payload: (_ for _ in ()).throw(RuntimeError("generation failed"))
    )

    job_service._run_job(job)

    terminal = updates[-1]
    assert terminal[0] == "failure-terminal"
    assert terminal[1]["status"] == "FAILED"
    assert terminal[1]["completed_at"] is not None
    assert terminal[1]["progress"] == 0
