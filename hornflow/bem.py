"""Stage 2: the AKABAK (BEM + LE) side of the workflow.

The Linux half lives here:
  * `driver_le.txt`      the lumped-element driver script, in ABEC/AKABAK syntax,
                         generated from the measured parameters in the YAML file
  * `bem.msh`            the BEM surface mesh in Gmsh MSH 2.2 (see mesh.py)
  * `bem.geo`            the same geometry as a Gmsh script (optional)
  * `akabak_recipe.md`   click-by-click instructions, the install route, and what
                         to send back
  * `--stage 2 --bem-import <folder>`  reads the exported spectra, writes
                         `bem/curves_stage2.csv` + `bem/compare.md` +
                         `bem/compare.png` and compares them with the Stage-1 model

Why not ATH here: ATH generates OS-SE and circular-arc profiles only, while this
design is an exponential horn. Feeding AKABAK our own mesh keeps the geometry
exactly as designed (and reuses the build package).
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

from . import mesh
from .config import Params
from .physics.solvers import manual as _manual
from .response import Result

NOTES_FOR_US = ("the exported spectra (the Files folder of Preferences-VACS, or the VACS "
                "project saved from VacsViewer), the .msh file, and a screenshot of the "
                "solved project")


# ---------------------------------------------------------------------------
#  lumped-element driver script (ABEC/AKABAK syntax; same shape as ATH's
#  generic25.txt, so it also works inside ATH-generated projects)
# ---------------------------------------------------------------------------
def le_driver_script(params: Params) -> str:
    d = params.driver
    return f"""// horn-workflow: lumped-element model of {d.name}
// generated from params/drivers/{d.name}.yaml - regenerate rather than edit
// units: dD mm, Mms g, Cms m/N, Rms Ns/m, Bl Tm, Re ohm, fre kHz, Le mH
Def_Driver '{d.name}'
  dD={d.dD * 1e3:.2f}mm
  Mms={d.Mms * 1e3:.2f}g
  Cms={d.Cms:.6e}m/N
  Rms={d.Rms:.3f}Ns/m
  Bl={d.Bl:.3f}Tm
  Re={d.Re:.3f}ohm
  fre={d.fre:.3f}kHz ExpoRe={d.ExpoRe:.3f}
  Le={d.Le * 1e3:.4f}mH ExpoLe={d.ExpoLe:.4f}

System 'S1'
  Driver 'D1' Def='{d.name}' Node=1=0=10=20

  // rear chamber: the existing sealed box behind the driver
  Enclosure 'Vb' Node=20
    Vb={d.rear_volume * 1e6:.0f}cm3 Qb/fo=0.1

  // short duct from the diaphragm to the BEM throat (the BEM part takes over here)
  Duct 'front' Node=10=100
    dD={d.dD * 1e3:.2f}mm Len=2mm

  // coupling element to the BEM model: this node is driven by the horn mesh
  RadImp 'Throat' Node=100 DrvGroup=1001
"""


def write_le_script(params: Params, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(le_driver_script(params), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
#  Stage-2 input files
# ---------------------------------------------------------------------------
def write_bem_files(params: Params, result: Result, out_dir, mesh_frequency: float = 500.0,
                    baffle_margin_mm: float = 400.0, platform: str = "wine",
                    symmetry: str = None, run_id: str | None = None) -> dict:
    """Write the Stage-2 inputs: mesh, optional geo, LE script, manifest, recipe.

    symmetry = 'x', 'y' or 'xy' additionally writes a cut (half/quarter) mesh for
    a project that exploits `Global -> Dim, Sym and BEM -> Symmetry`; that mesh
    deliberately carries no baffle ring, because the ring's outward offset would
    leave the plane of symmetry.

    A run manifest is written next to the inputs: it fingerprints what HornFlow
    handed over, when, and where the ``.vips`` exports are expected, so the
    import step can validate provenance.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    design = result.design
    suggest = mesh.suggest_mesh(design, mesh_frequency, params.simulation.c)
    m = mesh.horn_mesh(design, suggest["n_around"], suggest["n_stations"],
                       baffle_margin=baffle_margin_mm * 1e-3)
    files = {
        "BEM surface mesh (MSH 2.2)": mesh.write_msh22(m, out / "bem.msh"),
    }
    sym_mesh, sym_name = None, None
    if symmetry:
        symmetry = str(symmetry).strip().lower()
        sym_mesh = mesh.horn_mesh(design, suggest["n_around"], suggest["n_stations"],
                                  baffle_margin=0.0, symmetry=symmetry)
        sym_name = "bem_quarter.msh" if symmetry == "xy" else "bem_half.msh"
        files[f"symmetric BEM mesh (Symmetry={symmetry})"] = mesh.write_msh22(sym_mesh,
                                                                             out / sym_name)
    files.update({
        "lumped-element driver script": write_le_script(params, out / "driver_le.txt"),
        "Gmsh script (optional)": mesh.write_geo(design, out / "bem.geo", suggest["n_around"],
                                                 suggest["n_stations"], mesh_frequency,
                                                 params.simulation.c),
    })
    # manifest first (the recipe reads its timestamp), then the recipe, then the
    # final manifest naming every input ABAKAK consumes.
    rid = run_id or f"legacy-{params.project}"
    manifest = _manual.build_manifest(
        run_id=rid, project=params.project, input_path=params.source_path,
        solver="akabak-bem", solver_version="3.3-demo",
        fidelity="BEM_SOLVER", bem_dir=out, export_dir=out / "export",
        files={k: str(v) for k, v in files.items()},
        expected_exports=["*.vips", "*.txt"],
        notes="AKABAK Free 3.3.2 b144 under Wine; the GUI solve is manual by design.")
    _manual.write_manifest(manifest, out / _manual.MANIFEST_NAME)
    files["instructions"] = recipe_md(params, result, suggest, m, out / "akabak_recipe.md",
                                      platform, symmetry=symmetry, sym_name=sym_name,
                                      sym_mesh=sym_mesh, manifest=manifest, run_id=rid)
    files["run manifest"] = out / _manual.MANIFEST_NAME
    return {"files": files, "mesh": m, "suggest": suggest, "sym_mesh": sym_mesh,
            "manifest": manifest}



