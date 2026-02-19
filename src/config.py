"""Centralized configuration for the CarWash-2 viewport.

All magic numbers and hardcoded values are collected here.  Override via
environment variables where noted.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"

# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

WINDOW_WIDTH = int(os.getenv("VIEWPORT_WIDTH", "800"))
WINDOW_HEIGHT = int(os.getenv("VIEWPORT_HEIGHT", "600"))
WINDOW_TITLE = "CarWash-2 -- Storm Viewport"
MSAA_SAMPLES = int(os.getenv("MSAA_SAMPLES", "0"))

# ---------------------------------------------------------------------------
# Camera defaults
# ---------------------------------------------------------------------------

CAMERA_DEFAULT_TARGET = (0.0, 0.3, 0.0)
CAMERA_DEFAULT_DISTANCE = 5.0
CAMERA_DEFAULT_AZIMUTH = 35.0
CAMERA_DEFAULT_ELEVATION = 25.0
CAMERA_DEFAULT_FOV = 45.0
CAMERA_NEAR = 0.1
CAMERA_FAR = 100.0

# Sensitivity
CAMERA_ORBIT_SPEED = 0.3       # degrees per pixel
CAMERA_PAN_SPEED = 0.003       # world units per pixel (scaled by distance)
CAMERA_DOLLY_SPEED = 0.003     # fraction per pixel
CAMERA_SCROLL_SPEED = 0.1      # fraction per scroll step

# Clamps
CAMERA_MIN_ELEVATION = -89.0
CAMERA_MAX_ELEVATION = 89.0
CAMERA_MIN_DISTANCE = 0.05
CAMERA_MAX_DISTANCE = 500.0

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

MAX_LIGHTS = 4
MAX_EFFECTIVE_INTENSITY = 64.0
SPECULAR_POWER = 32.0
SPECULAR_STRENGTH = 0.3
AMBIENT_MIN = 0.15
DIFFUSE_FACTOR = 0.75

# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

GRID_EXTENT = 10          # half-size: grid goes from -EXTENT to +EXTENT
GRID_COLOR = (0.35, 0.35, 0.35)

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

DEFAULT_CUBE_COLOR = (0.6, 0.6, 0.6)
DEFAULT_GROUND_COLOR = (0.35, 0.35, 0.38)

# Selection highlight
HIGHLIGHT_COLOR = (1.0, 0.6, 0.0)   # orange wireframe

# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------

ANIMATION_FPS = 24.0
TURNTABLE_SPEED = 36.0       # degrees per second
ANIM_TIMER_INTERVAL = 16     # ms (~60 fps update)

# ---------------------------------------------------------------------------
# ComfyUI Bridge
# ---------------------------------------------------------------------------

COMFYUI_HOST = os.getenv("COMFYUI_HOST", "127.0.0.1")
COMFYUI_PORT = int(os.getenv("COMFYUI_PORT", "8188"))
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"
AOV_EXPORT_INTERVAL = 0.5   # seconds between auto-exports

# ---------------------------------------------------------------------------
# File formats
# ---------------------------------------------------------------------------

SUPPORTED_USD_EXTENSIONS = {".usd", ".usda", ".usdc", ".usdz"}
SUPPORTED_MESH_EXTENSIONS = {".glb", ".gltf", ".obj", ".ply"}
ALL_SUPPORTED_EXTENSIONS = SUPPORTED_USD_EXTENSIONS | SUPPORTED_MESH_EXTENSIONS
