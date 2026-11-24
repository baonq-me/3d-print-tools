"""Mesh checks shown before converting: size, volume, watertight, fits the bed,
tilt of the largest flat face, and the area resting on the bed."""
import math

import numpy as np

from .mesh import mesh_report, read_stl, weld

BED = (220.0, 220.0, 250.0)   # Ender-3 V3 SE build volume, mm
ON_BED_MM = 0.05              # faces this close to the lowest point count as touching the bed


def inspect(path, bed=BED):
    verts, faces = weld(read_stl(path))
    if len(faces) == 0:
        raise ValueError("the STL has no triangles")
    report = mesh_report(verts, faces)
    v = verts.astype(np.float64)
    lo, hi = v.min(0), v.max(0)
    size = hi - lo

    tri = v[faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    double_area = np.linalg.norm(normal, axis=1)
    keep = double_area > 0
    unit = normal[keep] / double_area[keep, None]
    area = double_area[keep] / 2
    total_area = float(area.sum())

    # Largest flat face: group faces by (rounded) normal direction, either side.
    flip = np.where(unit[:, 2] < 0, -1.0, 1.0)[:, None] * unit
    key = np.round(flip, 2)
    groups, inverse = np.unique(key, axis=0, return_inverse=True)
    group_area = np.bincount(inverse.ravel(), weights=area)
    best = int(np.argmax(group_area))
    nz = float(abs(groups[best][2]) / (np.linalg.norm(groups[best]) or 1.0))
    tilt = math.degrees(math.acos(min(1.0, nz)))
    largest_share = float(group_area[best] / total_area) if total_area else 0.0
    # Tilted: the largest flat area is neither lying flat nor standing upright.
    tilted = largest_share > 0.15 and 5.0 < tilt < 85.0

    on_bed = (tri[keep][:, :, 2].max(axis=1) < lo[2] + ON_BED_MM) & (unit[:, 2] < -0.99)
    contact = float(area[on_bed].sum())

    return {
        "triangles": int(len(faces)),
        "size_mm": [round(float(x), 2) for x in size],
        "volume_cm3": round(report["volume_mm3"] / 1000, 2),
        "watertight": report["open_edges"] == 0 and report["flipped_edges"] == 0,
        "open_edges": report["open_edges"],
        "flipped_edges": report["flipped_edges"],
        "fits": bool(size[0] <= bed[0] and size[1] <= bed[1] and size[2] <= bed[2]),
        "bed_mm": list(bed),
        "tilted": bool(tilted),
        "tilt_deg": round(tilt, 1),
        "bed_contact_mm2": round(contact, 1),
    }
