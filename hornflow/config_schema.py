"""Strict validation of a definition file, before anything runs (audit P12, U7).

Why this module exists
----------------------
The definition file is user input, and it used to be trusted.  A typo such as
``lenght:`` was ignored, a throat diameter given in metres produced a confident
answer with exit status 0, a quoted ``"false"`` meant True, and NaN passed
straight into the physics.  Validation is a pure function of the parsed
mapping, so the CLI can run it before a run directory exists and before any
simulation is paid for.

What is checked here
--------------------
* unknown sections and keys, with a ``difflib`` suggestion;
* numbers that are not finite, and values that must be positive or non-negative;
* unit slips, from :data:`RANGE_HINTS`;
* booleans written as strings (``"false"`` is not ``False``).

What is not checked here
------------------------
Rules that need two fields at once (``f_high > f_low``) and the closed enums
stay in the dataclasses in :mod:`hornflow.config`.  They raise ``ValueError``
with the same wording the CLI prints, so each rule has one implementation.
"""

from __future__ import annotations

import difflib
import math

# --------------------------------------------------------------------------- #
#  the vocabulary: every section and key a definition may carry
# --------------------------------------------------------------------------- #
KNOWN_KEYS: dict[str, set[str]] = {
    "meta": {"project", "author", "notes"},
    "target": {"f_low", "f_high", "fc", "krm_target"},
    "horn": {"profile", "throat_diameter", "length", "mouth_radius", "mouth_area",
             "mouth_shape", "mouth_aspect", "hyperbolic_T", "coverage_angle",
             "throat_angle", "tractrix_angle"},
    "driver": {"file", "name", "Sd", "dD", "Mms", "Cms", "Rms", "Bl", "Re", "Le",
               "ExpoRe", "fre", "ExpoLe", "rear_volume", "rear_q", "Fr", "Nd",
               "Xmax", "Xmax_convention"},
    "simulation": {"voltage", "f_min", "f_max", "n_frequencies", "spacing", "c",
                   "rho", "mouth_termination", "segments", "observation_distance",
                   "directivity", "half_space"},
    "ath": {"profile", "term_s", "term_q", "term_n", "os_k", "coverage_angle",
            "rollback", "rollback_start", "rollback_angle", "mesh", "abec",
            "source", "le", "polars", "output"},
    "ath.mesh": {"angular_segments", "length_segments", "throat_resolution",
                 "mouth_resolution", "interface_resolution", "interface_offset",
                 "subdomain_slices", "quadrants"},
    "ath.abec": {"sim_type", "sim_profile", "f1", "f2", "num_frequencies",
                 "abscissa", "mesh_frequency"},
    "environment": {"platform", "ath_exe", "wine_prefix", "gmsh_cmd",
                    "gnuplot_path", "akabak_exe", "output_root"},
    "output": {"dir", "csv", "plots", "report_md"},
}

# top level sections; "brief" is written by the app and "sweep" holds parameter
# paths as keys, so both are free-form records rather than key sets
TOP_LEVEL = {name.split(".")[0] for name in KNOWN_KEYS} | {"brief", "sweep"}

# numbers that must be strictly positive
POSITIVE = {
    "target.f_low", "target.f_high", "target.fc", "target.krm_target",
    "horn.throat_diameter", "horn.length", "horn.mouth_radius", "horn.mouth_area",
    "horn.mouth_aspect", "horn.hyperbolic_T", "horn.coverage_angle",
    "horn.tractrix_angle",
    "driver.dD", "driver.Sd", "driver.Mms", "driver.Cms", "driver.Rms", "driver.Bl",
    "driver.Re", "driver.fre", "driver.ExpoRe", "driver.rear_q", "driver.Fr",
    "driver.Nd", "driver.Xmax",
    "simulation.voltage", "simulation.f_min", "simulation.f_max", "simulation.c",
    "simulation.rho", "simulation.segments", "simulation.n_frequencies",
    "simulation.observation_distance",
    "ath.term_s", "ath.term_q", "ath.term_n", "ath.os_k", "ath.coverage_angle",
    "ath.rollback_start", "ath.rollback_angle",
    "ath.mesh.angular_segments", "ath.mesh.length_segments",
    "ath.mesh.throat_resolution", "ath.mesh.mouth_resolution",
    "ath.mesh.interface_resolution", "ath.mesh.quadrants",
    "ath.abec.f1", "ath.abec.f2", "ath.abec.num_frequencies",
    "ath.abec.mesh_frequency",
}

# numbers that may be zero but not negative
NON_NEGATIVE = {
    "driver.Le", "driver.rear_volume", "horn.throat_angle",
    "ath.mesh.interface_offset", "ath.abec.sim_type", "ath.abec.sim_profile",
    "ath.abec.abscissa",
}

# numbers where the string "auto" is meaningful (None in the dataclass)
AUTO_KEYS = {"horn.length", "horn.mouth_radius", "horn.mouth_area", "target.fc"}

