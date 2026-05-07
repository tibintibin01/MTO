# -*- coding: utf-8 -*-
from datetime import datetime
import threading
import json
import os
import sys
from utils import log_error_to_file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class DatabaseError(Exception):
    """Base class for database related errors."""
    pass

class ConnectionError(DatabaseError):
    """Raised when a connection to the database cannot be established."""
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import mysql.connector
    from mysql.connector import Error
    CONNECT_FN = mysql.connector.connect
    DB_DRIVER = "mysql.connector"
    MYSQL_CONNECTOR_IMPORT_ERROR = None
except ImportError as exc:
    try:
        import pymysql
        Error = Exception
        CONNECT_FN = pymysql.connect
        DB_DRIVER = "pymysql"
        MYSQL_CONNECTOR_IMPORT_ERROR = None
    except ImportError:
        mysql = None
        Error = Exception
        CONNECT_FN = None
        DB_DRIVER = None
        MYSQL_CONNECTOR_IMPORT_ERROR = exc

DB_CONFIG_PATH = os.path.join(BASE_DIR, "db_config.json")

def load_db_config():
    runtime_config = {
        "host": os.getenv("MTO_DB_HOST", "").strip(),
        "port": os.getenv("MTO_DB_PORT", "3306").strip(),
        "user": os.getenv("MTO_DB_USER", "").strip(),
        "password": os.getenv("MTO_DB_PASSWORD", ""),
        "database": os.getenv("MTO_DB_NAME", "").strip(),
        "connect_timeout": int(os.getenv("MTO_DB_CONNECT_TIMEOUT", "5") or "5"),
        "mysql_path": os.getenv("MYSQL_PATH", "mysql").strip(),
        "mysqldump_path": os.getenv("MYSQLDUMP_PATH", "mysqldump").strip(),
    }
    if os.path.exists(DB_CONFIG_PATH):
        try:
            with open(DB_CONFIG_PATH, "r", encoding="utf-8") as handle:
                file_config = json.load(handle)
            if isinstance(file_config, dict):
                runtime_source = file_config.get("runtime", file_config)
                if isinstance(runtime_source, dict):
                    for key in ("host", "port", "user", "password", "database", "connect_timeout", "mysql_path", "mysqldump_path"):
                        if key in runtime_source and runtime_source[key] is not None:
                            runtime_config[key] = runtime_source[key]
        except Exception as exc:
            raise RuntimeError(f"Could not read db_config.json: {exc}") from exc
    
    # Handle encrypted password if present
    if runtime_config.get("password_encrypted"):
        try:
            from cryptography.fernet import Fernet
            import base64
            # Use environment-based secret key for industry-standard security
            raw_key = os.getenv("SECRET_KEY")
            if not raw_key:
                raise RuntimeError("CRITICAL SECURITY ERROR: SECRET_KEY environment variable is missing. Application cannot safely decrypt database credentials.")
            
            raw_key = raw_key.encode()
            # Ensure key is exactly 32 bytes for Fernet
            if len(raw_key) < 32:
                raw_key = raw_key.ljust(32)[:32]
            else:
                raw_key = raw_key[:32]
            
            key = base64.urlsafe_b64encode(raw_key)
            f = Fernet(key)
            runtime_config["password"] = f.decrypt(runtime_config["password_encrypted"].encode()).decode()
        except Exception as exc:
            log_error_to_file("Failed to decrypt database password", exc)
    
    missing = [key for key in ("host", "user", "database") if not str(runtime_config.get(key) or "").strip()]
    if missing:
        raise RuntimeError(f"Database configuration incomplete. Missing: {', '.join(missing)}")
    
    try: 
        runtime_config["port"] = int(runtime_config.get("port", 3306) or 3306)
    except Exception as exc: 
        log_error_to_file("Invalid database port in config", exc)
        runtime_config["port"] = 3306
    
    # CRITICAL SECURITY CONTROL: Require a robust SECRET_KEY
    raw_key = os.getenv("SECRET_KEY")
    if not raw_key or len(raw_key) < 16:
        raise RuntimeError("CRITICAL SECURITY ERROR: SECRET_KEY environment variable is missing or too short. "
                           "The application requires a secure key (min 16 chars) to protect sensitive data.")
    
    return runtime_config

DB_CONFIG_ERROR = None
try:
    DB_CONFIG = load_db_config()
except Exception as exc:
    DB_CONFIG = None
    DB_CONFIG_ERROR = str(exc)

if MYSQL_CONNECTOR_IMPORT_ERROR is not None:
    DB_CONFIG_ERROR = "mysql-connector-python is not installed."

MAINTENANCE_DB_CONFIG = dict(DB_CONFIG) if DB_CONFIG else None
if MAINTENANCE_DB_CONFIG:
    MAINTENANCE_DB_CONFIG.pop("database", None)

