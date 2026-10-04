"""Build package: from a simulated design to geometry you can actually make.

Outputs (all optional except the first three, which need nothing but Python):

  profile.csv / profile.dxf    the wall curve (stacks, CAD, plotter)
  slices.csv / slices.dxf      per-slice cross section + wall frame (MDF stack / CNC)
  horn.stl                     printable/visable solid (outer + inner + rims)
  horn.msh                     BEM mesh, MSH 2.2 (feeds Stage 2)
  horn.geo                     optional Gmsh script for people who want Gmsh/CAD
  build_sheet.md               dimensions, slice list, material estimate, assembly
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import mesh
from .config import Params
from .response import Result


# ---------------------------------------------------------------------------
#  DXF (written by hand - no CAD library needed)
# ---------------------------------------------------------------------------
def write_dxf(polylines: list, path, layer: str = "horn") -> Path:
    """polylines: [(layer_name, (n,2) array in mm), ...] as LWPOLYLINE entities."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1015", "0", "ENDSEC",
           "0", "SECTION", "2", "ENTITIES"]
    for name, points in polylines:
        pts = np.asarray(points, dtype=float)
        out += ["0", "LWPOLYLINE", "8", str(name), "90", str(len(pts)), "70", "0"]
        for x, y in pts:
            out += ["10", f"{x:.4f}", "20", f"{y:.4f}"]
    out += ["0", "ENDSEC", "0", "EOF"]
    path.write_text("\n".join(out) + "\n", encoding="ascii")
    return path


# ---------------------------------------------------------------------------
#  wall profile
# ---------------------------------------------------------------------------
def profile_rows(design, step_mm: float = 20.0) -> list:
    xs = np.arange(0.0, design.length + 1e-9, step_mm * 1e-3)
    if xs[-1] < design.length - 1e-9:
        xs = np.append(xs, design.length)
    rows = []
    for x in xs:
        t = 0.0 if design.length <= 0 else x / design.length
        outline = mesh.section_outline(design, x, 256)
        width = 2.0 * float(np.abs(outline[:, 0]).max())
        height = 2.0 * float(np.abs(outline[:, 1]).max())
        radius = float(np.atleast_1d(design.radius(x))[0])
        rows.append({"x_mm": x * 1e3, "radius_mm": radius * 1e3,
                     "width_mm": width * 1e3, "height_mm": height * 1e3,
                     "area_cm2": math.pi * radius ** 2 * 1e4,
                     "profile_fraction": t})
    return rows


