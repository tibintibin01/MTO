import websocket
import threading
import json
from urllib.parse import urlencode

from api_clients.api_helper import BASE_URL, get_token, is_token_expired

class NotificationListener:
    def __init__(self, callbacks):
        self.callbacks = callbacks  # Dict: on_open, on_close, on_notification, on_progress
        self.ws_url = BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
        self._stop_event = threading.Event()
        self._thread = None
        self._ws = None
        self._lock = threading.Lock()

    def _build_endpoint(self):
        """Return an authenticated socket URL, or None until login is ready."""
        token = get_token()
        if not token or is_token_expired(token):
            return None
        query = urlencode({"token": token})
        return f"{self.ws_url}/ws/notifications?{query}"

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._listener_worker,
                name="mto-notification-listener",
                daemon=True,
            )
            self._thread.start()

    def _listener_worker(self):
        reconnect_delay = 2
        while not self._stop_event.is_set():
            endpoint = self._build_endpoint()
            if not endpoint:
                self._stop_event.wait(1)
                continue

            try:
                self._ws = websocket.WebSocketApp(
                    endpoint,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )
                self._ws.run_forever()
            except Exception:
                self._notify("on_close")
            finally:
                self._ws = None

            self._stop_event.wait(reconnect_delay)

    def stop(self):
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _notify(self, callback_name, *args):
        callback = self.callbacks.get(callback_name)
        if callback:
            try:
                callback(*args)
            except Exception:
                pass

    def _on_open(self, ws):
        self._notify("on_open")

    def _on_close(self, ws, code, msg):
        self._notify("on_close")

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("type") == "NOTIFICATION":
                self._notify("on_notification", data)
            elif data.get("type") == "PROGRESS":
                self._notify("on_progress", data)
        except (TypeError, ValueError, json.JSONDecodeError):
            return

    def _on_error(self, ws, error):
        self._notify("on_close")
