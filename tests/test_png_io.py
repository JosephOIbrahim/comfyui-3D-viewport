"""Regression tests for src/png_io.py.

Resolves a901163 — the consolidation of two near-identical PNG encoders
that previously lived in aov_renderer.py and aov_export.py. The tests
check the binary structure (magic bytes, IHDR, IDAT, IEND chunks) and
the public flip-Y / channel / bit-depth behavior so future drift is
caught.
"""
from __future__ import annotations

import struct
import zlib

import pytest

from png_io import encode_png, write_png


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _split_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """Walk a PNG byte-stream and return ``[(chunk_type, chunk_data), ...]``."""
    assert data.startswith(PNG_MAGIC), "missing PNG signature"
    i = len(PNG_MAGIC)
    chunks = []
    while i < len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        body = data[i + 8:i + 8 + length]
        # crc = data[i + 8 + length:i + 12 + length]
        chunks.append((ctype, body))
        i += 12 + length
    return chunks


def test_encode_png_has_required_chunks():
    pixels = bytes([255, 0, 0,  0, 255, 0,  0, 0, 255,  255, 255, 0])  # 2x2 RGB
    out = encode_png(pixels, width=2, height=2, channels=3)
    chunk_types = [t for t, _ in _split_chunks(out)]
    assert chunk_types[0] == b"IHDR"
    assert chunk_types[-1] == b"IEND"
    assert b"IDAT" in chunk_types


def test_encode_png_ihdr_records_dimensions_and_color_type():
    pixels = bytes([42] * 6)  # 3x2 grayscale
    out = encode_png(pixels, width=3, height=2, channels=1)
    chunks = dict(_split_chunks(out))
    ihdr = chunks[b"IHDR"]
    width, height, bit_depth, color_type = struct.unpack(">IIBB", ihdr[:10])
    assert width == 3
    assert height == 2
    assert bit_depth == 8
    assert color_type == 0  # grayscale


def test_encode_png_rgba_color_type():
    pixels = bytes([0] * 16)  # 2x2 RGBA
    out = encode_png(pixels, width=2, height=2, channels=4)
    ihdr = dict(_split_chunks(out))[b"IHDR"]
    color_type = struct.unpack(">B", ihdr[9:10])[0]
    assert color_type == 6  # RGBA


def test_encode_png_16bit_records_bit_depth():
    pixels = bytes([0] * 8)  # 2x2 grayscale at 16bpp
    out = encode_png(pixels, width=2, height=2, channels=1, bit_depth=16)
    ihdr = dict(_split_chunks(out))[b"IHDR"]
    assert struct.unpack(">B", ihdr[8:9])[0] == 16


def test_encode_png_rejects_unsupported_channels():
    with pytest.raises(ValueError, match="channel count"):
        encode_png(b"", width=1, height=1, channels=5)


def test_encode_png_rejects_unsupported_bit_depth():
    with pytest.raises(ValueError, match="bit depth"):
        encode_png(b"\0", width=1, height=1, channels=1, bit_depth=12)


def test_encode_png_flip_y_reverses_row_order():
    """flip_y True must emit rows bottom-up so an OpenGL readback is
    saved right-side-up."""
    # 2x2 grayscale: row 0 = [10, 20]; row 1 = [30, 40].
    pixels = bytes([10, 20, 30, 40])

    plain = encode_png(pixels, width=2, height=2, channels=1, flip_y=False)
    flipped = encode_png(pixels, width=2, height=2, channels=1, flip_y=True)

    # Decompress IDAT to inspect raw scanlines.
    plain_idat = dict(_split_chunks(plain))[b"IDAT"]
    flipped_idat = dict(_split_chunks(flipped))[b"IDAT"]

    plain_raw = zlib.decompress(plain_idat)
    flipped_raw = zlib.decompress(flipped_idat)
    # Each scanline starts with 1 filter byte (0x00). row_size = 2.
    assert plain_raw[1:3] == bytes([10, 20])  # row 0 first
    assert plain_raw[4:6] == bytes([30, 40])  # row 1 second
    assert flipped_raw[1:3] == bytes([30, 40])  # row 1 first
    assert flipped_raw[4:6] == bytes([10, 20])  # row 0 second


def test_write_png_round_trip_to_disk(tmp_path):
    pixels = bytes([255] * 12)  # 2x2 RGB white
    out = tmp_path / "white.png"
    write_png(str(out), pixels, 2, 2, channels=3)
    data = out.read_bytes()
    assert data.startswith(PNG_MAGIC)
    chunks = dict(_split_chunks(data))
    assert b"IHDR" in chunks and b"IDAT" in chunks and b"IEND" in chunks
