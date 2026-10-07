import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from scripts.portal_publication_check import collect, snapshot_metadata, PUBLISH_URL


@pytest.mark.parametrize("kind", ["missing", "fresh", "stale", "naive", "invalid"])
def test_diagnostic_reads_only_safe_snapshot_metadata(tmp_path, kind):
    path = tmp_path / "portal_snapshot_latest.json"
    now = datetime.now(timezone.utc)
    if kind != "missing":
        published = (now - timedelta(hours=50 if kind == "stale" else 1)).isoformat()
        if kind == "naive":
            published = now.replace(tzinfo=None).isoformat()
        data = {
            "schema_version": 2,
            "record_count": 1,
            "published_at": published,
            "properties": [{"owner_name": "PRIVATE TEST OWNER"}],
        }
        path.write_text(
            "invalid" if kind == "invalid" else json.dumps(data), encoding="utf-8"
        )
    before = path.read_bytes() if path.exists() else None
    result = snapshot_metadata(path, now)
    assert "PRIVATE TEST OWNER" not in json.dumps(result)
    assert result["readable"] is (kind in {"fresh", "stale"})
    if before is not None:
        assert path.read_bytes() == before


def test_diagnostic_never_discloses_config_secrets_or_changes_data(tmp_path):
    cfg = SimpleNamespace(
        PORTAL_PUBLISH_URL=PUBLISH_URL,
        PORTAL_PUBLISH_TOKEN="PRIVATE_PUBLISH_TOKEN" * 3,
        PORTAL_LOOKUP_SECRET="PRIVATE_LOOKUP_SECRET" * 3,
    )
    result = collect(
        cfg,
        tmp_path,
        health_reader=lambda: {"ok": False, "status": "stale"},
        task_reader=lambda: {"checked": True, "candidates": []},
    )
    assert result["status"] == "REVIEW_REQUIRED"
    assert "PRIVATE" not in json.dumps(result)
    assert result["database_queried"] is False and result["uploaded"] is False
    assert result["configuration_changed"] is False and result["tasks_changed"] is False
    assert list(tmp_path.iterdir()) == []


def test_diagnostic_requires_official_endpoint_and_verified_schedule(tmp_path):
    cfg = SimpleNamespace(
        PORTAL_PUBLISH_URL="https://example.invalid/",
        PORTAL_PUBLISH_TOKEN="a" * 48,
        PORTAL_LOOKUP_SECRET="b" * 48,
    )
    result = collect(
        cfg,
        tmp_path,
        health_reader=lambda: {"ok": True},
        task_reader=lambda: {
            "checked": True,
            "candidates": [{"approved_publish_runner": True, "state": "Ready"}],
        },
    )
    assert "PUBLISH_URL_IS_OFFICIAL" in result["issues"]
