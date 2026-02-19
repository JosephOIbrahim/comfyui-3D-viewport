"""Tests for src/file_drop.py -- path normalization, format detection.

PySide6.QtCore/QtGui are mocked since no display server is available.
Only the pure-Python utility functions are tested.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock PySide6 before importing file_drop
# ---------------------------------------------------------------------------

_mock_qt_core = types.ModuleType("PySide6.QtCore")
_mock_qt_gui = types.ModuleType("PySide6.QtGui")
_mock_pyside6 = types.ModuleType("PySide6")

_mock_qt_core.QMimeData = MagicMock
_mock_qt_core.Qt = MagicMock
_mock_qt_core.QRectF = MagicMock
_mock_qt_gui.QColor = MagicMock
_mock_qt_gui.QDragEnterEvent = MagicMock
_mock_qt_gui.QDropEvent = MagicMock
_mock_qt_gui.QFont = MagicMock
_mock_qt_gui.QPainter = MagicMock
_mock_qt_gui.QPen = MagicMock

_mock_pyside6.QtCore = _mock_qt_core
_mock_pyside6.QtGui = _mock_qt_gui

sys.modules.setdefault("PySide6", _mock_pyside6)
sys.modules.setdefault("PySide6.QtCore", _mock_qt_core)
sys.modules.setdefault("PySide6.QtGui", _mock_qt_gui)

from file_drop import normalize_path, detect_format, SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------

class TestNormalizePath:
    def test_plain_path(self):
        result = normalize_path("/home/user/model.usd")
        assert "model.usd" in result

    def test_file_url_windows(self):
        result = normalize_path("file:///C:/Users/User/model.usd")
        assert "C:" in result
        assert "model.usd" in result

    def test_file_url_unix(self):
        result = normalize_path("file:///home/user/model.usd")
        assert "model.usd" in result

    def test_percent_encoded(self):
        result = normalize_path("file:///C:/My%20Files/model.usd")
        assert "My Files" in result or "My%20Files" not in result

    def test_strips_whitespace(self):
        result = normalize_path("  /path/to/file.usd  ")
        assert result.strip() == result


# ---------------------------------------------------------------------------
# detect_format
# ---------------------------------------------------------------------------

class TestDetectFormat:
    def test_usd(self):
        assert detect_format("/path/to/scene.usd") == "usd"

    def test_usdc(self):
        assert detect_format("model.usdc") == "usd"

    def test_usda(self):
        assert detect_format("model.usda") == "usd"

    def test_glb(self):
        assert detect_format("model.glb") == "glb"

    def test_gltf(self):
        assert detect_format("model.gltf") == "gltf"

    def test_obj(self):
        assert detect_format("model.obj") == "obj"

    def test_ply(self):
        assert detect_format("model.ply") == "ply"

    def test_unknown(self):
        assert detect_format("model.fbx") == "unknown"


# ---------------------------------------------------------------------------
# SUPPORTED_EXTENSIONS
# ---------------------------------------------------------------------------

class TestSupportedExtensions:
    def test_contains_all(self):
        for ext in [".usd", ".usdc", ".usda", ".glb", ".gltf", ".obj", ".ply"]:
            assert ext in SUPPORTED_EXTENSIONS
