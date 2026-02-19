# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**comfyui_3D_viewport** is an enhancement layer ("graft") for the `comfyui-agent` project (v0.4.0). It adds 3D ecosystem intelligence to the agent's four capability layers: UNDERSTAND, DISCOVER, PILOT, and VERIFY.

This is **not** a standalone project. It extends the parent codebase at `C:\Users\User\comfyui-agent\` by adding:
- 3D data type recognition (MESH, VOXEL, POINT_CLOUD, CAMERA, POSE) to the UNDERSTAND layer
- Partner Node awareness and comparative knowledge to the DISCOVER layer
- Splat-to-mesh conversion path guidance
- 3D viewport/control tool discovery (VNCCS, Action Director)

The master plan lives in `SUPERDUPER_UI_PLAN_v2.md` (parent). This repo's scope is defined by `SUPERDUPER_3D_GRAFT.md` — five grafts (A through E) that slot into existing phases.

## Parent Project: comfyui-agent

**Path:** `C:\Users\User\comfyui-agent\`
**Always edit source there, never installed copies.**

### Key Files to Modify

| Graft | Target File(s) | What Changes |
|-------|----------------|--------------|
| A: 3D Data Types | `agent/tools/workflow_parse.py`, `agent/knowledge/comfyui_core.md` | Add MESH/VOXEL/POINT_CLOUD/CAMERA/POSE type mappings |
| B: Partner Nodes | `agent/tools/comfy_discover.py`, `agent/knowledge/` | Add `source_tier` field, partner node registry |
| C: Splat-to-Mesh | `agent/knowledge/3d_workflows.md` | Conversion path documentation and trigger phrases |
| D: Viewport Tools | `agent/knowledge/` | VNCCS, Action Director, 3DView knowledge entries |
| E: Demo Scenarios | Phase 5 test plan (not code) | Splat-to-mesh, ControlNet 3D, Partner Node comparison demos |

### Architecture Quick Reference

```
agent/
  tools/           # 44 tools across 4 intelligence layers
    workflow_parse.py    # UNDERSTAND: format detection, connection tracing, summaries
    comfy_discover.py    # DISCOVER: unified search (Manager registry + CivitAI + HuggingFace)
    workflow_patch.py    # PILOT: RFC6902 patching, semantic node ops, undo stack
    comfy_execute.py     # VERIFY: queue, execute, poll via WebSocket
    model_compat.py      # Model family matrix (already has hunyuan3d + wan entries)
    comfy_api.py         # Live ComfyUI HTTP API queries
  brain/           # 21 higher-order tools (vision, planner, memory, optimizer)
  knowledge/       # Trigger-loaded domain files
    comfyui_core.md      # Always loaded. Type system: IMAGE, LATENT, MODEL, CLIP, VAE, etc.
    3d_workflows.md      # Loaded on "3d", "mesh", "gaussian", "hunyuan3d" triggers
    controlnet_patterns.md
    flux_specifics.md
    common_recipes.md
  system_prompt.py       # Builds context; _KNOWLEDGE_TRIGGERS dict controls file loading
  workflow_session.py    # Thread-safe session state (base_workflow, current, history, format)
  mcp_server.py          # MCP stdio transport (primary interface)
  config.py              # Paths, ComfyUI base URL
```

### Existing 3D Support (already in comfyui-agent)

- `model_compat.py` recognizes `hunyuan3d` and `wan` as 3D/video modalities with incompatibility rules
- `3d_workflows.md` documents Hunyuan3D pipeline, Gaussian Splatting basics, output formats (.glb/.ply/.obj)
- `system_prompt.py` triggers 3D knowledge on ~20 keywords (3d, mesh, gaussian, splat, glb, etc.)
- `comfy_discover.py` maps HuggingFace tags: `"3d" -> "image-to-3d"`, `"text-to-3d" -> "text-to-3d"`

### What's Missing (the grafts fill these gaps)

- No human-readable descriptions for 3D connection types (UNDERSTAND says "unknown type")
- No Partner Node vs Community distinction in DISCOVER results
- No splat-to-mesh conversion guidance (the #1 community friction point)
- No awareness of viewport tools (VNCCS, Action Director) that aren't agent-operated

## Execution Order

```
Phase 2 (Backend Bridge) -> GRAFT A (3D data types)
                         -> Phase 3 (DISCOVER Panel) + GRAFTS B, C, D
                         -> Phase 4 (Status + UX)
                         -> Phase 5 + GRAFT E (demo scenarios)
