"""add_jobs_table

Revision ID: c7f4e8b2d6a9
Revises: b5e9d3f2a1c8
Create Date: 2026-05-20

Changes:
  1. Creates jobs table for the DB-backed background job queue.
     Stores PDF generation, backup, and import tasks so they survive
     server restarts and can be polled for status.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7f4e8b2d6a9'
down_revision = 'b5e9d3f2a1c8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('submitted_by', sa.String(150), nullable=False),
        sa.Column('payload', sa.Text(), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('progress', sa.Integer(), server_default='0'),
        sa.Column('progress_message', sa.String(255), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_job_type', 'jobs', ['job_type'])
    op.create_index('ix_jobs_created_at', 'jobs', ['created_at'])


def downgrade():
    op.drop_index('ix_jobs_created_at', table_name='jobs')
    op.drop_index('ix_jobs_job_type', table_name='jobs')
    op.drop_index('ix_jobs_status', table_name='jobs')
    op.drop_table('jobs')