# ---------------------------------------------------------------------------
#  the recipe
# ---------------------------------------------------------------------------
def recipe_md(params: Params, result: Result, suggest: dict, m: mesh.SurfaceMesh,
              path: Path, platform: str = "wine", symmetry: str = None, sym_name: str = None,
              sym_mesh: mesh.SurfaceMesh = None, manifest=None,
              run_id: str | None = None) -> Path:
    d, design, drv, t = result.derived, result.design, params.driver, params.target
    areas = m.area_by_group()
    where = "Wine on Linux" if platform == "wine" else "native Windows"
    rid = run_id or (manifest.run_id if manifest is not None else f"legacy-{params.project}")
    import_cmd = (f"python3 run_workflow.py {params.source_path} --stage 2 "
                  f"--bem-import {path.parent.as_posix()}/export")
    checklist = _manual.checklist_md(
        project=params.project, run_id=rid, input_path=params.source_path,
        bem_dir=path.parent, export_dir=path.parent / "export",
        expected_exports=(manifest.expected_exports if manifest is not None
                          else ["*.vips", "*.txt"]),
        manifest_path=path.parent / _manual.MANIFEST_NAME, legacy_cmd=import_cmd)
    md = checklist.splitlines() + [
        "",
        "---",
        "",
        f"# Detailed recipe - {params.project} ({where})",
        "",
        "Goal: verify the Stage-1 prediction of this horn with a 3D boundary-element solve.",
        "",
        f"* horn: {design.profile}, cut-off {d['fc_hz']:.0f} Hz, mouth "
        f"{design.mouth_width * 1e3:.0f} x {design.mouth_height * 1e3:.0f} mm, depth "
        f"{design.length * 1e3:.0f} mm",
        f"* mesh: `bem.msh`, {len(m.tris)} triangles in MSH 2.2, groups: "
        + ", ".join(f"{k} ({areas[k]:.2f} m2)" for k in sorted(areas)),
        f"* driver: {drv.name} - Re {drv.Re:.2f} ohm, Bl {drv.Bl:.2f} Tm, Mms "
        f"{drv.Mms * 1e3:.0f} g, Cms {drv.Cms:.2e} m/N, Rms {drv.Rms:.2f} Ns/m, Le "
        f"{drv.Le * 1e3:.2f} mH, rear chamber {drv.rear_volume * 1e6:.0f} cm3",
        f"* band: {t.f_low:.0f}-{t.f_high:.0f} Hz; mesh good to "
        f"{suggest['mesh_frequency_hz']:.0f} Hz (element size "
        f"{suggest['element_size_mm']:.0f} mm)",
    ]
    if symmetry and sym_mesh is not None:
        sa = sym_mesh.area_by_group()
        md += [
            f"* symmetry mesh: `{sym_name}`, {len(sym_mesh.tris)} triangles "
            f"({len(sym_mesh.tris) / max(1, len(m.tris)) * 100:.0f} % of `bem.msh`), groups: "
            + ", ".join(f"{k} ({sa[k]:.3f} m2)" for k in sorted(sa))
            + f" - for `Symmetry={symmetry}` in `Global -> Dim, Sym and BEM` (step 11)",
        ]
    md += [
        "",
        "## 1. The software (already downloaded in this project)",
        "",
        "| file | what it is |",
        "| --- | --- |",
        "| `AKABAK/AKABAK_Free_v332b144_NoInstaller.zip` | AKABAK Free 3.3.2 b144, already "
        "unpacked into `AKABAK/free/` |",
        "| `AKABAK/free/AKABAK_Demo_64r.exe` | the program (32-bit build: "
        "`AKABAK_Demo_32r.exe`) |",
        "| `AKABAK/free/Akabak.chm` | the help file (read this for the GUI details) |",
        "| `AKABAK/AKABAK-Examples.zip` | example projects - unzip into the same folder |",
        "| `AKABAK/VACSVIEWER_64_v213b33_NoInstaller.zip` | VACS plot viewer (optional) |",
        "",
        "Start it with the launcher that ships with this project:",
        "",
        "```",
        "AKABAK/akabak.sh          # register VacsViewer once, then start the 64-bit demo",
        "AKABAK/akabak.sh --vacs   # only (re-)register the VACS/VacsViewer COM server",
        "```",
        "",
        "Notes worth knowing before you start:",
        "",
        "* a graphical desktop is required (Wine needs a display - not a plain SSH session);",
        "* the demo **does not save solving-result files**, so export the curves (step 7) and "
        "re-solve when you need them again;",
        "* the AKABAK-to-VACS link is Windows COM and it **does work** in this Wine prefix "
        "once `VacsViewer.exe /RegServer` has run (`AKABAK/akabak.sh --vacs`; verified with "
        "Wine 6.0.3 on this laptop): the curves appear in VacsViewer while you work. If it "
        "ever refuses, step 7 lists the COM-free fallback;",
        "* if a window does not appear, run `winecfg` once and try again.",
        "",
    ]
    return _recipe_part2(params, result, suggest, m, path, md, where, t, symmetry, sym_name,
                         sym_mesh)


