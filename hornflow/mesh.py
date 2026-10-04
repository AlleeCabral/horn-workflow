"""Gmsh MSH 2.2 surface meshes, written and read back without external tools.

AKABAK/ABEC wants the old MSH version 2.2 (the Gmsh 4.x default is not read).
Writing it ourselves has two advantages: the workflow runs on Linux without Wine,
and the mesh topology is deterministic, so it can be tested here.

The horn is meshed as three (optionally four) surface groups:

    source     - disk capping the throat (this is what the LE driver drives)
    wall       - the horn's lateral surface, throat circle -> mouth outline
    interface  - the mouth plane, which splits the BEM subdomains
    baffle     - optional flat ring around the mouth (infinite-baffle models)

Cross sections morph from the throat circle to the rectangular mouth outline: a
superellipse with semi-axes a,b where a*b = area and a/b = the aspect ratio.
"""

from __future__ import annotations

import math
import numpy as np
from dataclasses import dataclass, field

MSH_VERSION = "2.2"
TRIANGLE = 2


@dataclass
class SurfaceMesh:
    """Nodes plus triangles, each triangle tagged with a physical group."""

    nodes: list = field(default_factory=list)          # [(x, y, z), ...] 0-based here
    tris: list = field(default_factory=list)           # [(n0, n1, n2, physical_tag), ...]
    physical: dict = field(default_factory=dict)       # tag -> name
    meta: dict = field(default_factory=dict)

    def tag_of(self, name: str) -> int:
        for tag, label in self.physical.items():
            if label == name:
                return tag
        raise KeyError(f"no physical group named {name!r}")

    def count(self, name: str) -> int:
        tag = self.tag_of(name)
        return sum(1 for t in self.tris if t[3] == tag)

    def bounds(self) -> tuple:
        a = np.asarray(self.nodes, dtype=float)
        return a.min(axis=0), a.max(axis=0)

    def area_by_group(self) -> dict:
        out: dict = {}
        for n0, n1, n2, tag in self.tris:
            p0, p1, p2 = (np.asarray(self.nodes[i], dtype=float) for i in (n0, n1, n2))
            out[self.physical[tag]] = out.get(self.physical[tag], 0.0) + 0.5 * float(
                np.linalg.norm(np.cross(p1 - p0, p2 - p0)))
        return out


# ---------------------------------------------------------------------------
#  geometry of one cross section
# ---------------------------------------------------------------------------
def superellipse_axes(area: float, aspect: float, exponent: float) -> tuple:
    """Semi-axes (a in x, b in y) of a superellipse with the given area and aspect.

    The area of |x/a|^p + |y/b|^p = 1 is  A = 4 a b Gamma(1+1/p)^2 / Gamma(1+2/p),
    so keeping the local area equal to the round horn's area needs those factors:
    p = 2 (ellipse) gives A = pi a b, p -> inf (rectangle) gives A = 4 a b.
    """
    k = math.exp(2.0 * math.lgamma(1.0 + 1.0 / exponent)
                 - math.lgamma(1.0 + 2.0 / exponent))
    a = math.sqrt(area * aspect / (4.0 * k))
    return a, a / aspect


def section_outline(design, z: float, n_around: int, morph: float = 1.5,
                    psi: np.ndarray = None) -> np.ndarray:
    """Outline of the horn at distance z from the throat [m] -> (n, 2) array.

    The cross section is a superellipse whose area equals the round horn's local
    area at every station, morphing from a circle (throat) to a soft-cornered
    rectangle with the requested aspect ratio (mouth).

    `psi` overrides the polar sampling: a full ring is the default, while a
    symmetric (half/quarter) model passes an arc that ends exactly on the plane
    of symmetry - see `symmetry_arc`.
    """
    t = 0.0 if design.length <= 0 else min(max(z / design.length, 0.0), 1.0)
    area = math.pi * float(np.atleast_1d(design.radius(z))[0]) ** 2
    if str(getattr(design, "mouth_shape", "round")) == "rectangular":
        aspect = 1.0 + (design.mouth_aspect - 1.0) * t ** morph
        exponent = 2.0 + 3.0 * t ** morph                 # 2 = circle, 5 = soft rectangle
    else:
        aspect, exponent = 1.0, 2.0                       # round mouth stays round
    a, b = superellipse_axes(area, aspect, exponent)
    if psi is None:
        psi = np.linspace(0.0, 2.0 * math.pi, int(n_around), endpoint=False)
    cos, sin = np.cos(psi), np.sin(psi)
    x = a * np.sign(cos) * np.abs(cos) ** (2.0 / exponent)
    y = b * np.sign(sin) * np.abs(sin) ** (2.0 / exponent)
    return np.column_stack([x, y])


