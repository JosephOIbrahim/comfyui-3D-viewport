"""Tests for src/math_utils.py -- vector and matrix operations."""

import math

import pytest

from math_utils import (
    vec3_normalize,
    vec3_normalize_tuple,
    mat4_multiply,
    mat4_inverse,
    mat4_inverse_safe,
    translation_matrix,
    scale_matrix,
    scale_matrix_uniform,
    mat4_transform_point,
    look_at,
    compute_vertex_normals,
)


# ---------------------------------------------------------------------------
# vec3_normalize
# ---------------------------------------------------------------------------

class TestVec3Normalize:
    def test_unit_x(self):
        assert vec3_normalize(1, 0, 0) == (1.0, 0.0, 0.0)

    def test_non_unit_vector(self):
        x, y, z = vec3_normalize(3, 4, 0)
        assert x == pytest.approx(0.6, rel=1e-6)
        assert y == pytest.approx(0.8, rel=1e-6)
        assert z == pytest.approx(0.0, abs=1e-10)

    def test_zero_vector_fallback(self):
        assert vec3_normalize(0, 0, 0) == (0.0, 1.0, 0.0)

    def test_result_is_unit_length(self):
        x, y, z = vec3_normalize(1, 2, 3)
        length = math.sqrt(x * x + y * y + z * z)
        assert length == pytest.approx(1.0, rel=1e-6)


class TestVec3NormalizeTuple:
    def test_basic(self):
        result = vec3_normalize_tuple((0, 3, 4))
        assert result[1] == pytest.approx(0.6, rel=1e-6)
        assert result[2] == pytest.approx(0.8, rel=1e-6)

    def test_zero_vector_fallback(self):
        assert vec3_normalize_tuple((0, 0, 0)) == (0.0, -1.0, 0.0)


# ---------------------------------------------------------------------------
# Matrix operations
# ---------------------------------------------------------------------------

class TestMat4Multiply:
    def test_identity_times_identity(self, identity_matrix):
        result = mat4_multiply(identity_matrix, identity_matrix)
        for i in range(16):
            assert result[i] == pytest.approx(identity_matrix[i], abs=1e-10)

    def test_identity_times_translation(self, identity_matrix, translation_3_4_5):
        result = mat4_multiply(identity_matrix, translation_3_4_5)
        for i in range(16):
            assert result[i] == pytest.approx(translation_3_4_5[i], abs=1e-10)

    def test_translation_composition(self):
        t1 = translation_matrix(1, 0, 0)
        t2 = translation_matrix(0, 2, 0)
        result = mat4_multiply(t1, t2)
        # Combined translation should be (1, 2, 0)
        assert result[12] == pytest.approx(1.0, abs=1e-10)
        assert result[13] == pytest.approx(2.0, abs=1e-10)
        assert result[14] == pytest.approx(0.0, abs=1e-10)


class TestMat4Inverse:
    def test_identity_inverse(self, identity_matrix):
        result = mat4_inverse(identity_matrix)
        for i in range(16):
            assert result[i] == pytest.approx(identity_matrix[i], abs=1e-10)

    def test_translation_inverse(self, translation_3_4_5):
        inv = mat4_inverse(translation_3_4_5)
        assert inv[12] == pytest.approx(-3.0, abs=1e-10)
        assert inv[13] == pytest.approx(-4.0, abs=1e-10)
        assert inv[14] == pytest.approx(-5.0, abs=1e-10)

    def test_roundtrip(self, translation_3_4_5, identity_matrix):
        inv = mat4_inverse(translation_3_4_5)
        result = mat4_multiply(translation_3_4_5, inv)
        for i in range(16):
            assert result[i] == pytest.approx(identity_matrix[i], abs=1e-10)

    def test_singular_raises(self):
        singular = [0.0] * 16
        with pytest.raises(ValueError, match="Singular"):
            mat4_inverse(singular)

    def test_scale_inverse(self):
        s = scale_matrix(2, 3, 4)
        inv = mat4_inverse(s)
        assert inv[0] == pytest.approx(0.5, abs=1e-10)
        assert inv[5] == pytest.approx(1.0 / 3.0, abs=1e-10)
        assert inv[10] == pytest.approx(0.25, abs=1e-10)


class TestMat4InverseSafe:
    def test_returns_none_for_singular(self):
        assert mat4_inverse_safe([0.0] * 16) is None

    def test_returns_inverse_for_valid(self, identity_matrix):
        result = mat4_inverse_safe(identity_matrix)
        assert result is not None


# ---------------------------------------------------------------------------
# Factory matrices
# ---------------------------------------------------------------------------

class TestTranslationMatrix:
    def test_basic(self):
        m = translation_matrix(1, 2, 3)
        assert m[12] == 1.0
        assert m[13] == 2.0
        assert m[14] == 3.0
        assert m[0] == 1.0 and m[5] == 1.0 and m[10] == 1.0 and m[15] == 1.0


class TestScaleMatrix:
    def test_non_uniform(self):
        m = scale_matrix(2, 3, 4)
        assert m[0] == 2.0
        assert m[5] == 3.0
        assert m[10] == 4.0

    def test_uniform(self):
        m = scale_matrix_uniform(5)
        assert m[0] == 5.0 and m[5] == 5.0 and m[10] == 5.0