NUMBER_KEYS = POSITIVE | NON_NEGATIVE | AUTO_KEYS

BOOLEAN_KEYS = {"simulation.half_space", "ath.rollback", "output.csv",
                "output.plots", "output.report_md"}

# unit slips: (low, high, message) in the unit the file writes
RANGE_HINTS = {
    "horn.throat_diameter": (5.0, 1000.0, "looks like metres? values are in mm"),
}


class ConfigError(ValueError):
    """One or more definition errors; ``errors`` keeps every message."""

    def __init__(self, errors) -> None:
        self.errors = [str(e) for e in errors] or ["the definition is invalid"]
        super().__init__(self.errors[0])


def error_lines(exc) -> list[str]:
    """The CLI's stderr lines: the first error, then how many more there are.

    A YAML syntax error is collapsed to one line on purpose: its Python message
    is several lines of parser context, which buries the actual mistake.
    """
    errors = getattr(exc, "errors", None)
    if errors:
        lines = [f"error: {errors[0]}"]
        if len(errors) > 1:
            lines.append(f"(+{len(errors) - 1} more)")
        return lines
    return ["error: " + " ".join(str(exc).split())]


# --------------------------------------------------------------------------- #
#  validation
# --------------------------------------------------------------------------- #
def validate_raw(raw: dict) -> list[str]:
    """Every problem in a parsed definition, as strings a user can act on."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return ["the definition must be a mapping of sections"]
    errors = [_unknown("section", str(name), TOP_LEVEL)
              for name in raw if name not in TOP_LEVEL]

    for section in ("target", "horn", "simulation", "environment", "output"):
        errors += _validate_block(section, raw.get(section))

    driver = raw.get("driver")
    if isinstance(driver, dict):
        errors += _validate_block("driver", driver)
    elif driver is not None and not isinstance(driver, str):
        errors.append("'driver': must be a file name or a mapping of driver items")

    ath = raw.get("ath")
    errors += _validate_block("ath", ath)
    if isinstance(ath, dict):
        for sub in ("mesh", "abec"):
            errors += _validate_block(f"ath.{sub}", ath.get(sub))

    errors += _validate_sweep(raw.get("sweep"))
    for free in ("meta", "brief"):
        block = raw.get(free)
        if block is not None and not isinstance(block, dict):
            errors.append(f"'{free}' must be a mapping")
    return errors


def _validate_block(section: str, block) -> list[str]:
    if block is None:
        return []
    if not isinstance(block, dict):
        return [f"'{section}' must be a mapping"]
    known = KNOWN_KEYS.get(section, set())
    errors = []
    for key, value in block.items():
        dotted = f"{section}.{key}"
        if key not in known:
            errors.append(_unknown("key", dotted, {f"{section}.{k}" for k in known}))
            continue
        if dotted in BOOLEAN_KEYS:
            errors += _check_bool(dotted, value)
        elif dotted in NUMBER_KEYS:
            errors += _check_number(dotted, value)
    return errors


def _validate_sweep(sweep) -> list[str]:
    if sweep is None:
        return []
    if not isinstance(sweep, dict):
        return ["'sweep' must be a mapping of parameter paths to value lists"]
    paths = {f"{section}.{key}" for section, keys in KNOWN_KEYS.items() for key in keys}
    errors = []
    for axis, values in sweep.items():
        if axis not in paths:
            errors.append(_unknown("sweep axis", str(axis), paths))
        elif not isinstance(values, list):
            errors.append(f"'{axis}': a sweep axis needs a list of values")
    return errors


def _check_bool(dotted: str, value) -> list[str]:
    if isinstance(value, bool):
        return []
    return [f"'{dotted}': must be true or false (got {value!r})"]


def _check_number(dotted: str, value) -> list[str]:
    if isinstance(value, str):
        if dotted in AUTO_KEYS and value.strip().lower() == "auto":
            return []
        return [f"'{dotted}': expected a number or 'auto', got {value!r}"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [f"'{dotted}': must be a finite number (got {value!r})"]
    if not math.isfinite(float(value)):
        return [f"'{dotted}': must be finite (got {value!r})"]
    errors = []
    low, high, message = RANGE_HINTS.get(dotted, (None, None, ""))
    if (low is not None and value < low) or (high is not None and value > high):
        errors.append(f"'{dotted}': {value:g} {message}")
    if dotted in POSITIVE and value <= 0:
        errors.append(f"'{dotted}': must be > 0 (got {value:g})")
    elif dotted in NON_NEGATIVE and value < 0:
        errors.append(f"'{dotted}': must be >= 0 (got {value:g})")
    return errors


def _unknown(kind: str, name: str, known) -> str:
    near = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.75)
    hint = f" (did you mean '{near[0]}'?)" if near else ""
    return f"unknown {kind} '{name}'{hint}"
