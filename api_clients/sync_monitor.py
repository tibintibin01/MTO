import threading
import time
import requests
import api_clients.api_helper as api
from api_clients.offline_manager import manager
from utils.logger import mto_logger
from utils.resilience import CircuitBreaker

class SyncMonitor:
    def __init__(self, interval=30, on_conflict=None):
        self.interval = interval
        self.on_conflict = on_conflict # Callback: func(action_id, local_payload, server_snapshot)
        self.running = False
        self._thread = None
        
        # Initialize Circuit Breaker for Local Backend connectivity
        self.circuit = CircuitBreaker(name="LocalBackend", failure_threshold=3, recovery_timeout=60)

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
        """Pings the local API server with circuit breaker protection."""
        def ping():
            response = requests.get(f"{api.BASE_URL}/", timeout=5, verify=api.CERT_PATH)
            return response.status_code == 200
            
        try:
            return self.circuit.call(ping)
        except Exception:
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
                if "Connection lost" in str(e) or "Status N/A" in str(e):
                    break

# Global monitor
sync_monitor = SyncMonitor(interval=20)
