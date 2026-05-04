# Code Review Report — `/home/user/comfyui-3D-viewport`

- **Run started:** 2026-05-03T23:38:14.759937+00:00
- **Model:** `claude-opus-4-7`
- **Git SHA:** `3505d92033e709c358822979be964b263b4f5df8`
- **Passes completed:** 5 / 5
- **Findings:** 27 accepted · 0 retracted
- **Severity counts:** BLOCKER=0 · HIGH=6 · MEDIUM=10 · LOW=10 · INFO=1
- **Aborted:** False

## Executive Summary
The MOE panel completed 5 pass(es) and produced 27 verified findings, of which **6 are HIGH or BLOCKER**.

**Top concerns:**
- `requirements.txt:1` — *No build backend (no pyproject.toml/setup.py) — repo cannot be installed as a package* (HIGH, SMALL)
- `requirements.txt:1` — *No pyproject.toml/setup.py: project has no build system* (HIGH, SMALL)
- `src/aov_renderer.py:275` — *aov_renderer.py (583 LOC) is entirely untested* (HIGH, MEDIUM)
- `tests/conftest.py:11` — *src/ has no __init__.py; tests bootstrap imports via sys.path.insert* (HIGH, MEDIUM)
- `src/comfy_bridge.py:77` — *comfy_bridge.py has zero tests; network failure paths uncovered* (HIGH, MEDIUM)


## Pass Lifecycle

| Pass | Panel | Raw | Accepted | Retracted | Store size | New | Spent USD |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | architect, build-integrity, concurrency, correctness, graphics-gl, performance, security, testing | 33 | 15 | 18 | 15 | 15 | $9.2598 |
| 2 | concurrency, correctness, graphics-gl, security, testing | 14 | 12 | 2 | 16 | 1 | $13.8994 |
| 3 (blind) | architect, build-integrity, concurrency, correctness, graphics-gl, performance, security, testing | 35 | 11 | 24 | 27 | 11 | $23.8733 |
| 4 | architect, concurrency, correctness, performance, testing | 21 | 15 | 6 | 27 | 0 | $27.7781 |
| 5 | architect, build-integrity, concurrency, correctness, graphics-gl, performance, security, testing | 27 | 27 | 0 | 27 | 0 | $30.4063 |

## Top 10 Findings (by priority)

| # | Severity | Cost | File | Title |
|---|---|---|---|---|
| 1 | HIGH | SMALL | `requirements.txt:1` | No build backend (no pyproject.toml/setup.py) — repo cannot be installed as a package |
| 2 | HIGH | SMALL | `requirements.txt:1` | No pyproject.toml/setup.py: project has no build system |
| 3 | MEDIUM | TRIVIAL | `src/viewport.py:213` | create_shader_program does not check GL_LINK_STATUS |
| 4 | MEDIUM | TRIVIAL | `src/file_drop.py:164` | Minimum Python version not declared in any installable artifact |
| 5 | MEDIUM | TRIVIAL | `src/viewport.py:27` | Python 3.12 requirement only stated in a runtime docstring; no python_requires anywhere |
| 6 | MEDIUM | TRIVIAL | `src/math_utils.py:45` | math_utils 4x4 helpers accept any list[float]; no length or finiteness check |
| 7 | HIGH | MEDIUM | `src/aov_renderer.py:275` | aov_renderer.py (583 LOC) is entirely untested |
| 8 | HIGH | MEDIUM | `tests/conftest.py:11` | src/ has no __init__.py; tests bootstrap imports via sys.path.insert |
| 9 | HIGH | MEDIUM | `src/comfy_bridge.py:77` | comfy_bridge.py has zero tests; network failure paths uncovered |
| 10 | MEDIUM | SMALL | `tests/conftest.py:11` | `src/` is not a Python package; `tests/conftest.py` mutates sys.path to make imports resolve |

## All Accepted Findings


### HIGH (6)

#### `9fdfb0e173c5e154` — No build backend (no pyproject.toml/setup.py) — repo cannot be installed as a package

- **Where:** `requirements.txt:1` · symbol `usd-core` · rule `MISSING_BUILD_BACKEND`
- **Severity:** HIGH (Repo is not installable as a package: no pyproject.toml/setup.py means `pip install -e .` is impossible, no CI gate can reproduce the env, and the test suite is forced into a sys.path hack. This blocks reliable install/test, which is the gate for HIGH per R12 (silent reliability failure on the install path).)
- **Cost:** SMALL · **Confidence:** 0.95 · **Expert:** moe-build-integrity
- **Lifecycle:** 1:build-integrity:NEW → 5:build-integrity:NEW
- **Related:** `c12987ed6500ab98`

The only build artifact in the repo is `requirements.txt`. There is no `pyproject.toml`, no `setup.py`, no `setup.cfg`, no `tox.ini`, and no `.github/workflows/`. Consequences: (1) `pip install -e .` fails — there is nothing to install; (2) downstream callers (including the parent `comfyui-agent`) cannot depend on this repo as a versioned package; (3) CI cannot reproduce a known-good environment because no install entry point exists; (4) the test suite has to mutate `sys.path` at `tests/conftest.py:11-13` instead of relying on import resolution, which means any tooling that doesn't load conftest first (mypy, an external runner, an IDE indexer) will fail to resolve the `src/` modules.

**Evidence:**
```
usd-core>=25.2
PySide6>=6.6
PyOpenGL>=3.1
```

**Proposed change:**
Add a minimal `pyproject.toml` at the repo root using setuptools as the build backend. Concretely:

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "comfyui-3d-viewport"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "usd-core>=25.2,<26",
    "PySide6>=6.6,<7",
    "PyOpenGL>=3.1,<4",
    "numpy>=1.26,<3",
    "trimesh>=4.0,<5",
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

Then the canonical setup becomes `pip install -e .[dev]` (with a `[project.optional-dependencies] dev = ["pytest>=7"]` table) and the conftest sys.path mutation can be deleted. Also add a minimal `.github/workflows/test.yml` that runs `pip install -e .` then `pytest -q` on Python 3.12 so this stays enforced.

**Self-skeptic:**
  - The team may intentionally avoid publishing this as a wheel (it is described as a 'graft' on a parent repo); in that case only the editable-install half of the fix matters and PyPI metadata is overkill.
  - If the parent `comfyui-agent` already vendors this code by path rather than import, packaging here adds little value. I have not verified the parent's import strategy.

---

#### `c12987ed6500ab98` — No pyproject.toml/setup.py: project has no build system

- **Where:** `requirements.txt:1` · symbol `usd-core` · rule `NO_BUILD_SYSTEM_DECLARED`
- **Severity:** HIGH (Without a pyproject.toml / setup.py, the project cannot be installed via pip, cannot be built into a wheel, cannot be editable-installed, and cannot declare its Python version, entry points, or dependencies as part of any standard PEP 517/518 toolchain — blocking CI and release.)
- **Cost:** SMALL · **Confidence:** 0.95 · **Expert:** moe-build-integrity
- **Lifecycle:** 3:build-integrity:NEW → 5:build-integrity:NEW
- **Related:** `9fdfb0e173c5e154`

The repository has only a `requirements.txt` (5 lines, runtime deps) and a `requirements-dev.txt` (test deps). Glob for `{pyproject.toml,setup.py,setup.cfg,tox.ini,Pipfile,poetry.lock,uv.lock}` returns zero matches. Consequence: `pip install .` fails; there is no canonical place to declare `python_requires`, package name, version, or entry points; no `console_scripts` exposed for the viewport launcher; the project cannot be uploaded to PyPI, registered as a dependency of comfyui-agent, or installed in a clean venv via a single command. The current install procedure (per viewport.py:28) is `.venv/Scripts/python src/viewport.py`, which is path-fragile and Windows-specific.

**Evidence:**
```
usd-core>=25.2
PySide6>=6.6
PyOpenGL>=3.1
```

**Proposed change:**
Add a minimal `pyproject.toml` at the repo root:
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "comfyui-3d-viewport"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "usd-core>=25.2",
  "PySide6>=6.6",
  "PyOpenGL>=3.1",
  "numpy>=1.26",
  "trimesh>=4.0",
]

[project.scripts]
comfyui-3d-viewport = "comfyui_3d_viewport.viewport:main"

