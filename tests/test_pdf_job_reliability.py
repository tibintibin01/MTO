import json
from contextlib import nullcontext
from pathlib import Path

from backend.models import Job
from backend.services import job_service


def test_soa_job_reaches_completed_with_one_valid_pdf(monkeypatch, tmp_path):
    output = tmp_path / "soa.pdf"
    output.write_bytes(b"%PDF-1.4\nphase4 reliability\n")
    updates = []
    job = Job(
        id="soa-success",
        job_type="pdf_soa",
        status="RUNNING",
        submitted_by="phase4-test",
        payload='{"property_id": 1}',
    )
    monkeypatch.setattr(job_service, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "backend.services.billing_service.get_property_statement_data",
        lambda _property_id, db_session=None: {"property_id": 1},
    )
    monkeypatch.setattr(
        "backend.generators.soa_gen.generate_statement_of_account",
        lambda _details, _base_dir: str(output),
    )
    monkeypatch.setattr(
        job_service,
        "_update_job",
        lambda job_id, **values: updates.append((job_id, values)),
    )

    job_service._handle_pdf(job, {"property_id": 1})

    terminal_updates = [values for _job_id, values in updates if "status" in values]
    assert len(terminal_updates) == 1
    terminal = terminal_updates[0]
    assert terminal["status"] == "COMPLETED"
    assert terminal["progress"] == 100
    assert terminal["completed_at"] is not None
    assert json.loads(terminal["result"])["file_path"] == str(output)
    assert Path(output).read_bytes().startswith(b"%PDF-")


def test_missing_property_raises_without_false_completion(monkeypatch):
    updates = []
    job = Job(
        id="soa-missing",
        job_type="pdf_soa",
        status="RUNNING",
        submitted_by="phase4-test",
        payload='{"property_id": 999}',
    )
    monkeypatch.setattr(job_service, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "backend.services.billing_service.get_property_statement_data",
        lambda _property_id, db_session=None: None,
    )
    monkeypatch.setattr(
        job_service,
        "_update_job",
        lambda job_id, **values: updates.append((job_id, values)),
    )

    try:
        job_service._handle_pdf(job, {"property_id": 999})
    except Exception as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("Missing property must fail PDF generation")

    assert not any(values.get("status") == "COMPLETED" for _job_id, values in updates)