def _run_with_db_config(config, func):
    global DB_CONFIG
    old_config = DB_CONFIG
    DB_CONFIG = config
    try:
        if hasattr(_db_state, "conn"):
            try: 
                _db_state.conn.close()
            except Exception as e:
                log_error_to_file("Failed to close connection in wrapper", e)
            _db_state.conn = None
        return func()
    finally:
        DB_CONFIG = old_config
        if hasattr(_db_state, "conn"):
            try: 
                _db_state.conn.close()
            except Exception as e:
                log_error_to_file("Failed to close connection in wrapper finally", e)
            _db_state.conn = None

def _show_warning(title, message):
    print(f"WARNING [{title}]: {message}")

_db_state = threading.local()
DB_POOL = None

def close_thread_connection():
    """
    Explicitly close and remove the thread-local connection, returning it to the pool.
    MUST be called at the end of background threads (dashboard refresh, backup, etc.).
    """
    if hasattr(_db_state, "conn") and _db_state.conn:
        try:
            _db_state.conn.close()
        except Exception as e:
            log_error_to_file("Failed to close thread connection", e)
        finally:
            _db_state.conn = None

def _init_pool():
    global DB_POOL
    if DB_POOL is not None or CONNECT_FN is None or DB_DRIVER != "mysql.connector":
        return
    
    try:
        from mysql.connector import pooling
        # Filter config for connection-only params
        pool_params = {k: v for k, v in DB_CONFIG.items() if k not in ("mysql_path", "mysqldump_path", "password_encrypted")}
        
        DB_POOL = pooling.MySQLConnectionPool(
            pool_name="mto_pool",
            pool_size=10, # Maintain up to 10 ready connections
            pool_reset_session=True,
            **pool_params
        )
        print("Database Connection Pool initialized (Size: 10)")
    except Exception as e:
        log_error_to_file("Failed to initialize connection pool", e)
        DB_POOL = None

def get_db_connection():
    if DB_CONFIG is None or CONNECT_FN is None:
        return None
    
    # Try to get from thread-local first (for transaction continuity)
    conn = getattr(_db_state, "conn", None)
    if conn is not None and _connection_is_alive(conn):
        return conn

    # Try to get from pool
    global DB_POOL
    if DB_POOL is None:
        _init_pool()
    
    try:
        if DB_POOL:
            conn = DB_POOL.get_connection()
        else:
            # Fallback to direct connection if pool failed
            conn_params = {k: v for k, v in DB_CONFIG.items() if k not in ("mysql_path", "mysqldump_path", "password_encrypted")}
            conn = CONNECT_FN(**conn_params)
        
        if hasattr(conn, 'autocommit'): 
            conn.autocommit = False
        
        _db_state.conn = conn
        return conn
    except Exception as e:
        log_error_to_file("Database connection request failed", e)
        return None