[tool.setuptools.packages.find]
where = ["src"]
```
Then `pip install -e .` works and conftest.py's sys.path hack can be removed.

**Self-skeptic:**
  - The console_scripts entry assumes a `main()` function in viewport.py; if absent, omit that section
  - Setuptools may need additional config if data files (e.g. data/camera_lens_database.json) need to be included as package data

---

#### `1b52399814e0b597` — aov_renderer.py (583 LOC) is entirely untested

- **Where:** `src/aov_renderer.py:275` · symbol `AOVRenderer` · rule `MISSING_TESTS_FOR_LARGE_MODULE`
- **Severity:** HIGH (R12: 583-LOC module with FBO/shader/PNG-write logic and zero tests touching real behavior is a silent regression risk equivalent to the 'HIGH' example in the constitution.)
- **Cost:** MEDIUM · **Confidence:** 0.95 · **Expert:** moe-testing
- **Lifecycle:** 1:testing:NEW → 2:testing:NEW → 4:testing:NEW → 5:testing:NEW
- **Related:** —

UPHOLD (pass 5): re-verified at SHA 3505d920 — `tests/test_aov_renderer.py` does not exist and no file under `tests/` imports `aov_renderer`. The class definition still anchors at line 275, and the proposed_change from pass 4 remains directly implementable against the current source. No new evidence calls for severity, evidence, or scope change.

**Evidence:**
```
class AOVRenderer:
    """Renders depth and normal AOV passes to an offscreen FBO.
```

**Proposed change:**
Create `tests/test_aov_renderer.py` with the following four test groups (no real GL context required):

1. **`_write_png` round-trip** (no mocks needed):
   ```python
   def test_write_png_roundtrip_rgba_8bit(tmp_path):
       from aov_renderer import _write_png
       import zlib, struct
       # 2x2 RGBA, bottom-up (red, green / blue, white)
       data = bytes([0,0,255,255, 255,255,255,255,   # bottom row
                     255,0,0,255,  0,255,0,255])     # top row
       out = tmp_path / "x.png"
       _write_png(str(out), data, 2, 2, 4, 8)
       raw = out.read_bytes()
       assert raw[:8] == b"\x89PNG\r\n\x1a\n"
       # IHDR width/height
       assert struct.unpack(">II", raw[16:24]) == (2, 2)
       # Decode IDAT, assert top scanline is red/green (Y was flipped)
       ...
   def test_write_png_rejects_bad_channels(tmp_path):
       with pytest.raises(ValueError): _write_png(str(tmp_path/"x.png"), b"", 1, 1, 2, 8)
   def test_write_png_rejects_bad_bit_depth(tmp_path):
       with pytest.raises(ValueError): _write_png(str(tmp_path/"x.png"), b"", 1, 1, 4, 12)
   ```

2. **`_compile_shader` failure path** (use `unittest.mock.patch` on `aov_renderer.glGetShaderiv` etc.):
   ```python
   @patch("aov_renderer.glDeleteShader")
   @patch("aov_renderer.glGetShaderInfoLog", return_value=b"syntax error")
   @patch("aov_renderer.glGetShaderiv", return_value=0)  # GL_FALSE
   @patch("aov_renderer.glCompileShader")
   @patch("aov_renderer.glShaderSource")
   @patch("aov_renderer.glCreateShader", return_value=42)
   def test_compile_shader_raises_on_failure(*_):
       from aov_renderer import _compile_shader
       with pytest.raises(RuntimeError, match="Shader compile error"):
           _compile_shader("bad", 0)
   ```
   Plus a success-path test asserting the returned handle equals the mocked `glCreateShader` value.

3. **`_create_program` link failure** (same pattern, mock `glGetProgramiv` to return 0 and assert `RuntimeError` with `'Shader link error'`).

4. **`AOVRenderer.setup` FBO incomplete** — patch `aov_renderer.glCheckFramebufferStatus` to return a value other than `GL_FRAMEBUFFER_COMPLETE` and assert `setup(800, 600)` raises `RuntimeError` and that `glDeleteFramebuffers` (i.e. `_delete_fbo` cleanup) is called before raising.

Wire `OpenGL.GL` mocks the same way `tests/test_bridge_server.py` already wires PySide6 (use `sys.modules.setdefault('OpenGL', MagicMock())` at the top of the file, before `import aov_renderer`). Target ≥40% line coverage on this file as the milestone.

**Self-skeptic:**
  - A GL-context-required headless test harness might exist that I missed (none found in tests/ or pytest.ini).
  - Some logic may be exercised indirectly when viewport.py is run; that would still not be regression coverage.

---

#### `d40086494a26410a` — src/ has no __init__.py; tests bootstrap imports via sys.path.insert

- **Where:** `tests/conftest.py:11` · symbol `SRC_DIR` · rule `MISSING_PACKAGE_INIT_FILE`
- **Severity:** HIGH (Without src/__init__.py the project is not a package: tests rely on a sys.path hack, third-party tools (mypy, sphinx, editable installs) cannot import the modules, and there is no namespacing for grafting into the parent comfyui-agent — a known design flaw.)
- **Cost:** MEDIUM · **Confidence:** 0.95 · **Expert:** moe-build-integrity
- **Lifecycle:** 3:build-integrity:NEW → 5:build-integrity:NEW
- **Related:** `9ca75b9e2f18c221`

The src/ directory contains 20 modules (viewport.py, math_utils.py, etc.) but no __init__.py, so it is a bare directory rather than a Python package. The conftest.py header explicitly documents the workaround (lines 3-4) and the patch (lines 10-13). Consequences: (1) `pip install` of this project is impossible — there is nothing to install; (2) running tests outside pytest (e.g. `python -m unittest`) will not find the modules; (3) every `from math_utils import ...` is a top-level import that conflicts with any other 'math_utils' on sys.path; (4) IDE tooling, mypy, and pyright cannot resolve cross-module references reliably; (5) the parent comfyui-agent cannot import this code as `from comfyui_3d_viewport.viewport import ...` because no such package exists.

**Evidence:**
```
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
```

**Proposed change:**
Create an empty `src/__init__.py` (or, preferably, restructure to `src/comfyui_3d_viewport/__init__.py` so the package has a proper namespace). Then in `tests/conftest.py`, replace the sys.path hack with a normal package import path (or rely on `pip install -e .` once a build system exists — see the NO_BUILD_SYSTEM_DECLARED finding). Update bare imports across src/*.py to relative imports (`from .math_utils import ...`) or fully qualified (`from comfyui_3d_viewport.math_utils import ...`).

**Self-skeptic:**
  - May break editor configurations or external scripts that hard-code `python src/viewport.py`
  - Renaming to a packaged layout touches every import in src/ — may exceed 300 LOC; if so, a one-line empty src/__init__.py is the smaller fix even if the namespace is generic

---

#### `d97257288dafcd75` — comfy_bridge.py has zero tests; network failure paths uncovered

- **Where:** `src/comfy_bridge.py:77` · symbol `ComfyBridge` · rule `MISSING_TESTS_FOR_NETWORK_LOGIC`
- **Severity:** HIGH (R12: a network bridge whose failure paths (timeouts, broad except, reconnect) are entirely uncovered is a silent-regression / silent-data-loss class. The broad `except Exception` at line 327 already swallows errors; without tests, a real bug there ships without warning.)
- **Cost:** MEDIUM · **Confidence:** 0.95 · **Expert:** moe-testing
- **Lifecycle:** 1:testing:NEW → 2:testing:NEW → 4:testing:NEW → 5:testing:NEW
- **Related:** —

UPHOLD (pass 5): re-verified at SHA 3505d920 — the broad-except still sits at line 327-329, `_post_json` at 335, `_probe` at 351, and no test file imports `comfy_bridge`. The pass-4 drop-in test file outline is fully implementable against the current module. Severity HIGH stands per R12 because the failure-path code is the precise class of code that hides bugs without coverage.

**Evidence:**
```
        except Exception:
            self._set_status(BridgeStatus.ERROR)
            logger.warning("ComfyUI bridge: connection lost")
```

**Proposed change:**
Create `tests/test_comfy_bridge.py` (no live ComfyUI required — only `unittest.mock`). All patches target `comfy_bridge.urllib.request.urlopen` because the module imports it by name (line 60). Concrete test signatures:

```python
import json, threading, time
import urllib.error
from unittest.mock import MagicMock, patch
import pytest
from comfy_bridge import ComfyBridge, BridgeStatus

# --- _probe ---
@pytest.mark.parametrize("exc", [urllib.error.URLError("x"), OSError, TimeoutError])
def test_probe_returns_false_on_network_errors(exc):
    b = ComfyBridge()
    with patch("comfy_bridge.urllib.request.urlopen", side_effect=exc):
        assert b._probe() is False

def test_probe_returns_true_on_http_200():
    resp = MagicMock(); resp.status = 200
    resp.__enter__ = lambda s: s; resp.__exit__ = lambda *a: None
    with patch("comfy_bridge.urllib.request.urlopen", return_value=resp):
        assert ComfyBridge()._probe() is True

# --- _post_json ---
def test_post_json_builds_correct_request():
    captured = {}
    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["hdr"] = req.headers
        m = MagicMock(); m.__enter__ = lambda s: m; m.__exit__ = lambda *a: None
        m.read.return_value = b"{}"
        return m
    with patch("comfy_bridge.urllib.request.urlopen", side_effect=fake_urlopen):
        ComfyBridge(host="h", port=9)._post_json("/api/x", {"k": 1})
    assert captured["url"] == "http://h:9/api/x"
    assert json.loads(captured["data"]) == {"k": 1}
    assert captured["hdr"]["Content-type"] == "application/json"

# --- public send_* return False when worker not running ---
def test_send_camera_returns_false_when_not_connected():
    b = ComfyBridge()  # _running = False
    assert b.send_camera({"a": 1}) is False
    assert b.send_aov("depth", b"png") is False
    assert b.send_viewport_state({"a": 1}, 100, 100) is False

# --- _dispatch error path ---
def test_dispatch_sets_error_status_when_post_raises():
    b = ComfyBridge()
    b._set_status(BridgeStatus.CONNECTED)  # skip the reconnect probe
    with patch.object(b, "_post_json", side_effect=RuntimeError("boom")):
        b._dispatch({"type": "camera_update", "data": {}})
    assert b._status is BridgeStatus.ERROR

# --- disconnect drains worker via None sentinel ---
def test_disconnect_joins_worker_via_sentinel():
    b = ComfyBridge()
    with patch.object(b, "_probe", return_value=True):
        b.connect()
    assert b._running is True
    b.disconnect()
    assert b._running is False
    assert b._worker is None
    assert b._status is BridgeStatus.DISCONNECTED

# --- reconnect path in _dispatch ---
def test_dispatch_reconnects_when_disconnected():
    b = ComfyBridge()
    with patch.object(b, "_probe", return_value=True), \
         patch.object(b, "_post_json") as post:
        b._dispatch({"type": "camera_update", "data": {}})
    post.assert_called_once()
    assert b._status is BridgeStatus.CONNECTED
```

This covers `_probe` (3 error types + happy path), `_post_json` URL/body/header construction, the three public send methods' `_running=False` short-circuit, `_dispatch` reconnect + error transitions, and `disconnect` worker-shutdown contract. Target ≥75% line coverage on this module.

**Self-skeptic:**
  - The broad-except itself is a correctness concern owned by another expert; my finding is the test-gap, not the except.
  - A future integration test bound to a real ComfyUI may exist out of repo, but that would not protect contributors locally.

---

#### `bbbb5d889e700cc1` — viewport.py (1085 LOC, StormViewport+MainWindow) has zero tests

- **Where:** `src/viewport.py:223` · symbol `StormViewport` · rule `MISSING_TESTS_FOR_LARGE_MODULE`
- **Severity:** HIGH (R12: the largest module in the codebase (1085 LOC), containing the central QOpenGLWidget, draw-list management, and event handling, has zero tests. This is a silent-regression risk far larger than aov_renderer.)
- **Cost:** LARGE · **Confidence:** 0.95 · **Expert:** moe-testing
- **Lifecycle:** 1:testing:NEW → 2:testing:NEW → 4:testing:NEW → 5:testing:NEW
- **Related:** —

UPHOLD (pass 5): re-verified at SHA 3505d920 — no test file imports `viewport`. `StormViewport` still defined at line 223. The two-step plan (extract Qt/GL fixture into conftest.py, add `tests/test_viewport.py` for the pure-Python shader helpers and event-routing branches) is unchanged in applicability. Severity HIGH stands per R12.

**Evidence:**
```
class StormViewport(QOpenGLWidget):
```

**Proposed change:**
Two-step plan:

**Step 1 — extract Qt/GL mock fixture into `tests/conftest.py`.** Today the PySide6 mock hierarchy lives at the top of `tests/test_bridge_server.py` (lines 13-90) and is re-built ad-hoc in other test files. Move it into a session-scoped autouse fixture in `conftest.py` and add `OpenGL.GL` to the mocked-module list so any test importing `viewport` works without a GL context. Concrete fixture:
```python
@pytest.fixture(scope="session", autouse=True)
def _mock_qt_and_gl():
    for name in ("PySide6", "PySide6.QtCore", "PySide6.QtGui",
                 "PySide6.QtWidgets", "PySide6.QtOpenGLWidgets",
                 "PySide6.QtNetwork", "PySide6.QtWebSockets",
                 "OpenGL", "OpenGL.GL"):
        sys.modules.setdefault(name, ModuleType(name))
    # ...wire submodule attrs as test_bridge_server already does...
```

**Step 2 — create `tests/test_viewport.py`** with at minimum:
```python
@patch("viewport.glDeleteShader")
@patch("viewport.glGetShaderInfoLog", return_value=b"oops")
@patch("viewport.glGetShaderiv", return_value=0)
@patch("viewport.glCompileShader")
@patch("viewport.glShaderSource")
@patch("viewport.glCreateShader", return_value=7)
def test_compile_shader_raises_on_compile_failure(*_):
    from viewport import compile_shader
    with pytest.raises(RuntimeError, match="Shader compile error"):
        compile_shader("x", 0)

def test_compile_shader_returns_handle_on_success(...):
    # mirror with glGetShaderiv -> 1

def test_create_shader_program_links_and_returns_program(...):
    # patch glCreateProgram -> 11; assert returned == 11
    # assert glAttachShader called twice, glLinkProgram called once,
    # glDeleteShader called for both vs/fs handles
```
Additionally, instantiate `StormViewport(stage=MagicMock())` and unit-test the pure-Python branches of any keyPressEvent/mousePressEvent that route on `event.key()`/`event.button()` — pass `MagicMock()` events with the appropriate return values and assert the documented side effect on the camera/draw list. Aim for ≥30% line coverage on `viewport.py` as the first milestone.

**Self-skeptic:**
  - Some viewport logic genuinely cannot be unit-tested without a GL context; the proposal targets the parts that can.
  - Cost is LARGE because of the module size, not because each test is hard.

---


### MEDIUM (10)

#### `3342813affab7e7d` — create_shader_program does not check GL_LINK_STATUS

- **Where:** `src/viewport.py:213` · symbol `create_shader_program` · rule `MISSING_LINK_STATUS_CHECK`
- **Severity:** MEDIUM (User-visible defect: a silent link failure produces a non-functional program handle that paintGL then binds, yielding an invisible scene with no diagnostic — exactly the kind of bug R12 MEDIUM covers.)
- **Cost:** TRIVIAL · **Confidence:** 0.98 · **Expert:** moe-graphics-gl
- **Lifecycle:** 3:graphics-gl:NEW → 5:graphics-gl:UPHOLD
- **Related:** —

viewport.py:207-216 links the main scene shader program but never queries GL_LINK_STATUS or glGetProgramInfoLog; on link failure the function returns a program handle that will be silently bound by paintGL with no error surfaced to the user. This is inconsistent with the codebase's own convention — grid.py:_link_program (grid.py:100-118), environment.py:_link_program (environment.py:201-213), and aov_renderer.py:_create_program (aov_renderer.py:251-268) all check GL_LINK_STATUS, log the info log, and raise. The same function also fails to call glDetachShader before glDeleteShader; while glDeleteShader on attached shaders only flags-for-deletion (so this is harmless once link succeeds), the link-status omission is a correctness bug.

**Evidence:**
```
    glLinkProgram(program)
    glDeleteShader(vs)
    glDeleteShader(fs)
```

**Proposed change:**
After glLinkProgram(program) at viewport.py:213, add: `if not glGetProgramiv(program, GL_LINK_STATUS): info = glGetProgramInfoLog(program).decode('utf-8', errors='replace'); glDeleteProgram(program); glDeleteShader(vs); glDeleteShader(fs); raise RuntimeError(f'Shader program link error: {info}')`. Import GL_LINK_STATUS, glGetProgramiv, glGetProgramInfoLog, glDeleteProgram from OpenGL.GL (some are already imported). This matches the pattern already used in grid.py:_link_program.

**Self-skeptic:**
  - Link failures are rare with hand-authored shaders that already compile, so in practice this may never trigger on the dev machine.
  - If a future shader refactor adds runtime-generated shaders, this becomes more important; for the current static shaders the impact is mostly diagnostic.

---

#### `539d649d6e5805fa` — Minimum Python version not declared in any installable artifact

- **Where:** `src/file_drop.py:164` · symbol `validate_drop` · rule `MISSING_PYTHON_VERSION_DECLARATION`
- **Severity:** MEDIUM (User-visible defect per R12: a user installs on Python 3.9, `pip install -r requirements.txt` succeeds, then `python src/viewport.py` crashes with `TypeError: unsupported operand type(s) for |: 'type' and 'type'` at import time. The required interpreter is mentioned only in a docstring (`src/viewport.py:27`), nowhere machine-readable.)
- **Cost:** TRIVIAL · **Confidence:** 0.95 · **Expert:** moe-build-integrity
- **Lifecycle:** 1:build-integrity:NEW → 5:build-integrity:NEW
- **Related:** `8a3cb3b1a6fdf35c`

The project uses PEP 604 union syntax (`X | None`, `A | B`) at `src/file_drop.py:164` and at least seven other files (per grep: `mesh_importers.py`, `projection.py`, `selection.py`, `usd_loader.py`, `bridge_server.py`, `camera.py`, `animation.py`). PEP 604 requires Python 3.10+. The README/docstring at `src/viewport.py:27` says "Requires Python 3.12 venv", but that is a free-text docstring — `pip` cannot read it, and there is no `requires-python` (no `pyproject.toml`), no `python_requires` (no `setup.py`), no `python` field in `pytest.ini`, and no `.python-version` file. A 3.9 user gets a clean install followed by an import-time crash.

**Evidence:**
```
    def validate_drop(event: QDragEnterEvent | QDropEvent) -> str | None:
```

**Proposed change:**
When the new `pyproject.toml` is added (per the missing-build-backend finding), include `requires-python = ">=3.12"` in the `[project]` table so `pip` refuses to install on older interpreters. Additionally commit a `.python-version` file containing `3.12` for pyenv users, and add a one-line guard at the top of `src/viewport.py` (`if sys.version_info < (3, 12): raise RuntimeError(...)`) so `python src/viewport.py` on a 3.9 venv fails with a readable message instead of a SyntaxError-on-import from one of the dependencies.

**Self-skeptic:**
  - The team's stated 3.12 floor may be aspirational — the actual hard requirement appears to be 3.10 (PEP 604). If a 3.10/3.11 user is acceptable, `requires-python = '>=3.10'` is the safer floor.
  - The `sys.version_info` runtime guard runs after Python parses the file, so SyntaxError-only features (e.g., `type X = ...` PEP 695, 3.12-only) would still fail before the guard runs. I haven't grepped for PEP 695 syntax, so the guard may not catch every case.

---

#### `8a3cb3b1a6fdf35c` — Python 3.12 requirement only stated in a runtime docstring; no python_requires anywhere

- **Where:** `src/viewport.py:27` · symbol `viewport` · rule `NO_PYTHON_VERSION_PIN`
- **Severity:** MEDIUM (User-visible defect: the only declaration of the Python version requirement is buried in a runtime docstring; pip / package managers cannot enforce it, so users on 3.10/3.11 will get late-binding import or syntax errors.)
- **Cost:** TRIVIAL · **Confidence:** 0.90 · **Expert:** moe-build-integrity
- **Lifecycle:** 3:build-integrity:NEW → 5:build-integrity:NEW
- **Related:** `539d649d6e5805fa`

The minimum Python version (3.12) appears once in the entire repo: in viewport.py's module docstring at line 27. There is no `python_requires` in any setup.py / pyproject.toml (because none exist — see NO_BUILD_SYSTEM_DECLARED), no `requires-python` in any metadata, no classifier, no check at runtime. Meanwhile the codebase uses 3.10+ syntax extensively: `X | None` PEP 604 unions appear in 10 src/ modules (mesh_importers.py, projection.py, selection.py, usd_loader.py, bridge_server.py, camera.py, comfy_bridge.py, file_drop.py, math_utils.py, animation.py). A user on Python 3.9 gets `TypeError: unsupported operand type(s) for |` at import time with no helpful diagnostic. The CLAUDE.md/EXECUTION_SPEC docs do not declare a min version either.

**Evidence:**
```
Requires Python 3.12 venv with: usd-core, PySide6, PyOpenGL, numpy, trimesh
    .venv/Scripts/python src/viewport.py
```

**Proposed change:**
Declare `requires-python = ">=3.12"` in pyproject.toml's `[project]` table (see NO_BUILD_SYSTEM_DECLARED finding). As a defensive belt-and-suspenders check, add at the top of viewport.py before any 3.10+ syntax is hit:
```python
import sys
if sys.version_info < (3, 12):
    raise RuntimeError(f"comfyui-3d-viewport requires Python >=3.12, got {sys.version}")
```
Move this check to a `comfyui_3d_viewport/__init__.py` once the package layout is fixed.

**Self-skeptic:**
  - 3.10 union syntax actually only requires Python 3.10, not 3.12 — the true minimum may be 3.10; verify whether any genuinely 3.12-only feature (PEP 695 generics, etc.) is in use before pinning >=3.12
  - If type hints are only used as annotations and `from __future__ import annotations` is added, the union syntax becomes string-only and 3.9 may suffice — but no module currently uses that future import

---

#### `61e3e9f6c1e495ed` — math_utils 4x4 helpers accept any list[float]; no length or finiteness check

- **Where:** `src/math_utils.py:45` · symbol `mat4_multiply` · rule `MISSING_INPUT_VALIDATION_AT_BOUNDARY`
- **Severity:** MEDIUM (User-visible defect with high blast radius: math_utils is used by viewport, selection, environment, usd_loader, and mesh_importers. A non-16 list silently goes off the end via `a[k * 4 + row]` (IndexError) with no informative message, or - worse - returns a wrong-shaped result if a 16-tuple is passed but treated as a column-major matrix in the wrong layout.)
- **Cost:** TRIVIAL · **Confidence:** 0.85 · **Expert:** moe-correctness
- **Lifecycle:** 1:correctness:NEW → 2:correctness:UPHOLD → 1:correctness:NEW → 2:correctness:UPHOLD → 4:correctness:REFINE → 5:correctness:NEW
- **Related:** —

R13 parent finding: every public 4x4 helper in math_utils.py declares `list[float]` but does not assert `len(m) == 16`. The functions affected are:
 - mat4_multiply (line 45): if `a` or `b` is shorter than 16 the inner loop raises IndexError far from the call site.
 - mat4_inverse (line 57): same shape assumption.
 - mat4_transform_point (line 163): same.
 - look_at (line 180): assumes `eye/target/up` are length 3 with a `_` index access.

Because these functions are used at boundaries (USD GfMatrix conversion, picking _unproject, environment HDRI inverse-VP) a malformed input gives a backtrace deep inside math_utils with no clue about which caller sent the bad data. The selection module uses `_mat4_inverse(vp)` on a result of `_mat4_mul(proj, view)` - if either matrix is built from caller

**Evidence:**
```
def mat4_multiply(a: list[float], b: list[float]) -> list[float]:
    """Multiply two column-major 4x4 matrices: result = A * B."""
    result = [0.0] * 16
```

**Proposed change:**
Add the validators at the top of src/math_utils.py (after the imports, before `vec3_normalize` at line 23):

```python
def _check_mat4(m: list[float], name: str) -> None:
    if len(m) != 16:
        raise ValueError(
            f"{name} must be a 16-element column-major matrix, got {len(m)}"
        )

def _check_vec3(v: tuple, name: str) -> None:
    if len(v) != 3:
        raise ValueError(f"{name} must be a 3-element vector, got {len(v)}")
```

Then wire them in at five concrete call sites (no other lines change):

- line 47, first stmt of `mat4_multiply`:
  `_check_mat4(a, 'a'); _check_mat4(b, 'b')`
- line 62, first stmt of `mat4_inverse` (before the inner `def a(...)`):
  `_check_mat4(m, 'm')`
- `mat4_inverse_safe` at line 121: no change needed; it delegates to `mat4_inverse`.
- line 170, first stmt of `mat4_transform_point`:
  `_check_mat4(m, 'm')`
- line 192, first stmt of `look_at` (before `f = normalize(...)`):
  `_check_vec3(eye, 'eye'); _check_vec3(target, 'target'); _check_vec3(up, 'up')`

Add to tests/test_math_utils.py:
```python
import pytest
@pytest.mark.parametrize('bad', [[], [1.0]*15, [1.0]*17])
def test_mat4_multiply_rejects_wrong_length(bad):
    with pytest.raises(ValueError, match='16-element'):
        mat4_multiply(bad, [0.0]*16)

def test_look_at_rejects_short_vector():
    with pytest.raises(ValueError, match='3-element'):
        look_at((0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
```

Do NOT add finiteness (`math.isfinite`) checks here — the cost is per-element scan and the existing pipeline does not produce non-finite values from finite USD/numpy inputs. Length-only is the right scope.

**Self-skeptic:**
  - Hot-path picking calls these per click only, not per frame, so cost is fine. But mat4_multiply is called per-frame in environment._draw_hdri - the per-call len() check is still negligible.
  - Tests in test_math_utils.py may need updates to cover the new ValueError paths.

---

#### `9ca75b9e2f18c221` — `src/` is not a Python package; `tests/conftest.py` mutates sys.path to make imports resolve

- **Where:** `tests/conftest.py:11` · symbol `SRC_DIR` · rule `MISSING_PACKAGE_LAYOUT_SYS_PATH_HACK`
- **Severity:** MEDIUM (Design flaw per R12: imports work in pytest only because conftest.py runs first. Any tool that doesn't load conftest (mypy on tests/, an external script, an IDE indexer rooted elsewhere, `python -m`) cannot resolve the modules. The blast radius is brittleness, not data loss, so MEDIUM not HIGH.)
- **Cost:** SMALL · **Confidence:** 0.95 · **Expert:** moe-build-integrity
- **Lifecycle:** 1:build-integrity:NEW → 5:build-integrity:NEW
- **Related:** `d40086494a26410a`

`src/` has no `__init__.py`, so the ~20 modules inside (`viewport.py`, `comfy_bridge.py`, `bridge_server.py`, `camera.py`, ...) are imported as top-level names — e.g., `from camera import OrbitCamera` at `src/viewport.py:101`. To make those bare imports resolve under pytest, `tests/conftest.py` inserts `src/` at the front of `sys.path` at module load. Symptoms: (1) running a script outside pytest from another directory cannot import these modules without replicating the hack; (2) static analyzers that don't execute conftest (mypy, pyright, ruff in some configs) can't follow imports; (3) two siblings under `src/` collide with any other top-level package of the same name (`grid`, `selection`, `lighting`, `shading` are common names); (4) it locks out `pip install -e .` because there is no pac

**Evidence:**
```
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
```

**Proposed change:**
Adopt the standard src-layout with a build backend (see the missing-build-backend finding). The minimal path that preserves existing import statements: add `pyproject.toml` with `[tool.setuptools] package-dir = {"" = "src"}` and `[tool.setuptools.packages.find] where = ["src"]`, then `touch src/__init__.py` is NOT needed — setuptools' src-layout discovery treats each `.py` under `src/` as a top-level module. After `pip install -e .`, delete lines 10-13 of `tests/conftest.py`. If you'd rather have a real namespace, move modules into `src/comfyui_3d_viewport/` and rewrite the ~20 import lines in `src/viewport.py` (a one-shot sed). The first option is the smaller change and is recommended.

**Self-skeptic:**
  - The flat-modules-under-src layout is unconventional — most projects nest a package directory. Some setuptools versions treat top-level `.py` files under `src/` as modules without explicit config; if that's not the case for the project's pinned setuptools, the proposed change won't work as stated and option (b) (real package directory + import rewrite) is required.
  - If the team intends to keep modules importable as bare names (e.g., `import camera`) for short-name convenience inside the repo, they may resist the rename. The minimal-config pyproject.toml above accommodates that, but it leaves the namespace-collision risk in place.

---

#### `e42958d62ec28bb1` — Fragment shader hardcodes lighting constants that already exist in config.py

- **Where:** `src/viewport.py:182` · symbol `FRAGMENT_SHADER` · rule `MAGIC_NUMBER_DUPLICATES_CONFIG`
- **Severity:** MEDIUM (User-visible defect / design flaw: config.py defines SPECULAR_POWER, SPECULAR_STRENGTH, AMBIENT_MIN, DIFFUSE_FACTOR (lines 57-60), but the fragment shader hardcodes the same values. Tweaking config does nothing - a maintainer changing SPECULAR_STRENGTH would expect the viewport to follow.)
- **Cost:** SMALL · **Confidence:** 0.95 · **Expert:** moe-correctness
- **Lifecycle:** 1:correctness:NEW → 2:correctness:UPHOLD → 1:correctness:NEW → 2:correctness:UPHOLD → 4:correctness:REFINE → 5:correctness:NEW
- **Related:** `95d4ffec6b8000f1`

R13 parent finding: viewport.py duplicates several values that have authoritative names in config.py:

  - shader literal `32.0` at line 182 == config.SPECULAR_POWER
  - shader literal `0.3` at line 182 == config.SPECULAR_STRENGTH
  - shader literal `0.15` at line 166 == config.AMBIENT_MIN
  - shader literal `0.75` at line 187 == config.DIFFUSE_FACTOR
  - `OrbitCamera(target=(0.0, 0.3, 0.0), distance=5.0, azimuth=35.0, elevation=25.0,)` at lines 247-252 duplicate config.CAMERA_DEFAULT_TARGET / DISTANCE / AZIMUTH / ELEVATION.
  - `CameraAnimator(fps=24.0)` at line 268 duplicates config.ANIMATION_FPS.
  - `AOVExporter(self._bridge, export_interval=0.5)` at line 273 duplicates config.AOV_EXPORT_INTERVAL.
  - `self._anim_timer.setInterval(16)` at line 307 duplicates config.ANIM_TIMER_INTERVAL.

**Evidence:**
```
            float spec = pow(max(dot(norm, halfDir), 0.0), 32.0) * 0.3;
            specular_accum += uLightColors[i] * spec;
```

**Proposed change:**
Concrete two-stage patch. Stage A (config-defaults wiring, ~7 line edits — TRIVIAL); Stage B (shader uniforms, ~12 line edits — SMALL). Do them in one PR.

Stage A — replace literals with config constants in src/viewport.py:

1) Add at top of file: `from src import config` (or extend the existing relative import block).
2) Lines 247-252, OrbitCamera defaults:
```python
        self._camera = OrbitCamera(
            target=config.CAMERA_DEFAULT_TARGET,
            distance=config.CAMERA_DEFAULT_DISTANCE,
            azimuth=config.CAMERA_DEFAULT_AZIMUTH,
            elevation=config.CAMERA_DEFAULT_ELEVATION,
        )
```
3) Line 268: `self._animator = CameraAnimator(fps=config.ANIMATION_FPS)`
4) Line 273: `self._aov_exporter = AOVExporter(self._bridge, export_interval=config.AOV_EXPORT_INTERVAL)`
5) Line 307: `self._anim_timer.setInterval(config.ANIM_TIMER_INTERVAL)`
6) Line 1026: `self.resize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)`
7) Line 1050: `fmt.setSamples(config.MSAA_SAMPLES)`

Stage B — wire shader constants as uniforms (preferred over .format() because it lets the HUD show live values later):

1) In FRAGMENT_SHADER at line 144, add four uniform declarations after `uniform float uAmbientOverride;`:
```glsl
uniform float uAmbientMin;
uniform float uSpecPower;
uniform float uSpecStrength;
uniform float uDiffuseFactor;
```
2) Replace line 166: `float ambient = max(uAmbientMin, uAmbientOverride);`
3) Replace line 182: `float spec = pow(max(dot(norm, halfDir), 0.0), uSpecPower) * uSpecStrength;`
4) Replace line 187: `vec3 result = uBaseColor * (ambient + diffuse_accum * uDiffuseFactor) + specular_accum;`
5) In the `uniform_names` list at viewport.py:319-322, append the four new names:
```python
            uniform_names = [
                "uProjection", "uView", "uModel", "uBaseColor",
                "uViewPos", "uAmbientOverride", "uLightCount",
                "uAmbientMin", "uSpecPower", "uSpecStrength", "uDiffuseFactor",
            ]
```
6) In `paintGL`, immediately after `glUseProgram(self._program)`, set the four constants once per frame (or once in initializeGL after the program is created — uniforms persist on the program):
```python
        glUniform1f(self._uniform_locs["uAmbientMin"], config.AMBIENT_MIN)
        glUniform1f(self._uniform_locs["uSpecPower"], config.SPECULAR_POWER)
        glUniform1f(self._uniform_locs["uSpecStrength"], config.SPECULAR_STRENGTH)
        glUniform1f(self._uniform_locs["uDiffuseFactor"], config.DIFFUSE_FACTOR)
```

Verification: change `SPECULAR_STRENGTH` in config.py from 0.3 to 0.0 and confirm specular highlights disappear in the viewport — currently they do not change.

**Self-skeptic:**
  - Some shader values (32.0 specular power) are intentionally hardcoded for performance - swapping to a uniform adds a tiny per-frame cost. But the dynamic-uniform pattern is already used for uViewPos/uAmbientOverride in this same shader, so consistency wins.

---

#### `3a28675cc8f11d8c` — look_at silently produces a NaN/zero view matrix on degenerate inputs

- **Where:** `src/math_utils.py:180` · symbol `look_at` · rule `MATH_EDGE_CASE_DEGENERATE`
- **Severity:** MEDIUM (User-visible defect: when target == eye (e.g. F-key pressed before scene loads, or distance clamped to 0) `normalize()` falls through with `l > 0` false but l != exactly 0 case handled, however when up is parallel to forward, `cross(f, up)` returns the zero vector and the inner `normalize` returns it unchanged because `l > 0` is false but no fallback runs.)
- **Cost:** SMALL · **Confidence:** 0.90 · **Expert:** moe-correctness
- **Lifecycle:** 3:correctness:NEW → 4:correctness:REFINE → 5:correctness:NEW
- **Related:** —

Three issues in look_at: (1) inner `normalize` returns `v` unchanged when `l == 0`, propagating a zero vector instead of falling back; (2) `if l > 0` admits subnormals like 1e-300 that then explode in division; (3) when world `up` is parallel to forward (look straight up/down with Y-up), `cross(f, up)` is exactly zero and the right vector becomes zero. Compare to the documented contract of `vec3_normalize` at line 23 which falls back to `(0,1,0)`. The viewport already uses `look_at` from `paintGL` and `mouseReleaseEvent`, so a single bad camera state corrupts every frame until reset. Pass 5 verification: source at lines 184-186 confirms `return (v[0]/l, v[1]/l, v[2]/l) if l > 0 else v` — bug stands.

**Evidence:**
```
    def normalize(v):
        l = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
        return (v[0]/l, v[1]/l, v[2]/l) if l > 0 else v
```

**Proposed change:**
Replace lines 184-201 of math_utils.py with the following concrete patch:

```python
def look_at(eye: tuple, target: tuple, up: tuple) -> list[float]:
    """Build a look-at view matrix (column-major for GL)."""
    EPS = 1e-8
    def sub(a, b):
        return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
    def length(v):
        return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
    def normalize(v, fallback=(0.0, 0.0, -1.0)):
        l = length(v)
        if l < EPS:
            return fallback
        return (v[0]/l, v[1]/l, v[2]/l)
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def dot(a, b):
        return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

    # (1) Forward: fall back to -Z if eye == target.
    f = normalize(sub(target, eye), fallback=(0.0, 0.0, -1.0))
    # (2) Right: if up is parallel to forward, retry with world Z.
    s_raw = cross(f, up)
    if length(s_raw) < EPS:
        s_raw = cross(f, (0.0, 0.0, 1.0))
        if length(s_raw) < EPS:
            s_raw = cross(f, (1.0, 0.0, 0.0))
    s = normalize(s_raw, fallback=(1.0, 0.0, 0.0))
    u = cross(s, f)

    return [
        s[0], u[0], -f[0], 0,
        s[1], u[1], -f[1], 0,
        s[2], u[2], -f[2], 0,
        -dot(s, eye), -dot(u, eye), dot(f, eye), 1,
    ]
```

Add two unit tests to tests/test_math_utils.py:
```python
def test_look_at_eye_equals_target_does_not_nan():
    m = look_at((1.0, 2.0, 3.0), (1.0, 2.0, 3.0), (0.0, 1.0, 0.0))
    assert all(math.isfinite(v) for v in m)

def test_look_at_up_parallel_to_forward():
    m = look_at((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0))
    assert all(math.isfinite(v) for v in m)
```

**Self-skeptic:**
  - camera.py clamps elevation to +/-89, so the 'forward parallel to up' case may be unreachable in practice
  - callers may already check for degenerate state before calling

---

#### `adc798205979f67f` — mat4_transform_point silently returns un-divided homogeneous coords on near-zero w

- **Where:** `src/math_utils.py:175` · symbol `mat4_transform_point` · rule `SILENT_DEGENERATE_FALLBACK`
- **Severity:** MEDIUM (User-visible defect: when `rw ~ 0` the function returns the un-divided homogeneous coords as if they were Euclidean. This is silently wrong rather than recoverable - the picking _unproject in selection.py uses this result directly to build a ray, so a near-degenerate inverse-VP produces a bogus ray with no warning.)
- **Cost:** SMALL · **Confidence:** 0.80 · **Expert:** moe-correctness
- **Lifecycle:** 1:correctness:NEW → 2:correctness:UPHOLD → 1:correctness:NEW → 2:correctness:UPHOLD → 4:correctness:REFINE → 5:correctness:NEW
- **Related:** —

When `abs(rw) < 1e-14`, the function returns `(rx, ry, rz)` directly. Those values are NOT in the same coordinate space as the divided result - they are pre-perspective-divide homogeneous values - so callers that treat the return as a world-space point (selection._unproject does exactly this at line 243-244) silently produce garbage. The correct behaviour is either to raise (consistent with mat4_inverse's ValueError on singular) or to return None and have callers handle it; mixing 'normal point' and 'unprojected homogeneous' in the same return type is the worst of both worlds.

selection._unproject at line 252 has its own degenerate-direction guard (`length < 1e-12`) that masks part of this, but the origin point still gets the bogus value through. Pass 5 verification: confirmed at lines 17

**Evidence:**
```
    if abs(rw) < 1e-14:
        return (rx, ry, rz)
    return (rx / rw, ry / rw, rz / rw)
```

**Proposed change:**
Choose option (a) — raise — to match the existing convention at `mat4_inverse` (line 80–81 raises ValueError on singular matrix). Two concrete edits:

1) Replace lines 175-177 of src/math_utils.py:
```python
    if abs(rw) < 1e-14:
        raise ValueError(
            'mat4_transform_point: w-component is zero; '
            'point lies on the camera plane / matrix is singular'
        )
    return (rx / rw, ry / rw, rz / rw)
```

2) Update the picking caller at src/selection.py:240-244 to swallow this case the same way it handles the existing degenerate-direction case at line 251 (return early with a neutral ray):
```python
    try:
        near_pt = _mat4_transform_point(inv_vp, ndc_x, ndc_y, -1.0)
        far_pt = _mat4_transform_point(inv_vp, ndc_x, ndc_y, 1.0)
    except ValueError:
        return (0.0, 0.0, 0.0), (0.0, 0.0, -1.0)
```

3) Add a unit test in tests/test_math_utils.py:
```python
def test_mat4_transform_point_raises_on_zero_w():
    # Matrix that makes (0, 0, 0, 1) -> (x, y, z, 0): bottom row all zero.
    m = [1.0, 0.0, 0.0, 0.0,
         0.0, 1.0, 0.0, 0.0,
         0.0, 0.0, 1.0, 0.0,
         0.0, 0.0, 0.0, 0.0]
    with pytest.raises(ValueError, match='w-component'):
        mat4_transform_point(m, 1.0, 2.0, 3.0)
```

Do NOT silently substitute a default point — that is exactly the bug being fixed. Raising is preferred over `return None` because the type signature stays `tuple[float, float, float]` and existing callers (USD GfMatrix conversions, environment HDRI) will get a clear backtrace pointing at the bad inverse-VP.

**Self-skeptic:**
  - Some callers may today rely on the silent fallback because the vp matrix is rarely degenerate; raising could trip code paths that have not been seen in practice.
  - Picking degenerate cases may already be screened upstream by camera clamps - empirical impact may be low.

---

#### `d8fb2490ff3be120` — Multiple src/ modules have no corresponding test_*.py (R13 grouped)

- **Where:** `src/environment.py:228` · symbol `EnvironmentMap` · rule `MISSING_TESTS_FOR_MODULE`
- **Severity:** MEDIUM (R12: user-visible defect class — a refactor in any of these modules ships without coverage. Picked MEDIUM (not HIGH) because each individual module is smaller / simpler than aov_renderer, viewport, or comfy_bridge, and parts may be exercised indirectly.)
- **Cost:** LARGE · **Confidence:** 0.90 · **Expert:** moe-testing
- **Lifecycle:** 1:testing:NEW → 2:testing:NEW → 4:testing:NEW → 5:testing:NEW
- **Related:** `bbbb5d889e700cc1`

UPHOLD (pass 5): re-verified at SHA 3505d920 — `aov_export.py`, `environment.py`, `grid.py`, and `stage_builder.py` still have no `tests/test_<name>.py`, and a Grep across `tests/` shows no test imports any of them. `EnvironmentMap` still anchors at line 228. Prioritised task list from pass 4 remains directly actionable.

**Evidence:**
```
class EnvironmentMap:
```

**Proposed change:**
Create one focused test file per orphan, in this order (highest pure-Python ratio first, so payoff/effort is best):

1. **`tests/test_stage_builder.py`** (97 LOC, ~1 hr): instantiate the public stage-builder entry, assert returned USD stage has the expected root prim path and units. Target 80% coverage.

2. **`tests/test_grid.py`** (299 LOC, ~3 hr): unit-test the grid-line generation math — assert vertex count = `2*(2N+1)` for an `NxN` grid, assert axis-aligned line endpoints at the expected world-space coordinates for at least 3 grid scales (1, 10, 100), and assert snap thresholds round to the nearest grid cell. Mock `OpenGL.GL` only for the upload-to-GPU path. Target 60% coverage.

3. **`tests/test_aov_export.py`** (406 LOC, ~3 hr): unit-test path-naming helpers (frame padding, format detection from extension, output directory creation under `tmp_path`). The GL-touching paths can wait for a follow-up. Target 50% coverage.

4. **`tests/test_environment.py`** (611 LOC, ~6 hr): instantiate `EnvironmentMap` with `MagicMock()` GL, test state transitions (load → unload → reload), and exercise the shader-compile error path with the same `@patch('environment.glGetShaderiv', return_value=0)` pattern recommended for `aov_renderer`. Target 30% coverage.

All four can reuse the session-scoped Qt/GL mock fixture extracted into `conftest.py` per the related viewport finding (related_findings = bbbb5d889e700cc1). File a tracking issue and tackle in the order above; each is independent so they can be parallelised across contributors.

**Self-skeptic:**
  - Some modules may be trivial wrappers around well-tested third-party libs; that does not eliminate the need for at least a smoke test.
  - Coverage targets are arbitrary; the point is non-zero coverage of the public API.

---

#### `0bd711ea0adcd35b` — StormViewport conflates rendering, input, file I/O, networking, animation, and AOV export

- **Where:** `src/viewport.py:223` · symbol `StormViewport` · rule `GOD_OBJECT`
- **Severity:** MEDIUM (Concentrated responsibilities create high change-cost and hide bugs (e.g. rendering vs. networking concerns share state); user-visible defects already accumulate here.)
- **Cost:** LARGE · **Confidence:** 0.85 · **Expert:** moe-architect
- **Lifecycle:** 3:architect:NEW → 4:architect:REFINE → 4:devils-advocate:REFINE → 3:architect:NEW → 4:architect:REFINE → 4:devils-advocate:REFINE → 5:architect:UPHOLD
- **Related:** —

StormViewport (1,085-LOC file, ~790 LOC of class body) owns at least nine unrelated responsibility areas: (1) GL setup + shader compile (initializeGL, _upload_mesh); (2) scene-file loading across formats (_load_scene_file, _load_default_geometry, _load_usd_geometry, _load_mesh_geometry, _reload_scene); (3) per-frame rendering (paintGL, _draw_scene, _draw_scene_for_aov); (4) DCC mouse + keyboard input (mousePressEvent, mouseMoveEvent, mouseReleaseEvent, wheelEvent, keyPressEvent + _CAMERA_PRESETS); (5) drag-and-drop (dragEnterEvent/dragLeaveEvent/dropEvent); (6) ComfyUI bridge lifecycle + push (_toggle_bridge, _send_camera_to_bridge); (7) AOV export to file + bridge (_save_aovs, _export_camera_json); (8) animation (_on_anim_tick, _toggle_turntable); (9) FPS tracking + depth verification + t

**Evidence:**
```
class StormViewport(QOpenGLWidget):
    """OpenGL viewport rendering USD geometry.
