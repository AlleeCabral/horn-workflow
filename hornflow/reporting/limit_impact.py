"""Limit-impact explanations (Stage 2).

For every user-defined limit produce a concise positive and negative influence,
the physical reason, the most-affected outputs, a constraint state and a
suggested relaxation.  Until a sensitivity run exists the assessment is
QUALITATIVE - never a fabricated number.
"""

from __future__ import annotations

from ..domain.limits import LimitImpact, LimitStatus


def build_limit_impacts(params, master, feasibility=None) -> list:
    t = params.target
    h = params.horn
    impacts = [
        LimitImpact(
            name="Passband", value=f"{t.f_low:.0f}-{t.f_high:.0f} Hz",
            status=LimitStatus.ACTIVE.value,
            positive="A defined band fixes the flare cut-off and mouth size target.",
            negative="Widening it downward forces a lower cut-off and a much larger horn.",
            physical_reason="Low-frequency loading scales with wavelength, so the "
                            "bottom of the band sets the required path length and mouth.",
            most_affected_outputs="cut-off, mouth area, gross volume, low-end SPL",
            suggested_relaxation="Raising f_low from 60 to 80 Hz roughly halves the "
                                 "required mouth and depth.",
        ),
        LimitImpact(
            name="Depth / path budget",
            value=f"{h.length*1e3 if h.length else 0:.0f} mm",
            status=LimitStatus.ACTIVE.value,
            positive="Caps the enclosure footprint and enables a folded layout.",
            negative="A short path raises the cut-off and reduces low-frequency loading.",
            physical_reason="Horn loading needs roughly a quarter wavelength of path "
                            "at the lowest frequency of interest.",
            most_affected_outputs="cut-off, low-end SPL, ripple",
            suggested_relaxation="Adding depth (or fold count) lowers the cut-off "
                                 "without enlarging the mouth.",
        ),
        LimitImpact(
            name="Mouth area", value=f"{master.mouth_area*1e4:.0f} cm^2",
            status=(LimitStatus.ACTIVE.value if feasibility and not feasibility.mouth_adequate
                    else LimitStatus.INACTIVE.value),
            positive="A larger mouth smooths the response and improves termination.",
            negative="A large mouth drives the enclosure footprint and mass.",
            physical_reason="Mouth size relative to wavelength (k*rm) controls "
                            "reflection at the mouth and the low-frequency ripple.",
            most_affected_outputs="ripple, directivity, gross volume",
            suggested_relaxation="A small k*rm reduction trades ripple for a smaller "
                                 "mouth; verify with a fold-aware simulation.",
        ),
        LimitImpact(
            name="Mouth aspect (W:H)", value=f"{h.mouth_aspect:.2f}",
            status=LimitStatus.INACTIVE.value,
            positive="Sets the horizontal/vertical coverage shape without changing loading.",
            negative="Extreme aspects raise panel spans and bend radii.",
            physical_reason="For a given area the aspect sets the two aperture "
                            "dimensions, hence panel spans and bend geometry.",
            most_affected_outputs="directivity, panel spans, bend radius",
            suggested_relaxation="Move aspect toward square only if directivity allows.",
        ),
    ]
    return _more(impacts, params, master)


def _more(impacts, params, master):
    d = params.driver
    sim = params.simulation
    impacts.append(LimitImpact(
        name="Rear chamber (fixed chassis)", value=f"{d.rear_volume*1e6:.0f} cm^3",
        status=LimitStatus.ACTIVE.value,
        positive="Provides the required restoring compliance behind the cone.",
        negative="Its resonance (Qtc) sets the true bottom end below the horn cut-off.",
        physical_reason="A sealed volume raises the driver resonance by "
                        "sqrt(1+Vas/Vb), setting Qtc.",
        most_affected_outputs="lowest usable frequency, excursion, group delay",
        suggested_relaxation="A larger rear volume lowers Qtc and smooths the "
                             "bottom octave at the cost of size.",
    ))
    impacts.append(LimitImpact(
        name="Drive voltage / power", value=f"{sim.voltage:.2f} Vrms",
        status=LimitStatus.ACTIVE.value,
        positive="Sets the reference output level for all SPL figures.",
        negative="Higher drive raises excursion and thermal load toward limits.",
        physical_reason="SPL and excursion scale with drive; Xmax and thermal "
                        "ratings bound the usable range.",
        most_affected_outputs="SPL, excursion margin, distortion risk",
        suggested_relaxation="None needed unless a target SPL is unmet; then the "
                             "limit is excursion or thermal, not voltage.",
    ))
    impacts.append(LimitImpact(
        name="Driver Xmax", value=f"{d.Xmax*1e3:.2f} mm" if d.Xmax else "unknown",
        status=(LimitStatus.UNCERTAIN.value if not d.Xmax else LimitStatus.ACTIVE.value),
        positive="Bounds cone travel, protecting the driver below cut-off.",
        negative="A small Xmax caps maximum low-frequency output.",
        physical_reason="Below the cut-off the horn stops loading the cone, so "
                        "excursion grows quickly with drive.",
        most_affected_outputs="maximum SPL, need for a high-pass filter",
        suggested_relaxation="None - a safety limit; the fix is a high-pass or "
                             "more displacement, not relaxing Xmax.",
    ))
    impacts.append(LimitImpact(
        name="Architecture preference (folded horn)", value="preferred",
        status=LimitStatus.INACTIVE.value,
        positive="Folded packaging cuts volume/mass for the same acoustic path.",
        negative="Adds bends, which can introduce passband ripple if over-folded.",
        physical_reason="Folding preserves path and area law but adds curvature, "
                        "whose effect grows with duct width and frequency.",
        most_affected_outputs="volume, mass, ripple, build complexity",
        suggested_relaxation="Prefer fewer/gentler bends when the passband ripple "
                             "budget is tight.",
    ))
    return impacts


def to_markdown(impacts) -> str:
    rows = ["| Parameter | Value/status | Positive | Negative | Physical reason | "
            "Most affected outputs | Constraint state | Suggested relaxation |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for li in impacts:
        rows.append("| {n} | {v} | {p} | {g} | {r} | {o} | {s} | {x} |".format(
            n=li.name, v=li.value, p=li.positive, g=li.negative, r=li.physical_reason,
            o=li.most_affected_outputs, s=li.status, x=li.suggested_relaxation))
    note = ("\n_All limit-impact assessments are **QUALITATIVE** until a "
            "sensitivity run replaces them with measured/simulated effects._")
    return "\n".join(rows) + "\n" + note
