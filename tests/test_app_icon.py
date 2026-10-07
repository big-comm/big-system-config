"""Application icon: every hicolor size exists, is RGBA and has a transparent
background (the source artwork came on a white canvas)."""

import struct
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HICOLOR = ROOT / "usr/share/icons/hicolor"
SIZES = (16, 22, 24, 32, 48, 64, 96, 128, 256, 512)


def read_png(path: Path) -> tuple[int, int, int, list[bytes]]:
    """Width, height, color type and unfiltered scanlines (8-bit only)."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat = 8, b""
    width = height = color_type = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        chunk = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color_type = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw = zlib.decompress(idat)
    channels = {6: 4, 2: 3}[color_type]
    stride = width * channels
    rows, prev = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = prev[i]
            upleft = prev[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + left) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + up) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif kind == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                pred = left if pa <= pb and pa <= pc else up if pb <= pc else upleft
                line[i] = (line[i] + pred) & 0xFF
        rows.append(bytes(line))
        prev = line
    return width, height, color_type, rows


def alpha(rows: list[bytes], x: int, y: int) -> int:
    return rows[y][x * 4 + 3]


@pytest.mark.parametrize("size", SIZES)
def test_icon_size_exists_and_is_transparent(size):
    path = HICOLOR / f"{size}x{size}/apps/biglinux-settings.png"
    width, height, color_type, rows = read_png(path)
    assert (width, height) == (size, size)
    assert color_type == 6, "icon must have an alpha channel"
    last = size - 1
    for x, y in ((0, 0), (last, 0), (0, last), (last, last)):
        assert alpha(rows, x, y) == 0, f"corner {x},{y} is not transparent"
    assert alpha(rows, size // 2, size // 2) == 255


def test_no_stale_scalable_icon():
    # A leftover SVG would win over the PNGs at every size
    assert not (HICOLOR / "scalable/apps/biglinux-settings.svg").exists()