def _recipe_part2(params: Params, result: Result, suggest: dict, m: mesh.SurfaceMesh,
                  path: Path, md: list, where: str, t, symmetry: str = None,
                  sym_name: str = None, sym_mesh: mesh.SurfaceMesh = None) -> Path:
    """Steps 2-4 of the recipe: project, mesh, BEM tree."""
    d, drv = result.derived, params.driver
    areas = m.area_by_group()
    lo, hi = m.bounds()
    md += [
        "## 2. Start the project",
        "",
        "1. `File -> New project`, type **BEM project**, 3D (not axisymmetric - the mouth is "
        "rectangular).",
        f"2. `Global -> Frequencies`: {t.f_low:.0f} - {t.f_high:.0f} Hz, logarithmic, about "
        f"{max(20, int(math.log10(t.f_high / t.f_low) * 60))} points.",
        f"3. `Global -> Meshing`: **mesh frequency {suggest['mesh_frequency_hz']:.0f} Hz** "
        f"(largest element edge = lambda/6 = {suggest['element_size_mm']:.0f} mm).",
        "4. `Global -> BEM Parameters`: **free standing** unless the horn will stand in a "
        "wall. The Stage-1 curve assumed a baffled (half-space) mouth, so the bottom octave "
        "reads a few dB lower here - expected, not an error. The floor (+3 dB at the mouth) "
        "is a later refinement via `Infinite Baffle` or a rigid plane.",
        "",
        "## 3. The mesh - Mesh File object plus Elements components",
        "",
        "1. Page **General**, new component **Mesh File**, load `bem.msh`.",
        "2. **All coordinates are in metres** (the horn is 1499 mm long, i.e. 1.499 in the "
        "file). Leave **Scaling = 1** everywhere. Do *not* apply 0.001.",
        "3. Fingerprints of this exact file - if your import shows other numbers, the wrong "
        "file is loaded:",
        "",
        "| check | expected |",
        "| --- | --- |",
        f"| nodes / triangles | {len(m.nodes)} / {len(m.tris)} (AKABAK reports them as "
        "nodes / shapes) |",
        f"| bounding box | {(hi[0] - lo[0]) * 1e3:.0f} x {(hi[1] - lo[1]) * 1e3:.0f} x "
        f"{(hi[2] - lo[2]) * 1e3:.0f} mm |",
        f"| bounding-box centre height | {(lo[2] + hi[2]) / 2 * 1e3:.2f} mm (AKABAK's own "
        "*centroid* line is area-weighted, so it prints higher - about 840 mm here) |",
        f"| element edge | from {suggest['element_size_mm']:.1f} mm (mesh frequency "
        f"{suggest['mesh_frequency_hz']:.0f} Hz) up to the horn length |",
        "",
        "4. Every **Elements** component picks its sub-set of this mesh by **Tags** - the "
        "physical group names below are already in the file, so a component needs only the "
        "`Mesh File` link plus the tag.",
        "",
        "## 4. The BEM tree",
        "",
        "| mesh group | area | GUI component | type of boundary |",
        "| --- | --- | --- | --- |",
        f"| `source` - throat disk | {areas.get('source', 0.0):.2f} m2 | Elements **Throat** "
        "in subdomain `Interior` | **Driven** |",
        f"| `wall` | {areas.get('wall', 0.0):.2f} m2 | Elements **Hornwall** | Neumann "
        "(rigid) |",
        f"| `interface` - mouth plane | {areas.get('interface', 0.0):.2f} m2 | **Interface** "
        "**Mouth** | - |",
        f"| `baffle` - flat ring | {areas.get('baffle', 0.0):.2f} m2 | *no component* | - |",
        "",
        "* `Interior` = Subdomain, Domain = **Interior**: a closed finite volume whose "
        "boundaries are the horn walls plus the throat disk (normals point into the volume).",
        "* `Mouth` = Interface, Subdomain 1 = **Interior**, Subdomain 2 = **Exterior** - this "
        "couples the horn to the outside air (Sub-Domain Modelling). Watch this one: if "
        "Subdomain 2 is left pointing at `Interior` the exterior field is wrong.",
        "* `Exterior` = Subdomain, Domain = **Exterior** (infinite domain, no reflections).",
        "* `baffle` is an artificial 400 mm vertical margin that only exists for wall-mount "
        "models: simply do not create an Elements component for it. Regenerate the mesh with "
        "`--bem-baffle 0` if you prefer a leaner file.",
        f"* The driven disk is {areas.get('source', 0.0) * 1e4:.0f} cm2 against Sd = "
        f"{drv.Sd * 1e4:.0f} cm2 of the {drv.name} (Sd/St = "
        f"{d['compression_ratio_Sd_St']:.2f}): that is the direct-coupled throat, and the "
        "reason the LEM side needs no compression chamber.",
        "",
    ]
    return _recipe_part3(params, result, suggest, m, path, md, where, t, symmetry, sym_name,
                         sym_mesh)


