"""Shared math utilities for the CarWash-2 viewport.

Provides column-major 4x4 matrix operations and vertex normal computation
used across viewport.py, selection.py, environment.py, usd_loader.py, and
mesh_importers.py.  Consolidating here avoids 3x duplicate matrix code and
2x duplicate normal code.

All matrices use OpenGL column-major layout:
    index:  0  1  2  3 | 4  5  6  7 | 8  9 10 11 | 12 13 14 15
    means: [col0       | col1       | col2       | col3       ]
    element(row, col) = m[col * 4 + row]
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Boundary validators
#
# math_utils functions are called from multiple sibling modules with
# user-supplied or computed inputs.  A wrong-shape matrix or NaN entry
# silently corrupts every downstream draw call without raising; these
# helpers fail fast at the boundary instead.
# ---------------------------------------------------------------------------

def _check_mat4(m, name: str = "matrix") -> None:
    """Raise ValueError unless *m* is a 16-element sequence of finite floats."""
    if not hasattr(m, "__len__"):
        raise ValueError(f"{name}: expected a sized sequence, got {type(m).__name__}")
    if len(m) != 16:
        raise ValueError(f"{name}: expected 16 elements, got {len(m)}")
    for i, v in enumerate(m):
        if not isinstance(v, (int, float)) or v != v or v in (math.inf, -math.inf):
            raise ValueError(f"{name}[{i}]: non-finite or non-numeric ({v!r})")


def _check_vec3(v, name: str = "vector") -> None:
    """Raise ValueError unless *v* is a 3-element sequence of finite floats."""
    if not hasattr(v, "__len__"):
        raise ValueError(f"{name}: expected a sized sequence, got {type(v).__name__}")
    if len(v) != 3:
        raise ValueError(f"{name}: expected 3 elements, got {len(v)}")
    for i, x in enumerate(v):
        if not isinstance(x, (int, float)) or x != x or x in (math.inf, -math.inf):
            raise ValueError(f"{name}[{i}]: non-finite or non-numeric ({x!r})")


# ---------------------------------------------------------------------------
# Vector operations
# ---------------------------------------------------------------------------

def vec3_normalize(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Return a unit-length (x, y, z) tuple; falls back to (0, 1, 0)."""
    length = math.sqrt(x * x + y * y + z * z)
    if length > 1e-10:
        return (x / length, y / length, z / length)
    return (0.0, 1.0, 0.0)


