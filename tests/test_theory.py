"""Stage 1 checks: every number asserted here comes from the paper or from theory.

Run with either
    python tests/test_theory.py          (standalone, prints PASS/FAIL)
    python -m pytest tests/test_theory.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hornflow import advise, bem, build, config, mesh, response, theory   # noqa: E402
from hornflow.config import Driver, Horn, Simulation, Target   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  PASS  {name}" + (f"   [{detail}]" if detail else ""))
    else:
        print(f"  FAIL  {name}" + (f"   [{detail}]" if detail else ""))
        FAILURES.append(name)


def close(a: float, b: float, rel: float = 1e-6) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-30)


def make(profile: str, **kw) -> tuple:
    throat_diameter = kw.pop("throat_diameter", 0.0508)
    length = kw.pop("length", None)
    mouth_radius = kw.pop("mouth_radius", None)
    fc = kw.pop("fc", 80.0)
    horn = Horn(profile=profile, throat_diameter=throat_diameter, length=length,
                mouth_radius=mouth_radius, **kw)
    target = Target(f_low=80.0, f_high=250.0, fc=fc, krm_target=0.9)
    return horn, target


def test_os_cutoff():
    """Paper Part 2, Eq. (24): a 1" throat and 60 deg included angle -> ~862 Hz."""
    rt = 0.0127
    theta0 = 30.0
    fc = (0.2 * 343.0 * math.sin(math.radians(theta0))) / (math.pi * rt)
    check("OS waveguide cut-off (paper: 862 Hz)", abs(fc - 862.0) < 3.0, f"fc = {fc:.1f} Hz")
    # the same formula written against f_low must scale linearly with rt
    fc2 = (0.2 * 343.0 * math.sin(math.radians(theta0))) / (math.pi * 2 * rt)
    check("OS cut-off halves when the throat radius doubles", close(fc2, fc / 2, 1e-9))


def test_exponential_flare():
    """Part 1: S = St e^(mx) with m = 4*pi*fc/c."""
    horn, target = make("exponential", throat_diameter=0.0508, fc=80.0)
    design = theory.solve_design(horn, target)
    m = 4.0 * math.pi * 80.0 / 343.0
    check("exponential flare constant m = 4 pi fc / c", close(design.m, m, 1e-12),
          f"m = {design.m:.6f} 1/m")
    check("area doubles per ln(2)/m of length",
          close(float(design.area(math.log(2.0) / m)) / design.St, 2.0, 1e-9))
    # auto mouth radius follows the paper's k*rm criterion
    rm_expected = 0.9 * 343.0 / (2 * math.pi * 80.0)
    design2 = theory.solve_design(Horn(profile="exponential", throat_diameter=0.0508,
                                       length=None, mouth_radius=None), target)
    check("mouth radius set by k*rm = 0.9", close(design2.rm, rm_expected, 1e-12),
          f"rm = {design2.rm * 1e3:.1f} mm")
    # length consistency: radius(length) must equal the mouth radius
    check("radius(length) == mouth radius", close(float(design2.radius(design2.length)),
                                                 design2.rm, 1e-9))


def test_hyperbolic_equals_exponential():
    """Salmon family with T = 1 is the exponential horn."""
    h1, t = make("hyperbolic", throat_diameter=0.0508, fc=80.0, T=1.0)
    h2, _ = make("exponential", throat_diameter=0.0508, fc=80.0)
    d1 = theory.solve_design(h1, t)
    d2 = theory.solve_design(h2, t)
    xs = np.linspace(0.0, min(d1.length, d2.length), 50)
    err = np.max(np.abs(d1.radius(xs) - d2.radius(xs)) / d2.radius(xs))
    check("hyperbolic T=1 == exponential profile", err < 1e-9, f"max rel err {err:.2e}")
    check("hyperbolic T=1 == exponential length", close(d1.length, d2.length, 1e-9),
          f"{d1.length * 1e3:.1f} mm vs {d2.length * 1e3:.1f} mm")


def test_profiles_reach_the_mouth():
    for profile in ("exponential", "hyperbolic", "conical", "os", "tractrix"):
        horn, target = make(profile, throat_diameter=0.0508, fc=80.0)
        d = theory.solve_design(horn, target)
        r0 = float(d.radius(0.0))
        rl = float(d.radius(d.length))
        ok = close(r0, d.rt, 1e-6) and close(rl, d.rm, 2e-3)
        check(f"{profile}: r(0)=rt and r(L)=rm", ok,
              f"r0={r0 * 1e3:.2f} rL={rl * 1e3:.2f} rm={d.rm * 1e3:.2f} mm")
        check(f"{profile}: area(0) = throat area", close(float(d.area(0.0)), d.St, 1e-6))


