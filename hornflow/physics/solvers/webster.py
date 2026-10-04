"""Level-2 solver adapter over the existing validated Webster core.

This wraps ``hornflow.response.simulate`` without changing any physics: it runs
the mature one-dimensional horn + lumped-element model and *normalizes* the
result into a ``SimulationRun``.  The baseline regression test
(tests/test_baseline.py) guarantees this adapter cannot drift from the original
numbers.
"""

from __future__ import annotations

import numpy as np

from ... import __version__
from ... import response as _response
from ...domain.evidence import EvidenceLabel
from .base import SimulationRun

SOLVER_NAME = "hornflow-webster-1p"


class WebsterSolver:
    """1-P (Webster) horn + lumped-element driver, the validated Stage-1 model."""

    name = SOLVER_NAME
    version = __version__
    fidelity = EvidenceLabel.ONE_DIMENSIONAL_SIMULATION.value

    def __init__(self, params) -> None:
        self.params = params

    def solve(self, master=None, grid=None, drive: float | None = None,
              boundary: str | None = None, candidate_id: str | None = None,
              **kw) -> SimulationRun:
        p = self.params
        r = _response.simulate(p)
        f = np.asarray(r.f, dtype=float)
        w = 2.0 * np.pi * f
        sd = p.driver.Sd
        st = float(r.design.St)
        sm = float(r.design.Sm)

        u_throat = np.abs(r.velocity) * sd
        u_mouth = np.abs(r.U_mouth)

        phase = np.unwrap(np.angle(r.p_axis))
        gd = -np.gradient(phase, w)

        ze = r.Ze
        v = float(drive if drive is not None else p.simulation.voltage)
        # electrical input power P = Vrms^2 / Re(Zin)  (Re is the real part)
        power = v ** 2 * np.real(1.0 / ze)

        cid = candidate_id or (master.candidate_id if master is not None else "ref")
        arch = master.architecture_id if master is not None else "front_loaded_horn"
        derived = r.design.derived(p.target.f_low, p.target.krm_target)
        run = SimulationRun(
            candidate_id=cid,
            architecture_id=arch,
            solver=self.name,
            solver_version=self.version,
            fidelity=self.fidelity,
            frequency_hz=f,
            drive_voltage_v=v,
            spl_db=np.asarray(r.spl, dtype=float),
            impedance_real_ohm=np.real(ze),
            impedance_imag_ohm=np.imag(ze),
            excursion_m=np.abs(r.excursion),
            phase_deg=np.degrees(phase),
            throat_velocity_m_s=u_throat / st,
            mouth_velocity_m_s=u_mouth / sm,
            group_delay_s=gd,
            input_power_w=power,
            radiation_angle_sr=(2.0 * np.pi if p.simulation.half_space else 4.0 * np.pi),
            grid={"f_min": float(f[0]), "f_max": float(f[-1]), "n": int(len(f)),
                  "spacing": p.simulation.spacing},
            boundary=boundary or p.simulation.mouth_termination,
            validity_flags={
                "one_parameter": bool(derived["f_1P_validity_hz"] >= f[-1]),
                "krt_at_fmax": round(float(derived.get("k_rt_at_fc", 0.0)), 4),
            },
            metrics=_metrics(r, p),
            warnings=list(r.warnings),
        )
        return run


def _metrics(r, p) -> dict:
    t = p.target
    exc = np.abs(r.excursion)
    return {
        "spl_mean_db": float(r.band_spl(t.f_low, t.f_high)),
        "spl_variation_db": float(r.variations_db(t.f_low, t.f_high)),
        "ze_min_ohm": float(np.min(np.abs(r.Ze))),
        "ze_max_ohm": float(np.max(np.abs(r.Ze))),
        "excursion_max_mm": float(np.max(exc) * 1e3),
        "excursion_max_at_hz": float(r.f[int(np.argmax(exc))]),
        "di_min_db": float(np.min(r.di)),
        "di_max_db": float(np.max(r.di)),
    }