def vec3_normalize_tuple(v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Normalize a 3-tuple. Returns (0, -1, 0) for zero vectors."""
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-12:
        return (0.0, -1.0, 0.0)
    inv = 1.0 / length
    return (x * inv, y * inv, z * inv)


# ---------------------------------------------------------------------------
# 4x4 matrix operations (column-major)
# ---------------------------------------------------------------------------

def mat4_multiply(a: list[float], b: list[float]) -> list[float]:
    """Multiply two column-major 4x4 matrices: result = A * B."""
    _check_mat4(a, "mat4_multiply.a")
    _check_mat4(b, "mat4_multiply.b")
    result = [0.0] * 16
    for col in range(4):
        for row in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + row] * b[col * 4 + k]
            result[col * 4 + row] = s
    return result


def mat4_inverse(m: list[float]) -> list[float]:
    """Invert a column-major 4x4 matrix using cofactor expansion.

    Returns the inverse matrix.  Raises ValueError if the matrix is singular
    or malformed (wrong length, non-finite entries).
    """
    _check_mat4(m, "mat4_inverse.m")

    def a(r: int, c: int) -> float:
        return m[c * 4 + r]

    s0 = a(0, 0) * a(1, 1) - a(1, 0) * a(0, 1)
    s1 = a(0, 0) * a(1, 2) - a(1, 0) * a(0, 2)
    s2 = a(0, 0) * a(1, 3) - a(1, 0) * a(0, 3)
    s3 = a(0, 1) * a(1, 2) - a(1, 1) * a(0, 2)
    s4 = a(0, 1) * a(1, 3) - a(1, 1) * a(0, 3)
    s5 = a(0, 2) * a(1, 3) - a(1, 2) * a(0, 3)

    c5 = a(2, 2) * a(3, 3) - a(3, 2) * a(2, 3)
    c4 = a(2, 1) * a(3, 3) - a(3, 1) * a(2, 3)
    c3 = a(2, 1) * a(3, 2) - a(3, 1) * a(2, 2)
    c2 = a(2, 0) * a(3, 3) - a(3, 0) * a(2, 3)
    c1 = a(2, 0) * a(3, 2) - a(3, 0) * a(2, 2)
    c0 = a(2, 0) * a(3, 1) - a(3, 0) * a(2, 1)

    det = s0 * c5 - s1 * c4 + s2 * c3 + s3 * c2 - s4 * c1 + s5 * c0
    if abs(det) < 1e-14:
        raise ValueError("Singular matrix -- cannot invert")

    inv_det = 1.0 / det

    # Adjugate matrix rows (transposed cofactor), then stored column-major.
    inv_rows = [
        [
            ( a(1, 1) * c5 - a(1, 2) * c4 + a(1, 3) * c3) * inv_det,
            (-a(0, 1) * c5 + a(0, 2) * c4 - a(0, 3) * c3) * inv_det,
            ( a(3, 1) * s5 - a(3, 2) * s4 + a(3, 3) * s3) * inv_det,
            (-a(2, 1) * s5 + a(2, 2) * s4 - a(2, 3) * s3) * inv_det,
        ],
        [
            (-a(1, 0) * c5 + a(1, 2) * c2 - a(1, 3) * c1) * inv_det,
            ( a(0, 0) * c5 - a(0, 2) * c2 + a(0, 3) * c1) * inv_det,
            (-a(3, 0) * s5 + a(3, 2) * s2 - a(3, 3) * s1) * inv_det,
            ( a(2, 0) * s5 - a(2, 2) * s2 + a(2, 3) * s1) * inv_det,
        ],
        [
            ( a(1, 0) * c4 - a(1, 1) * c2 + a(1, 3) * c0) * inv_det,
            (-a(0, 0) * c4 + a(0, 1) * c2 - a(0, 3) * c0) * inv_det,
            ( a(3, 0) * s4 - a(3, 1) * s2 + a(3, 3) * s0) * inv_det,
            (-a(2, 0) * s4 + a(2, 1) * s2 - a(2, 3) * s0) * inv_det,
        ],
        [
            (-a(1, 0) * c3 + a(1, 1) * c1 - a(1, 2) * c0) * inv_det,
            ( a(0, 0) * c3 - a(0, 1) * c1 + a(0, 2) * c0) * inv_det,
            (-a(3, 0) * s3 + a(3, 1) * s1 - a(3, 2) * s0) * inv_det,
            ( a(2, 0) * s3 - a(2, 1) * s1 + a(2, 2) * s0) * inv_det,
        ],
    ]

    # Store column-major
    result = [0.0] * 16
    for row in range(4):
        for col in range(4):
            result[col * 4 + row] = inv_rows[row][col]
    return result


def mat4_inverse_safe(m: list[float]) -> list[float] | None:
    """Invert a column-major 4x4 matrix.  Returns None if singular.

    This is the environment.py-style variant that returns None instead of
    raising, for use in rendering paths where a singular matrix is recoverable.
    """
    try:
        return mat4_inverse(m)
    except ValueError:
        return None


def translation_matrix(tx: float, ty: float, tz: float) -> list[float]:
    """4x4 translation matrix, column-major."""
    return [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        tx, ty, tz, 1,
    ]


def scale_matrix(sx: float, sy: float, sz: float) -> list[float]:
    """4x4 scale matrix, column-major."""
    return [
        sx, 0, 0, 0,
        0, sy, 0, 0,
        0, 0, sz, 0,
        0, 0, 0, 1,
    ]


def scale_matrix_uniform(s: float) -> list[float]:
    """4x4 uniform scale matrix, column-major."""
    return [
        s, 0, 0, 0,
        0, s, 0, 0,
        0, 0, s, 0,
        0, 0, 0, 1,
    ]


def mat4_transform_point(
    m: list[float], x: float, y: float, z: float,
) -> tuple[float, float, float]:
    """Transform a point (x, y, z, w=1) by a column-major 4x4 matrix.

    Performs perspective division (divide by w) for projection unproject.

    Raises ValueError when ``|w|`` is below 1e-12: returning the un-divided
    homogeneous coordinates was the previous behavior, but it silently
    produced a wildly off-scale result and downstream code (ray casting,
    selection picking) had no way to tell projection had failed.
    """
    _check_mat4(m, "mat4_transform_point.m")
    rx = m[0] * x + m[4] * y + m[8] * z + m[12]
    ry = m[1] * x + m[5] * y + m[9] * z + m[13]
    rz = m[2] * x + m[6] * y + m[10] * z + m[14]
    rw = m[3] * x + m[7] * y + m[11] * z + m[15]

    if abs(rw) < 1e-12:
        raise ValueError(
            f"mat4_transform_point: homogeneous w near zero ({rw!r}); "
            "projection is degenerate"
        )
    return (rx / rw, ry / rw, rz / rw)


_LOOK_AT_EPS = 1e-8


def look_at(eye: tuple, target: tuple, up: tuple) -> list[float]:
    """Build a look-at view matrix (column-major for GL).

    Robust against degenerate inputs: if ``eye == target`` we default
    forward to (0, 0, -1); if ``forward`` is parallel to ``up`` we
    fall back to a perpendicular up axis so ``cross(forward, up)`` is
    non-zero.  The returned matrix is always finite.
    """
    _check_vec3(eye, "look_at.eye")
    _check_vec3(target, "look_at.target")
    _check_vec3(up, "look_at.up")

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def length(v):
        return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    def normalize(v, fallback):
        l = length(v)
        if l < _LOOK_AT_EPS:
            return fallback
        return (v[0] / l, v[1] / l, v[2] / l)

    def cross(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    # Forward: target - eye. Zero-length when eye == target → default to -Z.
    f = normalize(sub(target, eye), fallback=(0.0, 0.0, -1.0))

    # Side: cross(f, up). Zero-length when f is parallel to up. Pick an
    # up axis that's perpendicular to f as a fallback.
    s_raw = cross(f, up)
    if length(s_raw) < _LOOK_AT_EPS:
        # Choose a fallback up axis that is not parallel to f.
        alt_up = (0.0, 0.0, 1.0) if abs(f[1]) > 0.9 else (0.0, 1.0, 0.0)
        s_raw = cross(f, alt_up)
    s = normalize(s_raw, fallback=(1.0, 0.0, 0.0))

    u = cross(s, f)

    return [
        s[0], u[0], -f[0], 0,
        s[1], u[1], -f[1], 0,
        s[2], u[2], -f[2], 0,
        -dot(s, eye), -dot(u, eye), dot(f, eye), 1,
    ]


# ---------------------------------------------------------------------------
# Geometry: vertex normal computation
# ---------------------------------------------------------------------------

def compute_vertex_normals(
    vertices: list[tuple],
    triangles: list[int],
) -> list[tuple]:
    """Compute smooth per-vertex normals by accumulating face normals.

    Each triangle's (un-normalised) face normal is added to all three of its
    vertices.  The accumulated vectors are normalised at the end, producing
    area-weighted smooth normals.  Degenerate triangles contribute zero and
    are harmless.
    """
    accum = [[0.0, 0.0, 0.0] for _ in range(len(vertices))]

    for i in range(0, len(triangles), 3):
        i0, i1, i2 = triangles[i], triangles[i + 1], triangles[i + 2]
        p0 = vertices[i0]
        p1 = vertices[i1]
        p2 = vertices[i2]

        # Edge vectors
        e1x = p1[0] - p0[0]
        e1y = p1[1] - p0[1]
        e1z = p1[2] - p0[2]
        e2x = p2[0] - p0[0]
        e2y = p2[1] - p0[1]
        e2z = p2[2] - p0[2]

        # Cross product (un-normalised face normal)
        nx = e1y * e2z - e1z * e2y
        ny = e1z * e2x - e1x * e2z
        nz = e1x * e2y - e1y * e2x

        for vi in (i0, i1, i2):
            accum[vi][0] += nx
            accum[vi][1] += ny
            accum[vi][2] += nz

    return [vec3_normalize(a[0], a[1], a[2]) for a in accum]
