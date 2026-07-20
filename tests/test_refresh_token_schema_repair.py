from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.services.migration_service import (
    REFRESH_TOKEN_SESSION_COLUMNS,
    ensure_refresh_token_session_columns,
    get_missing_refresh_token_session_columns,
)


def test_refresh_token_session_schema_is_repaired_idempotently():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE refresh_tokens ("
                "id INTEGER PRIMARY KEY, "
                "user_id INTEGER NOT NULL, "
                "token VARCHAR(512) NOT NULL, "
                "expires_at DATETIME NOT NULL, "
                "is_revoked BOOLEAN DEFAULT 0"
                ")"
            )
        )

    with Session(engine) as session:
        assert get_missing_refresh_token_session_columns(session) == set(
            REFRESH_TOKEN_SESSION_COLUMNS
        )
        ensure_refresh_token_session_columns(session)
        ensure_refresh_token_session_columns(session)
        assert get_missing_refresh_token_session_columns(session) == set()

    columns = {
        column["name"] for column in inspect(engine).get_columns("refresh_tokens")
    }
    assert set(REFRESH_TOKEN_SESSION_COLUMNS) <= columns
