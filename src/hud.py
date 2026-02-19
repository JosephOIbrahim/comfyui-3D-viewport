"""Heads-up display overlay for the 3D viewport.

Renders camera info, FPS counter, and keyboard shortcut hints
using QPainter on top of the QOpenGLWidget surface.

Usage in StormViewport.paintGL()::

    def paintGL(self):
        # ... GL rendering ...

        painter = QPainter(self)
        self._hud.draw(painter, self._width, self._height, camera_info, fps)
        painter.end()
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QFont, QColor, QPen


class HUD:
    """Draws a translucent heads-up display over the viewport.

    Layout::

        Top-left      camera sensor, lens, focal length, FOV
        Bottom-left   keyboard shortcut hints
        Bottom-right  FPS counter
    """

    def __init__(self, font_size: int = 12) -> None:
        self._font = QFont("Consolas", font_size)
        self._font_small = QFont("Consolas", font_size - 2)
        self._enabled = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def toggle(self) -> None:
        self._enabled = not self._enabled

    def draw(
        self,
        painter: QPainter,
        width: int,
        height: int,
        camera_info: dict,
        fps: float = 0.0,
    ) -> None:
        """Draw the full HUD overlay.

        Parameters
        ----------
        painter:
            An active ``QPainter`` bound to the viewport widget.
        width, height:
            Current viewport dimensions in pixels.
        camera_info:
            Dict with keys *sensor*, *lens*, *focal_mm*, *fov_h*,
            *fov_v*, *squeeze*.  See :meth:`build_camera_info`.
        fps:
            Frames per second to display.  Hidden when <= 0.
        """
        if not self._enabled:
            return

        painter.setRenderHint(QPainter.Antialiasing)

        # Shared palette
        bg = QColor(0, 0, 0, 120)
        text_color = QColor(220, 220, 220)
        accent_color = QColor(120, 180, 255)  # light blue for labels

        margin = 12
        line_h = 18

        self._draw_camera_info(
            painter, margin, line_h, bg, text_color, accent_color, camera_info
        )
        self._draw_fps(painter, width, height, margin, fps)
        self._draw_controls(painter, height, margin, line_h)

    def build_camera_info(self, camera) -> dict:
        """Build a *camera_info* dict from an :class:`OrbitCamera` instance.

        Gracefully falls back when the camera has no physical projection
        attached (i.e. simple-FOV mode).
        """
        has_projection = (
            hasattr(camera, "_projection") and camera._projection is not None
        )
        info: dict = {
            "sensor": camera.sensor_name,
            "lens": camera.lens_name,
            "focal_mm": None,
            "fov_h": camera._projection.fov_h_deg if has_projection else camera.fov,
            "fov_v": camera._projection.fov_v_deg if has_projection else camera.fov,
            "squeeze": 1.0,
        }
        if has_projection:
            info["focal_mm"] = camera._projection.lens.focal_mm
            info["squeeze"] = camera._projection.lens.squeeze_ratio
        return info

    # ------------------------------------------------------------------
    # Internal drawing helpers
    # ------------------------------------------------------------------

    def _draw_camera_info(
        self,
        painter: QPainter,
        margin: int,
        line_h: int,
        bg: QColor,
        text_color: QColor,
        accent_color: QColor,
        camera_info: dict,
    ) -> None:
        """Top-left block: sensor, lens, focal/squeeze, FOV."""
        painter.setFont(self._font)

        sensor = camera_info.get("sensor", "Simple FOV")
        lens = camera_info.get("lens", "Pinhole")
        focal = camera_info.get("focal_mm")
        fov_h = camera_info.get("fov_h", 0)
        fov_v = camera_info.get("fov_v", 0)
        squeeze = camera_info.get("squeeze", 1.0)

        lines: list[str] = [sensor, lens]

        detail = ""
        if focal is not None:
            detail = f"{focal:.0f}mm"
        if squeeze and squeeze != 1.0:
            detail += f"  {squeeze:.1f}x Ana"
        if detail:
            lines.append(detail)

        lines.append(f"FOV: {fov_h:.1f}\u00b0 x {fov_v:.1f}\u00b0")

        # Background rect
        fm = painter.fontMetrics()
        max_text_w = max(fm.horizontalAdvance(line) for line in lines)
        bg_rect = QRectF(
            margin - 4, margin - 4, max_text_w + 16, len(lines) * line_h + 12
        )
        painter.fillRect(bg_rect, bg)

        # Text lines
        y = margin + line_h - 4
        for i, line in enumerate(lines):
            painter.setPen(QPen(accent_color if i == 0 else text_color))
            painter.drawText(margin, y, line)
            y += line_h

    def _draw_fps(
        self,
        painter: QPainter,
        width: int,
        height: int,
        margin: int,
        fps: float,
    ) -> None:
        """Bottom-right: FPS counter."""
        if fps <= 0:
            return
        painter.setFont(self._font_small)
        painter.setPen(QPen(QColor(150, 150, 150)))
        fps_text = f"FPS: {fps:.0f}"
        tw = painter.fontMetrics().horizontalAdvance(fps_text)
        painter.drawText(width - margin - tw, height - margin, fps_text)

    def _draw_controls(
        self,
        painter: QPainter,
        height: int,
        margin: int,
        line_h: int,
    ) -> None:
        """Bottom-left: keyboard/mouse shortcut hints."""
        painter.setFont(self._font_small)
        painter.setPen(QPen(QColor(130, 130, 130)))

        controls = [
            "Alt+LMB: Orbit  Alt+MMB: Pan  Scroll: Zoom",
            "F: Frame  0-4: Presets  H: Toggle HUD",
            "P: Save AOVs  L: Export Camera",
        ]

        y = height - margin - (len(controls) - 1) * (line_h - 2)
        for line in controls:
            painter.drawText(margin, y, line)
            y += line_h - 2
