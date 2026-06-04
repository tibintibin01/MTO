"""Add composite indexes for job queue worker scans.

Revision ID: c8d9e0f1a2b3
Revises: b2c3d4e5f6a1
Create Date: 2026-06-04

The worker hot paths are:

    WHERE status='PENDING' AND job_type IN (...) ORDER BY created_at LIMIT 1
    WHERE status='RUNNING' AND started_at < :cutoff

The previous schema had single-column indexes only, which left MariaDB with
more work under queue load. These composite indexes match the actual access
patterns without changing queue behavior.
"""

from alembic import op


revision = "c8d9e0f1a2b3"
down_revision = "b2c3d4e5f6a1"
branch_labels = None
depends_on = None


def _index_exists(table: str, name: str) -> bool:
    from sqlalchemy import text

    bind = op.get_bind()
    return bool(bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table_name "
        "AND INDEX_NAME = :index_name"
    ), {"table_name": table, "index_name": name}).scalar())


def upgrade():
    if not _index_exists("jobs", "ix_jobs_status_type_created"):
        op.create_index(
            "ix_jobs_status_type_created",
            "jobs",
            ["status", "job_type", "created_at"],
            unique=False,
        )

    if not _index_exists("jobs", "ix_jobs_status_started"):
        op.create_index(
            "ix_jobs_status_started",
            "jobs",
            ["status", "started_at"],
            unique=False,
        )


def downgrade():
    if _index_exists("jobs", "ix_jobs_status_started"):
        op.drop_index("ix_jobs_status_started", table_name="jobs")

    if _index_exists("jobs", "ix_jobs_status_type_created"):
        op.drop_index("ix_jobs_status_type_created", table_name="jobs")