def suggest_mesh(design, mesh_frequency: float, c: float = 343.0,
                 max_elements: float = 4000.0) -> dict:
    """Mesh density for a target mesh frequency: element <= lambda/6 at the mouth."""
    lam = c / float(mesh_frequency)
    h = lam / 6.0
    outer = section_outline(design, design.length, 64)
    perimeter = float(np.sum(np.linalg.norm(np.diff(np.vstack([outer, outer[:1]]), axis=0),
                                           axis=1)))
    n_around = int(max(24, round(perimeter / h)))
    slant = float(np.sum(np.linalg.norm(np.diff(
        np.column_stack([np.linspace(0, design.length, 200),
                         np.atleast_1d(design.radius(np.linspace(0, design.length, 200)))]),
        axis=0), axis=1)))
    n_stations = int(max(6, round(slant / (0.5 * h))))
    est = n_around * n_stations * 2
    if est > max_elements:                                # keep the model tractable
        scale = math.sqrt(max_elements / est)
        n_around = max(16, int(n_around * scale))
        n_stations = max(5, int(n_stations * scale))
        est = n_around * n_stations * 2
    return {"mesh_frequency_hz": float(mesh_frequency), "element_size_mm": h * 1e3,
            "lambda_over_6_mm": h * 1e3, "n_around": n_around, "n_stations": n_stations,
            "estimated_triangles": est, "mouth_perimeter_mm": perimeter * 1e3}


