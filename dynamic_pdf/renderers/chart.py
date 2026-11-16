"""
Chart renderer — converts ChartBlock → matplotlib figure → SVG → ReportLab Drawing.

Supported chart types:
    bar, horizontal_bar, grouped_bar, stacked_bar
    line, area
    pie, donut
    scatter, bubble
    histogram
    heatmap
    waterfall
    funnel
    gauge
    sparkline
    treemap
"""
from ..utils.errors import BlockRenderError

import io
import re
import os
import math
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.text
import numpy as np
from svglib.svglib import svg2rlg


# ─── Helpers ──────────────────────────────────────────────────────────────────

# twelve distinct hues: the old list repeated red, green, orange and blue from its seventh colour
_FALLBACK_COLORS = [
    "#4f81bd", "#c0504d", "#9bbb59", "#8064a2",
    "#4bacc6", "#f79646", "#8c564b", "#e377c2",
    "#7f7f7f", "#bcbd22", "#1f3a5f", "#f2c80f",
]


def _colors(block, n: int) -> list:
    """n colours: the author's, repeated as given, or the palette, which never repeats a
    colour: past its end come lighter, then darker, versions of each hue."""
    if block.colors:
        return [block.colors[i % len(block.colors)] for i in range(n)]
    base = _FALLBACK_COLORS
    out = []
    for i in range(n):
        tier, hue = divmod(i, len(base))
        if tier == 0:
            out.append(base[hue])
        else:
            rgb = mcolors.to_rgb(base[hue])
            towards = 1.0 if tier % 2 else 0.0          # lighter, darker, lighter ...
            mix = min(0.75, 0.38 * ((tier + 1) // 2))
            out.append(mcolors.to_hex([c + (towards - c) * mix for c in rgb]))
    return out


# ─── Numbers as the document writes them ───────────────────────────────────────

_ARABIC_DIGITS = str.maketrans("0123456789,.-%", "٠١٢٣٤٥٦٧٨٩٬٫-٪")


def _digits() -> str:
    """"arabic" when the document being rendered writes its figures in Arabic-Indic digits."""
    from .. import policy as _policy
    col = _policy._current.get()
    return getattr(col, "digits", "western") if col is not None else "western"


def _decimals(values) -> int:
    """Decimal places the data shows, at most 2."""
    out = 0
    for v in values:
        text = f"{float(v):.6f}".rstrip("0")
        out = max(out, len(text.split(".")[1]) if "." in text else 0)
    return min(out, 2)


def _num(v, decimals: int = 0, sign: bool = False, percent: bool = False) -> str:
    """A figure with thousands separators, in the document's digits."""
    text = f"{float(v):{'+' if sign else ''},.{decimals}f}" + ("%" if percent else "")
    return text.translate(_ARABIC_DIGITS) if _digits() == "arabic" else text


def _value_axis(axis) -> None:
    """Tick labels in the same format as the values."""
    from matplotlib.ticker import FuncFormatter
    axis.set_major_formatter(FuncFormatter(
        lambda v, _: _num(v, 0 if abs(v - round(v)) < 1e-9 else min(2, len(f"{v:.6g}".split(".")[-1])))))


# ─── What each chart can show ──────────────────────────────────────────────────

_ONE_SERIES = {"bar", "horizontal_bar", "pie", "donut", "funnel", "waterfall", "treemap", "sparkline",
               "histogram"}
_PARTS = {"pie", "donut", "funnel", "treemap"}       # parts of a whole: no negatives, not all zero


def _is_num(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return math.isfinite(v)
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _check_data(key: str, data) -> None:
    """Refuse data that the chart type cannot draw truthfully, saying what it needs."""
    if key in ("gauge", "scatter", "bubble", "heatmap"):
        return                                        # these check their own shapes
    if data is None or (hasattr(data, "__len__") and len(data) == 0):
        raise ValueError(f"{key} chart has no data")
    if key in _ONE_SERIES and isinstance(data, dict) and (
            "series" in data or any(isinstance(v, (dict, list, tuple)) for v in data.values())):
        names = list(data.get("series", data))[:4]
        raise ValueError(f"{key} chart shows one series {{label: value}}; got several ({', '.join(map(str, names))})"
                         " — use grouped_bar, stacked_bar or line for several series")
    if key in _ONE_SERIES or (isinstance(data, dict) and "series" not in data and
                              not any(isinstance(v, dict) for v in data.values())):
        labels, raw = _raw_pairs(data)
        bad = [f"{lab}={val!r}" for lab, val in zip(labels, raw) if not _is_num(val)]
        if bad:
            raise ValueError(f"{key} chart values must be numbers; got {', '.join(bad[:3])}")
        if key in _PARTS:
            neg = [f"{lab}={val}" for lab, val in zip(labels, raw) if float(val) < 0]
            if neg:
                raise ValueError(f"a {key} chart shows parts of a whole and cannot show negative values "
                                 f"({', '.join(neg[:3])}); use a bar chart")
            if not any(float(v) for v in raw):
                raise ValueError(f"every value of the {key} chart is zero: there is no whole to divide")


def _raw_pairs(data):
    if isinstance(data, dict):
        return [str(k) for k in data], list(data.values())
    if isinstance(data, (list, tuple)):
        if data and isinstance(data[0], dict):
            return [str(d.get("label", i)) for i, d in enumerate(data)], [d.get("value") for d in data]
        return [str(i) for i in range(len(data))], list(data)
    return ["data"], [data]


def _style_ax(ax, theme=None):
    """Strip chartjunk; apply neutral grid."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#d0d0d0")
    ax.spines["bottom"].set_color("#d0d0d0")
    ax.tick_params(colors="#555555", labelsize=8.5)
    ax.set_facecolor("#ffffff")
    ax.yaxis.grid(True, color="#eeeeee", linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)


def _add_legend(ax, **kwargs):
    """Add legend only when the axes contain labeled artists."""
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) > 1:                 # one series is named by the title; a legend would cover data
        ax.legend(fontsize=8, framealpha=0.7, **kwargs)


def _label_axes(ax, block):
    if block.x_label:
        ax.set_xlabel(block.x_label, fontsize=9, color="#444444")
    if block.y_label:
        ax.set_ylabel(block.y_label, fontsize=9, color="#444444")
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=10)


_ARABIC_TEXT = re.compile("[؀-ۿݐ-ݿ]")


def _arabic_face() -> str:
    """Register the bundled Arabic face with Matplotlib once; returns its family name."""
    from matplotlib import font_manager
    from ..fonts.manager import BUNDLED_DIR, current_arabic_face, font_catalog
    name = current_arabic_face()
    if not any(f.name == name for f in font_manager.fontManager.ttflist):
        files = font_catalog().get(name, {}).get("files", {}).values() or ("Amiri-Regular.ttf", "Amiri-Bold.ttf")
        for file in files:
            font_manager.fontManager.addfont(os.path.join(BUNDLED_DIR, file))
    return name


def _visual(text: str) -> str:
    """Matplotlib has no shaping or bidi: give it joined letters in visual order, line by line."""
    from ..layout.factory import _apply_rtl, _is_rtl
    return "\n".join(_apply_rtl(line, "R" if _is_rtl(line) else "L") if _ARABIC_TEXT.search(line) else line
                     for line in text.split("\n"))


def _shape_arabic(fig, block) -> None:
    """Shape every piece of Arabic text in a finished figure: title, axis labels,
    tick labels, legend entries and annotations. Figures without Arabic are untouched."""
    if _digits() != "arabic" and not _ARABIC_TEXT.search(str(block.data) + "".join(
            str(getattr(block, k, "") or "") for k in ("title", "x_label", "y_label"))):
        return
    face = _arabic_face()
    fig.canvas.draw()                  # tick labels only exist once the axes are laid out
    done = set()
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            ticks = axis.get_ticklabels()
            if any(_ARABIC_TEXT.search(t.get_text()) for t in ticks):
                axis.set_ticks(axis.get_ticklocs())
                axis.set_ticklabels([_visual(t.get_text()) for t in ticks])
                for t in axis.get_ticklabels():
                    t.set_fontfamily(face)
                    done.add(id(t))
    for t in fig.findobj(matplotlib.text.Text):
        if id(t) not in done and _ARABIC_TEXT.search(t.get_text()):
            t.set_text(_visual(t.get_text()))
            t.set_fontfamily(face)


def _fig(block):
    """Create a figure sized by block.width/height (inches)."""
    return plt.subplots(figsize=(block.width, block.height))


def _fig_to_drawing(fig, block, theme):
    """Serialize fig → SVG → ReportLab Drawing, scaled to block.width pts."""
    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
        tf.write(buf.getvalue())
        tf_name = tf.name

    drawing = svg2rlg(tf_name)
    os.unlink(tf_name)

    if drawing and drawing.width:
        target_w = block.width * 72          # inches → pt
        scale = target_w / drawing.width
        drawing.width = target_w
        drawing.height = drawing.height * scale
        drawing.transform = (scale, 0, 0, scale, 0, 0)
        drawing.hAlign = "CENTER"

    return drawing


# ─── Data parsers ─────────────────────────────────────────────────────────────

def _simple(data) -> tuple:
    """Parse {label: value} | [value] | [{label,value}] → (labels, values)."""
    if isinstance(data, dict):
        return list(data.keys()), [float(v) for v in data.values()]
    if isinstance(data, (list, tuple)):
        if not data:
            return [], []
        if isinstance(data[0], dict):
            labels = [str(d.get("label", i)) for i, d in enumerate(data)]
            values = [float(d.get("value", 0)) for d in data]
            return labels, values
        return [str(i) for i in range(len(data))], [float(v) for v in data]
    return [], []


def _multi_series(data) -> tuple:
    """
    Parse multi-series data → (categories, {series_name: [values]}).

    Accepts:
        {"categories": [...], "series": {"A": [...], "B": [...]}}
        {"A": {"Q1": 1, "Q2": 2}, "B": {"Q1": 3, "Q2": 4}}
    """
    if isinstance(data, dict):
        if "series" in data and "categories" in data:
            return data["categories"], data["series"]
        # Detect nested dicts → series
        first = next(iter(data.values()))
        if isinstance(first, dict):
            all_cats = []
            for v in data.values():
                for k in v:
                    if k not in all_cats:
                        all_cats.append(k)
            series = {name: [float(vals.get(c, 0)) for c in all_cats]
                      for name, vals in data.items()}
            return all_cats, series
    # Fallback: treat as simple single series
    labels, values = _simple(data)
    return labels, {"Series": values}


# ─── Individual renderers ──────────────────────────────────────────────────────

def _bar(block, theme):
    labels, values = _simple(block.data)
    fig, ax = _fig(block)
    c = _colors(block, len(labels))
    bars = ax.bar(labels, values, color=c, width=0.6, zorder=3)
    dec = _decimals(values)
    ax.bar_label(bars, labels=[_num(v, dec) for v in values], padding=3, fontsize=8, color="#444444")
    _style_ax(ax, theme)
    _value_axis(ax.yaxis)
    _label_axes(ax, block)
    # one series: each bar is named on its axis, so no legend repeats the labels over the bars
    fig.tight_layout()
    return fig


def _horizontal_bar(block, theme):
    labels, values = _simple(block.data)
    fig, ax = _fig(block)
    c = _colors(block, len(labels))
    bars = ax.barh(labels, values, color=c, height=0.6, zorder=3)
    ax.bar_label(bars, labels=[_num(v, _decimals(values)) for v in values], padding=3, fontsize=8, color="#444444")
    _value_axis(ax.xaxis)
    ax.spines["left"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#d0d0d0")
    ax.tick_params(colors="#555555", labelsize=8.5)
    ax.set_facecolor("#ffffff")
    ax.xaxis.grid(True, color="#eeeeee", linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    _label_axes(ax, block)
    fig.tight_layout()
    return fig


def _grouped_bar(block, theme):
    cats, series = _multi_series(block.data)
    names = list(series.keys())
    x = np.arange(len(cats))
    w = 0.8 / len(names)
    c = _colors(block, len(names))
    fig, ax = _fig(block)
    for i, (name, vals) in enumerate(series.items()):
        offset = (i - len(names) / 2 + 0.5) * w
        bars = ax.bar(x + offset, vals, w, label=name, color=c[i], zorder=3)
        ax.bar_label(bars, labels=[_num(v, _decimals(vals)) for v in vals], padding=2, fontsize=7,
                     color="#444444")
    ax.set_xticks(x)
    ax.set_xticklabels(cats, rotation=15 if len(cats) > 5 else 0, ha="right")
    _style_ax(ax, theme)
    _label_axes(ax, block)
    if block.legend:
        _add_legend(ax)
    fig.tight_layout()
    return fig


def _stacked_bar(block, theme):
    cats, series = _multi_series(block.data)
    names = list(series.keys())
    x = np.arange(len(cats))
    c = _colors(block, len(names))
    fig, ax = _fig(block)
    bottoms = np.zeros(len(cats))
    for i, (name, vals) in enumerate(series.items()):
        vals = np.array(vals, dtype=float)
        ax.bar(x, vals, bottom=bottoms, label=name, color=c[i], width=0.6, zorder=3)
        bottoms += vals
    ax.set_xticks(x)
    ax.set_xticklabels(cats, rotation=15 if len(cats) > 5 else 0, ha="right")
    _style_ax(ax, theme)
    _label_axes(ax, block)
    if block.legend:
        _add_legend(ax)
    fig.tight_layout()
    return fig


def _line(block, theme):
    data = block.data
    fig, ax = _fig(block)
    # Multi-series or single
    if isinstance(data, dict) and data and isinstance(next(iter(data.values())), dict):
        cats, series = _multi_series(data)
        c = _colors(block, len(series))
        x = np.arange(len(cats))
        for i, (name, vals) in enumerate(series.items()):
            ax.plot(x, vals, marker="o", markersize=4, linewidth=2,
                    color=c[i], label=name, zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(cats, rotation=15 if len(cats) > 5 else 0, ha="right")
    else:
        labels, values = _simple(data)
        x = np.arange(len(labels))
        c = _colors(block, 1)
        ax.plot(x, values, marker="o", markersize=4, linewidth=2, color=c[0], zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15 if len(labels) > 5 else 0, ha="right")
    _style_ax(ax, theme)
    _label_axes(ax, block)
    if block.legend:
        _add_legend(ax)
    fig.tight_layout()
    return fig


def _area(block, theme):
    data = block.data
    fig, ax = _fig(block)
    if isinstance(data, dict) and data and isinstance(next(iter(data.values())), dict):
        cats, series = _multi_series(data)
        c = _colors(block, len(series))
        x = np.arange(len(cats))
        bottoms = np.zeros(len(cats))
        for i, (name, vals) in enumerate(series.items()):
            vals = np.array(vals, dtype=float)
            ax.fill_between(x, bottoms, bottoms + vals,
                            alpha=0.7, color=c[i], label=name, zorder=3)
            ax.plot(x, bottoms + vals, color=c[i], linewidth=1.2, zorder=4)
            bottoms += vals
        ax.set_xticks(x)
        ax.set_xticklabels(cats, rotation=15 if len(cats) > 5 else 0, ha="right")
    else:
        labels, values = _simple(data)
        x = np.arange(len(labels))
        c = _colors(block, 1)
        ax.fill_between(x, values, alpha=0.4, color=c[0], zorder=2)
        ax.plot(x, values, marker="o", markersize=4, linewidth=2, color=c[0], zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15 if len(labels) > 5 else 0, ha="right")
    _style_ax(ax, theme)
    _label_axes(ax, block)
    if block.legend:
        _add_legend(ax)
    fig.tight_layout()
    return fig


def _pie(block, theme):
    labels, values = _simple(block.data)
    c = _colors(block, len(labels))
    fig, ax = plt.subplots(figsize=(block.width, block.height))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, colors=c,
        autopct=lambda p: _num(p, 1, percent=True), startangle=90,
        pctdistance=0.82,
        wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
    )
    for t in autotexts:
        t.set_fontsize(8)
        t.set_color("white")
    for t in texts:
        t.set_fontsize(9)
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=10)
    fig.tight_layout()
    return fig


def _donut(block, theme):
    labels, values = _simple(block.data)
    c = _colors(block, len(labels))
    fig, ax = plt.subplots(figsize=(block.width, block.height))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, colors=c,
        autopct=lambda p: _num(p, 1, percent=True), startangle=90,
        pctdistance=0.78,
        wedgeprops={"linewidth": 1.5, "edgecolor": "white", "width": 0.5},
    )
    for t in autotexts:
        t.set_fontsize(8)
        t.set_color("#333333")
    for t in texts:
        t.set_fontsize(9)
    if block.title:
        ax.text(0, 0, block.title, ha="center", va="center",
                fontsize=10, fontweight="bold", color="#222222")
    fig.tight_layout()
    return fig


def _scatter(block, theme):
    data = block.data
    fig, ax = _fig(block)
    c = _colors(block, 1)
    # Accepts: [{x,y}] | {x:[..], y:[..]} | {series: [{x,y}]}
    if isinstance(data, list):
        xs = [float(d.get("x", i)) for i, d in enumerate(data)]
        ys = [float(d.get("y", 0)) for d in data]
        ax.scatter(xs, ys, color=c[0], alpha=0.7, edgecolors="white",
                   linewidths=0.5, s=50, zorder=3)
    elif isinstance(data, dict):
        if "x" in data and "y" in data:
            ax.scatter(data["x"], data["y"], color=c[0], alpha=0.7,
                       edgecolors="white", linewidths=0.5, s=50, zorder=3)
        else:
            # Multi-series scatter
            palette = _colors(block, len(data))
            for i, (name, pts) in enumerate(data.items()):
                if isinstance(pts, list):
                    xs = [float(p.get("x", j)) for j, p in enumerate(pts)]
                    ys = [float(p.get("y", 0)) for p in pts]
                elif isinstance(pts, dict):
                    xs, ys = pts.get("x", []), pts.get("y", [])
                else:
                    continue
                ax.scatter(xs, ys, color=palette[i], alpha=0.7,
                           edgecolors="white", linewidths=0.5, s=50,
                           label=name, zorder=3)
            if block.legend:
                _add_legend(ax)
    _style_ax(ax, theme)
    _label_axes(ax, block)
    fig.tight_layout()
    return fig


def _bubble(block, theme):
    """data: [{x, y, size, label?}] or {series: [{x,y,size}]}"""
    data = block.data
    fig, ax = _fig(block)
    if isinstance(data, list):
        c = _colors(block, len(data))
        for i, d in enumerate(data):
            size = float(d.get("size", 10)) * 20
            ax.scatter(float(d.get("x", i)), float(d.get("y", 0)),
                       s=size, color=c[i], alpha=0.6,
                       edgecolors="white", linewidths=0.5, zorder=3)
            if "label" in d:
                ax.annotate(d["label"],
                            (float(d.get("x", i)), float(d.get("y", 0))),
                            fontsize=7.5, ha="center", va="center", color="#333")
    elif isinstance(data, dict):
        palette = _colors(block, len(data))
        for i, (name, pts) in enumerate(data.items()):
            pts = pts if isinstance(pts, list) else [pts]
            xs = [float(p.get("x", j)) for j, p in enumerate(pts)]
            ys = [float(p.get("y", 0)) for p in pts]
            ss = [float(p.get("size", 5)) * 20 for p in pts]
            ax.scatter(xs, ys, s=ss, color=palette[i], alpha=0.6,
                       edgecolors="white", linewidths=0.5, label=name, zorder=3)
        if block.legend:
            _add_legend(ax)
    _style_ax(ax, theme)
    _label_axes(ax, block)
    fig.tight_layout()
    return fig


def _histogram(block, theme):
    """data: [values] or {label: value} (values used as raw samples)."""
    data = block.data
    if isinstance(data, (list, tuple)):
        values = [float(v) for v in data]
    else:
        _, values = _simple(data)
    c = _colors(block, 1)
    fig, ax = _fig(block)
    n_bins = max(5, int(math.sqrt(len(values)))) if values else 10
    ax.hist(values, bins=n_bins, color=c[0], edgecolor="white",
            linewidth=0.8, zorder=3)
    _style_ax(ax, theme)
    _label_axes(ax, block)
    fig.tight_layout()
    return fig


def _heatmap(block, theme):
    """
    data: {rows: [...], cols: [...], values: [[...]]}
       or 2D list [[...], [...]]
    """
    data = block.data
    if isinstance(data, dict) and "values" in data:
        matrix = np.array(data["values"], dtype=float)
        row_labels = data.get("rows", [str(i) for i in range(matrix.shape[0])])
        col_labels = data.get("cols", [str(i) for i in range(matrix.shape[1])])
    elif isinstance(data, list):
        matrix = np.array(data, dtype=float)
        row_labels = [str(i) for i in range(matrix.shape[0])]
        col_labels = [str(i) for i in range(matrix.shape[1])]
    else:
        matrix = np.array([[0]])
        row_labels, col_labels = [""], [""]

    c = _colors(block, 1)
    # Build a colormap from white → primary color
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "theme_heat", ["#ffffff", c[0]])

    fig, ax = _fig(block)
    im = ax.imshow(matrix, cmap=cmap, aspect="auto")
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, fontsize=8.5, rotation=30, ha="right")
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=8.5)
    plt.colorbar(im, ax=ax, fraction=0.04, pad=0.04)
    # Annotate cells
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            val = matrix[i, j]
            text_color = "white" if val > (matrix.max() * 0.6) else "#333333"
            ax.text(j, i, f"{val:.4g}", ha="center", va="center",
                    fontsize=7.5, color=text_color)
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    return fig


def _waterfall(block, theme):
    """
    data: {label: value, ...}
    The last key is always rendered as the total (full bar from 0).
    Positive deltas are green, negative are red, total uses primary color.
    """
    labels, values = _simple(block.data)
    c = _colors(block, 1)
    positive_c = "#4caf50"
    negative_c = "#f44336"
    total_c = c[0]

    running = 0.0
    bottoms = []
    bar_heights = []
    bar_colors = []

    for i, (label, val) in enumerate(zip(labels, values)):
        is_last = (i == len(labels) - 1)
        if is_last:
            bottoms.append(0)
            bar_heights.append(val)
            bar_colors.append(total_c)
        else:
            bottoms.append(running if val >= 0 else running + val)
            bar_heights.append(abs(val))
            bar_colors.append(positive_c if val >= 0 else negative_c)
            running += val

    fig, ax = _fig(block)
    x = np.arange(len(labels))
    bars = ax.bar(x, bar_heights, bottom=bottoms, color=bar_colors,
                  width=0.6, edgecolor="white", linewidth=0.8, zorder=3)
    # Connector lines
    for i in range(len(labels) - 1):
        top = bottoms[i] + bar_heights[i]
        ax.plot([x[i] + 0.3, x[i + 1] - 0.3], [top, top],
                color="#aaaaaa", linewidth=0.8, linestyle="--", zorder=2)
    dec = _decimals(values)
    ax.bar_label(bars, labels=[_num(v, dec, sign=True) if i < len(labels) - 1 else _num(v, dec)
                                for i, v in enumerate(values)],
                 padding=3, fontsize=8, color="#444444")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15 if len(labels) > 5 else 0, ha="right")
    _style_ax(ax, theme)
    _label_axes(ax, block)
    fig.tight_layout()
    return fig


def _funnel(block, theme):
    """data: {label: value} — renders as a horizontal funnel (largest → smallest)."""
    labels, values = _simple(block.data)
    # Sort descending
    pairs = sorted(zip(labels, values), key=lambda p: p[1], reverse=True)
    labels = [p[0] for p in pairs]
    values = [p[1] for p in pairs]

    c = _colors(block, len(labels))
    max_val = max(values) if values else 1
    fig, ax = plt.subplots(figsize=(block.width, block.height))
    ax.set_facecolor("#ffffff")
    ax.set_ylim(-0.5, len(labels) - 0.5)
    dec = _decimals(values)
    texts = [f"{label}  {_num(val, dec)}" for label, val in zip(labels, values)]
    # width of a label as a share of the widest stage (9 pt bold, about 0.6 em a character)
    span_pt = block.width * 72 * 0.9
    share = [len(t) * 9 * 0.6 / span_pt for t in texts]
    right = max_val * 1.05
    for i, (label, val) in enumerate(zip(labels, values)):
        y = len(labels) - 1 - i
        left = (max_val - val) / 2
        ax.barh(y, val, left=left, height=0.7, color=c[i], edgecolor="white", linewidth=0.8, zorder=3)
        if val / max_val >= share[i] + 0.06:
            ax.text(max_val / 2, y, texts[i], ha="center", va="center", fontsize=9,
                    color="white", fontweight="bold", zorder=4)
        else:                          # too narrow for its label: set beside the stage, readable
            x = left + val + max_val * 0.03
            ax.text(x, y, texts[i], ha="left", va="center", fontsize=9, color="#333333",
                    fontweight="bold", zorder=4)
            right = max(right, x + share[i] * max_val * 1.1)
    ax.set_xlim(-max_val * 0.05, right)

    ax.set_yticks([])
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=10)
    fig.tight_layout()
    return fig


def _gauge(block, theme):
    """
    data: float (0–100) | {value, min?, max?, label?}
    Renders a semicircular gauge.
    """
    data = block.data
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    if numeric(data):
        val, vmin, vmax, inner_label = float(data), 0.0, 100.0, ""
    elif isinstance(data, dict) and "value" in data:
        val = float(data["value"])
        vmin = float(data.get("min", 0))
        vmax = float(data.get("max", 100))
        inner_label = str(data.get("label", ""))
    elif isinstance(data, dict) and len(data) == 1 and numeric(next(iter(data.values()))):
        # {label: value}, the shape every other single-series chart takes
        (inner_label, val), = data.items()
        val, vmin, vmax, inner_label = float(val), 0.0, 100.0, str(inner_label)
    else:
        # drawing 0 would show a reading the author never gave
        raise ValueError("gauge data must be a number, {'value': n, 'min'?: n, 'max'?: n, 'label'?: text} "
                         f"or {{label: n}}; got {type(data).__name__} {str(data)[:60]!r}")

    pct = max(0.0, min(1.0, (val - vmin) / (vmax - vmin) if vmax != vmin else 0))
    c = _colors(block, 1)

    fig, ax = plt.subplots(figsize=(block.width, block.height / 1.4),
                           subplot_kw={"aspect": "equal"})
    ax.set_facecolor("#ffffff")
    fig.patch.set_facecolor("#ffffff")

    # Background arc
    theta_bg = np.linspace(np.pi, 0, 200)
    ax.plot(np.cos(theta_bg), np.sin(theta_bg),
            color="#e0e0e0", linewidth=18, solid_capstyle="round")
    # Value arc
    theta_val = np.linspace(np.pi, np.pi - pct * np.pi, 200)
    ax.plot(np.cos(theta_val), np.sin(theta_val),
            color=c[0], linewidth=18, solid_capstyle="round")
    # Needle
    angle = np.pi - pct * np.pi
    ax.annotate("", xy=(0.6 * np.cos(angle), 0.6 * np.sin(angle)),
                xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color="#333333", lw=2))
    ax.plot(0, 0, "o", color="#333333", markersize=8, zorder=5)

    # Labels
    ax.text(0, -0.15, _num(val, _decimals([val])), ha="center", va="center",
            fontsize=18, fontweight="bold", color="#222222")
    ax.text(0, -0.38, inner_label, ha="center", va="center",
            fontsize=9, color="#666666")
    ax.text(-1.1, -0.05, _num(vmin, _decimals([vmin])), ha="center", fontsize=8, color="#888888")
    ax.text(1.1, -0.05, _num(vmax, _decimals([vmax])), ha="center", fontsize=8, color="#888888")

    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-0.5, 1.15)
    ax.axis("off")
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=6)
    fig.tight_layout()
    return fig


def _sparkline(block, theme):
    """
    Minimal line chart — no axes, no labels, no title.
    data: {label: value} | [value]
    """
    _, values = _simple(block.data)
    c = _colors(block, 1)
    fig, ax = plt.subplots(figsize=(block.width, block.height))
    ax.plot(values, color=c[0], linewidth=2, zorder=3)
    ax.fill_between(range(len(values)), values, alpha=0.15, color=c[0], zorder=2)
    ax.axis("off")
    fig.patch.set_alpha(0)
    fig.tight_layout(pad=0.2)
    return fig


def _treemap(block, theme):
    """
    data: {label: value} — squarified treemap using recursive bisection.
    Falls back gracefully to a sorted horizontal bar if data has < 2 items.
    """
    labels, values = _simple(block.data)
    if len(values) < 2:
        # Too few segments for a treemap — render as bar
        return _bar(block, theme)

    total = sum(values)
    if total == 0:
        return _bar(block, theme)

    c = _colors(block, len(labels))
    fig, ax = plt.subplots(figsize=(block.width, block.height))
    ax.set_facecolor("#ffffff")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Simple squarify via recursive bisection
    def _squarify(items, x, y, w, h):
        """items: list of (label, normalized_value, color)"""
        if not items:
            return
        if len(items) == 1:
            label, val, col = items[0]
            rect = mpatches.FancyBboxPatch(
                (x + 0.002, y + 0.002), w - 0.004, h - 0.004,
                boxstyle="round,pad=0.005",
                facecolor=col, edgecolor="white", linewidth=1.5,
            )
            ax.add_patch(rect)
            if w > 0.08 and h > 0.05:
                ax.text(x + w / 2, y + h / 2, f"{label}\n{val * total:.4g}",
                        ha="center", va="center", fontsize=7.5,
                        color="white", fontweight="bold", wrap=True)
            return

        # Split at midpoint by area
        total_here = sum(v for _, v, _ in items)
        half = total_here / 2
        split, acc = 0, 0
        for i, (_, v, _) in enumerate(items):
            acc += v
            split = i + 1
            if acc >= half:
                break

        first_half = items[:split]
        second_half = items[split:]
        ratio = sum(v for _, v, _ in first_half) / total_here

        if w >= h:
            _squarify(first_half, x, y, w * ratio, h)
            _squarify(second_half, x + w * ratio, y, w * (1 - ratio), h)
        else:
            _squarify(first_half, x, y + h * (1 - ratio), w, h * ratio)
            _squarify(second_half, x, y, w, h * (1 - ratio))

    normed = [v / total for v in values]
    items = sorted(zip(labels, normed, c), key=lambda x: x[1], reverse=True)
    _squarify(list(items), 0, 0, 1, 1)

    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=10)
    fig.tight_layout()
    return fig


# ─── Dispatcher ───────────────────────────────────────────────────────────────

_RENDERERS = {
    "bar":            _bar,
    "vertical_bar":   _bar,
    "horizontal_bar": _horizontal_bar,
    "grouped_bar":    _grouped_bar,
    "stacked_bar":    _stacked_bar,
    "line":           _line,
    "area":           _area,
    "pie":            _pie,
    "donut":          _donut,
    "scatter":        _scatter,
    "bubble":         _bubble,
    "histogram":      _histogram,
    "heatmap":        _heatmap,
    "waterfall":      _waterfall,
    "funnel":         _funnel,
    "gauge":          _gauge,
    "sparkline":      _sparkline,
    "treemap":        _treemap,
}


def _sized(block):
    """Apply a composer ``figure_size`` hint (inches): the chart is *re-drawn* at
    that size, so its text keeps its native point size (unlike scaling)."""
    size = (getattr(block, "hints", None) or {}).get("figure_size")
    if not size:
        return block
    w, h = size
    return block.model_copy(update={"width": float(w), "height": float(h)})


def render_chart(block, theme):
    block = _sized(block)
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors as rl_colors

    try:
        key = block.chart_type.lower().replace("-", "_").replace(" ", "_")
        renderer = _RENDERERS.get(key)
        if renderer is None:
            raise BlockRenderError(
                "chart", f'unsupported type "{block.chart_type}"; supported: {", ".join(_RENDERERS)}')

        _check_data(key, block.data)
        fig = renderer(block, theme)
        _shape_arabic(fig, block)
        drawing = _fig_to_drawing(fig, block, theme)

        if drawing:
            from reportlab.platypus import Spacer
            gap = getattr(getattr(theme, "spacing", None), "block_gap", 12)
            flowables = [drawing, Spacer(1, gap)]
            return flowables

        raise BlockRenderError("chart", f"{block.chart_type}: SVG conversion failed")

    except BlockRenderError:
        raise
    except Exception as exc:
        # Surface through the caller's error policy (strict → raise,
        # permissive → diagnostic + visible marker); never silently swallow.
        raise BlockRenderError("chart", f"{block.chart_type}: {type(exc).__name__}: {exc}", exc) from exc


def chart_png(block, theme, dpi: int = 200) -> bytes:
    """Render a ChartBlock to PNG bytes (used by the DOCX renderer)."""
    import io
    block = _sized(block)
    key = block.chart_type.lower().replace("-", "_").replace(" ", "_")
    renderer = _RENDERERS.get(key)
    if renderer is None:
        raise BlockRenderError(
            "chart", f'unsupported type "{block.chart_type}"; supported: {", ".join(_RENDERERS)}')
    try:
        _check_data(key, block.data)
        fig = renderer(block, theme)
        _shape_arabic(fig, block)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi,
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()
    except BlockRenderError:
        raise
    except Exception as exc:
        raise BlockRenderError("chart", f"{block.chart_type}: {type(exc).__name__}: {exc}", exc) from exc
