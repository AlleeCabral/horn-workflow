"""Horn theory: profile geometry, derived design quantities, throat impedance.

Reference: B. Kolbrek, "Horn Theory: An Introduction", Parts 1 & 2,
audioXpress 2008 -- docs/an-introduction-to-horn-theory.pdf
The equation numbers below are the ones used in the paper.

  Webster horn equation, 1P (one-parameter) assumption      Appendix (Part 2)
  conical horn      S = Omega (x + x0)^2                    Eq. (5), (6)
  conical horn      infinite throat impedance                Eq. (7)
  exponential horn  S = St e^(m x), flare rate m             Part 1
  exponential horn  infinite throat impedance                Eq. (9)
  hyperbolic horn   Salmon family, parameter T               Eqs. (10)-(13)
  what cutoff is / flare rate                                Part 1
  finite horn       [pt,Ut] = M [pm,Um], Zt=(g Zm-b)/(a-f Zm) Eqs. (14)-(16)
  mouth termination k*rm criterion (0.7-1 bass, >= 1 mid)    Part 1
  OS waveguide      r^2 = rt^2 + (x tan t0)^2                Eq. (23)
  OS waveguide      fc = 0.2 c sin(t0) / (pi rt)             Eq. (24)
  directivity       Q = 180^2/(a b), f_I = 25e6/(x t)        Eqs. (25), (26)

Conventions: e^{+j w t} time convention, so a mass-like reactance is
positive imaginary.  Pressure/volume velocity pairs are used throughout
(acoustic two-port), volume velocity positive away from the throat.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import special

P_REF = 20.0e-6          # reference pressure [Pa]
C_DEFAULT = 343.0        # speed of sound [m/s]
RHO_DEFAULT = 1.205      # air density [kg/m^3]


def k_of(f: Any, c: float = C_DEFAULT) -> np.ndarray:
    """Wave number [1/m] (paper: k = 2*pi*f/c)."""
    return 2.0 * np.pi * np.asarray(f, dtype=float) / c


def lambda_of(f: Any, c: float = C_DEFAULT) -> np.ndarray:
    return c / np.asarray(f, dtype=float)


@dataclass
class Design:
    """Fully resolved horn geometry (SI units).

    Exactly one of ``length`` / ``mouth_radius`` is derived, see solve_design().
    """

    profile: str
    rt: float                    # throat radius [m]
    length: float                # axial depth [m]
    rm: float                    # mouth radius [m]
    fc: float                    # cut-off frequency of the flare [Hz]
    c: float = C_DEFAULT
    rho: float = RHO_DEFAULT
    T: float = 1.0               # hyperbolic family parameter
    coverage_angle: float = 45.0  # half included angle [deg] (os / conical)
    tractrix_angle: float = 90.0  # wall tangent angle at the mouth [deg]
    mouth_shape: str = "round"    # round | rectangular
    mouth_aspect: float = 1.6     # width / height when rectangular
    _table: tuple = field(default=(), repr=False)

    def __post_init__(self) -> None:
        """Keep the mouth radius consistent with the profile geometry.

        The wall radius at x = length is what the profile formula gives, so a
        design can never claim a mouth radius that its own curve does not reach
        (otherwise the mouth impedance and the two-port chain would describe
        different horns).
        """
        if self.profile != "tractrix" and self.length > 0.0:
            self.rm = float(np.atleast_1d(self.radius(self.length))[0])

    # ------------------------------------------------------------------ helpers
    @property
    def St(self) -> float:
        """Throat area [m^2]."""
        return math.pi * self.rt ** 2

    @property
    def Sm(self) -> float:
        """Mouth area [m^2]."""
        return math.pi * self.rm ** 2

    @property
    def m(self) -> float:
        """Exponential flare constant [1/m]: S = St e^(mx),  m = 4 pi fc / c."""
        return 4.0 * math.pi * self.fc / self.c

    @property
    def x0(self) -> float:
        """Salmon-family scale length [m], x0 = c / (2 pi fc)."""
        return self.c / (2.0 * math.pi * self.fc)

    @property
    def theta0(self) -> float:
        """Half included angle [rad] for the OS / conical families."""
        return math.radians(self.coverage_angle)

    # ------------------------------------------------------------- profile curve
    def radius(self, x: Any) -> np.ndarray:
        """Wall radius [m] as a function of the axial distance x [m] from the throat."""
        x = np.asarray(x, dtype=float)
        if self.profile == "exponential":
            return self.rt * np.exp(self.m * x / 2.0)
        if self.profile == "hyperbolic":
            u = x / self.x0
            return self.rt * (np.cosh(u) + self.T * np.sinh(u))
        if self.profile == "conical":
            x0c = self.rt / math.sqrt(1.0 - math.cos(self.theta0))
            return self.rt * (x + x0c) / x0c
        if self.profile == "os":
            return np.sqrt(self.rt ** 2 + (x * math.tan(self.theta0)) ** 2)
        if self.profile == "tractrix":
            s, y = self._table
            return np.interp(x, s, y)
        raise ValueError(f"unknown profile {self.profile!r}")

    def area(self, x: Any) -> np.ndarray:
        """Cross-sectional area [m^2] at the axial distance x [m]."""
        return math.pi * self.radius(x) ** 2

    # ---------------------------------------------------------------- build size
    @property
    def mouth_width(self) -> float:
        """Mouth width [m] (the wider dimension for a rectangular mouth)."""
        if self.mouth_shape == "rectangular":
            return math.sqrt(math.pi * self.rm ** 2 * self.mouth_aspect)
        return 2.0 * self.rm

    @property
    def mouth_height(self) -> float:
        """Mouth height [m] (the shorter dimension for a rectangular mouth)."""
        if self.mouth_shape == "rectangular":
            return math.sqrt(math.pi * self.rm ** 2 / self.mouth_aspect)
        return 2.0 * self.rm

    def horn_volume_l(self) -> float:
        """Net internal volume of the horn [litres] (what the air inside occupies)."""
        x = np.linspace(0.0, self.length, 401)
        a = self.area(x)
        return float(np.sum(0.5 * (a[1:] + a[:-1]) * np.diff(x))) * 1e3

    @property
    def build_envelope(self) -> tuple:
        """Bounding box of the build [m]: (width, height, depth).

        For a round mouth this is 2*rm x 2*rm x length; for a rectangular mouth it
        is the actual W x H x depth you have to fit somewhere.
        """
        return (self.mouth_width, self.mouth_height, self.length)

    def build_volume_l(self) -> float:
        """Bounding box volume [litres] - the space the finished horn occupies."""
        w, h, d = self.build_envelope
        return w * h * d * 1e3

    # ------------------------------------------------------------ derived report
    def derived(self, f_low: float, krm_target: float) -> dict:
        """Design quantities and the checks the paper recommends."""
        kc = 2.0 * math.pi * self.fc / self.c
        out = {
            "profile": self.profile,
            "throat_radius_mm": self.rt * 1e3,
            "throat_area_cm2": self.St * 1e4,
            "mouth_radius_mm": self.rm * 1e3,
            "mouth_diameter_mm": 2.0 * self.rm * 1e3,
            "mouth_area_cm2": self.Sm * 1e4,
            "area_ratio": self.Sm / self.St,
            "length_mm": self.length * 1e3,
            "fc_hz": self.fc,
            "flare_m_1_per_m": self.m,
            "flare_x0_mm": self.x0 * 1e3,
            "mouth_circumference_mm": 2.0 * math.pi * self.rm * 1e3,
            "lambda_at_fc_mm": self.c / self.fc * 1e3,
            "k_rm_at_fc": kc * self.rm,
            "k_rm_target": krm_target,
            "k_rt_at_fc": kc * self.rt,
            "f_1P_validity_hz": self.c / (2.0 * math.pi * self.rt),
            "mouth_ka_at_f_high": None,   # filled by the caller (needs f_high)
            # what you would actually build
            "mouth_shape": self.mouth_shape,
            "mouth_aspect": self.mouth_aspect,
            "mouth_width_mm": self.mouth_width * 1e3,
            "mouth_height_mm": self.mouth_height * 1e3,
            "build_width_mm": self.mouth_width * 1e3,
            "build_height_mm": self.mouth_height * 1e3,
            "build_depth_mm": self.length * 1e3,
            "build_volume_l": self.build_volume_l(),
            "horn_volume_l": self.horn_volume_l(),
        }
        if self.profile == "hyperbolic":
            out["hyperbolic_T"] = self.T
        return out


# ---------------------------------------------------------------------------
#  geometry solvers: derive the missing length / mouth radius
# ---------------------------------------------------------------------------
def _exponential_length(rt: float, rm: float, fc: float, c: float) -> float:
    m = 4.0 * math.pi * fc / c
    return 2.0 * math.log(rm / rt) / m


def _hyperbolic_length(rt: float, rm: float, fc: float, c: float, T: float) -> float:
    x0 = c / (2.0 * math.pi * fc)
    R = rm / rt
    A = (1.0 + T) / 2.0
    B = (1.0 - T) / 2.0
    disc = R * R - 4.0 * A * B
    if disc < 0.0:
        raise ValueError("hyperbolic profile: mouth radius is below the profile minimum")
    eu = (R + math.sqrt(disc)) / (2.0 * A)
    return x0 * math.log(eu)


def _conical_x0(rt: float, coverage_angle_deg: float) -> float:
    return rt / math.sqrt(1.0 - math.cos(math.radians(coverage_angle_deg)))


def _conical_length(rt: float, rm: float, coverage_angle_deg: float) -> float:
    x0 = _conical_x0(rt, coverage_angle_deg)
    return x0 * (rm / rt - 1.0)


def _os_length(rt: float, rm: float, coverage_angle_deg: float) -> float:
    if rm <= rt:
        raise ValueError("os waveguide: mouth radius must exceed the throat radius")
    return math.sqrt(rm * rm - rt * rt) / math.tan(math.radians(coverage_angle_deg))


def _tractrix_x(y: np.ndarray, a: float) -> np.ndarray:
    """Tractrix curve: x = a*acosh(a/y) - sqrt(a^2-y^2)  (paper Fig. 17/18)."""
    y = np.asarray(y, dtype=float)
    y = np.clip(y, 1e-12, a * (1.0 - 1e-15))
    return a * np.arccosh(a / y) - np.sqrt(a * a - y * y)


def _tractrix_scale(rm: float, tractrix_angle_deg: float) -> float:
    """Tangent length a from the mouth radius and the mouth tangent angle.

    The tangent from a point of the tractrix to the axis has the constant length
    a, and the tangent angle at the radius y obeys sin(theta) = y/a, hence
    a = rm / sin(theta).
    """
    return rm / math.sin(math.radians(tractrix_angle_deg))


def _tractrix_length(rt: float, rm: float, tractrix_angle_deg: float) -> float:
    a = _tractrix_scale(rm, tractrix_angle_deg)
    return float(_tractrix_x(np.array([rt]), a)[0] - _tractrix_x(np.array([rm]), a)[0])


def _tractrix_table(rt: float, rm: float, tractrix_angle_deg: float,
                    n: int = 512) -> tuple:
    """(s, y): distance from the throat [m] -> wall radius [m]."""
    a = _tractrix_scale(rm, tractrix_angle_deg)
    y = np.linspace(rt, rm, n)
    x = _tractrix_x(y, a)
    s = x[0] - x
    return s, y


def _tractrix_rm_for_length(rt: float, length: float, tractrix_angle_deg: float) -> float:
    """Bisection for the mouth radius giving the requested tractrix length."""
    lo = rt * 1.0001
    hi = rt * 4.0
    while _tractrix_length(rt, hi, tractrix_angle_deg) < length:
        hi *= 1.5
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _tractrix_length(rt, mid, tractrix_angle_deg) < length:
            lo = mid
        else:
            hi = mid
        if (hi - lo) < 1e-9:
            break
    return 0.5 * (lo + hi)


def derive_fc(profile: str, rt: float, rm: float, length: float, c: float = C_DEFAULT,
              T: float = 1.0) -> float:
    """Cut-off frequency implied by a given mouth radius and horn length.

    Use this when the shape is fixed first (the intuitive way round: "I want a
    1.2 m mouth and a 0.9 m deep box - what will that do?").  Only the families
    with a flare cut-off have an answer; for conical/OS/tractrix the shape is set
    by the coverage/tangent angle instead.
    """
    if rm <= rt:
        raise ValueError("mouth radius must be larger than the throat radius")
    if profile == "exponential":
        m = 2.0 * math.log(rm / rt) / length           # S = St e^(mx), rm = rt e^(mL/2)
        return m * c / (4.0 * math.pi)
    if profile == "hyperbolic":
        R = rm / rt
        A = (1.0 + T) / 2.0
        B = (1.0 - T) / 2.0
        disc = R * R - 4.0 * A * B
        if disc < 0.0:
            raise ValueError("hyperbolic profile: mouth radius is below the profile minimum")
        x0 = length / math.log((R + math.sqrt(disc)) / (2.0 * A))
        return c / (2.0 * math.pi * x0)
    raise ValueError(
        f"the '{profile}' profile has no cut-off frequency (its flare is set by the "
        "coverage/tangent angle). Give target.fc explicitly, or vary the angle instead."
    )


def size_requirements(rt: float, fcs: list, krms: list, c: float = C_DEFAULT,
                      T: float = 1.0, profile: str = "exponential") -> list:
    """'To reach fc you need at least this big': mouth diameter and length table."""
    rows = []
    for fc in fcs:
        for k in krms:
            rm = k * c / (2.0 * math.pi * fc)
            if profile == "exponential":
                m = 4.0 * math.pi * fc / c
                length = 2.0 * math.log(rm / rt) / m
            elif profile == "hyperbolic":
                length = _hyperbolic_length(rt, rm, fc, c, T)
            elif profile == "conical":
                length = _conical_length(rt, rm, 45.0)
            elif profile == "os":
                length = _os_length(rt, rm, 45.0)
            else:
                length = float("nan")
            rows.append({
                "fc_hz": fc,
                "k_rm": k,
                "mouth_diameter_mm": 2.0 * rm * 1e3,
                "length_mm": length * 1e3,
                "bounding_volume_l": (2.0 * rm) ** 2 * length * 1e3,
            })
    return rows


def solve_design(horn, target, c: float = C_DEFAULT, rho: float = RHO_DEFAULT) -> Design:
    """Resolve a Horn config + Target into a complete Design (SI units).

    Rules (see README): at most one of horn.length / horn.mouth_radius may be
    'auto'.  The requested mouth radius normally follows the paper's criterion
    k*rm = target.krm_target at the cut-off frequency: rm = krm*c/(2*pi*fc).
    """
    rt = horn.throat_diameter / 2.0
    length = horn.length
    rm = horn.mouth_radius
    if horn.mouth_area is not None:
        rm = math.sqrt(horn.mouth_area / math.pi)      # equal-area circle
    warn: list[str] = []
    notes: list[str] = []

    fc = target.fc
    if fc is None:
        # shape first: the mouth radius and the length decide the flare cut-off
        if rm is None or length is None:
            raise ValueError(
                "target.fc is 'auto': give both horn.mouth_radius and horn.length so the "
                "flare can be derived (or set target.fc explicitly)"
            )
        fc = derive_fc(horn.profile, rt, rm, length, c, horn.T)
        notes.append(f"target.fc = auto -> derived from the mouth radius "
                     f"{rm * 1e3:.0f} mm and the length {length * 1e3:.0f} mm: fc = {fc:.1f} Hz")

    rm_target = target.krm_target * c / (2.0 * math.pi * fc)
    if rm is None:
        rm = rm_target

    if length is None:
        if horn.profile == "exponential":
            length = _exponential_length(rt, rm, fc, c)
        elif horn.profile == "hyperbolic":
            length = _hyperbolic_length(rt, rm, fc, c, horn.T)
        elif horn.profile == "conical":
            length = _conical_length(rt, rm, horn.coverage_angle)
        elif horn.profile == "os":
            length = _os_length(rt, rm, horn.coverage_angle)
        elif horn.profile == "tractrix":
            length = _tractrix_length(rt, rm, horn.tractrix_angle)
        else:  # pragma: no cover - config validation prevents this
            raise ValueError(f"unknown profile {horn.profile!r}")
    elif rm is None:
        # the geometry decides the mouth size
        if horn.profile == "exponential":
            rm = rt * math.exp(fc * 2.0 * math.pi / c * length)
        elif horn.profile == "hyperbolic":
            u = length / (c / (2.0 * math.pi * fc))
            rm = rt * (math.cosh(u) + horn.T * math.sinh(u))
        elif horn.profile == "conical":
            rm = rt * (1.0 + length / _conical_x0(rt, horn.coverage_angle))
        elif horn.profile == "os":
            rm = math.sqrt(rt ** 2 + (length * math.tan(math.radians(horn.coverage_angle))) ** 2)
        elif horn.profile == "tractrix":
            rm = _tractrix_rm_for_length(rt, length, horn.tractrix_angle)
    else:
        # both given: verify that they belong to the same profile curve
        if horn.profile == "exponential":
            required = _exponential_length(rt, rm, fc, c)
        elif horn.profile == "hyperbolic":
            required = _hyperbolic_length(rt, rm, fc, c, horn.T)
        elif horn.profile == "conical":
            required = _conical_length(rt, rm, horn.coverage_angle)
        elif horn.profile == "os":
            required = _os_length(rt, rm, horn.coverage_angle)
        else:
            required = _tractrix_length(rt, rm, horn.tractrix_angle)
        if abs(required - length) > 0.02 * max(required, length):
            warn.append(
                f"horn.length = {length * 1e3:.0f} mm does not match the profile "
                f"({horn.profile} needs {required * 1e3:.0f} mm for rm = {rm * 1e3:.0f} mm)"
            )

    design = Design(profile=horn.profile, rt=rt, length=length, rm=rm, fc=fc,
                    c=c, rho=rho, T=horn.T, coverage_angle=horn.coverage_angle,
                    tractrix_angle=horn.tractrix_angle, mouth_shape=horn.mouth_shape,
                    mouth_aspect=(horn.mouth_aspect if horn.mouth_shape == "rectangular"
                                  else 1.0))
    if horn.profile == "tractrix":
        design._table = _tractrix_table(rt, rm, horn.tractrix_angle)
    design.warnings = warn
    design.notes = notes
    return design


# ---------------------------------------------------------------------------
#  throat impedance
# ---------------------------------------------------------------------------
def infinite_throat_impedance(design: Design, f) -> np.ndarray | None:
    """Analytic throat impedance of an *infinite* horn where the paper gives one.

    Returns None for the families for which the paper only presents the general
    (numerical) treatment - use finite_throat_impedance() for those.
    """
    f = np.asarray(f, dtype=float)
    k = k_of(f, design.c)
    rc = design.rho * design.c
    if design.profile == "exponential":
        # Eq. (9):  Z = (rho c / St) ( sqrt(1-(a/k)^2) + j a/k ),  a = m/2 = 2 pi fc/c
        alpha = 2.0 * math.pi * design.fc / design.c
        x = alpha / k
        below = x > 1.0
        root = np.sqrt(np.maximum(1.0 - x ** 2, 0.0)).astype(complex)
        root = np.where(below, -1j * np.sqrt(np.maximum(x ** 2 - 1.0, 0.0)), root)
        return rc / design.St * (root + 1j * x)
    if design.profile == "conical":
        # Eq. (7)
        x0 = _conical_x0(design.rt, design.coverage_angle)
        kx = k * x0
        return rc / design.St * (kx ** 2 + 1j * kx) / (1.0 + kx ** 2)
    return None


def mouth_impedance(termination: str, rm: float, f, c: float = C_DEFAULT,
                    rho: float = RHO_DEFAULT) -> np.ndarray:
    """Acoustic impedance [Pa*s/m^3] seen by the mouth (paper 'Termination')."""
    f = np.asarray(f, dtype=float)
    k = k_of(f, c)
    ka = k * rm
    rc = rho * c
    S = math.pi * rm ** 2
    if termination == "infinite_pipe":
        return np.full(f.shape, rc / S, dtype=complex)
    if termination == "piston_infinite_baffle":
        x = 2.0 * ka
        safe = np.where(np.abs(x) < 1e-12, 1e-12, x)
        R1 = 1.0 - 2.0 * special.j1(safe) / safe
        X1 = 2.0 * special.struve(1, safe) / safe
        return rc / S * (R1 + 1j * X1)
    if termination == "sphere":
        # pulsating sphere of radius rm (paper Figs. 7/19/23 mouth terminations)
        ka2 = ka ** 2
        return rc / (4.0 * math.pi * rm ** 2) * (ka2 + 1j * ka) / (1.0 + ka2)
    raise ValueError(f"unknown mouth termination {termination!r}")


# ---------------------------------------------------------------------------
#  finite horn: segmented two-port model (paper Eqs. 14-16)
# ---------------------------------------------------------------------------
def _segment_abcd(f, S1: float, S2: float, length: float, c: float, rho: float) -> tuple:
    """Stress/velocity two-port of one conical (frustum) segment.

    [p_in, U_in]^T = M [p_out, U_out]^T with U the volume velocity.
    p(x) = (A e^-jkx + B e^+jkx)/x and U = (Omega/(j w rho)) *
    (j k x (A e^-jkx - B e^+jkx) + (A e^-jkx + B e^+jkx)), x measured from the
    cone apex (paper: a, b, f, g in Eqs. 14-16, Stewart's expressions).
    """
    f = np.asarray(f, dtype=float)
    k = k_of(f, c)
    w = 2.0 * np.pi * f
    r1 = math.sqrt(S1 / math.pi)
    r2 = math.sqrt(S2 / math.pi)
    slope = (r2 - r1) / length
    if abs(slope) * length < 1e-9 * max(r1, 1e-12):
        Z0 = rho * c / S1
        cos = np.cos(k * length) + 0j
        return (cos, 1j * Z0 * np.sin(k * length),
                1j * np.sin(k * length) / Z0, cos)

    x1 = r1 / slope          # distance from the apex to the input plane
    x2 = r2 / slope          # ... and to the output plane (= x1 + length)
    om = S1 / x1 ** 2        # local solid angle, S = Omega x^2

    def mat(x):
        e = np.exp(-1j * k * x)
        g = np.exp(1j * k * x)
        coef = om / (1j * w * rho)
        return (e / x, g / x,
                coef * (1j * k * x * e + e), coef * (-1j * k * x * g + g))

    m1 = mat(x1)
    m2 = mat(x2)
    det = m2[0] * m2[3] - m2[1] * m2[2]
    inv = (m2[3] / det, -m2[1] / det, -m2[2] / det, m2[0] / det)
    return (m1[0] * inv[0] + m1[1] * inv[2], m1[0] * inv[1] + m1[1] * inv[3],
            m1[2] * inv[0] + m1[3] * inv[2], m1[2] * inv[1] + m1[3] * inv[3])


def analytic_local_impedance(design: Design, x_mouth: float, f) -> np.ndarray | None:
    """Local (outgoing-wave) impedance at a given profile position, Eqs. (7)/(9).

    Terminating the segmented two-port line with this impedance is
    reflection-free, which makes the numeric model directly comparable with the
    analytic *infinite* horn result.  Only defined where the paper gives a closed
    form (exponential and conical).
    """
    f = np.asarray(f, dtype=float)
    k = k_of(f, design.c)
    rc = design.rho * design.c
    s_local = math.pi * float(design.radius(x_mouth)) ** 2
    if design.profile == "exponential":
        alpha = 2.0 * math.pi * design.fc / design.c
        xx = alpha / k
        root = np.sqrt(np.maximum(1.0 - xx ** 2, 0.0)).astype(complex)
        root = np.where(xx > 1.0, -1j * np.sqrt(np.maximum(xx ** 2 - 1.0, 0.0)), root)
        return rc / s_local * (root + 1j * xx)
    if design.profile == "conical":
        x0 = _conical_x0(design.rt, design.coverage_angle)
        # move the apex distance with the local position so that S(x) matches
        kx = k * (x0 + x_mouth)
        return rc / s_local * (kx ** 2 + 1j * kx) / (1.0 + kx ** 2)
    return None


def horn_abcd(design: Design, f, n_segments: int = 200) -> tuple:
    """Two-port chain of the whole horn: [p_throat, U_throat] = M [p_mouth, U_mouth]."""
    f = np.asarray(f, dtype=float)
    n = int(n_segments)
    xs = np.linspace(0.0, design.length, n + 1)
    areas = design.area(xs)
    A = np.ones_like(f, dtype=complex)
    B = np.zeros_like(f, dtype=complex)
    C = np.zeros_like(f, dtype=complex)
    D = np.ones_like(f, dtype=complex)
    dx = design.length / n
    for i in range(n):
        a, b, cc, dd = _segment_abcd(f, float(areas[i]), float(areas[i + 1]), dx,
                                     design.c, design.rho)
        A, B, C, D = (A * a + B * cc, A * b + B * dd, C * a + D * cc, C * b + D * dd)
    return A, B, C, D


def finite_throat_impedance(design: Design, f, termination: str = "piston_infinite_baffle",
                            n_segments: int = 200, zm=None) -> np.ndarray:
    """Throat impedance of the finite horn, Eq. (16): Zt = (g Zm - b)/(a - f Zm).

    ``zm`` overrides the built-in mouth terminations (used for the reflection-free
    analytic reference, see analytic_local_impedance()).
    """
    A, B, C, D = horn_abcd(design, f, n_segments)
    if zm is None:
        zm = mouth_impedance(termination, design.rm, f, design.c, design.rho)
    return (A * zm + B) / (C * zm + D)


def mouth_volume_velocity(design: Design, f, U_throat, termination: str = "piston_infinite_baffle",
                          n_segments: int = 200, zm=None) -> np.ndarray:
    """Volume velocity at the mouth for a given throat volume velocity."""
    A, B, C, D = horn_abcd(design, f, n_segments)
    if zm is None:
        zm = mouth_impedance(termination, design.rm, f, design.c, design.rho)
    return np.asarray(U_throat) / (C * zm + D)


# ---------------------------------------------------------------------------
#  directivity helpers (Part 2)
# ---------------------------------------------------------------------------
def coverage_q(alpha_deg: float, beta_deg: float) -> float:
    """Q from the coverage angles, paper Eq. (25): Q = 180^2/(alpha*beta)."""
    return 180.0 ** 2 / (alpha_deg * beta_deg)


def intercept_frequency(mouth_size_mm: float, coverage_deg: float) -> float:
    """Frequency below which a horn loses directivity control, Eq. (26)."""
    return 25.0e6 / (mouth_size_mm * coverage_deg)


def piston_q(ka, half_space: bool = True) -> np.ndarray:
    """Directivity factor of a piston in an infinite baffle (mouth radiation).

    Q = (ka)^2 / (1 - J1(2ka)/ka);  Q -> 2 for ka -> 0 (half space), Q ~ (ka)^2
    for large ka (see the DI discussion in Part 2).
    """
    ka = np.atleast_1d(np.asarray(ka, dtype=float))
    safe = np.maximum(ka, 1e-12)
    zr = 1.0 - special.j1(2.0 * safe) / safe
    q = safe ** 2 / np.maximum(zr, 1e-12)
    return np.maximum(q, 2.0 if half_space else 1.0)


def piston_di(ka, half_space: bool = True) -> np.ndarray:
    """Directivity index [dB] of the mouth radiation."""
    return 10.0 * np.log10(piston_q(ka, half_space))