# ---------------------------------------------------------------------------
#  the mesh itself
# ---------------------------------------------------------------------------
def symmetry_arc(symmetry, n_around: int) -> tuple:
    """Polar sampling and closure for an optional plane of symmetry.

    AKABAK names a plane of symmetry by its normal: `Symmetry=x` is the plane
    x = 0 (the yz-plane), so only the part with x >= 0 has to be meshed;
    `Symmetry=xy` keeps the quadrant x >= 0, y >= 0.  The cut faces carry no
    boundary elements - AKABAK mirrors the entries and completes the model
    ("there should be no Boundary Elements in the plane of symmetry").

    Returns (psi, closed).  `psi` spans exactly the kept sector, so its first and
    last sample lie on the plane(s) of symmetry, and `closed` is False: the two
    ends of the arc must not be joined by a face (that would sit in the plane).
    """
    sym = str(symmetry).strip().lower() if symmetry else "none"
    n = int(n_around)
    if sym in ("none", "", "0", "null"):
        return np.linspace(0.0, 2.0 * math.pi, n, endpoint=False), True
    half_pi = 0.5 * math.pi
    if sym == "x":                     # normal x -> keep x >= 0: phi in [-90, 90]
        return np.linspace(-half_pi, half_pi, max(4, n // 2) + 1), False
    if sym == "y":                     # normal y -> keep y >= 0: phi in [0, 180]
        return np.linspace(0.0, math.pi, max(4, n // 2) + 1), False
    if sym == "xy":                    # normals x and y -> quadrant x, y >= 0
        return np.linspace(0.0, half_pi, max(3, n // 4) + 1), False
    raise ValueError(f"symmetry must be None, 'x', 'y' or 'xy' (a plane at z=0 is "
                     f"not usable for a horn standing on the floor): {symmetry!r}")


def horn_mesh(design, n_around: int = 40, n_stations: int = 10, baffle_margin: float = 0.0,
              with_source: bool = True, with_interface: bool = True,
              symmetry: str = None) -> SurfaceMesh:
    """Build the BEM surface mesh (BEM needs a *closed* interior subdomain).

    baffle_margin > 0 adds a flat ring around the mouth (for infinite-baffle
    models); 0 leaves the horn free standing.

    symmetry = None/'x'/'y'/'xy' meshes only the kept sector, for a project whose
    `Global -> Dim, Sym and BEM -> Symmetry` is set the same way.  The sector is
    cut out of the same geometry, so the group names, tags, units and the z
    origin (mouth at z = design.length) are unchanged; the areas come out as the
    corresponding fraction and AKABAK mirrors them back.
    """
    m = SurfaceMesh()
    names = [(1, "source"), (2, "wall"), (3, "interface"), (4, "baffle")]
    for tag, name in names[:2 + int(with_interface) + int(baffle_margin > 0)]:
        m.physical[tag] = name

    symmetry = str(symmetry).strip().lower() if symmetry else None
    if symmetry and baffle_margin > 0.0:
        raise ValueError("a baffle ring cannot be combined with a symmetric model: the "
                         "outward offset of the ring would leave the plane of symmetry - "
                         "generate the symmetric mesh with baffle_margin=0")
    psi, closed = symmetry_arc(symmetry, n_around)
    seg = len(psi) if closed else len(psi) - 1          # faces around one ring
    zs = np.linspace(0.0, design.length, int(n_stations) + 1)
    rings = [section_outline(design, z, n_around, psi=psi) for z in zs]
    if not closed:
        # the arc ends must sit exactly on the plane of symmetry; the superellipse
        # exponent makes cos(90 deg) = 6e-17 become (1e-16)^(2/exponent) = 2.5e-7 m
        for ring in rings:
            for k in (0, -1):
                if abs(ring[k][0]) < 1e-4:
                    ring[k][0] = 0.0
                if abs(ring[k][1]) < 1e-4:
                    ring[k][1] = 0.0

    def add(p, z):
        m.nodes.append((float(p[0]), float(p[1]), float(z)))
        return len(m.nodes) - 1

    # wall: quads between consecutive rings, split into triangles
    ring_ids = [[add(p, z) for p in ring] for ring, z in zip(rings, zs)]
    wall_tag = m.tag_of("wall")
    for i in range(int(n_stations)):
        lo, hi = ring_ids[i], ring_ids[i + 1]
        for k in range(seg):
            k2 = (k + 1) % len(lo)
            m.tris.append((lo[k], lo[k2], hi[k2], wall_tag))
            m.tris.append((lo[k], hi[k2], hi[k], wall_tag))

    # source: disk capping the throat (a sector of it in a symmetric model)
    if with_source:
        src_tag = m.tag_of("source")
        centre = add((0.0, 0.0), 0.0)
        first = ring_ids[0]
        for k in range(seg):
            m.tris.append((centre, first[(k + 1) % len(first)], first[k], src_tag))

    # interface: mouth cap, as concentric rings (keeps the triangles well shaped)
    if with_interface:
        iface_tag = m.tag_of("interface")
        last = ring_ids[-1]
        n_rings = 3
        prev = last
        cx = sum(m.nodes[i][0] for i in last) / len(last)
        cy = sum(m.nodes[i][1] for i in last) / len(last)
        if not closed:
            # shrink towards the origin, not the (off-plane) sector centroid, so
            # the cut edges stay flush with the planes of symmetry
            cx = cy = 0.0
        for r in range(1, n_rings + 1):
            s = 1.0 - r / (n_rings + 1.0)
            ring = [add((cx + (m.nodes[i][0] - cx) * s, cy + (m.nodes[i][1] - cy) * s),
                        design.length) for i in last]
            for k in range(seg):
                k2 = (k + 1) % len(prev)
                m.tris.append((prev[k], prev[k2], ring[k2], iface_tag))
                m.tris.append((prev[k], ring[k2], ring[k], iface_tag))
            prev = ring
        centre = add((cx, cy), design.length)
        for k in range(seg):
            m.tris.append((centre, prev[(k + 1) % len(prev)], prev[k], iface_tag))

    # optional baffle ring around the mouth
    if baffle_margin > 0.0:
        baf_tag = m.tag_of("baffle")
        outer = section_outline(design, design.length, n_around, psi=psi)
        # expand the mouth outline outwards by baffle_margin (same parameterisation)
        scale = (np.abs(outer) + baffle_margin) * np.sign(outer)
        outer_ids = [add(p, design.length) for p in scale]
        last = ring_ids[-1]
        for k in range(seg):
            k2 = (k + 1) % len(last)
            m.tris.append((last[k], outer_ids[k], outer_ids[k2], baf_tag))
            m.tris.append((last[k], outer_ids[k2], last[k2], baf_tag))

    m.meta = {"n_around": int(n_around), "n_stations": int(n_stations),
              "length_mm": design.length * 1e3,
              "mouth_w_mm": design.mouth_width * 1e3,
              "mouth_h_mm": design.mouth_height * 1e3,
              "baffle_margin_mm": baffle_margin * 1e3,
              "symmetry": symmetry}
    return m


# ---------------------------------------------------------------------------
#  MSH 2.2 file I/O
# ---------------------------------------------------------------------------
def write_msh22(mesh: SurfaceMesh, path) -> "Path":
    """Write the mesh as Gmsh MSH 2.2 - the version AKABAK/ABEC reads."""
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = ["$MeshFormat", f"{MSH_VERSION} 0 8", "$EndMeshFormat"]
    out += ["$PhysicalNames", str(len(mesh.physical))]
    for tag, name in sorted(mesh.physical.items()):
        out.append(f'2 {tag} "{name}"')
    out.append("$EndPhysicalNames")
    out += ["$Nodes", str(len(mesh.nodes))]
    for i, (x, y, z) in enumerate(mesh.nodes, start=1):
        out.append(f"{i} {x:.6e} {y:.6e} {z:.6e}")
    out.append("$EndNodes")
    out += ["$Elements", str(len(mesh.tris))]
    for i, (n0, n1, n2, tag) in enumerate(mesh.tris, start=1):
        out.append(f"{i} {TRIANGLE} 2 {int(tag)} 0 {n0 + 1} {n1 + 1} {n2 + 1}")
    out.append("$EndElements")
    path.write_text("\n".join(out) + "\n", encoding="ascii")
    return path


def read_msh22(path) -> dict:
    """Read back an MSH 2.2 file (used for verification and by the tests)."""
    from pathlib import Path

    lines = Path(path).read_text(encoding="ascii").splitlines()
    info: dict = {"version": "", "physical": {}, "nodes": [], "tris": [], "counts": {}}
    i, n = 0, len(lines)
    while i < n:
        key = lines[i].strip()
        if key == "$MeshFormat":
            info["version"] = lines[i + 1].split()[0]
            i += 3
            continue
        if key == "$PhysicalNames":
            cnt = int(lines[i + 1])
            for k in range(cnt):
                parts = lines[i + 2 + k].split(maxsplit=2)
                info["physical"][int(parts[1])] = parts[2].strip().strip('"')
            i += cnt + 3
            continue
        if key == "$Nodes":
            cnt = int(lines[i + 1])
            for k in range(cnt):
                parts = lines[i + 2 + k].split()
                info["nodes"].append(tuple(float(v) for v in parts[1:4]))
            i += cnt + 3
            continue
        if key == "$Elements":
            cnt = int(lines[i + 1])
            for k in range(cnt):
                parts = lines[i + 2 + k].split()
                etype, ntags = int(parts[1]), int(parts[2])
                tags = [int(v) for v in parts[3:3 + ntags]]
                nodes = [int(v) - 1 for v in parts[3 + ntags:]]
                if etype == TRIANGLE and len(nodes) == 3:
                    info["tris"].append((nodes[0], nodes[1], nodes[2], tags[0] if tags else 0))
            i += cnt + 3
            continue
        i += 1
    for tag, name in info["physical"].items():
        info["counts"][name] = sum(1 for t in info["tris"] if t[3] == tag)
    return info


# ---------------------------------------------------------------------------
#  optional: Gmsh script + meshing (for CAD/STEP and for people who prefer it)
# ---------------------------------------------------------------------------
def write_geo(design, path, n_around: int = 40, n_stations: int = 10,
              mesh_frequency: float = 500.0, c: float = 343.0) -> "Path":
    """A Gmsh .geo script for the same geometry (only useful if Gmsh is installed).

    Uses the OpenCASCADE factory: the caps are created first (so they own tags 1 and
    2) and the horn surface is a ThruSections loft through the section loops. The
    built-in kernel cannot loft a loop with more than 4 edges, which is why OCC is
    required here.
    """
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    zs = np.linspace(0.0, design.length, int(n_stations) + 1)
    rings = [section_outline(design, z, int(n_around)) for z in zs]
    out = ["// horn-workflow: generated geometry (section loft, throat circle -> mouth)",
           'SetFactory("OpenCASCADE");',
           "Mesh.MshFileVersion = 2.2;",
           f"Mesh.CharacteristicLengthMax = {c / mesh_frequency / 6 * 1e3:.1f};",
           "Mesh.Algorithm = 6;"]
    pid, ring_ids, loops = 1, [], []
    for ring, z in zip(rings, zs):
        ids = []
        for (x, y) in ring:
            out.append(f"Point({pid}) = {{{x:.6f}, {y:.6f}, {z:.6f}, 0}};")
            ids.append(pid)
            pid += 1
        ring_ids.append(ids)
    for i, ids in enumerate(ring_ids):
        cids = []
        for k in range(len(ids)):
            out.append(f"Line({pid}) = {{{ids[k]}, {ids[(k + 1) % len(ids)]}}};")
            cids.append(pid)
            pid += 1
        out.append(f"Curve Loop({i + 1}) = {{{', '.join(str(v) for v in cids)}}};")
        loops.append(i + 1)
    # caps first: they must own the low surface tags, the loft adds its own after
    out.append(f"Plane Surface(1) = {{{loops[0]}}};")          # throat -> source
    out.append(f"Plane Surface(2) = {{{loops[-1]}}};")         # mouth  -> interface
    out.append(f"out[] = ThruSections{{{', '.join(str(v) for v in loops)}}};")
    out += ['Physical Surface("source") = {1};',
            'Physical Surface("interface") = {2};',
            'Physical Surface("wall") = {out[]};',
            "Mesh.SaveAll = 0;"]
    path.write_text("\n".join(out) + "\n", encoding="ascii")
    return path


def run_gmsh(geo, out_dir) -> dict:
    """Mesh with Gmsh if it is installed; otherwise say how to get it."""
    import shutil
    import subprocess
    from pathlib import Path

    exe = shutil.which("gmsh")
    out_dir = Path(out_dir)
    if exe is None:
        return {"ok": False, "reason": "gmsh not installed - run: sudo apt install gmsh"}
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {"ok": True, "msh": None, "stl": None, "log": ""}
    for fmt, target in (("msh2", out_dir / "horn_from_geo.msh"),
                        ("stl", out_dir / "horn_from_geo.stl")):
        try:
            proc = subprocess.run([exe, str(geo), "-2", "-format", fmt, "-o", str(target),
                                   "-v", "2"], capture_output=True, text=True, timeout=900)
        except Exception as exc:                  # pragma: no cover - environment dependent
            return {"ok": False, "reason": f"gmsh failed: {exc}"}
        res["log"] += (proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]
        if proc.returncode != 0:
            return {"ok": False, "reason": f"gmsh returned {proc.returncode} for {fmt}"}
        res["msh" if fmt.startswith("msh") else "stl"] = target
    return res