def _recipe_part3(params: Params, result: Result, suggest: dict, m: mesh.SurfaceMesh,
                  path: Path, md: list, where: str, t, symmetry: str = None,
                  sym_name: str = None, sym_mesh: mesh.SurfaceMesh = None) -> Path:
    """Step 5: the lumped-element network (the part that is easy to wire wrongly)."""
    drv = params.driver
    throat_mm = params.horn.throat_diameter * 1e3
    md += [
        "## 5. The lumped-element network",
        "",
        "`bem.msh` supplies the acoustic load only; the driver, the rear chamber and the "
        "coupling live in the LEM part. This is `driver_le.txt` translated to the schematic:",
        "",
        "```",
        "   S1 --> s --+-----------+-- u --> Rad1 --> (BEM: Throat, Type = Driven)",
        "   GND --- t -|   Dyn1    |-",
        "              +-----------+-- v --> Encl   (Vb = 0.028 m3, closed stub)",
        "```",
        "",
        "### 5.1 The driver element (`Dyn1`)",
        "",
        f"Elec-Dyn Driver, `Inherit from` = the DefDriver object **{drv.name}**. The values "
        "are the same as in `bem/driver_le.txt`; note the GUI asks for **Kms** where the ABEC "
        "script has Cms (reciprocals, and the form calculates fs from them):",
        "",
        "| parameter | value | comment |",
        "| --- | --- | --- |",
        f"| Mms | {drv.Mms * 1e3:.1f} g | moving mass Mmd; the air loads come from the model |",
        f"| Kms | {1.0 / drv.Cms:.0f} N/m | suspension stiffness, = 1 / Cms "
        f"({drv.Cms:.3e} m/N) |",
        f"| Rms | {drv.Rms:.2f} Ns/m | mechanical resistance |",
        f"| fs | {drv.fs:.2f} Hz | appears by itself from Mms + Kms (measured 31.70 Hz) |",
        f"| Re | {drv.Re:.2f} ohm | voice-coil DC resistance |",
        f"| BL | {drv.Bl:.2f} N/A | force factor (GUI writes N/A, not T*m) |",
        f"| VC | Model **AkAbak**, Le {drv.Le * 1e3:.2f} mH, fre {drv.fre * 1e3:.0f} Hz, "
        f"Expo Re {drv.ExpoRe:.3f}, Expo Le {drv.ExpoLe:.3f} | `fre` is in **Hz** (the form "
        "shows SI prefixes, e.g. `1.1k` = 1100 Hz, a typical 2-20 kHz value); "
        "`Model = AkAbak` is the model those three numbers belong to |",
        "",
        "### 5.2 Which terminal is which",
        "",
        "The Elec-Dyn Driver is a four-pole: one stacked pair of terminals per edge. This is "
        "the part that is easiest to get wrong, so check it against the symbol:",
        "",
        "| terminal | where | domain | connect to |",
        "| --- | --- | --- | --- |",
        "| **s** | top of one edge | voice coil | the Source's driven pole |",
        "| **t** | bottom of that edge | voice coil return | GND |",
        "| **u** | top of the **other** edge | **diaphragm front** | **Rad1** -> BEM "
        "`Throat`; this is the driving node |",
        "| **v** | bottom of the same edge as u | **diaphragm rear** | **Encl** (the closed "
        "stub) |",
        "",
        "The manual (Elec-Dyn Driver): *the port to the left is of the electric domain ... the "
        "port on the right hand side is driving the acoustic domain ... connect to node u any "
        "acoustic component which shares the sound pressure at the front of the diaphragm; to "
        "node v acoustic components which have the same pressure at the rear.* So **front and "
        "rear are the same edge** (upper / lower) and the source plus ground sit on the "
        "opposite edge. Cross-check with the picture `CmpSchDynDriver` in the help, or open "
        "the example `/BEM/Loudspeakers/Speaker Cabinet Bass-Horn Bogart.akp` - a bass horn "
        "with a rear chamber, i.e. our topology. (LE components mark their polarity with a "
        "tiny dot: the source's driven pole on the dotted terminal keeps the absolute phase "
        "right - the magnitude does not care.)",
        "",
        "### 5.3 Diaphragm areas",
        "",
        f"Open `Diaph front`, page **Values**: Shape = **Circle**, `dDf` = "
        f"**{drv.dD * 1e3:.2f} mm** (hole / exclusion 0). Same for `Diaph rear` -> `dDr` = "
        f"{drv.dD * 1e3:.2f} mm. Both faces of the cone convert force to pressure with "
        "F = p*S, q = v*S, so both need their area.",
        "",
        "* `Diaph rear`: leave the Reference page at **- not referenced -**. Only the horn's "
        "inside is meshed, so there is no rear boundary to link to; the 28 L box is purely "
        "lumped. A reference here would claim that the back of the cone radiates into the "
        "horn.",
        "* `Diaph front`: either keep **Values** (as above) and let **Rad1** do the coupling - "
        "that is exactly what `driver_le.txt` does - **or** set Reference = `Elements (mesh "
        "file) - Throat` and then **delete Rad1**. Never both: two couplings on one driven "
        "boundary is a different, wrong speaker. (A reference takes the area from the mesh "
        f"too: the throat disk is {throat_mm:.0f} mm diameter = "
        f"{math.pi * (throat_mm * 1e-3 / 2.0) ** 2 * 1e4:.0f} cm2 by design, and that is why "
        "the two routes agree.)",
        "",
        "### 5.4 Rear chamber, coupling element, source",
        "",
        f"* **Encl** (Enclosure, closed): `Vb` = **0.028 m3** (= "
        f"{drv.rear_volume * 1e6:.0f} cm3). The schematic label is the quick check - a bare "
        "`28` would be 28 cubic metres.",
        "* **Rad1** (Radiator): *Application* = **BEM Boundaries**, *Ref to BEM* = the driven "
        "group **Throat**. This is the GUI form of `RadImp 'Throat' Node=100 DrvGroup=1001`; "
        "the help: *installs a radiation impedance of vibrating boundaries of the BEM-part. "
        "The model is fully coupled.* Its free pole goes to GND.",
        "* **S1** (Source): Domain Type = **Electric**, Source Type = **Potential**, Weight = "
        "**1** - the level belongs in one place only (step 6).",
        "* **GND**: one at the driver's `t`, one at the radiator's free pole.",
        "",
    ]
    return _recipe_part4(params, result, suggest, m, path, md, where, t, symmetry, sym_name,
                         sym_mesh)


