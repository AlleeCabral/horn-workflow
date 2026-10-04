"""Geometry exporters.

Reliable formats are implemented directly (STL via the validated writer, DXF via
the validated writer, GLB for the browser viewer).  Ambitious formats that need
a CAD/CAM library are *stubs*: they write a clearly-named deferred note instead
of a dubious hand-rolled file.
"""

from __future__ import annotations

from pathlib import Path

from .. import build as _build


def write_stl(mesh, path, name: str = "horn") -> Path:
    return _build.write_stl(mesh, path, name)


def write_dxf(polylines, path, layer: str = "horn") -> Path:
    return _build.write_dxf(polylines, path, layer)


def export_glb(mesh, path, **kw) -> Path:
    from ..viz.gltf import write_glb
    return write_glb(mesh, path, **kw)


def deferred_stub(kind: str, out_dir, reason: str) -> Path:
    """Record that a format was deliberately deferred, with the reason."""
    out = Path(out_dir) / f"{kind}.DEFERRED.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"{kind} export DEFERRED\n"
        f"reason: {reason}\n"
        f"implement when the active milestone needs it and the dependency is approved\n",
        encoding="utf-8")
    return out


# formats we deliberately defer, and why
DEFERRED = {
    "step": "editable B-rep needs a CAD kernel (CadQuery/OCCT); a faceted "
            "hand-rolled STEP would not be editable truth",
    "3mf": "preferred print package; needs a tested 3MF writer (deferred to the "
           "manufacturing milestone)",
    "vtu": "scientific field VTK; deferred until field data exists (3-D stage)",
}
