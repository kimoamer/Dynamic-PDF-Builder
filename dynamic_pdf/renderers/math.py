"""Legacy math renderer entry point — delegates to the factory renderer
(which records a ``math_fallback`` diagnostic when it falls back to source)."""


def render_math(block, theme):
    from ..layout.factory import _render_math
    return _render_math(block, theme)