def _recipe_part4(params: Params, result: Result, suggest: dict, m: mesh.SurfaceMesh,
                  path: Path, md: list, where: str, t, symmetry: str = None,
                  sym_name: str = None, sym_mesh: mesh.SurfaceMesh = None) -> Path:
    """Steps 6-10: driving level, solve, export, acceptance tests, hand-over."""
    v0 = params.simulation.voltage
    l0 = 20.0 * math.log10(v0 * math.sqrt(2.0))
    md += [
        "## 6. The driving level",
        "",
        "`Global -> Level of Driving...` (the form is titled *Global Driving Source*). It "
        "scales every LE Source of the project, so the level lives in exactly one place:",
        "",
        f"* Amplitude `V0` = **{v0:.3f}** - the Stage-1 model is documented at {v0:.2f} Vrms "
        f"= 1 W into 8 ohm ({math.sqrt(8.0):.6f} V is the exact 1 W value),",
        f"* **Is rms** checked. The form then shows *Internally following peak value is "
        f"applied: {v0 * math.sqrt(2.0):.3f}* and `L0` = **{l0:.4f} dB**: the two fields are "
        "the same setting in two units (L0 = 20 log10 of the internal peak), so filling one "
        "is enough.",
        "* With *Is rms* unchecked the same number is read as a peak, i.e. 3 dB quieter - the "
        "comparison expects rms, so keep it ticked.",
        "",
        "## 7. Solve and export",
        "",
        "The five buttons along the bottom of the desktop are the pipeline, in this order: "
        "**BEM-Meshing -> BEM-Solving -> LE-Solving -> Ob Fields -> Ob Spectra**.",
        "",
        f"1. **BEM-Meshing**: AKABAK refines the imported mesh ({len(m.tris)} triangles to "
        "start with).",
        "2. **BEM-Solving**: the Helmholtz solve with the throat driven.",
        "3. **LE-Solving**: the network is solved with the BEM impedance inside it. The "
        "terminal impedance is available now - check step 8.1 before spending time elsewhere.",
        "4. **Ob Fields / Ob Spectra**: the observations - on-axis SPL at 1 m, a 0-90 deg arc, "
        "and the input impedance.",
        "",
        "### Getting the numbers out",
        "",
        "**Route A - VACS over COM (this works in this Wine prefix).** Register once and "
        "AKABAK feeds VacsViewer live, updating the curves on every recalculation:",
        "",
        "```",
        "AKABAK/akabak.sh --vacs      # = wine VacsViewer.exe /RegServer",
        "```",
        "",
        "Until it is registered AKABAK reports *Cannot locate Vacs.exe or VacsViewer.exe ... "
        "COM service*; that dialog is harmless (the value was applied) but it repeats. The "
        "manual's remark that a COM-free route *becomes necessary if the underlying operating "
        "system does not support the COM-transfer technique, such as on LINUX* describes the "
        "fallback, not a hard limit.",
        "",
        "**Route B - without COM.** `Options -> Preferences... -> VACS -> Spectrum way of "
        "output` = **Files**, tick **Text format**, Folder = "
        f"`{path.parent.as_posix()}/export/` (Clipboard works too). `Processing -> Output "
        "Spectra` re-emits the datasets at any time, and VacsViewer picks them up with "
        "`IO -> Import Data`. This is the route the import step expects, so it is worth "
        "leaving switched on.",
        "",
        "## 8. What to look for (in this order)",
        "",
        "1. **Input impedance** - the level-independent check: two peaks, the horn-loaded one "
        "around **15-16 ohm near 58 Hz** (fs 31.8 Hz shows only a small peak, because the horn "
        "loads the front while the 28 L box stiffens the rear). **If the big peak is at "
        "~31.8 Hz, the cone is the wrong way round** - enclosure on `u`, horn on `v` "
        "(step 5.2).",
        "2. **On axis**: the same shape as `spl_onaxis.png`. A few dB low in the bottom octave "
        "is the baffle assumption (free standing vs half space); ripple above ~150 Hz is mouth "
        "diffraction, which the 1P model cannot see.",
        "3. **Level bookkeeping**: a *constant* **+3.01 dB** against Stage 1 is AKABAK's "
        "peak-value rendering (20 log10 sqrt(2)) - the one offset to accept as a convention. "
        "Any other constant offset points at the drive level or the baffle assumption; a "
        "resonance in one curve only points at diffraction or at the coupling.",
        "4. **Off axis**: new information - how wide the rectangle is horizontally and how the "
        "vertical coverage behaves; compare with `excursion_directivity.png`.",
        "",
        "## 9. Send it back",
        "",
        "```",
        f"python3 run_workflow.py {params.source_path} --stage 2 --bem-import <that folder>",
        "```",
        "",
        "That writes `bem/curves_stage2.csv`, `bem/compare.md`, `bem/compare.png` and adds a "
        "*Stage 1 vs Stage 2* section to the report. If the parser cannot read your export it "
        "prints the first lines it saw - send those and it will be adapted.",
        "",
        f"Worth including in the folder: {NOTES_FOR_US}.",
        "",
        "## 10. If something goes wrong",
        "",
        "* *Model comes out tiny or huge* -> the `.msh` is in metres; Scaling must be 1. Check "
        "the fingerprints of step 3 (bounding box about 2.4 x 1.8 x 1.5 m).",
        "* *Flat or empty curve* -> the driven group is not coupled to the network: `Throat` "
        "must be Type of Boundary = **Driven** *and* Rad1 must carry *Ref to BEM = Throat* (or "
        "the diaphragm reference instead - never both).",
        "* *LE network complains about domains* -> a wire crossed the domains; both acoustic "
        "parts belong on the acoustic edge of the driver (step 5.2).",
        "* *VACS error dialog* -> `AKABAK/akabak.sh --vacs`, or switch to Files/Clipboard "
        "(step 7).",
        "* *Out of memory* -> lower the mesh frequency (e.g. 300 Hz) or use symmetry "
        "(step 11).",
        "* *Wine trouble* -> the NoInstaller build behaves better than the installer; the same "
        "files work identically on Windows.",
        "",
    ]
    md += _recipe_symmetry(symmetry, sym_name, sym_mesh, m, suggest)
    md += [
        "## 12. Send it back (run this at the end)",
        "",
        "```",
        f"python3 run_workflow.py {params.source_path} --stage 2 "
        f"--bem-import {path.parent.as_posix()}/export",
        "```",
        "",
        "Or, for the gated pipeline state machine:",
        "",
        "```",
        f"python3 -m hornflow.cli {params.source_path} --bem-import "
        f"{path.parent.as_posix()}/export",
        "```",
        "",
        "The importer validates every ``.vips`` file (exists, non-empty, belongs to this "
        "run, valid frequency grid, required pressure spectrum, numeric finite values, "
        "newer than the generated inputs, manifest match) and then compares the on-axis "
        "curve with the Stage-1 model. Only a passing import plus comparison marks the "
        "candidate ``BEM_VALIDATED``.",
        "",
    ]
    path.write_text("\n".join(md), encoding="utf-8")
    return path


