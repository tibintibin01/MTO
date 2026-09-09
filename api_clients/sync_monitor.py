import threading
import time
import requests
import api_clients.api_helper as api
from api_clients.offline_manager import manager
from api_clients.client_logger import mto_logger


class SyncMonitor:
    def __init__(self, interval=30, on_conflict=None):
        self.interval = interval
        self.on_conflict = (
            on_conflict  # Callback: func(action_id, local_payload, server_snapshot)
        )
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
                    manager.quarantine_pending_actions()
                elif is_online is False:
                    api.record_connection_failure()
            except Exception as e:
                # A monitor implementation error is not proof of an API outage.
                # Log it and let the next health probe determine connectivity.
                mto_logger.warning("SyncMonitor loop error: %s", e)

            time.sleep(self.interval)

    def _check_connection(self):
        """Pings the local API server without delaying future recovery probes."""
        verify_param = api.get_tls_verification()
        try:
            response = requests.get(
                f"{api.BASE_URL}/readyz",
                timeout=(2, 3),
                verify=verify_param,
            )
            return response.status_code < 500
        except requests.exceptions.SSLError as exc:
            # A trust failure is a security/configuration incident, not proof
            # that the server is offline. Do not flush or queue anything.
            api.set_connection_status("DEGRADED")
            mto_logger.error("API TLS verification failed: %s", exc)
            return None
        except requests.exceptions.RequestException:
            return False

    def _flush_queue(self, pending):
        """Never replay mutations; quarantine evidence from older builds."""
        manager.quarantine_pending_actions()


# Global monitor
sync_monitor = SyncMonitor(interval=10)
