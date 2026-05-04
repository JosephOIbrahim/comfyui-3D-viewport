"""AOV Renderer — Depth and Normal pass rendering to FBO textures.

Renders depth and normal AOV passes to offscreen framebuffers and saves
them as PNG files. Designed to work alongside the main StormViewport in
a Qt OpenGL 3.3 Core Profile context.

Usage:
    aov = AOVRenderer()
    aov.setup(800, 600)

    # Depth pass — render_callback(program) draws the scene
    depth_array = aov.render_depth(render_callback, near=0.1, far=100.0)
    aov.save_depth_png("depth.png", render_callback, near=0.1, far=100.0)

    # Normal pass
    normal_array = aov.render_normals(render_callback)
    aov.save_normal_png("normals.png", render_callback)

    aov.cleanup()

The render_callback pattern:
    The AOV renderer does not own scene geometry. The caller provides a
    callback that draws the scene (sets uniforms, binds VAOs, calls
    glDrawElements). The AOV renderer manages FBO binding, shader
    activation, and pixel readback.

    def my_render_callback(program):
        # 'program' is the active AOV shader program.
        # Set uModel, uView, uProjection uniforms and draw geometry.
        model_loc = glGetUniformLocation(program, "uModel")
        ...
        glDrawElements(...)
"""

import ctypes

import numpy as np

from png_io import write_png
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_COLOR_ATTACHMENT0,
    GL_COLOR_BUFFER_BIT,
    GL_COMPILE_STATUS,
    GL_DEPTH_ATTACHMENT,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_COMPONENT24,
    GL_DEPTH_TEST,
    GL_FLOAT,
    GL_FRAGMENT_SHADER,
    GL_FRAMEBUFFER,
    GL_FRAMEBUFFER_BINDING,
    GL_FRAMEBUFFER_COMPLETE,
    GL_LINEAR,
    GL_LINK_STATUS,
    GL_RENDERBUFFER,
    GL_RGBA,
    GL_RGBA8,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_UNSIGNED_BYTE,
    GL_VERTEX_SHADER,
    glAttachShader,
    glBindFramebuffer,
    glBindRenderbuffer,
    glBindTexture,
    glCheckFramebufferStatus,
    glClear,
    glClearColor,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteFramebuffers,
    glDeleteProgram,
    glDeleteRenderbuffers,
    glDeleteShader,
    glDeleteTextures,
    glEnable,
    glFramebufferRenderbuffer,
    glFramebufferTexture2D,
    glGenFramebuffers,
    glGenRenderbuffers,
    glGenTextures,
    glGetIntegerv,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glLinkProgram,
    glReadPixels,
    glRenderbufferStorage,
    glShaderSource,
    glTexImage2D,
    glTexParameteri,
    glUseProgram,
    glViewport,
)


# ---------------------------------------------------------------------------
# Shader sources
# ---------------------------------------------------------------------------

DEPTH_VERTEX_SHADER = """\
#version 330 core

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProjection;

out float vDepth;

void main() {
    vec4 viewPos = uView * uModel * vec4(aPos, 1.0);
    vDepth = -viewPos.z;  // positive depth in view space
    gl_Position = uProjection * viewPos;
}
"""

DEPTH_FRAGMENT_SHADER = """\
#version 330 core

in float vDepth;

uniform float uNear;
uniform float uFar;

out vec4 FragColor;

void main() {
    float linearDepth = (vDepth - uNear) / (uFar - uNear);
    linearDepth = clamp(1.0 - linearDepth, 0.0, 1.0);  // near=white, far=black
    FragColor = vec4(vec3(linearDepth), 1.0);
}
"""

NORMAL_VERTEX_SHADER = """\
#version 330 core

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProjection;

out vec3 vWorldNormal;

void main() {
    vWorldNormal = mat3(transpose(inverse(uModel))) * aNormal;
    gl_Position = uProjection * uView * uModel * vec4(aPos, 1.0);
}
"""

NORMAL_FRAGMENT_SHADER = """\
#version 330 core

in vec3 vWorldNormal;

out vec4 FragColor;

void main() {
    vec3 n = normalize(vWorldNormal);
    FragColor = vec4(n * 0.5 + 0.5, 1.0);  // map [-1,1] to [0,1]
}
"""


# ---------------------------------------------------------------------------
# Minimal PNG writer (no Pillow dependency)
# ---------------------------------------------------------------------------

def _write_png(path, data, width, height, channels, bit_depth=8):
    """Write a PNG file using only zlib and struct. No Pillow required.

    Thin wrapper over :func:`png_io.write_png` — kept so external callers
    inside this module retain their existing call sites. Input is in
    OpenGL convention (bottom-to-top) and is flipped to top-to-bottom in
    the output PNG.
    """
    write_png(
        path, data, width, height, channels,
        bit_depth=bit_depth, flip_y=True, compression_level=9,
    )


# ---------------------------------------------------------------------------
# GL helpers (local to this module)
# ---------------------------------------------------------------------------

