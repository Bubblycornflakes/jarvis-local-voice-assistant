"""Draws the arc-reactor app icon as a macOS iconset (no image libraries needed)."""
import struct
import sys
import zlib
from pathlib import Path

import numpy as np


def reactor(n: int) -> np.ndarray:
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n - 0.5
    r = np.hypot(x, y) * 2.3  # 0 centre, ~1 just inside the tile edge
    ang = np.arctan2(y, x)
    cyan = np.array([0.25, 0.95, 1.0])
    glow = np.zeros(r.shape)
    glow += np.exp(-((r - 0.86) / 0.025) ** 2) * (np.sin(ang * 36) > -0.3)  # dashed outer ring
    glow += np.exp(-((r - 0.70) / 0.03) ** 2) * 0.9
    glow += np.exp(-((r - 0.52) / 0.05) ** 2) * (np.cos(ang * 2) > -0.2)  # split inner ring
    glow += np.exp(-(r / 0.30) ** 2) * 1.6  # core
    glow += np.exp(-(r / 0.75) ** 2) * 0.25  # haze
    rgb = np.clip(glow[..., None] * cyan + np.exp(-(r / 0.12) ** 2)[..., None] * 0.9, 0, 1)
    bg = np.array([0.01, 0.04, 0.07])
    # rounded-square macOS tile
    half, rad = 0.82, 0.2  # tile half-size and corner radius, in units of half the canvas
    dx = np.maximum(np.abs(x) * 2 - (half - rad), 0)
    dy = np.maximum(np.abs(y) * 2 - (half - rad), 0)
    inside = np.hypot(dx, dy) < rad
    img = np.where(inside[..., None], np.clip(bg + rgb, 0, 1), 0)
    alpha = inside.astype(float)
    return (np.dstack([img, alpha]) * 255).astype(np.uint8)


def png(arr: np.ndarray) -> bytes:
    h, w, _ = arr.shape
    raw = b"".join(b"\0" + arr[i].tobytes() for i in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for size in (16, 32, 128, 256, 512):
    (out / f"icon_{size}x{size}.png").write_bytes(png(reactor(size)))
    (out / f"icon_{size}x{size}@2x.png").write_bytes(png(reactor(size * 2)))