def _recipe_symmetry(symmetry: str, sym_name: str, sym_mesh: mesh.SurfaceMesh,
                     m: mesh.SurfaceMesh, suggest: dict) -> list:
    """Step 11: the optional half/quarter model - 4x to 64x faster solves."""
    if not symmetry or sym_mesh is None:
        return []
    sa, af = sym_mesh.area_by_group(), m.area_by_group()
    planes = {"x": "x = 0 (the yz-plane)", "y": "y = 0 (the xz-plane)",
              "xy": "x = 0 and y = 0"}[symmetry]
    mesh_freq = suggest["mesh_frequency_hz"]
    return [
        f"## 11. Optional - `Symmetry={symmetry}`: the same horn, {len(sym_mesh.tris)} "
        f"triangles instead of {len(m.tris)}",
        "",
        "The BEM now solves for the surface pressure on every element, and a mirrored point "
        "holds the same pressure as its twin - so half (or three quarters) of the unknowns are "
        "duplicates of each other. AKABAK removes them with symmetry-adapted Green-functions, "
        "and the size of the system matrix is what costs the time:",
        "",
        "> *\"The speed-advantage in calculation stems from the usage of special "
        "Green-functions. Not only integration is faster but also the size of the "
        "system-matrices to solve for are smaller. For one plane of symmetry this matrix is "
        "reduced to 1/4. For two planes it reduces to 1/8.\"* (help: `Global -> Dim, Sym and "
        "BEM`)",
        "",
        f"`{sym_name}` is a copy of the horn with everything outside {planes} cut away. "
        f"Nothing else about the model changes: same group names, same tags, same units, same "
        f"z origin (mouth at z = {sym_mesh.meta['length_mm'] / 1e3:.3f}), same element size "
        f"({suggest['element_size_mm']:.0f} mm, good to {mesh_freq:.0f} Hz). The areas read a "
        "quarter (or half) of the originals and AKABAK mirrors them back; the driven throat "
        "disk is *cut* by the planes, which is the supported case:",
        "",
        "> *\"If we cut vertically, the two diaphragms would be halved, however, AKABAK will "
        "take care of this situation and will provide the correct calculation.\"*",
        "",
        "| group | `bem.msh` | `%s` | ratio |" % sym_name,
        "| --- | --- | --- | --- |",
    ] + [
        f"| `{g}` | {af[g]:.3f} m2 | {sa[g]:.3f} m2 | {sa[g] / af[g]:.3f} |"
        for g in sorted(sa)
    ] + [
        "",
        "### The clicks (nothing is re-created)",
        "",
        "Every GUI object keeps working because the new file carries the same tags - the "
        "Mesh File object is the only thing that points at a file:",
        "",
        "1. `File -> Save As...` -> e.g. `_sym.akp`, so the full-mesh project stays intact as "
        "a fallback.",
        "2. Double-click the **Mesh File** object -> `File name` = `%s` -> press "
        "**`Re-Open`** (it *\"maintains the current stack of Tag-Filters\"*, so `Throat`, "
        "`Hornwall` and `Mouth` keep their selections)." % sym_name,
        "3. Check the tree: the three components are still listed, their areas are the "
        "fraction above, no \"empty selection\" warning.",
        f"4. `Global -> Dim, Sym and BEM` -> **Symmetry = `{symmetry}`** -> OK. (AKABAK asks "
        "for one of `x`, `y`, `xy`, `xz`, `yz` - a plane at z = 0 is *not* usable here: the "
        "horn stands on the floor, there is nothing below it to mirror.)",
        "5. `Global -> Meshing` -> clear `Edge Length` (leave the field empty; answer *Yes* to "
        "the prompt). A value in that field refines the imported mesh, and the refined count "
        "is what makes a solve take hours.",
        "6. `Processing -> Calculate All`. In `Log Calc`, `BEM Meshing -> Elements (total)` "
        f"must now read about {len(sym_mesh.tris)} (instead of {len(m.tris)}), and the "
        "solving time should drop to minutes.",
        "",
        "**Do not** touch `Diaph front` (259.43 mm): AKABAK corrects the halved driven surface "
        "internally, so the network keeps the full Sd.",
        "",
        "Two things to watch:",
        "",
        "* the on-axis microphone sits exactly *on* both planes of symmetry - if AKABAK "
        "objects, move it to x = 0.001 m (the field there is unchanged);",
        "* if `Log Calc` reports the interior subdomain as not closed, drop to "
        "`Symmetry = x` (a half model is still a 1/4-sized matrix) - or go back to "
        "`bem.msh` with `Symmetry = (no symmetry)`, which is the configuration already "
        "verified.",
        "",
        "Symmetry is exact for this horn - the mouth rectangle and the throat circle are both "
        "centred on the axis - but it stops being valid the moment the design becomes "
        "asymmetric (an off-axis driver, a side wall modelled on one side only).",
        "",
    ]


# ---------------------------------------------------------------------------
#  importing what AKABAK exported
# ---------------------------------------------------------------------------
import re   # noqa: E402  (used only by the import helpers below)


def _split(line: str) -> list:
    for sep in (",", ";", "\t"):
        if sep in line:
            return [t.strip() for t in line.split(sep) if t.strip() != ""]
    return line.split()


def _num(token: str):
    try:
        return float(token.replace(",", "."))
    except ValueError:
        return None


def parse_export(text: str) -> dict:
    """Parse a text export into {'freq': ndarray, 'curves': {label: ndarray}}.

    Deliberately tolerant: AKABAK/VACS text exports vary (column order, separators,
    header lines, comment prefixes). The first mostly-numeric table wins; a header
    line supplies the labels when there is one.
    """
    keep = [ln for ln in text.splitlines() if ln.strip()
            and not ln.lstrip().startswith(("!", "#", "*", "//", "%"))]
    if not keep:
        raise ValueError("the file looks empty")
    # the first line that holds a table, and the line just above it (if any) as header
    first_num = None
    for i, ln in enumerate(keep[:12]):
        vals = [_num(t) for t in _split(ln)]
        if sum(1 for v in vals if v is not None) >= 2:
            first_num = i
            break
    labels, start = None, 0
    if first_num is not None and first_num > 0:
        cand = _split(keep[first_num - 1])
        if len(cand) >= 2:
            labels, start = cand, first_num
    rows = []
    for ln in keep[start:]:
        vals = [_num(t) for t in _split(ln)]
        if sum(1 for v in vals if v is not None) >= 2:
            rows.append(vals)
    if not rows:
        raise ValueError("no numeric table found; first lines were:\n" + "\n".join(keep[:3]))
    width = max(len(r) for r in rows)
    freq_idx = 0
    if labels:
        for i, lab in enumerate(labels):
            if re.search(r"(freq|hz)", lab, re.I):
                freq_idx = i
                break
    freq = np.array([r[freq_idx] for r in rows if r[freq_idx] is not None], dtype=float)
    order = np.argsort(freq)
    freq = freq[order]
    curves: dict = {}
    for j in range(width):
        if j == freq_idx:
            continue
        vals = np.array([r[j] if j < len(r) and r[j] is not None else np.nan for r in rows],
                        dtype=float)[order]
        if np.all(np.isnan(vals)):
            continue
        name = labels[j] if labels and j < len(labels) else f"column {j}"
        curves[name] = vals
    if not curves:
        raise ValueError("found a frequency column but no data columns")
    return {"freq": freq, "curves": curves}

