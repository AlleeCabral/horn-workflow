"""Refresh the UI shell of an already-finished run (`--emit-ui`).

The pipeline writes the view model and the shell in `_finalize()`.  This module
does the same thing on demand for a run that already exists - useful after a
`--bem-import`, which changes the authoritative state without re-running the
pipeline.  It never touches `state.json`; it only re-renders the two artifacts
that are pure projections of it.
"""

from __future__ import annotations

from pathlib import Path

from ..io.state_store import load_state_file
from ..viz import export as viz_export
from . import view as view_mod


def emit_ui_for_run(run_dir, *, now=None, host: str = "static") -> dict:
    """Re-emit `deliverables/viewer/{viewer.html,app_view.json}` for one run."""
    run_dir = Path(run_dir)
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"no state.json under {run_dir}")
    state = load_state_file(state_path)

    view = view_mod.build_view(state, run_dir=run_dir, now=now, host=host)
    vdir = run_dir / "deliverables" / "viewer"
    glb = vdir / "scene.glb"
    if not glb.is_file():
        raise FileNotFoundError(
            f"no scene.glb under {vdir}; run the pipeline once to build the geometry")

    title = view["viewer"]["title"] or state.project.get("name", "")
    files = viz_export.write_viewer(None, vdir, title=title, app_view=view,
                                    glb_source=glb)
    files["app_view"] = view_mod.emit_view(view, vdir / "app_view.json")
    return {"run_dir": str(run_dir), "view": view, "files": files}
