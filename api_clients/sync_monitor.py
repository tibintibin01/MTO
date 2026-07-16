import threading
import time
import requests
import api_clients.api_helper as api
from api_clients.offline_manager import manager
from utils.logger import mto_logger

class SyncMonitor:
    def __init__(self, interval=30, on_conflict=None):
        self.interval = interval
        self.on_conflict = on_conflict # Callback: func(action_id, local_payload, server_snapshot)
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
                    api.record_connection_success()
                    
                    # Flush queue if online
                    pending = manager.get_pending_actions()
                    if pending:
                        api.set_connection_status("SYNCING")
                        self._flush_queue(pending)
                        if api.get_connection_status() == "SYNCING":
                            api.record_connection_success()
                else:
                    api.record_connection_failure()
            except Exception as e:
                # A monitor implementation error is not proof of an API outage.
                # Log it and let the next health probe determine connectivity.
                mto_logger.warning("SyncMonitor loop error: %s", e)
                
            time.sleep(self.interval)

    def _check_connection(self):
        """Pings the local API server without delaying future recovery probes."""
        verify_param = str(api.CERT_PATH) if api.CERT_PATH.exists() else False
        try:
            response = requests.get(
                f"{api.BASE_URL}/readyz",
                timeout=(2, 3),
                verify=verify_param,
            )
            return response.status_code < 500
        except requests.exceptions.RequestException:
            return False

    def _flush_queue(self, pending):
        """Attempts to push all pending actions to the server."""
        for action in pending:
            try:
                # Use raw api_request (which now enforces SSL)
                response = api.api_request(
                    action["method"],
                    action["endpoint"],
                    data=action["payload"],
                    queue_offline=False,
                )
                
                # If success, remove from local DB
                manager.mark_as_synced(action["id"])
                mto_logger.info(f"SYNC SUCCESS: {action['method']} {action['endpoint']}", action_id=action["id"])
            except Exception as e:
                # 409 Conflict Handling (Version Mismatch)
                if "409" in str(e):
                    mto_logger.warning(f"SYNC CONFLICT detected for {action['id']}", action_id=action["id"])
                    
                    # Extract server snapshot (Simulation for now)
                    server_snapshot = {"error": "Conflict", "hint": "Field mismatch detected on server"}
                    
                    manager.mark_as_conflict(action["id"], server_snapshot)
                    
                    if self.on_conflict:
                        # Signal the coordinator to show UI
                        self.on_conflict(action["id"], action["payload"], server_snapshot)
                    continue

                mto_logger.error(f"SYNC FAILED for {action['id']}", error=str(e), action_id=action["id"])
                # A connection failure already updates the shared status in
                # api_request. Stop immediately instead of timing out once for
                # every queued action while the server is unavailable.
                if api.get_connection_status() in {"DEGRADED", "OFFLINE"}:
                    break

# Global monitor
sync_monitor = SyncMonitor(interval=10)