```

**Proposed change:**
Stage the split as four mechanical extractions, each landed as a separate commit so the diff is reviewable. Each collaborator is constructed in StormViewport.__init__ and receives a `gl_context: Callable[[], None]` callback (defaulting to `self.makeCurrent`) so they can request the GL context without holding a widget reference.

  Step 1 — `src/viewport_scene_loader.py` (new, ~220 LOC). Move `_load_scene_file`, `_load_default_geometry`, `_load_usd_geometry`, `_load_mesh_geometry`, `_upload_mesh`, `_reload_scene`, plus `_draw_list` and `_mesh_data_list` ownership. Public API: `load(path: Path) -> None`, `reload() -> None`, `iter_draw_items() -> Iterator[DrawItem]`, `iter_mesh_data() -> Iterator[MeshData]`. StormViewport gets `self._scene = SceneLoader(self.makeCurrent, self._selection)`.

  Step 2 — `src/viewport_input.py` (new, ~180 LOC). Move `mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent`, `wheelEvent`, `keyPressEvent`, the `_CAMERA_PRESETS` table, the mouse-tracking state (`_last_mouse_x/y`, `_mouse_button`, `_alt_held`, `_mouse_moved`), and the drag/drop handlers (`dragEnterEvent`/`dragLeaveEvent`/`dropEvent`). Expose `InputController(camera, scene, selection, animator, bridge_coord)` with `handle_mouse_press(QMouseEvent)` etc. that StormViewport's Qt event hooks delegate to in one line each (`def mousePressEvent(self, e): self._input.handle_mouse_press(e); self.update()`).

  Step 3 — `src/viewport_bridge_coord.py` (new, ~140 LOC). Move `_bridge`, `_bridge_server`, `_aov_exporter` ownership plus `_toggle_bridge`, `_send_camera_to_bridge`, `_save_aovs`, `_export_camera_json`. Public API: `start()`, `stop()`, `push_camera(state: dict)`, `save_aovs() -> tuple[Path,Path]`. The widget keeps the L/B/A keybindings but they call `self._bridge_coord.<method>`.

  Step 4 — collapse `paintGL` (lines 380-512) by moving the inner per-frame body into `src/viewport_frame.py:FrameRenderer.draw(scene, camera, light_rig, environment, hud, selection)`. `paintGL` becomes ~10 lines: bind FBO/default, call `self._frame.draw(...)`, increment FPS counter.

  Acceptance: viewport.py ≤ 350 LOC; each new module ≤ 250 LOC; no public Qt method on StormViewport changes signature; existing tests in tests/test_undo.py / tests/test_selection.py pass without modification because they touch only SelectionManager, which is now wired through SceneLoader. Add a thin contract test asserting `len(StormViewport.__dict__)` <= 25 to prevent regrowth.

**Self-skeptic:**
  - A single-window app may legitimately keep Qt event hooks and the delegation orchestrator in one widget; the boundary I propose may be over-engineered for a 1-developer project.
  - Some collaborators need the GL context (makeCurrent), so passing `self` is unavoidable -- if poorly executed the split could leak coupling rather than reduce it.
  - I have not measured how often these responsibilities co-change; the apparent god object may simply be a façade with most logic already delegated.

**Rewrite rationale (R5):** The change exceeds 300 LOC because the constitutional cleavage requires moving ~5-7 method clusters (load_*_geometry, paintGL helpers, input handlers, AOV save, bridge push) out of viewport.py. A smaller change cannot reduce the responsibility count below the 5-unrelated threshold; piecemeal extraction would leave the file as a shrinking god object indefinitely.

---


### LOW (10)

#### `6ed58a34de6b0f12` — compile_shader leaks shader handle when compilation fails

- **Where:** `src/viewport.py:201` · symbol `compile_shader` · rule `GL_RESOURCE_LEAK`
- **Severity:** LOW (Polish: a single shader handle is leaked only on compile failure, which is essentially a fatal start-up path; lower than the per-load mesh leak (R12 LOW per the 'pick the lower' tie rule).)
- **Cost:** TRIVIAL · **Confidence:** 0.95 · **Expert:** moe-graphics-gl
- **Lifecycle:** 3:graphics-gl:NEW → 5:graphics-gl:RETRACT
- **Related:** `ee824bbd77d4b0cf`

viewport.py:197-204 calls glCreateShader and on failure raises RuntimeError without first calling glDeleteShader(shader); the local handle is unrecoverable so the shader object is leaked for the lifetime of the GL context. Inconsistent with the same helper in environment.py:_compile_shader (environment.py:189-198), grid.py:_compile_shader (grid.py:85-97), and aov_renderer.py:_compile_shader (aov_renderer.py:239-248), all of which call glDeleteShader(shader) before raising. R6 cross-file consistency applies: the codebase has an established pattern that this site violates.

**Evidence:**
```
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        info = glGetShaderInfoLog(shader).decode()
        raise RuntimeError(f"Shader compile error: {info}")
