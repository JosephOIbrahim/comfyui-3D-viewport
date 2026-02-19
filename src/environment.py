"""Environment map / skybox renderer for the OpenGL 3.3 Core Profile viewport.

Renders a background behind all scene geometry using a fullscreen triangle
technique (3 vertices, no index buffer, driven by gl_VertexID).  Supports
three modes:

- **gradient** -- procedural vertical gradient between two colours
- **hdri** -- equirectangular environment map sampled by view direction
- **solid** -- single flat colour

Integration pattern (inside paintGL, BEFORE drawing scene geometry)::

    env = self._environment
    env.draw(view_matrix, proj_matrix)
    # ... draw scene geometry with depth test enabled ...

The draw call disables depth writing so the background sits behind everything.
"""

from __future__ import annotations

import ctypes
import math
from typing import Dict, List, Optional, Tuple

from math_utils import mat4_inverse_safe, mat4_multiply

import numpy as np
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE,
    GL_COMPILE_STATUS,
    GL_FALSE,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_LINEAR,
    GL_LINK_STATUS,
    GL_RGB,
    GL_RGBA,
    GL_STATIC_DRAW,
    GL_TEXTURE0,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_TRUE,
    GL_UNSIGNED_BYTE,
    GL_VERTEX_SHADER,
    glActiveTexture,
    glAttachShader,
    glBindTexture,
    glBindVertexArray,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteProgram,
    glDeleteShader,
    glDeleteTextures,
    glDeleteVertexArrays,
    glDepthMask,
    glDrawArrays,
    glGenTextures,
    glGenVertexArrays,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glShaderSource,
    glTexImage2D,
    glTexParameteri,
    glUniform1i,
    glUniform3f,
    glUniformMatrix4fv,
    glUseProgram,
)

# ---------------------------------------------------------------------------
# GLSL shaders (version 330 core)
# ---------------------------------------------------------------------------

_FULLSCREEN_VERTEX_SHADER = """
#version 330 core

// Fullscreen triangle from gl_VertexID -- no VBO needed.
// Produces a triangle that covers the entire screen:
//   ID 0 -> (-1, -1)
//   ID 1 -> ( 3, -1)
//   ID 2 -> (-1,  3)

out vec2 vUV;

void main() {
    float x = float((gl_VertexID & 1) << 2) - 1.0;
    float y = float((gl_VertexID & 2) << 1) - 1.0;
    vUV = vec2(x * 0.5 + 0.5, y * 0.5 + 0.5);
    gl_Position = vec4(x, y, 1.0, 1.0);
}
"""

_GRADIENT_FRAGMENT_SHADER = """
#version 330 core

in vec2 vUV;
out vec4 FragColor;

uniform vec3 uBottomColor;
uniform vec3 uTopColor;

void main() {
    vec3 color = mix(uBottomColor, uTopColor, vUV.y);
    FragColor = vec4(color, 1.0);
}
"""

_SOLID_FRAGMENT_SHADER = """
#version 330 core

in vec2 vUV;
out vec4 FragColor;

uniform vec3 uSolidColor;

void main() {
    FragColor = vec4(uSolidColor, 1.0);
}
"""

_HDRI_FRAGMENT_SHADER = """
#version 330 core

in vec2 vUV;
out vec4 FragColor;

uniform sampler2D uEnvMap;
uniform mat4 uInvViewProj;

void main() {
    // Reconstruct clip-space position for this fragment.
    // vUV is [0,1], convert to NDC [-1,1].  Z = 1.0 (far plane).
    vec4 clip = vec4(vUV * 2.0 - 1.0, 1.0, 1.0);

    // Transform to world space via inverse view-projection.
    vec4 world = uInvViewProj * clip;
    vec3 dir = normalize(world.xyz / world.w);

    // Convert direction to equirectangular UV.
    // u = atan(z, x) mapped to [0, 1]
    // v = asin(y)    mapped to [0, 1]
    float u = atan(dir.z, dir.x) / (2.0 * 3.14159265359) + 0.5;
    float v = asin(clamp(dir.y, -1.0, 1.0)) / 3.14159265359 + 0.5;

    FragColor = texture(uEnvMap, vec2(u, v));
}
"""

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

