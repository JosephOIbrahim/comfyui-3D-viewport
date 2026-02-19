"""Tests for src/hud.py -- HUD toggle, enabled state.

PySide6 is mocked since no display server is available.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock PySide6 before importing hud
# ---------------------------------------------------------------------------

_mock_qt_core = sys.modules.get("PySide6.QtCore")
if _mock_qt_core is None:
    _mock_pyside6 = types.ModuleType("PySide6")
    _mock_qt_core = types.ModuleType("PySide6.QtCore")
    _mock_qt_gui = types.ModuleType("PySide6.QtGui")
    _mock_qt_core.Qt = MagicMock()
    _mock_qt_core.QRectF = MagicMock()
    _mock_qt_gui.QPainter = MagicMock()
    _mock_qt_gui.QFont = MagicMock()
    _mock_qt_gui.QColor = MagicMock()
    _mock_qt_gui.QPen = MagicMock()
    _mock_pyside6.QtCore = _mock_qt_core
    _mock_pyside6.QtGui = _mock_qt_gui
    sys.modules["PySide6"] = _mock_pyside6
    sys.modules["PySide6.QtCore"] = _mock_qt_core
    sys.modules["PySide6.QtGui"] = _mock_qt_gui

from hud import HUD


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------

class TestHUD:
    def test_enabled_by_default(self):
        h = HUD()
        assert h.enabled is True

    def test_toggle(self):
        h = HUD()
        h.toggle()
        assert h.enabled is False
        h.toggle()
        assert h.enabled is True

    def test_toggle_twice_returns_to_original(self):
        h = HUD()
        h.toggle()
        h.toggle()
        assert h.enabled is True
