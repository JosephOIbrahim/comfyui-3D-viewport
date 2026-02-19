"""Shared fixtures and sys.path setup for the test suite.

src/ has no __init__.py -- modules use bare imports like `from math_utils import ...`.
We insert src/ at the front of sys.path so pytest can import them the same way.
"""

import sys
from pathlib import Path

# Insert src/ at front of sys.path so bare imports work
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


import pytest


# ---------------------------------------------------------------------------
# Matrix fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def identity_matrix():
    """16-float column-major identity matrix."""
    return [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ]


@pytest.fixture
def translation_3_4_5():
    """Translation matrix for (3, 4, 5)."""
    return [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        3, 4, 5, 1,
    ]


# ---------------------------------------------------------------------------
# Geometry fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def triangle_vertices():
    """A simple triangle in the XY plane."""
    return [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    ]


@pytest.fixture
def triangle_indices():
    """Indices for a single triangle."""
    return [0, 1, 2]


@pytest.fixture
def cube_vertices():
    """8 vertices of a unit cube centered at origin."""
    return [
        (-0.5, -0.5, -0.5),
        ( 0.5, -0.5, -0.5),
        ( 0.5,  0.5, -0.5),
        (-0.5,  0.5, -0.5),
        (-0.5, -0.5,  0.5),
        ( 0.5, -0.5,  0.5),
        ( 0.5,  0.5,  0.5),
        (-0.5,  0.5,  0.5),
    ]


@pytest.fixture
def cube_triangles():
    """12 triangles (36 indices) for a unit cube."""
    return [
        # Front face
        0, 1, 2,  0, 2, 3,
        # Back face
        4, 6, 5,  4, 7, 6,
        # Top face
        3, 2, 6,  3, 6, 7,
        # Bottom face
        0, 5, 1,  0, 4, 5,
        # Right face
        1, 5, 6,  1, 6, 2,
        # Left face
        0, 3, 7,  0, 7, 4,
    ]
