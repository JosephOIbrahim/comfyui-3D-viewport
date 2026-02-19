# Integration Contract: comfyui_3D_viewport <-> comfyui-agent

## Overview

This document defines the data formats and message types exchanged between the
comfyui_3D_viewport (GL viewport) and the comfyui-agent (AI assistant) via
ComfyUI's node system.

## LOAD3D_CAMERA Schema

The canonical camera export format. Produced by the viewport's `L` key export
and the bridge WebSocket.

```json
{
    "position": [x, y, z],
    "target": [x, y, z],
    "up": [0.0, 1.0, 0.0],
    "fov": 39.6,
    "focal_length": 50.0,
    "near": 0.1,
    "far": 1000.0,

    "carwash_sensor_width": 28.25,
    "carwash_sensor_height": 18.84,
    "carwash_camera_model": "ARRI ALEXA 35",
    "carwash_lens_model": "Cooke Anamorphic/i 40mm",
    "carwash_aspect_ratio": 1.5,
    "carwash_squeeze": 2.0
}
```

### Required Fields

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| position | float[3] | world units | Camera eye position |
| target | float[3] | world units | Look-at point |
| up | float[3] | normalized | Camera up vector |
| fov | float | degrees | Vertical field of view |
| focal_length | float | mm | Physical focal length |
| near | float | world units | Near clip plane |
| far | float | world units | Far clip plane |

### Extension Fields (carwash_ prefix)

Optional. Ignored by nodes that don't support them. Used for cinema-accurate
camera matching.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| carwash_sensor_width | float | mm | Physical sensor width |
| carwash_sensor_height | float | mm | Physical sensor height |
| carwash_camera_model | string | — | Camera body identifier |
| carwash_lens_model | string | — | Lens identifier |
| carwash_aspect_ratio | float | ratio | Sensor width/height |
| carwash_squeeze | float | factor | Anamorphic squeeze (1.0 = spherical) |

### Compatibility

- **Load3D node**: Reads position, target, up, fov. Ignores carwash_ fields.
- **AdvancedCameraControlNode**: Reads position, target, fov, focal_length.
- **comfyui_3D_viewport**: Writes all fields. Reads none (producer only).
- **comfyui-agent**: Knowledge layer describes the schema. Does not read/write directly.

## Bridge Message Types

WebSocket messages between the viewport bridge (`controlnet_bridge.py`) and
ComfyUI. All messages are JSON with a `type` field.

### camera_update

Sent by viewport when the camera moves. Debounced to ~10 Hz.

```json
{
    "type": "camera_update",
    "camera": { /* LOAD3D_CAMERA schema */ },
    "timestamp": 1708300000.0
}
```

### aov_update

Sent by viewport after rendering AOV passes (depth, normal).

```json
{
    "type": "aov_update",
    "aovs": {
        "depth": "/path/to/depth_aov.png",
        "normal": "/path/to/normal_aov.png"
    },
    "resolution": [1280, 720],
    "timestamp": 1708300001.0
}
```

### status

Sent by viewport on connect/disconnect.

```json
{
    "type": "status",
    "state": "connected",
    "viewport_version": "0.3.0",
    "capabilities": ["camera_export", "depth_aov", "normal_aov"]
}
```

## File-Based Integration (No Bridge)

When the bridge is not running, integration works through files:

1. **Camera export**: Press `L` in viewport -> writes `camera_export.json`
   in LOAD3D_CAMERA format
2. **AOV export**: Press `P` in viewport -> writes `depth_aov.png` and
   `normal_aov.png` to working directory
3. **ComfyUI consumption**: Load3D node reads the JSON. ControlNet nodes
   read the AOV PNGs via LoadImage.

## Agent Knowledge Integration

The comfyui-agent knows about this contract via:

1. **`comfyui_core.md`**: LOAD3D_CAMERA listed in the type system
2. **`3d_camera_pipeline.md`**: Full schema documentation, producer/consumer
   nodes, and workflow recommendations
3. **`3d_workflows.md`**: Viewport tools (VNCCS, Action Director) documented
4. **`system_prompt.py`**: Trigger keywords route camera queries to the
   camera pipeline knowledge file

## Versioning

- Schema version is implicit in the `carwash_` prefix convention
- New extension fields must use the `carwash_` prefix
- Required fields are frozen — adding new required fields is a breaking change
- Extension fields are always optional and backward-compatible
