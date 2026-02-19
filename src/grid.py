"""World-space ground grid and axis gizmo renderer.

Renders a 21x21 ground grid on the XZ plane and an RGB axis gizmo at the
origin using OpenGL 3.3 Core Profile.  Designed to be overlaid on the main
viewport scene.
"""

from __future__ import annotations

import ctypes
from typing import List

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_COMPILE_STATUS,
    GL_DEPTH_TEST,
    GL_FALSE,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_LINES,
    GL_LINK_STATUS,
    GL_STATIC_DRAW,
    GL_VERTEX_SHADER,
    glAttachShader,
    glBindBuffer,
    glBindVertexArray,
    glBufferData,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteBuffers,
    glDeleteProgram,
    glDeleteShader,
    glDeleteVertexArrays,
    glDisable,
    glDrawArrays,
    glEnable,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenVertexArrays,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glShaderSource,
    glUniformMatrix4fv,
    glUseProgram,
    glVertexAttribPointer,
)

# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

_VERTEX_SHADER_SRC = """
#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aColor;
uniform mat4 uView;
uniform mat4 uProjection;
out vec3 vColor;
void main() {
    vColor = aColor;
    gl_Position = uProjection * uView * vec4(aPos, 1.0);
}
"""

_FRAGMENT_SHADER_SRC = """
#version 330 core
in vec3 vColor;
out vec4 FragColor;
void main() {
    FragColor = vec4(vColor, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile_shader(source: str, shader_type: int) -> int:
    """Compile a GLSL shader and return its handle.

    Raises ``RuntimeError`` if compilation fails.
    """
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if glGetShaderiv(shader, GL_COMPILE_STATUS) != 1:
        info = glGetShaderInfoLog(shader).decode("utf-8", errors="replace")
        glDeleteShader(shader)
        raise RuntimeError(f"Shader compilation failed:\n{info}")
    return shader


def _link_program(vertex_shader: int, fragment_shader: int) -> int:
    """Link vertex and fragment shaders into a program.

    Both shaders are detached and flagged for deletion after linking so that
    the caller only needs to manage the program handle.

    Raises ``RuntimeError`` if linking fails.
    """
    program = glCreateProgram()
    glAttachShader(program, vertex_shader)
    glAttachShader(program, fragment_shader)
    glLinkProgram(program)
    if glGetProgramiv(program, GL_LINK_STATUS) != 1:
        info = glGetProgramInfoLog(program).decode("utf-8", errors="replace")
        glDeleteProgram(program)
        raise RuntimeError(f"Program linking failed:\n{info}")
    glDeleteShader(vertex_shader)
    glDeleteShader(fragment_shader)
    return program


def _upload_geometry(data: np.ndarray) -> tuple[int, int]:
    """Upload interleaved pos+color float data into a new VAO/VBO pair.

    The vertex layout is::

        location 0: vec3 aPos   (offset 0,  stride 24)
        location 1: vec3 aColor (offset 12, stride 24)

    Returns ``(vao, vbo)``.
    """
    vao = glGenVertexArrays(1)
    vbo = glGenBuffers(1)

    glBindVertexArray(vao)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)

    stride = 6 * 4  # 6 floats * 4 bytes = 24

    # aPos — location 0
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
    glEnableVertexAttribArray(0)

    # aColor — location 1
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
    glEnableVertexAttribArray(1)

    glBindBuffer(GL_ARRAY_BUFFER, 0)
    glBindVertexArray(0)

    return vao, vbo


# ---------------------------------------------------------------------------
# GridRenderer
# ---------------------------------------------------------------------------


class GridRenderer:
    """Renders a ground grid and an origin axis gizmo.

    Typical usage::

        renderer = GridRenderer()
        renderer.setup()
        # ... per frame ...
        renderer.draw(view_matrix, proj_matrix)
        # ... on shutdown ...
        renderer.cleanup()
    """

    def __init__(self) -> None:
        self._program: int = 0
        self._view_loc: int = -1
        self._proj_loc: int = -1

        self._grid_vao: int = 0
        self._grid_vbo: int = 0
        self._grid_vertex_count: int = 0

        self._axis_vao: int = 0
        self._axis_vbo: int = 0

    # -- geometry builders ---------------------------------------------------

    def _build_grid_geometry(self) -> list[float]:
        """Generate grid line vertices: ``[x, y, z, r, g, b, ...]``."""
        verts: list[float] = []
        extent = 10

        for i in range(-extent, extent + 1):
            if i == 0:
                # Z-axis line (runs along Z at X=0): Blue
                verts.extend([0, 0, -extent, 0.2, 0.2, 0.8])
                verts.extend([0, 0, extent, 0.2, 0.2, 0.8])
                # X-axis line (runs along X at Z=0): Red
                verts.extend([-extent, 0, 0, 0.8, 0.2, 0.2])
                verts.extend([extent, 0, 0, 0.8, 0.2, 0.2])
            else:
                if i % 5 == 0:
                    color = (0.4, 0.4, 0.4)  # major
                else:
                    color = (0.3, 0.3, 0.3)  # minor

                # Lines parallel to Z (varying X)
                verts.extend([i, 0, -extent, *color])
                verts.extend([i, 0, extent, *color])
                # Lines parallel to X (varying Z)
                verts.extend([-extent, 0, i, *color])
                verts.extend([extent, 0, i, *color])

        return verts

    def _build_axis_geometry(self) -> list[float]:
        """Generate axis gizmo vertices at origin."""
        length = 0.5
        return [
            # X axis: Red
            0, 0, 0, 1, 0, 0,
            length, 0, 0, 1, 0, 0,
            # Y axis: Green
            0, 0, 0, 0, 1, 0,
            0, length, 0, 0, 1, 0,
            # Z axis: Blue
            0, 0, 0, 0, 0, 1,
            0, 0, length, 0, 0, 1,
        ]

    # -- lifecycle -----------------------------------------------------------

    def setup(self) -> None:
        """Compile shaders and upload grid / axis geometry to the GPU."""
        # Shaders
        vs = _compile_shader(_VERTEX_SHADER_SRC, GL_VERTEX_SHADER)
        fs = _compile_shader(_FRAGMENT_SHADER_SRC, GL_FRAGMENT_SHADER)
        self._program = _link_program(vs, fs)

        self._view_loc = glGetUniformLocation(self._program, "uView")
        self._proj_loc = glGetUniformLocation(self._program, "uProjection")

        # Grid geometry
        grid_data = np.array(self._build_grid_geometry(), dtype=np.float32)
        self._grid_vertex_count = len(grid_data) // 6
        self._grid_vao, self._grid_vbo = _upload_geometry(grid_data)

        # Axis geometry
        axis_data = np.array(self._build_axis_geometry(), dtype=np.float32)
        self._axis_vao, self._axis_vbo = _upload_geometry(axis_data)

    def draw(self, view_matrix: List[float], proj_matrix: List[float]) -> None:
        """Render the grid and axis gizmo.

        Parameters
        ----------
        view_matrix:
            Column-major 4x4 view matrix as a flat list of 16 floats.
        proj_matrix:
            Column-major 4x4 projection matrix as a flat list of 16 floats.
        """
        glUseProgram(self._program)

        # Upload uniforms
        glUniformMatrix4fv(
            self._view_loc, 1, GL_FALSE, (ctypes.c_float * 16)(*view_matrix)
        )
        glUniformMatrix4fv(
            self._proj_loc, 1, GL_FALSE, (ctypes.c_float * 16)(*proj_matrix)
        )

        # Draw ground grid (with depth test enabled)
        glBindVertexArray(self._grid_vao)
        glDrawArrays(GL_LINES, 0, self._grid_vertex_count)

        # Draw axis gizmo on top of everything
        glDisable(GL_DEPTH_TEST)
        glBindVertexArray(self._axis_vao)
        glDrawArrays(GL_LINES, 0, 6)  # 3 lines * 2 vertices
        glEnable(GL_DEPTH_TEST)

        glBindVertexArray(0)
        glUseProgram(0)

    def cleanup(self) -> None:
        """Delete all GL resources owned by this renderer."""
        if self._grid_vao:
            glDeleteVertexArrays(1, [self._grid_vao])
            self._grid_vao = 0
        if self._grid_vbo:
            glDeleteBuffers(1, [self._grid_vbo])
            self._grid_vbo = 0
        if self._axis_vao:
            glDeleteVertexArrays(1, [self._axis_vao])
            self._axis_vao = 0
        if self._axis_vbo:
            glDeleteBuffers(1, [self._axis_vbo])
            self._axis_vbo = 0
        if self._program:
            glDeleteProgram(self._program)
            self._program = 0
