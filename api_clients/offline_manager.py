# -*- coding: utf-8 -*-
import sqlite3
import json
from datetime import datetime

import threading
from api_clients.client_logger import mto_logger


class OfflineManager:
    def __init__(self, db_path="mto_local.db"):
        self.db_path = db_path
        self._queue_count_lock = threading.Lock()
        self._queue_count = 0
        self._init_db()
        self._refresh_queue_count()
        self._sync_thread = None
        self._stop_event = threading.Event()
        self._on_queue_change = None
        self._is_syncing = False

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Table for caching GET responses (Property lists, etc.)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT,
                    timestamp DATETIME
                )
            """
            )
            # Retain the legacy table only as forensic evidence. Phase 3 never
            # inserts or replays financial mutations from this local database.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method TEXT,
                    endpoint TEXT,
                    payload TEXT,
                    timestamp DATETIME,
                    status TEXT DEFAULT 'PENDING',
                    retry_count INTEGER DEFAULT 0,
                    last_error TEXT
                )
            """
            )
            conn.execute(
                """
                UPDATE sync_queue
                SET status = 'BLOCKED_LEGACY',
                    last_error = 'Automatic replay disabled by Phase 3 financial safety'
                WHERE status = 'PENDING'
                """
            )
            conn.commit()

    def set_on_queue_change(self, callback):
        """Register a callback to notify the UI of queue changes."""
        self._on_queue_change = callback
        self._notify_change()

    def _notify_change(self):
        if self._on_queue_change:
            try:
                count = self.get_queue_count()
                self._on_queue_change(count, self._is_syncing)
            except:
                pass

    def cache_data(self, key, data):
        """Saves a JSON snapshot of API data."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, data, timestamp) VALUES (?, ?, ?)",
                    (key, json.dumps(data), datetime.now()),
                )
                conn.commit()
        except:
            pass

    def get_cached_data(self, key):
        """Retrieves a local snapshot of API data."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT data FROM cache WHERE key = ?", (key,)
                ).fetchone()
                return json.loads(row[0]) if row else None
        except:
            return None

    def queue_action(self, method, endpoint, payload):
        """Reject offline writes; callers must never report local success."""
        mto_logger.warning(
            "Offline mutation queue is disabled; action was not stored",
            method=method,
            endpoint=endpoint,
        )
        return False

    def get_pending_actions(self, include_conflicts=False):
        """Return no replayable actions; legacy rows remain quarantined."""
        return []

    def get_quarantined_actions(self):
        """Return legacy queue evidence for administrator review only."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT id, method, endpoint, payload, status, timestamp
                    FROM sync_queue
                    WHERE status <> 'SYNCED'
                    ORDER BY id ASC
                    """
                ).fetchall()
                return [
                    {
                        "id": r[0],
                        "method": r[1],
                        "endpoint": r[2],
                        "payload": json.loads(r[3]),
                        "status": r[4],
                        "timestamp": r[5],
                    }
                    for r in rows
                ]
        except:
            return []

    def quarantine_pending_actions(self):
        """Defensively block pending rows created by an older client build."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                result = conn.execute(
                    """
                    UPDATE sync_queue
                    SET status = 'BLOCKED_LEGACY',
                        last_error = 'Automatic replay disabled by Phase 3 financial safety'
                    WHERE status = 'PENDING'
                    """
                )
                conn.commit()
            self._refresh_queue_count()
            self._notify_change()
            return int(result.rowcount or 0)
        except Exception:
            return 0

    def get_quarantined_count(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                return int(
                    conn.execute(
                        "SELECT COUNT(*) FROM sync_queue WHERE status <> 'SYNCED'"
                    ).fetchone()[0]
                )
        except Exception:
            return 0

    def mark_as_synced(self, action_id):
        """Removes or marks an action as successfully synchronized."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM sync_queue WHERE id = ?", (action_id,))
                conn.commit()
            self._refresh_queue_count()
            self._notify_change()
        except:
            pass

    def mark_as_failed(self, action_id, error_msg):
        """Increments retry count and logs error."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE sync_queue SET retry_count = retry_count + 1, last_error = ? WHERE id = ?",
                    (str(error_msg), action_id),
                )
                conn.commit()
        except:
            pass

    def mark_as_conflict(self, action_id, server_data):
        """Marks an action as in-conflict for manual resolution."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE sync_queue SET status = 'CONFLICT', last_error = 'Conflict Detected' WHERE id = ?",
                    (action_id,),
                )
                conn.commit()
            self._refresh_queue_count()
            self._notify_change()
        except:
            pass

    def get_queue_count(self):
        """Returns the cached pending count without blocking the UI thread."""
        with self._queue_count_lock:
            return self._queue_count

    def _refresh_queue_count(self):
        """Refreshes the cached pending count after a queue mutation."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM sync_queue WHERE status = 'PENDING'"
                ).fetchone()[0]
        except Exception:
            return
        with self._queue_count_lock:
            self._queue_count = count

    def start_sync_worker(self, api_request_fn):
        """Compatibility no-op: mutation replay is permanently disabled."""
        self.quarantine_pending_actions()
        mto_logger.info("Offline mutation replay remains disabled.")

    def stop_sync_worker(self):
        self._stop_event.set()
        if self._sync_thread:
            self._sync_thread.join(timeout=2)

    def _sync_worker_loop(self, api_request_fn):
        """Compatibility no-op retained for older imports."""
        self.quarantine_pending_actions()


# Global instance
manager = OfflineManager()
