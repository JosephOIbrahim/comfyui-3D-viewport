# Code Review Report — `/home/user/comfyui-3D-viewport`

- **Run started:** 2026-05-04T00:40:27.870133+00:00
- **Model:** `claude-opus-4-7`
- **Git SHA:** `7159466620a517eda99e09ff3a4a78244d306077`
- **Passes completed:** 1 / 1
- **Findings:** 6 accepted · 0 retracted
- **Severity counts:** BLOCKER=0 · HIGH=1 · MEDIUM=2 · LOW=3 · INFO=0
- **Aborted:** False

## Executive Summary
The MOE panel completed 1 pass(es) and produced 6 verified findings, of which **1 are HIGH or BLOCKER**.

**Top concerns:**
- `src/viewport.py:242` — *StormViewport is a 1,104-LOC god class spanning eight subsystems* (HIGH, LARGE)


## Pass Lifecycle

| Pass | Panel | Raw | Accepted | Retracted | Store size | New | Spent USD |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | architect, build-integrity, concurrency, correctness, graphics-gl, performance, security, testing | 30 | 6 | 24 | 6 | 6 | $9.7731 |

## Top 10 Findings (by priority)

| # | Severity | Cost | File | Title |
|---|---|---|---|---|
| 1 | MEDIUM | TRIVIAL | `src/viewport.py:192` | Fragment shader hardcodes Blinn-Phong constants that already exist in config.py |
| 2 | MEDIUM | TRIVIAL | `src/lighting.py:29` | MAX_LIGHTS is duplicated in config.py:55 and lighting.py:29; viewport imports the wrong one |
| 3 | HIGH | LARGE | `src/viewport.py:242` | StormViewport is a 1,104-LOC god class spanning eight subsystems |
| 4 | LOW | TRIVIAL | `requirements.txt:1` | requirements.txt and requirements-dev.txt duplicate pyproject.toml dependency tables |
| 5 | LOW | TRIVIAL | `src/lighting.py:29` | MAX_LIGHTS and _MAX_EFFECTIVE_INTENSITY are defined in both lighting.py and config.py |
| 6 | LOW | TRIVIAL | `src/math_utils.py:54` | vec3_normalize and vec3_normalize_tuple disagree on zero-vector fallback |

## All Accepted Findings


### HIGH (1)

#### `0bd711ea0adcd35b` — StormViewport is a 1,104-LOC god class spanning eight subsystems

- **Where:** `src/viewport.py:242` · symbol `StormViewport` · rule `GOD_OBJECT`
- **Severity:** HIGH (1,104-LOC class concentrates eight unrelated subsystems; design flaw causing maintenance friction and visible coupling bugs (e.g. _save_aovs mixes file IO, WS broadcast and HTTP bridge in 35 lines).)
- **Cost:** LARGE · **Confidence:** 0.90 · **Expert:** moe-architect
- **Lifecycle:** 1:architect:NEW
- **Related:** —

The widget owns: (1) GL pipeline state and shader program (lines 252-348, 514-614), (2) scene file loading for USD/GLB/OBJ/PLY (399-472), (3) input handling and DCC controls (817-916), (4) camera preset routing (922-989), (5) animation loop (678-697), (6) AOV export orchestration with both file output, WS broadcast, and HTTP push in one method (703-739), (7) ComfyUI bridge lifecycle (756-778), (8) HUD/overlay drawing (617-637). Cleavage planes are visible: the FileDrop, Selection, Animation and AOV subsystems are already separate classes but get re-stitched inside this widget. Symptom-level evidence: _save_aovs (703-739) routes the same data to three sinks (file, BridgeServer.broadcast_aov, AOVExporter.export_all) inline; _send_camera_to_bridge (768-778) does the same for camera with two t

**Evidence:**
```
class StormViewport(QOpenGLWidget):
    """OpenGL viewport rendering USD geometry.
```

