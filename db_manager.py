# -*- coding: utf-8 -*-
from datetime import datetime
import threading
import json
import os
import sys
from utils import log_error_to_file

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import QueuePool
except ImportError as e:
    log_error_to_file("SQLAlchemy not found. Database pooling will be disabled.", e)
    create_engine = None
    QueuePool = None

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


from utils.config import config as mto_config
from utils.secrets_manager import secrets

def load_db_config():
    """
    Retrieves database configuration from the centralized config engine.
    """
    runtime_config = {
        "host": mto_config.DB_HOST,
        "port": mto_config.DB_PORT,
        "user": mto_config.DB_USER,
        "password": secrets.db_password,
        "database": mto_config.DB_NAME,
        "connect_timeout": mto_config.DB_CONNECT_TIMEOUT,
        "mysql_path": mto_config.MYSQL_PATH,
        "mysqldump_path": mto_config.MYSQLDUMP_PATH,
    }
    
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
DB_ENGINE = None

class ResultCache:
    """Namespaced TTL cache for granular invalidation and high-hit rates."""
    def __init__(self):
        self._cache = {} # Structure: {namespace: {key: (value, timestamp, ttl)}}
        self._lock = threading.Lock()

    def get(self, key, namespace="default"):
        with self._lock:
            ns = self._cache.get(namespace)
            if ns and key in ns:
                val, ts, ttl = ns[key]
                if (datetime.now() - ts).total_seconds() < ttl:
                    return val
                del ns[key]
        return None

    def set(self, key, value, namespace="default", ttl=60):
        with self._lock:
            if namespace not in self._cache:
                self._cache[namespace] = {}
            
            ns = self._cache[namespace]
            # Prevent single namespace bloat
            if len(ns) > 500:
                ns.clear()
                
            ns[key] = (value, datetime.now(), ttl)

    def clear(self, namespace=None):
        """Clears a specific namespace or the entire cache."""
        with self._lock:
            if namespace:
                if namespace in self._cache:
                    self._cache[namespace].clear()
            else:
                self._cache.clear()

# Global read cache with namespacing
read_cache = ResultCache()

def close_thread_connection():
    """
    Explicitly close and remove the thread-local connection and cached cursor.
    """
    if hasattr(_db_state, "cursor") and _db_state.cursor:
        try: _db_state.cursor.close()
        except: pass
        _db_state.cursor = None

    if hasattr(_db_state, "conn") and _db_state.conn:
        try:
            _db_state.conn.close()
        except Exception as e:
            log_error_to_file("Failed to close thread connection", e)
        finally:
            _db_state.conn = None


def _init_pool():
    global DB_ENGINE
    if DB_ENGINE is not None:
        return

    if not create_engine:
        log_error_to_file("SQLAlchemy engine creation skipped", "create_engine is not defined (import failed)")
        DB_ENGINE = None
        return

    try:
        # Construct SQLAlchemy URI
        user = DB_CONFIG["user"]
        password = DB_CONFIG["password"]
        host = DB_CONFIG["host"]
        port = DB_CONFIG["port"]
        database = DB_CONFIG["database"]
        
        # Using PyMySQL as the driver for robust pooling
        uri = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        
        DB_ENGINE = create_engine(
            uri,
            poolclass=QueuePool,
            pool_size=50,
            max_overflow=20,
            pool_recycle=1800,  # Recycled every 30 mins to prevent stale connections
            pool_timeout=30,    # Max wait time for a connection before failing
            pool_pre_ping=True  # Automatic recovery from drops (Health Check)
        )
        print(f"SQLAlchemy Connection Pool initialized (Size: 50 + 20 Overflow)")
    except Exception as e:
        log_error_to_file("Failed to initialize SQLAlchemy engine", e)
        DB_ENGINE = None


from contextlib import contextmanager

