"""Viewport Bridge Server — WebSocket server broadcasting camera and AOV state.

Runs inside the Qt event loop using QWebSocketServer. Broadcasts camera updates
to all connected browser clients (ComfyUI sidebar panel) and auto-writes
camera_state.json for file-based polling by Python custom nodes.

Architecture:
    Qt Viewport (this server on port 8766)
      |-- Browser WS client (ComfyUI panel JS) -- real-time camera/AOV display
      |-- Python node reads camera_state.json    -- file-based, no WS dependency
"""

from __future__ import annotations

import json
import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocketServer, QWebSocket

from config import (
    BRIDGE_WS_PORT,
    BRIDGE_CAMERA_THROTTLE_MS,
    CAMERA_STATE_FILE,
)


class BridgeServer:
    """WebSocket server that broadcasts viewport state to ComfyUI panels.

    Parameters
    ----------
    port : int
        TCP port to listen on.
    """

    def __init__(self, port: int = BRIDGE_WS_PORT) -> None:
        self._port = port
        self._server: QWebSocketServer | None = None
        self._clients: list[QWebSocket] = []
        self._last_camera_state: dict = {}
        self._last_aov_paths: dict = {}
        self._last_broadcast_time: float = 0.0
        self._running = False

        # Throttle timer for camera broadcasts
        self._throttle_timer = QTimer()
        self._throttle_timer.setSingleShot(True)
        self._throttle_timer.timeout.connect(self._flush_camera)
        self._pending_camera: dict | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the WebSocket server. Returns True on success."""
        if self._running:
            return True

        self._server = QWebSocketServer(
            "ViewportBridge",
            QWebSocketServer.SslMode.NonSecureMode,
        )

        if not self._server.listen(QHostAddress.SpecialAddress.LocalHost, self._port):
            print(f"Bridge server: failed to listen on port {self._port}")
            self._server = None
            return False

        self._server.newConnection.connect(self._on_new_connection)
        self._running = True
        print(f"Bridge server: listening on ws://127.0.0.1:{self._port}")
        return True

    def stop(self) -> None:
        """Stop the server and disconnect all clients."""
        if not self._running:
            return

        self._throttle_timer.stop()

        for client in self._clients[:]:
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()

        if self._server is not None:
            self._server.close()
            self._server = None

        self._running = False
        print("Bridge server: stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        client = self._server.nextPendingConnection()
        if client is None:
            return

        client.textMessageReceived.connect(
            lambda msg, c=client: self._on_message(c, msg)
        )
        client.disconnected.connect(
            lambda c=client: self._on_disconnected(c)
        )

        self._clients.append(client)
        print(f"Bridge server: client connected ({self.client_count} total)")

        # Send current state to new client
        self._send_to_client(client, {
            "type": "status",
            "state": "connected",
            "viewport_version": "0.4.0",
            "capabilities": ["camera_export", "depth_aov", "normal_aov"],
        })
        if self._last_camera_state:
            self._send_to_client(client, {
                "type": "camera_update",
                "camera": self._last_camera_state,
                "timestamp": time.time(),
            })
        if self._last_aov_paths:
            self._send_to_client(client, {
                "type": "aov_update",
                "aovs": self._last_aov_paths,
                "timestamp": time.time(),
            })

    def _on_disconnected(self, client: QWebSocket) -> None:
        if client in self._clients:
            self._clients.remove(client)
        print(f"Bridge server: client disconnected ({self.client_count} total)")

    def _on_message(self, client: QWebSocket, message: str) -> None:
        """Handle incoming messages from browser panel."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type", "")

        if msg_type == "get_state":
            self._send_to_client(client, {
                "type": "full_state",
                "camera": self._last_camera_state,
                "aovs": self._last_aov_paths,
                "timestamp": time.time(),
            })
        elif msg_type == "request_preset":
            # Forward preset request to viewport (handled by callback)
            preset_id = data.get("preset_id")
            if preset_id is not None and self._preset_callback:
                self._preset_callback(preset_id)
        elif msg_type == "request_aov":
            if self._aov_callback:
                self._aov_callback()

    # ------------------------------------------------------------------
    # Callbacks (set by viewport)
    # ------------------------------------------------------------------

    _preset_callback = None
    _aov_callback = None

    def set_preset_callback(self, callback) -> None:
        """Set callback for preset change requests from the panel."""
        self._preset_callback = callback

    def set_aov_callback(self, callback) -> None:
        """Set callback for AOV render requests from the panel."""
        self._aov_callback = callback

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    def broadcast_camera(self, camera_dict: dict) -> None:
        """Broadcast camera state to all clients (throttled).

        Also writes camera_state.json for file-based polling.
        """
        self._last_camera_state = camera_dict
        self._pending_camera = camera_dict

        # Write file for Python node polling
        self._write_camera_file(camera_dict)

        # Throttle WS broadcasts
        if not self._throttle_timer.isActive():
            self._throttle_timer.start(BRIDGE_CAMERA_THROTTLE_MS)

    def _flush_camera(self) -> None:
        """Send the pending camera update to all clients."""
        if self._pending_camera is None:
            return

        msg = {
            "type": "camera_update",
            "camera": self._pending_camera,
            "timestamp": time.time(),
        }
        self._broadcast(msg)
        self._pending_camera = None

    def broadcast_aov(self, aov_paths: dict, resolution: tuple[int, int]) -> None:
        """Broadcast AOV update to all clients.

        Parameters
        ----------
        aov_paths : dict
            Mapping of AOV name to file path, e.g. {"depth": "depth_aov.png"}.
        resolution : tuple
            (width, height) of the AOV renders.
        """
        self._last_aov_paths = aov_paths
        msg = {
            "type": "aov_update",
            "aovs": aov_paths,
            "resolution": list(resolution),
            "timestamp": time.time(),
        }
        self._broadcast(msg)

    def _broadcast(self, msg: dict) -> None:
        """Send a JSON message to all connected clients."""
        text = json.dumps(msg, sort_keys=True)
        for client in self._clients[:]:
            self._send_to_client(client, msg, _text=text)

    def _send_to_client(
        self, client: QWebSocket, msg: dict, _text: str | None = None,
    ) -> None:
        """Send a JSON message to a single client."""
        text = _text or json.dumps(msg, sort_keys=True)
        try:
            client.sendTextMessage(text)
        except Exception:
            # Client likely disconnected
            if client in self._clients:
                self._clients.remove(client)

    # ------------------------------------------------------------------
    # File-based state export
    # ------------------------------------------------------------------

    @staticmethod
    def _write_camera_file(camera_dict: dict) -> None:
        """Write camera state to JSON file for Python node polling."""
        try:
            with open(CAMERA_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(camera_dict, f, indent=2, sort_keys=True)
        except OSError:
            pass  # Non-critical — file write failure shouldn't crash viewport
