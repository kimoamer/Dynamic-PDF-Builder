"""Optional dependencies with an install hint when they are missing."""
from .errors import MissingDependencyError

CHARTS_HINT = ("Charts, math and diagrams need matplotlib, which is not installed: "
               "pip install 'dynamic-pdf-builder[charts]'")


def require_matplotlib():
    """Import matplotlib with the non-interactive backend, or explain how to install it."""
    try:
        import matplotlib
    except ImportError as e:
        raise MissingDependencyError(CHARTS_HINT) from e
    matplotlib.use("Agg")
    return matplotlib