**Proposed change:**
Extract three collaborator classes that StormViewport composes rather than implements: (a) SceneLoader owning _load_default_geometry / _load_usd_geometry / _load_mesh_geometry / _load_scene_file / _reload_scene (viewport.py:371-472); (b) CameraInputController owning mousePressEvent/mouseMoveEvent/mouseReleaseEvent/wheelEvent and the orbit/pan/dolly dispatch (viewport.py:817-885); (c) BridgeCoordinator owning the dual ComfyBridge+BridgeServer routing currently inlined in _save_aovs and _send_camera_to_bridge. StormViewport keeps GL setup, paintGL and event-routing only. Target line count for the widget itself: <400 LOC.

**Self-skeptic:**
  - Qt widgets often consolidate input + paint by convention; some 'responsibilities' are unavoidable for a QOpenGLWidget.
  - Splitting may introduce circular references between widget and controllers; needs care at construction time.

**Rewrite rationale (R5):** The change exceeds 300 LOC because the widget is 1,104 LOC and the responsibilities are interlocked through shared GL state (makeCurrent guards, _draw_list, _camera). Smaller surgical extractions either leave a still-overweight class or create stub helpers that don't cleave a real boundary. The proposed split aligns each new class with a concrete subsystem already present in the codebase (FileDropHandler, SelectionManager, AOVRenderer) and lets paintGL stay below 100 lines.

---


### MEDIUM (2)

#### `29e34fa96470f013` — Fragment shader hardcodes Blinn-Phong constants that already exist in config.py

- **Where:** `src/viewport.py:192` · symbol `FRAGMENT_SHADER` · rule `MAGIC_NUMBER_DUPLICATES_CONFIG`
- **Severity:** MEDIUM (User-visible defect: changing config.SPECULAR_POWER / SPECULAR_STRENGTH / AMBIENT_MIN / DIFFUSE_FACTOR has no effect because the shader hardcodes the same numeric literals.)
- **Cost:** TRIVIAL · **Confidence:** 0.95 · **Expert:** moe-correctness
- **Lifecycle:** 1:correctness:NEW
- **Related:** —

config.py defines SPECULAR_POWER=32.0, SPECULAR_STRENGTH=0.3, AMBIENT_MIN=0.15, DIFFUSE_FACTOR=0.75 (lines 57-60), but FRAGMENT_SHADER duplicates every one of them as a baked literal: line 176 'max(0.15, uAmbientOverride)', line 192 'pow(..., 32.0) * 0.3', and line 197 'diffuse_accum * 0.75'. Editing config.py is silently dropped on the floor. R13: one finding for the file-level pattern.

**Evidence:**
```
            float spec = pow(max(dot(norm, halfDir), 0.0), 32.0) * 0.3;
            specular_accum += uLightColors[i] * spec;
        }
```

**Proposed change:**
Build FRAGMENT_SHADER with an f-string at module import: e.g. `FRAGMENT_SHADER = f"""... pow(..., {SPECULAR_POWER}) * {SPECULAR_STRENGTH} ... max({AMBIENT_MIN}, uAmbientOverride) ... diffuse_accum * {DIFFUSE_FACTOR} ..."""` and import the four constants from config. Add a unit test that asserts each constant appears in the compiled string.

**Self-skeptic:**
  - GLSL compilers may not accept all Python float reprs (e.g. very small or scientific-notation values) -- the four current values are plain decimals so this is fine, but a future config edit could trip it.
  - If anyone tunes shader constants by directly editing the shader they would lose that workflow.

---

#### `e3be0e43d1879c9b` — MAX_LIGHTS is duplicated in config.py:55 and lighting.py:29; viewport imports the wrong one

- **Where:** `src/lighting.py:29` · symbol `MAX_LIGHTS` · rule `CONFIG_NOT_SOURCE_OF_TRUTH`
- **Severity:** MEDIUM (config.py declares itself the canonical source of magic numbers but is bypassed; a future bump in one place will silently desync the shader bound from the rig bound.)
- **Cost:** TRIVIAL · **Confidence:** 0.95 · **Expert:** moe-architect
- **Lifecycle:** 1:architect:NEW
- **Related:** —