# --------------------------------------------------------------------------- #
#  AKABAK/VACS .vips - the real export format of AKABAK Free 3.3.2 b144
# --------------------------------------------------------------------------- #
# Verified against results/jbl_1200b/bem/export/*.vips and the documented
# 60 Hz checkpoint (Rad1_23Sept26 Mic1 -> 87.73 dB rms-referenced).
VIPS_MARKER = "SourceDesc=VACS_Data_Text"
P_REF = 20.0e-6                      # [Pa] reference (rms convention)
PEAK_TO_RMS_DB = 20.0 * math.log10(math.sqrt(2.0))   # 3.0103 dB

# every text extension we can read back (AKABAK writes .vips)
IMPORT_EXTS = (".vips", ".txt", ".csv", ".dat", ".tsv", ".asc")


def peak_pa_to_spl_db(magnitude):
    """Peak complex pressure [Pa] -> rms-referenced dB SPL (Stage-1 convention).

    AKABAK stores the complex amplitude (peak) and displays peak-referenced dB,
    which is exactly PEAK_TO_RMS_DB (3.01 dB) above the rms-referenced dB SPL the
    1-D model uses.
    """
    return 20.0 * np.log10(np.maximum(np.asarray(magnitude, dtype=float), 1e-30) / P_REF) \
        - PEAK_TO_RMS_DB


def _clean_lines(text: str) -> list:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _vips_split(line: str) -> list:
    for sep in (",", ";", "\t"):
        if sep in line:
            return [t.strip() for t in line.split(sep) if t.strip() != ""]
    return line.split()


