# Archived Raw SQL Migrations

These files were the original hand-written SQL migration scripts used before
Alembic was adopted as the single migration tool.

**DO NOT RUN THESE FILES.** They have all been superseded by the Alembic
migrations in `migrations/versions/`. Running them against the live database
will create duplicate objects, break constraints, or corrupt the Alembic
version state.

They are kept here for historical reference only.

## Why they were archived

The live database was built by a mix of `SQLAlchemy create_all()` and these
raw SQL files, which caused `alembic_version` to drift out of sync with the
actual schema. The drift was resolved on 2026-06-01 by:

1. Stamping the DB to the true current revision (`f3a9b2c1d8e7`)
2. Running migration `a1b2c3d4e5f6` to apply the genuinely missing items
3. Moving these files here so they cannot be accidentally re-applied

## Single source of truth

All future schema changes must go through Alembic:

```bash
# Create a new migration
alembic revision --autogenerate -m "describe_your_change"

# Apply pending migrations
alembic upgrade head

# Check current state
alembic current
```
