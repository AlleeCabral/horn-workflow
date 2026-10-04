"""Swept-duct surface meshes from a folded candidate.

Produces the acoustic cavity surface (for BEM/viz) and a closed wall shell (for
STL / printing).  Built directly on the existing ``mesh.SurfaceMesh`` container
so it reuses the validated MSH-2.2 and STL writers.
"""

from __future__ import annotations

import numpy as np

from ..mesh import SurfaceMesh


def ring_local(sec, k: int = 4, wall: float = 0.0) -> list:
    """Closed rectangular ring (u,v) local coordinates, ``4*k`` points."""
    hw = sec.width / 2.0 + wall
    hh = sec.height / 2.0 + wall
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    pts = []
    for i in range(4):
        a = np.array(corners[i]); b = np.array(corners[(i + 1) % 4])
        for t in np.linspace(0.0, 1.0, k, endpoint=False):
            p = a + t * (b - a)
            pts.append((float(p[0]), float(p[1])))
    return pts


def _ring3d(centreline, i: int, sec, k: int, wall: float = 0.0) -> np.ndarray:
    p = centreline.points[i]
    nv = centreline.normals[i]
    bv = centreline.binormals[i]
    pts = ring_local(sec, k, wall)
    return np.array([p + u * bv + v * nv for (u, v) in pts])


def _add_ring_quads(verts, tris, r0, r1, k, tag, flip=False):
    for j in range(k):
        a = r0[j]; b = r0[(j + 1) % k]
        c = r1[(j + 1) % k]; d = r1[j]
        if flip:
            tris.append((a, c, d, tag)); tris.append((a, b, c, tag))
        else:
            tris.append((a, b, c, tag)); tris.append((a, c, d, tag))


def _cap(verts, tris, ring, centre_idx, tag, flip=False):
    k = len(ring)
    for j in range(k):
        a = ring[j]; b = ring[(j + 1) % k]
        if flip:
            tris.append((centre_idx, b, a, tag))
        else:
            tris.append((centre_idx, a, b, tag))


def _add_vertex(verts, p) -> int:
    verts.append((float(p[0]), float(p[1]), float(p[2])))
    return len(verts) - 1


def cavity_mesh(candidate, k: int = 4) -> SurfaceMesh:
    """The inner acoustic duct surface (open at throat and mouth)."""
    cl = candidate.centreline
    n = len(cl.points)
    verts: list = []
    tris: list = []
    rings = []
    for i, sec in enumerate(candidate.sections):
        idx = [_add_vertex(verts, p) for p in _ring3d(cl, i, sec, k)]
        rings.append(idx)
    for i in range(n - 1):
        _add_ring_quads(verts, tris, rings[i], rings[i + 1], 4 * k, 1)
    m = SurfaceMesh()
    m.nodes = verts
    m.tris = tris
    m.physical = {1: "wall"}
    m.meta = {"kind": "cavity"}
    return m


def shell_mesh(candidate, wall_mm: float = 18.0, k: int = 4) -> SurfaceMesh:
    """A closed wall shell: inner duct + outer offset + rim rings (watertight)."""
    cl = candidate.centreline
    n = len(cl.points)
    wall = wall_mm * 1e-3
    verts: list = []
    tris: list = []
    inner, outer = [], []
    for i, sec in enumerate(candidate.sections):
        inner.append([_add_vertex(verts, p) for p in _ring3d(cl, i, sec, k, 0.0)])
        outer.append([_add_vertex(verts, p) for p in _ring3d(cl, i, sec, k, wall)])
    for i in range(n - 1):
        _add_ring_quads(verts, tris, inner[i], inner[i + 1], 4 * k, 1)         # inner wall
        _add_ring_quads(verts, tris, outer[i], outer[i + 1], 4 * k, 2, flip=True)  # outer wall
    # rim quads at throat and mouth (connect inner<->outer)
    for j in range(4 * k):
        a = inner[0][j]; b = inner[0][(j + 1) % (4 * k)]
        c = outer[0][(j + 1) % (4 * k)]; d = outer[0][j]
        tris.append((a, b, c, 3)); tris.append((a, c, d, 3))
        a = inner[-1][j]; b = inner[-1][(j + 1) % (4 * k)]
        c = outer[-1][(j + 1) % (4 * k)]; d = outer[-1][j]
        tris.append((a, c, b, 3)); tris.append((a, d, c, 3))
    m = SurfaceMesh()
    m.nodes = verts
    m.tris = tris
    m.physical = {1: "wall_inner", 2: "wall_outer", 3: "rim"}
    m.meta = {"kind": "shell"}
    return m


def edge_manifold_report(m: SurfaceMesh) -> dict:
    """Watertightness: every edge must be shared by exactly two triangles."""
    from collections import Counter
    edges = Counter()
    for n0, n1, n2, _tag in m.tris:
        for a, b in ((n0, n1), (n1, n2), (n2, n0)):
            edges[tuple(sorted((a, b)))] += 1
    boundary = sum(1 for v in edges.values() if v == 1)
    nonmanifold = sum(1 for v in edges.values() if v > 2)
    return {"edges": len(edges), "boundary_edges": boundary,
            "nonmanifold_edges": nonmanifold,
            "watertight": boundary == 0 and nonmanifold == 0}
