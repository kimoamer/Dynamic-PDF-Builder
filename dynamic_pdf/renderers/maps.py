"""
Maps, location sketches and mind maps, drawn as charts (so they work in PDF, in Word, from a
```chart fence, and with Arabic labels).

``map``: regions from GeoJSON the author supplies (nothing is fetched), optionally shaded by a value
each, with named points on top::

    {"geojson": {...} or "regions.geojson", "label": "name",
     "values": {"Cairo": 9.5, "Giza": 8.6}, "points": [{"name": "Port", "lon": 32.3, "lat": 31.2}]}

``sketch``: a location sketch (a croquis), not to scale, in any units::

    {"roads": [{"name": "Tahrir St", "points": [[0, 5], [10, 5]], "width": 2}],
     "blocks": [{"name": "Park", "box": [1, 6, 4, 9]}],
     "places": [{"name": "Our office", "at": [6, 5.8], "kind": "site"}, {"name": "Mosque", "at": [3, 4.2]}],
     "north": 0}

``mindmap``: one topic and its branches::

    {"Strategy": {"Growth": ["New markets", "Pricing"], "Costs": ["Suppliers"], "People": []}}
"""
from __future__ import annotations

import json
import math

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt


def _palette(theme):
    c = getattr(theme, "colors", None)
    return (getattr(c, "primary", "#1F3A5F"), getattr(c, "accent", "#C0392B"),
            getattr(c, "text_primary", "#222222"), getattr(c, "text_muted", "#777777"))


_PLATE = dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="none", alpha=0.9)


def _blank(block):
    fig, ax = plt.subplots(figsize=(block.width, block.height))
    ax.set_aspect("equal")
    ax.axis("off")
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold", pad=10)
    return fig, ax


def _fit(ax, block, extra_x: float = 0.0):
    """Widen the limits to the figure's own proportions, so a tall, narrow drawing stays within the
    size it was given (a tight crop of equal-aspect axes would otherwise scale it past the page)."""
    ax.autoscale_view()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    x1 += (x1 - x0) * extra_x
    w, h, want = x1 - x0, y1 - y0, block.width / block.height
    if w / h < want:
        pad = (h * want - w) / 2
        x0, x1 = x0 - pad, x1 + pad
    else:
        pad = (w / want - h) / 2
        y0, y1 = y0 - pad, y1 + pad
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)


# ── map ────────────────────────────────────────────────────────────────────────────────

def _geojson(source):
    if isinstance(source, str):                      # a file, read under the asset policy like any other
        from .. import policy
        from ..assets import load_asset_bytes
        source = json.loads(load_asset_bytes(source, policy.current().policy.assets).decode("utf-8"))
    if not isinstance(source, dict):
        raise ValueError('a map needs "geojson": a GeoJSON object, or the path of a .geojson file')
    kind = source.get("type")
    if kind == "FeatureCollection":
        return source.get("features") or []
    if kind == "Feature":
        return [source]
    return [{"type": "Feature", "properties": {}, "geometry": source}]


def _rings(geometry):
    """(polygons, lines, points) of one geometry: each polygon its outer ring, holes left out."""
    kind, coords = (geometry or {}).get("type"), (geometry or {}).get("coordinates") or []
    if kind == "Polygon":
        return [coords[0]] if coords else [], [], []
    if kind == "MultiPolygon":
        return [p[0] for p in coords if p], [], []
    if kind == "LineString":
        return [], [coords], []
    if kind == "MultiLineString":
        return [], list(coords), []
    if kind == "Point":
        return [], [], [coords]
    if kind == "MultiPoint":
        return [], [], list(coords)
    if kind == "GeometryCollection":
        out = ([], [], [])
        for g in geometry.get("geometries") or []:
            for acc, part in zip(out, _rings(g)):
                acc.extend(part)
        return out
    return [], [], []


