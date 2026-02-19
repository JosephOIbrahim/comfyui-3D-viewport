"""WebSocket/HTTP bridge for sending 3D viewport state to ComfyUI.

Sends camera state and AOV images (depth, normal) from the Qt+OpenGL
viewport to a running ComfyUI instance. Uses only stdlib (urllib, json)
for HTTP transport -- no pip dependencies required.

Protocol
--------
Two message types are sent as JSON POSTs to the ComfyUI API:

**Camera update** -- POST /api/camera
    {
        "type": "camera_update",
        "data": { ... camera_dict from OrbitCamera.to_load3d_camera() ... },
        "viewport": {"width": 1024, "height": 768},
        "timestamp": 1708300000.0
    }

**AOV update** -- POST /api/aov/{aov_type}
    {
        "type": "aov_update",
        "aov": "depth",
        "width": 1024,
        "height": 768,
        "format": "png",
        "data": "<base64-encoded PNG bytes>"
    }

Usage
-----
    from comfy_bridge import ComfyBridge

    bridge = ComfyBridge()
    bridge.connect()

    # Send camera from OrbitCamera
    cam_dict = orbit_camera.to_load3d_camera()
    bridge.send_camera(cam_dict)

    # Send AOV image
    bridge.send_aov("depth", depth_png_bytes)

    # Combined convenience
    bridge.send_viewport_state(cam_dict, width=1024, height=768)

    bridge.disconnect()

All network calls are dispatched to a daemon thread so the Qt main
thread never blocks on I/O.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from enum import Enum
from queue import Empty, SimpleQueue
from typing import Any

logger = logging.getLogger(__name__)


class BridgeStatus(Enum):
    """Connection state of the ComfyUI bridge."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class ComfyBridge:
    """Non-blocking bridge that sends camera and AOV data to ComfyUI.

    Parameters
    ----------
    host : str
        ComfyUI host address.
    port : int
        ComfyUI port number.
    timeout : float
        HTTP connection timeout in seconds.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8188,
        timeout: float = 2.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

        self._status = BridgeStatus.DISCONNECTED
        self._status_lock = threading.Lock()

        # Background sender thread and its work queue.
        self._queue: SimpleQueue[dict[str, Any] | None] = SimpleQueue()
        self._worker: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True when the bridge has confirmed ComfyUI is reachable."""
        with self._status_lock:
            return self._status is BridgeStatus.CONNECTED

    @property
    def status(self) -> str:
        """Human-readable status string."""
        with self._status_lock:
            st = self._status
        if st is BridgeStatus.CONNECTED:
            return f"Connected to ComfyUI at {self._host}:{self._port}"
        if st is BridgeStatus.CONNECTING:
            return f"Connecting to ComfyUI at {self._host}:{self._port}..."
        if st is BridgeStatus.ERROR:
            return f"Error communicating with ComfyUI at {self._host}:{self._port}"
        return "Disconnected"

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Start the background worker and probe ComfyUI.

        Returns True if ComfyUI responded to the initial health check,
        False otherwise.  Even on False the worker stays alive so that
        subsequent send calls can auto-reconnect.
        """
        if self._running:
            return self.is_connected

        self._running = True
        self._worker = threading.Thread(
            target=self._run_worker,
            name="ComfyBridge-worker",
            daemon=True,
        )
        self._worker.start()

        # Synchronous probe on the caller's thread so they get an
        # immediate True/False.  The worker handles everything after.
        reachable = self._probe()
        if reachable:
            self._set_status(BridgeStatus.CONNECTED)
            logger.info("ComfyUI bridge: connected to %s:%s", self._host, self._port)
        else:
            self._set_status(BridgeStatus.DISCONNECTED)
            logger.warning(
                "ComfyUI bridge: ComfyUI not reachable at %s:%s "
                "(will retry on next send)",
                self._host,
                self._port,
            )
        return reachable

    def disconnect(self) -> None:
        """Shut down the background worker and drain the queue."""
        if not self._running:
            return

        self._running = False
        # Sentinel value tells the worker to exit.
        self._queue.put(None)

        if self._worker is not None:
            self._worker.join(timeout=3.0)
            self._worker = None

        self._set_status(BridgeStatus.DISCONNECTED)
        logger.info("ComfyUI bridge: disconnected")

    # ------------------------------------------------------------------
    # Public send methods (non-blocking -- enqueue and return)
    # ------------------------------------------------------------------

    def send_camera(self, camera_dict: dict) -> bool:
        """Enqueue a camera-update message.

        Parameters
        ----------
        camera_dict : dict
            The dict returned by ``OrbitCamera.to_load3d_camera()``.

        Returns
        -------
        bool
            True if the message was enqueued (worker alive), False otherwise.
        """
        message = {
            "type": "camera_update",
            "data": camera_dict,
            "viewport": {},
            "timestamp": time.time(),
        }
        return self._enqueue(message)

    def send_aov(self, aov_type: str, png_bytes: bytes) -> bool:
        """Enqueue an AOV image message.

        Parameters
        ----------
        aov_type : str
            AOV identifier, e.g. ``"depth"`` or ``"normal"``.
        png_bytes : bytes
            Raw PNG image data.

        Returns
        -------
        bool
            True if the message was enqueued.
        """
        encoded = base64.b64encode(png_bytes).decode("ascii")
        message = {
            "type": "aov_update",
            "aov": aov_type,
            "format": "png",
            "data": encoded,
            "timestamp": time.time(),
        }
        return self._enqueue(message)

    def send_viewport_state(
        self,
        camera_dict: dict,
        width: int,
        height: int,
    ) -> bool:
        """Convenience: send camera + viewport dimensions in one message.

        Parameters
        ----------
        camera_dict : dict
            The dict returned by ``OrbitCamera.to_load3d_camera()``.
        width : int
            Viewport width in pixels.
        height : int
            Viewport height in pixels.
        """
        message = {
            "type": "camera_update",
            "data": camera_dict,
            "viewport": {"width": width, "height": height},
            "timestamp": time.time(),
        }
        return self._enqueue(message)

    # ------------------------------------------------------------------
    # Internal: queue management
    # ------------------------------------------------------------------

    def _enqueue(self, message: dict) -> bool:
        """Put a message on the send queue.

        Returns False if the worker is not running.
        """
        if not self._running:
            logger.debug("ComfyUI bridge: message dropped (bridge not running)")
            return False
        self._queue.put(message)
        return True

    # ------------------------------------------------------------------
    # Internal: background worker
    # ------------------------------------------------------------------

    def _run_worker(self) -> None:
        """Drain the queue and POST each message to ComfyUI.

        Runs on a daemon thread. Exits when it receives a ``None``
        sentinel or ``self._running`` becomes False.
        """
        while self._running:
            try:
                message = self._queue.get(timeout=0.25)
            except Empty:
                continue

            # Sentinel: shut down.
            if message is None:
                break

            self._dispatch(message)

    def _dispatch(self, message: dict) -> None:
        """Route a message to the correct HTTP endpoint."""
        msg_type = message.get("type", "")

        # Ensure we can reach ComfyUI; try reconnecting if needed.
        if not self.is_connected:
            self._set_status(BridgeStatus.CONNECTING)
            if not self._probe():
                self._set_status(BridgeStatus.ERROR)
                logger.debug(
                    "ComfyUI bridge: message dropped (ComfyUI unreachable)"
                )
                return
            self._set_status(BridgeStatus.CONNECTED)
            logger.info(
                "ComfyUI bridge: reconnected to %s:%s", self._host, self._port
            )

        try:
            if msg_type == "camera_update":
                self._post_json("/api/camera", message)
            elif msg_type == "aov_update":
                aov = message.get("aov", "unknown")
                self._post_json(f"/api/aov/{aov}", message)
            else:
                logger.warning("ComfyUI bridge: unknown message type %r", msg_type)
        except Exception:
            self._set_status(BridgeStatus.ERROR)
            logger.warning("ComfyUI bridge: connection lost")

    # ------------------------------------------------------------------
    # Internal: HTTP helpers (stdlib only)
    # ------------------------------------------------------------------

    def _post_json(self, path: str, payload: dict) -> bytes:
        """POST a JSON payload to ComfyUI and return the response body.

        Raises on network errors so the caller can update status.
        """
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as resp:
            return resp.read()

    def _probe(self) -> bool:
        """Check if ComfyUI is reachable (GET /system_stats).

        Returns True if it responds with HTTP 200, False otherwise.
        """
        url = f"{self.base_url}/system_stats"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False