def record_audit_log(user, action, table_name=None, record_id=None, old_values=None, new_values=None, ip_address=None):
    from services.auth_service import get_username
    username = get_username(user)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    def _to_json(val):
        if val is None: return None
        try: return json.dumps(val, default=str)
        except Exception as e: 
            log_error_to_file("JSON Audit Log encoding failure", e)
            return str(val)

    def operation(cur):
        cur.execute(
            """
            INSERT INTO audit_logs (user_id, username, action, table_name, record_id, old_values, new_values, ip_address, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (user_id, username, action, table_name, record_id, _to_json(old_values), _to_json(new_values), ip_address),
        )
        return cur.lastrowid
    
    # If no cursor provided, create a new transaction
    return execute_transaction(operation, show_errors=False)

def record_audit_log_with_cur(cur, user, action, table_name=None, record_id=None, old_values=None, new_values=None, ip_address=None):
    from services.auth_service import get_username
    username = get_username(user)
    user_id = user.get("id") if isinstance(user, dict) else None
    
    def _to_json(val):
        if val is None: return None
        try: return json.dumps(val, default=str)
        except: return str(val)

    cur.execute(
        """
        INSERT INTO audit_logs (user_id, username, action, table_name, record_id, old_values, new_values, ip_address, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (user_id, username, action, table_name, record_id, _to_json(old_values), _to_json(new_values), ip_address),
    )
    return cur.lastrowid

def _connection_is_alive(conn):
    try:
        if hasattr(conn, "is_connected"): return bool(conn.is_connected())
        conn.ping(reconnect=True)
        return True
    except Exception as e: 
        # Don't log this to file as it might spam during connection drops
        print(f"Connection check failed: {e}")
        return False

def db_query(query, params=(), fetch=False, commit=True, dictionary=False):
    conn = get_db_connection()
    if not conn:
        log_error_to_file("Database connection error in db_query", DB_CONFIG_ERROR, extra=query)
        raise ConnectionError("Lost connection to the Treasury Database.")
    result = None
    try:
        cur = _create_cursor(conn, dictionary=dictionary)
        cur.execute(query, params)
        if fetch: result = cur.fetchall()
        if commit: conn.commit()
        else: conn.rollback()
        cur.close()
    except Error as e:
        if commit: conn.rollback()
        log_error_to_file("Database query failed", e, extra=f"query={query}")
        raise DatabaseError(f"SQL Error: {str(e)}") from e
    return result

def db_execute(query, params=(), fetch=False, commit=True):
    conn = get_db_connection()
    if not conn:
        raise ConnectionError("Lost connection to the Treasury Database.")
    payload = {"rows": None, "lastrowid": None, "rowcount": 0}
    try:
        cur = _create_cursor(conn)
        cur.execute(query, params)
        payload["lastrowid"] = cur.lastrowid
        payload["rowcount"] = cur.rowcount
        if fetch: payload["rows"] = cur.fetchall()
        if commit: conn.commit()
        else: conn.rollback()
        cur.close()
        return payload
    except Error as e:
        if commit: conn.rollback()
        log_error_to_file("Database execute failed", e, extra=f"query={query}")
        raise DatabaseError(f"SQL Error: {str(e)}") from e

def execute_transaction(operation, show_errors=True, return_error=False):
    """Executes a set of database operations atomically."""
    conn = get_db_connection()
    if not conn: 
        raise ConnectionError("Could not establish database connection for transaction.")
    
    cur = None
    try:
        # Ensure we are in a clean state
        if hasattr(conn, 'rollback'):
            conn.rollback() 
            
        cur = _create_cursor(conn)
        
        # Explicitly start transaction for clarity and safety
        try:
            cur.execute("START TRANSACTION")
        except Error:
            # Some drivers/configurations might not support explicit START
            pass
            
        result = operation(cur)
        
        conn.commit()
        return result
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except:
            pass
            
        log_error_to_file("Atomic Transaction failed - ROLLBACK TRIGGERED", e)
        if isinstance(e, (DatabaseError, ConnectionError)):
            raise
        raise DatabaseError(f"Transaction failed: {str(e)}") from e
    finally:
        if cur is not None:
            try: cur.close()
            except: pass

def _create_cursor(conn, dictionary=False):
    try: 
        if DB_DRIVER == "mysql.connector":
            return conn.cursor(buffered=True, dictionary=dictionary)
        elif DB_DRIVER == "pymysql" and dictionary:
            import pymysql.cursors
            return conn.cursor(pymysql.cursors.DictCursor)
        return conn.cursor()
    except: 
        return conn.cursor()

# Lock management (generic helpers used by services)
def _acquire_named_lock(table_name, key_column, key_value, user_name, stale_minutes=30):
    # Use a whitelist for allowed table names to prevent SQL injection
    ALLOWED_LOCK_TABLES = ["property_locks", "ledger_locks", "user_locks", "payment_post_locks"]
    if table_name not in ALLOWED_LOCK_TABLES:
        raise ValueError(f"Unauthorized lock table: {table_name}")
    
    ALLOWED_LOCK_COLUMNS = ["property_id", "receipt_number", "user_id", "td_number"]
    if key_column not in ALLOWED_LOCK_COLUMNS:
        raise ValueError(f"Unauthorized lock column: {key_column}")

    # Import locally to avoid circular dependency
    from services.auth_service import get_username
    user_name = get_username(user_name)
    def lock_transaction(cur):
        cur.execute(f"DELETE FROM {table_name} WHERE locked_at < NOW() - INTERVAL %s MINUTE", (stale_minutes,))
        cur.execute(f"SELECT locked_by FROM {table_name} WHERE {key_column} = %s LIMIT 1", (key_value,))
        row = cur.fetchone()
        if row and row[0] != user_name: return {"ok": False, "locked_by": row[0]}
        if row and row[0] == user_name:
            cur.execute(f"UPDATE {table_name} SET locked_at = NOW() WHERE {key_column} = %s", (key_value,))
            return {"ok": True, "locked_by": user_name}
        cur.execute(f"INSERT INTO {table_name} ({key_column}, locked_by, locked_at) VALUES (%s, %s, NOW())", (key_value, user_name))
        return {"ok": True, "locked_by": user_name}
    return execute_transaction(lock_transaction, show_errors=False)

def _release_named_lock(table_name, key_column, key_value, user_name):
    ALLOWED_LOCK_TABLES = ["property_locks", "ledger_locks", "user_locks", "payment_post_locks"]
    if table_name not in ALLOWED_LOCK_TABLES:
        raise ValueError(f"Unauthorized lock table: {table_name}")
    
    ALLOWED_LOCK_COLUMNS = ["property_id", "receipt_number", "user_id", "td_number"]
    if key_column not in ALLOWED_LOCK_COLUMNS:
        raise ValueError(f"Unauthorized lock column: {key_column}")

    from services.auth_service import get_username
    user_name = get_username(user_name)
    db_query(f"DELETE FROM {table_name} WHERE {key_column} = %s AND locked_by = %s", (key_value, user_name))

def _release_all_named_locks(table_name, user_name):
    ALLOWED_LOCK_TABLES = ["property_locks", "ledger_locks", "user_locks", "payment_post_locks"]
    if table_name not in ALLOWED_LOCK_TABLES:
        raise ValueError(f"Unauthorized lock table: {table_name}")

    from services.auth_service import get_username
    user_name = get_username(user_name)
    db_query(f"DELETE FROM {table_name} WHERE locked_by = %s", (user_name,))
