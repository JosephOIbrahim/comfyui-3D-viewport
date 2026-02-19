"""Mesh selection and highlight system for the OpenGL 3.3 viewport.

Provides ray-based picking (screen coords -> world-space ray -> AABB hit test),
selection state management, and highlight rendering data. Pure Python with no
numpy or OpenGL dependencies -- all matrix math is done manually so the viewport
can consume the results without coupling this module to a GL context.

The viewport draws meshes from a draw list of (vao, index_count, model_matrix,
color) tuples. Each mesh also has a MeshData (from usd_loader) with vertices,
indices, and a 16-float column-major 4x4 transform. This module bridges between
those data structures and user interaction (click-to-select, Tab-to-cycle).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from math_utils import (
    mat4_inverse as _mat4_inverse,
    mat4_multiply as _mat4_mul,
    mat4_transform_point as _mat4_transform_point,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SceneObject:
    """A registered scene object with geometry and bounding box data."""

    id: int
    name: str
    vao: int
    index_count: int
    model_matrix: list[float]           # 16-float column-major 4x4
    color: tuple[float, float, float]
    vertices: list[tuple]               # original vertices for raycasting
    indices: list[int]                  # triangle indices for raycasting
    aabb_min: tuple[float, float, float]
    aabb_max: tuple[float, float, float]


# ---------------------------------------------------------------------------
# Highlight constants
# ---------------------------------------------------------------------------

_HIGHLIGHT_COLOR: tuple[float, float, float] = (1.0, 0.7, 0.0)
_HIGHLIGHT_SCALE: float = 1.02


def get_highlight_color() -> tuple[float, float, float]:
    """Return the selection highlight color (orange)."""
    return _HIGHLIGHT_COLOR


def get_highlight_scale() -> float:
    """Return the slight scale-up factor for the outline highlight effect."""
    return _HIGHLIGHT_SCALE


# ---------------------------------------------------------------------------
# Selection manager
# ---------------------------------------------------------------------------

class SelectionManager:
    """Manages scene object registration, picking, and selection state.

    Objects are registered via ``register()`` which computes a world-space AABB.
    Picking casts a ray from screen coordinates through the scene and returns the
    closest AABB hit.
    """

    def __init__(self) -> None:
        self.objects: list[SceneObject] = []
        self.selected_id: int | None = None
        self._next_id: int = 0

    # -- Registration -------------------------------------------------------

    def register(self, mesh_data, vao: int, index_count: int) -> SceneObject:
        """Create a SceneObject from a MeshData and GL handles.

        Computes the world-space AABB from the mesh vertices and transform.

        Args:
            mesh_data: A ``usd_loader.MeshData`` instance (or any object with
                ``name``, ``vertices``, ``indices``, ``transform``, ``color``
                attributes).
            vao: OpenGL VAO handle for this mesh.
            index_count: Number of indices in the GL element buffer.

        Returns:
            The newly registered SceneObject.
        """
        aabb_min, aabb_max = _compute_world_aabb(
            mesh_data.vertices, mesh_data.transform,
        )
        obj = SceneObject(
            id=self._next_id,
            name=mesh_data.name,
            vao=vao,
            index_count=index_count,
            model_matrix=list(mesh_data.transform),
            color=tuple(mesh_data.color[0:3]),
            vertices=list(mesh_data.vertices),
            indices=list(mesh_data.indices),
            aabb_min=aabb_min,
            aabb_max=aabb_max,
        )
        self._next_id += 1
        self.objects.append(obj)
        return obj

    def clear(self) -> None:
        """Remove all registered objects and reset selection."""
        self.objects.clear()
        self.selected_id = None
        self._next_id = 0

    # -- Picking ------------------------------------------------------------

    def pick(
        self,
        screen_x: float,
        screen_y: float,
        viewport_width: int,
        viewport_height: int,
        view_matrix: list[float],
        proj_matrix: list[float],
    ) -> SceneObject | None:
        """Cast a ray from screen coordinates and return the closest hit.

        Args:
            screen_x: Mouse X in window pixels (0 = left edge).
            screen_y: Mouse Y in window pixels (0 = top edge).
            viewport_width: Viewport width in pixels.
            viewport_height: Viewport height in pixels.
            view_matrix: 16-float column-major view matrix.
            proj_matrix: 16-float column-major projection matrix.

        Returns:
            The closest SceneObject whose AABB is hit, or None.
        """
        origin, direction = _unproject(
            screen_x, screen_y,
            viewport_width, viewport_height,
            view_matrix, proj_matrix,
        )

        closest: SceneObject | None = None
        closest_dist: float = float("inf")

        for obj in self.objects:
            t = _ray_aabb_intersect(origin, direction, obj.aabb_min, obj.aabb_max)
            if t is not None and t < closest_dist:
                closest_dist = t
                closest = obj

        return closest

    # -- Selection state ----------------------------------------------------

    def select(self, object_id: int | None) -> None:
        """Set the currently selected object by ID, or None to deselect."""
        self.selected_id = object_id

    def get_selected(self) -> SceneObject | None:
        """Return the currently selected SceneObject, or None."""
        if self.selected_id is None:
            return None
        for obj in self.objects:
            if obj.id == self.selected_id:
                return obj
        return None

    def cycle_selection(self) -> None:
        """Select the next object in the list (for Tab key cycling).

        Wraps around to the first object after the last. If nothing is
        selected, selects the first object.  If the object list is empty,
        does nothing.
        """
        if not self.objects:
            return

        if self.selected_id is None:
            self.selected_id = self.objects[0].id
            return

        # Find current index
        current_idx = -1
        for i, obj in enumerate(self.objects):
            if obj.id == self.selected_id:
                current_idx = i
                break

        if current_idx < 0:
            # Selected ID no longer in list -- pick first
            self.selected_id = self.objects[0].id
        else:
            next_idx = (current_idx + 1) % len(self.objects)
            self.selected_id = self.objects[next_idx].id


# ---------------------------------------------------------------------------
# Ray construction (screen -> world)
# ---------------------------------------------------------------------------

def _unproject(
    screen_x: float,
    screen_y: float,
    viewport_w: int,
    viewport_h: int,
    view_matrix: list[float],
    proj_matrix: list[float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Convert screen coordinates to a world-space ray (origin, direction).

    Args:
        screen_x: Pixel X (0 = left).
        screen_y: Pixel Y (0 = top).
        viewport_w: Viewport width in pixels.
        viewport_h: Viewport height in pixels.
        view_matrix: 16-float column-major 4x4 view matrix.
        proj_matrix: 16-float column-major 4x4 projection matrix.

    Returns:
        (origin, direction) where both are (x, y, z) tuples. Direction is
        normalised.
    """
    # Screen -> NDC  (Y is flipped: top=0 in screen, +1 in NDC)
    ndc_x = (2.0 * screen_x / viewport_w) - 1.0
    ndc_y = 1.0 - (2.0 * screen_y / viewport_h)

    # Composite matrix: view * proj  (both column-major)
    vp = _mat4_mul(proj_matrix, view_matrix)
    inv_vp = _mat4_inverse(vp)

    # Near point (NDC z = -1) and far point (NDC z = 1)
    near_pt = _mat4_transform_point(inv_vp, ndc_x, ndc_y, -1.0)
    far_pt = _mat4_transform_point(inv_vp, ndc_x, ndc_y, 1.0)

    # Direction = far - near, normalised
    dx = far_pt[0] - near_pt[0]
    dy = far_pt[1] - near_pt[1]
    dz = far_pt[2] - near_pt[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-12:
        return near_pt, (0.0, 0.0, -1.0)
    direction = (dx / length, dy / length, dz / length)

    return near_pt, direction


# ---------------------------------------------------------------------------
# Ray-AABB intersection (slab method)
# ---------------------------------------------------------------------------

def _ray_aabb_intersect(
    ray_origin: tuple[float, float, float],
    ray_dir: tuple[float, float, float],
    aabb_min: tuple[float, float, float],
    aabb_max: tuple[float, float, float],
) -> float | None:
    """Test ray-AABB intersection using the slab method.

    Args:
        ray_origin: Ray origin (x, y, z).
        ray_dir: Normalised ray direction (x, y, z).
        aabb_min: AABB minimum corner.
        aabb_max: AABB maximum corner.

    Returns:
        Distance along the ray to the nearest intersection, or None if the
        ray misses the box. Only returns positive-distance (forward) hits.
    """
    t_min = float("-inf")
    t_max = float("inf")

    for i in range(3):
        if abs(ray_dir[i]) < 1e-12:
            # Ray is parallel to slab -- miss if origin is outside
            if ray_origin[i] < aabb_min[i] or ray_origin[i] > aabb_max[i]:
                return None
        else:
            inv_d = 1.0 / ray_dir[i]
            t1 = (aabb_min[i] - ray_origin[i]) * inv_d
            t2 = (aabb_max[i] - ray_origin[i]) * inv_d
            if t1 > t2:
                t1, t2 = t2, t1
            if t1 > t_min:
                t_min = t1
            if t2 < t_max:
                t_max = t2
            if t_min > t_max:
                return None

    # Only return forward hits
    if t_max < 0.0:
        return None

    return t_min if t_min >= 0.0 else t_max


# ---------------------------------------------------------------------------
# World-space AABB from vertices + transform
# ---------------------------------------------------------------------------

def _compute_world_aabb(
    vertices: list[tuple],
    transform: list[float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Transform all vertices by a column-major 4x4 matrix and return the AABB.

    Args:
        vertices: List of (x, y, z) tuples in local space.
        transform: 16-float column-major 4x4 matrix.

    Returns:
        (aabb_min, aabb_max) as (x, y, z) tuples. Falls back to
        ((0, 0, 0), (0, 0, 0)) for empty vertex lists.
    """
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    m = transform
    lo = [float("inf"), float("inf"), float("inf")]
    hi = [float("-inf"), float("-inf"), float("-inf")]

    for v in vertices:
        # Column-major multiply: same layout as usd_loader.compute_scene_bounds
        wx = m[0] * v[0] + m[4] * v[1] + m[8] * v[2] + m[12]
        wy = m[1] * v[0] + m[5] * v[1] + m[9] * v[2] + m[13]
        wz = m[2] * v[0] + m[6] * v[1] + m[10] * v[2] + m[14]
        for axis, c in enumerate((wx, wy, wz)):
            if c < lo[axis]:
                lo[axis] = c
            if c > hi[axis]:
                hi[axis] = c

    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


# Matrix math imported from math_utils (mat4_inverse, mat4_multiply, mat4_transform_point)