@contextmanager
def managed_connection(use_read_pool=False):
    """
    Context manager for safe database connection management.
    Ensures the connection is returned to the pool even if errors occur.
    """
    # 1. Choose path (Read vs Write)
    if not use_read_pool:
        # Writes clear the cache
        read_cache.clear()
        conn = get_db_connection()
    else:
        conn = get_read_connection()

    if not conn:
        raise ConnectionError("Could not acquire a database connection.")

    try:
        yield conn
    finally:
        # If we are NOT in an active transaction, we should return it to the pool
        # For SQLAlchemy raw_connection, 'close()' returns it to the pool.
        # However, we only do this if we aren't managing it via _db_state for a transaction.
        if not hasattr(_db_state, "in_transaction") or not _db_state.in_transaction:
            try:
                # Close cursor if cached
                if hasattr(_db_state, "cursor") and _db_state.cursor:
                    _db_state.cursor.close()
                    _db_state.cursor = None
                
                conn.close()
            except: pass
            finally:
                if hasattr(_db_state, "conn"):
                    _db_state.conn = None

def get_db_connection():
    if DB_CONFIG is None:
        return None

    # Try to get from thread-local (transaction support)
    conn = getattr(_db_state, "conn", None)
    if conn is not None and _connection_is_alive(conn):
        return conn

    # Always use the Pool
    global DB_ENGINE
    if DB_ENGINE is None:
        _init_pool()

    try:
        if DB_ENGINE:
            conn = DB_ENGINE.raw_connection()
            if hasattr(conn, "autocommit"):
                conn.autocommit = False
            return conn
            
        # --- FALLBACK: Direct Driver Connection ---
        if CONNECT_FN:
            conn = CONNECT_FN(
                host=DB_CONFIG["host"],
                port=DB_CONFIG["port"],
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                database=DB_CONFIG["database"]
            )
            return conn
            
        return None
    except Exception as e:
        log_error_to_file("Database connection request failed (including fallback)", e)
        return None


