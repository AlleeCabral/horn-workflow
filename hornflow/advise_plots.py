"""Figures for the advice engine: what your budget can reach, and what it buys."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt     # noqa: E402
import numpy as np                  # noqa: E402

from . import advise                # noqa: E402
from .config import Params          # noqa: E402


def _fig(w: float = 9.5, h: float = 5.0):
    return plt.subplots(figsize=(w, h), dpi=130)


def spl_overlay(data: dict, out_dir: Path):
    """Every candidate's on-axis response, against the direct-radiating driver."""
    cands = [c for c in data["candidates"] if c.fits and c.result is not None]
    if not cands:
        return None
    base: Params = data["base"]
    best = advise.best_candidate(data)
    fig, ax = _fig()
    cmap = plt.get_cmap("viridis")
    ref = data["reference"]["result"]
    ax.semilogx(ref.f, ref.spl, color="k", linestyle="--", linewidth=1.2,
                label="direct radiator, same driver + rear chamber")
    for i, c in enumerate(sorted(cands, key=lambda c: c.fc)):
        tag = (f"fc {c.fc:.0f} Hz, mouth {c.mouth_width * 1e3:.0f}x{c.mouth_height * 1e3:.0f} mm, "
               f"depth {c.depth * 1e3:.0f} mm, var {c.metrics['spl_variation_db']:.1f} dB")
        ax.semilogx(c.result.f, c.result.spl, linewidth=2.2 if c is best else 1.0,
                    color=cmap(i / max(len(cands) - 1, 1)),
                    label=("* " if c is best else "") + tag)
    ax.axvspan(base.target.f_low, base.target.f_high, color="tab:green", alpha=0.07,
               label=f"band {base.target.f_low:.0f}-{base.target.f_high:.0f} Hz")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("on-axis SPL [dB] at 2.83 V / 1 m")
    ax.set_title("Advice: candidates that fit your depth budget (dashed = no horn)", fontsize=10)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    p = Path(out_dir) / "advise_spl.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def gain_curve(data: dict, out_dir: Path):
    """How much the recommended horn adds over the direct radiator."""
    best = advise.best_candidate(data)
    if best is None or best.result is None:
        return None
    ref = data["reference"]["result"]
    f = best.result.f
    gain = best.result.spl - ref.spl
    fig, ax = _fig(9.5, 4.4)
    ax.semilogx(f, gain, color="tab:blue", label=f"gain of {best.label}")
    ax.axhline(0.0, color="k", linewidth=0.8)
    ax.axvline(best.fc, color="tab:red", linestyle="--", linewidth=0.9,
               label=f"horn cut-off {best.fc:.0f} Hz")
    base = data["base"]
    ax.axvspan(base.target.f_low, base.target.f_high, color="tab:green", alpha=0.07,
               label=f"band {base.target.f_low:.0f}-{base.target.f_high:.0f} Hz")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("horn gain over direct radiator [dB]")
    ax.set_title("What the horn adds, same driver and same rear chamber", fontsize=10)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = Path(out_dir) / "advise_gain.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def limit_map(data: dict, out_dir: Path):
    """The whole design space: k*rm and required mouth width vs cut-off and depth."""
    base: Params = data["base"]
    rt = base.horn.throat_diameter / 2.0
    c = base.simulation.c
    fc = np.linspace(40.0, 120.0, 41)
    depth = np.linspace(300.0, 1800.0, 31) / 1e3
    km = np.array([[advise.k_rm_at_depth(x, rt, L, c) for x in fc] for L in depth])
    rm_grid = advise.mouth_radius_for(fc[None, :], km, c)      # (depth, fc) [m]
    area = np.sqrt(np.pi * rm_grid ** 2 * data["aspect"]) * 1e3  # mouth width [mm]

    fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.6), dpi=130)
    for ax, mat, title, unit in (
            (axs[0], km, "mouth criterion k*rm", ""),
            (axs[1], area, "mouth width required (rectangular)", " mm")):
        im = ax.imshow(mat, origin="lower", aspect="auto", cmap="magma_r",
                       extent=[fc[0], fc[-1], depth[0] * 1e3, depth[-1] * 1e3])
        ax.set_xlabel("intended cut-off fc [Hz]")
        ax.set_ylabel("horn depth [mm]")
        ax.set_title(f"{title} [{unit}]", fontsize=10)
        fig.colorbar(im, ax=ax)
        ax.axhline(data["depth_limit"], color="tab:cyan", linestyle="--", linewidth=1.1,
                   label=f"your depth limit {data['depth_limit']:.0f} mm")
        ax.legend(fontsize=7)
    cs = axs[0].contour(fc, depth * 1e3, km, levels=[0.7, 1.0], colors="w", linewidths=1.0)
    axs[0].clabel(cs, fmt="%.1f")
    for c_ in data["candidates"]:
        if not c_.fits:
            continue
        for ax in axs:
            ax.plot([c_.fc], [c_.depth * 1e3], "o", color="tab:cyan", ms=4)
    fig.suptitle("Design space for your driver, throat and depth budget", fontsize=11)
    fig.tight_layout()
    p = Path(out_dir) / "advise_limits.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def math_pi_mouth(fc: float, k: float, aspect: float) -> float:
    """Mouth width [m] of a rectangle with the given aspect that reaches k*rm = k."""
    rm = advise.mouth_radius_for(fc, k)
    return advise.rectangle(np.pi * rm ** 2, aspect)[0]


def all_figures(data: dict, out_dir: Path) -> list:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return [f for f in (spl_overlay(data, out), gain_curve(data, out), limit_map(data, out))
            if f is not None]
