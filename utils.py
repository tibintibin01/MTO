from datetime import datetime
import os
import traceback
import pandas as pd
from typing import Optional, Any

def format_date_for_db(date_str: Optional[str]) -> Optional[str]:
    if not date_str: return None
    date_str = date_str.replace("/", "-").strip()
    try:
        return datetime.strptime(date_str, "%m-%d-%Y").strftime("%Y-%m-%d")
    except ValueError:
        try: return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError as e: 
            log_error_to_file(f"Date format warning for db: {date_str}", error=e)
            return date_str

def format_date_for_display(date_val: Any) -> str:
    if not date_val: return ""
    try:
        if isinstance(date_val, str):
            return datetime.strptime(date_val, "%Y-%m-%d").strftime("%m-%d-%Y")
        return date_val.strftime("%m-%d-%Y")
    except (ValueError, TypeError, AttributeError) as e:
        log_error_to_file(f"Date display format warning: {date_val}", error=e)
        return str(date_val)

def format_curr(val: Any) -> str:
    try: return "{:,.2f}".format(float(val)) if val else "0.00"
    except (ValueError, TypeError) as e: 
        log_error_to_file(f"Currency format warning: {val}", error=e)
        return "0.00"

def clean_num(val: Any) -> float:
    try: 
        if pd.isna(val) or val == "": return 0.0
        s = str(val).replace(",", "").replace("â‚±", "").strip()
        return float(s) if s else 0.0
    except (ValueError, TypeError) as e: 
        log_error_to_file(f"Number clean warning: {val}", error=e)
        return 0.0

import logging
from logging.handlers import RotatingFileHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
ERROR_LOG_PATH = os.path.join(LOGS_DIR, "system.log")

# Setup professional rotating logger (5MB per file, keep last 5 backups)
logger = logging.getLogger("MTOSystem")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(ERROR_LOG_PATH, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.addHandler(handler)

def log_error_to_file(context: str, error: Optional[Exception] = None, extra: Optional[Any] = None, traceback_text: Optional[str] = None) -> Optional[str]:
    """Professional wrapper for the system logger to maintain compatibility."""
    try:
        msg = context
        if error:
            msg += f" | Error: {error}"
        if extra:
            msg += f" | Details: {extra}"
        
        if traceback_text:
            msg += f"\nTraceback:\n{traceback_text}"
        elif error:
            # If an error is provided but no traceback, capture it if possible
            auto_traceback = traceback.format_exc()
            if auto_traceback and auto_traceback.strip() != "NoneType: None":
                msg += f"\nTraceback:\n{auto_traceback}"

        logger.error(msg)
        return ERROR_LOG_PATH
    except Exception:
        return None

def export_data_to_excel(data, columns, filename_prefix="Export"):
    """
    General purpose export tool. 
    data: List of lists/tuples representing rows.
    columns: List of column headers.
    """
    try:
        from tkinter import filedialog, messagebox
        import pandas as pd
        
        # Ask user for save location
        default_name = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        save_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("CSV files", "*.csv")],
            initialfile=default_name
        )
        
        if not save_path:
            return None

        df = pd.DataFrame(data, columns=columns)
        
        if save_path.endswith(".csv"):
            df.to_csv(save_path, index=False)
        else:
            df.to_excel(save_path, index=False)
            
        messagebox.showinfo("Success", f"Data exported successfully to:\n{save_path}")
        return save_path
    except Exception as e:
        log_error_to_file("Failed to export data", e)
        from tkinter import messagebox
        messagebox.showerror("Export Error", f"Failed to export data: {str(e)}")
        return None
