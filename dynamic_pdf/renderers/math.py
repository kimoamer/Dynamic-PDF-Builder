"""Legacy math renderer entry point — delegates to the factory renderer
(which records a ``math_fallback`` diagnostic when it falls back to source)."""


def render_math(block, theme):
    from ..layout.factory import _render_math
    return _render_math(block, theme)


def math_png(latex: str, dpi: int = 220) -> bytes:
    """Render LaTeX (matplotlib mathtext subset) to a tight PNG."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(7, 1.2))
    fig.patch.set_alpha(0)
    fig.text(0.5, 0.5, f"${latex}$", fontsize=15, ha="center", va="center")
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi, transparent=True)
    finally:
        plt.close(fig)
    return buf.getvalue()
