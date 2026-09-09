"""Transaction-bound idempotency for financial mutations.

The claim row is created and completed in the caller's database session. The
business mutation and its completed response therefore commit or roll back as
one unit; there is no fail-open middleware or unsigned-token identity parsing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import IdempotencyKey


_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_RETENTION_HOURS = 24


def _canonical_json(value: Any) -> str:
    return json.dumps(
        jsonable_encoder(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _request_hash(method: str, path: str, payload: Any) -> str:
    canonical = "\n".join((method.upper(), path, _canonical_json(payload)))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_uuid(value: Optional[str]) -> str:
    key = str(value or "").strip().lower()
    if not _UUID4_RE.fullmatch(key):
        raise HTTPException(
            status_code=400,
            detail=(
                "X-Idempotency-Key is required for financial changes and must "
                "be a UUID version 4."
            ),
        )
    return key


def _utcnow() -> datetime:
    # MariaDB stores naive UTC DATETIME values. Keeping comparison values naive
    # also makes this service deterministic under SQLite tests.
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class IdempotencyClaim:
    record: IdempotencyKey
    db_session: Session
    replayed: bool = False
    replay_body: Any = None
    replay_status_code: int = 200

    def complete(self, response_body: Any, status_code: int = 200) -> None:
        """Stage completion in the same transaction as the financial write."""
        if self.replayed:
            return
        self.record.response_body = _canonical_json(response_body)
        self.record.status_code = int(status_code)
        self.record.state = "COMPLETED"
        self.record.updated_at = _utcnow()
        self.db_session.flush()


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def _load_claim(
    db_session: Session, identity_key: str, *, lock: bool = True
) -> Optional[IdempotencyKey]:
    query = db_session.query(IdempotencyKey).filter(IdempotencyKey.key == identity_key)
    if lock:
        query = query.with_for_update()
    return query.first()


def begin_financial_operation(
    *,
    db_session: Session,
    idempotency_key: Optional[str],
    current_user: dict,
    method: str,
    path: str,
    payload: Any,
) -> IdempotencyClaim:
    """Atomically claim or replay one authenticated financial operation."""
    request_uuid = _validated_uuid(idempotency_key)
    user_id = current_user.get("id")
    if user_id is None:
        raise HTTPException(
            status_code=500,
            detail="Authenticated user identity is unavailable.",
        )

    user_scope = str(user_id)
    identity_key = f"v2:{user_scope}:{request_uuid}"
    fingerprint = _request_hash(method, path, payload)
    now = _utcnow()
    candidate = None

    # Do not gap-lock a missing key. Concurrent first attempts must be allowed
    # to race on the unique insert; the loser then reloads the committed result.
    existing = _load_claim(db_session, identity_key, lock=False)
    if existing and existing.expires_at <= now:
        db_session.delete(existing)
        db_session.flush()
        existing = None

    if existing is None:
        candidate = IdempotencyKey(
            key=identity_key,
            user_id=user_scope,
            request_hash=fingerprint,
            method=method.upper(),
            path=path,
            state="PROCESSING",
            status_code=200,
            response_body=None,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=_RETENTION_HOURS),
        )
        try:
            # Claim in the caller's outer transaction. A concurrent insert
            # waits on the unique index; if the winner commits, the loser
            # rolls back its empty transaction and loads the completed result.
            db_session.add(candidate)
            db_session.flush()
            existing = candidate
        except IntegrityError:
            # This function runs before business changes are staged, so this
            # rollback cannot discard a caller mutation. It only clears the
            # failed competing insert and starts a clean read transaction.
            db_session.rollback()
            existing = _load_claim(db_session, identity_key)
            if existing is None:
                raise _conflict(
                    "The operation could not acquire its idempotency claim. Retry safely."
                )

    if existing.request_hash != fingerprint:
        raise _conflict(
            "This idempotency key was already used for different request data."
        )
    if existing.method != method.upper() or existing.path != path:
        raise _conflict(
            "This idempotency key was already used for a different operation."
        )

    if existing.state == "COMPLETED":
        try:
            body = json.loads(existing.response_body or "{}")
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=500,
                detail="Stored idempotency response is invalid.",
            )
        return IdempotencyClaim(
            record=existing,
            db_session=db_session,
            replayed=True,
            replay_body=body,
            replay_status_code=int(existing.status_code or 200),
        )

    if existing is not candidate:
        raise _conflict(
            "An identical financial operation is already being processed. Retry shortly."
        )

    return IdempotencyClaim(record=existing, db_session=db_session)
