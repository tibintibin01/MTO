"""add_deleted_at_and_restrict_cascades

Revision ID: 87249241749c
Revises: 15a23adcbe4b
Create Date: 2026-05-19 07:16:55.501367

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '87249241749c'
down_revision = '15a23adcbe4b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add 'deleted_at' column to 'users' and 'properties'
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('properties', sa.Column('deleted_at', sa.DateTime(), nullable=True))

    # 2. Create indices for faster soft-delete filtering
    op.create_index(op.f('ix_users_deleted_at'), 'users', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_properties_deleted_at'), 'properties', ['deleted_at'], unique=False)

    # 3. Migrate existing is_deleted = True records to current timestamp
    op.execute("UPDATE users SET deleted_at = NOW() WHERE is_deleted = 1")
    op.execute("UPDATE properties SET deleted_at = NOW() WHERE is_deleted = 1")

    # 4. Drop the obsolete 'is_deleted' columns
    op.drop_column('users', 'is_deleted')
    op.drop_column('properties', 'is_deleted')

    # 5. Recreate foreign key constraints to enforce ON DELETE RESTRICT
    # --- payments -> properties ---
    op.drop_constraint('fk_payments_property', 'payments', type_='foreignkey')
    op.create_foreign_key('fk_payments_property', 'payments', 'properties', ['property_id'], ['id'], ondelete='RESTRICT')

    # --- property_billings -> properties ---
    op.drop_constraint('fk_property_billings_property', 'property_billings', type_='foreignkey')
    op.create_foreign_key('fk_property_billings_property', 'property_billings', 'properties', ['property_id'], ['id'], ondelete='RESTRICT')

    # --- property_assessment_history -> properties ---
    op.drop_constraint('fk_assessment_history_property', 'property_assessment_history', type_='foreignkey')
    op.create_foreign_key('fk_assessment_history_property', 'property_assessment_history', 'properties', ['property_id'], ['id'], ondelete='RESTRICT')

    # --- receipt_history -> properties ---
    op.drop_constraint('fk_receipt_history_property', 'receipt_history', type_='foreignkey')
    op.create_foreign_key('fk_receipt_history_property', 'receipt_history', 'properties', ['property_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    # 1. Revert constraints to CASCADE (original model state)
    op.drop_constraint('fk_receipt_history_property', 'receipt_history', type_='foreignkey')
    op.create_foreign_key('fk_receipt_history_property', 'receipt_history', 'properties', ['property_id'], ['id'], ondelete='CASCADE')

    op.drop_constraint('fk_assessment_history_property', 'property_assessment_history', type_='foreignkey')
    op.create_foreign_key('fk_assessment_history_property', 'property_assessment_history', 'properties', ['property_id'], ['id'], ondelete='CASCADE')

    op.drop_constraint('fk_property_billings_property', 'property_billings', type_='foreignkey')
    op.create_foreign_key('fk_property_billings_property', 'property_billings', 'properties', ['property_id'], ['id'], ondelete='CASCADE')

    op.drop_constraint('fk_payments_property', 'payments', type_='foreignkey')
    op.create_foreign_key('fk_payments_property', 'payments', 'properties', ['property_id'], ['id'], ondelete='CASCADE')

    # 2. Add back 'is_deleted' columns
    op.add_column('properties', sa.Column('is_deleted', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('is_deleted', sa.Boolean(), server_default='0', nullable=False))

    # 3. Restore soft deleted markers to is_deleted
    op.execute("UPDATE users SET is_deleted = 1 WHERE deleted_at IS NOT NULL")
    op.execute("UPDATE properties SET is_deleted = 1 WHERE deleted_at IS NOT NULL")

    # 4. Remove 'deleted_at' columns and indexes
    op.drop_index(op.f('ix_properties_deleted_at'), table_name='properties')
    op.drop_column('properties', 'deleted_at')
    
    op.drop_index(op.f('ix_users_deleted_at'), table_name='users')
    op.drop_column('users', 'deleted_at')