def test_numeric_matches_analytic():
    """Segmented two-port line + reflection-free mouth == paper Eqs. (7)/(9)."""
    for profile in ("exponential", "conical"):
        horn, target = make(profile, throat_diameter=0.0508, fc=80.0)
        d = theory.solve_design(horn, target)
        f = np.array([100.0, 200.0, 400.0, 800.0, 1600.0])
        zm = theory.analytic_local_impedance(d, d.length, f)
        num = theory.finite_throat_impedance(d, f, n_segments=400, zm=zm)
        ana = theory.infinite_throat_impedance(d, f)
        rel = float(np.max(np.abs(num - ana) / np.abs(ana)))
        check(f"{profile}: matched numeric line == analytic infinite horn", rel < 0.02,
              f"max rel err {rel * 100:.2f}%")


def test_mouth_impedance_laws():
    f = np.array([50.0, 100.0, 1000.0])
    rm = 0.5
    zp = theory.mouth_impedance("infinite_pipe", rm, f)
    check("infinite pipe: Z = rho c / S",
          np.allclose(np.abs(zp), 1.205 * 343.0 / (math.pi * rm ** 2), rtol=1e-12))
    # piston in an infinite baffle: R -> 1 and X -> 0 for ka >> 1
    rm_norm = 1.205 * 343.0 / (math.pi * rm ** 2)
    f10 = np.array([10.0 * 343.0 / (2 * math.pi * rm)])
    z_p = theory.mouth_impedance("piston_infinite_baffle", rm, f10) / rm_norm
    check("baffled piston: R -> 1 for ka >> 1", abs(z_p.real[0] - 1.0) < 0.02,
          f"R = {z_p.real[0]:.4f}")
    check("baffled piston: X -> 0 for ka >> 1", abs(z_p.imag[0]) < 0.05,
          f"X = {z_p.imag[0]:.4f}")
    # pulsating sphere: resistance grows as (ka)^2 for ka << 1
    z_s = theory.mouth_impedance("sphere", rm, np.array([1.0, 2.0])).real
    check("pulsating sphere: R ~ (ka)^2 for ka << 1", close(z_s[1] / z_s[0], 4.0, 0.02),
          f"ratio {z_s[1] / z_s[0]:.4f}")


def test_finite_horn_behaviour():
    """Paper Fig. 6 / Fig. 10: longer horns ripple less, big mouths load better."""
    d_short = theory.Design(profile="exponential", rt=0.0254, length=1.0, rm=0.6, fc=80.0)
    d_long = theory.Design(profile="exponential", rt=0.0254, length=2.0, rm=0.6, fc=80.0)
    f = np.linspace(100.0, 400.0, 60)

    def ripple(a: np.ndarray) -> float:
        return float(np.max(a) - np.min(a)) / float(np.mean(a))

    r_short = ripple(theory.finite_throat_impedance(d_short, f).real)
    r_long = ripple(theory.finite_throat_impedance(d_long, f).real)
    check("longer exponential horn ripples less (paper Fig. 6)", r_long < r_short,
          f"short {r_short:.3f} -> long {r_long:.3f}")
    for term in ("infinite_pipe", "piston_infinite_baffle", "sphere"):
        z = theory.finite_throat_impedance(d_long, f, termination=term)
        check(f"passive {term}: Re(Zt) >= 0", bool(np.all(z.real >= -1e-9)),
              f"min Re = {z.real.min():.3e}")
    # large mouth (ka >> 1) -> the throat resistance approaches rho c / St
    d_big = theory.Design(profile="exponential", rt=0.0254, length=1.0, rm=0.6, fc=80.0)
    rc_st = 1.205 * 343.0 / d_big.St
    z_hi = theory.finite_throat_impedance(d_big, np.array([5000.0]))[0]
    z_lo = theory.finite_throat_impedance(d_big, np.array([1000.0]))[0]
    check("mouth radius follows the profile curve", close(d_big.rm, 0.1099, 2e-3),
          f"rm = {d_big.rm * 1e3:.1f} mm at x = 1000 mm")
    check("large ka mouth: Re(Zt) -> rho c / St", abs(z_hi.real / rc_st - 1.0) < 0.1,
          f"Re(Zt)/(rho c/St) = {z_hi.real / rc_st:.3f} at 5 kHz (ka = "
          f"{2 * math.pi * 5000 / 343 * d_big.rm:.1f})")
    check("matching improves with frequency", abs(z_hi.real / rc_st - 1.0)
          < abs(z_lo.real / rc_st - 1.0),
          f"1 kHz {z_lo.real / rc_st:.3f} -> 5 kHz {z_hi.real / rc_st:.3f}")