def parse_vips(text: str) -> dict:
    """Parse an AKABAK/VACS ``.vips`` spectrum file.

    Returns the same shape as :func:`parse_export` (``freq`` + ``curves``) plus the
    file metadata.  Pressure columns (``Data_BaseUnit=Pa``) are converted to
    rms-referenced dB SPL; every other unit stays a raw magnitude.  The raw
    magnitudes remain available under ``magnitude`` for validation.
    """
    meta: dict = {}
    rows: list = []
    in_data = False
    for raw in _clean_lines(text):
        s = raw.strip().lstrip("\ufeff")
        if not in_data:
            if s == "Data":
                in_data = True
            elif s and not s.startswith("//") and "=" in s:
                k, v = s.split("=", 1)
                meta[k.strip()] = v.strip().strip('"')
        else:
            if s == "Data_End":
                break
            if s:
                rows.append(s)
    if not rows:
        raise ValueError("vips file has no Data block")

    table = []
    for ln in rows:
        vals = [_num(t) for t in _vips_split(ln)]
        if len(vals) >= 2 and all(v is not None for v in vals):
            table.append(vals)
    if not table:
        raise ValueError("vips Data block holds no numeric rows")
    width = min(len(r) for r in table)
    arr = np.array([r[:width] for r in table], dtype=float)

    freq = arr[:, 0]
    order = np.argsort(freq)
    freq, data = freq[order], arr[order]

    is_complex = "complex" in str(meta.get("Data_Format", "Complex")).lower()
    step = 2 if is_complex else 1
    n_curves = max(0, (width - 1) // step)
    angles = [a.strip() for a in str(meta.get("Param_Coord_x2", "")).split(",")
              if a.strip()] if str(meta.get("Param_Coord_Type", "")).lower() == "spherical" \
        and meta.get("Param_Coord_x2") else []
    legend = str(meta.get("Data_Legend", "")).split(";")[0].strip()
    legend = re.sub(r"\s*\([^)]*\)\s*$", "", legend).strip() or "curve"
    base_unit = str(meta.get("Data_BaseUnit", ""))
    is_pressure = base_unit == "Pa"

    curves: dict = {}
    magnitude: dict = {}
    for c in range(n_curves):
        col = 1 + c * step
        if is_complex:
            mag = np.hypot(data[:, col], data[:, col + 1])
        else:
            mag = np.abs(data[:, col])
        if angles and len(angles) == n_curves:
            label = f"{legend} {angles[c]} deg"
        elif n_curves == 1:
            label = legend
        else:
            label = f"{legend} {c + 1}"
        magnitude[label] = mag
        curves[label] = peak_pa_to_spl_db(mag) if is_pressure else mag

    return {"freq": freq, "curves": curves, "magnitude": magnitude, "meta": meta,
            "kind": "vips", "is_pressure": is_pressure, "base_unit": base_unit,
            "n_curves": n_curves}


def parse_any(text: str, name: str = "") -> dict:
    """Dispatch to the ``.vips`` parser or the tolerant text parser."""
    if VIPS_MARKER in text or "Data_LevelType=" in text or "Data_BaseUnit=" in text:
        return parse_vips(text)
    return parse_export(text)


def _looks_like_spl(parsed: dict) -> bool:
    if parsed.get("is_pressure"):
        return True
    return any(re.search(r"(spl|sound|pressure|db|mic)", str(k), re.I)
               for k in parsed.get("curves", {}))


def _has_point_mic(parsed: dict) -> bool:
    """A point (1 m) microphone observation - the right thing to compare on-axis."""
    return any(re.search(r"mic", str(k), re.I) for k in parsed.get("curves", {}))


def candidate_files(folder) -> list:
    """Every importable file under ``folder`` (recursive), deterministically sorted."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*")
                  if p.is_file() and p.suffix.lower() in IMPORT_EXTS)


def choose_best(items: list, mtimes: dict | None = None) -> tuple:
    """Rank parsed exports: pressure/SPL, then a point mic, then richness, then newest."""
    mtimes = mtimes or {}
    best = best_name = None
    for name, parsed in items:
        key = (1 if _looks_like_spl(parsed) else 0,
               1 if _has_point_mic(parsed) else 0,
               len(parsed["freq"]) * max(1, len(parsed["curves"])),
               float(mtimes.get(name, 0.0)))
        if best is None or key > best[0]:
            best, best_name = (key, parsed), name
    return (best[1] if best else None), best_name


def folder_mtimes(folder) -> dict:
    """``{filename: mtime}`` for every importable file (newest-wins tie-break)."""
    return {p.name: p.stat().st_mtime for p in candidate_files(folder)}


def parse_folder(folder) -> tuple:
    """Parse every importable file in ``folder``.

    Returns ``(parsed_by_name, errors)``; a parse failure is recorded rather than
    raised, so a partly-bad folder can still be validated field by field.
    """
    parsed, errors = {}, []
    for p in candidate_files(folder):
        try:
            parsed[p.name] = parse_any(p.read_text(errors="replace"), p.name)
        except Exception as exc:                     # noqa: BLE001 - reported, not raised
            errors.append(f"{p.name}: {exc}")
    return parsed, errors


def import_exports(params: Params, result: Result, folder, out_dir) -> dict:
    """Read every importable file in `folder`, keep the best table, compare with Stage 1."""
    folder = Path(folder)
    parsed, errors = parse_folder(folder)
    if not parsed:
        if not candidate_files(folder):
            raise FileNotFoundError(
                f"no importable files ({', '.join(IMPORT_EXTS)}) found in {folder}")
        raise ValueError("could not parse any export in that folder:\n  " + "\n  ".join(errors))
    best, best_name = choose_best(list(parsed.items()), folder_mtimes(folder))
    return _write_comparison(params, result, best, best_name, Path(out_dir))


def _write_comparison(params: Params, result: Result, best: dict, best_name: str,
                      out: Path) -> dict:
    """Write curves_stage2.csv + compare.png + compare.md for a parsed export."""
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "curves_stage2.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz"] + list(best["curves"]))
        for i, f0 in enumerate(best["freq"]):
            w.writerow([f"{f0:.4f}"] + [f"{best['curves'][k][i]:.6g}" for k in best["curves"]])

    png_path = compare_figure(params, result, best, out / "compare.png")
    md_path = out / "compare.md"
    md_path.write_text(compare_md(params, result, best, best_name), encoding="utf-8")
    return {"source": best_name, "parsed": best,
            "files": {"curves": csv_path, "report": md_path, "figure": png_path}}


def _onaxis_curve(best: dict) -> str:
    """Pick the curve that looks like 0 degrees, else the first one."""
    pattern = re.compile(r"(^|[^0-9])0(\.0+)?\s*[-_ ]?\s*(deg|°|$)", re.I)
    for name in best["curves"]:
        if pattern.search(str(name)):
            return name
    return next(iter(best["curves"]))


def compare_figure(params: Params, result: Result, best: dict, path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f = best["freq"]
    fig, ax = plt.subplots(figsize=(9.5, 5.0), dpi=130)
    ax.semilogx(result.f, result.spl, color="tab:blue", linewidth=1.6,
                label="Stage 1 model (1P horn + LE driver)")
    cmap = plt.get_cmap("plasma")
    names = list(best["curves"])
    for i, name in enumerate(names):
        ax.semilogx(f, best["curves"][name], linewidth=1.1, linestyle="--",
                    color=cmap(i / max(len(names) - 1, 1)), label=f"BEM {name}")
    ax.axvspan(params.target.f_low, params.target.f_high, color="tab:green", alpha=0.07,
               label=f"band {params.target.f_low:.0f}-{params.target.f_high:.0f} Hz")
    ax.axvline(result.design.fc, color="tab:red", linestyle=":", linewidth=0.9,
               label=f"cut-off {result.design.fc:.0f} Hz")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("SPL [dB]")
    ax.set_title("Stage 1 (1P) vs Stage 2 (BEM)", fontsize=10)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def compare_md(params: Params, result: Result, best: dict, source: str) -> str:
    ref = _onaxis_curve(best)
    f, y = best["freq"], best["curves"][ref]
    targets = [params.target.f_low, 70.0, 80.0, 100.0, 125.0, 150.0, params.target.f_high]
    md = [f"# Stage 1 (1P model) vs Stage 2 (BEM) - {params.project}",
          "",
          f"BEM data from `{source}`; curve **{ref}** compared with the Stage-1 on-axis "
          "prediction.",
          "",
          "| frequency | Stage 1 | BEM | difference |",
          "| --- | --- | --- | --- |"]
    diffs = []
    for ft in targets:
        i = int(np.argmin(abs(f - ft)))
        j = int(np.argmin(abs(result.f - ft)))
        diffs.append(y[i] - result.spl[j])
        md.append(f"| {f[i]:.0f} Hz | {result.spl[j]:.1f} dB | {y[i]:.1f} dB | "
                  f"{y[i] - result.spl[j]:+.1f} dB |")
    md += ["",
           f"mean difference over those points: **{float(np.mean(diffs)):+.1f} dB**, worst "
           f"{float(np.max(np.abs(diffs))):.1f} dB",
           "",
           "How to read it: the 1P model assumes plane wave-fronts, a baffled piston mouth and "
           "no diffraction, so a few dB at the band edges and ripple above ~150 Hz are "
           "expected. A systematic offset across the whole band points at the baffle "
           "assumption or the drive level; a resonance in one curve only points at diffraction "
           "or at the mesh/coupling in AKABAK. AKABAK renders amplitudes as peak values, so a "
           "constant **+3.01 dB** (20 log10 sqrt(2)) is the one offset that is a convention "
           "rather than a difference - subtract it before reading anything else.",
           ""]
    return "\n".join(md)