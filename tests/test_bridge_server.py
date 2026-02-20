"""Tests for src/bridge_server.py -- WebSocket bridge server."""

import importlib
import json
import sys
import time
from types import ModuleType
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Mock PySide6 modules before importing bridge_server
#
# Uses setdefault so we never overwrite mocks already installed by other
# test modules (test collection order varies). We also ensure all attributes
# that sibling test files need (Qt, QMimeData, QRectF, etc.) are present.
# ---------------------------------------------------------------------------

def _get_or_create_module(name):
    """Get existing mock module or create a new one."""
    existing = sys.modules.get(name)
    if existing is not None and isinstance(existing, ModuleType):
        return existing
    mod = ModuleType(name)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


# Build PySide6 mock hierarchy (never overwrite existing)
_pyside6 = _get_or_create_module("PySide6")
_qtcore = _get_or_create_module("PySide6.QtCore")
_qtgui = _get_or_create_module("PySide6.QtGui")
_qtnetwork = _get_or_create_module("PySide6.QtNetwork")
_qtwebsockets = _get_or_create_module("PySide6.QtWebSockets")

# Wire submodules to parent
_pyside6.QtCore = _qtcore
_pyside6.QtGui = _qtgui
_pyside6.QtNetwork = _qtnetwork
_pyside6.QtWebSockets = _qtwebsockets

# QtCore attributes (bridge_server needs QTimer; other tests need Qt, etc.)
if not hasattr(_qtcore, "QTimer"):
    _mock_qtimer_cls = MagicMock()
    _mock_qtimer_instance = MagicMock()
    _mock_qtimer_instance.isActive.return_value = False
    _mock_qtimer_cls.return_value = _mock_qtimer_instance
    _qtcore.QTimer = _mock_qtimer_cls
if not hasattr(_qtcore, "Qt"):
    _qtcore.Qt = MagicMock()
if not hasattr(_qtcore, "QMimeData"):
    _qtcore.QMimeData = MagicMock
if not hasattr(_qtcore, "QRectF"):
    _qtcore.QRectF = MagicMock()

# QtGui attributes (needed by test_file_drop, test_hud)
for _attr in ("QColor", "QDragEnterEvent", "QDropEvent", "QFont", "QPainter", "QPen"):
    if not hasattr(_qtgui, _attr):
        setattr(_qtgui, _attr, MagicMock())

# QtNetwork
if not hasattr(_qtnetwork, "QHostAddress"):
    _mock_host = MagicMock()
    _mock_host.SpecialAddress = MagicMock()
    _mock_host.SpecialAddress.LocalHost = "localhost"
    _qtnetwork.QHostAddress = _mock_host

# QtWebSockets
if not hasattr(_qtwebsockets, "QWebSocketServer"):
    _mock_ws_server_cls = MagicMock()
    _mock_ws_server_cls.SslMode = MagicMock()
    _mock_ws_server_cls.SslMode.NonSecureMode = 0
    _qtwebsockets.QWebSocketServer = _mock_ws_server_cls
if not hasattr(_qtwebsockets, "QWebSocket"):
    _qtwebsockets.QWebSocket = MagicMock()


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

import config  # noqa: E402 — must be after path setup by conftest
import bridge_server  # noqa: E402

# Force reimport to pick up mocks
importlib.reload(bridge_server)
BridgeServer = bridge_server.BridgeServer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def server():
    """Create a BridgeServer with mocked Qt internals."""
    srv = BridgeServer(port=9999)
    # Replace the QTimer that was created in __init__
    srv._throttle_timer = MagicMock()
    srv._throttle_timer.isActive.return_value = False
    return srv


@pytest.fixture
def mock_ws_server():
    """A mock QWebSocketServer that successfully listens."""
    mock = MagicMock()
    mock.listen.return_value = True
    return mock


@pytest.fixture
def mock_client():
    """A mock QWebSocket client."""
    client = MagicMock()
    client.sendTextMessage = MagicMock()
    return client


@pytest.fixture
def started_server(server, mock_ws_server):
    """A BridgeServer that has been started with a mock server."""
    with patch.object(bridge_server, "QWebSocketServer", return_value=mock_ws_server):
        # Patch the QWebSocketServer class used in bridge_server
        original = bridge_server.QWebSocketServer
        bridge_server.QWebSocketServer = MagicMock(return_value=mock_ws_server)
        server.start()
        bridge_server.QWebSocketServer = original
    # Point at the mock
    server._server = mock_ws_server
    return server


