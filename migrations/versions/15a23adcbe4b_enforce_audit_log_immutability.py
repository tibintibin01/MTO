"""enforce_audit_log_immutability

Revision ID: 15a23adcbe4b
Revises: 001_baseline
Create Date: 2026-05-19 07:09:29.926002

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '15a23adcbe4b'
down_revision = '001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Trigger to prevent updates to audit_logs
    op.execute("""
    CREATE TRIGGER trg_prevent_audit_log_update 
    BEFORE UPDATE ON audit_logs 
    FOR EACH ROW 
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit logs are immutable. UPDATE operations are forbidden.';
    """)

    # Trigger to prevent deletions from audit_logs
    op.execute("""
    CREATE TRIGGER trg_prevent_audit_log_delete 
    BEFORE DELETE ON audit_logs 
    FOR EACH ROW 
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit logs are immutable. DELETE operations are forbidden.';
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_audit_log_update;")
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_audit_log_delete;")