def test_directivity_helpers():
    check("Q from coverage angles, Eq. (25)", close(theory.coverage_q(90.0, 90.0), 4.0, 1e-12),
          "90 x 90 deg -> Q = 4 (the paper's example)")
    f_i = theory.intercept_frequency(1000.0, 90.0)
    check("directivity intercept, Eq. (26)", close(f_i, 25e6 / (1000.0 * 90.0), 1e-12),
          f"{f_i:.1f} Hz for a 1000 mm mouth at 90 deg")
    q_small = float(theory.piston_q(np.array([1e-6]), half_space=True)[0])
    check("piston Q -> 2 (half space) for ka -> 0", close(q_small, 2.0, 1e-4), f"{q_small:.6f}")
    q_big = float(theory.piston_q(np.array([10.0]), half_space=True)[0])
    check("piston Q ~ (ka)^2 for ka >> 1", 0.8 < q_big / 100.0 < 1.2, f"Q(ka=10) = {q_big:.1f}")


def test_driver_electrical():
    """The motional impedance peaks exactly at the driver resonance."""
    drv = config._build_driver({"name": "t", "dD": 380.0, "Mms": 65.0, "Cms": 2.5e-4,
                                "Rms": 4.0, "Bl": 17.0, "Re": 6.0, "Le": 1.2})
    f = np.linspace(10.0, 200.0, 4001)
    w = 2 * np.pi * f
    zm = drv.Rms + 1j * w * drv.Mms + 1.0 / (1j * w * drv.Cms)
    f_peak = f[int(np.argmax(np.abs(drv.Bl ** 2 / zm)))]
    check("motional impedance peaks at fs", abs(f_peak - drv.fs) < 0.5,
          f"peak {f_peak:.2f} Hz vs fs {drv.fs:.2f} Hz")
    check("Sd follows from dD", close(drv.Sd, math.pi * 0.380 ** 2 / 4, 1e-12),
          f"Sd = {drv.Sd * 1e4:.1f} cm^2")


def test_voice_coil_model():
    """AKABAK voice-coil model: Re(f) = Re(1+f/fre)^ExpoRe, Xe = w Le r(q)."""
    drv = config._build_driver({"name": "t", "dD": 380.0, "Mms": 65.0, "Cms": 2.5e-4,
                                "Rms": 4.0, "Bl": 17.0, "Re": 6.0, "Le": 1.2,
                                "fre": 10.0, "ExpoRe": 1.0, "ExpoLe": 1.0})
    f = np.array([1e-9, 100.0, 1000.0, 20000.0])
    z = response.voice_coil_impedance(drv, f)
    check("Re(f) -> Re at DC", abs(z.real[0] - drv.Re) < 1e-6, f"Re = {z.real[0]:.4f} ohm")
    check("Re(f) rises with frequency", z.real[3] > z.real[2] > z.real[1] > z.real[0],
          f"{z.real[1]:.2f} -> {z.real[3]:.2f} ohm at 20 kHz")
    check("ExpoLe = 1 gives a pure inductance Xe = w Le",
          close(z.imag[2], 2 * math.pi * 1000.0 * drv.Le, 1e-9),
          f"Xe(1 kHz) = {z.imag[2]:.3f} ohm")
    # the motional branch is passive -> |Ze| can never fall below Re(f)
    path = Path(__file__).resolve().parents[1] / "params" / "horn_80_250Hz.yaml"
    params = config.load(path)
    r = response.simulate(params)
    re_f = response.voice_coil_impedance(params.driver, r.f).real
    check("|Ze| >= Re(f) everywhere (passive motional branch)",
          bool(np.all(np.abs(r.Ze) >= re_f - 1e-9)),
          f"min margin {float(np.min(np.abs(r.Ze) - re_f)):.3e} ohm")


