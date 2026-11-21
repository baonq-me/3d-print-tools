"""Read an STL, weld its vertices and check the mesh."""
import struct

import numpy as np


def read_stl(path):
    """Return (n, 3, 3) float32 triangles from a binary or ASCII STL."""
    raw = open(path, "rb").read()
    if len(raw) >= 84:
        n = struct.unpack("<I", raw[80:84])[0]
        if len(raw) == 84 + 50 * n:
            rec = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
            return np.frombuffer(raw, dtype=rec, offset=84, count=n)["v"].copy()
    coords = [line.split()[1:4] for line in raw.decode("ascii", "replace").splitlines()
              if line.lstrip().startswith("vertex")]
    if not coords or len(coords) % 3:
        raise ValueError(f"{path}: not a valid binary or ASCII STL")
    return np.array(coords, dtype=np.float32).reshape(-1, 3, 3)


def weld(tris):
    """Merge identical vertices -> (vertices, faces); drop degenerate faces."""
    verts, inverse = np.unique(tris.reshape(-1, 3), axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    ok = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return verts, faces[ok]


def mesh_report(verts, faces):
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    _, shared = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    _, directed = np.unique(edges, axis=0, return_counts=True)
    v = verts.astype(np.float64)
    a, b, c = (v[faces[:, i]] for i in range(3))
    return {
        "open_edges": int((shared != 2).sum()),
        "flipped_edges": int((directed != 1).sum()),
        "volume_mm3": float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6),
    }
