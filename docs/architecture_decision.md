# Architecture Decision: ComfyUI 3D Viewport Integration

## Decision

**Hybrid approach**: standalone GL viewport + ComfyUI bridge protocol.

The comfyui_3D_viewport runs as an independent Qt/OpenGL application that
communicates with ComfyUI via a WebSocket bridge. It is NOT a ComfyUI custom
node, NOT embedded in the ComfyUI web UI, and NOT dependent on ComfyUI running.

## Alternatives Considered

### Option A: Custom Node (rejected)

Package the viewport as a ComfyUI custom node with a web-based 3D viewer.

Pros:
- Single install, lives inside ComfyUI
- Automatic data flow through node connections

Cons:
- Web GL performance ceiling (no native OpenGL 3.3 Core)
- Limited to ComfyUI's execution model (batch, not interactive)
- Cannot use PySide6 or native windowing
- No physical camera system (sensor/lens database) in browser context
- Couples viewport lifetime to ComfyUI process

### Option B: Standalone Only (rejected)

Viewport with no ComfyUI awareness — purely offline 3D viewer.

Pros:
- Simplest architecture
- No network dependencies

Cons:
- Cannot export camera data to ComfyUI pipelines
- No ControlNet bridge for depth/normal AOVs
- Misses the primary use case (3D-assisted image generation)

### Option C: Hybrid (selected)

Standalone viewport that bridges to ComfyUI when available.

Pros:
- Native OpenGL performance (MSAA, FBO AOVs, physical cameras)
- Works offline (3D viewer, AOV export, camera presets)
- Bridges to ComfyUI when running (LOAD3D_CAMERA export, ControlNet depth/normal)
- Physical camera database (ARRI, RED, Sony + cinema lenses) impossible in web context
- Can evolve independently of ComfyUI release cycle

Cons:
- Two processes to manage (viewport + ComfyUI)
- Bridge protocol must be maintained
- User must manually trigger camera export (L key) or use bridge auto-sync

## Why Hybrid Wins

1. **Performance**: Native GL with FBO-based AOV rendering (depth, normal) at full
   resolution. Web GL would limit to ~60fps with no direct framebuffer access.

2. **Physical cameras**: The sensor/lens database (6 cameras, 12 lenses, 4 presets)
   computes projection matrices from real sensor dimensions. This requires
   numpy + OpenGL matrix math that doesn't translate to a browser context.

3. **Independence**: The viewport is useful without ComfyUI (USD file viewer,
   camera preset testing, AOV preview). Making it a custom node would lock it
   to ComfyUI's lifecycle.

4. **Bridge is simple**: The integration surface is small — LOAD3D_CAMERA JSON
   export + ControlNet depth/normal PNGs. This maps cleanly to a WebSocket
   message protocol.

## Integration Surface

The viewport touches ComfyUI through exactly 3 channels:

1. **LOAD3D_CAMERA JSON** (file or WebSocket): Camera position, target, fov,
   focal_length, plus `carwash_` extension fields for cinematic cameras.

2. **AOV PNGs** (file): Depth and normal render passes exported as 16-bit PNGs
   for ControlNet consumption.

3. **Bridge WebSocket** (optional): Real-time camera updates pushed to ComfyUI
   when `controlnet_bridge.py` is active.

## Status

- Channels 1 and 2 are implemented and tested (Sprint 3)
- Channel 3 has a skeleton (`controlnet_bridge.py`) but is not yet integrated
  into the main viewport loop