# ---------------------------------------------------------------------------
# Transform point
# ---------------------------------------------------------------------------

class TestMat4TransformPoint:
    def test_identity(self, identity_matrix):
        result = mat4_transform_point(identity_matrix, 1, 2, 3)
        assert result == pytest.approx((1, 2, 3), abs=1e-10)

    def test_translation(self, translation_3_4_5):
        result = mat4_transform_point(translation_3_4_5, 1, 1, 1)
        assert result == pytest.approx((4, 5, 6), abs=1e-10)


# ---------------------------------------------------------------------------
# look_at
# ---------------------------------------------------------------------------

class TestLookAt:
    def test_returns_16_floats(self):
        m = look_at((0, 0, 5), (0, 0, 0), (0, 1, 0))
        assert len(m) == 16

    def test_looking_down_negative_z(self):
        m = look_at((0, 0, 5), (0, 0, 0), (0, 1, 0))
        # Forward is -Z in view space. The view matrix should have
        # a negative translation along the forward axis.
        assert m[14] == pytest.approx(-5.0, rel=1e-4)

    def test_eye_equals_target_returns_finite_matrix(self):
        """3a28675c regression: eye == target previously produced NaN."""
        m = look_at((1.0, 2.0, 3.0), (1.0, 2.0, 3.0), (0.0, 1.0, 0.0))
        assert all(math.isfinite(v) for v in m), \
            "look_at must produce a finite matrix even when eye == target"

    def test_up_parallel_to_forward_returns_finite_matrix(self):
        """3a28675c regression: forward parallel to up previously produced
        a zero rotation block. Looking straight up the +Y axis with up = +Y."""
        m = look_at((0.0, 0.0, 0.0), (0.0, 5.0, 0.0), (0.0, 1.0, 0.0))
        assert all(math.isfinite(v) for v in m)
        # Side vector (matrix col 0 rows 0..2 = m[0], m[4], m[8] in
        # column-major) must be unit-ish, not zero.
        side_len = math.sqrt(m[0] ** 2 + m[4] ** 2 + m[8] ** 2)
        assert side_len > 0.5, \
            "side vector collapsed; cross(f, up) fallback failed"

    def test_up_antiparallel_to_forward_returns_finite_matrix(self):
        """Forward = -up should also get a fallback up axis."""
        m = look_at((0.0, 5.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        assert all(math.isfinite(v) for v in m)

    def test_rejects_non_finite_eye(self):
        with pytest.raises(ValueError):
            look_at((float("nan"), 0.0, 0.0), (0, 0, 0), (0, 1, 0))


# ---------------------------------------------------------------------------
# compute_vertex_normals
# ---------------------------------------------------------------------------

class TestComputeVertexNormals:
    def test_single_triangle(self, triangle_vertices, triangle_indices):
        normals = compute_vertex_normals(triangle_vertices, triangle_indices)
        assert len(normals) == 3
        # XY plane triangle -- normal should be along Z
        for nx, ny, nz in normals:
            assert abs(nz) == pytest.approx(1.0, rel=1e-6)
            assert abs(nx) == pytest.approx(0.0, abs=1e-6)
            assert abs(ny) == pytest.approx(0.0, abs=1e-6)

    def test_normals_are_unit_length(self, cube_vertices, cube_triangles):
        normals = compute_vertex_normals(cube_vertices, cube_triangles)
        for nx, ny, nz in normals:
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            assert length == pytest.approx(1.0, rel=1e-4)

    def test_empty_input(self):
        normals = compute_vertex_normals([], [])
        assert normals == []


# ---------------------------------------------------------------------------
# Boundary validators (61e3e9f6 regression)
# ---------------------------------------------------------------------------

class TestBoundaryValidation:
    """Wrong-shape or NaN inputs must raise ValueError instead of silently
    producing corrupt math."""

    def test_mat4_multiply_rejects_wrong_length(self, identity_matrix):
        with pytest.raises(ValueError, match="expected 16 elements"):
            mat4_multiply([1.0, 0.0, 0.0], identity_matrix)

    def test_mat4_multiply_rejects_nan(self, identity_matrix):
        bad = list(identity_matrix)
        bad[5] = float("nan")
        with pytest.raises(ValueError, match="non-finite"):
            mat4_multiply(bad, identity_matrix)

    def test_mat4_multiply_rejects_inf(self, identity_matrix):
        bad = list(identity_matrix)
        bad[0] = float("inf")
        with pytest.raises(ValueError, match="non-finite"):
            mat4_multiply(identity_matrix, bad)

    def test_mat4_inverse_rejects_wrong_length(self):
        with pytest.raises(ValueError, match="expected 16 elements"):
            mat4_inverse([0.0] * 9)

    def test_mat4_transform_point_rejects_wrong_length(self):
        with pytest.raises(ValueError, match="expected 16 elements"):
            from math_utils import mat4_transform_point
            mat4_transform_point([0.0] * 4, 0.0, 0.0, 0.0)

    def test_mat4_transform_point_accepts_valid(self, translation_3_4_5):
        from math_utils import mat4_transform_point
        x, y, z = mat4_transform_point(translation_3_4_5, 0.0, 0.0, 0.0)
        assert x == 3 and y == 4 and z == 5
