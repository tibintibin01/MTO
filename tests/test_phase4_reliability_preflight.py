import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.models import Job
from scripts import phase4_reliability_preflight as preflight


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase4-jobs.sqlite'}")
    Job.__table__.create(engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _job(identifier, *, status="PENDING", job_type="pdf_soa", now=None, **kwargs):
    captured_at = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    defaults = {
        "id": identifier,
        "job_type": job_type,
        "status": status,
        "submitted_by": "phase4-test",
        "payload": '{"secret":"must-not-appear"}',
        "progress": 0,
        "created_at": captured_at,
    }
    defaults.update(kwargs)
    return Job(**defaults)


def _pass_component(**extra):
    return {"status": "PASS", "findings": [], **extra}


def test_empty_valid_queue_passes_privacy_safely(tmp_path):
    engine, factory = _session_factory(tmp_path)
    try:
        report = preflight.capture_job_queue(session_factory=factory)
    finally:
        engine.dispose()

    rendered = json.dumps(report)
    assert report["status"] == "PASS"
    assert report["schema"] == {
        "table_present": True,
        "missing_column_count": 0,
        "missing_index_count": 0,
    }
    assert report["expected_workers"] == {"fast": 3, "slow": 1}
    assert "payload" not in rendered
    assert "submitted_by" not in rendered
    assert "must-not-appear" not in rendered


def test_stale_pending_and_running_jobs_fail(tmp_path):
    engine, factory = _session_factory(tmp_path)
    now = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)
    old = now.replace(tzinfo=None) - timedelta(minutes=11)
    with factory() as session:
        session.add(_job("pending-old", now=now, created_at=old))
        session.add(
            _job(
                "running-old",
                now=now,
                status="RUNNING",
                created_at=old,
                started_at=old,
                progress=5,
            )
        )
        session.commit()
    try:
        report = preflight.capture_job_queue(
            session_factory=factory,
            now=now,
            stale_minutes=10,
        )
    finally:
        engine.dispose()

    assert report["status"] == "FAIL"
    assert report["counts"]["stale_pending"] == 1
    assert report["counts"]["stale_running"] == 1
    assert {item["code"] for item in report["findings"]} >= {
        "STALE_PENDING_JOBS",
        "STALE_RUNNING_JOBS",
    }


def test_recent_failure_requires_review_without_exposing_error(tmp_path):
    engine, factory = _session_factory(tmp_path)
    now = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)
    with factory() as session:
        session.add(
            _job(
                "failed-job",
                now=now,
                status="FAILED",
                completed_at=now.replace(tzinfo=None),
                error="MTO_DB_PASSWORD=never-report-this",
            )
        )
        session.commit()
    try:
        report = preflight.capture_job_queue(session_factory=factory, now=now)
    finally:
        engine.dispose()

    rendered = json.dumps(report)
    assert report["status"] == "REVIEW"
    assert report["counts"]["recent_failures_by_type"] == {"pdf_soa": 1}
    assert "MTO_DB_PASSWORD" not in rendered
    assert "never-report-this" not in rendered
    assert "failed-job" not in rendered


def test_invalid_status_and_type_fail(tmp_path):
    engine, factory = _session_factory(tmp_path)
    now = datetime(2026, 9, 16, 1, 0)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs "
                "(id, job_type, status, submitted_by, payload, progress, created_at) "
                "VALUES (:id, :job_type, :status, :submitted_by, :payload, :progress, :created_at)"
            ),
            {
                "id": "invalid-job",
                "job_type": "shell_command",
                "status": "UNKNOWN",
                "submitted_by": "phase4-test",
                "payload": "{}",
                "progress": 0,
                "created_at": now,
            },
        )
    try:
        report = preflight.capture_job_queue(
            session_factory=factory,
            now=now.replace(tzinfo=timezone.utc),
        )
    finally:
        engine.dispose()

    assert report["status"] == "FAIL"
    assert report["counts"]["invalid_status"] == 1
    assert report["counts"]["invalid_type"] == 1


def test_inconsistent_terminal_state_fails(tmp_path):
    engine, factory = _session_factory(tmp_path)
    with factory() as session:
        session.add(
            _job(
                "bad-completed",
                status="COMPLETED",
                progress=90,
                result=None,
                completed_at=None,
            )
        )
        session.commit()
    try:
        report = preflight.capture_job_queue(session_factory=factory)
    finally:
        engine.dispose()

    assert report["status"] == "FAIL"
    assert report["counts"]["inconsistent_state"] == 1
    assert report["findings"][0]["code"] == "JOB_STATE_INCONSISTENT"


def test_capture_reliability_aggregates_component_review(monkeypatch):
    monkeypatch.setattr(
        preflight.certification, "capture_source_control", lambda: _pass_component()
    )
    monkeypatch.setattr(
        preflight.certification, "capture_database_assurance", lambda: _pass_component()
    )
    monkeypatch.setattr(
        preflight.certification,
        "capture_api_latency",
        lambda _samples, _maximum: _pass_component(),
    )
    monkeypatch.setattr(
        preflight.certification, "capture_runtime_supervisor", lambda: _pass_component()
    )
    monkeypatch.setattr(
        preflight,
        "capture_job_queue",
        lambda **_kwargs: {
            "status": "REVIEW",
            "findings": [
                preflight._finding(
                    "job_queue",
                    "RECENT_JOB_FAILURE_REVIEW_REQUIRED",
                    "Recent failed jobs require documented operational review.",
                    "MEDIUM",
                )
            ],
        },
    )

    report = preflight.capture_reliability()

    assert report["status"] == "REVIEW"
    assert report["finding_count"] == 1


def test_main_writes_atomic_report_and_returns_review(monkeypatch, tmp_path):
    report = {
        "status": "REVIEW",
        "components": {"job_queue": {"status": "REVIEW"}},
        "findings": [],
    }
    monkeypatch.setattr(preflight, "capture_reliability", lambda **_kwargs: report)
    destination = tmp_path / "phase4-report.json"

    result = preflight.main(["--require-ready", "--output", str(destination)])

    assert result == 4
    assert json.loads(destination.read_text(encoding="utf-8"))["require_ready"] is True
    assert not list(tmp_path.glob("*.tmp"))
