#!/usr/bin/env python3
"""One-shot generator for the plugin icon. Writes a 128x128 RGB PNG."""

import struct
import zlib
from pathlib import Path

SIZE = 128
BG = (15, 17, 23)
INK = (45, 212, 191)
DIM = (56, 89, 94)

buf = [[BG for _ in range(SIZE)] for _ in range(SIZE)]


def put(x, y, color):
    if 0 <= x < SIZE and 0 <= y < SIZE:
        buf[y][x] = color


def disc(cx, cy, r, color):
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                put(x, y, color)


def line(x0, y0, x1, y1, color, width=3):
    steps = max(abs(x1 - x0), abs(y1 - y0)) * 4
    for step in range(steps + 1):
        t = step / steps if steps else 0
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        for dx in range(-width, width + 1):
            for dy in range(-width, width + 1):
                if dx * dx + dy * dy <= width * width:
                    put(int(round(x)) + dx, int(round(y)) + dy, color)


# trunk
line(18, 64, 62, 64, INK, 4)
# branches
for target_y in (26, 64, 102):
    line(62, 64, 88, target_y, DIM, 3)
    disc(100, target_y, 12, INK)
    disc(100, target_y, 6, BG)
    disc(100, target_y, 3, INK)

# entry dot
disc(16, 64, 10, INK)
disc(16, 64, 5, BG)

raw = b""
for row in buf:
    raw += b"\x00" + b"".join(struct.pack("3B", *pixel) for pixel in row)


def chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(raw, 9))
png += chunk(b"IEND", b"")

out = Path(__file__).resolve().parent.parent / "icon.png"
out.write_bytes(png)
print("wrote", out, len(png), "bytes")
