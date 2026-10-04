"""glTF 2.0 / GLB writer - standard-library only.

A GLB is a well-specified binary container (JSON chunk + BIN chunk); writing one
directly is reliable and gives an artifact that opens in any glTF viewer, not
just our page.  Supports triangle meshes (mode 4) and line strips (mode 1) so the
centreline and area-station markers travel in the same file.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_FLOAT = 5126
_UINT = 5125


def _pad4(b: bytes, fill: bytes = b"\x00") -> bytes:
    while len(b) % 4:
        b += fill
    return b


def part_mesh(surface_mesh, color=(0.8, 0.8, 0.85, 1.0), name: str = "wall",
              mode: int = 4) -> dict:
    pos = np.asarray(surface_mesh.nodes, dtype=np.float32)
    idx = np.asarray([t[:3] for t in surface_mesh.tris], dtype=np.uint32).reshape(-1)
    return {"name": name, "positions": pos, "indices": idx, "color": list(color),
            "mode": mode}


def part_polyline(points, color=(1.0, 0.3, 0.1, 1.0), name: str = "centreline") -> dict:
    pts = np.asarray(points, dtype=np.float32)
    idx = np.arange(len(pts), dtype=np.uint32)
    return {"name": name, "positions": pts, "indices": idx, "color": list(color),
            "mode": 1}


def part_points(points, color=(0.1, 0.6, 1.0, 1.0), name: str = "stations") -> dict:
    pts = np.asarray(points, dtype=np.float32)
    idx = np.arange(len(pts), dtype=np.uint32)
    return {"name": name, "positions": pts, "indices": idx, "color": list(color),
            "mode": 0}


def write_glb(parts: list, path, name: str = "horn") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    buffer = bytearray()
    buffer_views, accessors, meshes, materials, nodes = [], [], [], [], []

    for part in parts:
        pos = np.asarray(part["positions"], dtype=np.float32).reshape(-1, 3)
        idx = np.asarray(part["indices"], dtype=np.uint32).reshape(-1)
        mode = int(part.get("mode", 4))
        color = list(part.get("color", (0.8, 0.8, 0.85, 1.0)))
        if mode == 0:                      # points: indices == vertex order
            idx = np.arange(len(pos), dtype=np.uint32)

        # positions
        pos_off = len(buffer)
        buffer += pos.tobytes()
        buffer = bytearray(_pad4(bytes(buffer)))
        buffer_views.append({"buffer": 0, "byteOffset": pos_off,
                             "byteLength": int(pos.nbytes), "target": _ARRAY_BUFFER})
        pv = len(buffer_views) - 1
        accessors.append({"bufferView": pv, "componentType": _FLOAT, "count": int(len(pos)),
                          "type": "VEC3",
                          "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()})
        pa = len(accessors) - 1

        # indices
        idx_off = len(buffer)
        buffer += idx.tobytes()
        buffer = bytearray(_pad4(bytes(buffer)))
        buffer_views.append({"buffer": 0, "byteOffset": idx_off,
                             "byteLength": int(idx.nbytes), "target": _ELEMENT_ARRAY_BUFFER})
        iv = len(buffer_views) - 1
        accessors.append({"bufferView": iv, "componentType": _UINT,
                          "count": int(len(idx)), "type": "SCALAR"})
        ia = len(accessors) - 1

        materials.append({
            "name": part.get("name", "mat"),
            "pbrMetallicRoughness": {"baseColorFactor": color,
                                     "metallicFactor": 0.0, "roughnessFactor": 0.7},
            "alphaMode": "BLEND" if color[3] < 1.0 else "OPAQUE",
            "doubleSided": True,
        })
        meshes.append({"name": part.get("name", "part"),
                       "primitives": [{"attributes": {"POSITION": pa}, "indices": ia,
                                       "material": len(materials) - 1, "mode": mode}]})
        nodes.append({"mesh": len(meshes) - 1, "name": part.get("name", "part")})

    gltf = {
        "asset": {"version": "2.0", "generator": "hornflow-gltf"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(buffer)}],
    }

    json_bytes = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    bin_bytes = _pad4(bytes(buffer))
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)

    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", _GLB_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_bytes), _CHUNK_JSON))
        fh.write(json_bytes)
        fh.write(struct.pack("<II", len(bin_bytes), _CHUNK_BIN))
        fh.write(bin_bytes)
    return path
