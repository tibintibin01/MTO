# -*- coding: utf-8 -*-
import threading
import time
import requests
import api_clients.api_helper as api
from api_clients.offline_manager import manager

class SyncMonitor:
    def __init__(self, interval=30):
        self.interval = interval
        self.running = False
        self._thread = None

    def start(self):
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self):
        while self.running:
            try:
                # Check connection
                is_online = self._check_connection()
                
                if is_online:
                    if api.CONNECTION_STATUS == "OFFLINE":
                        api.CONNECTION_STATUS = "ONLINE"
                    
                    # Flush queue if online
                    pending = manager.get_pending_actions()
                    if pending:
                        api.CONNECTION_STATUS = "SYNCING"
                        self._flush_queue(pending)
                        api.CONNECTION_STATUS = "ONLINE"
                else:
                    api.CONNECTION_STATUS = "OFFLINE"
            except:
                api.CONNECTION_STATUS = "OFFLINE"
                
            time.sleep(self.interval)

    def _check_connection(self):
        try:
            # Ping a simple endpoint
            response = requests.get(f"{api.BASE_URL}/", timeout=5, verify=False)
            return response.status_code == 200
        except:
            return False

    def _flush_queue(self, pending):
        """Attempts to push all pending actions to the server."""
        for action in pending:
            try:
                # Use raw api_request to avoid re-queuing on failure here
                # but we handle exceptions to stop flushing if connection drops again
                response = api.api_request(
                    action["method"],
                    action["endpoint"],
                    data=action["payload"]
                )
                
                # If success, remove from local DB
                manager.mark_as_synced(action["id"])
                print(f"SYNC SUCCESS: {action['method']} {action['endpoint']}")
            except Exception as e:
                # 409 Conflict Handling (Version Mismatch)
                if "409" in str(e):
                    print(f"SYNC CONFLICT for {action['id']}: Version mismatch.")
                    # Mark as conflict for manual resolution
                    manager.mark_as_conflict(action["id"], {"server_version": "CONFLICT_DETECTED"})
                    continue

                print(f"SYNC FAILED for {action['id']}: {e}")
                # If it fails due to connection, stop flushing and wait for next interval
                if "Connection lost" in str(e) or "Status N/A" in str(e):
                    break

# Global monitor
sync_monitor = SyncMonitor(interval=20) # Check every 20 seconds