# ---------------------------------------------------------------------------
# Tests: Lifecycle
# ---------------------------------------------------------------------------

class TestBridgeLifecycle:
    def test_initial_state(self, server):
        assert not server.is_running
        assert server.client_count == 0

    def test_start_sets_running(self, started_server):
        assert started_server.is_running

    def test_start_idempotent(self, started_server):
        """Calling start() twice returns True without double-binding."""
        assert started_server.start() is True

    def test_stop_clears_state(self, started_server, mock_ws_server):
        started_server.stop()
        assert not started_server.is_running
        assert started_server.client_count == 0
        mock_ws_server.close.assert_called_once()

    def test_stop_when_not_running(self, server):
        """Stopping a server that was never started is a no-op."""
        server.stop()  # should not raise
        assert not server.is_running


# ---------------------------------------------------------------------------
# Tests: Connection management
# ---------------------------------------------------------------------------

class TestBridgeConnections:
    def test_on_new_connection_adds_client(self, started_server, mock_ws_server, mock_client):
        mock_ws_server.nextPendingConnection.return_value = mock_client
        started_server._on_new_connection()
        assert started_server.client_count == 1

    def test_on_new_connection_sends_status(self, started_server, mock_ws_server, mock_client):
        mock_ws_server.nextPendingConnection.return_value = mock_client
        started_server._on_new_connection()
        # First call should be status message
        sent = mock_client.sendTextMessage.call_args_list[0][0][0]
        data = json.loads(sent)
        assert data["type"] == "status"
        assert data["state"] == "connected"
        assert "camera_export" in data["capabilities"]

    def test_on_new_connection_sends_cached_camera(self, started_server, mock_ws_server, mock_client):
        started_server._last_camera_state = {"position": [1, 2, 3], "fov": 45}
        mock_ws_server.nextPendingConnection.return_value = mock_client
        started_server._on_new_connection()
        # Second call should be camera_update
        sent_calls = mock_client.sendTextMessage.call_args_list
        assert len(sent_calls) >= 2
        cam_msg = json.loads(sent_calls[1][0][0])
        assert cam_msg["type"] == "camera_update"
        assert cam_msg["camera"]["fov"] == 45

    def test_on_disconnected_removes_client(self, started_server, mock_ws_server, mock_client):
        mock_ws_server.nextPendingConnection.return_value = mock_client
        started_server._on_new_connection()
        assert started_server.client_count == 1
        started_server._on_disconnected(mock_client)
        assert started_server.client_count == 0

    def test_on_disconnected_unknown_client(self, started_server, mock_client):
        """Disconnecting an unknown client is a no-op."""
        started_server._on_disconnected(mock_client)
        assert started_server.client_count == 0


# ---------------------------------------------------------------------------
# Tests: Message handling
# ---------------------------------------------------------------------------

class TestBridgeMessages:
    def test_get_state_sends_full_state(self, started_server, mock_ws_server, mock_client):
        started_server._last_camera_state = {"fov": 50}
        started_server._last_aov_paths = {"depth": "depth.png"}
        mock_ws_server.nextPendingConnection.return_value = mock_client
        started_server._on_new_connection()

        # Simulate incoming get_state message
        started_server._on_message(mock_client, json.dumps({"type": "get_state"}))

        # Find the full_state response (last call)
        last_sent = mock_client.sendTextMessage.call_args_list[-1][0][0]
        data = json.loads(last_sent)
        assert data["type"] == "full_state"
        assert data["camera"]["fov"] == 50
        assert data["aovs"]["depth"] == "depth.png"

    def test_request_preset_calls_callback(self, started_server):
        callback = MagicMock()
        started_server.set_preset_callback(callback)
        started_server._on_message(MagicMock(), json.dumps({
            "type": "request_preset",
            "preset_id": 2,
        }))
        callback.assert_called_once_with(2)

    def test_request_aov_calls_callback(self, started_server):
        callback = MagicMock()
        started_server.set_aov_callback(callback)
        started_server._on_message(MagicMock(), json.dumps({
            "type": "request_aov",
        }))
        callback.assert_called_once()

    def test_malformed_json_ignored(self, started_server):
        """Malformed JSON messages should be silently ignored."""
        started_server._on_message(MagicMock(), "not valid json{{{")
        # No crash = pass

    def test_unknown_message_type_ignored(self, started_server):
        """Unknown message types should be silently ignored."""
        started_server._on_message(MagicMock(), json.dumps({"type": "unknown_xyz"}))
        # No crash = pass


