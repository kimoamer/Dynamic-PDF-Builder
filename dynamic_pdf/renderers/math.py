"""Legacy math renderer entry point — delegates to the factory renderer
(which records a ``math_fallback`` diagnostic when it falls back to source)."""


def render_math(block, theme):
    from ..layout.factory import _render_math
    return _render_math(block, theme)


def math_png(latex: str, dpi: int = 220, paper: bool = False) -> bytes:
    """Render LaTeX (matplotlib mathtext subset) to a tight PNG. ``paper``: a Times-like face."""
    import contextlib
    import io
    from ..utils.optional import require_matplotlib
    require_matplotlib()
    import matplotlib.pyplot as plt
    rc = plt.rc_context({"font.family": "STIXGeneral", "mathtext.fontset": "stix"}) if paper \
        else contextlib.nullcontext()
    buf = io.BytesIO()
    with rc:
        fig = plt.figure(figsize=(7, 1.2))
        fig.patch.set_alpha(0)
        fig.text(0.5, 0.5, f"${latex}$", fontsize=15, ha="center", va="center")
        try:
            fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi, transparent=True)
        finally:
            plt.close(fig)
    return buf.getvalue()
