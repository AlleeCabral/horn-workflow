"""Stage 1 solver: lumped-element driver loaded by the 1P horn model.

The driver network uses the same quantity set as the ABEC/AKABAK LE scripts
(Re, Le, Bl, Mms, Cms, Rms + rear cavity); the horn load is the throat impedance
of the finite horn (theory.finite_throat_impedance); the radiated sound is
estimated from the mouth volume velocity as a piston in an infinite baffle
(paper: "Termination of the horn" and the directivity sections of Part 2).

Deliberately *not* modelled here: diffraction, higher-order modes, 3D/baffle/
ground effects, phase-plug and front-cavity detail - that is Stage 2
(ATH -> Gmsh -> AKABAK, BEM).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import theory
from .config import Driver, Params, Simulation


def voice_coil_impedance(driver: Driver, f: np.ndarray) -> np.ndarray:
    """Frequency dependent voice-coil impedance, AKABAK "Akabak model".

    Verbatim from the AKABAK help system (LE Voice Coil Parameters):
        Zvc = Re(f) + j Xe(f)
        Re(f) = Re (1 + f/fre)^ExpoRe            (eddy currents, fre >> fs)
        Xe    = (w Le) r,  r = (1 + ExpoLe q^2)/(1 + q^2),  q = w Le/Re
    The parameters (Re, Le, fre, ExpoRe, ExpoLe) are exactly the ones used by the
    ATH/ABEC lumped-element driver scripts, so Stage 2 can inject the same numbers
    into the LE script without conversion.
    """
    w = 2.0 * np.pi * f
    ref = driver.fre * 1e3                      # scripts give fre in kHz
    re_f = driver.Re * (1.0 + f / ref) ** driver.ExpoRe
    q = w * driver.Le / driver.Re
    r = (1.0 + driver.ExpoLe * q ** 2) / (1.0 + q ** 2)
    return re_f + 1j * w * driver.Le * r


def rear_impedance(driver: Driver, f: np.ndarray, c: float, rho: float) -> np.ndarray:
    """Acoustic impedance of the sealed rear cavity (compliance + loss).

    Cb = Vb/(rho c^2); the loss resistance follows from the cavity Q at the
    driver resonance, Rb = 1/(Qb * w_s * Cb).  Vb = 0 -> open back (no load).
    """
    if driver.rear_volume <= 0.0:
        return np.zeros_like(f, dtype=complex)
    cb = driver.rear_volume / (rho * c ** 2)
    w = 2.0 * np.pi * f
    rb = 1.0 / (driver.rear_q * 2.0 * math.pi * driver.fs * cb)
    return rb + 1.0 / (1j * w * cb)


def sealed_box_alignment(driver: Driver, c: float = 343.0, rho: float = 1.205) -> dict:
    """Where a sealed rear chamber puts the driver (T/S small-signal alignment).

    alpha = Vas/Vb; box resonance fb = fs sqrt(1+alpha); Qtc = Qts sqrt(1+alpha).
    """
    vas = driver.Vas
    if driver.rear_volume <= 0.0:
        return {"alpha": float("nan"), "fb": driver.fs, "Qtc": driver.Qts,
                "note": "open back (no rear chamber)"}
    alpha = vas / driver.rear_volume
    root = math.sqrt(1.0 + alpha)
    return {"alpha": alpha, "fb": driver.fs * root, "Qtc": driver.Qts * root,
            "Vas_l": vas * 1e3, "note": ""}


@dataclass
class Result:
    """Everything Stage 1 produces."""

    f: np.ndarray
    design: theory.Design
    Zt: np.ndarray                     # throat impedance seen by the driver
    Zt_infinite: np.ndarray | None     # analytic reference (paper Eqs. 7/9)
    Ze: np.ndarray                     # electrical impedance
    current: np.ndarray
    velocity: np.ndarray               # diaphragm velocity
    excursion: np.ndarray              # diaphragm excursion [m]
    U_mouth: np.ndarray                # mouth volume velocity
    p_axis: np.ndarray                 # on-axis pressure at the observation point
    spl: np.ndarray                    # on-axis SPL [dB]
    di: np.ndarray                     # directivity index of the mouth [dB]
    derived: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def band_spl(self, f_lo: float, f_hi: float) -> float:
        """Mean on-axis SPL in a frequency band [dB]."""
        m = (self.f >= f_lo) & (self.f <= f_hi)
        return float(np.mean(self.spl[m])) if np.any(m) else float("nan")

    def variations_db(self, f_lo: float, f_hi: float) -> float:
        """Peak-to-peak variation of the on-axis SPL in a band [dB]."""
        m = (self.f >= f_lo) & (self.f <= f_hi)
        if not np.any(m):
            return float("nan")
        band = self.spl[m]
        return float(np.max(band) - np.min(band))


def simulate(params: Params) -> Result:
    """Run the Stage 1 simulation described by a validated parameter set."""
    sim: Simulation = params.simulation
    driver: Driver = params.driver
    design = theory.solve_design(params.horn, params.target, c=sim.c, rho=sim.rho)
    f = sim.frequencies()
    w = 2.0 * np.pi * f

    zt = theory.finite_throat_impedance(design, f, sim.mouth_termination, sim.segments)
    zt_inf = theory.infinite_throat_impedance(design, f)
    z_rear = rear_impedance(driver, f, sim.c, sim.rho)

    # mechanical impedance of the moving assembly, including the reflected
    # acoustic loads (an acoustical impedance becomes mechanical as Z*Sd^2)
    sd2 = driver.Sd ** 2
    zm = (driver.Rms + 1j * w * driver.Mms + 1.0 / (1j * w * driver.Cms)
          + (zt + z_rear) * sd2)

    ze = voice_coil_impedance(driver, f) + driver.Bl ** 2 / zm
    current = sim.voltage / ze
    velocity = driver.Bl * current / zm
    excursion = velocity / (1j * w)

    u_throat = velocity * driver.Sd                 # volume velocity into the throat
    u_mouth = theory.mouth_volume_velocity(design, f, u_throat, sim.mouth_termination,
                                          sim.segments)

    r_obs = sim.observation_distance
    k = theory.k_of(f, sim.c)
    opening = 2.0 if sim.half_space else 4.0        # baffled piston: pressure doubles
    p_axis = (1j * w * sim.rho * u_mouth * np.exp(-1j * k * r_obs)
              / (opening * math.pi * r_obs))
    spl = 20.0 * np.log10(np.maximum(np.abs(p_axis), 1e-12) / theory.P_REF)
    di = theory.piston_di(k * design.rm, sim.half_space)

    derived = design.derived(params.target.f_low, params.target.krm_target)
    align = sealed_box_alignment(driver, sim.c, sim.rho)
    derived.update({
        "driver_fs_hz": driver.fs,
        "driver_Qms": driver.Qms,
        "driver_Qes": driver.Qes,
        "driver_Qts": driver.Qts,
        "driver_Vas_l": driver.Vas * 1e3,
        "box_alpha": align["alpha"],
        "box_resonance_hz": align["fb"],
        "box_Qtc": align["Qtc"],
    })
    derived["mouth_ka_at_f_high"] = float(theory.k_of(params.target.f_high, sim.c) * design.rm)
    derived["driver_fs_hz"] = driver.fs
    derived["driver_Sd_cm2"] = driver.Sd * 1e4
    derived["compression_ratio_Sd_St"] = driver.Sd / design.St
    derived["q_coverage"] = theory.coverage_q(2.0 * params.horn.coverage_angle,
                                              2.0 * params.horn.coverage_angle)
    derived["directivity_intercept_hz"] = theory.intercept_frequency(
        design.rm * 2e3, params.horn.coverage_angle * 2.0)
    derived["spl_mean_band_db"] = None      # filled by the caller/report
    derived["spl_variation_band_db"] = None

    warnings = list(getattr(design, "warnings", []))
    notes = list(getattr(design, "notes", []))
    if driver.Fr:
        diff = (driver.fs - driver.Fr) / driver.Fr * 100.0
        line = (f"driver: fs from Mms/Cms = {driver.fs:.2f} Hz vs the measured Fr = "
                f"{driver.Fr:.2f} Hz ({diff:+.1f} %)")
        if abs(diff) <= 5.0:
            notes.append(line + " - the measured parameters are consistent")
        else:
            warnings.append(line + " - check Mms/Cms against the measurement")
    if derived["k_rm_at_fc"] < 0.7:
        warnings.append(
            f"mouth is small for a bass horn: k*rm = {derived['k_rm_at_fc']:.2f} at fc "
            "(paper: 0.7-1 for smooth bass response)")
    if params.target.f_low < design.fc:
        warnings.append(
            f"target f_low ({params.target.f_low:.0f} Hz) is below the flare cut-off "
            f"({design.fc:.0f} Hz): the horn does not load the driver there")
    k_rt_high = 2.0 * math.pi * params.target.f_high * design.rt / sim.c
    if k_rt_high > 1.0:
        warnings.append(
            f"k*rt = {k_rt_high:.2f} at {params.target.f_high:.0f} Hz: the 1P assumption "
            "(and the BEM mesh) need care above that frequency")

    return Result(f=f, design=design, Zt=zt, Zt_infinite=zt_inf, Ze=ze, current=current,
                  velocity=velocity, excursion=excursion, U_mouth=u_mouth, p_axis=p_axis,
                  spl=spl, di=di, derived=derived, warnings=warnings, notes=notes)