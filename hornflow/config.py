"""Parameter file (YAML) loading, unit conversion and validation.

The YAML definition file is the single source of truth for both stages:
  Stage 1 (native 1P/LE solver, this package)
  Stage 2 (ATH -> Gmsh -> AKABAK)

The file stores practical units (mm, cm^2, cm^3, g, mH, ohm); this module
converts everything to SI so the physics code has no unit handling at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MM = 1.0e-3
CM2 = 1.0e-4
CM3 = 1.0e-6
GRAM = 1.0e-3
MH = 1.0e-3

PROFILE_FAMILIES = ("exponential", "hyperbolic", "conical", "os", "tractrix")


def _get(d: dict, key: str, where: str, default: Any = None, required: bool = False) -> Any:
    if key in d and d[key] is not None:
        return d[key]
    if required:
        raise KeyError(f"missing required item '{key}' in '{where}'")
    return default


def _auto_or_float(value: Any, name: str) -> float | None:
    """Accepts a number, or the string 'auto' -> None."""
    if isinstance(value, str):
        if value.strip().lower() == "auto":
            return None
        raise ValueError(f"'{name}': expected a number or 'auto', got {value!r}")
    return float(value)


@dataclass
class Target:
    f_low: float
    f_high: float
    fc: float | None            # None = "auto": derive the flare from mouth + length
    krm_target: float

    def __post_init__(self) -> None:
        if not (self.f_low < self.f_high):
            raise ValueError("target.f_low must be below target.f_high")
        if self.fc is not None and self.fc <= 0.0:
            raise ValueError("target.fc must be > 0 or 'auto'")
        if not (0.0 < self.krm_target <= 1.5):
            raise ValueError("target.krm_target should be in (0, 1.5] (paper: 0.7-1 bass, >=1 mid)")


@dataclass
class Horn:
    profile: str
    throat_diameter: float      # [m] full exit diameter = 2*r0
    length: float | None        # [m] or None -> derived from the mouth target
    mouth_radius: float | None  # [m] or None -> derived from krm_target / mouth_area
    mouth_area: float | None = None   # [m^2] alternative to mouth_radius (equal-area circle)
    mouth_shape: str = "round"        # round | rectangular
    mouth_aspect: float = 1.6         # width / height when rectangular (wider than tall)
    T: float = 1.0              # hyperbolic family parameter
    coverage_angle: float = 45.0   # [deg] half included angle (os/conical)
    throat_angle: float = 0.0      # [deg] half included angle at the throat
    tractrix_angle: float = 90.0   # [deg] wall tangent angle at the mouth

    def __post_init__(self) -> None:
        if self.profile not in PROFILE_FAMILIES:
            raise ValueError(
                f"horn.profile must be one of {PROFILE_FAMILIES}, got {self.profile!r}"
            )
        if self.throat_diameter <= 0.0:
            raise ValueError("horn.throat_diameter must be > 0")
        if self.length is not None and self.length <= 0.0:
            raise ValueError("horn.length must be > 0 or 'auto'")
        if self.mouth_radius is not None and self.mouth_radius <= 0.0:
            raise ValueError("horn.mouth_radius must be > 0 or 'auto'")
        if self.mouth_area is not None and self.mouth_area <= 0.0:
            raise ValueError("horn.mouth_area must be > 0 or 'auto'")
        if self.mouth_radius is not None and self.mouth_area is not None:
            raise ValueError("give horn.mouth_radius or horn.mouth_area, not both")
        if self.mouth_shape not in ("round", "rectangular"):
            raise ValueError("horn.mouth_shape must be 'round' or 'rectangular'")
        if not (1.0 <= self.mouth_aspect <= 4.0):
            raise ValueError("horn.mouth_aspect (width/height) should be in 1.0 - 4.0")
        if self.profile == "hyperbolic" and not (0.0 < self.T <= 6.0):
            raise ValueError("horn.hyperbolic_T should be in (0, 6] (paper: 0.5-1 most useful)")
        if not (0.0 < self.coverage_angle < 90.0):
            raise ValueError("horn.coverage_angle must be in (0, 90) deg")


@dataclass
class Driver:
    """Lumped-element driver, same quantity set as the ABEC/AKABAK LE scripts."""

    name: str
    dD: float          # effective piston diameter [m]
    Mms: float         # moving mass [kg]
    Cms: float         # suspension compliance [m/N]
    Rms: float         # mechanical resistance [Ns/m]
    Bl: float          # force factor [T*m]
    Re: float          # voice coil DC resistance [ohm]
    Le: float          # voice coil inductance [H]
    ExpoRe: float = 1.0
    fre: float = 35.0  # [kHz] reference frequency of the Re loss model
    ExpoLe: float = 0.618
    rear_volume: float = 0.0  # [m^3], 0 -> open back
    rear_q: float = 7.0       # rear cavity loss (Q at the cavity resonance)
    Fr: float | None = None   # measured free-air resonance [Hz] (validation only)
    Nd: int = 1               # number of voice coils (informational)
    Xmax: float | None = None  # [m] excursion limit - see Xmax_convention below
    Xmax_convention: str = "one_way_peak"  # one_way_peak | peak_to_peak

    @property
    def Sd(self) -> float:
        """Piston area [m^2]."""
        return math.pi * self.dD ** 2 / 4.0

    @property
    def fs(self) -> float:
        """Free-air resonance without air load / rear cavity [Hz]."""
        return 1.0 / (2.0 * math.pi * math.sqrt(self.Mms * self.Cms))

    @property
    def Qms(self) -> float:
        """Mechanical Q."""
        return 2.0 * math.pi * self.fs * self.Mms / self.Rms

    @property
    def Qes(self) -> float:
        """Electrical Q."""
        return 2.0 * math.pi * self.fs * self.Mms * self.Re / self.Bl ** 2

    @property
    def Qts(self) -> float:
        """Total Q."""
        return 1.0 / (1.0 / self.Qes + 1.0 / self.Qms)

    @property
    def Vas(self) -> float:
        """Equivalent suspension volume [m^3] at standard air conditions."""
        return 1.205 * 343.0 ** 2 * self.Sd ** 2 * self.Cms

    def __post_init__(self) -> None:
        for name in ("dD", "Mms", "Cms", "Rms", "Bl", "Re"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"driver.{name} must be > 0 (got {getattr(self, name)})")
        if self.Le < 0.0 or self.rear_volume < 0.0:
            raise ValueError("driver.Le and driver.rear_volume must be >= 0")
        if self.Xmax is not None and self.Xmax <= 0.0:
            raise ValueError("driver.Xmax must be > 0 (metres) when given")
        # Validate (do not guess) the excursion convention.  Imported locally so
        # this module stays importable from anywhere without a cycle.
        from .domain.excursion import normalize_convention

        self.Xmax_convention = normalize_convention(self.Xmax_convention)

    @property
    def Xmax_one_way_peak(self) -> float | None:
        """Xmax converted to one-way peak [m] - the like-for-like comparison value."""
        from .domain.excursion import xmax_one_way_peak

        return None if self.Xmax is None else xmax_one_way_peak(
            self.Xmax, self.Xmax_convention)


@dataclass
class Simulation:
    voltage: float = 2.83
    f_min: float = 20.0
    f_max: float = 1000.0
    n_frequencies: int = 400
    spacing: str = "log"
    c: float = 343.0
    rho: float = 1.205
    mouth_termination: str = "piston_infinite_baffle"
    segments: int = 200
    observation_distance: float = 1.0
    directivity: str = "piston"
    half_space: bool = True   # True -> piston in an infinite baffle (2x pressure)

    MOUTH_TERMINATIONS = ("infinite_pipe", "piston_infinite_baffle", "sphere")

    def __post_init__(self) -> None:
        if self.f_min <= 0.0 or self.f_max <= self.f_min:
            raise ValueError("simulation.f_min/f_max are inconsistent")
        if self.n_frequencies < 5:
            raise ValueError("simulation.n_frequencies must be >= 5")
        if self.spacing not in ("log", "linear"):
            raise ValueError("simulation.spacing must be 'log' or 'linear'")
        if self.mouth_termination not in self.MOUTH_TERMINATIONS:
            raise ValueError(
                f"simulation.mouth_termination must be one of {self.MOUTH_TERMINATIONS}"
            )
        if self.segments < 20:
            raise ValueError("simulation.segments must be >= 20")
        if self.c <= 0.0 or self.rho <= 0.0:
            raise ValueError("simulation.c and simulation.rho must be > 0")

    def frequencies(self):
        import numpy as np

        if self.spacing == "log":
            return np.logspace(math.log10(self.f_min), math.log10(self.f_max),
                               int(self.n_frequencies))
        return np.linspace(self.f_min, self.f_max, int(self.n_frequencies))


@dataclass
class AthMesh:
    angular_segments: int = 64
    length_segments: int = 120
    throat_resolution: float = 4.0
    mouth_resolution: float = 20.0
    interface_resolution: float = 20.0
    interface_offset: float = 5.0
    subdomain_slices: Any = "auto"
    quadrants: int = 1


@dataclass
class AthAbec:
    sim_type: int = 2
    sim_profile: int = 0
    f1: float = 80.0
    f2: float = 250.0
    num_frequencies: int = 40
    abscissa: int = 1
    mesh_frequency: float = 2000.0


@dataclass
class AthConfig:
    """Stage 2 settings -> ATH horn definition file (Ath User Guide, chapter 4)."""

    profile: str = "os_se"
    term_s: float = 0.7
    term_q: float = 0.995
    term_n: float = 4.0
    os_k: float = 1.0
    coverage_angle: float = 45.0
    rollback: bool = False
    rollback_start: float = 0.6
    rollback_angle: float = 180.0
    mesh: AthMesh = field(default_factory=AthMesh)
    abec: AthAbec = field(default_factory=AthAbec)
    source: dict = field(default_factory=dict)
    le_script: str | None = None
    le_voltage: float = 2.83
    polars: list = field(default_factory=list)
    output: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.profile not in ("os_se", "circ_arc"):
            raise ValueError("ath.profile must be 'os_se' or 'circ_arc'")


@dataclass
class Environment:
    """Where ATH/Gmsh/AKABAK live (Stage 2 only)."""

    platform: str = "windows"
    ath_exe: str = "ath.exe"
    wine_prefix: str | None = None
    gmsh_cmd: str = "gmsh.exe %f -"
    gnuplot_path: str | None = None
    akabak_exe: str | None = None
    output_root: str = "C:/Horns"

    def __post_init__(self) -> None:
        if self.platform not in ("windows", "wine"):
            raise ValueError("environment.platform must be 'windows' or 'wine'")
        if "%f" not in self.gmsh_cmd:
            raise ValueError("environment.gmsh_cmd must contain the '%f' placeholder "
                             "(Ath User Guide 1.1.3)")


@dataclass
class Output:
    dir: str = "results"
    csv: bool = True
    plots: bool = True
    report_md: bool = True


@dataclass
class Params:
    meta: dict = field(default_factory=dict)
    target: Target | None = None
    horn: Horn | None = None
    driver: Driver | None = None
    simulation: Simulation = field(default_factory=Simulation)
    ath: AthConfig = field(default_factory=AthConfig)
    environment: Environment = field(default_factory=Environment)
    output: Output = field(default_factory=Output)
    source_path: Path | None = None
    raw: dict = field(default_factory=dict)

    @property
    def project(self) -> str:
        return str(self.meta.get("project", "horn_project"))


def _build_driver(d: dict) -> Driver:
    # Sd (cm^2) is accepted as an alternative to dD (mm)
    if "Sd" in d and "dD" not in d:
        sd_m2 = float(d["Sd"]) * CM2
        d_diameter_mm = math.sqrt(4.0 * sd_m2 / math.pi) * 1e3
    else:
        d_diameter_mm = float(_get(d, "dD", "driver", required=True))
    return Driver(
        name=str(_get(d, "name", "driver", "driver")),
        dD=d_diameter_mm * MM,
        Mms=float(_get(d, "Mms", "driver", required=True)) * GRAM,
        Cms=float(_get(d, "Cms", "driver", required=True)),
        Rms=float(_get(d, "Rms", "driver", 0.1)),
        Bl=float(_get(d, "Bl", "driver", required=True)),
        Re=float(_get(d, "Re", "driver", required=True)),
        Le=float(_get(d, "Le", "driver", 0.0)) * MH,
        ExpoRe=float(_get(d, "ExpoRe", "driver", 1.0)),
        fre=float(_get(d, "fre", "driver", 35.0)),
        ExpoLe=float(_get(d, "ExpoLe", "driver", 0.618)),
        rear_volume=float(_get(d, "rear_volume", "driver", 0.0)) * CM3,
        rear_q=float(_get(d, "rear_q", "driver", 7.0)),
        Fr=None if _get(d, "Fr", "driver", None) is None else float(d["Fr"]),
        Nd=int(_get(d, "Nd", "driver", 1)),
        Xmax=None if _get(d, "Xmax", "driver", None) is None else float(d["Xmax"]) * MM,
        Xmax_convention=_get(d, "Xmax_convention", "driver", "one_way_peak"),
    )


def load(path: str | Path, overrides: dict | None = None) -> Params:
    """Read and validate a definition file, returning SI-unit dataclasses.

    ``overrides`` are dotted item paths, e.g. {"horn.mouth_radius": 600}, applied
    to the file content before validation.  The sweep mode uses this to run the
    same file with a grid of parameter values.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"definition file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if overrides:
        raw = apply_overrides(raw, overrides)
    return build(raw, source_path=path)