def record_audit_log(
    user,
    action,
    table_name=None,
    record_id=None,
    old_values=None,
    new_values=None,
    ip_address=None,
):
    from backend.services.auth_service import get_username

    username = get_username(user)
    user_id = user.get("id") if isinstance(user, dict) else None

    def _to_json(val):
        if val is None:
            return None
        try:
            return json.dumps(val, default=str)
        except Exception as e:
            log_error_to_file("JSON Audit Log encoding failure", e)
            return str(val)

    def operation(cur):
        cur.execute(
            """
            INSERT INTO audit_logs (user_id, username, action, table_name, record_id, old_values, new_values, ip_address, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                user_id,
                username,
                action,
                table_name,
                record_id,
                _to_json(old_values),
                _to_json(new_values),
                ip_address,
            ),
        )
        return cur.lastrowid

    # If no cursor provided, create a new transaction
    return execute_transaction(operation, show_errors=False)


def record_audit_log_with_cur(
    cur,
    user,
    action,
    table_name=None,
    record_id=None,
    old_values=None,
    new_values=None,
    ip_address=None,
):
    from backend.services.auth_service import get_username

    username = get_username(user)
    user_id = user.get("id") if isinstance(user, dict) else None

    def _to_json(val):
        if val is None:
            return None
        try:
            return json.dumps(val, default=str)
        except:
            return str(val)

    cur.execute(
        """
        INSERT INTO audit_logs (user_id, username, action, table_name, record_id, old_values, new_values, ip_address, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """,
        (
            user_id,
            username,
            action,
            table_name,
            record_id,
            _to_json(old_values),
            _to_json(new_values),
            ip_address,
        ),
    )
    return cur.lastrowid


def _connection_is_alive(conn):
    try:
        if hasattr(conn, "is_connected"):
            return bool(conn.is_connected())
        conn.ping(reconnect=True)
        return True
    except Exception as e:
        # Don't log this to file as it might spam during connection drops
        print(f"Connection check failed: {e}")
        return False


def get_read_connection():
    """Returns a connection optimized for read-only operations."""
    return get_db_connection()

def get_write_connection(invalidate_namespaces=None):
    """Returns a connection for write operations. Clears targeted cache folders."""
    if invalidate_namespaces:
        for ns in invalidate_namespaces:
            read_cache.clear(ns)
    else:
        # Safety fallback: clear everything if no scope defined
        read_cache.clear()
    return get_db_connection()

def db_query(query, params=(), fetch=False, commit=True, dictionary=False, use_cache=True, namespace="default", ttl=60):
    """
    Executes a query with namespaced caching and custom TTL support.
    """
    # 1. Try Cache for Read-Only fetches
    cache_key = None
    if fetch and not commit and use_cache:
        cache_key = f"{query}:{str(params)}:{dictionary}"
        cached_res = read_cache.get(cache_key, namespace=namespace)
        if cached_res is not None:
            return cached_res

    # 2. Handle Connection and Write Invalidation
    if commit:
        # Note: For db_query writes, we still default to global clear for safety
        # unless more specific logic is added to callers.
        conn = get_write_connection()
    else:
        conn = get_read_connection()

    if not conn:
        raise ConnectionError("Lost connection to the Treasury Database.")

    try:
        with managed_connection(use_read_pool=not commit) as conn:
            if not hasattr(_db_state, "cursor") or _db_state.cursor is None:
                _db_state.cursor = _create_cursor(conn, dictionary=dictionary)
            cur = _db_state.cursor
            
            cur.execute(query, params)
            
            result = None
            if fetch:
                result = cur.fetchall()
                if cache_key:
                    read_cache.set(cache_key, result, namespace=namespace, ttl=ttl)
            
            if commit:
                conn.commit()
            else:
                conn.rollback()
                
            return result
    except Error as e:
        log_error_to_file("Database query failed", e, extra=f"query={query}")
        raise DatabaseError(f"SQL Error: {str(e)}") from e

def db_execute(query, params=(), fetch=False, commit=True):
    """Wrapper for db_query returning metadata."""
    res = db_query(query, params, fetch=fetch, commit=commit)
    return {"rows": res}

def execute_transaction(operation, show_errors=True, return_error=False, invalidate_namespaces=None):
    """Executes a set of database operations atomically with targeted cache clearing."""
    with managed_connection(use_read_pool=False) as conn:
        _db_state.in_transaction = True
        _db_state.conn = conn
        
        try:
            conn.rollback()
            cur = _create_cursor(conn)
            _db_state.cursor = cur
            
            # Target invalidation: Only throw away what's necessary
            if invalidate_namespaces:
                for ns in invalidate_namespaces:
                    read_cache.clear(ns)
            else:
                read_cache.clear()

            try: cur.execute("START TRANSACTION")
            except: pass

            result = operation(cur)

            conn.commit()
            return result
        except Exception as e:
            try: conn.rollback()
            except: pass
            log_error_to_file("Atomic Transaction failed", e)
            
            # Re-raise original exception if it's a known business logic or connection error
            # We avoid wrapping these so the API layer can catch specific types (like Conflict)
            if isinstance(e, (DatabaseError, ConnectionError)) or "Conflict" in type(e).__name__ or "Sync" in type(e).__name__:
                raise
            
            raise DatabaseError(f"Transaction failed: {str(e)}") from e
        finally:
            _db_state.in_transaction = False
            _db_state.conn = None


def _create_cursor(conn, dictionary=False):
    """
    Creates a cursor from the connection, handling driver-specific options.
    If a driver-specific option fails (e.g. buffered on PyMySQL), it falls back to a standard cursor.
    """
    try:
        # 1. Try PyMySQL with dictionary support if requested
        if dictionary:
            try:
                import pymysql.cursors
                return conn.cursor(pymysql.cursors.DictCursor)
            except (ImportError, AttributeError):
                pass
        
        # 2. Try MySQL Connector with buffered support if available
        try:
            return conn.cursor(buffered=True, dictionary=dictionary)
        except (AttributeError, TypeError):
            # Probably PyMySQL or similar which doesn't support 'buffered'
            pass
            
        # 3. Fallback to standard cursor
        return conn.cursor()
    except Exception as e:
        # Last resort fallback
        print(f"DEBUG: Critical cursor creation failure: {e}")
        return conn.cursor()


# Lock management (generic helpers used by services)
def _acquire_named_lock(table_name, key_column, key_value, user_name, stale_minutes=30):
    # Use a whitelist for allowed table names to prevent SQL injection
    ALLOWED_LOCK_TABLES = [
        "property_locks",
        "ledger_locks",
        "user_locks",
        "payment_post_locks",
    ]
    if table_name not in ALLOWED_LOCK_TABLES:
        raise ValueError(f"Unauthorized lock table: {table_name}")

    ALLOWED_LOCK_COLUMNS = ["property_id", "receipt_number", "user_id", "td_number"]
    if key_column not in ALLOWED_LOCK_COLUMNS:
        raise ValueError(f"Unauthorized lock column: {key_column}")

    # Import locally to avoid circular dependency
    from backend.services.auth_service import get_username

    user_name = get_username(user_name)

    def lock_transaction(cur):
        cur.execute(
            f"DELETE FROM {table_name} WHERE locked_at < NOW() - INTERVAL %s MINUTE",
            (stale_minutes,),
        )
        cur.execute(
            f"SELECT locked_by FROM {table_name} WHERE {key_column} = %s LIMIT 1",
            (key_value,),
        )
        row = cur.fetchone()
        if row and row[0] != user_name:
            return {"ok": False, "locked_by": row[0]}
        if row and row[0] == user_name:
            cur.execute(
                f"UPDATE {table_name} SET locked_at = NOW() WHERE {key_column} = %s",
                (key_value,),
            )
            return {"ok": True, "locked_by": user_name}
        cur.execute(
            f"INSERT INTO {table_name} ({key_column}, locked_by, locked_at) VALUES (%s, %s, NOW())",
            (key_value, user_name),
        )
        return {"ok": True, "locked_by": user_name}

    return execute_transaction(lock_transaction, show_errors=False)


def _release_named_lock(table_name, key_column, key_value, user_name):
    ALLOWED_LOCK_TABLES = [
        "property_locks",
        "ledger_locks",
        "user_locks",
        "payment_post_locks",
    ]
    if table_name not in ALLOWED_LOCK_TABLES:
        raise ValueError(f"Unauthorized lock table: {table_name}")

    ALLOWED_LOCK_COLUMNS = ["property_id", "receipt_number", "user_id", "td_number"]
    if key_column not in ALLOWED_LOCK_COLUMNS:
        raise ValueError(f"Unauthorized lock column: {key_column}")

    from backend.services.auth_service import get_username

    user_name = get_username(user_name)
    db_query(
        f"DELETE FROM {table_name} WHERE {key_column} = %s AND locked_by = %s",
        (key_value, user_name),
    )


def _release_all_named_locks(table_name, user_name):
    ALLOWED_LOCK_TABLES = [
        "property_locks",
        "ledger_locks",
        "user_locks",
        "payment_post_locks",
    ]
    if table_name not in ALLOWED_LOCK_TABLES:
        raise ValueError(f"Unauthorized lock table: {table_name}")

    from backend.services.auth_service import get_username

    user_name = get_username(user_name)
    db_query(f"DELETE FROM {table_name} WHERE locked_by = %s", (user_name,))
def get_infrastructure_stats():
    """
    Returns real-time diagnostics for the database pool and result cache.
    Used for monitoring system health in the Admin Dashboard.
    """
    stats = {
        "pool": {"active": 0, "idle": 0, "size": 50, "overflow": 0},
        "cache": {"items": len(read_cache.cache), "namespaces": list(read_cache.namespaces.keys())},
        "environment": os.getenv("MTO_ENV", "development"),
        "timestamp": datetime.now().isoformat()
    }
    
    if DB_ENGINE:
        try:
            p = DB_ENGINE.pool
            stats["pool"]["active"] = p.checkedout()
            stats["pool"]["idle"] = p.checkedin()
            stats["pool"]["overflow"] = p.overflow()
            stats["pool"]["size"] = p.size()
        except:
            pass
            
    return stats
