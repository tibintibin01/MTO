# -*- coding: utf-8 -*-
import sqlite3
import json
import os
from datetime import datetime

class OfflineManager:
    def __init__(self, db_path="mto_local.db"):
        self.db_path = db_path
        self._init_db()

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
                    status TEXT DEFAULT 'PENDING'
                )
            """)
            conn.commit()

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
            return True
        except: return False

    def get_pending_actions(self):
        """Retrieves all actions waiting for synchronization."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute("SELECT id, method, endpoint, payload FROM sync_queue WHERE status = 'PENDING' ORDER BY id ASC").fetchall()
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
        except: pass

    def get_queue_count(self):
        """Returns the number of items waiting to be synced."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute("SELECT COUNT(*) FROM sync_queue").fetchone()[0]
        except: return 0

# Global instance
manager = OfflineManager()
