"""Regression tests for src/viewport.py shader-error handling.

Covers compile_shader and create_shader_program error paths so the fix from
findings ee824bbd (handle leak on compile failure) and 3342813a (missing
GL_LINK_STATUS check) does not regress.

We can't run a real GL context in CI; instead we mock OpenGL.GL and the
Qt imports viewport.py touches at module-level, then call the helpers
directly with the mocks driving compile/link success or failure.
"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _ensure_module(name: str) -> ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and isinstance(existing, ModuleType):
        return existing
    mod = ModuleType(name)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


# --- minimal PySide6 mocks (idempotent with other test modules) -------------

_pyside6 = _ensure_module("PySide6")
_qtcore = _ensure_module("PySide6.QtCore")
_qtgui = _ensure_module("PySide6.QtGui")
_qtnetwork = _ensure_module("PySide6.QtNetwork")
_qtwebsockets = _ensure_module("PySide6.QtWebSockets")
_qtwidgets = _ensure_module("PySide6.QtWidgets")
_qtopengl = _ensure_module("PySide6.QtOpenGLWidgets")
_pyside6.QtCore = _qtcore
_pyside6.QtGui = _qtgui
_pyside6.QtNetwork = _qtnetwork
_pyside6.QtWebSockets = _qtwebsockets
_pyside6.QtWidgets = _qtwidgets
_pyside6.QtOpenGLWidgets = _qtopengl


def _install_getattr(mod: ModuleType) -> None:
    """Auto-supply any attribute as a MagicMock, even if other tests already
    populated some attrs on this module — extra attrs we don't already have
    flow through __getattr__."""
    mod.__getattr__ = lambda name, _m=mod: MagicMock(name=f"{_m.__name__}.{name}")


for mod in (_qtcore, _qtgui, _qtnetwork, _qtwebsockets, _qtwidgets, _qtopengl):
    _install_getattr(mod)


# --- OpenGL.GL mock (auto-supplies any constant/function viewport asks for) -

_opengl = _ensure_module("OpenGL")
_opengl_gl = _ensure_module("OpenGL.GL")
_opengl.GL = _opengl_gl
_install_getattr(_opengl_gl)
_install_getattr(_opengl)


# --- viewport.py is heavy at import time; isolate the helpers ---------------

# We rely on the production module being importable end-to-end with the mocks
# above; the alternative (re-implementing the helpers in the test) would not
# guard against regressions in the actual code.
import viewport  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_gl_mocks():
    """Each test starts with fresh GL function mocks installed on viewport."""
    saved = {}
    for name in (
        "glCreateShader", "glShaderSource", "glCompileShader",
        "glGetShaderiv", "glGetShaderInfoLog", "glDeleteShader",
        "glCreateProgram", "glAttachShader", "glLinkProgram",
        "glDeleteProgram", "glGetProgramiv", "glGetProgramInfoLog",
    ):
        saved[name] = getattr(viewport, name, None)
        setattr(viewport, name, MagicMock(name=name))
    # Default: shaders compile, programs link.
    viewport.glCreateShader.side_effect = lambda kind: 100 + int(kind)
    viewport.glCreateProgram.return_value = 999
    viewport.glGetShaderiv.return_value = True
    viewport.glGetProgramiv.return_value = True
    viewport.glGetShaderInfoLog.return_value = b""
    viewport.glGetProgramInfoLog.return_value = b""
    yield
    for name, val in saved.items():
        if val is None:
            delattr(viewport, name)
        else:
            setattr(viewport, name, val)


def test_compile_shader_happy_path():
    handle = viewport.compile_shader("void main(){}", viewport.GL_VERTEX_SHADER)
    assert isinstance(handle, int)
    viewport.glDeleteShader.assert_not_called()


def test_compile_shader_failure_deletes_handle_and_raises():
    """ee824bbd: handle must be released before raising."""
    viewport.glGetShaderiv.return_value = False
    viewport.glGetShaderInfoLog.return_value = b"syntax error"
    fake_handle = 42
    viewport.glCreateShader.side_effect = lambda kind: fake_handle

    with pytest.raises(RuntimeError, match="Shader compile error"):
        viewport.compile_shader("garbage", viewport.GL_VERTEX_SHADER)

    viewport.glDeleteShader.assert_called_once_with(fake_handle)


def test_create_shader_program_happy_path():
    program = viewport.create_shader_program("vs", "fs")
    assert program == 999
    # Both intermediate shaders should be deleted on success.
    assert viewport.glDeleteShader.call_count == 2
    viewport.glDeleteProgram.assert_not_called()


def test_create_shader_program_link_failure_deletes_program():
    """3342813a: link status must be checked; failure must clean up."""
    viewport.glGetProgramiv.return_value = False
    viewport.glGetProgramInfoLog.return_value = b"link error"

    with pytest.raises(RuntimeError, match="Shader link error"):
        viewport.create_shader_program("vs", "fs")

    viewport.glDeleteProgram.assert_called_once_with(999)


def test_create_shader_program_fragment_compile_failure_deletes_vertex():
    """If fs fails to compile after vs succeeded, vs handle must be released."""
    call_count = {"n": 0}

    def fake_get_iv(_handle, _enum):
        call_count["n"] += 1
        # First call (vs compile) succeeds; second (fs compile) fails.
        return call_count["n"] == 1

    viewport.glGetShaderiv.side_effect = fake_get_iv
    viewport.glGetShaderInfoLog.return_value = b"fs compile error"

    vs_handle = 100 + int(viewport.GL_VERTEX_SHADER)

    with pytest.raises(RuntimeError, match="Shader compile error"):
        viewport.create_shader_program("vs", "broken fs")

    # Both the failed fs and the previously-compiled vs should be deleted.
    deleted = {c.args[0] for c in viewport.glDeleteShader.call_args_list}
    assert vs_handle in deleted
