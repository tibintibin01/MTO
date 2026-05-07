import mysql.connector
import json
import os

def apply_migration():
    # 1. Load config
    config_path = "db_config.json"
    if not os.path.exists(config_path):
        print(f"Error: {config_path} not found. Please run this script from the MTO project folder.")
        return

    with open(config_path, "r") as f:
        config = json.load(f)["runtime"]

    print(f"Connecting to database '{config['database']}' on {config['host']}...")
    
    try:
        conn = mysql.connector.connect(
            host=config["host"],
            user=config["user"],
            password=config["password"],
            database=config["database"],
            port=config["port"]
        )
        cursor = conn.cursor()

        print("Adding new Assessment Roll columns (PIN, Barangay, etc.)...")
        
        # We use separate try blocks for each column in case some already exist
        new_columns = [
            "ALTER TABLE properties ADD COLUMN pin VARCHAR(100) DEFAULT NULL",
            "ALTER TABLE properties ADD COLUMN block_number VARCHAR(100) DEFAULT NULL",
            "ALTER TABLE properties ADD COLUMN prev_td_number VARCHAR(100) DEFAULT NULL",
            "ALTER TABLE properties ADD COLUMN effectivity_date DATE DEFAULT NULL",
            "ALTER TABLE properties ADD COLUMN barangay VARCHAR(100) DEFAULT NULL"
        ]

        for sql in new_columns:
            try:
                cursor.execute(sql)
                print(f"  [SUCCESS] {sql.split('ADD COLUMN ')[1].split(' ')[0]} added.")
            except mysql.connector.Error as err:
                if err.errno == 1060: # Duplicate column name
                    print(f"  [INFO] Column already exists, skipping.")
                else:
                    print(f"  [ERROR] {err.msg}")

        # Add Indices
        print("Optimizing database for fast searching...")
        indices = [
            "CREATE INDEX idx_barangay ON properties(barangay)",
            "CREATE INDEX idx_pin ON properties(pin)"
        ]
        for sql in indices:
            try:
                cursor.execute(sql)
                print(f"  [SUCCESS] Index created.")
            except:
                print(f"  [INFO] Index already exists, skipping.")

        conn.commit()
        print("\n✅ DATABASE MIGRATION COMPLETE!")
        print("You can now restart the app and run your Import again.")
        
    except mysql.connector.Error as err:
        print(f"CRITICAL ERROR: {err.msg}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    apply_migration()