def _shade(color: str, t: float):
    """From a pale tint of ``color`` (t=0) to the colour itself (t=1)."""
    import matplotlib.colors as mc
    r, g, b = mc.to_rgb(color)
    k = 0.12 + 0.88 * max(0.0, min(1.0, t))
    return (1 - (1 - r) * k, 1 - (1 - g) * k, 1 - (1 - b) * k)


def render_map(block, theme):
    data = block.data if isinstance(block.data, dict) else {}
    features = _geojson(data.get("geojson", data if data.get("type") else None))
    if not features and not data.get("points"):
        raise ValueError("the map has nothing to draw: its GeoJSON holds no features")
    primary, accent, ink, muted = _palette(theme)
    key = data.get("label") or "name"
    values = {str(k): float(v) for k, v in (data.get("values") or {}).items()}
    highlight = {str(x) for x in data.get("highlight") or []}
    lo, hi = (min(values.values()), max(values.values())) if values else (0.0, 1.0)
    lats = [pt[1] for f in features for part in _rings(f.get("geometry")) for shape in part
            for pt in (shape if isinstance(shape[0], (list, tuple)) else [shape])]
    lats += [float(p["lat"]) for p in data.get("points") or []]
    k = math.cos(math.radians(sum(lats) / len(lats))) if lats else 1.0     # east-west shrinks away from the equator

    def xy(pt):
        return pt[0] * k, pt[1]
    fig, ax = _blank(block)
    for f in features:
        name = str((f.get("properties") or {}).get(key, ""))
        polys, lines, pts = _rings(f.get("geometry"))
        if name in values:
            face = _shade(primary, (values[name] - lo) / (hi - lo) if hi > lo else 1.0)
        else:
            face = _shade(accent, 0.75) if name in highlight else "#ECEEF1"
        for ring in polys:
            ax.add_patch(mpatches.Polygon([xy(p) for p in ring], closed=True, facecolor=face, edgecolor="white",
                                          linewidth=0.8, zorder=1))
        for line in lines:
            ax.plot(*zip(*[xy(p) for p in line]), color=muted, linewidth=1.0, zorder=2)
        for p in pts:
            ax.plot(*xy(p), "o", color=accent, markersize=4, zorder=3)
        if name and polys and (data.get("labels", True)):
            big = max(polys, key=len)
            cx, cy = sum(xy(p)[0] for p in big) / len(big), sum(p[1] for p in big) / len(big)
            ax.text(cx, cy, name, ha="center", va="center", fontsize=7, color=ink, zorder=4)
    for p in data.get("points") or []:
        x, y = xy((float(p["lon"]), float(p["lat"])))
        ax.plot(x, y, "o", color=accent, markersize=5, markeredgecolor="white", markeredgewidth=0.8, zorder=5)
        if p.get("name"):                            # on a plate, so it reads over a region's own name
            ax.annotate(str(p["name"]), (x, y), xytext=(7, 7), textcoords="offset points", fontsize=7.5,
                        color=ink, fontweight="bold", zorder=6, bbox=_PLATE)
    ax.margins(0.03)
    _fit(ax, block)
    if values and hi > lo:                           # the scale the shading reads against
        import matplotlib as mpl
        cmap = mpl.colors.LinearSegmentedColormap.from_list("v", [_shade(primary, 0), _shade(primary, 1)])
        bar = fig.colorbar(mpl.cm.ScalarMappable(mpl.colors.Normalize(lo, hi), cmap), ax=ax, shrink=0.5, pad=0.02)
        bar.outline.set_visible(False)
        bar.ax.tick_params(labelsize=7, length=0)
    return fig


# ── location sketch ────────────────────────────────────────────────────────────────────

