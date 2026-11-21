"""Plate thumbnails: a small numpy point-splat renderer and a PNG writer."""
import struct
import zlib

import numpy as np

from .config import THUMB, THUMB_SMALL


def png(rgba):
    """Encode an (h, w, 4) uint8 array as PNG."""
    h, w, _ = rgba.shape
    rows = np.concatenate([np.zeros((h, 1), np.uint8), rgba.reshape(h, w * 4)], axis=1).tobytes()

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def render(verts, faces, size, view="iso", lit=True, colour="#F2754E", samples=1_500_000):
    """Small point-splat renderer: area-weighted surface samples + z-buffer."""
    rng = np.random.default_rng(0)
    v = verts.astype(np.float64)
    a, b, c = (v[faces[:, i]] for i in range(3))
    normal = np.cross(b - a, c - a)
    area = np.linalg.norm(normal, axis=1)
    keep = area > 0
    a, b, c, normal, area = a[keep], b[keep], c[keep], normal[keep], area[keep]
    normal /= area[:, None]
    pick = rng.choice(len(area), size=samples, p=area / area.sum())
    r1, r2 = np.sqrt(rng.random(samples)), rng.random(samples)
    pts = (1 - r1)[:, None] * a[pick] + (r1 * (1 - r2))[:, None] * b[pick] + (r1 * r2)[:, None] * c[pick]
    pts = np.concatenate([pts, a, b, c])
    nrm = np.concatenate([normal[pick], normal, normal, normal])

    if view == "top":
        right, up, toward = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
    else:
        az, el = np.radians(-50), np.radians(25)
        toward = np.array([np.cos(el) * np.sin(az), -np.cos(el) * np.cos(az), np.sin(el)])
        right = np.array([np.cos(az), np.sin(az), 0.0])
        up = np.cross(toward, right)
    x, y, depth = pts @ right, pts @ up, pts @ toward
    span = max(np.ptp(x), np.ptp(y)) or 1.0
    scale = (size * 0.86) / span
    px = np.clip(((x - (x.min() + x.max()) / 2) * scale + size / 2).astype(int), 0, size - 1)
    py = np.clip((size / 2 - (y - (y.min() + y.max()) / 2) * scale).astype(int), 0, size - 1)

    base = np.array([int(colour[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64)
    if lit:
        light = np.array([-0.35, -0.45, 0.82])
        light /= np.linalg.norm(light)
        facing = np.where(nrm @ toward < 0, -1.0, 1.0)[:, None] * nrm
        shade = 0.38 + 0.62 * np.clip(facing @ light, 0, 1)
        rgb = np.clip(base[None, :] * shade[:, None], 0, 255)
    else:
        rgb = np.repeat(base[None, :], len(pts), axis=0)

    order = np.argsort(depth)  # nearest written last
    img = np.zeros((size, size, 4), np.uint8)
    img[py[order], px[order], :3] = rgb[order].astype(np.uint8)
    img[py[order], px[order], 3] = 255
    return img


def thumbnails(verts, faces, colour, plate=1, samples=1_500_000):
    kw = {"samples": samples}
    return {
        f"Metadata/plate_{plate}.png": png(render(verts, faces, THUMB, colour=colour, **kw)),
        f"Metadata/plate_{plate}_small.png": png(render(verts, faces, THUMB_SMALL, colour=colour,
                                                        samples=min(samples, 400_000))),
        f"Metadata/plate_no_light_{plate}.png": png(render(verts, faces, THUMB, lit=False, colour=colour, **kw)),
        f"Metadata/top_{plate}.png": png(render(verts, faces, THUMB, view="top", colour=colour, **kw)),
        f"Metadata/pick_{plate}.png": png(render(verts, faces, THUMB, lit=False, colour="#4D0000", **kw)),
    }