```

**Proposed change:**
Insert `glDeleteShader(shader)` between the info-log decode and the raise at viewport.py:202-203, mirroring the pattern in environment.py:196 and aov_renderer.py:246. Single line addition.

**Self-skeptic:**
  - Compile failure is essentially a fatal start-up condition (initializeGL catches it and prints a traceback), so a single leaked shader handle has near-zero practical impact.
  - If glCreateShader returned 0 the leak is not actually present, but glShaderSource on 0 would have already raised — so this concern is academic.

---

#### `b8fe44694d413fc3` — BridgeServer stores _preset_callback / _aov_callback as class attributes, not instance attributes

- **Where:** `src/bridge_server.py:182` · symbol `BridgeServer` · rule `CLASS_LEVEL_MUTABLE_DEFAULT`
- **Severity:** LOW (Polish/correctness risk: the class-level None defaults work today but obscure ownership and break if anyone mutates via the class object or expects per-instance isolation.)
- **Cost:** TRIVIAL · **Confidence:** 0.95 · **Expert:** moe-architect
- **Lifecycle:** 3:architect:NEW → 4:architect:UPHOLD → 3:architect:NEW → 4:architect:UPHOLD → 5:architect:UPHOLD
- **Related:** —

_preset_callback and _aov_callback are declared at class scope (bridge_server.py:182-183), not initialised in __init__. They are read by _on_message (bridge_server.py:172) as self._preset_callback / self._aov_callback. The setter set_aov_callback (line 189) assigns to self, which creates a per-instance attribute that shadows the class one -- so it works, but: (a) two instances of BridgeServer share state until each is configured; (b) reading before set_aov_callback returns the class attribute (None) rather than raising AttributeError, masking the 'forgot to wire callback' bug; (c) any future @classmethod or test that touches BridgeServer._aov_callback directly will mutate global state. The other state on this class (_clients, _last_camera_state, _server, etc.) is correctly per-instance in 

**Evidence:**
```
    _preset_callback = None
    _aov_callback = None
