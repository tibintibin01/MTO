"""Read-only publisher diagnostics. No DB queries, uploads, secret changes or tasks."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

PORTAL = "https://mto-portal-dipaculao.vercel.app"
PUBLISH_URL = PORTAL + "/api/portal-snapshot/publish"


def snapshot_metadata(path: Path, now: datetime) -> dict:
    result = {"present": path.is_file(), "readable": False}
    if not result["present"]:
        return result
    try:
        for item in (path, *path.parents):
            if (
                item.is_symlink()
                or getattr(item.stat(), "st_file_attributes", 0) & 0x400
            ):
                return {**result, "reason": "LINKED_PATH"}
        if path.stat().st_size > 80 * 1024 * 1024:
            return {**result, "reason": "SNAPSHOT_TOO_LARGE"}
        data = json.loads(path.read_text(encoding="utf-8"))
        published = datetime.fromisoformat(
            str(data.get("published_at", "")).replace("Z", "+00:00")
        )
        if published.tzinfo is None:
            return {**result, "reason": "TIMESTAMP_WITHOUT_TIMEZONE"}
        count = data.get("record_count")
        version = data.get("owner_lookup_version", 1)
        if (
            type(count) is not int
            or count < 0
            or data.get("schema_version") != 2
            or type(version) is not int
            or version not in (1, 2)
        ):
            return {**result, "reason": "INVALID_METADATA"}
        return {
            **result,
            "readable": True,
            "published_at": published.astimezone(timezone.utc).isoformat(),
            "age_hours": round(
                (now - published.astimezone(timezone.utc)).total_seconds() / 3600, 1
            ),
            "record_count": count,
            "owner_lookup_version": version,
        }
    except (OSError, ValueError, TypeError):
        return {**result, "reason": "METADATA_UNAVAILABLE"}


def hosted_health() -> dict:
    try:
        try:
            response = urlopen(PORTAL + "/api/health", timeout=15)
        except HTTPError as error:
            response = error
        with response:
            body = response.read(16_385)
            if len(body) > 16_384:
                return {"checked": False, "reason": "RESPONSE_TOO_LARGE"}
            payload = json.loads(body)
            # Never copy arbitrary error bodies, URLs, credentials or records.
            if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
                return {"checked": False, "reason": "INVALID_HEALTH_RESPONSE"}
            status = payload.get("status")
            if status not in {
                "ready",
                "stale",
                "missing",
                "unavailable",
                "error",
                "invalid_timestamp",
            }:
                return {"checked": False, "reason": "INVALID_HEALTH_RESPONSE"}
            published = None
            try:
                stamp = datetime.fromisoformat(
                    str(payload.get("published_at", "")).replace("Z", "+00:00")
                )
                if stamp.tzinfo is not None:
                    published = stamp.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                pass
            numbers = {
                key: (
                    payload.get(key)
                    if type(payload.get(key)) in (int, float)
                    and math.isfinite(payload[key])
                    and payload[key] >= 0
                    else None
                )
                for key in ("age_hours", "max_age_hours", "record_count")
            }
            return {
                "checked": True,
                "http_status": response.code,
                "ok": payload["ok"],
                "status": status,
                "published_at": published,
                **numbers,
            }
    except (URLError, OSError, ValueError, TypeError):
        return {"checked": False, "reason": "HEALTH_UNAVAILABLE"}


def publisher_tasks() -> dict:
    if os.name != "nt":
        return {"checked": False, "reason": "NOT_WINDOWS", "candidates": []}
    # Inspect actions only to classify them; never return command lines that
    # could contain a token or invoke/change a scheduled task.
    query = r"""
$ErrorActionPreference='Stop'; $items=@();
foreach($task in @(Get-ScheduledTask)){
  $candidate=$task.TaskName -like '*MTO*Portal*'; $approved=$false;
  foreach($action in @($task.Actions)){
    if($action.Arguments -match '(?i)portal[_ -]?(snapshot|publish|publication)'){$candidate=$true};
    if($action.Arguments -match '\bscripts\.publish_portal_snapshot\b'){$approved=$true}
  };
  if($candidate){$i=Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath;
    $items += [pscustomobject]@{candidate_index=($items.Count+1);state=[string]$task.State;last_result=$i.LastTaskResult;
      last_run_utc=$i.LastRunTime.ToUniversalTime().ToString('o');approved_publish_runner=$approved}
  }
}; [pscustomobject]@{checked=$true;candidates=$items}|ConvertTo-Json -Depth 4
"""
    try:
        powershell = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return {
                "checked": False,
                "reason": "TASK_INVENTORY_UNAVAILABLE",
                "candidates": [],
            }
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {
            "checked": False,
            "reason": "TASK_INVENTORY_UNAVAILABLE",
            "candidates": [],
        }


def collect(
    config, directory: Path, health_reader=hosted_health, task_reader=publisher_tasks
) -> dict:
    now = datetime.now(timezone.utc)
    flags = {
        "publish_url_configured": bool(config.PORTAL_PUBLISH_URL),
        "publish_url_is_official": str(config.PORTAL_PUBLISH_URL).strip()
        == PUBLISH_URL,
        "publish_token_configured": len(str(config.PORTAL_PUBLISH_TOKEN or "")) >= 32,
        "lookup_secret_configured": len(str(config.PORTAL_LOOKUP_SECRET or "")) >= 32,
    }
    health = health_reader()
    tasks = task_reader()
    local = snapshot_metadata(directory / "portal_snapshot_latest.json", now)
    issues = [key.upper() for key, ok in flags.items() if not ok]
    if health.get("ok") is not True:
        issues.append("HOSTED_SNAPSHOT_NOT_READY")
    if not local.get("readable"):
        issues.append("LOCAL_SNAPSHOT_NOT_VERIFIED")
    elif local.get("age_hours", 0) < -0.1:
        issues.append("LOCAL_SNAPSHOT_CLOCK_INVALID")
    if not tasks.get("checked"):
        issues.append("PUBLISH_SCHEDULE_NOT_VERIFIED")
    elif not any(
        row.get("approved_publish_runner") and row.get("state") != "Disabled"
        for row in tasks.get("candidates", [])
    ):
        issues.append("AUTOMATIC_PUBLISH_RUNNER_NOT_VERIFIED")
    return {
        "report_type": "MTO_PORTAL_PUBLICATION_DIAGNOSTIC",
        "timestamp_utc": now.isoformat(),
        "status": "REVIEW_REQUIRED" if issues else "READY",
        "configuration": flags,
        "local_snapshot": local,
        "hosted_health": health,
        "publisher_tasks": tasks,
        "issues": issues,
        "database_queried": False,
        "uploaded": False,
        "configuration_changed": False,
        "tasks_changed": False,
        "note": "A local snapshot refresh is not a hosted upload. A task candidate is not proof of successful scheduled publication.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.project.resolve()))
    try:
        # This affects only the checker child process. Relative snapshot paths
        # must resolve exactly as they do when the API runs from C:\mto.
        os.chdir(args.project.resolve())
        from utils.config import config
        from backend.services.portal_publish_service import portal_snapshot_directory

        report = collect(config, Path(portal_snapshot_directory()))
    except Exception as error:
        # Do not expose secret values, SQL, environment files or raw exceptions.
        report = {
            "report_type": "MTO_PORTAL_PUBLICATION_DIAGNOSTIC",
            "status": "REVIEW_REQUIRED",
            "reason": "DIAGNOSTIC_UNAVAILABLE",
            "error_type": type(error).__name__,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