def test_simulation_and_project_file():
    """End-to-end run of the shipped definition file + linearity checks."""
    path = Path(__file__).resolve().parents[1] / "params" / "horn_80_250Hz.yaml"
    params = config.load(path)
    r1 = response.simulate(params)
    params2 = config.load(path)
    params2.simulation.voltage = 2.0 * params.simulation.voltage
    r2 = response.simulate(params2)
    delta = float(np.max(np.abs((r2.spl - r1.spl) - 20 * math.log10(2.0))))
    check("SPL scales +6 dB per doubling of voltage", delta < 1e-6, f"max dev {delta:.2e} dB")
    check("impedance is independent of the drive level", bool(np.allclose(r1.Ze, r2.Ze, rtol=1e-12)))
    check("all curves share the frequency grid",
          len(r1.f) == len(r1.Ze) == len(r1.spl) == len(r1.excursion) == len(r1.Zt))
    d = r1.derived
    kc = 2 * math.pi * d["fc_hz"] / params.simulation.c
    check("k*rm reported at fc", close(d["k_rm_at_fc"], kc * r1.design.rm, 1e-12),
          f"k*rm = {d['k_rm_at_fc']:.3f}")
    check("mouth circumference = 2 pi rm",
          close(d["mouth_circumference_mm"], 2 * math.pi * d["mouth_radius_mm"], 1e-9))
    check("area ratio = Sm / St", close(d["area_ratio"], r1.design.Sm / r1.design.St, 1e-9),
          f"{d['area_ratio']:.1f}")
    check("k*rt at fc from the throat radius", close(d["k_rt_at_fc"], kc * r1.design.rt, 1e-12))
    check("excursion is finite and non-zero",
          bool(np.all(np.isfinite(r1.excursion))) and float(np.max(np.abs(r1.excursion))) > 0)


def test_mouth_area_and_rectangle():
    """mouth_area = equal-area circle; a rectangular mouth keeps that area."""
    horn = Horn(profile="exponential", throat_diameter=0.260, length=None, mouth_radius=None,
                mouth_area=0.16, mouth_shape="rectangular", mouth_aspect=1.6)
    target = Target(f_low=60.0, f_high=200.0, fc=62.0, krm_target=0.81)
    d = theory.solve_design(horn, target)
    check("mouth_area -> equal-area radius", close(d.rm, math.sqrt(0.16 / math.pi), 2e-3),
          f"rm = {d.rm * 1e3:.1f} mm")
    check("rectangle keeps the mouth area",
          close(d.mouth_width * d.mouth_height, 0.16, 1e-3),
          f"{d.mouth_width * 1e3:.0f} x {d.mouth_height * 1e3:.0f} mm")
    check("rectangle aspect = width / height", close(d.mouth_width / d.mouth_height, 1.6, 1e-3))
    check("envelope uses width x height x depth",
          close(d.build_volume_l(), d.mouth_width * d.mouth_height * d.length * 1e3, 1e-3),
          f"{d.build_volume_l():.1f} l")
    check("length remains consistent with the mouth area",
          close(float(d.radius(d.length)), d.rm, 1e-9))


def test_driver_file_include():
    """driver: <name>.yaml pulls the driver block out of a separate file."""
    path = Path(__file__).resolve().parents[1] / "params" / "horn_jbl_1200b.yaml"
    if not path.is_file():
        return
    params = config.load(path)
    check("driver loaded from its own file", params.driver.name == "jbl_1200b",
          f"name = {params.driver.name}")
    check("rear chamber from the driver file", close(params.driver.rear_volume, 0.028, 1e-9),
          f"Vb = {params.driver.rear_volume * 1e6:.0f} cm^3")
    check("locked design: mouth 1.60 m2 rectangular", params.horn.mouth_shape == "rectangular"
          and close(params.horn.mouth_area, 1.60, 1e-9),
          f"area = {params.horn.mouth_area:.3f} m^2")


def test_advise_relations():
    """The closed forms the advice engine solves."""
    rt, c = 0.130, 343.0
    # k*rm at a given depth, and the depth that reaches a given k*rm: round trip
    for fc in (59.0, 62.0, 80.0):
        for k in (0.7, 0.81, 1.0):
            L = advise.depth_for(fc, rt, k, c)
            check(f"depth/statement round trip fc={fc:.0f} k={k:.2f}",
                  close(advise.k_rm_at_depth(fc, rt, L, c), k, 1e-9),
                  f"L = {L * 1e3:.0f} mm")
    floor = advise.floor_fc(rt, 1.5, 0.7, c)
    check("62 Hz design matches the adviseed depth for k*rm 0.81",
          close(advise.depth_for(62.0, rt, 0.81, c), 1.499, 4e-3),
          f"{advise.depth_for(62.0, rt, 0.81, c) * 1e3:.0f} mm")
    check("floor cut-off for 1500 mm at k*rm 0.7 is about 59 Hz", 58.0 < floor < 60.0,
          f"{floor:.1f} Hz")
    check("mouth radius for a cut-off and criterion", close(
        advise.mouth_radius_for(62.0, 0.81, c), 0.81 * c / (2 * math.pi * 62.0), 1e-12))
    w, h = advise.rectangle(1.6, 1.6)
    check("rectangle widths", close(w * h, 1.6, 1e-12) and close(w / h, 1.6, 1e-12))


