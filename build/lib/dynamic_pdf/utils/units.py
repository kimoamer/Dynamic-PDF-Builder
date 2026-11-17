"""Unit conversion utilities for theme values."""
from reportlab.lib.units import inch, cm, mm

UNITS = {
    "pt": 1.0,
    "in": inch,          # 72pt
    "inch": inch,
    "cm": cm,            # 28.35pt
    "mm": mm,            # 2.835pt
    "px": 0.75,          # CSS px at 96dpi ≈ 0.75pt
}

def to_points(value: float, unit: str = "pt") -> float:
    """Convert a value in the given unit to points."""
    factor = UNITS.get(unit.lower(), 1.0)
    return value * factor

def from_points(pts: float, unit: str = "in") -> float:
    """Convert points to the given unit."""
    factor = UNITS.get(unit.lower(), 1.0)
    return pts / factor if factor else pts
