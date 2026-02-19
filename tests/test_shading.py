"""Tests for src/shading.py -- ShadingMode enum, ShadingManager.

OpenGL.GL is mocked since no GL context is available.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock OpenGL.GL before importing shading
# ---------------------------------------------------------------------------

_mock_gl = types.ModuleType("OpenGL.GL")
_mock_opengl = types.ModuleType("OpenGL")

_mock_gl.GL_FILL = 0x1B02
_mock_gl.GL_FRONT_AND_BACK = 0x0408
_mock_gl.GL_LINE = 0x1B01
_mock_gl.GL_POLYGON_OFFSET_LINE = 0x2A02
_mock_gl.glDisable = MagicMock()
_mock_gl.glEnable = MagicMock()
_mock_gl.glPolygonMode = MagicMock()
_mock_gl.glPolygonOffset = MagicMock()

_mock_opengl.GL = _mock_gl

sys.modules.setdefault("OpenGL", _mock_opengl)
sys.modules.setdefault("OpenGL.GL", _mock_gl)

from shading import ShadingMode, ShadingManager


# ---------------------------------------------------------------------------
# ShadingMode
# ---------------------------------------------------------------------------

class TestShadingMode:
    def test_all_modes_exist(self):
        assert ShadingMode.SOLID
        assert ShadingMode.WIREFRAME
        assert ShadingMode.WIREFRAME_ON_SHADED
        assert ShadingMode.UNLIT


# ---------------------------------------------------------------------------
# ShadingManager
# ---------------------------------------------------------------------------

class TestShadingManager:
    def test_default_mode(self):
        mgr = ShadingManager()
        assert mgr.mode == ShadingMode.SOLID
        assert mgr.mode_name == "Solid"

    def test_cycle(self):
        mgr = ShadingManager()
        mode = mgr.cycle()
        assert mode == ShadingMode.WIREFRAME

    def test_cycle_full_loop(self):
        mgr = ShadingManager()
        modes = []
        for _ in range(4):
            modes.append(mgr.cycle())
        assert modes[-1] == ShadingMode.SOLID  # back to start

    def test_needs_second_pass(self):
        mgr = ShadingManager()
        assert not mgr.needs_second_pass
        mgr.set_mode(ShadingMode.WIREFRAME_ON_SHADED)
        assert mgr.needs_second_pass

    def test_unlit_overrides(self):
        mgr = ShadingManager()
        assert mgr.get_unlit_overrides() == {}
        mgr.set_mode(ShadingMode.UNLIT)
        assert mgr.get_unlit_overrides() == {"ambient": 1.0}

    def test_wireframe_color(self):
        mgr = ShadingManager(wireframe_color=(1, 0, 0))
        assert mgr.wireframe_color == (1, 0, 0)
        mgr.wireframe_color = (0, 1, 0)
        assert mgr.wireframe_color == (0, 1, 0)