def polygon_area(o: np.ndarray) -> float:
    x, y = o[:, 0], o[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _tmp() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="hornflow_test_"))


def locked_design():
    params = config.load(ROOT / "params" / "horn_jbl_1200b.yaml")
    return params, response.simulate(params)


def test_mesh_sections():
    """Every cross section keeps the round horn's area; the mouth outline is the design's."""
    params, r = locked_design()
    d = r.design
    for z in (0.0, 0.25 * d.length, 0.5 * d.length, 0.75 * d.length, d.length):
        o = mesh.section_outline(d, z, 720)
        want = math.pi * float(np.atleast_1d(d.radius(z))[0]) ** 2
        check(f"section area at z = {z * 1e3:.0f} mm equals the round horn's area",
              abs(polygon_area(o) - want) / want < 5e-3,
              f"{polygon_area(o) * 1e4:.1f} vs {want * 1e4:.1f} cm^2")
    o0 = mesh.section_outline(d, 0.0, 720)
    check("throat section is a circle of radius rt",
          close(float(np.abs(o0[:, 0]).max()), d.rt, 1e-3) and
          close(float(np.abs(o0[:, 1]).max()), d.rt, 1e-3),
          f"{2 * float(np.abs(o0[:, 0]).max()) * 1e3:.0f} mm across")
    # a round-mouth horn must stay round; a rectangular one must become a rectangle
    horn = Horn(profile="exponential", throat_diameter=0.300, length=None, mouth_radius=None,
                mouth_area=1.131, mouth_shape="round")
    round_design = theory.solve_design(
        horn, Target(f_low=80.0, f_high=250.0, fc=84.0, krm_target=0.9))
    oround = mesh.section_outline(round_design, round_design.length, 360)
    check("round mouth stays circular in the build geometry",
          close(float(np.abs(oround[:, 0]).max()), float(np.abs(oround[:, 1]).max()), 1e-9) and
          close(float(np.abs(oround[:, 0]).max()), round_design.rm, 1e-9) and
          abs(polygon_area(oround) - math.pi * round_design.rm ** 2) /
          (math.pi * round_design.rm ** 2) < 1e-3,
          f"{2 * float(np.abs(oround[:, 0]).max()) * 1e3:.0f} mm dia vs rm = "
          f"{2 * round_design.rm * 1e3:.0f} mm")
    # the superellipse area formula itself: A = 4ab Gamma(1+1/p)^2 / Gamma(1+2/p)
    for p in (2.0, 3.0, 5.0):
        a, b = mesh.superellipse_axes(1.0, 1.6, p)
        k = math.exp(2 * math.lgamma(1 + 1 / p) - math.lgamma(1 + 2 / p))
        check(f"superellipse area formula p = {p:.0f}", close(4 * a * b * k, 1.0, 1e-12),
              f"a = {a * 1e3:.1f} mm, b = {b * 1e3:.1f} mm")


def test_mesh_groups():
    """The BEM mesh closes the throat and the mouth and matches the design dimensions."""
    params, r = locked_design()
    d = r.design
    sug = mesh.suggest_mesh(d, 500.0, params.simulation.c)
    check("mesh suggestion keeps the element at lambda/6",
          close(sug["element_size_mm"], 343.0 / 500.0 / 6 * 1e3, 1e-9),
          f"{sug['element_size_mm']:.0f} mm at 500 Hz")
    m = mesh.horn_mesh(d, sug["n_around"], sug["n_stations"], baffle_margin=0.4)
    areas = m.area_by_group()
    check("source disk area equals the throat area",
          abs(areas["source"] - d.St) / d.St < 0.01,
          f"{areas['source'] * 1e4:.1f} vs {d.St * 1e4:.1f} cm^2")
    check("mouth plane area equals the mouth area",
          abs(areas["interface"] - d.Sm) / d.Sm < 0.02,
          f"{areas['interface'] * 1e4:.0f} vs {d.Sm * 1e4:.0f} cm^2")
    lo, hi = m.bounds()
    check("mesh depth equals the horn length", close(hi[2] - lo[2], d.length, 1e-9),
          f"{(hi[2] - lo[2]) * 1e3:.0f} mm")
    check("mesh mouth height equals the design's", hi[1] - lo[1] >= d.mouth_height - 1e-3,
          f"{(hi[1] - lo[1]) * 1e3:.0f} mm")
    check("every triangle is tagged", len(m.tris) == sum(m.count(n) for n in m.physical.values()),
          f"{len(m.tris)} triangles")


