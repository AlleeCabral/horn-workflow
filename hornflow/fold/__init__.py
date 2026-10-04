"""hornflow.fold - fold topology generation and evaluation (layers 7 + 8)."""

from ..domain.geometry import Centreline
from . import paths
from .base import Bend, FoldCandidate, FoldEvaluator, FoldGenerator, sections_along
from .bends import analyze_bends, required_radius
from .evaluate import build_fold_candidate
from .generators import JFold, StraightFold, UFold, generators
from .packaging import package_report

__all__ = [
    "Centreline", "paths",
    "Bend", "FoldCandidate", "FoldEvaluator", "FoldGenerator", "sections_along",
    "analyze_bends", "required_radius", "build_fold_candidate",
    "StraightFold", "JFold", "UFold", "generators", "package_report",
]