# ---------------------------------------------------------------------------
# Tests: Broadcasting
# ---------------------------------------------------------------------------

class TestBridgeBroadcasting:
    def test_broadcast_camera_stores_state(self, started_server):
        camera = {"position": [0, 1, 5], "fov": 45}
        with patch.object(BridgeServer, "_write_camera_file"):
            started_server.broadcast_camera(camera)
        assert started_server._last_camera_state == camera

    def test_broadcast_camera_writes_file(self, started_server, tmp_path):
        camera = {"position": [0, 1, 5], "fov": 45}
        state_file = tmp_path / "camera_state.json"
        with patch.object(bridge_server, "CAMERA_STATE_FILE", str(state_file)):
            started_server.broadcast_camera(camera)
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["fov"] == 45

    def test_broadcast_camera_starts_throttle_timer(self, started_server):
        started_server._throttle_timer.isActive.return_value = False
        with patch.object(BridgeServer, "_write_camera_file"):
            started_server.broadcast_camera({"fov": 45})
        started_server._throttle_timer.start.assert_called_once()

    def test_broadcast_camera_skips_timer_if_active(self, started_server):
        started_server._throttle_timer.isActive.return_value = True
        with patch.object(BridgeServer, "_write_camera_file"):
            started_server.broadcast_camera({"fov": 45})
        started_server._throttle_timer.start.assert_not_called()

    def test_flush_camera_sends_to_clients(self, started_server, mock_client):
        started_server._clients = [mock_client]
        started_server._pending_camera = {"fov": 60}
        started_server._flush_camera()
        sent = mock_client.sendTextMessage.call_args[0][0]
        data = json.loads(sent)
        assert data["type"] == "camera_update"
        assert data["camera"]["fov"] == 60
        assert started_server._pending_camera is None

    def test_flush_camera_noop_when_no_pending(self, started_server, mock_client):
        started_server._clients = [mock_client]
        started_server._pending_camera = None
        started_server._flush_camera()
        mock_client.sendTextMessage.assert_not_called()

    def test_broadcast_aov_sends_to_clients(self, started_server, mock_client):
        started_server._clients = [mock_client]
        started_server.broadcast_aov(
            {"depth": "depth.png", "normal": "normal.png"},
            (800, 600),
        )
        sent = mock_client.sendTextMessage.call_args[0][0]
        data = json.loads(sent)
        assert data["type"] == "aov_update"
        assert data["aovs"]["depth"] == "depth.png"
        assert data["resolution"] == [800, 600]

    def test_broadcast_to_multiple_clients(self, started_server):
        clients = [MagicMock(), MagicMock(), MagicMock()]
        started_server._clients = clients
        started_server._pending_camera = {"fov": 45}
        started_server._flush_camera()
        for c in clients:
            c.sendTextMessage.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------

class TestBridgeErrorHandling:
    def test_send_to_disconnected_client_removes_it(self, started_server):
        bad_client = MagicMock()
        bad_client.sendTextMessage.side_effect = RuntimeError("disconnected")
        started_server._clients = [bad_client]
        started_server._send_to_client(bad_client, {"type": "test"})
        assert bad_client not in started_server._clients

    def test_write_camera_file_oserror_ignored(self, started_server):
        """OSError in file write should not crash."""
        with patch("builtins.open", side_effect=OSError("disk full")):
            BridgeServer._write_camera_file({"fov": 45})
        # No crash = pass


# ---------------------------------------------------------------------------
# Tests: Config integration
# ---------------------------------------------------------------------------

class TestBridgeConfig:
    def test_bridge_ws_port_default(self):
        assert config.BRIDGE_WS_PORT == 8766

    def test_bridge_auto_export_default(self):
        assert config.BRIDGE_AUTO_EXPORT is True

    def test_bridge_throttle_ms(self):
        assert config.BRIDGE_CAMERA_THROTTLE_MS == 100

    def test_camera_state_file(self):
        assert config.CAMERA_STATE_FILE == "camera_state.json"

    def test_bridge_port_override(self, monkeypatch):
        monkeypatch.setenv("BRIDGE_WS_PORT", "9999")
        importlib.reload(config)
        assert config.BRIDGE_WS_PORT == 9999

    def test_bridge_auto_export_override(self, monkeypatch):
        monkeypatch.setenv("BRIDGE_AUTO_EXPORT", "0")
        importlib.reload(config)
        assert config.BRIDGE_AUTO_EXPORT is False
