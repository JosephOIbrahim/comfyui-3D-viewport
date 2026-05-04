"""Multi-light rig manager for the OpenGL 3.3 Core Profile viewport.

Provides uniform data for up to 4 directional lights. This module performs
no OpenGL calls -- it only produces data dictionaries that the viewport
reads via ``get_uniform_data()`` and uploads as shader uniforms.

Lighting Law
------------
Intensity is ALWAYS 1.0 or below.  Brightness is controlled by EXPOSURE
(logarithmic, in stops).  ``effective_intensity = intensity * 2^exposure``.

Key:fill ratio 3:1 = 1.585 stops difference; 4:1 = 2.0 stops.

Integration pattern (inside paintGL)::

    rig = self._light_rig
    uniforms = rig.get_uniform_data()
    # set uniforms on the active shader program ...
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Dict, List, Tuple

# Hard ceiling on lights the shader supports.
MAX_LIGHTS: int = 4

# Clamp effective intensity to this value to avoid blowing out the HDR buffer.
_MAX_EFFECTIVE_INTENSITY: float = 64.0


def _normalize(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Return a unit-length copy of *v*.  Returns (0, -1, 0) for zero vectors."""
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-12:
        return (0.0, -1.0, 0.0)
    inv = 1.0 / length
    return (x * inv, y * inv, z * inv)


# ------------------------------------------------------------------
# Light dataclass
# ------------------------------------------------------------------

@dataclass
class Light:
    """A single directional light.

    Parameters
    ----------
    name : str
        Human-readable label (e.g. "Key", "Fill").
    direction : tuple[float, float, float]
        Normalized world-space direction **from** the light **to** the scene.
    color : tuple[float, float, float]
        RGB in 0-1.
    intensity : float
        Base intensity, clamped to [0.0, 1.0].  **Never** above 1.0.
    exposure : float
        Logarithmic stops.  Default 0.0.
    enabled : bool
        Whether the light contributes to the uniform array.
    """

    name: str
    direction: Tuple[float, float, float] = (0.0, -1.0, 0.0)
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    exposure: float = 0.0
    enabled: bool = True

    def __post_init__(self) -> None:
        self.direction = _normalize(self.direction)
        self.intensity = max(0.0, min(1.0, self.intensity))

    @property
    def effective_intensity(self) -> float:
        """``intensity * 2^exposure``, clamped to [0, _MAX_EFFECTIVE_INTENSITY]."""
        value = self.intensity * (2.0 ** self.exposure)
        return max(0.0, min(_MAX_EFFECTIVE_INTENSITY, value))


# ------------------------------------------------------------------
# Preset definitions
# ------------------------------------------------------------------

def _make_3point() -> List[Light]:
    """Classic 3-point lighting rig."""
    return [
        Light(
            name="Key",
            direction=(-0.5, -1.0, -0.8),
            color=(1.0, 0.95, 0.9),
            intensity=1.0,
            exposure=0.0,
        ),
        Light(
            name="Fill",
            direction=(0.6, -0.3, 0.5),
            color=(0.8, 0.85, 1.0),
            intensity=1.0,
            exposure=-1.585,
        ),
        Light(
            name="Rim",
            direction=(0.0, -0.2, 1.0),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
            exposure=-1.0,
        ),
    ]


def _make_rim_heavy() -> List[Light]:
    """Strong backlight with subtle fill."""
    return [
        Light(
            name="Rim Key",
            direction=(0.0, -0.3, 1.0),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
            exposure=0.0,
        ),
        Light(
            name="Subtle Fill",
            direction=(0.5, -0.5, -0.5),
            color=(0.85, 0.85, 0.9),
            intensity=1.0,
            exposure=-2.0,
        ),
    ]


def _make_top_down() -> List[Light]:
    """Overhead key, no fill."""
    return [
        Light(
            name="Top Key",
            direction=(0.0, -1.0, 0.0),
            color=(1.0, 0.98, 0.95),
            intensity=1.0,
            exposure=0.0,
        ),
    ]


def _make_flat() -> List[Light]:
    """Even lighting from all sides, low contrast."""
    return [
        Light(
            name="Front",
            direction=(0.0, 0.0, -1.0),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
            exposure=-0.5,
        ),
        Light(
            name="Back",
            direction=(0.0, 0.0, 1.0),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
            exposure=-0.5,
        ),
        Light(
            name="Left",
            direction=(-1.0, 0.0, 0.0),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
            exposure=-0.5,
        ),
        Light(
            name="Right",
            direction=(1.0, 0.0, 0.0),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
            exposure=-0.5,
        ),
    ]


# Ordered list of (name, factory).  Insertion order = cycle order.
LightFactory = Callable[[], List["Light"]]

_PRESETS: List[Tuple[str, LightFactory]] = [
    ("3-Point", _make_3point),
    ("Rim Heavy", _make_rim_heavy),
    ("Top Down", _make_top_down),
    ("Flat", _make_flat),
]

_PRESET_NAMES: List[str] = [name for name, _ in _PRESETS]
_PRESET_MAP: Dict[str, LightFactory] = dict(_PRESETS)


# ------------------------------------------------------------------
# LightRig
# ------------------------------------------------------------------

class LightRig:
    """Manages up to :pydata:`MAX_LIGHTS` directional lights and exposes
    uniform data for the viewport shader.

    The rig initialises with a default **3-Point** preset.
    """

    def __init__(self) -> None:
        self._preset_index: int = 0
        self._lights: List[Light] = _make_3point()

    # -- properties ------------------------------------------------

    @property
    def preset_name(self) -> str:
        """Name of the currently active preset."""
        return _PRESET_NAMES[self._preset_index]

    @property
    def lights(self) -> List[Light]:
        """Current light list (read-only reference for HUD display)."""
        return list(self._lights)

    # -- preset management -----------------------------------------

    def set_preset(self, name: str) -> None:
        """Activate a preset by *name*.

        Raises ``ValueError`` if *name* is not a known preset.
        """
        if name not in _PRESET_MAP:
            raise ValueError(
                f"Unknown preset {name!r}. "
                f"Available: {', '.join(_PRESET_NAMES)}"
            )
        self._preset_index = _PRESET_NAMES.index(name)
        self._lights = _PRESET_MAP[name]()

    def cycle_preset(self) -> str:
        """Advance to the next preset (wrapping) and return its name."""
        self._preset_index = (self._preset_index + 1) % len(_PRESETS)
        name = _PRESET_NAMES[self._preset_index]
        self._lights = _PRESET_MAP[name]()
        return name

    # -- uniform export --------------------------------------------

    def get_uniform_data(self) -> Dict[str, object]:
        """Return a dict of uniform values ready for the fragment shader.

        Keys
        ----
        ``uLightCount`` : int
            Number of enabled lights (0 to MAX_LIGHTS).
        ``uLightDirs`` : list[float]
            Flat interleaved ``[x0, y0, z0, x1, y1, z1, ...]`` for enabled
            lights only.
        ``uLightColors`` : list[float]
            Flat interleaved ``[r0, g0, b0, r1, g1, b1, ...]`` pre-multiplied
            by each light's :pyattr:`effective_intensity`.
        """
        enabled = [lt for lt in self._lights if lt.enabled][:MAX_LIGHTS]

        dirs: List[float] = []
        colors: List[float] = []

        for lt in enabled:
            dx, dy, dz = lt.direction
            dirs.extend((dx, dy, dz))

            ei = lt.effective_intensity
            r, g, b = lt.color
            colors.extend((r * ei, g * ei, b * ei))

        return {
            "uLightCount": len(enabled),
            "uLightDirs": dirs,
            "uLightColors": colors,
        }
