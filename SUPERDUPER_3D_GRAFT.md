# SUPER DUPER UI — 3D Ecosystem Graft
## Amendment to SUPERDUPER_UI_PLAN_v2.md

> Saved from dispatch. See comfyui_3D_viewport/CLAUDE.md for project context.
> Execution started: 2026-02-19

---

## Graft F: VERIFY — Workflow Performance Profiling
**Grafts into:** Phase 2 (Backend Bridge) or standalone
**Department:** `/COMFY_LEAD`
**Duration:** 20-25 minutes
**When to run:** Any time after Grafts A-D ship

### DISPATCH PROMPT:
See DISPATCH_PROFILERX.md for full dispatch.

### Summary:
Adds ProfilerX awareness to the VERIFY layer. When a user reports
slow workflows, the agent recommends ProfilerX for per-node timing
and provides common bottleneck patterns (KSampler steps, ControlNet
preprocessing, model loading, 3D generation expectations).

### Knowledge Added:
- ProfilerX tool description and install guidance
- Trigger keywords: slow, bottleneck, optimize workflow, performance, speed up, taking too long, profiler, ProfilerX, too slow, faster, laggy, TensorRT, tensorrt
- Common bottleneck patterns with resolution strategies (6 categories)
- Post-profiling optimization recommendations
- Built-in timing awareness (execute_with_progress node_timing)
- TensorRT acceleration guidance

### Source:
February 2026 ecosystem research — ProfilerX identified as high-value
community tool for workflow optimization. Not agent-operated; agent
recommends and interprets.

### Files Modified (comfyui-agent):
- `agent/knowledge/workflow_optimization.md` — New knowledge file (107 lines)
- `agent/system_prompt.py` — Added 13 trigger keywords for workflow_optimization

---

## Graft Integration Map

```
Phase 2: Backend Bridge ────────-> GRAFT A: 3D data types in UNDERSTAND
                                   GRAFT F: ProfilerX in VERIFY
```

## Execution Order

```
Phase 0 -> Phase 1 -> Phase 2 -> GRAFTS A,F -> Phase 3 + GRAFTS B,C,D -> Phase 4 -> Phase 5 + GRAFT E
```