_PRESETS: Dict[str, dict] = {
    "studio": {
        "mode": "gradient",
        "top": (0.15, 0.15, 0.22),
        "bottom": (0.08, 0.08, 0.12),
    },
    "outdoor": {
        "mode": "gradient",
        "top": (0.35, 0.55, 0.85),
        "bottom": (0.85, 0.75, 0.55),
    },
    "dark": {
        "mode": "solid",
        "color": (0.02, 0.02, 0.02),
    },
    "neutral": {
        "mode": "solid",
        "color": (0.5, 0.5, 0.5),
    },
}

# ---------------------------------------------------------------------------
# Shader helpers
# ---------------------------------------------------------------------------


def _compile_shader(source: str, shader_type: int) -> int:
    """Compile a GLSL shader and return its handle."""
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if glGetShaderiv(shader, GL_COMPILE_STATUS) != 1:
        info = glGetShaderInfoLog(shader).decode("utf-8", errors="replace")
        glDeleteShader(shader)
        raise RuntimeError(f"Environment shader compilation failed:\n{info}")
    return shader


def _link_program(vertex_shader: int, fragment_shader: int) -> int:
    """Link vertex and fragment shaders into a program."""
    program = glCreateProgram()
    glAttachShader(program, vertex_shader)
    glAttachShader(program, fragment_shader)
    glLinkProgram(program)
    if glGetProgramiv(program, GL_LINK_STATUS) != 1:
        info = glGetProgramInfoLog(program).decode("utf-8", errors="replace")
        glDeleteProgram(program)
        raise RuntimeError(f"Environment program linking failed:\n{info}")
    glDeleteShader(vertex_shader)
    glDeleteShader(fragment_shader)
    return program


# Matrix math imported from math_utils (mat4_inverse_safe, mat4_multiply)

# Aliases for internal usage (keep call sites unchanged)
_mat4_multiply = mat4_multiply
_mat4_inverse = mat4_inverse_safe


# ---------------------------------------------------------------------------
# EnvironmentMap
# ---------------------------------------------------------------------------