```

**Proposed change:**
Move the initialisations into __init__: replace the class-level lines 182-183 with `self._preset_callback: Callable | None = None` and `self._aov_callback: Callable | None = None` placed alongside the other instance state in __init__ (around bridge_server.py:46). Add a type annotation `Callable[[str], None]` / `Callable[[], None]` so callers know the signature. No behavioural change for current callers.

**Self-skeptic:**
  - Some Python codebases deliberately use class-level `None` to advertise an optional slot; the author may have intended this idiom rather than missed __init__.
  - Only one BridgeServer is ever instantiated in this app, so the shared-state risk is theoretical.

---

#### `e38fdaf46d12775d` — _PRESETS uses `type(lambda: None)` as a type, not Callable

- **Where:** `src/lighting.py:185` · symbol `_PRESETS` · rule `INCORRECT_TYPE_ANNOTATION`
- **Severity:** LOW (Polish: `type(lambda: None)` evaluates to `<class 'function'>` at module-load time but is meaningless as a type annotation - mypy would treat the variable as `function` literal, not `Callable[[], List[Light]]`. The code runs fine because Python annotations are not enforced, but the intent (a Callable) is incorrectly captured.)
- **Cost:** TRIVIAL · **Confidence:** 0.95 · **Expert:** moe-correctness
- **Lifecycle:** 1:correctness:NEW → 2:correctness:UPHOLD → 1:correctness:NEW → 2:correctness:UPHOLD → 4:correctness:UPHOLD → 5:correctness:NEW
- **Related:** —

_PRESETS is annotated `List[Tuple[str, type(lambda: None)]]` and _PRESET_MAP as `Dict[str, type(lambda: None)]`. Both are tuples of (name, factory_fn) where factory returns `List[Light]`. The correct annotation is `Callable[[], List[Light]]` from typing. The current expression actually works at runtime (it's just `<class 'function'>`) but defeats type checkers. typing.Callable is already implicitly available via `from typing import ...` patterns elsewhere in the codebase. Pass 5 verification: confirmed at lines 185 and 193.

**Evidence:**
```
_PRESETS: List[Tuple[str, type(lambda: None)]] = [
    ("3-Point", _make_3point),
    ("Rim Heavy", _make_rim_heavy),
```

**Proposed change:**
Add `Callable` to the existing typing import at lighting.py:25 and change line 185 to `_PRESETS: List[Tuple[str, Callable[[], List[Light]]]] = [` and line 193 to `_PRESET_MAP: Dict[str, Callable[[], List[Light]]] = dict(_PRESETS)`.

**Self-skeptic:**
  - Possible the original author wanted FunctionType specifically, but the import would then be types.FunctionType - the lambda trick suggests no specific intent.

---

#### `ee824bbd77d4b0cf` — compile_shader leaks the shader handle when compilation fails

- **Where:** `src/viewport.py:197` · symbol `compile_shader` · rule `GL_RESOURCE_LEAK_ON_ERROR`
- **Severity:** LOW (Polish: a single shader handle leaks on the (rare) compile-failure path, only at startup; the process either continues without rendering or exits, so impact is minimal.)
- **Cost:** TRIVIAL · **Confidence:** 0.95 · **Expert:** moe-graphics-gl
- **Lifecycle:** 1:graphics-gl:NEW → 2:graphics-gl:UPHOLD → 5:graphics-gl:UPHOLD
- **Related:** `3342813affab7e7d`

On compile failure, compile_shader raises RuntimeError without first calling glDeleteShader(shader). The shader name allocated by glCreateShader is leaked. Compare to aov_renderer._compile_shader (aov_renderer.py:246) and environment._compile_shader (environment.py:196) which both call glDeleteShader before raising — viewport.py is the inconsistent file (R6 cross-file).

**Evidence:**
```
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        info = glGetShaderInfoLog(shader).decode()
        raise RuntimeError(f"Shader compile error: {info}")
```

**Proposed change:**
Insert `glDeleteShader(shader)` between the glGetShaderInfoLog line and the raise: `info = glGetShaderInfoLog(shader).decode(); glDeleteShader(shader); raise RuntimeError(...)`. Add glDeleteShader to the imports if not already present.

**Self-skeptic:**
  - The leak is only on a one-shot startup error path so it does not accumulate; arguably INFO not LOW, but the local-convention violation justifies LOW

---

#### `a901163232b4d43e` — Two minimal PNG encoders implemented separately in aov_renderer.py and aov_export.py

- **Where:** `src/aov_renderer.py:177` · symbol `_write_png` · rule `DUPLICATED_LOGIC_ACROSS_MODULES`
- **Severity:** LOW (Polish/cleanup: two minimal PNG encoders (aov_renderer._write_png and aov_export._encode_png) implement the same algorithm in different ways — flip-Y handling differs, bit-depth handling differs. Not a functional bug today but a divergence trap (e.g. someone fixes a bug in one and not the other).)
- **Cost:** TRIVIAL · **Confidence:** 0.92 · **Expert:** moe-architect
- **Lifecycle:** 1:architect:NEW → 4:architect:UPHOLD → 1:architect:NEW → 4:architect:UPHOLD → 5:architect:UPHOLD
- **Related:** —

src/aov_renderer.py:177-232 defines `_write_png(path, data, width, height, channels, bit_depth=8)` that flips Y internally and writes to disk, supports 8 and 16 bit depths. src/aov_export.py:59-111 defines `_encode_png(pixels, width, height, channels) -> bytes` that does NOT flip Y, only supports 8-bit, and returns bytes for the bridge. Both encode IHDR/IDAT/IEND with `struct` + `zlib`, both compute CRC32 the same way, both use filter byte 0x00. The two callers (save_*_png on disk vs send_aov over network) genuinely need different output sinks (file vs bytes) and different Y orientations, but the chunk-encoding core is identical and copied. A bug in one (e.g. CRC width, IHDR field order) will silently survive in the other.

**Evidence:**
```
def _write_png(path, data, width, height, channels, bit_depth=8):
    """Write a PNG file using only zlib and struct. No Pillow required.
```

**Proposed change:**
Create src/png_io.py exporting `encode_png(pixels, width, height, channels, bit_depth=8, flip_y=False) -> bytes`. Move the chunk/IHDR/IDAT/IEND machinery there. Make aov_renderer._write_png a thin wrapper: `with open(path,'wb') as f: f.write(encode_png(data, w, h, channels, bit_depth, flip_y=True))`. Delete aov_export._encode_png and have AOVExporter call `encode_png(grayscale, w, h, 1)` (with flip already applied by _rgba_to_grayscale_flipped). Add one PNG round-trip test against PIL.Image to lock the format down.

**Self-skeptic:**
  - the two implementations are short (~30 lines each) and the duplication cost is small relative to the cost of introducing a new module everyone has to import
  - the bit-depth=16 path is only used by save_depth_png; consolidation could complicate the simpler 8-bit path

---

#### `5b7d2a7afa7a8f93` — mesh_importers broad-except recovery duplicates the else branch

- **Where:** `src/mesh_importers.py:196` · symbol `_trimesh_to_meshdata` · rule `BROAD_EXCEPT_MASKS_BUGS`
- **Severity:** LOW (Polish / dead branch: the `except Exception` block does the same thing as the immediately-preceding `else` branch (`normals = _compute_vertex_normals(vertices, indices)`). Catching every Exception here means the recovery path silently absorbs unrelated bugs (e.g. an AttributeError from a future trimesh API change) under the guise of 'normals fall-back', when it should narrow the catch to whatever trimesh raises on degenerate geometry.)
- **Cost:** TRIVIAL · **Confidence:** 0.75 · **Expert:** moe-correctness
- **Lifecycle:** 2:correctness:NEW → 2:correctness:NEW → 4:correctness:REFINE → 5:correctness:NEW
- **Related:** —

In `_trimesh_to_meshdata`, the try-block computes `mesh.vertex_normals` and falls back to `_compute_vertex_normals` either when the trimesh call returns a wrong-shape result OR when it raises. The except clause catches `Exception`, masking any non-trimesh bug (typo in the else branch, AttributeError from a refactored helper, etc.) under a normals-fallback that looks legitimate. The remaining two broad-except sites in this file (lines 232 and 259) catch everything from color-extraction code under `pass` - same pattern.

R13 parent finding: lines 196, 232, 259 share the rule_kind in this file. Pass 5 verification: source at 196-197, 232-233, 259-260 confirms three `except Exception:` sites — issue stands.

**Evidence:**
```
    except Exception:
        normals = _compute_vertex_normals(vertices, indices)
```

**Proposed change:**
Apply the following three concrete edits in src/mesh_importers.py (verified against the current source at lines 186-260):

1) Line 196 — narrow normals fallback so unrelated bugs surface:
```python
    except (ValueError, AttributeError, IndexError, TypeError) as exc:
        # trimesh raises these on degenerate geometry / missing topology.
        # Re-raise on truly unexpected exceptions so they are not masked.
        normals = _compute_vertex_normals(vertices, indices)
```
If trimesh-version-specific exceptions appear in CI, append them here rather than widening to `Exception`.

2) Line 232 — vertex-color extraction is numpy-only; narrow:
```python
        except (AttributeError, ValueError, IndexError, TypeError):
            pass  # vertex colors malformed; fall through to material color
```

3) Line 259 — material-color extraction; narrow and add a one-line comment:
```python
        except (AttributeError, ValueError, IndexError, TypeError):
            pass  # material attribute missing or non-numeric; fall through
```

No new imports required; all four exception classes are builtins. Add a regression test in tests/test_mesh_importers.py that constructs a fake `mesh` object whose `.vertex_normals` raises `RuntimeError` and asserts the call now propagates rather than silently using computed normals.

**Self-skeptic:**
  - The exact exception types trimesh raises are version-dependent; the proposed list may need to add NotImplementedError or trimesh-specific exceptions after empirical testing.
  - If the call ever raises KeyboardInterrupt or SystemExit through some misbehaving native code, narrowing the catch is strictly better - so the change is upside-only.

---

#### `95d4ffec6b8000f1` — Fragment shader duplicates four named lighting constants from config.py

- **Where:** `src/viewport.py:144` · symbol `FRAGMENT_SHADER` · rule `MAGIC_NUMBER`
- **Severity:** LOW (Polish/maintenance: shader hard-codes constants that already have named values in config.py (SPECULAR_POWER=32.0, SPECULAR_STRENGTH=0.3, AMBIENT_MIN=0.15, DIFFUSE_FACTOR=0.75). Tuning a lighting parameter in config.py has no effect.)
- **Cost:** SMALL · **Confidence:** 0.95 · **Expert:** moe-correctness
- **Lifecycle:** 3:correctness:NEW → 4:correctness:RETRACT → 5:correctness:NEW
- **Related:** `e42958d62ec28bb1`

R13 duplicate: this finding is fully subsumed by e42958d62ec28bb1 (`MAGIC_NUMBER_DUPLICATES_CONFIG`) which targets the same shader, the same four constants, plus the wider set of duplicate config values (OrbitCamera defaults, ANIMATION_FPS, AOV_EXPORT_INTERVAL, ANIM_TIMER_INTERVAL) at MEDIUM severity. Per R13 (one finding per rule_kind per file) and per the precedence rule that severity ties break to the lower severity — except here the broader finding is correctly at MEDIUM because tuning config does nothing user-visibly. Pass 5 RETRACT confirmed: this is a duplicate of e42958d62ec28bb1 and contains the strict subset of literals already enumerated there.

**Evidence:**
```
    float ambient = max(0.15, uAmbientOverride);
    bool unlit = (ambient >= 1.0);
```

**Proposed change:**
Retracted as duplicate of e42958d62ec28bb1; see that finding's proposed_change for the unified shader-uniform / config-wired patch.

**Self-skeptic:**
  - the constants in config.py may be unused legacy values not actually wired anywhere; a quick grep would confirm whether anything else reads them

---

#### `f0daf45e45407ecc` — Highlight color duplicated between config.py and selection.py with conflicting values

- **Where:** `src/selection.py:50` · symbol `_HIGHLIGHT_COLOR` · rule `MAGIC_CONSTANT_DUPLICATED`
- **Severity:** LOW (Two definitions of the highlight color disagree on the actual value -- this is observable drift, not a hypothetical risk.)
- **Cost:** SMALL · **Confidence:** 0.95 · **Expert:** moe-architect
- **Lifecycle:** 3:architect:NEW → 4:architect:REFINE → 4:devils-advocate:REFINE → 3:architect:NEW → 4:architect:REFINE → 4:devils-advocate:REFINE → 5:architect:UPHOLD
- **Related:** —

config.py:77 declares HIGHLIGHT_COLOR = (1.0, 0.6, 0.0) (commented as 'orange wireframe'). selection.py:50 declares _HIGHLIGHT_COLOR = (1.0, 0.7, 0.0) and exposes it via get_highlight_color(), which is the value viewport.py actually paints. The values differ in the green channel (0.6 vs 0.7) -- already-drifted duplication. config.py also declares ANIMATION_FPS, TURNTABLE_SPEED, MAX_LIGHTS, MAX_EFFECTIVE_INTENSITY, SPECULAR_POWER, AMBIENT_MIN, DIFFUSE_FACTOR; lighting.py independently re-declares MAX_LIGHTS=4 and _MAX_EFFECTIVE_INTENSITY=64.0; the shader source in viewport.py hardcodes the AMBIENT_MIN (0.15), DIFFUSE_FACTOR (0.75), SPECULAR_POWER (32.0), and SPECULAR_STRENGTH (0.3) literals.

**Evidence:**
```
_HIGHLIGHT_COLOR: tuple[float, float, float] = (1.0, 0.7, 0.0)
```

**Proposed change:**
Land in three independent commits so each module's import surface is reviewed in isolation:

  Commit A — selection.py: Replace lines 50-51 with `from config import HIGHLIGHT_COLOR as _HIGHLIGHT_COLOR` and keep `_HIGHLIGHT_SCALE: float = 1.02` local (it's not in config). Update `config.HIGHLIGHT_COLOR` from `(1.0, 0.6, 0.0)` to `(1.0, 0.7, 0.0)` since the rendered value is canonical (users have been seeing 0.7). Add a one-line test in tests/test_config.py asserting `selection.get_highlight_color() == config.HIGHLIGHT_COLOR`.

  Commit B — lighting.py: Replace `MAX_LIGHTS: int = 4` (line 28) and `_MAX_EFFECTIVE_INTENSITY: float = 64.0` (line 31) with `from config import MAX_LIGHTS, MAX_EFFECTIVE_INTENSITY as _MAX_EFFECTIVE_INTENSITY`. The values already match config — this just removes the redundant declarations.

  Commit C — viewport.py shader literals: Convert `FRAGMENT_SHADER` (currently a module-level triple-quoted string at lines ~140-189) into a Python f-string template, substituting `{ambient_min}`, `{diffuse_factor}`, `{specular_power}`, `{specular_strength}` from `config`. Concretely:
    `FRAGMENT_SHADER = _FRAGMENT_SHADER_TEMPLATE.format(ambient_min=config.AMBIENT_MIN, diffuse_factor=config.DIFFUSE_FACTOR, specular_power=config.SPECULAR_POWER, specular_strength=config.SPECULAR_STRENGTH)` after escaping the existing `{` / `}` in the GLSL `main()` body to `{{` / `}}`. Lines 166, 182, 187 lose their literal `0.15`, `32.0`, `0.3`, `0.75`. Add a smoke test that compiles the substituted shader (already done implicitly by tests that bring up a GL context) so the substitution doesn't break GLSL parsing.

  Optional D (defer): If the team prefers runtime uniforms over compile-time substitution, add `glUniform1f(uAmbientMin, config.AMBIENT_MIN)` etc. in `paintGL` and reference them in the shader via `uniform float uAmbientMin`. This is more flexible but costs ~12 lines of uniform plumbing per constant; commit C is the smaller change.

**Self-skeptic:**
  - selection.py was deliberately kept GL-context-free, so the author may have wanted zero non-stdlib imports; config.py is pure Python so importing is safe, but the intent should be confirmed.
  - Sub-100-LOC modules sometimes prefer self-contained literals over a config dependency; the cure may be worse than the disease for one tuple.

---

#### `0e436264bc60ae2d` — trimesh.load called without a sandboxed resolver — malicious OBJ/glTF can reference arbitrary host paths

- **Where:** `src/mesh_importers.py:139` · symbol `_load_via_trimesh` · rule `UNRESTRICTED_EXTERNAL_RESOURCE_RESOLVER`
- **Severity:** LOW (Polish / hardening: a malicious dropped OBJ/MTL or glTF file can reference textures or .bin buffers via path-traversal (e.g. `map_Kd ../../../etc/ssh/ssh_host_rsa_key`) and trimesh's default `FilePathResolver` will happily attempt to read them. The contents are loaded as image bytes and never sent over the wire from this module, so there is no direct exfil — but it gives a malicious file a way to probe for arbitrary paths and (via subsequent file-format errors written to stdout) leak path-existence side channels.)
- **Cost:** SMALL · **Confidence:** 0.70 · **Expert:** moe-security
- **Lifecycle:** 1:security:NEW → 2:security:NEW → 5:security:NEW
- **Related:** `ed09005aa5917ac5`

`_load_via_trimesh` calls `trimesh.load(file_path, force=None, **kwargs)` with no `resolver=` argument. trimesh's default behaviour for OBJ/glTF/PLY is to construct a `FilePathResolver` rooted at the parent directory of `file_path`, but it does not constrain *.mtl* / texture / external buffer references to that root — relative paths containing `..` are followed. A user dragging an attacker-supplied OBJ would cause reads of arbitrary files (those readable as the user) under the cover of texture loading. Since `file_drop.py` is the documented untrusted-input boundary, this widens the parser attack surface beyond the file the user actually consented to open. Pass 5 verification: line 139 is unchanged (`loaded = trimesh.load(file_path, force=None, **kwargs)`), no resolver guard exists in the c

**Evidence:**
```
    loaded = trimesh.load(file_path, force=None, **kwargs)
```

**Proposed change:**
Wrap the call so external references are confined to the dropped file's directory: `from trimesh.resolvers import FilePathResolver; resolver = FilePathResolver(os.path.dirname(os.path.abspath(file_path))); loaded = trimesh.load(file_path, force=None, resolver=resolver, **kwargs)`. Then before `trimesh.load` returns, add a guard that rejects any resolver lookup whose resolved absolute path is not a child of the resolver root (subclass `FilePathResolver` and override `get` to call `os.path.commonpath` against the root). Document the constraint in `mesh_importers.py`'s module docstring.

**Self-skeptic:**
  - I have not verified the exact resolver behaviour of trimesh 4.x against this repo's pinned version — newer trimesh may already block traversal.
  - Even if traversal succeeds, the read content is decoded as image bytes and silently discarded on failure; the practical exfil path is narrow.
  - A subclassed resolver may break legitimate cases where assets sit in a sibling `textures/` directory referenced via `../textures/foo.png`.

---

#### `66300a02c80d6fb0` — USD loader passes drag-dropped paths straight to Usd.Stage.Open with no size/extension/magic precheck

- **Where:** `src/usd_loader.py:50` · symbol `load_usd_file` · rule `PARSER_NO_PRECHECK_ON_UNTRUSTED_INPUT`
- **Severity:** LOW (Polish: drag-and-drop is the documented untrusted-input boundary (file_drop.py), and `Usd.Stage.Open` invokes the full pxr USD parser (and, for `.usdz`, an embedded zip extractor) on whatever file the user dropped with zero pre-validation — no size cap, no extension recheck, no magic-byte sniff. A malformed USD file that triggers a pxr parser bug currently surfaces as either a UI hang or a stack trace exposing `file_path` via the print at viewport.py:401. Failing closed early is cheap.)
- **Cost:** SMALL · **Confidence:** 0.65 · **Expert:** moe-security
- **Lifecycle:** 1:security:NEW → 2:security:NEW → 5:security:NEW
- **Related:** —

`load_usd_file` calls `Usd.Stage.Open(file_path)` directly on a path that originated in `file_drop.py:validate_drop`, which only checks the *extension*. An attacker-supplied `.usda` containing a 10 GB recursive layer reference, or a `.usdz` (a zip archive) crafted to trigger zip-bomb behaviour, will be opened without any guard. The pxr library is third-party and out of scope for fixing internally, but a thin precheck in this repo (size cap, magic-byte verify, refuse symlinks) keeps the failure mode predictable and prevents the UI thread from being wedged during the parse. Pass 5 verification: lines 50-53 unchanged; `config.SUPPORTED_USD_EXTENSIONS` vs `file_drop.SUPPORTED_EXTENSIONS` mismatch on `.usdz` is still present; UPHOLD as written.

**Evidence:**
```
    stage = Usd.Stage.Open(file_path)
    if stage is None:
        raise RuntimeError(f"Failed to open USD file: {file_path}")
```

**Proposed change:**
Before the `Usd.Stage.Open` call, add: (1) `if os.path.islink(file_path): raise RuntimeError("Refusing to load symlinked USD")`; (2) `size = os.path.getsize(file_path); MAX_USD_BYTES = int(os.getenv("MAX_USD_BYTES", str(512 * 1024 * 1024))); if size > MAX_USD_BYTES: raise RuntimeError(f"USD file too large: {size} bytes")`; (3) extension whitelist check against `config.SUPPORTED_USD_EXTENSIONS`; (4) for `.usdz` open via `zipfile.ZipFile` first and reject archives whose uncompressed total > 4× compressed (zip-bomb guard) before delegating to `Usd.Stage.Open`. Reconcile the extension lists so `file_drop.SUPPORTED_EXTENSIONS` and `config.SUPPORTED_USD_EXTENSIONS` agree on `.usdz`.

**Self-skeptic:**
  - A 512 MB cap is arbitrary; legitimate film-pipeline USDs can exceed it. The env-override mitigates this but the default may annoy power users.
  - pxr USD already has internal protections against some pathological inputs; the precheck may be redundant.
  - The error message in the existing `raise RuntimeError(f"Failed to open USD file: {file_path}")` already echoes the path back to stdout — that's a minor info-leak but I'm not raising it separately because it's covered by this finding's failing-closed proposal.

---


### INFO (1)

#### `ed09005aa5917ac5` — trimesh.load follows external asset references from drag-dropped files

- **Where:** `src/mesh_importers.py:139` · symbol `_load_via_trimesh` · rule `UNTRUSTED_FILE_PARSER_RESOLVES_EXTERNAL_REFS`
- **Severity:** INFO (RETRACTED in pass 5 as a duplicate of `0e436264bc60ae2d` (same file, same line, same `_load_via_trimesh` call, same underlying observation that trimesh follows external resource references from drag-dropped files). Different `rule_kind` strings caused R10 IDs to differ so synthesizer did not auto-merge, but R13 (one pattern per file) and the precedence rule favouring the lower-severity calibration both apply: the LOW finding already carries the actionable proposed_change and self-skepticism set, so the INFO copy adds noise without information.)
- **Cost:** SMALL · **Confidence:** 0.90 · **Expert:** moe-security
- **Lifecycle:** 3:security:NEW → 5:security:NEW
- **Related:** `0e436264bc60ae2d`

Retracted: duplicate of finding 0e436264bc60ae2d. Both findings cite the identical evidence quote at src/mesh_importers.py:139 (`loaded = trimesh.load(file_path, force=None, **kwargs)`), the identical symbol (`_load_via_trimesh`), and propose the identical mitigation (pass a `FilePathResolver` rooted at the file directory). The only differences are the `rule_kind` label and the severity choice (INFO vs LOW). Per R13 (one pattern per file per pass) and the constitution's tie-break rule favouring the lower severity, the LOW-severity sibling already represents the position the security expert wants on the record; this INFO copy should be dropped from the merged report.

**Evidence:**
```
    loaded = trimesh.load(file_path, force=None, **kwargs)
```

**Proposed change:**
Drop this finding from the synthesized report; defer to 0e436264bc60ae2d which carries the same evidence and a more actionable proposed_change.

**Self-skeptic:**
  - this is the documented behavior of trimesh and most users want sidecar MTL/textures to load -- restricting could break legitimate workflows
  - I have not verified whether the bundled trimesh version exposes a custom-resolver hook on every format

---


## Expert Contribution

| Expert | Accepted findings |
|---|---:|
| `moe-correctness` | 7 |
| `moe-build-integrity` | 6 |
| `moe-architect` | 4 |
| `moe-testing` | 4 |
| `moe-security` | 3 |
| `moe-graphics-gl` | 3 |

## Cost

| Expert | Calls | Input tokens | Output tokens | Cost USD |
|---|---:|---:|---:|---:|
| `moe-architect` | 4 | 185 | 52,045 | $3.9857 |
| `moe-build-integrity` | 3 | 1,765 | 36,077 | $1.5825 |
| `moe-concurrency` | 5 | 258 | 54,834 | $3.7334 |
| `moe-correctness` | 5 | 9,734 | 69,952 | $5.3103 |
| `moe-devils-advocate` | 2 | 64 | 8,376 | $0.6315 |
| `moe-graphics-gl` | 4 | 174 | 36,339 | $3.7068 |
| `moe-performance` | 4 | 177 | 44,487 | $4.3995 |
| `moe-security` | 4 | 189 | 35,349 | $3.0873 |
| `moe-testing` | 5 | 273 | 58,411 | $3.9693 |
| **TOTAL** | | | | **$30.4063** |

## Provenance

- Generated: 2026-05-04T00:07:44.413136+00:00
- Constitution: `.claude/CONSTITUTION.md` (R1–R13)
- Harness: `review_harness/` v0.1.0
- Reproduce: `python -m review_harness --rounds 5 --model claude-opus-4-7 --seed 42`
