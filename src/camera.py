"""Turntable orbit camera for the CarWash-2 viewport.

DCC-standard controls:
    Alt + LMB drag  — Orbit (tumble)
    Alt + MMB drag  — Pan
    Alt + RMB drag  — Dolly (zoom)
    Scroll wheel    — Dolly (zoom)
    F key           — Frame scene (reset to default view)

The camera uses spherical coordinates (azimuth, elevation, distance)
relative to a target point. Pan shifts both eye and target in the
camera's local XY plane.

Physical camera projection support:
    Optionally swap between simple FOV (Sprint 1) and real sensor+lens
    combinations via set_projection() / clear_projection() methods.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from projection import PhysicalProjection


class OrbitCamera:
    """Turntable orbit camera with pan, dolly, and optional physical projection.

    By default uses simple FOV-based perspective (Sprint 1). Optionally swap
    to real sensor+lens combinations via set_projection() for physically-based
    camera parameters.
    """

    def __init__(
        self,
        target: tuple[float, float, float] = (0.0, 0.3, 0.0),
        distance: float = 5.0,
        azimuth: float = 35.0,
        elevation: float = 25.0,
        fov: float = 45.0,
        near: float = 0.1,
        far: float = 100.0,
        projection: PhysicalProjection | None = None,
    ):
        self.target = list(target)
        self.distance = distance
        self.azimuth = azimuth      # degrees, horizontal rotation
        self.elevation = elevation  # degrees, vertical rotation
        self.fov = fov
        self.near = near
        self.far = far
        self._projection = projection

        # Sensitivity tuning
        self.orbit_speed = 0.3      # degrees per pixel
        self.pan_speed = 0.003      # world units per pixel (scaled by distance)
        self.dolly_speed = 0.003    # fraction per pixel
        self.scroll_speed = 0.1     # fraction per scroll step

        # Elevation clamp (prevent gimbal flip)
        self.min_elevation = -89.0
        self.max_elevation = 89.0

        # Distance clamp
        self.min_distance = 0.05
        self.max_distance = 500.0

        # Store defaults for frame (F key) reset
        self._default_target = list(target)
        self._default_distance = distance
        self._default_azimuth = azimuth
        self._default_elevation = elevation

    @property
    def eye(self) -> tuple[float, float, float]:
        """Compute eye position from spherical coordinates."""
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        cos_el = math.cos(el)
        x = self.target[0] + self.distance * cos_el * math.sin(az)
        y = self.target[1] + self.distance * math.sin(el)
        z = self.target[2] + self.distance * cos_el * math.cos(az)
        return (x, y, z)

    @property
    def up(self) -> tuple[float, float, float]:
        """World up vector (Y-up)."""
        return (0.0, 1.0, 0.0)

    def _right_and_up_vectors(self) -> tuple[tuple, tuple]:
        """Compute camera-local right and up vectors for panning."""
        eye = self.eye
        # Forward: target - eye, normalized
        fx = self.target[0] - eye[0]
        fy = self.target[1] - eye[1]
        fz = self.target[2] - eye[2]
        fl = math.sqrt(fx*fx + fy*fy + fz*fz)
        if fl < 1e-10:
            return (1, 0, 0), (0, 1, 0)
        fx, fy, fz = fx/fl, fy/fl, fz/fl

        # Right: forward x world_up
        ux, uy, uz = 0.0, 1.0, 0.0
        rx = fy * uz - fz * uy
        ry = fz * ux - fx * uz
        rz = fx * uy - fy * ux
        rl = math.sqrt(rx*rx + ry*ry + rz*rz)
        if rl < 1e-10:
            return (1, 0, 0), (0, 1, 0)
        rx, ry, rz = rx/rl, ry/rl, rz/rl

        # Camera up: right x forward
        cx = ry * fz - rz * fy
        cy = rz * fx - rx * fz
        cz = rx * fy - ry * fx

        return (rx, ry, rz), (cx, cy, cz)

    def orbit(self, dx: float, dy: float):
        """Rotate around target. dx = horizontal pixels, dy = vertical pixels.

        Drag right = orbit right (see right side of object).
        Drag up = orbit up (see top of object).
        """
        self.azimuth += dx * self.orbit_speed
        self.elevation += dy * self.orbit_speed
        self.elevation = max(self.min_elevation, min(self.max_elevation, self.elevation))

    def pan(self, dx: float, dy: float):
        """Shift target and eye in camera-local XY plane."""
        right, up = self._right_and_up_vectors()
        scale = self.pan_speed * self.distance  # Pan scales with distance
        move_x = -dx * scale
        move_y = dy * scale
        for i in range(3):
            self.target[i] += right[i] * move_x + up[i] * move_y

    def dolly(self, delta: float):
        """Move closer/further from target. Positive delta = zoom in."""
        factor = 1.0 - delta
        self.distance *= factor
        self.distance = max(self.min_distance, min(self.max_distance, self.distance))

    def dolly_scroll(self, steps: float):
        """Zoom via scroll wheel. Positive steps = zoom in."""
        self.dolly(steps * self.scroll_speed)

    def frame_scene(self):
        """Reset camera to default view (F key)."""
        self.target = list(self._default_target)
        self.distance = self._default_distance
        self.azimuth = self._default_azimuth
        self.elevation = self._default_elevation

    def set_projection(self, projection: PhysicalProjection) -> None:
        """Swap to a physical camera (sensor + lens) projection.

        Updates near/far clipping planes from the projection's depth bounds.
        """
        self._projection = projection
        self.near = projection.near
        self.far = projection.far

    def clear_projection(self) -> None:
        """Revert to simple FOV-based perspective (Sprint 1 fallback)."""
        self._projection = None

    def projection_matrix(self, aspect: float) -> list[float]:
        """Return column-major 4x4 projection matrix.

        If a physical projection is set, uses its fov_perspective_matrix().
        Otherwise falls back to simple FOV-based perspective.
        """
        if self._projection is not None:
            return self._projection.fov_perspective_matrix(aspect)

        # Simple FOV-based perspective (Sprint 1 fallback)
        f = 1.0 / math.tan(math.radians(self.fov) / 2.0)
        nf = 1.0 / (self.near - self.far)
        return [
            f / aspect, 0, 0, 0,
            0, f, 0, 0,
            0, 0, (self.far + self.near) * nf, -1,
            0, 0, 2 * self.far * self.near * nf, 0,
        ]

    def to_load3d_camera(self) -> dict:
        """Export camera state as a load3D-compatible dict.

        If projection is set, delegates to the projection's to_load3d_camera().
        Otherwise returns basic dict with position, target, up, and FOV.
        """
        if self._projection is not None:
            return self._projection.to_load3d_camera(
                self.eye,
                tuple(self.target),
                self.up,
            )

        # Simple fallback dict
        return {
            "position": list(self.eye),
            "target": list(self.target),
            "up": list(self.up),
            "fov": self.fov,
            "focal_length": None,
        }

    @property
    def sensor_name(self) -> str:
        """Return sensor name from projection, or 'Simple FOV' if no projection."""
        if self._projection is not None:
            return self._projection.sensor.name
        return "Simple FOV"

    @property
    def lens_name(self) -> str:
        """Return lens name from projection, or 'Pinhole' if no projection."""
        if self._projection is not None:
            return self._projection.lens.name
        return "Pinhole"
