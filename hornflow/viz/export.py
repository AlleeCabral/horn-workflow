"""Visualization export: GLB scene + a self-contained offline Three.js viewer."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

from ..manufacturing import meshbuild
from . import gltf

_VIEWER_DIR = Path(__file__).resolve().parent / "viewer"


def build_scene_parts(candidate) -> list:
    """Parts for one folded candidate: duct, centreline, stations, throat, mouth."""
    parts = []
    cavity = meshbuild.cavity_mesh(candidate, k=4)
    parts.append(gltf.part_mesh(cavity, color=(0.72, 0.76, 0.84, 1.0), name="duct"))
    parts.append(gltf.part_polyline(candidate.centreline.points,
                                    color=(1.0, 0.35, 0.10, 1.0), name="centreline"))
    stations = candidate.centreline.resample(11).points
    parts.append(gltf.part_points(stations, color=(0.15, 0.7, 1.0, 1.0), name="area_stations"))
    parts.append(gltf.part_points([candidate.centreline.points[0]],
                                  color=(0.2, 1.0, 0.35, 1.0), name="throat"))
    parts.append(gltf.part_points([candidate.centreline.points[-1]],
                                  color=(1.0, 0.25, 0.25, 1.0), name="mouth"))
    return parts


def export_glb(candidate, path) -> Path:
    return gltf.write_glb(build_scene_parts(candidate), path)


def write_viewer(candidate, out_dir, title: str = "folded horn", app_view=None,
                 annotations=None, glb_source=None) -> dict:
    """Write scene.glb, the self-contained viewer shell and the vendored assets.

    ``app_view`` (the HornFlow-emitted view model) and ``annotations`` (the
    dimension figures) are optional and feature-detected: when ``app_view`` is
    absent or empty the page renders **only** the Viewer tab and behaves exactly
    like the original viewer.

    ``glb_source`` reuses an existing ``scene.glb`` instead of building one from
    ``candidate`` - that is what lets ``--emit-ui`` refresh the shell of an
    already-finished run without re-deriving the fold.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    glb_path = out / "scene.glb"
    if glb_source is not None and Path(glb_source).is_file():
        if Path(glb_source).resolve() != glb_path.resolve():
            shutil.copyfile(glb_source, glb_path)
    else:
        parts = build_scene_parts(candidate)
        glb_path = gltf.write_glb(parts, glb_path)

    b64 = base64.b64encode(glb_path.read_bytes()).decode("ascii")
    tpl = (_VIEWER_DIR / "index.html").read_text(encoding="utf-8")
    html = (tpl.replace("__GLB_B64__", b64)
               .replace("__TITLE__", title)
               .replace("__APP_VIEW__", _embedded_json(app_view, annotations)))
    viewer = out / "viewer.html"
    viewer.write_text(html, encoding="utf-8")

    for name in ("vendor", "ui"):
        dest = out / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(_VIEWER_DIR / name, dest)
    return {"glb": glb_path, "viewer": viewer, "vendor": out / "vendor",
            "ui": out / "ui"}


def _embedded_json(app_view, annotations) -> str:
    """Serialise the embedded view model; merge the annotations into it.

    A ``</`` sequence would close the surrounding ``<script>`` element, so it is
    escaped.  An empty string means "no app view" - the shell then hides every
    tab except Viewer.
    """
    if not app_view:
        return ""
    payload = dict(app_view)
    if annotations is None:
        annotations = payload.get("annotations")
    if annotations is not None:
        payload["annotations"] = annotations
    text = json.dumps(payload, sort_keys=True)
    return text.replace("</", "<\\/")

