import db_manager as db
try:
    print("Testing DB connection...")
    res = db.db_query("SELECT 1", fetch=True)
    print(f"Result: {res}")
except Exception as e:
    print(f"Error: {e}")
