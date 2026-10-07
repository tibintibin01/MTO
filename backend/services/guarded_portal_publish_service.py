"""One guarded publisher for the desktop job and the owned daily SYSTEM task.

Reuse the installed, hash-pinned R4 transport instead of adding a second upload
implementation. A new application release requires explicit source approval;
neither an HTTP request nor a job payload can supply code, paths or credentials.
"""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from mto_version import PRODUCT_VERSION

ROOT = Path(r"C:\ProgramData\MTO\portal-publication")
HELPER = Path(
    r"C:\ProgramData\MTO\release-tools\portal-publication-20261007-r4\publish_portal_snapshot.py"
)
HELPER_SHA256 = "A9626C2731BC5502A71EB680441F0A7A5A66E245344BE5179997061658FC5FCA"
PROJECT = Path(__file__).resolve().parents[2]
BRIDGE_REVISION = "app-guarded-publish-v1"


class GuardedPublicationBlocked(Exception):
    """Fixed reason codes only; never log network exceptions/capabilities."""


def _require(condition, reason):
    if not condition:
        raise GuardedPublicationBlocked(reason)


def _no_links(path):
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            _require(
                not item.is_symlink()
                and not getattr(item.lstat(), "st_file_attributes", 0) & 0x400,
                "LINKED_PUBLICATION_PATH",
            )


def _namespace():
    _no_links(HELPER)
    source = HELPER.read_bytes()
    _require(
        hashlib.sha256(source).hexdigest().upper() == HELPER_SHA256,
        "GUARDED_PUBLISHER_IDENTITY_MISMATCH",
    )

    class VerifiedLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            # Compile exactly the buffer whose hash was checked, never re-read
            # the path or accept cached bytecode between check and import.
            return self.source_to_code(source, str(HELPER))

    loader = VerifiedLoader("installed_guarded_publisher", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.__dict__


def _protected_roots():
    _require(os.name == "nt", "GUARDED_PUBLISHER_REQUIRES_WINDOWS_SERVER")
    # Read ACLs only. Do not repair or broaden permissions at request time.
    command = r"""$ErrorActionPreference='Stop';foreach($p in @('C:\ProgramData\MTO\portal-publication','C:\ProgramData\MTO\release-tools\portal-publication-20261007-r4')){$a=Get-Acl -LiteralPath $p;if(-not $a.AreAccessRulesProtected){exit 2};foreach($r in $a.Access){$s=$r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value;if($r.AccessControlType -eq 'Allow' -and $s -notin @('S-1-5-18','S-1-5-32-544')){exit 2}}}"""
    executable = (
        Path(os.environ["SystemRoot"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    result = subprocess.run(
        [str(executable), "-NoProfile", "-Command", command],
        capture_output=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _require(result.returncode == 0, "PUBLICATION_ROOT_PERMISSIONS_REVIEW_REQUIRED")


def _approved_namespace(loader=_namespace):
    _protected_roots()
    h = loader()
    _require(
        Path(h["ROOT"]) == ROOT and Path(h["APP"]).resolve() == PROJECT.resolve(),
        "UNAPPROVED_PUBLICATION_ROOT",
    )
    _no_links(ROOT)
    state = h["read_json"](ROOT / "publisher-state.json")
    _require(
        h["read_json"](ROOT / "owner.json").get("owner") == h["OWNER"]
        and state.get("owner") == h["OWNER"],
        "PUBLICATION_ROOT_NOT_OWNED",
    )
    approved = state.get("approved_source_commit")
    _require(
        isinstance(approved, str)
        and re.fullmatch(r"[a-f0-9]{40}", approved)
        and state.get("approved_product_version") == PRODUCT_VERSION
        and state.get("approved_bridge_revision") == BRIDGE_REVISION,
        "APP_PUBLISHER_RELEASE_APPROVAL_REQUIRED",
    )
    result = subprocess.run(
        [
            "git",
            "-C",
            str(PROJECT),
            "rev-parse",
            f"refs/tags/v{PRODUCT_VERSION}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _require(
        result.returncode == 0 and result.stdout.strip() == approved,
        "APP_RELEASE_TAG_IDENTITY_MISMATCH",
    )
    # The installed R4 file stays immutable. Only its in-memory expected source
    # identity is bound to the explicitly approved release. Original clean-tree,
    # master/origin/root checks, locking, masking, CAS and byte readback remain.
    h["EXPECTED_COMMIT"] = approved
    return h


def execute_guarded_publication(mode="operator"):
    """Child-process entry only: isolate R4 cwd/env/output changes from API."""
    _require(mode in {"operator", "scheduled", "verify"}, "UNAPPROVED_PUBLICATION_MODE")
    try:
        # Keep import/config output out of API logs and job results. R4 returns
        # only fixed codes and allowlisted publication metadata.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            h = _approved_namespace()
            with h["publication_lock"](ROOT):
                result = h["publish"](mode)
        result["bridge_revision"] = BRIDGE_REVISION
        result["product_version"] = PRODUCT_VERSION
        return result
    except GuardedPublicationBlocked as error:
        return {"status": "BLOCKED", "reason_code": str(error), "uploaded": False}
    except Exception as error:
        # Preserve known installed-helper fixed codes, not arbitrary messages.
        if type(error).__name__ == "Blocked" and re.fullmatch(
            r"[A-Z0-9_]{1,100}", str(error)
        ):
            code = str(error)
        else:
            code = "GUARDED_PUBLICATION_UNAVAILABLE"
        return {
            "status": "BLOCKED",
            "reason_code": code,
            "uploaded": False,
            "error_type": type(error).__name__,
        }


def run_guarded_publication(mode="operator"):
    _require(mode in {"operator", "scheduled", "verify"}, "UNAPPROVED_PUBLICATION_MODE")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "scripts.publish_guarded_portal",
                "--mode",
                mode,
            ],
            cwd=PROJECT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=570,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _require(
            len(result.stdout.encode("utf-8")) <= 32768, "PUBLICATION_RECEIPT_TOO_LARGE"
        )
        receipt = json.loads(result.stdout)
        _require(
            isinstance(receipt, dict)
            and receipt.get("status") in {"VERIFIED", "BLOCKED"},
            "PUBLICATION_RECEIPT_INVALID",
        )
        _require(
            (result.returncode == 0) == (receipt.get("status") == "VERIFIED"),
            "PUBLICATION_EXIT_RECEIPT_MISMATCH",
        )
        return receipt
    except Exception:
        # A timeout may have interrupted a commit: preserve pending evidence,
        # never queue another upload or claim it failed before reaching storage.
        return {
            "status": "BLOCKED",
            "reason_code": "PUBLICATION_CHILD_RECHECK_REQUIRED",
            "uploaded": False,
        }