def write_profile_csv(rows: list, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "x_mm,radius_mm,width_mm,height_mm,area_cm2,profile_fraction"
    body = "\n".join(
        f"{r['x_mm']:.2f},{r['radius_mm']:.2f},{r['width_mm']:.2f},{r['height_mm']:.2f},"
        f"{r['area_cm2']:.1f},{r['profile_fraction']:.4f}" for r in rows)
    path.write_text(head + "\n" + body + "\n", encoding="ascii")
    return path


def profile_dxf(design, n: int = 161) -> tuple:
    xs = np.linspace(0.0, design.length, n)
    top = np.column_stack([xs * 1e3,
                           np.atleast_1d(design.radius(xs)) * 1e3])
    bottom = np.column_stack([xs * 1e3, -np.atleast_1d(design.radius(xs)) * 1e3])
    return [("profile_top", top), ("profile_bottom", bottom)]


# ---------------------------------------------------------------------------
#  slice stack (the practical way to build a horn this size from sheet material)
# ---------------------------------------------------------------------------
def slice_rows(design, slice_size_mm: float = 100.0, wall_mm: float = 18.0,
               n_around: int = 64) -> list:
    step = max(20.0, float(slice_size_mm)) * 1e-3
    zs = np.arange(0.0, design.length, step)
    if len(zs) == 0 or zs[-1] < design.length - 1e-9:
        zs = np.append(zs, design.length)
    rows = []
    for i in range(len(zs) - 1):
        z0, z1 = zs[i], zs[i + 1]
        outline = mesh.section_outline(design, 0.5 * (z0 + z1), int(n_around))
        a = float(np.abs(outline[:, 0]).max())
        b = float(np.abs(outline[:, 1]).max())
        area = math.pi * float(np.atleast_1d(design.radius(0.5 * (z0 + z1)))[0]) ** 2
        rows.append({
            "index": i + 1,
            "z_from_mm": z0 * 1e3, "z_to_mm": z1 * 1e3,
            "thickness_mm": (z1 - z0) * 1e3,
            "width_mm": 2.0 * a * 1e3, "height_mm": 2.0 * b * 1e3,
            "inner_area_cm2": area * 1e4,
            "outline": outline * 1e3,
            "frame": _offset_outline(outline, wall_mm * 1e-3) * 1e3,
        })
    return rows


def _offset_outline(outline: np.ndarray, offset: float) -> np.ndarray:
    """Push an outline outwards by `offset` [m] (for the slice frame/wall)."""
    out = np.array(outline, dtype=float)
    norms = np.linalg.norm(out, axis=1)
    norms[norms == 0.0] = 1.0
    return out * (1.0 + offset / norms)[:, None]


def write_slices_csv(rows: list, path) -> Path:
    path = Path(path)
    head = ("slice,z_from_mm,z_to_mm,thickness_mm,width_mm,height_mm,inner_area_cm2,"
            "outer_width_mm,outer_height_mm")
    body = []
    for r in rows:
        fw = 2.0 * float(np.abs(r["frame"][:, 0]).max())
        fh = 2.0 * float(np.abs(r["frame"][:, 1]).max())
        body.append(f"{r['index']},{r['z_from_mm']:.1f},{r['z_to_mm']:.1f},"
                    f"{r['thickness_mm']:.1f},{r['width_mm']:.1f},{r['height_mm']:.1f},"
                    f"{r['inner_area_cm2']:.1f},{fw:.1f},{fh:.1f}")
    path.write_text(head + "\n" + "\n".join(body) + "\n", encoding="ascii")
    return path


def slices_dxf(rows: list, path) -> Path:
    """One outline + frame per slice, laid out in a grid and labelled by layer."""
    if not rows:
        return write_dxf([], path)
    widest = max(max(float(np.abs(r["frame"][:, 0]).max()) for r in rows), 1e-3)
    tallest = max(max(float(np.abs(r["frame"][:, 1]).max()) for r in rows), 1e-3)
    cols = int(math.ceil(math.sqrt(len(rows))))
    pitch_x, pitch_y = 2.2 * widest * 1e3, 2.2 * tallest * 1e3
    polys = []
    for i, r in enumerate(rows):
        cx = (i % cols) * pitch_x
        cy = (i // cols) * pitch_y
        name = f"s{r['index']:02d}_z{r['z_from_mm']:.0f}-{r['z_to_mm']:.0f}"
        polys.append((name, np.column_stack([r["frame"][:, 0] + cx, r["frame"][:, 1] + cy])))
        polys.append((name + "_hole", np.column_stack([r["outline"][:, 0] + cx,
                                                       r["outline"][:, 1] + cy])))
    return write_dxf(polys, path)


# ---------------------------------------------------------------------------
#  solid (printable) model: outer wall + inner wall + rims
# ---------------------------------------------------------------------------
@dataclass
class _Shrunk:
    """Wrapper giving section_outline() a horn whose wall is `wall` metres thinner."""

    base: object
    wall: float

    def __getattr__(self, item):
        return getattr(self.base, item)

    def radius(self, x):
        r = np.atleast_1d(self.base.radius(x))
        return np.maximum(r - self.wall, 0.02 * r)


def wall_solid(design, wall_mm: float = 18.0, n_around: int = 48,
               n_stations: int = 12) -> mesh.SurfaceMesh:
    """Closed solid of the horn wall: outer surface, inner surface and both rims."""
    wall = float(wall_mm) * 1e-3
    m = mesh.SurfaceMesh()
    m.physical = {1: "solid"}
    tag = 1
    zs = np.linspace(0.0, design.length, int(n_stations) + 1)
    inner = _Shrunk(design, wall)

    def rings(d):
        return [[(float(p[0]), float(p[1]), float(z))
                 for p in mesh.section_outline(d, z, int(n_around))] for z in zs]

    o_rings, i_rings = rings(design), rings(inner)
    idx_o = [[(m.nodes.append(p) or (len(m.nodes) - 1)) for p in ring] for ring in o_rings]
    idx_i = [[(m.nodes.append(p) or (len(m.nodes) - 1)) for p in ring] for ring in i_rings]
    n = int(n_around)

    for r in range(int(n_stations)):                     # outer + inner lateral surfaces
        for k in range(n):
            k2 = (k + 1) % n
            m.tris.append((idx_o[r][k], idx_o[r][k2], idx_o[r + 1][k2], tag))
            m.tris.append((idx_o[r][k], idx_o[r + 1][k2], idx_o[r + 1][k], tag))
            m.tris.append((idx_i[r][k], idx_i[r + 1][k2], idx_i[r][k2], tag))
            m.tris.append((idx_i[r][k], idx_i[r + 1][k], idx_i[r + 1][k2], tag))
    for k in range(n):                                   # throat rim and mouth rim
        k2 = (k + 1) % n
        m.tris.append((idx_o[0][k], idx_i[0][k2], idx_o[0][k2], tag))
        m.tris.append((idx_o[0][k], idx_i[0][k], idx_i[0][k2], tag))
        m.tris.append((idx_o[-1][k], idx_o[-1][k2], idx_i[-1][k2], tag))
        m.tris.append((idx_o[-1][k], idx_i[-1][k2], idx_i[-1][k], tag))

    vol = closed_volume(m)
    if vol < 0:                                          # flip so normals point outward
        m.tris = [(a, c, b, t) for a, b, c, t in m.tris]
        vol = -vol
    m.meta = {"wall_mm": float(wall_mm), "volume_l": vol * 1e3,
              "n_around": n, "n_stations": int(n_stations)}
    return m


def closed_volume(m: mesh.SurfaceMesh) -> float:
    """Signed volume of a closed triangle mesh (positive when normals point out)."""
    v = 0.0
    for n0, n1, n2, _ in m.tris:
        p0, p1, p2 = (np.asarray(m.nodes[i], dtype=float) for i in (n0, n1, n2))
        v += float(np.dot(p0, np.cross(p1, p2)))
    return v / 6.0


def write_stl(m: mesh.SurfaceMesh, path, name: str = "horn") -> Path:
    """ASCII STL of a triangle mesh (viewers, slicers, meshmixer...)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = [f"solid {name}"]
    for n0, n1, n2, _ in m.tris:
        p0, p1, p2 = (np.asarray(m.nodes[i], dtype=float) for i in (n0, n1, n2))
        nrm = np.cross(p1 - p0, p2 - p0)
        ln = float(np.linalg.norm(nrm))
        nrm = nrm / ln if ln > 0 else np.zeros(3)
        out.append(f"  facet normal {nrm[0]:.6e} {nrm[1]:.6e} {nrm[2]:.6e}")
        out.append("    outer loop")
        for p in (p0, p1, p2):
            out.append(f"      vertex {p[0]:.6e} {p[1]:.6e} {p[2]:.6e}")
        out.append("    endloop")
        out.append("  endfacet")
    out.append(f"endsolid {name}")
    path.write_text("\n".join(out) + "\n", encoding="ascii")
    return path




# ---------------------------------------------------------------------------
#  verification
# ---------------------------------------------------------------------------
def verify(design, m: mesh.SurfaceMesh, msh_path=None, solid=None) -> list:
    """Consistency checks between the design numbers and the generated geometry."""
    out = []

    def add(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    if msh_path is not None:
        info = mesh.read_msh22(msh_path)
        add("MSH file version is 2.2 (the version AKABAK reads)",
            info["version"] == mesh.MSH_VERSION, f"version {info['version']}")
        add("physical groups present",
            {"source", "wall", "interface"} <= set(info["physical"].values()),
            ", ".join(info["physical"].values()))
        add("triangle count matches the in-memory mesh", len(info["tris"]) == len(m.tris),
            f"{len(info['tris'])} triangles")
    areas = m.area_by_group()
    add("source disk area == throat area",
        abs(areas.get("source", 0.0) - design.St) / design.St < 0.01,
        f"{areas.get('source', 0.0) * 1e4:.1f} vs {design.St * 1e4:.1f} cm^2")
    add("mouth plane area == mouth area",
        abs(areas.get("interface", 0.0) - design.Sm) / design.Sm < 0.02,
        f"{areas.get('interface', 0.0) * 1e4:.0f} vs {design.Sm * 1e4:.0f} cm^2")
    lo, hi = m.bounds()
    add("depth (z extent) == horn length", abs((hi[2] - lo[2]) - design.length) < 1e-3,
        f"{(hi[2] - lo[2]) * 1e3:.1f} mm")
    add("mouth height covered (baffle ring included)",
        (hi[1] - lo[1]) >= design.mouth_height - 1e-3, f"{(hi[1] - lo[1]) * 1e3:.0f} mm")
    if solid is not None:
        vol = closed_volume(solid)
        add("solid model closed and positively oriented", vol > 0.0,
            f"{vol * 1e3:.1f} litres of wall material")
        bad = orientation_problems(solid)
        add("solid model orientation consistent (no flipped faces)", bad == 0,
            f"{bad} bad edges")
    return out


def orientation_problems(m: mesh.SurfaceMesh) -> int:
    """Count edges whose two triangles traverse them in the same direction.

    A closed mesh can still have flipped faces; this catches them (the raw volume
    then comes out wrong, which is how the bug shows up).
    """
    seen: dict = {}
    bad = 0
    for a, b, c, _ in m.tris:
        for e in ((a, b), (b, c), (c, a)):
            key = tuple(sorted(e))
            forward = e[0] == key[0]
            if key in seen:
                if seen[key] == forward:          # same direction -> inconsistent
                    bad += 1
            else:
                seen[key] = forward
    return bad


# ---------------------------------------------------------------------------
#  build sheet
# ---------------------------------------------------------------------------
def _outline_size(design) -> str:
    o = mesh.section_outline(design, design.length, 720)
    if design.mouth_shape != "rectangular":
        return f"{2 * float(np.abs(o[:, 0]).max()) * 1e3:.0f} mm diameter"
    return (f"{2 * float(np.abs(o[:, 0]).max()) * 1e3:.0f} x "
            f"{2 * float(np.abs(o[:, 1]).max()) * 1e3:.0f} mm")


def _wall_area(design) -> float:
    xs = np.linspace(0.0, design.length, 400)
    r = np.atleast_1d(design.radius(xs))
    return float(np.sum(2.0 * math.pi * 0.5 * (r[1:] + r[:-1]) * np.diff(xs)))


def build_sheet_md(params: Params, result: Result, prof: list, slices: list, files: dict,
                   verification: list, path: Path) -> Path:
    d, design, drv = result.derived, result.design, params.driver
    wall_l = float(files.get("material_l", 0.0) or 0.0)
    rect = design.mouth_shape == "rectangular"
    if rect:
        mouth_lines = [
            f"| mouth, nominal rectangle | {d['mouth_width_mm']:.0f} x "
            f"{d['mouth_height_mm']:.0f} mm ({design.Sm * 1e4:.0f} cm^2, aspect "
            f"{design.mouth_aspect:.1f}:1) |",
            f"| mouth, built outline | {_outline_size(design)}, soft corners "
            f"(same {design.Sm * 1e4:.0f} cm^2 area) |",
        ]
    else:
        mouth_lines = [
            f"| mouth | {d['mouth_diameter_mm']:.0f} mm circle "
            f"({design.Sm * 1e4:.0f} cm^2) |",
        ]
    md = [
        f"# Build sheet - {params.project}",
        "",
        f"design: **{design.profile} horn, {d['fc_hz']:.0f} Hz cut-off, mouth "
        f"{design.mouth_width * 1e3:.0f} x {design.mouth_height * 1e3:.0f} mm, depth "
        f"{design.length * 1e3:.0f} mm**  ",
        f"driver: {drv.name} ({drv.Sd * 1e4:.0f} cm^2, fs {drv.fs:.1f} Hz, Qts {drv.Qts:.2f}) in "
        f"its sealed {drv.rear_volume * 1e6:.0f} cm^3 chamber  ",
        f"predicted: {result.band_spl(params.target.f_low, params.target.f_high):.1f} dB mean in "
        f"{params.target.f_low:.0f}-{params.target.f_high:.0f} Hz, "
        f"{result.variations_db(params.target.f_low, params.target.f_high):.1f} dB peak-to-peak",
        "",
        "## 1. Dimensions",
        "",
        "| item | value |",
        "| --- | --- |",
        f"| depth (throat plane to mouth) | **{design.length * 1e3:.0f} mm** |",
        f"| throat opening | **{2 * design.rt * 1e3:.0f} mm** circle "
        f"({design.St * 1e4:.0f} cm^2) |",
        *mouth_lines,
        f"| envelope | {design.mouth_width * 1e3:.0f} x {design.mouth_height * 1e3:.0f} x "
        f"{design.length * 1e3:.0f} mm = {d['build_volume_l'] / 1000:.2f} m3 |",
        f"| air inside the horn | {d['horn_volume_l']:.0f} litres |",
        f"| internal surface area | {_wall_area(design):.2f} m2 |",
        f"| wall material ({files.get('wall_mm', 18.0):.0f} mm thick) | {wall_l:.0f} litres "
        f"(~{wall_l * 0.75:.0f} kg in MDF, ~{wall_l * 1.24:.0f} kg printed) |",
        "",
        "## 2. Wall curve (reduced; full table in profile.csv)",
        "",
        "| x [mm] | width [mm] | height [mm] | equal-area radius [mm] | area [cm^2] |",
        "| --- | --- | --- | --- | --- |",
    ]
    step = max(1, len(prof) // 16)
    for r in prof[::step]:
        md.append(f"| {r['x_mm']:.0f} | {r['width_mm']:.0f} | {r['height_mm']:.0f} | "
                  f"{r['radius_mm']:.1f} | {r['area_cm2']:.0f} |")
    md += ["",
           "## 3. Slice stack (the practical way to build this size)",
           "",
           "Cut each slice as a frame, stack and glue, then smooth and seal the inside.",
           "",
           "| slice | z range [mm] | thickness | inner W x H [mm] | frame W x H [mm] |",
           "| --- | --- | --- | --- | --- |",
           ]
    for r in slices:
        fw = 2.0 * float(np.abs(r["frame"][:, 0]).max())
        fh = 2.0 * float(np.abs(r["frame"][:, 1]).max())
        md.append(f"| {r['index']} | {r['z_from_mm']:.0f} - {r['z_to_mm']:.0f} | "
                  f"{r['thickness_mm']:.0f} mm | {r['width_mm']:.0f} x {r['height_mm']:.0f} | "
                  f"{fw:.0f} x {fh:.0f} |")
    return _sheet_part2(params, result, files, verification, md, path)


def _sheet_part2(params: Params, result: Result, files: dict, verification: list,
                 md: list, path: Path) -> Path:
    """Files, construction notes and verification table of the build sheet."""
    design, drv = result.design, params.driver
    md += ["", "## 4. Files", ""]
    for label, name in files.items():
        if name and not isinstance(name, (float, int)):
            md.append(f"* `{Path(str(name)).name}` - {label}")
    md += ["",
           "How to look at them: `horn.stl` opens in any 3D viewer or slicer (Meshmixer, "
           "PrusaSlicer, Windows 3D Viewer); `profile.dxf` / `slices.dxf` open in any CAD "
           "(Fusion, LibreCAD, QCAD - the layers are named per slice); `horn.msh` is the BEM "
           "mesh for Stage 2.",
           "",
           "## 5. Construction notes",
           "",
           "* **Slice stack (MDF or plywood):** the mouth is "
           f"{design.mouth_width * 1e3:.0f} mm across, so build it in slices; `slices.dxf` has "
           "every slice outline and frame, laid out in a grid with the z range in the layer name.",
           "* **Lofted / fibreglass:** use `profile.dxf` for the ribs and `horn.stl` to CNC or "
           "print a mould.",
           "* **3D printed:** `horn.stl` is a closed solid; split it into sections (no desktop "
           "printer takes a "
           f"{design.mouth_width * 1e3:.0f} mm part) and bolt or glue the sections.",
           f"* **Throat plate:** a flat plate with a {2 * design.rt * 1e3:.0f} mm hole bolts the "
           f"horn to your {drv.rear_volume * 1e6:.0f} cm^3 chamber. Keep the hole edges smooth and "
           "the joint airtight.",
           "* **Airtightness beats wall thickness:** seal both joints with gaskets and paint the "
           "inside; a leak at the throat or mouth costs low-frequency output.",
           "* **Brace it:** a 1.6 m mouth in 18 mm sheet material will flex; add ribs behind the "
           "mouth and around the throat flange.",
           "* **Mouth lip:** a modest roundover on the mouth edge reduces diffraction ripple.",
           "",
           "## 6. Verification (run automatically)",
           "",
           "| check | result | detail |",
           "| --- | --- | --- |",
           ]
    for name, ok, detail in verification:
        md.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    md += ["",
           "## 7. Limits",
           "",
           "* The acoustic numbers come from the Stage-1 (1P) model - see `../report.md`; "
           "directivity and diffraction need Stage 2 (BEM).",
           "* The mesh here is geometry for building and for the BEM model, not a structural "
           "analysis.",
           ""]
    path.write_text("\n".join(md), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
#  orchestration
# ---------------------------------------------------------------------------
def run(params: Params, result: Result, out_dir, slice_size_mm: float = 100.0,
        wall_mm: float = 18.0, mesh_frequency: float = 500.0, baffle_margin_mm: float = 400.0,
        with_geo: bool = True) -> dict:
    """Write the whole build package; returns the file map and the verification table."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    design = result.design
    files: dict = {"wall_mm": float(wall_mm)}

    prof = profile_rows(design, 20.0)
    files["wall profile, every 20 mm"] = write_profile_csv(prof, out / "profile.csv")
    files["wall profile as CAD polylines"] = write_dxf(profile_dxf(design), out / "profile.dxf",
                                                       layer="profile")

    slices = slice_rows(design, slice_size_mm, wall_mm)
    files["slice stack table"] = write_slices_csv(slices, out / "slices.csv")
    files["slice outlines and frames (DXF grid)"] = slices_dxf(slices, out / "slices.dxf")

    solid = wall_solid(design, wall_mm, n_around=64, n_stations=16)
    files["printable/visible solid (STL)"] = write_stl(solid, out / "horn.stl", params.project)
    files["material_l"] = float(solid.meta["volume_l"])

    suggestions = mesh.suggest_mesh(design, mesh_frequency, params.simulation.c)
    m = mesh.horn_mesh(design, suggestions["n_around"], suggestions["n_stations"],
                       baffle_margin=baffle_margin_mm * 1e-3)
    msh = out / "horn.msh"
    mesh.write_msh22(m, msh)
    files[f"BEM surface mesh, {len(m.tris)} triangles (for Stage 2)"] = msh

    gmsh = {"ok": False, "reason": "not requested"}
    if with_geo:
        geo = mesh.write_geo(design, out / "horn.geo", suggestions["n_around"],
                            suggestions["n_stations"], mesh_frequency, params.simulation.c)
        files["Gmsh script (optional)"] = geo
        gmsh = mesh.run_gmsh(geo, out)
        if gmsh["ok"]:
            files["mesh from Gmsh (msh2)"] = gmsh["msh"]
            files["surface mesh from Gmsh (STL; horn.stl is the printable solid)"] = gmsh["stl"]

    verification = verify(design, m, msh, solid)
    sheet = build_sheet_md(params, result, prof, slices, files, verification,
                           out / "build_sheet.md")
    return {"files": files, "verification": verification, "sheet": sheet, "mesh": m,
            "solid": solid, "slices": slices, "profile": prof, "suggested_mesh": suggestions,
            "gmsh_note": (gmsh.get("reason") if with_geo and not gmsh["ok"] else "gmsh ok")
            if with_geo else None}