```

Or bundle Grafts A-D as a single Phase 3.5 after Phase 3 ships.

## Build & Test

All work happens in the parent project:

```bash
# Install (from comfyui-agent root)
pip install -e ".[dev]"

# Run all tests (~573 tests, <35s, fully mocked, no ComfyUI needed)
cd C:\Users\User\comfyui-agent && python -m pytest tests/ -v

# Single test file
python -m pytest tests/test_workflow_parse.py -v

# Single test by keyword
python -m pytest tests/ -v -k "3d"

# Tests relevant to grafts
python -m pytest tests/test_workflow_parse.py tests/test_comfy_discover.py tests/test_model_compat.py tests/test_new_features.py -v
```

### CLI Commands (for manual verification)

```bash
agent run                    # Interactive chat (test UNDERSTAND/DISCOVER responses)
agent parse workflow.json    # Test workflow parsing with 3D data types
agent search "mesh generation" --nodes   # Test DISCOVER with 3D queries
```

## Coding Patterns

### Data Type Registration

Connection types in comfyui-agent are defined in `agent/knowledge/comfyui_core.md` (always-loaded knowledge) and handled dynamically via ComfyUI's `/object_info` API. The workflow parser in `workflow_parse.py` uses `_trace_connections()` to detect `[node_id_str, output_index_int]` arrays and `_build_summary()` to describe data flow. Add type descriptions to both the knowledge file and the summary builder.

### DISCOVER Result Schema

Every discover result returns:
```python
{
    "name": str, "type": str, "source": str,  # "registry" | "civitai" | "huggingface"
    "installed": bool, "relevance_score": float,
    "url": str, "author": str, "description": str,
    "tags": list[str], "last_modified": str
}
```
Graft B adds `"source_tier": "partner" | "community" | "core"` to this schema.

### Knowledge File Pattern

Knowledge files are plain Markdown in `agent/knowledge/`. They're injected into the system prompt when trigger keywords match (see `_KNOWLEDGE_TRIGGERS` in `system_prompt.py`). To add new knowledge:
1. Create or extend a `.md` file in `agent/knowledge/`
2. Add trigger keywords to the dict in `system_prompt.py`
3. Keep files concise — they become part of every matching prompt

### Test Pattern

All tests use mocks — no live ComfyUI connection:
```python
@patch.object(comfy_discover, "_MANAGER_DIR", tmp_path / "ComfyUI-Manager")
def test_something(mock_dir):
    # Write fake registry files to tmp_path
    # Run test with real code, fake data
```

### Determinism

`sort_keys=True` on all JSON serialization. Sorted dict iteration before aggregation. No `uuid.uuid4()` in hot paths.

## ComfyUI 3D Ecosystem Reference

### Partner Nodes (officially supported, distinct from community)

| Node | Provider | Capability | Best For |
|------|----------|-----------|----------|
| Hunyuan 3D 3.0 | Tencent | Text/image/sketch to 3D | Production assets |
| Meshy 6 | Meshy | AI mesh generation | Stylized game assets |
| Tripo v3.0 | Tripo | Fast 3D prototyping | Rapid iteration |
| Rodin 3D Gen-2 | Rodin | High-detail 3D | Realistic models |

### Key Community Packs

| Pack | Stars | Capability |
|------|-------|-----------|
| ComfyUI-3D-Pack | 3,641+ | Comprehensive 3DGS/NeRF/mesh toolkit, marching cubes |
| Trellis2 | — | Open-source mesh generation |

### Viewport & Control Tools (not agent-operated, but DISCOVER should surface)

| Tool | Author | Use Case |
|------|--------|----------|
| VNCCS | @wildmindai | Character posing, lighting, ControlNet prep |
| Action Director | @wildmindai | 3D viewport, camera control, batch ControlNet passes |
| 3DView | @kakachiex | In-graph 3D model preview |

### Splat-to-Mesh Conversion Paths

1. **ComfyUI-3D-Pack** marching cubes: 3DGS/NeRF -> marching cubes -> mesh -> GLB
2. **Trellis2** native mesh output (no conversion needed)
3. **External bridge**: Export splat -> Blender/Houdini -> reimport

Common pitfalls: marching cubes resolution affects quality; GLB export may lose UVs; large splats need downsampling.

## ComfyUI Installation Path

```
G:\COMFYUI_Database\
  Custom_Nodes\        # Capital C, capital N
    ComfyUI-Manager\   # Registry JSON files live here
  models\
    3d\                # 3D model weights
```
