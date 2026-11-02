"""Legacy image renderer entry point — delegates to the policy-checked factory renderer."""


def render_image(block, theme, available_width: float = 500):
    from ..layout.factory import _render_image
    return _render_image(block, theme, available_width)
