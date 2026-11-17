"""Optional dependencies with an install hint when they are missing."""
import sys

from .errors import MissingDependencyError

CHARTS_HINT = ("Charts, math and diagrams need matplotlib, which is not installed: "
               "pip install 'dynamic-pdf-builder[charts]'")


def require_matplotlib():
    """Import matplotlib, or explain how to install it. The non-interactive backend is chosen only
    when the host has not started pyplot: a notebook or an application keeps the backend it set
    (saving a figure to an image works under any of them)."""
    try:
        import matplotlib
    except ImportError as e:
        raise MissingDependencyError(CHARTS_HINT) from e
    if "matplotlib.pyplot" not in sys.modules:
        matplotlib.use("Agg")
    return matplotlib
