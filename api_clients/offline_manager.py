# -*- coding: utf-8 -*-
import sqlite3
import json
import os
from datetime import datetime

import threading
import time
from utils.logger import mto_logger

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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT,
                    timestamp DATETIME
                )
            """)
            # Table for queuing POST/PUT actions (Payments, Edits)
            conn.execute("""
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
            """)
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
            except: pass

    def cache_data(self, key, data):
        """Saves a JSON snapshot of API data."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, data, timestamp) VALUES (?, ?, ?)",
                    (key, json.dumps(data), datetime.now())
                )
                conn.commit()
        except: pass

    def get_cached_data(self, key):
        """Retrieves a local snapshot of API data."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT data FROM cache WHERE key = ?", (key,)).fetchone()
                return json.loads(row[0]) if row else None
        except: return None

    def queue_action(self, method, endpoint, payload):
        """Saves a pending write action to the queue."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO sync_queue (method, endpoint, payload, timestamp) VALUES (?, ?, ?, ?)",
                    (method, endpoint, json.dumps(payload), datetime.now())
                )
                conn.commit()
            self._refresh_queue_count()
            self._notify_change()
            return True
        except: return False

    def get_pending_actions(self, include_conflicts=False):
        """Retrieves actions waiting for synchronization."""
        try:
            query = "SELECT id, method, endpoint, payload FROM sync_queue WHERE status = 'PENDING' ORDER BY id ASC"
            if include_conflicts:
                query = "SELECT id, method, endpoint, payload FROM sync_queue ORDER BY id ASC"
            
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(query).fetchall()
                return [
                    {"id": r[0], "method": r[1], "endpoint": r[2], "payload": json.loads(r[3])}
                    for r in rows
                ]
        except: return []

    def mark_as_synced(self, action_id):
        """Removes or marks an action as successfully synchronized."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM sync_queue WHERE id = ?", (action_id,))
                conn.commit()
            self._refresh_queue_count()
            self._notify_change()
        except: pass

    def mark_as_failed(self, action_id, error_msg):
        """Increments retry count and logs error."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE sync_queue SET retry_count = retry_count + 1, last_error = ? WHERE id = ?",
                    (str(error_msg), action_id)
                )
                conn.commit()
        except: pass

    def mark_as_conflict(self, action_id, server_data):
        """Marks an action as in-conflict for manual resolution."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE sync_queue SET status = 'CONFLICT', last_error = 'Conflict Detected' WHERE id = ?",
                    (action_id,)
                )
                conn.commit()
            self._refresh_queue_count()
            self._notify_change()
        except: pass

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
        """Starts the background sync thread."""
        if self._sync_thread and self._sync_thread.is_alive():
            return

        self._stop_event.clear()
        self._sync_thread = threading.Thread(
            target=self._sync_worker_loop, 
            args=(api_request_fn,),
            daemon=True,
            name="OfflineSyncWorker"
        )
        self._sync_thread.start()
        mto_logger.info("Offline Sync Worker started.")

    def stop_sync_worker(self):
        self._stop_event.set()
        if self._sync_thread:
            self._sync_thread.join(timeout=2)

    def _sync_worker_loop(self, api_request_fn):
        """Internal loop that attempts to drain the queue when online."""
        while not self._stop_event.is_set():
            pending = self.get_pending_actions()
            if pending:
                self._is_syncing = True
                self._notify_change()
                
                # Attempt to sync each item
                for action in pending:
                    if self._stop_event.is_set(): break
                    
                    try:
                        # Attempt real API call
                        # Note: we use api_request_fn which handles tokens/errors
                        res = api_request_fn(
                            action["method"], 
                            action["endpoint"], 
                            data=action["payload"]
                        )
                        self.mark_as_synced(action["id"])
                        mto_logger.info(f"Sync Success: {action['method']} {action['endpoint']}")
                    except Exception as e:
                        err = str(e)
                        if "Status 409" in err or "Conflict" in err or "412" in err:
                            self.mark_as_conflict(action["id"], None)
                            mto_logger.warning(f"Sync Conflict: {action['endpoint']}")
                        elif "Offline" in err or "Connection" in err or "Status 502" in err:
                            # Still offline, stop draining for now
                            mto_logger.info("Still offline, pausing sync worker.")
                            break
                        else:
                            self.mark_as_failed(action["id"], err)
                            mto_logger.error(f"Sync Failed: {action['endpoint']} - {err}")
                            break # Pause on unknown errors to prevent infinite loops

                self._is_syncing = False
                self._notify_change()

            # Wait before next check
            self._stop_event.wait(30) # Check every 30 seconds

# Global instance
manager = OfflineManager()
