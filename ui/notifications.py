import websocket
import threading
import json
import time
from api_clients.api_helper import BASE_URL

class NotificationListener:
    def __init__(self, callbacks):
        self.callbacks = callbacks # Dict: on_open, on_close, on_notification, on_progress
        self.ws_url = BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
        self.ws_endpoint = f"{self.ws_url}/ws/notifications"
        
    def start(self):
        def listener_worker():
            while True:
                try:
                    ws = websocket.WebSocketApp(
                        self.ws_endpoint,
                        on_message=self._on_message,
                        on_error=self._on_error,
                        on_close=self._on_close,
                        on_open=self._on_open
                    )
                    ws.run_forever()
                except: pass
                time.sleep(5)
        threading.Thread(target=listener_worker, daemon=True).start()

    def _on_open(self, ws):
        if "on_open" in self.callbacks:
            self.callbacks["on_open"]()

    def _on_close(self, ws, code, msg):
        if "on_close" in self.callbacks:
            self.callbacks["on_close"]()

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("type") == "NOTIFICATION":
                if "on_notification" in self.callbacks:
                    self.callbacks["on_notification"](data)
            elif data.get("type") == "PROGRESS":
                if "on_progress" in self.callbacks:
                    self.callbacks["on_progress"](data)
        except: pass

    def _on_error(self, ws, error): pass