def apply_overrides(raw: dict, overrides: dict) -> dict:
    """Return a copy of ``raw`` with dotted keys ('horn.mouth_radius') replaced."""
    import copy as _copy

    out = _copy.deepcopy(raw)
    for key, value in overrides.items():
        node = out
        parts = str(key).split(".")
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value
    return out


def parse_value(text: str):
    """Parse a CLI sweep value: '600' -> 600, '1e-4' -> 1e-4, 'auto' -> 'auto'."""
    return yaml.safe_load(str(text))


def build(raw: dict, source_path=None) -> Params:
    """Validate an already parsed definition mapping (use load() normally)."""
    t = raw.get("target", {}) or {}
    h = raw.get("horn", {}) or {}
    d = raw.get("driver", {}) or {}
    s = raw.get("simulation", {}) or {}

    # a driver may live in its own file:  driver: jbl_1200b.yaml
    #                              or:  driver: {file: drivers/jbl_1200b.yaml}
    if isinstance(d, str) or (isinstance(d, dict) and "file" in d):
        name = d if isinstance(d, str) else d["file"]
        base = Path(source_path).resolve().parent if source_path else Path.cwd()
        ref = Path(name)
        cand = ref if ref.is_absolute() else base / ref
        if not cand.is_file():
            cand = base / "drivers" / ref.name
        if not cand.is_file():
            raise FileNotFoundError(f"driver file not found: {name} (looked in {base})")
        loaded = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict) and isinstance(loaded.get("driver"), dict):
            loaded = loaded["driver"]                      # allow a driver: wrapper
        if not isinstance(loaded, dict):
            raise ValueError(f"driver file {cand} must contain a mapping of driver items")
        if isinstance(d, dict):
            loaded = {**loaded, **{k: v for k, v in d.items() if k != "file"}}
        d = loaded

    _len = _auto_or_float(_get(h, "length", "horn", default="auto"), "horn.length")
    _rm = _auto_or_float(_get(h, "mouth_radius", "horn", default="auto"), "horn.mouth_radius")
    _area = _auto_or_float(_get(h, "mouth_area", "horn", default="auto"), "horn.mouth_area")

    horn = Horn(
        profile=str(_get(h, "profile", "horn", "exponential")),
        throat_diameter=float(_get(h, "throat_diameter", "horn", required=True)) * MM,
        length=None if _len is None else _len * MM,
        mouth_radius=None if _rm is None else _rm * MM,
        mouth_area=None if _area is None else _area * CM2,
        mouth_shape=str(_get(h, "mouth_shape", "horn", "round")),
        mouth_aspect=float(_get(h, "mouth_aspect", "horn", 1.6)),
        T=float(_get(h, "hyperbolic_T", "horn", 1.0)),
        coverage_angle=float(_get(h, "coverage_angle", "horn", 45.0)),
        throat_angle=float(_get(h, "throat_angle", "horn", 0.0)),
        tractrix_angle=float(_get(h, "tractrix_angle", "horn", 90.0)),
    )

    target = Target(
        f_low=float(_get(t, "f_low", "target", required=True)),
        f_high=float(_get(t, "f_high", "target", required=True)),
        fc=_auto_or_float(_get(t, "fc", "target", default="auto"), "target.fc"),
        krm_target=float(_get(t, "krm_target", "target", 0.9)),
    )

    mt = str(_get(s, "mouth_termination", "simulation", "piston_infinite_baffle"))
    sim = Simulation(
        voltage=float(_get(s, "voltage", "simulation", 2.83)),
        f_min=float(_get(s, "f_min", "simulation", 20.0)),
        f_max=float(_get(s, "f_max", "simulation", 1000.0)),
        n_frequencies=int(_get(s, "n_frequencies", "simulation", 400)),
        spacing=str(_get(s, "spacing", "simulation", "log")),
        c=float(_get(s, "c", "simulation", 343.0)),
        rho=float(_get(s, "rho", "simulation", 1.205)),
        mouth_termination=mt,
        segments=int(_get(s, "segments", "simulation", 200)),
        observation_distance=float(_get(s, "observation_distance", "simulation", 1.0)),
        directivity=str(_get(s, "directivity", "simulation", "piston")),
        half_space=bool(_get(s, "half_space", "simulation", mt != "sphere")),
    )

    a = raw.get("ath", {}) or {}
    am = a.get("mesh", {}) or {}
    aa = a.get("abec", {}) or {}
    default_mesh = AthMesh()
    default_abec = AthAbec()
    ath = AthConfig(
        profile=str(_get(a, "profile", "ath", "os_se")),
        term_s=float(_get(a, "term_s", "ath", 0.7)),
        term_q=float(_get(a, "term_q", "ath", 0.995)),
        term_n=float(_get(a, "term_n", "ath", 4.0)),
        os_k=float(_get(a, "os_k", "ath", 1.0)),
        coverage_angle=float(_get(a, "coverage_angle", "ath", 45.0)),
        rollback=bool(_get(a, "rollback", "ath", False)),
        rollback_start=float(_get(a, "rollback_start", "ath", 0.6)),
        rollback_angle=float(_get(a, "rollback_angle", "ath", 180.0)),
        mesh=AthMesh(**{k: am.get(k, getattr(default_mesh, k)) for k in default_mesh.__dict__}),
        abec=AthAbec(**{k: aa.get(k, getattr(default_abec, k)) for k in default_abec.__dict__}),
        source=dict(a.get("source", {}) or {}),
        le_script=((a.get("le", {}) or {}).get("script")),
        le_voltage=float((a.get("le", {}) or {}).get("voltage", 2.83)),
        polars=list(a.get("polars", []) or []),
        output=dict(a.get("output", {}) or {}),
    )

    e = raw.get("environment", {}) or {}
    env = Environment(
        platform=str(_get(e, "platform", "environment", "windows")),
        ath_exe=str(_get(e, "ath_exe", "environment", "ath.exe")),
        wine_prefix=_get(e, "wine_prefix", "environment", None),
        gmsh_cmd=str(_get(e, "gmsh_cmd", "environment", "gmsh.exe %f -")),
        gnuplot_path=_get(e, "gnuplot_path", "environment", None),
        akabak_exe=_get(e, "akabak_exe", "environment", None),
        output_root=str(_get(e, "output_root", "environment", "C:/Horns")),
    )

    o = raw.get("output", {}) or {}
    out = Output(
        dir=str(_get(o, "dir", "output", "results")),
        csv=bool(_get(o, "csv", "output", True)),
        plots=bool(_get(o, "plots", "output", True)),
        report_md=bool(_get(o, "report_md", "output", True)),
    )

    return Params(meta=dict(raw.get("meta", {}) or {}), target=target, horn=horn,
                  driver=_build_driver(d), simulation=sim, ath=ath, environment=env,
                  output=out, source_path=source_path, raw=raw)