class EnvironmentMap:
    """Background environment renderer for the 3D viewport.

    Supports three visual modes:

    - ``"gradient"`` -- procedural vertical gradient (default)
    - ``"hdri"`` -- equirectangular environment map texture
    - ``"solid"`` -- flat single colour

    Typical lifecycle::

        env = EnvironmentMap()
        env.init_gl()              # during initializeGL
        env.draw(view, proj)       # every frame, before scene geometry
        env.cleanup()              # during cleanup / destructor
    """

    def __init__(self) -> None:
        # Shader programs (one per mode that needs a shader)
        self._gradient_program: int = 0
        self._solid_program: int = 0
        self._hdri_program: int = 0

        # Empty VAO for the fullscreen triangle (required by Core Profile)
        self._vao: int = 0

        # Texture handles
        self._gradient_texture: int = 0
        self._hdri_texture: int = 0

        # State
        self._loaded: bool = False
        self._hdri_loaded: bool = False
        self._mode: str = "gradient"
        self._gradient_colors: Tuple[Tuple[float, float, float], Tuple[float, float, float]] = (
            (0.15, 0.15, 0.22),  # top
            (0.08, 0.08, 0.12),  # bottom
        )
        self._solid_color: Tuple[float, float, float] = (0.18, 0.18, 0.20)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        """Current background mode: ``'gradient'``, ``'hdri'``, or ``'solid'``."""
        return self._mode

    @property
    def is_loaded(self) -> bool:
        """Whether GL resources have been initialised."""
        return self._loaded

    # ------------------------------------------------------------------
    # GL initialisation
    # ------------------------------------------------------------------

    def init_gl(self) -> None:
        """Compile shaders, create VAO, and build the default gradient texture.

        Must be called from within a current OpenGL context (e.g. during
        ``initializeGL``).
        """
        # --- Shader programs ---
        vs = _compile_shader(_FULLSCREEN_VERTEX_SHADER, GL_VERTEX_SHADER)
        fs_grad = _compile_shader(_GRADIENT_FRAGMENT_SHADER, GL_FRAGMENT_SHADER)
        self._gradient_program = _link_program(vs, fs_grad)

        vs = _compile_shader(_FULLSCREEN_VERTEX_SHADER, GL_VERTEX_SHADER)
        fs_solid = _compile_shader(_SOLID_FRAGMENT_SHADER, GL_FRAGMENT_SHADER)
        self._solid_program = _link_program(vs, fs_solid)

        vs = _compile_shader(_FULLSCREEN_VERTEX_SHADER, GL_VERTEX_SHADER)
        fs_hdri = _compile_shader(_HDRI_FRAGMENT_SHADER, GL_FRAGMENT_SHADER)
        self._hdri_program = _link_program(vs, fs_hdri)

        # --- Empty VAO (Core Profile requires a bound VAO for any draw) ---
        self._vao = glGenVertexArrays(1)

        # --- Default gradient texture ---
        self._create_gradient_texture()

        self._loaded = True

    # ------------------------------------------------------------------
    # Gradient texture
    # ------------------------------------------------------------------

    def _create_gradient_texture(self) -> None:
        """Create (or recreate) a 1x256 vertical gradient texture from current colours."""
        top_r, top_g, top_b = self._gradient_colors[0]
        bot_r, bot_g, bot_b = self._gradient_colors[1]

        # Build 256-row gradient (bottom row = index 0, top row = index 255)
        pixels = bytearray(256 * 3)
        for i in range(256):
            t = i / 255.0
            pixels[i * 3 + 0] = int(round((bot_r + (top_r - bot_r) * t) * 255.0))
            pixels[i * 3 + 1] = int(round((bot_g + (top_g - bot_g) * t) * 255.0))
            pixels[i * 3 + 2] = int(round((bot_b + (top_b - bot_b) * t) * 255.0))

        if self._gradient_texture == 0:
            self._gradient_texture = glGenTextures(1)

        glBindTexture(GL_TEXTURE_2D, self._gradient_texture)
        glTexImage2D(
            GL_TEXTURE_2D, 0, GL_RGB,
            1, 256, 0,
            GL_RGB, GL_UNSIGNED_BYTE, bytes(pixels),
        )
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)

    # ------------------------------------------------------------------
    # HDRI loading
    # ------------------------------------------------------------------

    def load_hdri(self, file_path: str) -> bool:
        """Load an equirectangular environment map from an image file.

        Supports any format that Qt's ``QImage`` can read (PNG, JPG, BMP,
        TGA, etc.).  Sets mode to ``"hdri"`` on success.

        Parameters
        ----------
        file_path:
            Path to the image file.

        Returns
        -------
        bool
            ``True`` if the image was loaded and uploaded successfully.
        """
        try:
            from PySide6.QtGui import QImage
        except ImportError:
            print("Environment: PySide6 not available -- cannot load HDRI.")
            return False

        image = QImage(file_path)
        if image.isNull():
            print(f"Environment: failed to load image '{file_path}'.")
            return False

        # Convert to RGB888 for consistent upload
        image = image.convertToFormat(QImage.Format.Format_RGB888)
        width = image.width()
        height = image.height()

        # QImage stores rows top-to-bottom; OpenGL expects bottom-to-top.
        image = image.mirrored(False, True)

        # Extract raw bytes
        ptr = image.constBits()
        # PySide6 returns a memoryview or bytes-like object
        raw_bytes = bytes(ptr)

        if self._hdri_texture == 0:
            self._hdri_texture = glGenTextures(1)

        glBindTexture(GL_TEXTURE_2D, self._hdri_texture)
        glTexImage2D(
            GL_TEXTURE_2D, 0, GL_RGB,
            width, height, 0,
            GL_RGB, GL_UNSIGNED_BYTE, raw_bytes,
        )
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)

        self._hdri_loaded = True
        self._mode = "hdri"
        print(f"Environment: loaded HDRI '{file_path}' ({width}x{height}).")
        return True

    # ------------------------------------------------------------------
    # Mode configuration
    # ------------------------------------------------------------------

    def set_gradient(
        self,
        top_color: Tuple[float, float, float],
        bottom_color: Tuple[float, float, float],
    ) -> None:
        """Set a procedural vertical gradient background.

        Parameters
        ----------
        top_color:
            RGB colour at the top of the viewport (0-1 per channel).
        bottom_color:
            RGB colour at the bottom of the viewport (0-1 per channel).
        """
        self._gradient_colors = (top_color, bottom_color)
        self._mode = "gradient"
        if self._loaded:
            self._create_gradient_texture()

    def set_solid(self, color: Tuple[float, float, float]) -> None:
        """Set a flat solid-colour background.

        Parameters
        ----------
        color:
            RGB colour (0-1 per channel).
        """
        self._solid_color = color
        self._mode = "solid"

    def set_preset(self, name: str) -> None:
        """Apply a named background preset.

        Available presets: ``"studio"``, ``"outdoor"``, ``"dark"``, ``"neutral"``.

        Parameters
        ----------
        name:
            Preset name (case-insensitive).

        Raises
        ------
        ValueError
            If the preset name is not recognised.
        """
        key = name.lower()
        if key not in _PRESETS:
            available = ", ".join(sorted(_PRESETS.keys()))
            raise ValueError(
                f"Unknown environment preset '{name}'. "
                f"Available: {available}"
            )

        preset = _PRESETS[key]
        mode = preset["mode"]

        if mode == "gradient":
            self.set_gradient(preset["top"], preset["bottom"])
        elif mode == "solid":
            self.set_solid(preset["color"])

    def cycle_mode(self) -> str:
        """Cycle to the next background mode and return its name.

        Order: ``"gradient"`` -> ``"hdri"`` (if loaded) -> ``"solid"`` -> ...
        """
        order = ["gradient", "solid"]
        if self._hdri_loaded:
            order = ["gradient", "hdri", "solid"]

        try:
            idx = order.index(self._mode)
        except ValueError:
            idx = -1

        self._mode = order[(idx + 1) % len(order)]
        return self._mode

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, view_matrix: List[float], proj_matrix: List[float]) -> None:
        """Render the environment background.

        Must be called **before** scene geometry so that depth-tested
        objects draw on top.

        Parameters
        ----------
        view_matrix:
            Column-major 4x4 view matrix (flat list of 16 floats).
        proj_matrix:
            Column-major 4x4 projection matrix (flat list of 16 floats).
        """
        if not self._loaded:
            return

        # Disable depth writing so background is always behind geometry.
        glDepthMask(GL_FALSE)

        if self._mode == "gradient":
            self._draw_gradient()
        elif self._mode == "solid":
            self._draw_solid()
        elif self._mode == "hdri" and self._hdri_loaded:
            self._draw_hdri(view_matrix, proj_matrix)

        # Restore depth writing for subsequent scene draws.
        glDepthMask(GL_TRUE)

    def _draw_gradient(self) -> None:
        """Draw the gradient background using uniform colours."""
        glUseProgram(self._gradient_program)

        top = self._gradient_colors[0]
        bot = self._gradient_colors[1]
        loc_top = glGetUniformLocation(self._gradient_program, "uTopColor")
        loc_bot = glGetUniformLocation(self._gradient_program, "uBottomColor")
        glUniform3f(loc_top, *top)
        glUniform3f(loc_bot, *bot)

        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        glBindVertexArray(0)
        glUseProgram(0)

    def _draw_solid(self) -> None:
        """Draw a flat solid-colour background."""
        glUseProgram(self._solid_program)

        loc_color = glGetUniformLocation(self._solid_program, "uSolidColor")
        glUniform3f(loc_color, *self._solid_color)

        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        glBindVertexArray(0)
        glUseProgram(0)

    def _draw_hdri(
        self,
        view_matrix: List[float],
        proj_matrix: List[float],
    ) -> None:
        """Draw the HDRI equirectangular environment map."""
        # Compute inverse(projection * view) for direction reconstruction.
        vp = _mat4_multiply(proj_matrix, view_matrix)
        inv_vp = _mat4_inverse(vp)
        if inv_vp is None:
            # Singular matrix -- fall back to gradient for this frame.
            self._draw_gradient()
            return

        glUseProgram(self._hdri_program)

        loc_inv_vp = glGetUniformLocation(self._hdri_program, "uInvViewProj")
        loc_env = glGetUniformLocation(self._hdri_program, "uEnvMap")

        glUniformMatrix4fv(
            loc_inv_vp, 1, GL_FALSE, (ctypes.c_float * 16)(*inv_vp)
        )

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._hdri_texture)
        glUniform1i(loc_env, 0)

        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        glBindVertexArray(0)

        glBindTexture(GL_TEXTURE_2D, 0)
        glUseProgram(0)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Delete all GL resources owned by this renderer."""
        if self._gradient_program:
            glDeleteProgram(self._gradient_program)
            self._gradient_program = 0
        if self._solid_program:
            glDeleteProgram(self._solid_program)
            self._solid_program = 0
        if self._hdri_program:
            glDeleteProgram(self._hdri_program)
            self._hdri_program = 0
        if self._vao:
            glDeleteVertexArrays(1, [self._vao])
            self._vao = 0
        if self._gradient_texture:
            glDeleteTextures(1, [self._gradient_texture])
            self._gradient_texture = 0
        if self._hdri_texture:
            glDeleteTextures(1, [self._hdri_texture])
            self._hdri_texture = 0
        self._loaded = False
        self._hdri_loaded = False
