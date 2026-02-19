"""Shading mode management for the 3D viewport.

Provides an enum of shading modes (SOLID, WIREFRAME, WIREFRAME_ON_SHADED,
UNLIT) and a manager that applies the correct OpenGL state before and after
each draw call.

Integration pattern (inside paintGL)::

    shading = self._shading

    # Pre-draw
    shading.apply_pre_draw()
    # ... draw scene ...
    shading.apply_post_draw()

    # Second pass for wireframe-on-shaded
    if shading.needs_second_pass:
        shading.apply_wireframe_overlay_state()
        # ... draw scene again with wireframe_color as uBaseColor ...
        shading.restore_wireframe_overlay_state()
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Dict, Tuple

from OpenGL.GL import (
    GL_FILL,
    GL_FRONT_AND_BACK,
    GL_LINE,
    GL_POLYGON_OFFSET_LINE,
    glDisable,
    glEnable,
    glPolygonMode,
    glPolygonOffset,
)


class ShadingMode(Enum):
    """Available viewport shading modes."""

    SOLID = auto()
    WIREFRAME = auto()
    WIREFRAME_ON_SHADED = auto()
    UNLIT = auto()


# Ordered cycle used by ShadingManager.cycle().
_MODE_ORDER: list[ShadingMode] = [
    ShadingMode.SOLID,
    ShadingMode.WIREFRAME,
    ShadingMode.WIREFRAME_ON_SHADED,
    ShadingMode.UNLIT,
]

_MODE_NAMES: Dict[ShadingMode, str] = {
    ShadingMode.SOLID: "Solid",
    ShadingMode.WIREFRAME: "Wireframe",
    ShadingMode.WIREFRAME_ON_SHADED: "Wire + Solid",
    ShadingMode.UNLIT: "Unlit",
}


class ShadingManager:
    """Manages the current shading mode and applies GL state accordingly.

    Parameters
    ----------
    wireframe_color : tuple[float, float, float], optional
        RGB colour used for the wireframe overlay pass.  Defaults to black
        ``(0.0, 0.0, 0.0)``.  This value is intended to be passed as the
        ``uBaseColor`` uniform during the wireframe overlay draw call.
    """

    def __init__(
        self,
        wireframe_color: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        self._mode: ShadingMode = ShadingMode.SOLID
        self._wireframe_color: Tuple[float, float, float] = wireframe_color

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> ShadingMode:
        """Return the current shading mode."""
        return self._mode

    @property
    def mode_name(self) -> str:
        """Human-readable name of the current shading mode."""
        return _MODE_NAMES[self._mode]

    @property
    def wireframe_color(self) -> Tuple[float, float, float]:
        """RGB colour used for the wireframe overlay pass."""
        return self._wireframe_color

    @wireframe_color.setter
    def wireframe_color(self, value: Tuple[float, float, float]) -> None:
        self._wireframe_color = value

    @property
    def needs_second_pass(self) -> bool:
        """Whether the current mode requires a second draw pass."""
        return self._mode == ShadingMode.WIREFRAME_ON_SHADED

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def set_mode(self, mode: ShadingMode) -> None:
        """Set the shading mode explicitly."""
        self._mode = mode

    def cycle(self) -> ShadingMode:
        """Advance to the next shading mode in the cycle and return it.

        Order: SOLID -> WIREFRAME -> WIREFRAME_ON_SHADED -> UNLIT -> SOLID.
        """
        idx = _MODE_ORDER.index(self._mode)
        self._mode = _MODE_ORDER[(idx + 1) % len(_MODE_ORDER)]
        return self._mode

    # ------------------------------------------------------------------
    # GL state management — primary draw pass
    # ------------------------------------------------------------------

    def apply_pre_draw(self) -> None:
        """Set GL state before the primary draw call."""
        if self._mode == ShadingMode.WIREFRAME:
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        # SOLID, WIREFRAME_ON_SHADED (first pass is solid), and UNLIT all
        # draw with the default filled polygon mode — no state change needed.

    def apply_post_draw(self) -> None:
        """Restore GL state after the primary draw call."""
        if self._mode == ShadingMode.WIREFRAME:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

    # ------------------------------------------------------------------
    # GL state management — wireframe overlay (second pass)
    # ------------------------------------------------------------------

    def apply_wireframe_overlay_state(self) -> None:
        """Set GL state for the wireframe-on-shaded overlay pass.

        Call this only when :attr:`needs_second_pass` is ``True``.  After
        drawing, call :meth:`restore_wireframe_overlay_state`.
        """
        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        glEnable(GL_POLYGON_OFFSET_LINE)
        glPolygonOffset(-1.0, -1.0)

    def restore_wireframe_overlay_state(self) -> None:
        """Restore GL state after the wireframe overlay pass."""
        glPolygonOffset(0.0, 0.0)
        glDisable(GL_POLYGON_OFFSET_LINE)
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

    # ------------------------------------------------------------------
    # Uniform overrides
    # ------------------------------------------------------------------

    def get_unlit_overrides(self) -> Dict[str, float]:
        """Return uniform overrides that disable lighting.

        When the mode is ``UNLIT`` this returns ``{"ambient": 1.0}`` so the
        shader renders the base colour at full brightness with no directional
        contribution.  For all other modes an empty dict is returned.
        """
        if self._mode == ShadingMode.UNLIT:
            return {"ambient": 1.0}
        return {}
