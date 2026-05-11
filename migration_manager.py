import os
import re
from datetime import datetime
import db_manager as db

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def get_applied_versions():
    """Returns a set of version numbers that have already been applied."""
    try:
        # Check if table exists first
        exists = db.db_query(
            "SHOW TABLES LIKE 'schema_versions'", fetch=True, commit=False
        )
        if not exists:
            return set()

        rows = db.db_query(
            "SELECT version FROM schema_versions", fetch=True, commit=False
        )
        return {row[0] for row in rows}
    except Exception as e:
        print(f"Error checking schema_versions: {e}")
        return set()


def apply_migration(version, name, sql_content):
    """Executes the migration SQL and records it in schema_versions."""
    print(f"Applying migration {version}: {name}...")

    def transaction(cur):
        # Split by semicolon but ignore ones inside quotes (basic split)
        # For more complex SQL, we'd need a better parser, but this is a start
        statements = [s.strip() for s in sql_content.split(";") if s.strip()]
        for stmt in statements:
            if stmt:
                cur.execute(stmt)

        cur.execute(
            "INSERT INTO schema_versions (version, name, applied_at) VALUES (%s, %s, NOW())",
            (version, name),
        )

    try:
        db.execute_transaction(transaction)
        print(f"Successfully applied {name}")
        return True
    except Exception as e:
        print(f"FAILED to apply migration {name}: {e}")
        return False


def run_migrations():
    """Scans the migrations folder and applies pending migrations."""
    if not os.path.exists(MIGRATIONS_DIR):
        print(f"Migrations directory not found: {MIGRATIONS_DIR}")
        return

    applied = get_applied_versions()
    files = os.listdir(MIGRATIONS_DIR)

    # Match files like 001_initial.sql
    migration_files = []
    for f in files:
        match = re.match(r"(\d+)_(.+)\.sql", f)
        if match:
            version = int(match.group(1))
            name = match.group(2)
            migration_files.append((version, name, f))

    # Sort by version number
    migration_files.sort()

    for version, name, filename in migration_files:
        if version not in applied:
            file_path = os.path.join(MIGRATIONS_DIR, filename)
            with open(file_path, "r", encoding="utf-8") as h:
                content = h.read()

            if not apply_migration(version, name, content):
                print("Stopping migrations due to error.")
                break
        else:
            # print(f"Migration {version} already applied.")
            pass


if __name__ == "__main__":
    run_migrations()
