import ast
from contextlib import nullcontext
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.services import guarded_portal_publish_service as bridge
from backend.services import job_service
from ui.portal_publish_feedback import publication_feedback


def verified():
    return {
        "status": "VERIFIED",
        "uploaded": True,
        "record_count": 2,
        "checksum": "a" * 64,
        "published_at": "2026-10-07T07:38:27+00:00",
        "verification": {
            "http_readiness": True,
            "publication_identity_matches": True,
            "checksum_readback_verified": True,
            "expanded_bytes_readback_verified": True,
        },
    }


@pytest.mark.parametrize(
    "key",
    [
        "http_readiness",
        "publication_identity_matches",
        "checksum_readback_verified",
        "expanded_bytes_readback_verified",
    ],
)
def test_unverified_acknowledgment_never_gets_success_icon(key):
    result = verified()
    result["verification"][key] = False
    assert publication_feedback(result)["outcome"] != "success"


def test_status_feedback_distinguishes_verified_blocked_and_legacy_ack():
    assert publication_feedback(verified())["outcome"] == "success"
    assert (
        publication_feedback({"status": "uploaded", "uploaded": True})["outcome"]
        == "warning"
    )
    assert (
        publication_feedback({"status": "BLOCKED", "reason_code": "EXAMPLE"})["outcome"]
        == "error"
    )


@pytest.mark.parametrize(
    "case", ["valid", "source", "version", "revision", "owner", "tag", "root"]
)
def test_only_operator_approved_tagged_release_can_use_r4_namespace(monkeypatch, case):
    state = {
        "owner": "OWNER",
        "approved_source_commit": "a" * 40,
        "approved_product_version": bridge.PRODUCT_VERSION,
        "approved_bridge_revision": bridge.BRIDGE_REVISION,
    }
    if case == "source":
        state["approved_source_commit"] = "NOT_A_COMMIT"
    if case == "version":
        state["approved_product_version"] = "0.0.0"
    if case == "revision":
        state["approved_bridge_revision"] = "FOREIGN"
    if case == "owner":
        state["owner"] = "FOREIGN"
    h = {
        "ROOT": bridge.ROOT,
        "APP": bridge.PROJECT if case != "root" else Path("FOREIGN"),
        "OWNER": "OWNER",
        "EXPECTED_COMMIT": "old",
        "read_json": lambda p: (
            state if p.name == "publisher-state.json" else {"owner": "OWNER"}
        ),
    }
    monkeypatch.setattr(bridge, "_protected_roots", lambda: None)
    monkeypatch.setattr(bridge, "_no_links", lambda _: None)
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout="b" * 40 if case == "tag" else "a" * 40
        ),
    )
    if case == "valid":
        result = bridge._approved_namespace(loader=lambda: h)
        assert result["EXPECTED_COMMIT"] == "a" * 40
    else:
        with pytest.raises(bridge.GuardedPublicationBlocked):
            bridge._approved_namespace(loader=lambda: h)
        assert h["EXPECTED_COMMIT"] == "old"


def test_api_publisher_runs_in_child_without_global_cwd_or_stream_redirection(
    monkeypatch,
):
    calls = []

    def run(args, **kw):
        calls.append((args, kw))
        return SimpleNamespace(
            returncode=0, stdout=json.dumps(verified()), stderr="PRIVATE_IMPORT_LOG"
        )

    monkeypatch.setattr(bridge.subprocess, "run", run)
    result = bridge.run_guarded_publication("operator")
    assert result["status"] == "VERIFIED"
    assert calls[0][0][-2:] == ["--mode", "operator"]
    assert calls[0][1]["cwd"] == bridge.PROJECT and calls[0][1]["timeout"] == 570
    assert "PRIVATE_IMPORT_LOG" not in json.dumps(result)


@pytest.mark.parametrize(
    "case", ["invalid_json", "nonzero_success", "zero_blocked", "timeout", "oversized"]
)
def test_child_ambiguity_stops_without_retry_or_raw_error(monkeypatch, case):
    calls = []

    def run(*_, **__):
        calls.append(1)
        if case == "timeout":
            raise RuntimeError("PRIVATE_AUTH_OR_URL")
        body = "PRIVATE" if case == "invalid_json" else json.dumps(verified())
        if case == "oversized":
            body = "x" * 32769
        if case == "zero_blocked":
            body = json.dumps({"status": "BLOCKED"})
        return SimpleNamespace(
            returncode=2 if case == "nonzero_success" else 0, stdout=body
        )

    monkeypatch.setattr(bridge.subprocess, "run", run)
    result = bridge.run_guarded_publication("operator")
    assert result["status"] == "BLOCKED" and len(calls) == 1
    assert "PRIVATE" not in json.dumps(result)


def test_child_executor_keeps_config_output_private(monkeypatch, capsys):
    def publish(mode):
        print("PRIVATE_CONFIGURATION")
        return verified()

    monkeypatch.setattr(
        bridge,
        "_approved_namespace",
        lambda: {"publication_lock": lambda _: nullcontext(), "publish": publish},
    )
    result = bridge.execute_guarded_publication("operator")
    assert (
        result["status"] == "VERIFIED"
        and result["bridge_revision"] == bridge.BRIDGE_REVISION
    )
    assert "PRIVATE_CONFIGURATION" not in capsys.readouterr().out


@pytest.mark.parametrize("ok", [True, False])
def test_portal_job_completion_requires_both_readback_proofs(monkeypatch, ok):
    result = verified()
    if not ok:
        result["verification"]["expanded_bytes_readback_verified"] = False
    updates = []
    monkeypatch.setattr(bridge, "run_guarded_publication", lambda _: result)
    monkeypatch.setattr(job_service, "_update_job", lambda id, **kw: updates.append(kw))
    job_service._handle_portal_publish(SimpleNamespace(id="SYNTHETIC"), {})
    assert updates[-1]["status"] == ("COMPLETED" if ok else "FAILED")


def test_legacy_non_preview_entry_never_saves_or_posts_directly(monkeypatch):
    from backend.services import portal_publish_service as legacy

    monkeypatch.setattr(
        bridge,
        "run_guarded_publication",
        lambda mode: {"status": "BLOCKED", "reason_code": "TEST", "mode": mode},
    )
    monkeypatch.setattr(
        legacy,
        "generate_portal_snapshot",
        lambda _: pytest.fail("Must not generate a legacy snapshot"),
    )
    assert legacy.publish_portal_snapshot(None)["mode"] == "operator"


def test_dialog_footer_is_reserved_before_message_and_failure_icon_is_not_ok():
    source = (Path(__file__).parents[1] / "ui/system_admin.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_show_portal_publish_result"
    )
    body = ast.get_source_segment(source, node)
    assert body.index('btn_fr.pack(side="bottom"') < body.index("body.pack(")
    assert (
        "ctk.CTkScrollableFrame" in body
        and '"OK" if outcome == "success" else "!"' in body
    )
    assert "height=290" not in body


def test_desktop_publication_is_never_offline_queued(monkeypatch):
    from api_clients import system_service as client

    calls = []
    monkeypatch.setattr(client, "api_request", lambda *a, **kw: calls.append((a, kw)))
    client.publish_portal_snapshot()
    assert calls[0][1]["queue_offline"] is False and calls[0][1]["timeout"] == 15
