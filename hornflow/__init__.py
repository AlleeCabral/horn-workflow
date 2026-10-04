"""horn-workflow :: parameter-driven acoustic horn design & simulation.

Stage 1 (this package): native 1P (Webster horn equation) + lumped-element
model.  All relations are taken from

    B. Kolbrek, "Horn Theory: An Introduction", Parts 1 & 2,
    audioXpress 2008 (docs/an-introduction-to-horn-theory.pdf)

Stage 2 (planned): the same parameter file drives ATH (OS-SE geometry) ->
Gmsh (MSH 2.2) -> AKABAK (BEM/LEM) for full 3D verification.
"""

__version__ = "0.1.0"

__all__ = ["config", "theory", "response", "report", "plots"]
