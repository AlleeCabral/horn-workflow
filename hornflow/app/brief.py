"""The brief: the user's answers, validated, then frozen into a definition file.

Two artifacts, both inside the project root:

* ``.hornflow/brief.draft.yaml`` - the editable draft (what the user typed);
* ``.hornflow/brief.yaml`` - the frozen record (revision, input hash, timestamp);
* ``.hornflow/generated/<slug>.yaml`` - the definition file the pipeline loads.

The frozen definition is **verified by loading it** with the real
``config.load()`` before it is accepted, so a frozen brief can never produce a
definition the pipeline would reject.  Nothing here writes ``state.json``: the
brief is an input, and only the pipeline writes run state.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .. import config
from ..io.artifacts import atomic_write

BRIEF_DIR = ".hornflow"
DRAFT_NAME = "brief.draft.yaml"
FROZEN_NAME = "brief.yaml"
GENERATED_DIR = "generated"


# --------------------------------------------------------------------------- #
#  the field rules - one table, used by save-draft and by freeze
# --------------------------------------------------------------------------- #
# kind: "number" (with an inclusive range) or "enum" (closed list) or "text"
FIELD_RULES: dict = {
    "deployment": ("text", None),
    "boundary": ("enum", ("free", "wall", "corner")),
    "operating_orientation": ("enum", ("upright", "on_side", "inverted")),
    "transport_orientation": ("enum", ("upright", "on_side", "any")),
    "manufacturer": ("text", None),
    "model": ("text", None),
    "data_source": ("enum", ("measured", "datasheet", "estimated")),
    "ts_set": ("text", None),
    "Xmax": ("number", (0.01, 200.0)),
    "xmax_convention": ("enum", ("one-way", "peak-to-peak", "one_way_peak",
                                 "peak_to_peak")),
    "thermal_power_w": ("number", (1.0, 100000.0)),
    "min_safe_impedance_ohm": ("number", (0.1, 100.0)),
    "f_min_hz": ("number", (5.0, 1000.0)),
    "f_max_hz": ("number", (5.0, 2000.0)),
    "spl_continuous_db": ("number", (60.0, 160.0)),
    "measurement_distance_m": ("number", (0.25, 100.0)),
    "max_width_mm": ("number", (50.0, 10000.0)),
    "max_height_mm": ("number", (50.0, 10000.0)),
    "max_depth_mm": ("number", (50.0, 10000.0)),
    "max_external_volume_m3": ("number", (0.001, 100.0)),
    "max_mass_kg": ("number", (0.1, 2000.0)),
    "method": ("enum", ("print", "plywood", "either")),
}


@dataclass
class BriefValidation:
    ok: bool
    errors: dict          # field key -> message
    warnings: list

    def to_dict(self) -> dict:
        return {"ok": self.ok, "field_errors": self.errors,
                "warnings": list(self.warnings)}


def slugify(text: str, fallback: str = "brief") -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
    return s[:60] or fallback


def validate_values(values: dict) -> BriefValidation:
    """Per-field type/range/enum checks plus the two cross-field rules."""
    errors: dict = {}
    warnings: list = []
    for key, value in (values or {}).items():
        if key not in FIELD_RULES:
            errors[key] = "unknown field"
            continue
        if value is None or value == "":
            continue                     # absence is the model's business, not ours
        kind, spec = FIELD_RULES[key]
        if kind == "number":
            try:
                num = float(value)
            except (TypeError, ValueError):
                errors[key] = "must be a number"
                continue
            if not math.isfinite(num):
                errors[key] = "must be a finite number"
                continue
            lo, hi = spec
            if not (lo <= num <= hi):
                errors[key] = f"must be between {lo:g} and {hi:g}"
        elif kind == "enum":
            if str(value) not in spec:
                errors[key] = "must be one of: " + " / ".join(spec)
        elif kind == "text":
            if not isinstance(value, (str, int, float)) or str(value).strip() == "":
                errors[key] = "must be text"

    f_lo, f_hi = values.get("f_min_hz"), values.get("f_max_hz")
    if f_lo not in (None, "") and f_hi not in (None, ""):
        try:
            if float(f_lo) >= float(f_hi):
                errors["f_max_hz"] = "must be above the lowest required frequency"
        except (TypeError, ValueError):
            pass
    xc = values.get("xmax_convention")
    if xc in ("peak-to-peak", "peak_to_peak"):
        warnings.append("Xmax declared peak-to-peak: the limit is halved to compare "
                        "with one-way peak travel.")
    return BriefValidation(ok=not errors, errors=errors, warnings=warnings)


# --------------------------------------------------------------------------- #
#  the store
# --------------------------------------------------------------------------- #
class BriefStore:
    """Load / save / freeze the brief, constrained to one project root."""

    def __init__(self, project_root, base_definition=None, definitions_dir=None):
        self.root = Path(project_root).resolve()
        self.dir = self.root / BRIEF_DIR
        self.generated = self.dir / GENERATED_DIR
        self.definitions_dir = Path(definitions_dir) if definitions_dir else \
            self.root / "params"
        if base_definition is not None:
            self.base_definition = Path(base_definition).resolve()
        else:
            cands = sorted(self.definitions_dir.glob("*.yaml"))
            cands = [c for c in cands if c.name != DRAFT_NAME]
            if not cands:
                raise FileNotFoundError(
                    f"no definition file (*.yaml) under {self.definitions_dir}")
            self.base_definition = cands[0].resolve()

    # ------------------------------------------------------------------ io
    def _read_yaml(self, path: Path) -> dict:
        if not path.is_file():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    def _write_yaml(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=88)
        atomic_write(path, text.encode("utf-8"))

    def draft(self) -> dict:
        """``{"values", "revision", "input_hash", "frozen_utc", "definition"}``

        The values are the **draft overlaid on the frozen record**, so the current
        brief is always the latest known set whether the user has typed anything
        since freezing or not.
        """
        raw = self._read_yaml(self.dir / DRAFT_NAME)
        frozen = self._read_yaml(self.dir / FROZEN_NAME)
        values = dict(frozen.get("values") or {})
        values.update(raw.get("values") or {})
        return {"values": values,
                "revision": frozen.get("revision"),
                "input_hash": frozen.get("input_hash"),
                "frozen_utc": frozen.get("frozen_utc"),
                "definition": frozen.get("definition")}

    def save_draft(self, values: dict) -> dict:
        values = {k: v for k, v in (values or {}).items() if v not in (None, "")}
        check = validate_values(values)
        if not check.ok:
            return {"ok": False, "field_errors": check.errors,
                    "warnings": check.warnings}
        current = self.draft()["values"]
        current.update(values)
        self._write_yaml(self.dir / DRAFT_NAME,
                         {"schema": "hornflow-brief-draft/1", "values": current})
        return {"ok": True, "field_errors": {}, "warnings": check.warnings,
                "values": current}

    # -------------------------------------------------------------- helpers
    def available_drivers(self) -> list:
        base = self.definitions_dir / "drivers"
        return sorted(p.name for p in base.glob("*.yaml")) if base.is_dir() else []

    def resolve_driver(self, model, manufacturer=None):
        """Find a driver file from the brief's model/manufacturer text.

        Matching is deliberately forgiving (normalised substring either way) but
        never invented: no match returns ``None`` and the base definition's driver
        is kept, with a warning.
        """
        def norm(s):
            return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

        want = norm(model)
        if not want:
            return None
        base = self.definitions_dir / "drivers"
        if not base.is_dir():
            return None
        for path in sorted(base.glob("*.yaml")):
            raw = self._read_yaml(path)
            name = raw.get("name")
            hay = norm(f"{path.stem} {name or ''} {manufacturer or ''}")
            if want in hay or norm(name) and norm(name) in want:
                return path.resolve()
        # last resort: does the normalised model appear in a filename?
        for path in sorted(base.glob("*.yaml")):
            if want in norm(path.stem) or norm(path.stem) in want:
                return path.resolve()
        return None

    def definitions(self) -> list:
        """The allow-list of definitions a run may use (names only, never paths)."""
        out = []
        for p in sorted(self.definitions_dir.glob("*.yaml")):
            if p.name == DRAFT_NAME:
                continue
            out.append({"name": p.name, "path": str(p.relative_to(self.root))})
        for p in sorted(self.generated.glob("*.yaml")):
            out.append({"name": p.name,
                        "path": str(p.relative_to(self.root)), "generated": True})
        return out

    # ----------------------------------------------------------------- freeze
    def limits(self, values: dict) -> dict:
        """The pipeline limits implied by the brief (only what maps cleanly)."""
        out = {}
        z = values.get("min_safe_impedance_ohm")
        if z not in (None, ""):
            out["min_safe_impedance_ohm"] = float(z)
        vol = values.get("max_external_volume_m3")
        if vol in (None, ""):
            w, h, d = (values.get("max_width_mm"), values.get("max_height_mm"),
                       values.get("max_depth_mm"))
            if None not in (w, h, d) and "" not in (w, h, d):
                vol = float(w) * float(h) * float(d) / 1e9      # mm^3 -> m^3
        if vol not in (None, ""):
            out["max_external_volume_m3"] = float(vol)
        return out

    def _driver_block(self, raw: dict, values: dict, warnings: list, applied: dict):
        d = raw.get("driver")
        if isinstance(d, dict):
            file_ref = d.get("file")
            overrides = {k: v for k, v in d.items() if k != "file"}
        else:
            file_ref, overrides = d, {}
        target = None
        if values.get("model"):
            target = self.resolve_driver(values["model"], values.get("manufacturer"))
            if target is None:
                warnings.append(
                    f"no driver file matched model {values['model']!r}; the base "
                    "definition's driver is kept")
        if target is None and file_ref:
            ref = Path(str(file_ref))
            cand = ref if ref.is_absolute() else self.base_definition.parent / ref
            if not cand.is_file():
                cand = self.base_definition.parent / "drivers" / ref.name
            target = cand.resolve() if cand.is_file() else None
        if target is None:
            warnings.append("driver file could not be resolved from the brief or "
                            "the base definition")
            return
        if values.get("Xmax") not in (None, ""):
            overrides["Xmax"] = float(values["Xmax"])
            applied["driver.Xmax"] = overrides["Xmax"]
        if values.get("xmax_convention"):
            overrides["Xmax_convention"] = str(values["xmax_convention"])
            applied["driver.Xmax_convention"] = overrides["Xmax_convention"]
        raw["driver"] = {"file": str(target), **overrides}
        applied["driver.file"] = str(target)
        if values.get("thermal_power_w") not in (None, ""):
            warnings.append(
                "thermal_power_w is recorded in the brief, but the driver model has "
                "no thermal field yet, so the thermal limit stays estimate-only")

    def freeze(self, values: dict, *, author=None, now=None) -> dict:
        """Validate, write the definition, prove it loads, then record the revision."""
        import copy
        import hashlib

        from ..domain.ids import canonical_json

        check = validate_values(values)
        if not check.ok:
            return {"ok": False, "field_errors": check.errors,
                    "warnings": check.warnings}
        warnings = list(check.warnings)
        prev = self._read_yaml(self.dir / FROZEN_NAME)
        revision = int(prev.get("revision") or 0) + 1
        stamp = now or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        digest = hashlib.sha256(
            canonical_json({k: v for k, v in sorted(values.items())})
            .encode("utf-8")).hexdigest()

        raw = copy.deepcopy(self._read_yaml(self.base_definition))
        applied: dict = {}

        def setp(path, value):
            keys = path.split(".")
            cur = raw
            for k in keys[:-1]:
                cur = cur.setdefault(k, {})
            cur[keys[-1]] = value
            applied[path] = value

        for section in ("target", "horn", "simulation"):
            raw.setdefault(section, {})
        if values.get("f_min_hz") not in (None, ""):
            setp("target.f_low", float(values["f_min_hz"]))
        if values.get("f_max_hz") not in (None, ""):
            setp("target.f_high", float(values["f_max_hz"]))
        if values.get("measurement_distance_m") not in (None, ""):
            setp("simulation.observation_distance",
                 float(values["measurement_distance_m"]))
        if values.get("max_depth_mm") not in (None, ""):
            setp("horn.length", float(values["max_depth_mm"]))
        b = values.get("boundary")
        if b:
            # 'free' radiates into 4*pi; a wall or a corner bounds the mouth to a
            # half space.  This is the same 2*pi/4*pi question the BEM comparison
            # is about, so the mapping is recorded rather than assumed.
            setp("simulation.half_space", b in ("wall", "corner"))
            applied["simulation.half_space.from_boundary"] = b
        self._driver_block(raw, values, warnings, applied)

        slug = slugify(values.get("deployment") or values.get("model")
                       or (raw.get("meta") or {}).get("project") or "brief")
        raw.setdefault("meta", {})
        raw["meta"]["project"] = raw["meta"].get("project") or slug
        raw["meta"]["notes"] = (
            f"Generated from the HornFlow brief rev {revision} on {stamp}. "
            "Do not edit by hand - edit the brief and freeze again.")
        raw.setdefault("output", {})
        raw["output"]["dir"] = raw["output"].get("dir") or f"results/{slug}"
        raw["brief"] = {
            "schema": "hornflow-brief/1", "revision": revision,
            "input_hash": digest, "frozen_utc": stamp, "author": author,
            "source": str(self.base_definition.relative_to(self.root)),
            "values": {k: v for k, v in sorted(values.items())},
            "applied": applied, "warnings": warnings,
            "limits": self.limits(values),
        }

        # Write, then PROVE the pipeline can load it, then keep it.
        self.generated.mkdir(parents=True, exist_ok=True)
        staging = self.generated / f".{slug}.staging.yaml"
        self._write_yaml(staging, raw)
        try:
            config.load(staging)
        except Exception as exc:               # noqa: BLE001 - reported, not raised
            staging.unlink(missing_ok=True)
            return {"ok": False, "warnings": warnings, "field_errors": {
                "_definition": f"the definition would not load: {exc}"}}
        target = self.generated / f"{slug}.yaml"
        staging.replace(target)
        rel = str(target.relative_to(self.root))
        self._write_yaml(self.dir / FROZEN_NAME, {
            "schema": "hornflow-brief-frozen/1", "revision": revision,
            "input_hash": digest, "frozen_utc": stamp, "author": author,
            "definition": rel, "values": {k: v for k, v in sorted(values.items())},
            "applied": applied, "warnings": warnings, "limits": self.limits(values)})
        return {"ok": True, "revision": revision, "input_hash": digest,
                "frozen_utc": stamp, "definition": rel, "applied": applied,
                "warnings": warnings, "limits": self.limits(values),
                "field_errors": {}}