def render_sketch(block, theme):
    data = block.data if isinstance(block.data, dict) else {}
    roads, places, blocks = data.get("roads") or [], data.get("places") or [], data.get("blocks") or []
    if not roads and not places:
        raise ValueError('a sketch needs "roads" ([{"name", "points": [[x, y], ...]}]) or "places" ([{"name", "at": [x, y]}])')
    primary, accent, ink, muted = _palette(theme)
    fig, ax = _blank(block)
    for b in blocks:                                  # built-up blocks, parks, plots: pale shapes behind the roads
        x0, y0, x1, y1 = b["box"]
        ax.add_patch(mpatches.FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=0.15",
                                             facecolor=b.get("color") or "#EEF2E6", edgecolor="#D5DCC8", linewidth=0.8, zorder=1))
        if b.get("name"):
            ax.text((x0 + x1) / 2, (y0 + y1) / 2, str(b["name"]), ha="center", va="center", fontsize=7.5, color=muted, zorder=2)
    names = []                                        # where road names sit, so a place's label keeps clear of them
    for r in roads:
        pts = r.get("points") or [r["from"], r["to"]]
        xs, ys = zip(*pts)
        w = float(r.get("width", 1)) * 7
        ax.plot(xs, ys, color="#B9BDC4", linewidth=w + 1.6, solid_capstyle="round", solid_joinstyle="round", zorder=3)
        ax.plot(xs, ys, color="#FFFFFF", linewidth=w, solid_capstyle="round", solid_joinstyle="round", zorder=4)
        if r.get("name"):                             # the name runs along the longest stretch of the road
            i = max(range(len(pts) - 1), key=lambda j: math.dist(pts[j], pts[j + 1]))
            (xa, ya), (xb, yb) = pts[i], pts[i + 1]
            angle = math.degrees(math.atan2(yb - ya, xb - xa))
            angle = angle - 180 if angle > 90 else angle + 180 if angle < -90 else angle
            ax.text((xa + xb) / 2, (ya + yb) / 2, str(r["name"]), ha="center", va="center", rotation=angle,
                    rotation_mode="anchor", fontsize=7, color="#555B66", zorder=5)
            names.append(((xa + xb) / 2, (ya + yb) / 2))
    for p in places:
        x, y = p["at"]
        site = str(p.get("kind", "landmark")).lower() == "site"
        ax.plot(x, y, marker="*" if site else "o", color=accent if site else primary, markersize=17 if site else 6,
                markeredgecolor="white", markeredgewidth=1.0, zorder=7)
        if p.get("name"):
            near = min(names, key=lambda n: math.dist(n, (x, y)), default=None)
            below = near is not None and near[1] > y          # the nearest road name is above: the label goes below
            gap = (13 if site else 8) * (-1 if below else 1)
            ax.annotate(str(p["name"]), (x, y), xytext=(0, gap), textcoords="offset points", ha="center",
                        va="top" if below else "bottom", fontsize=9 if site else 7.5,
                        fontweight="bold" if site else "normal", color=accent if site else ink, zorder=8, bbox=_PLATE)
    ax.margins(0.08)
    _fit(ax, block, 0.12 if data.get("north") is not None else 0.0)   # a clear strip down the side for the north arrow
    if data.get("north") is not None:                 # a north arrow in the corner, turned by "north" degrees clockwise
        a = math.radians(float(data["north"]))
        dx, dy = 0.07 * math.sin(a), 0.07 * math.cos(a) * (block.width / block.height)
        ax.annotate("", xy=(0.95 + dx, 0.84 + dy), xytext=(0.95 - dx, 0.84 - dy), xycoords="axes fraction",
                    arrowprops=dict(arrowstyle="-|>", color=ink, lw=1.4), zorder=9)
        from ..layout.factory import _is_rtl
        arabic = any(_is_rtl(str(x.get("name", ""))) for x in roads + places)
        ax.text(0.95 + dx * 1.6, 0.84 + dy * 1.6, "ش" if arabic else "N", transform=ax.transAxes, ha="center", va="center", fontsize=8,
                fontweight="bold", color=ink, zorder=9)
    if data.get("note"):
        fig.text(0.5, 0.01, str(data["note"]), ha="center", fontsize=7, color=muted)
    return fig