def _compile_shader(source, shader_type):
    """Compile a GLSL shader and return its handle."""
    shader = glCreateShader(shader_type)
    glShaderSource(shader, source)
    glCompileShader(shader)
    if not glGetShaderiv(shader, GL_COMPILE_STATUS):
        info = glGetShaderInfoLog(shader).decode()
        glDeleteShader(shader)
        raise RuntimeError(f"Shader compile error: {info}")
    return shader


def _create_program(vert_src, frag_src):
    """Compile and link a shader program from vertex + fragment sources."""
    vs = _compile_shader(vert_src, GL_VERTEX_SHADER)
    fs = _compile_shader(frag_src, GL_FRAGMENT_SHADER)
    program = glCreateProgram()
    glAttachShader(program, vs)
    glAttachShader(program, fs)
    glLinkProgram(program)
    # Check link status
    if not glGetProgramiv(program, GL_LINK_STATUS):
        info = glGetProgramInfoLog(program).decode()
        glDeleteShader(vs)
        glDeleteShader(fs)
        glDeleteProgram(program)
        raise RuntimeError(f"Shader link error: {info}")
    glDeleteShader(vs)
    glDeleteShader(fs)
    return program


# ---------------------------------------------------------------------------
# AOVRenderer
# ---------------------------------------------------------------------------