config.py:1-5 docstring claims 'all magic numbers and hardcoded values are collected here'. config.py:55 sets MAX_LIGHTS = 4. lighting.py:29 redeclares MAX_LIGHTS: int = 4. viewport.py:117 imports MAX_LIGHTS from lighting (not from config) and uses it to size shader uniform arrays at lines 342-344 and 569-574. Bumping config.MAX_LIGHTS to 8 would silently leave lighting and the shader at 4. Same R13 child instance: viewport.py:117 picks the wrong source.

**Evidence:**
```
MAX_LIGHTS: int = 4
```

**Proposed change:**
Replace lighting.py:29 with `from config import MAX_LIGHTS`, keep the comment one line above. Verify viewport.py:117 still resolves MAX_LIGHTS via the lighting re-export, or change viewport.py:117 to `from config import MAX_LIGHTS` and import LightRig separately. Update tests/test_lighting.py:7 import accordingly. Remove the redundant declaration; do not add an alias.

**Self-skeptic:**
  - lighting.py may have been intended to ship standalone (without config) for embedding in other apps; if so, config should re-export from lighting, not the other way.

---


### LOW (3)

#### `6ae192c19cc1cde3` — requirements.txt and requirements-dev.txt duplicate pyproject.toml dependency tables

- **Where:** `requirements.txt:1` · symbol `usd-core` · rule `DEPENDENCY_DECLARATION_DUPLICATED`
- **Severity:** LOW (Polish / minor cleanup per R12: both files currently declare the same five deps with identical pins, so nothing is broken today, but every future bump must touch two places — a known drift hazard rather than a live defect.)
- **Cost:** TRIVIAL · **Confidence:** 0.90 · **Expert:** moe-build-integrity
- **Lifecycle:** 1:build-integrity:NEW
- **Related:** —

`requirements.txt` lines 1-5 list exactly the same five runtime deps with the same `>=` pins as pyproject.toml `[project] dependencies` lines 12-18 (`usd-core>=25.2`, `PySide6>=6.6`, `PyOpenGL>=3.1`, `numpy>=1.26`, `trimesh>=4.0`). The same duplication exists between `requirements-dev.txt` (5 entries) and `[project.optional-dependencies] dev` (5 entries). Now that conftest.py (lines 1-6) declares `pip install -e .` as the canonical bootstrap, the loose requirements files are redundant — a future bump to e.g. `numpy>=2` in pyproject without updating requirements.txt produces a confusing two-source-of-truth situation. R13 parent finding: one pattern, two files.

**Evidence:**
```
usd-core>=25.2
PySide6>=6.6
PyOpenGL>=3.1
```

**Proposed change:**
Replace the body of `requirements.txt` with a single line `-e .` and the body of `requirements-dev.txt` with `-e .[dev]`, so pyproject.toml is the single source of truth for pins. (Or delete both files outright and document `pip install -e .[dev]` in CLAUDE.md / a new README.) Then update any scripts or docs that reference `pip install -r requirements.txt` to use the editable install instead.

**Self-skeptic:**
  - some downstream tooling (Docker images, internal mirrors) may scrape requirements.txt by convention; deleting it could break that — verify before removal
  - keeping both files in lockstep via a pre-commit hook is an alternative to deletion if there's a reason to publish a flat requirements.txt

---

#### `e979810a94c5652c` — MAX_LIGHTS and _MAX_EFFECTIVE_INTENSITY are defined in both lighting.py and config.py

- **Where:** `src/lighting.py:29` · symbol `MAX_LIGHTS` · rule `MAGIC_NUMBER_DUPLICATES_CONFIG`
- **Severity:** LOW (Polish: lighting.py predates config.py registration of these values so they exist twice; not a runtime defect today because both copies happen to match.)
- **Cost:** TRIVIAL · **Confidence:** 0.90 · **Expert:** moe-correctness
- **Lifecycle:** 1:correctness:NEW
- **Related:** —

lighting.py defines `MAX_LIGHTS: int = 4` (line 29) and `_MAX_EFFECTIVE_INTENSITY: float = 64.0` (line 32). config.py defines the same values: `MAX_LIGHTS = 4` (line 55) and `MAX_EFFECTIVE_INTENSITY = 64.0` (line 56). The shader-uniform array length is also baked at 4 (`uniform vec3 uLightDirs[4]` in viewport.py:162); changing config alone would silently break the shader.