# ── mind map ───────────────────────────────────────────────────────────────────────────

def _children(node):
    """[(label, children)] of a dict of branches, a list of leaves, or nothing."""
    if isinstance(node, dict):
        return [(str(k), v) for k, v in node.items()]
    if isinstance(node, (list, tuple)):
        return [(str(x), None) if not isinstance(x, dict) else next(iter((str(k), v) for k, v in x.items())) for x in node]
    return []


def _leaves(node) -> int:
    kids = _children(node)
    return sum(_leaves(c) for _, c in kids) if kids else 1


def render_mindmap(block, theme):
    data = block.data
    if not isinstance(data, dict) or len(data) != 1:
        raise ValueError('a mind map has one topic: {"Topic": {"Branch": ["leaf", ...], ...}}')
    (topic, branches), = data.items()
    branches = _children(branches)
    if not branches:
        raise ValueError("the mind map's topic has no branches")
    from .chart import _colors
    colors = _colors(block, len(branches))
    _, _, ink, _ = _palette(theme)
    fig, ax = plt.subplots(figsize=(block.width, block.height))
    ax.axis("off")
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold", pad=10)
    # branches alternate sides, each taking height by its leaves
    sides = {1: [], -1: []}
    for i, b in enumerate(branches):
        sides[1 if i % 2 == 0 else -1].append((i, b))
    span = max(sum(_leaves(c) for _, (_, c) in side) for side in sides.values()) or 1

    def curve(x0, y0, x1, y1, color, width):
        t = [k / 20 for k in range(21)]
        mid = (x0 + x1) / 2
        ax.plot([(1 - u) ** 3 * x0 + 3 * (1 - u) ** 2 * u * mid + 3 * (1 - u) * u ** 2 * mid + u ** 3 * x1 for u in t],
                [(1 - u) ** 3 * y0 + 3 * (1 - u) ** 2 * u * y0 + 3 * (1 - u) * u ** 2 * y1 + u ** 3 * y1 for u in t],
                color=color, linewidth=width, solid_capstyle="round", zorder=1)

    def place(node, label, depth, sign, top, height, color, parent):
        y = top - height / 2
        x = sign * (1.0 + (depth - 1) * 1.15)
        curve(parent[0], parent[1], x, y, color, 2.6 if depth == 1 else 1.3)
        kids = _children(node)
        if depth == 1:
            ax.text(x, y, label, ha="center", va="center", fontsize=8.5, fontweight="bold", color="white", zorder=3,
                    bbox=dict(boxstyle="round,pad=0.45", facecolor=color, edgecolor="none"))
        else:
            ax.text(x + sign * 0.06, y, label, ha="left" if sign > 0 else "right", va="center", fontsize=7.5, color=ink, zorder=3)
        total = sum(_leaves(c) for _, c in kids) or 1
        for kl, kc in kids:
            h = height * _leaves(kc) / total
            place(kc, kl, depth + 1, sign, top, h, color, (x + sign * (0.42 if depth == 1 else 0.0), y))
            top -= h

    for sign, side in sides.items():
        total = sum(_leaves(c) for _, (_, c) in side) or 1
        top = total / 2
        for i, (label, kids) in side:
            h = _leaves(kids)
            place(kids, label, 1, sign, top, h, colors[i], (0.0, 0.0))
            top -= h
    ax.text(0, 0, str(topic), ha="center", va="center", fontsize=10.5, fontweight="bold", color="white", zorder=4,
            bbox=dict(boxstyle="round,pad=0.7", facecolor=ink, edgecolor="none"))
    depth = max((2 if _children(c) else 1) + (1 if any(_children(k) for _, k in _children(c)) else 0) for _, c in branches)
    ax.set_xlim(-(1.0 + depth * 1.15), 1.0 + depth * 1.15)
    ax.set_ylim(-span / 2 - 0.6, span / 2 + 0.6)
    return fig
