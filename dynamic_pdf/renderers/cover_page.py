"""Legacy cover-page renderer entry point — delegates to the policy-checked factory renderer."""


def render_cover_page(block, theme):
    from ..layout.factory import _render_cover
    return _render_cover(block, theme)