**Evidence:**
```
MAX_LIGHTS: int = 4

# Clamp effective intensity to this value to avoid blowing out the HDR buffer.
```

**Proposed change:**
Delete the local definitions and `from config import MAX_LIGHTS, MAX_EFFECTIVE_INTENSITY as _MAX_EFFECTIVE_INTENSITY`. Add an assertion (or generate the GLSL `[4]` size from the constant) in viewport.py to keep the shader array length in lockstep.

**Self-skeptic:**
  - Removing the public MAX_LIGHTS export from lighting.py would break viewport.py's existing import on line 117; the proposal would route it through config but viewport.py would also need updating.

---

#### `62ffb59de3051056` — vec3_normalize and vec3_normalize_tuple disagree on zero-vector fallback

- **Where:** `src/math_utils.py:54` · symbol `vec3_normalize` · rule `INCONSISTENT_FALLBACK_BEHAVIOR`
- **Severity:** LOW (Polish: two near-identical functions in the same module disagree on the zero-vector fallback (one returns +Y, the other -Y) and on the epsilon (1e-10 vs 1e-12); not a current correctness bug because callers happen not to mix them, but it is a silent trap for future callers.)
- **Cost:** TRIVIAL · **Confidence:** 0.85 · **Expert:** moe-correctness
- **Lifecycle:** 1:correctness:NEW
- **Related:** —

`vec3_normalize(x, y, z)` (line 54) returns `(0, 1, 0)` with epsilon 1e-10 for zero-length input. `vec3_normalize_tuple(v)` (line 62) returns `(0, -1, 0)` with epsilon 1e-12 for the same case. lighting._normalize (lines 35-42) uses the latter convention. The +Y vs -Y choice changes the side a degenerate light shines on, so the inconsistency is observable if input ever flows from one normalizer to the other.

**Evidence:**
```
    length = math.sqrt(x * x + y * y + z * z)
    if length > 1e-10:
        return (x / length, y / length, z / length)
```

**Proposed change:**
Pick one convention (recommend `(0, 1, 0)` since +Y is the project's world-up) and a single epsilon (`_NORMALIZE_EPS = 1e-12`). Have `vec3_normalize_tuple` delegate to `vec3_normalize(*v)` and have lighting._normalize import `vec3_normalize` instead of duplicating it. Add a regression test that all three former entry points produce the same fallback.

**Self-skeptic:**
  - The two functions may have been intentionally split to give light directions a downward fallback (-Y so light shines down) -- if so the comment should say so explicitly.
  - Changing the lighting fallback could perturb existing reference renders.

---


## Expert Contribution

| Expert | Accepted findings |
|---|---:|
| `moe-correctness` | 3 |
| `moe-architect` | 2 |
| `moe-build-integrity` | 1 |

## Cost

| Expert | Calls | Input tokens | Output tokens | Cost USD |
|---|---:|---:|---:|---:|
| `moe-architect` | 1 | 59 | 16,639 | $1.3647 |
| `moe-build-integrity` | 1 | 66 | 14,799 | $0.6884 |
| `moe-concurrency` | 1 | 65 | 15,689 | $1.0323 |
| `moe-correctness` | 1 | 14,302 | 17,503 | $1.6309 |
| `moe-graphics-gl` | 1 | 49 | 9,886 | $1.0439 |
| `moe-performance` | 1 | 53 | 11,497 | $1.4939 |
| `moe-security` | 1 | 62 | 10,369 | $0.9646 |
| `moe-testing` | 1 | 93 | 11,260 | $1.5545 |
| **TOTAL** | | | | **$9.7731** |

## Provenance

- Generated: 2026-05-04T00:47:06.111445+00:00
- Constitution: `.claude/CONSTITUTION.md` (R1–R13)
- Harness: `review_harness/` v0.1.0
- Reproduce: `python -m review_harness --rounds 1 --model claude-opus-4-7 --seed 42`
