"""Stage 1 figures (matplotlib, Agg backend - no display needed)."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                        # noqa: E402

from . import theory                      # noqa: E402
from .config import Params                # noqa: E402
from .response import Result              # noqa: E402

STYLE = {"grid": {"alpha": 0.3, "linestyle": ":"}, "figsize": (8.0, 4.5), "dpi": 130}


def _fig() -> tuple:
    return plt.subplots(figsize=STYLE["figsize"], dpi=STYLE["dpi"])


def _finish(fig, ax, path: Path, title: str) -> Path:
    ax.set_title(title, fontsize=10)
    ax.grid(**STYLE["grid"])
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def profile_figure(params: Params, r: Result, out_dir: Path) -> Path:
    d = r.design
    x = np.linspace(0.0, d.length, 400)
    rad = d.radius(x) * 1e3
    fig, ax = _fig()
    ax.plot(x * 1e3, rad, color="tab:blue", label=f"{d.profile} profile")
    ax.plot(x * 1e3, -rad, color="tab:blue")
    ax.axhline(0.0, color="k", linewidth=0.6)
    ax.plot([0], [d.rt * 1e3], "o", color="tab:red", ms=4, label="throat 2r0")
    ax.plot([d.length * 1e3], [d.rm * 1e3], "s", color="tab:green", ms=4, label="mouth 2rm")
    ax.set_xlabel("axial distance x [mm]")
    ax.set_ylabel("radius [mm]")
    ax.set_aspect("equal", adjustable="datalim")
    info = (f"fc = {d.fc:.0f} Hz   m = {d.m:.2f} 1/m   St = {d.St * 1e4:.0f} cm²   "
            f"Sm = {d.Sm * 1e4:.0f} cm²")
    return _finish(fig, ax, out_dir / "profile.png",
                   f"Horn profile ({params.project})\n{info}")


def impedance_figure(r: Result, out_dir: Path) -> Path:
    f = r.f
    fig, ax = _fig()
    rc_st = r.design.rho * r.design.c / r.design.St
    ax.semilogx(f, r.Zt.real / rc_st, color="tab:blue", label="Re(Zt) finite horn")
    ax.semilogx(f, r.Zt.imag / rc_st, color="tab:blue", linestyle="--",
                label="Im(Zt) finite horn")
    if r.Zt_infinite is not None:
        ax.semilogx(f, r.Zt_infinite.real / rc_st, color="tab:red", linewidth=1.0,
                    label="Re(Zt) infinite horn (Eq. 7/9)")
        ax.semilogx(f, r.Zt_infinite.imag / rc_st, color="tab:red", linestyle="--",
                    linewidth=1.0, label="Im(Zt) infinite horn")
    ax.axhline(1.0, color="k", linewidth=0.6, linestyle=":")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("Zt / (rho c / St)")
    return _finish(fig, ax, out_dir / "throat_impedance.png",
                   "Throat impedance seen by the driver (normalized)")


def spl_figure(params: Params, r: Result, out_dir: Path) -> Path:
    fig, ax = _fig()
    ax.semilogx(r.f, r.spl, color="tab:blue", label="on axis, 1 m")
    ax.axvspan(params.target.f_low, params.target.f_high, color="tab:green", alpha=0.08,
               label=f"target band {params.target.f_low:.0f}-{params.target.f_high:.0f} Hz")
    ax.axvline(r.design.fc, color="tab:red", linewidth=0.8, linestyle="--",
               label=f"flare cut-off {r.design.fc:.0f} Hz")
    mean = r.band_spl(params.target.f_low, params.target.f_high)
    var = r.variations_db(params.target.f_low, params.target.f_high)
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("SPL [dB]")
    return _finish(fig, ax, out_dir / "spl_onaxis.png",
                   f"On-axis SPL at {params.simulation.voltage:.2f} V / "
                   f"{params.simulation.observation_distance:g} m\n"
                   f"band mean {mean:.1f} dB, peak-to-peak {var:.1f} dB")


def electrical_figure(r: Result, out_dir: Path) -> Path:
    fig, ax = _fig()
    ax.semilogx(r.f, np.abs(r.Ze), color="tab:purple", label="|Ze|")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("|Ze| [ohm]")
    ax2 = ax.twinx()
    ax2.semilogx(r.f, np.angle(r.Ze, deg=True), color="tab:orange", linewidth=1.0,
                 label="arg(Ze)")
    ax2.set_ylabel("phase [deg]")
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [ln.get_label() for ln in lines], fontsize=8)
    return _finish(fig, ax, out_dir / "electrical_impedance.png",
                   "Electrical impedance (LE model loaded by the horn)")


def excursion_figure(r: Result, out_dir: Path) -> Path:
    from .domain.excursion import RMS_TO_PEAK

    fig, ax = _fig()
    x_rms = np.abs(r.excursion) * 1e3
    ax.semilogx(r.f, x_rms, color="tab:brown", label="excursion (rms)")
    ax.semilogx(r.f, x_rms * RMS_TO_PEAK, color="tab:brown", linestyle="--",
                linewidth=1.0, label="excursion (one-way peak)")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("excursion [mm]")
    ax2 = ax.twinx()
    ax2.semilogx(r.f, r.di, color="tab:cyan", linewidth=1.0, label="DI (piston mouth)")
    ax2.set_ylabel("DI [dB]")
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [ln.get_label() for ln in lines], fontsize=8)
    return _finish(fig, ax, out_dir / "excursion_directivity.png",
                   "Diaphragm excursion and mouth directivity index")


def all_figures(params: Params, r: Result, out_dir: str | Path) -> list:
    """Write every Stage 1 figure and return the list of file paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return [profile_figure(params, r, out), impedance_figure(r, out),
            spl_figure(params, r, out), electrical_figure(r, out),
            excursion_figure(r, out)]

