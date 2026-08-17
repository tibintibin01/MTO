import os
import sys
from logging.config import fileConfig
from sqlalchemy import create_engine, pool
from alembic import context

# Add project root to sys.path so backend package imports resolve correctly
sys.path.append(os.getcwd())
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SQLALCHEMY_DATABASE_URL, Base
import backend.models  # noqa: F401 — ensures all models are registered on Base.metadata
import backend.models_portfolio  # noqa: F401 - registers portfolio metadata

# ---------------------------------------------------------------------------
# Alembic config object
# ---------------------------------------------------------------------------
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the database URL from utils.config + secrets_manager.
# We do NOT put the URL in alembic.ini because that would commit credentials.
# config.set_main_option makes it available to both offline and online modes.
config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode (generates SQL without a live connection).
    Useful for generating migration scripts to review before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "pyformat"},
        # Render AS NULL for server defaults so autogenerate diffs are clean
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations against a live database connection.

    We create the engine directly from SQLALCHEMY_DATABASE_URL rather than
    using engine_from_config() — the latter reads from the [alembic] INI
    section which intentionally has no sqlalchemy.url (credentials must not
    be committed). Using create_engine() directly avoids that fragility.

    NullPool is used so Alembic doesn't hold connections open after the
    migration completes — important in the Docker entrypoint where the
    migration process exits immediately after.
    """
    connectable = create_engine(
        SQLALCHEMY_DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Compare server defaults so autogenerate catches DEFAULT changes
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
