
import sys
import os

# Add root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

print("Importing main components...")
try:
    import main
    print("main.py imported successfully")
    import dashboard
    print("dashboard.py imported successfully")
    from ui.property import PropertyPage
    print("PropertyPage imported successfully")
    from ui.receipts import ReceiptHistoryPage
    print("ReceiptHistoryPage imported successfully")
    from ui.ledger import LedgerPage
    print("LedgerPage imported successfully")
    from ui.reports import ReportsPage
    print("ReportsPage imported successfully")
except Exception as e:
    import traceback
    print(f"IMPORT ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\nSUCCESS: All modules imported without error.")
