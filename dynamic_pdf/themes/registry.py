"""Theme registry — maps theme names to Theme instances."""
from ..schema.theme import Theme

_THEMES: dict[str, Theme] = {}

def register_theme(theme: Theme):
    _THEMES[theme.name] = theme

def get_theme(name: str) -> Theme:
    if name not in _THEMES:
        _load_defaults()
    if name not in _THEMES:
        raise ValueError(f"Unknown theme: {name!r}. Available: {list(_THEMES.keys())}")
    return _THEMES[name].model_copy(deep=True)

def list_themes() -> list[str]:
    _load_defaults()
    return list(_THEMES.keys())

_loaded = False

def _load_defaults():
    global _loaded
    if _loaded:
        return
    from .claude import CLAUDE_THEME
    from .chatgpt import CHATGPT_THEME
    from .corporate_dark import CORPORATE_DARK_THEME
    from .academic import ACADEMIC_THEME
    from .modern_minimal import MODERN_MINIMAL_THEME
    from .government import GOVERNMENT_THEME
    from .data_report import DATA_REPORT_THEME
    for t in (CLAUDE_THEME, CHATGPT_THEME, CORPORATE_DARK_THEME,
              ACADEMIC_THEME, MODERN_MINIMAL_THEME,
              GOVERNMENT_THEME, DATA_REPORT_THEME):
        if t.name not in _THEMES:
            _THEMES[t.name] = t
    _loaded = True
