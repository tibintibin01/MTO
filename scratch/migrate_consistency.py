import db_manager as db
import sys

def migrate():
    print("Starting Consistency Metadata Migration...")
    try:
        # Add version column for logical sequencing
        try:
            db.db_query("ALTER TABLE properties ADD COLUMN version INT DEFAULT 1")
            print("Added 'version' column to properties table.")
        except Exception as e:
            print(f"Version column check: {e}")

        # Add updated_at column for temporal tracking
        try:
            db.db_query("ALTER TABLE properties ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
            print("Added 'updated_at' column to properties table.")
        except Exception as e:
            print(f"Updated_at column check: {e}")

        print("Migration COMPLETED.")
    except Exception as e:
        print(f"CRITICAL MIGRATION ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate()