def test_mesh_symmetry():
    """A half/quarter mesh: same tags, exactly the fraction of every area, nothing across."""
    params, r = locked_design()
    d = r.design
    sug = mesh.suggest_mesh(d, 500.0, params.simulation.c)
    full = mesh.horn_mesh(d, sug["n_around"], sug["n_stations"], baffle_margin=0.0)
    af = full.area_by_group()
    for sym, frac, axes in (("x", 0.5, (0,)), ("y", 0.5, (1,)), ("xy", 0.25, (0, 1))):
        m = mesh.horn_mesh(d, sug["n_around"], sug["n_stations"], symmetry=sym)
        areas = m.area_by_group()
        check(f"symmetry {sym}: group names and tags survive",
              m.physical == full.physical, str(m.physical))
        check(f"symmetry {sym}: every area is the sector fraction (to the "
              "polygonisation error)",
              all(abs(areas[g] / af[g] - frac) < 0.005 for g in af),
              ", ".join(f"{g}={areas[g] / af[g]:.4f}" for g in sorted(af)))
        pts = np.asarray(m.nodes)
        check(f"symmetry {sym}: no node crosses the plane(s) of symmetry",
              all(pts[:, a].min() > -1e-12 for a in axes),
              f"min x={pts[:, 0].min():.2e}, min y={pts[:, 1].min():.2e}")
        check(f"symmetry {sym}: depths unchanged (mouth still at the horn length)",
              close(max(n[2] for n in m.nodes), d.length, 1e-12),
              f"{max(n[2] for n in m.nodes) * 1e3:.1f} mm")
    m = mesh.horn_mesh(d, sug["n_around"], sug["n_stations"], symmetry="xy")
    check("a quarter mesh has about a quarter of the triangles",
          abs(len(m.tris) / len(full.tris) - 0.25) < 0.02,
          f"{len(m.tris)} vs {len(full.tris)}")
    check("the mesh records which symmetry it was built for", m.meta["symmetry"] == "xy",
          str(m.meta["symmetry"]))
    try:
        mesh.horn_mesh(d, 8, 2, baffle_margin=0.4, symmetry="xy")
        check("baffle ring plus symmetry is refused", False, "no error raised")
    except ValueError:
        check("baffle ring plus symmetry is refused", True, "ValueError")


def test_bem_symmetry_files():
    """Stage 2 with --bem-symmetry writes the cut mesh and documents the switch."""
    params, r = locked_design()
    out = _tmp()
    s2 = bem.write_bem_files(params, r, out, symmetry="xy")
    names = {Path(v).name for v in s2["files"].values()}
    check("the symmetric mesh is written next to the full one",
          {"bem.msh", "bem_quarter.msh"} <= names, ", ".join(sorted(names)))
    info = mesh.read_msh22(out / "bem_quarter.msh")
    full = mesh.read_msh22(out / "bem.msh")
    check("bem_quarter.msh has about a quarter of the triangles of bem.msh",
          abs(len(info["tris"]) / len(full["tris"]) - 0.25) < 0.02,
          f"{len(info['tris'])} vs {len(full['tris'])}")
    check("the cut mesh keeps the tags and drops the (useless) baffle ring",
          info["physical"] == {1: "source", 2: "wall", 3: "interface"}, str(info["physical"]))
    check("no element of the cut mesh crosses a plane of symmetry",
          all(min(n[0] for n in (info["nodes"][a], info["nodes"][b], info["nodes"][c])) > -1e-12
              and min(n[1] for n in (info["nodes"][a], info["nodes"][b], info["nodes"][c])) > -1e-12
              for a, b, c, _ in info["tris"]),
          f"{len(info['tris'])} triangles")
    md = Path(s2["files"]["instructions"]).read_text()
    check("the recipe explains the symmetry switch",
          "Symmetry = `xy`" in md and "Re-Open" in md and "bem_quarter.msh" in md)
    check("the recipe keeps the step numbering consistent", "## 11." in md)
    check("a half mesh is named bem_half.msh",
          Path(bem.write_bem_files(params, r, _tmp(), symmetry="x")["files"]
               ["symmetric BEM mesh (Symmetry=x)"]).name == "bem_half.msh")


