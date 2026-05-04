"""Minimal PNG encoder shared by aov_renderer.py and aov_export.py.

Pure stdlib (struct + zlib); no Pillow dependency.

Single source of truth — earlier versions of the codebase had two
near-identical implementations (one returning bytes, one writing a file
and flipping Y), which made it easy for them to drift on bit-depth or
chunk-handling details.
"""
from __future__ import annotations

import struct
import zlib

# PNG color_type constants from the spec.
_COLOR_TYPE_GRAY = 0
_COLOR_TYPE_RGB = 2
_COLOR_TYPE_RGBA = 6
_COLOR_TYPE_BY_CHANNELS = {1: _COLOR_TYPE_GRAY, 3: _COLOR_TYPE_RGB, 4: _COLOR_TYPE_RGBA}


def encode_png(
    pixels: bytes,
    width: int,
    height: int,
    channels: int,
    *,
    bit_depth: int = 8,
    flip_y: bool = False,
    compression_level: int = 6,
) -> bytes:
    """Encode raw pixel data as a PNG file in memory.

    Parameters
    ----------
    pixels : bytes
        Raw pixel data, row-major. Row order is top-to-bottom unless
        ``flip_y`` is True.
    width, height : int
        Image dimensions.
    channels : int
        1 (grayscale), 3 (RGB), or 4 (RGBA).
    bit_depth : int
        Bits per channel. Must be 8 or 16.
    flip_y : bool
        Set True when input is bottom-to-top (OpenGL ``glReadPixels``
        convention) and the encoded PNG should be top-to-bottom.
    compression_level : int
        zlib level 0-9; default 6 trades latency for size, 9 produces the
        smallest output.

    Returns
    -------
    bytes
        Complete PNG file contents (signature + IHDR + IDAT + IEND).
    """
    if channels not in _COLOR_TYPE_BY_CHANNELS:
        raise ValueError(f"Unsupported channel count: {channels}")
    if bit_depth not in (8, 16):
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    color_type = _COLOR_TYPE_BY_CHANNELS[channels]
    bytes_per_sample = bit_depth // 8
    row_size = width * channels * bytes_per_sample

    # Build raw scanlines with a per-row filter byte (0x00 = None).
    raw = bytearray()
    for y in range(height):
        raw += b"\x00"
        src_y = (height - 1 - y) if flip_y else y
        row_start = src_y * row_size
        raw += pixels[row_start : row_start + row_size]

    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += _chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0),
    )
    out += _chunk(b"IDAT", zlib.compress(bytes(raw), compression_level))
    out += _chunk(b"IEND", b"")
    return bytes(out)


def write_png(path: str, *args, **kwargs) -> None:
    """Convenience: encode pixels and write the result to ``path``.

    All parameters after ``path`` are forwarded to :func:`encode_png`.
    """
    data = encode_png(*args, **kwargs)
    with open(path, "wb") as f:
        f.write(data)


def _chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    body = chunk_type + chunk_data
    crc = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return struct.pack(">I", len(chunk_data)) + body + crc
