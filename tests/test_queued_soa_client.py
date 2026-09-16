import asyncio

import pytest
from fastapi import HTTPException

from api_clients import billing_service as billing_client
from backend.routes import jobs as job_routes


def test_statement_pdf_uses_queue_polling_and_result_download(monkeypatch):
    requests = []
    downloads = []
    statuses = iter(
        [
            {"status": "PENDING"},
            {"status": "RUNNING"},
            {"status": "COMPLETED", "result": {"file_path": "server-only.pdf"}},
        ]
    )

    def fake_request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        if method == "POST":
            return {"job_id": "soa-job-1", "status": "queued"}
        return next(statuses)

    def fake_download(method, endpoint, **kwargs):
        downloads.append((method, endpoint, kwargs))
        return "C:/Temp/downloaded-soa.pdf"

    monkeypatch.setattr(billing_client, "api_request", fake_request)
    monkeypatch.setattr(billing_client, "api_download_file", fake_download)
    monkeypatch.setattr(billing_client.time, "sleep", lambda _seconds: None)

    result = billing_client.download_statement_pdf(
        41,
        timeout_seconds=15,
        poll_interval=0.01,
    )

    assert result == "C:/Temp/downloaded-soa.pdf"
    assert requests == [
        ("POST", "/jobs/pdf/soa/41", {"queue_offline": False}),
        ("GET", "/jobs/soa-job-1", {"queue_offline": False}),
        ("GET", "/jobs/soa-job-1", {"queue_offline": False}),
        ("GET", "/jobs/soa-job-1", {"queue_offline": False}),
    ]
    assert downloads == [
        (
            "GET",
            "/jobs/pdf/soa/soa-job-1/download",
            {"timeout": 15.0},
        )
    ]
    assert not any(
        "/properties/41/statement-pdf" in endpoint for _, endpoint, _ in requests
    )


def test_statement_pdf_rejects_failed_or_malformed_jobs(monkeypatch):
    monkeypatch.setattr(
        billing_client,
        "api_request",
        lambda *_args, **_kwargs: {"status": "queued"},
    )
    with pytest.raises(RuntimeError, match="job identifier"):
        billing_client.download_statement_pdf(7)

    responses = iter(
        [
            {"job_id": "failed-job", "status": "queued"},
            {"status": "FAILED", "error": "sensitive server path"},
        ]
    )
    monkeypatch.setattr(
        billing_client,
        "api_request",
        lambda *_args, **_kwargs: next(responses),
    )
    with pytest.raises(RuntimeError, match="failed on the server") as exc_info:
        billing_client.download_statement_pdf(7)
    assert "sensitive server path" not in str(exc_info.value)


def test_statement_pdf_polling_has_a_bounded_timeout(monkeypatch):
    responses = iter(
        [
            {"job_id": "slow-job", "status": "queued"},
            {"status": "RUNNING"},
        ]
    )
    times = iter([10.0, 10.2])
    monkeypatch.setattr(
        billing_client,
        "api_request",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(billing_client.time, "monotonic", lambda: next(times))

    with pytest.raises(TimeoutError, match="may still complete"):
        billing_client.download_statement_pdf(
            8,
            timeout_seconds=0.1,
            poll_interval=0.01,
        )


def _completed_job(pdf_path, *, submitted_by="kevin"):
    return {
        "id": "job-1",
        "job_type": "pdf_soa",
        "status": "COMPLETED",
        "submitted_by": submitted_by,
        "result": {"file_path": str(pdf_path)},
    }


def test_soa_job_download_is_owner_scoped_and_path_confined(monkeypatch, tmp_path):
    statements = tmp_path / "statements"
    statements.mkdir()
    pdf_path = statements / "soa.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    job = _completed_job(pdf_path)

    monkeypatch.setattr(job_routes, "_STATEMENTS_DIRECTORY", statements)
    monkeypatch.setattr(job_routes, "get_job", lambda *_args, **_kwargs: job)

    response = asyncio.run(
        job_routes.download_soa_pdf_job_result(
            "job-1",
            current_user={"username": "kevin", "role": "encoder"},
            db_session=object(),
        )
    )
    assert response.path == str(pdf_path.resolve())
    assert response.media_type == "application/pdf"
    assert response.headers["cache-control"] == "no-store"

    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            job_routes.download_soa_pdf_job_result(
                "job-1",
                current_user={"username": "other", "role": "encoder"},
                db_session=object(),
            )
        )
    assert denied.value.status_code == 403

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        job_routes,
        "get_job",
        lambda *_args, **_kwargs: _completed_job(outside),
    )
    with pytest.raises(HTTPException) as unsafe:
        asyncio.run(
            job_routes.download_soa_pdf_job_result(
                "job-1",
                current_user={"username": "kevin", "role": "encoder"},
                db_session=object(),
            )
        )
    assert unsafe.value.status_code == 410


def test_soa_job_download_requires_completed_soa(monkeypatch, tmp_path):
    statements = tmp_path / "statements"
    statements.mkdir()
    monkeypatch.setattr(job_routes, "_STATEMENTS_DIRECTORY", statements)

    running = _completed_job(statements / "missing.pdf")
    running["status"] = "RUNNING"
    monkeypatch.setattr(job_routes, "get_job", lambda *_args, **_kwargs: running)
    with pytest.raises(HTTPException) as incomplete:
        asyncio.run(
            job_routes.download_soa_pdf_job_result(
                "job-1",
                current_user={"username": "kevin", "role": "encoder"},
                db_session=object(),
            )
        )
    assert incomplete.value.status_code == 409

    wrong_type = _completed_job(statements / "missing.pdf")
    wrong_type["job_type"] = "backup"
    monkeypatch.setattr(job_routes, "get_job", lambda *_args, **_kwargs: wrong_type)
    with pytest.raises(HTTPException) as invalid_type:
        asyncio.run(
            job_routes.download_soa_pdf_job_result(
                "job-1",
                current_user={"username": "kevin", "role": "encoder"},
                db_session=object(),
            )
        )
    assert invalid_type.value.status_code == 400