def test_msh22_roundtrip():
    """MSH 2.2 write/read round trip - the version AKABAK accepts."""
    tmp_dir = _tmp()
    params, r = locked_design()
    m = mesh.horn_mesh(r.design, 24, 8)
    p = mesh.write_msh22(m, tmp_dir / "round.msh")
    info = mesh.read_msh22(p)
    check("msh header says 2.2", info["version"] == "2.2", info["version"])
    check("node count survives the round trip", len(info["nodes"]) == len(m.nodes),
          f"{len(info['nodes'])} nodes")
    check("triangle count survives the round trip", len(info["tris"]) == len(m.tris),
          f"{len(info['tris'])} triangles")
    check("physical group names survive", info["physical"] == m.physical,
          str(info["physical"]))
    check("counts per group match",
          all(info["counts"][n] == m.count(n) for n in m.physical.values()),
          str(info["counts"]))


def test_build_package():
    """The build package: profile, slices, solid, DXF and the verification table."""
    tmp_dir = _tmp()
    params, r = locked_design()
    d = r.design
    prof = build.profile_rows(d, 20.0)
    check("profile starts at the throat", close(prof[0]["x_mm"], 0.0, 1e-9) and
          close(prof[0]["width_mm"], 2 * d.rt * 1e3, 1e-3), f"{prof[0]['width_mm']:.0f} mm")
    o_end = mesh.section_outline(d, d.length, 256)
    check("profile ends at the mouth (built outline, same area as the nominal rectangle)",
          close(prof[-1]["x_mm"], d.length * 1e3, 1e-6) and
          close(prof[-1]["width_mm"], 2 * float(np.abs(o_end[:, 0]).max()) * 1e3, 5e-3) and
          prof[-1]["width_mm"] >= d.mouth_width * 1e3 * 0.99,
          f"{prof[-1]['width_mm']:.0f} mm vs nominal {d.mouth_width * 1e3:.0f} mm")
    check("profile is monotone", all(a["radius_mm"] < b["radius_mm"]
                                    for a, b in zip(prof, prof[1:])))
    rows = build.slice_rows(d, 100.0, 18.0)
    check("slice count covers the depth", close(rows[-1]["z_to_mm"], d.length * 1e3, 1e-6),
          f"{len(rows)} slices")
    check("every slice frame is bigger than its hole",
          all(2 * float(np.abs(s["frame"][:, 0]).max()) > s["width_mm"] + 1e-9 for s in rows))
    solid = build.wall_solid(d, 18.0, 48, 10)
    vol = build.closed_volume(solid)
    check("wall solid is closed and outward-oriented", vol > 0.0, f"{vol * 1e3:.1f} litres")
    check("no flipped faces in the solid", build.orientation_problems(solid) == 0,
          f"{build.orientation_problems(solid)} bad edges")
    xs = np.linspace(0.0, d.length, 800)
    inner = np.maximum(np.atleast_1d(d.radius(xs)) - 0.018, 0.0)
    exact = float(np.trapezoid(math.pi * (np.atleast_1d(d.radius(xs)) ** 2 - inner ** 2), xs))
    check("wall volume matches the volume between the two nested surfaces",
          abs(vol - exact) / exact < 0.02,
          f"{vol * 1e3:.1f} l vs {exact * 1e3:.1f} l (area x thickness says "
          f"{build._wall_area(d) * 0.018 * 1e3:.1f} l)")
    dxf = build.write_dxf(build.profile_dxf(d), tmp_dir / "p.dxf")
    text = dxf.read_text()
    check("DXF has LWPOLYLINE entities", text.count("LWPOLYLINE") == 2, f"{dxf.name}")
    check("DXF carries the design depth",
          f"{d.length * 1e3:.4f}" in text and "0.0000" in text)
    rows_m = build.verify(d, mesh.horn_mesh(d, 48, 12), None, solid)
    check("build verification table passes", all(ok for _, ok, _ in rows_m),
          "; ".join(f"{n}:{ok}" for n, ok, _ in rows_m if not ok) or "all pass")


