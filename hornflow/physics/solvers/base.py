"""Acoustic solver contract and the normalized simulation-run schema.

Level-1 (analytical), Level-2 (one-dimensional) and Level-3 (BEM) solvers all
return a ``SimulationRun`` with the same normalized, SI, per-frequency columns
so downstream stages never special-case a solver.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Protocol, runtime_checkable

import numpy as np

from ...domain.evidence import now_utc

# normalized per-frequency column order (spec)
SIM_COLUMNS = (
    "frequency_hz", "drive_voltage_v", "input_power_w", "radiation_angle_sr",
    "spl_db", "impedance_real_ohm", "impedance_imag_ohm", "impedance_magnitude_ohm",
    "phase_deg", "excursion_m", "group_delay_s", "throat_velocity_m_s",
    "mouth_velocity_m_s",
)


@dataclass
class SimulationRun:
    candidate_id: str
    architecture_id: str
    solver: str
    solver_version: str
    fidelity: str                              # ANALYTICAL_ESTIMATE | ONE_DIMENSIONAL_SIMULATION | BEM_SIMULATION
    frequency_hz: np.ndarray
    drive_voltage_v: float
    spl_db: np.ndarray
    impedance_real_ohm: np.ndarray
    impedance_imag_ohm: np.ndarray
    excursion_m: np.ndarray
    phase_deg: np.ndarray
    throat_velocity_m_s: np.ndarray | None = None
    mouth_velocity_m_s: np.ndarray | None = None
    group_delay_s: np.ndarray | None = None
    input_power_w: np.ndarray | None = None
    radiation_angle_sr: float = 0.0
    fold_id: str | None = None
    manufacturing_variant_id: str | None = None
    grid: dict = field(default_factory=dict)
    boundary: str = ""
    validity_flags: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    created_utc: str = field(default_factory=now_utc)

    @property
    def impedance_magnitude_ohm(self) -> np.ndarray:
        return np.hypot(self.impedance_real_ohm, self.impedance_imag_ohm)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, np.ndarray):
                d[k] = v.tolist()
        return d

    def rows(self) -> list:
        """The normalized tabular dataset (one dict per frequency, in SI)."""
        n = len(self.frequency_hz)
        mag = self.impedance_magnitude_ohm
        out = []
        for i in range(n):
            out.append({
                "frequency_hz": float(self.frequency_hz[i]),
                "drive_voltage_v": float(self.drive_voltage_v),
                "input_power_w": _at(self.input_power_w, i),
                "radiation_angle_sr": float(self.radiation_angle_sr),
                "spl_db": float(self.spl_db[i]),
                "impedance_real_ohm": float(self.impedance_real_ohm[i]),
                "impedance_imag_ohm": float(self.impedance_imag_ohm[i]),
                "impedance_magnitude_ohm": float(mag[i]),
                "phase_deg": float(self.phase_deg[i]),
                "excursion_m": float(self.excursion_m[i]),
                "group_delay_s": _at(self.group_delay_s, i),
                "throat_velocity_m_s": _at(self.throat_velocity_m_s, i),
                "mouth_velocity_m_s": _at(self.mouth_velocity_m_s, i),
                "validity_flags": _flags(self.validity_flags),
                "solver": self.solver,
                "solver_version": self.solver_version,
            })
        return out

    def to_table(self) -> tuple:
        header = list(SIM_COLUMNS) + ["validity_flags", "solver", "solver_version"]
        return header, [[r[h] for h in header] for r in self.rows()]


def _at(arr, i):
    if arr is None:
        return None
    return float(np.asarray(arr)[i])


def _flags(d: dict) -> str:
    return ";".join(f"{k}={v}" for k, v in sorted(d.items())) if d else ""


@runtime_checkable
class AcousticSolver(Protocol):
    name: str
    version: str
    fidelity: str

    def solve(self, master, grid, drive, boundary: str, **kw) -> SimulationRun:
        ...