class AOVRenderer:
    """Renders depth and normal AOV passes to an offscreen FBO.

    Manages a single FBO with a color texture attachment and a depth
    renderbuffer. Shader programs for each pass are compiled once and
    reused across frames.

    The renderer does not own scene geometry. A user-provided callback
    draws the scene while the AOV renderer controls FBO binding, shader
    activation, and pixel readback.
    """

    def __init__(self):
        self._fbo = None
        self._color_tex = None
        self._depth_rbo = None
        self._width = 0
        self._height = 0
        self._depth_program = None
        self._normal_program = None

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    def setup(self, width, height):
        """Create or resize the offscreen FBO.

        Parameters
        ----------
        width, height : int
            Framebuffer dimensions in pixels. Must be > 0.
        """
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid FBO dimensions: {width}x{height}")

        # Tear down previous resources on resize
        if self._fbo is not None:
            self._delete_fbo()

        self._width = width
        self._height = height

        # Save current FBO binding to restore after setup
        prev_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)

        # -- Create FBO --
        self._fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self._fbo)

        # Color texture attachment (RGBA8)
        self._color_tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._color_tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self._color_tex, 0)

        # Depth renderbuffer attachment
        self._depth_rbo = glGenRenderbuffers(1)
        glBindRenderbuffer(GL_RENDERBUFFER, self._depth_rbo)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24,
                              width, height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                  GL_RENDERBUFFER, self._depth_rbo)

        # Verify completeness
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            self._delete_fbo()
            raise RuntimeError(
                f"AOV FBO incomplete: status=0x{status:04X}")

        # Restore previous FBO
        glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo)

        # Compile shader programs (first time only)
        if self._depth_program is None:
            self._depth_program = _create_program(
                DEPTH_VERTEX_SHADER, DEPTH_FRAGMENT_SHADER)
        if self._normal_program is None:
            self._normal_program = _create_program(
                NORMAL_VERTEX_SHADER, NORMAL_FRAGMENT_SHADER)

    def cleanup(self):
        """Release all GL resources (FBO, textures, shaders)."""
        self._delete_fbo()
        if self._depth_program is not None:
            glDeleteProgram(self._depth_program)
            self._depth_program = None
        if self._normal_program is not None:
            glDeleteProgram(self._normal_program)
            self._normal_program = None

    def _delete_fbo(self):
        """Delete FBO and its attachments."""
        if self._color_tex is not None:
            glDeleteTextures(1, [self._color_tex])
            self._color_tex = None
        if self._depth_rbo is not None:
            glDeleteRenderbuffers(1, [self._depth_rbo])
            self._depth_rbo = None
        if self._fbo is not None:
            glDeleteFramebuffers(1, [self._fbo])
            self._fbo = None
        self._width = 0
        self._height = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def width(self):
        """Current FBO width in pixels."""
        return self._width

    @property
    def height(self):
        """Current FBO height in pixels."""
        return self._height

    @property
    def is_ready(self):
        """True if the FBO and shaders are set up and ready to render."""
        return (self._fbo is not None
                and self._depth_program is not None
                and self._normal_program is not None)

    @property
    def depth_program(self):
        """GL handle for the depth shader program."""
        return self._depth_program

    @property
    def normal_program(self):
        """GL handle for the normal shader program."""
        return self._normal_program

    # ------------------------------------------------------------------
    # Render passes
    # ------------------------------------------------------------------

    def _bind_fbo(self):
        """Bind the AOV FBO and return the previously bound FBO handle."""
        prev_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        glBindFramebuffer(GL_FRAMEBUFFER, self._fbo)
        glViewport(0, 0, self._width, self._height)
        return int(prev_fbo)

    def _unbind_fbo(self, prev_fbo):
        """Restore the previously bound FBO."""
        glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo)

    def _readback_rgba(self):
        """Read back the color attachment as a numpy RGBA uint8 array.

        Returns shape (height, width, 4), bottom-to-top row order
        (raw OpenGL layout).
        """
        data = glReadPixels(0, 0, self._width, self._height,
                            GL_RGBA, GL_UNSIGNED_BYTE)
        arr = np.frombuffer(data, dtype=np.uint8)
        return arr.reshape(self._height, self._width, 4)

    def render_depth(self, render_callback, near, far):
        """Render a linearized depth pass.

        Parameters
        ----------
        render_callback : callable(program)
            Function that draws the scene. Receives the depth shader
            program handle so it can set uModel/uView/uProjection
            uniforms and issue draw calls.
        near : float
            Near plane distance (view-space, positive).
        far : float
            Far plane distance (view-space, positive).

        Returns
        -------
        numpy.ndarray
            Linearized depth as float32 array, shape (height, width),
            values in [0, 1]. 1.0 = near plane, 0.0 = far plane.
            Row order is top-to-bottom (image convention).
        """
        if not self.is_ready:
            raise RuntimeError("AOVRenderer not set up. Call setup() first.")

        prev_fbo = self._bind_fbo()
        try:
            glClearColor(0.0, 0.0, 0.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glEnable(GL_DEPTH_TEST)

            glUseProgram(self._depth_program)

            # Set near/far uniforms
            from OpenGL.GL import glGetUniformLocation, glUniform1f
            near_loc = glGetUniformLocation(self._depth_program, "uNear")
            far_loc = glGetUniformLocation(self._depth_program, "uFar")
            glUniform1f(near_loc, float(near))
            glUniform1f(far_loc, float(far))

            # Let the caller draw the scene
            render_callback(self._depth_program)

            # Read back
            rgba = self._readback_rgba()
        finally:
            self._unbind_fbo(prev_fbo)

        # Extract R channel as float [0, 1], flip Y to image convention
        depth = rgba[::-1, :, 0].astype(np.float32) / 255.0
        return depth

    def render_normals(self, render_callback):
        """Render a world-space normal pass.

        Parameters
        ----------
        render_callback : callable(program)
            Function that draws the scene. Receives the normal shader
            program handle so it can set uModel/uView/uProjection
            uniforms and issue draw calls.

        Returns
        -------
        numpy.ndarray
            World-space normals as uint8 array, shape (height, width, 3),
            RGB channels. Normal components mapped from [-1,1] to [0,255].
            Row order is top-to-bottom (image convention).
        """
        if not self.is_ready:
            raise RuntimeError("AOVRenderer not set up. Call setup() first.")

        prev_fbo = self._bind_fbo()
        try:
            glClearColor(0.5, 0.5, 1.0, 1.0)  # neutral normal background
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glEnable(GL_DEPTH_TEST)

            glUseProgram(self._normal_program)

            # Let the caller draw the scene
            render_callback(self._normal_program)

            # Read back
            rgba = self._readback_rgba()
        finally:
            self._unbind_fbo(prev_fbo)

        # Extract RGB, flip Y to image convention
        normals = rgba[::-1, :, :3].copy()
        return normals

    # ------------------------------------------------------------------
    # PNG save helpers
    # ------------------------------------------------------------------

    def save_depth_png(self, path, render_callback, near, far):
        """Render depth pass and save as 16-bit greyscale PNG.

        The linearized depth (0.0-1.0) is scaled to 0-65535 and written
        as a 16-bit greyscale PNG for maximum precision.

        Parameters
        ----------
        path : str
            Output PNG file path.
        render_callback : callable(program)
            Scene drawing callback (see render_depth).
        near : float
            Near plane distance.
        far : float
            Far plane distance.
        """
        depth = self.render_depth(render_callback, near, far)
        h, w = depth.shape

        # Scale to 16-bit and convert to big-endian bytes (PNG uses
        # network byte order for 16-bit samples)
        depth_16 = np.clip(depth * 65535.0, 0, 65535).astype(np.uint16)
        # Convert to big-endian
        depth_be = depth_16.byteswap().tobytes()

        _write_png(path, depth_be, w, h, channels=1, bit_depth=16)

    def save_normal_png(self, path, render_callback):
        """Render normal pass and save as 8-bit RGB PNG.

        Parameters
        ----------
        path : str
            Output PNG file path.
        render_callback : callable(program)
            Scene drawing callback (see render_normals).
        """
        normals = self.render_normals(render_callback)
        h, w, _ = normals.shape

        # normals is already uint8 RGB, top-to-bottom. _write_png expects
        # bottom-to-top (GL convention), so flip Y back before writing
        # since _write_png flips internally.
        normals_flipped = normals[::-1].copy()
        _write_png(path, normals_flipped.tobytes(), w, h, channels=3,
                   bit_depth=8)