def test_akabak_le_script():
    """The generated LE script carries the measured driver values and still says fs."""
    params, r = locked_design()
    d = params.driver
    text = bem.le_driver_script(params)
    for needle in (f"dD={d.dD * 1e3:.2f}mm", f"Mms={d.Mms * 1e3:.2f}g",
                   f"Bl={d.Bl:.3f}Tm", f"Re={d.Re:.3f}ohm", f"Le={d.Le * 1e3:.4f}mH",
                   f"Vb={d.rear_volume * 1e6:.0f}cm3", f"Def_Driver '{d.name}'",
                   "RadImp 'Throat' Node=100 DrvGroup=1001"):
        check(f"LE script contains {needle}", needle in text)
    # parse the script back and check that it reproduces the measured resonance
    vals = {}
    for line in text.splitlines():
        line = line.strip()
        for key, unit in (("Mms", "g"), ("Cms", "m/N")):
            if line.startswith(key + "="):
                vals[key] = float(line.split("=", 1)[1].split(unit)[0])
    fs_script = 1.0 / (2 * math.pi * math.sqrt(vals["Mms"] * 1e-3 * vals["Cms"]))
    check("fs implied by the LE script matches the measured Fr",
          abs(fs_script - d.Fr) / d.Fr < 5e-3,
          f"{fs_script:.2f} Hz vs {d.Fr:.2f} Hz")


def test_export_parser():
    """The AKABAK/VACS text export parser: labels, separators, comments, bad input."""
    header = "Freq  SPL_0deg  SPL_30deg  DI\n"
    body = "".join(f"{f}  {90 + i * 0.1:.2f}  {88 + i * 0.1:.2f}  {3 + i * 0.01:.2f}\n"
                   for i, f in enumerate((20.0, 50.0, 100.0, 200.0)))
    p = bem.parse_export(header + body)
    check("parser reads every row", len(p["freq"]) == 4 and close(p["freq"][0], 20.0, 1e-12),
          f"{len(p['freq'])} rows")
    check("parser picks up the column labels",
          list(p["curves"]) == ["SPL_0deg", "SPL_30deg", "DI"], str(list(p["curves"])))
    check("parser finds the 0 deg curve", bem._onaxis_curve(p) == "SPL_0deg")
    comma = bem.parse_export("Hz,SPL(0deg),SPL(45deg)\n30,95.5,93.0\n45,96.0,94.1\n")
    check("parser handles comma separated text",
          len(comma["curves"]) == 2 and close(comma["freq"][1], 45.0, 1e-12))
    commented = bem.parse_export("! exported by AKABAK\n# freq  spl\n50  91.2\n100  93.0\n")
    check("parser skips comment lines", len(commented["freq"]) == 2, str(commented["freq"]))
    unsorted = bem.parse_export("100 93\n20 90\n50 91\n")
    check("parser sorts by frequency", list(unsorted["freq"]) == [20.0, 50.0, 100.0])
    try:
        bem.parse_export("this file has no numbers at all")
        check("parser rejects a file without a table", False)
    except ValueError as exc:
        check("parser rejects a file without a table", "no numeric table" in str(exc))


def test_bem_import_and_compare():
    """--bem-import: parse a synthetic export, write the CSV, the report and the figure."""
    params, r = locked_design()
    tmp = _tmp()
    lines = ["VACS export", "freq SPL_0deg SPL_45deg"]
    for f in (60.0, 80.0, 100.0, 150.0, 200.0):
        on = float(np.interp(f, r.f, r.spl))
        lines.append(f"{f:.1f} {on + 1.5:.2f} {on - 2.0:.2f}")
    (tmp / "export.txt").write_text("\n".join(lines) + "\n")
    imp = bem.import_exports(params, r, tmp, tmp / "bem")
    check("import found the file", imp["source"] == "export.txt", imp["source"])
    check("curves CSV was written", imp["files"]["curves"].is_file())
    check("comparison figure was written", imp["files"]["figure"].is_file())
    md = imp["files"]["report"].read_text()
    check("comparison report has the difference table",
          "Stage 1" in md and "difference" in md and "60 Hz" in md)
    check("difference is about +1.5 dB where the synthetic data says so",
          "+1.5 dB" in md or "+1.4 dB" in md or "+1.6 dB" in md)
    csv_text = imp["files"]["curves"].read_text().splitlines()
    check("curves CSV has a header and one row per frequency",
          csv_text[0].startswith("freq_hz") and len(csv_text) == 6, str(len(csv_text)))
    # a folder with nothing parseable must fail loudly, not silently
    bad = _tmp()
    (bad / "junk.txt").write_text("nothing numeric here\n")
    try:
        bem.import_exports(params, r, bad, bad / "bem")
        check("import fails loudly on unusable input", False)
    except ValueError as exc:
        check("import fails loudly on unusable input", "could not parse" in str(exc))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        doc = (t.__doc__ or "").strip().splitlines()
        print(f"\n{t.__name__}" + (f"  -- {doc[0]}" if doc else ""))
        t()
    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print("FAILED: " + "; ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
