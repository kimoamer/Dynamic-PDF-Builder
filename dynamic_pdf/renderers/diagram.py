"""
Diagram renderer -- converts DiagramBlock -> matplotlib figure -> SVG -> ReportLab Drawing.

Supported diagram types:
    flowchart   - directed graph with labeled nodes, edges, and arrows
    tree        - hierarchical tree layout with optional annotations
    network     - undirected or directed network/graph
    state       - state machine diagram with transitions
    sequence    - vertical sequence / swim-lane style
"""

import io
import os
import math
import tempfile

from ..utils.optional import require_matplotlib
matplotlib = require_matplotlib()   # before numpy: both come with the charts extra
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np
from svglib.svglib import svg2rlg


# ── Constants ────────────────────────────────────────────────────────────────

_FALLBACK_COLORS = [
    "#2C3E50", "#2980B9", "#27AE60", "#E74C3C",
    "#8E44AD", "#F39C12", "#1ABC9C", "#E67E22",
]

_NODE_SHAPES = {
    "rect": "s",
    "rounded": "o",
    "diamond": "D",
    "circle": "o",
    "ellipse": "o",
    "hexagon": "H",
    "parallelogram": "d",
    "stadium": "o",
}

_EDGE_STYLES = {
    "solid": "-",
    "dashed": "--",
    "dotted": ":",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

import contextvars as _cv

_PNG_MODE = _cv.ContextVar("dpb_diagram_png", default=False)


def _fig_to_drawing(fig, width_inches, height_inches):
    """Serialize fig -> SVG -> ReportLab Drawing, scaled to fit width and max height.

    In PNG mode (see ``diagram_png``) returns PNG bytes instead (DOCX path).
    """
    if _PNG_MODE.get():
        out = io.BytesIO()
        fig.savefig(out, format="png", bbox_inches="tight",
                    facecolor=fig.get_facecolor(), dpi=200)
        plt.close(fig)
        return out.getvalue()
    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight",
                facecolor=fig.get_facecolor(), dpi=100)
    buf.seek(0)
    plt.close(fig)

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
        tf.write(buf.getvalue())
        tf_name = tf.name

    drawing = svg2rlg(tf_name)
    os.unlink(tf_name)

    if drawing and drawing.width:
        target_w = width_inches * 72
        target_h = height_inches * 72
        scale_w = target_w / drawing.width
        scale_h = target_h / drawing.height if drawing.height else scale_w
        scale = min(scale_w, scale_h)
        drawing.width = drawing.width * scale
        drawing.height = drawing.height * scale
        drawing.transform = (scale, 0, 0, scale, 0, 0)
        drawing.hAlign = "CENTER"

    return drawing


def _parse_nodes(raw_nodes):
    """Normalize node definitions into list of dicts."""
    nodes = []
    for n in raw_nodes:
        if isinstance(n, str):
            nodes.append({"id": n, "label": n})
        elif isinstance(n, dict):
            nd = dict(n)
            if "id" not in nd:
                nd["id"] = nd.get("label", f"n{len(nodes)}")
            if "label" not in nd:
                nd["label"] = nd["id"]
            nodes.append(nd)
    return nodes


def _parse_edges(raw_edges):
    """Normalize edge definitions into list of dicts."""
    edges = []
    for e in raw_edges:
        if isinstance(e, (list, tuple)):
            if len(e) >= 3:
                edges.append({"from": e[0], "to": e[1], "label": str(e[2])})
            else:
                edges.append({"from": e[0], "to": e[1], "label": ""})
        elif isinstance(e, dict):
            ed = dict(e)
            ed.setdefault("label", "")
            edges.append(ed)
    return edges


def _get_node_color(node, colors, idx):
    """Get color for a node."""
    if "color" in node:
        return node["color"]
    return colors[idx % len(colors)]


# ── Layout algorithms ────────────────────────────────────────────────────────

def _layout_flowchart(nodes, edges, direction="TB"):
    """Simple layered layout for flowcharts.
    direction: TB (top-to-bottom) or LR (left-to-right).
    """
    node_ids = [n["id"] for n in nodes]
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}

    # Build adjacency
    children = {nid: [] for nid in node_ids}
    parents = {nid: [] for nid in node_ids}
    for e in edges:
        src, dst = e["from"], e["to"]
        if src in children and dst in parents:
            children[src].append(dst)
            parents[dst].append(src)

    # Assign layers via BFS from roots
    roots = [nid for nid in node_ids if not parents[nid]]
    if not roots:
        roots = [node_ids[0]]

    layers = {}
    queue = list(roots)
    for r in roots:
        layers[r] = 0
    visited = set(roots)

    while queue:
        cur = queue.pop(0)
        for ch in children[cur]:
            new_layer = layers[cur] + 1
            if ch not in layers or new_layer > layers[ch]:
                layers[ch] = new_layer
            if ch not in visited:
                visited.add(ch)
                queue.append(ch)

    # Assign unvisited nodes
    for nid in node_ids:
        if nid not in layers:
            layers[nid] = 0

    # Group by layer
    max_layer = max(layers.values()) if layers else 0
    layer_groups = [[] for _ in range(max_layer + 1)]
    for nid in node_ids:
        layer_groups[layers[nid]].append(nid)

    # Position nodes
    positions = {}
    for layer_idx, group in enumerate(layer_groups):
        n_in_layer = len(group)
        for pos_idx, nid in enumerate(group):
            if direction == "LR":
                x = layer_idx * 2.5
                y = -(pos_idx - (n_in_layer - 1) / 2) * 2.0
            else:
                x = (pos_idx - (n_in_layer - 1) / 2) * 2.5
                y = -layer_idx * 2.0
            positions[nid] = (x, y)

    return positions


def _layout_tree(nodes, edges, direction="TB"):
    """Hierarchical tree layout."""
    node_ids = [n["id"] for n in nodes]
    children_map = {nid: [] for nid in node_ids}
    has_parent = set()
    for e in edges:
        src, dst = e["from"], e["to"]
        if src in children_map:
            children_map[src].append(dst)
            has_parent.add(dst)

    roots = [nid for nid in node_ids if nid not in has_parent]
    if not roots:
        roots = [node_ids[0]]

    positions = {}
    x_counter = [0]

    def _assign(nid, depth):
        kids = children_map.get(nid, [])
        if not kids:
            positions[nid] = (x_counter[0], -depth * 2.0)
            x_counter[0] += 2.0
        else:
            for kid in kids:
                _assign(kid, depth + 1)
            child_xs = [positions[k][0] for k in kids if k in positions]
            if child_xs:
                cx = (min(child_xs) + max(child_xs)) / 2
            else:
                cx = x_counter[0]
                x_counter[0] += 2.0
            positions[nid] = (cx, -depth * 2.0)

    for r in roots:
        _assign(r, 0)

    # Assign unvisited
    for nid in node_ids:
        if nid not in positions:
            positions[nid] = (x_counter[0], 0)
            x_counter[0] += 2.0

    return positions


def _layout_network(nodes, edges):
    """Force-directed-like circular + spring layout using simple iteration."""
    node_ids = [n["id"] for n in nodes]
    n = len(node_ids)
    if n == 0:
        return {}

    # Start with circular layout
    positions = {}
    for i, nid in enumerate(node_ids):
        angle = 2 * math.pi * i / n
        positions[nid] = (math.cos(angle) * 3.0, math.sin(angle) * 3.0)

    # Simple force-directed refinement
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    adj = set()
    for e in edges:
        src, dst = e["from"], e["to"]
        if src in id_to_idx and dst in id_to_idx:
            adj.add((src, dst))

    for _ in range(50):
        forces = {nid: [0.0, 0.0] for nid in node_ids}
        # Repulsion between all pairs
        for i in range(n):
            for j in range(i + 1, n):
                ni, nj = node_ids[i], node_ids[j]
                dx = positions[ni][0] - positions[nj][0]
                dy = positions[ni][1] - positions[nj][1]
                dist = max(math.sqrt(dx * dx + dy * dy), 0.1)
                repel = 4.0 / (dist * dist)
                fx, fy = repel * dx / dist, repel * dy / dist
                forces[ni][0] += fx
                forces[ni][1] += fy
                forces[nj][0] -= fx
                forces[nj][1] -= fy
        # Attraction along edges
        for (src, dst) in adj:
            dx = positions[dst][0] - positions[src][0]
            dy = positions[dst][1] - positions[src][1]
            dist = max(math.sqrt(dx * dx + dy * dy), 0.1)
            attract = 0.3 * (dist - 2.0)
            fx, fy = attract * dx / dist, attract * dy / dist
            forces[src][0] += fx
            forces[src][1] += fy
            forces[dst][0] -= fx
            forces[dst][1] -= fy
        # Apply forces
        for nid in node_ids:
            positions[nid] = (
                positions[nid][0] + forces[nid][0] * 0.1,
                positions[nid][1] + forces[nid][1] * 0.1,
            )

    return positions


# ── Drawing functions ────────────────────────────────────────────────────────

def _draw_node(ax, x, y, label, shape="rounded", color="#2980B9",
               text_color="#FFFFFF", border_color=None, border_style="solid",
               node_width=1.6, node_height=0.7):
    """Draw a single node on the axes."""
    bc = border_color or color

    if shape in ("diamond", "D"):
        diamond = mpatches.FancyBboxPatch(
            (x - node_width / 2, y - node_height / 2),
            node_width, node_height,
            boxstyle=f"round,pad=0.05",
            facecolor=color, edgecolor=bc, linewidth=1.5,
            mutation_aspect=0.7,
        )
        # Use a rotated rectangle to simulate diamond
        from matplotlib.patches import FancyBboxPatch
        diamond = FancyBboxPatch(
            (x - node_width * 0.5, y - node_height * 0.5),
            node_width, node_height,
            boxstyle="round,pad=0.1",
            facecolor=color, edgecolor=bc, linewidth=1.5,
            linestyle=_EDGE_STYLES.get(border_style, "-"),
        )
        ax.add_patch(diamond)
    elif shape in ("circle", "ellipse"):
        ellipse = mpatches.Ellipse(
            (x, y), node_width, node_height,
            facecolor=color, edgecolor=bc, linewidth=1.5,
            linestyle=_EDGE_STYLES.get(border_style, "-"),
        )
        ax.add_patch(ellipse)
    elif shape == "rect":
        rect = mpatches.FancyBboxPatch(
            (x - node_width / 2, y - node_height / 2),
            node_width, node_height,
            boxstyle="square,pad=0.05",
            facecolor=color, edgecolor=bc, linewidth=1.5,
            linestyle=_EDGE_STYLES.get(border_style, "-"),
        )
        ax.add_patch(rect)
    else:  # rounded (default)
        box = mpatches.FancyBboxPatch(
            (x - node_width / 2, y - node_height / 2),
            node_width, node_height,
            boxstyle="round,pad=0.15",
            facecolor=color, edgecolor=bc, linewidth=1.5,
            linestyle=_EDGE_STYLES.get(border_style, "-"),
        )
        ax.add_patch(box)

    # Multi-line label
    lines = label.split("\n")
    fontsize = 8.5 if len(label) > 15 else 9.5
    if len(lines) > 1:
        fontsize = min(fontsize, 8.5)

    ax.text(x, y, label, ha="center", va="center",
            fontsize=fontsize, fontweight="bold", color=text_color,
            path_effects=[pe.withStroke(linewidth=0.5, foreground="none")],
            zorder=10, wrap=True,
            fontfamily="sans-serif")


def _draw_edge(ax, pos_from, pos_to, label="", directed=True,
               edge_color="#555555", edge_style="solid",
               node_width=1.6, node_height=0.7, curve=0.0):
    """Draw an edge (arrow) between two node positions."""
    x1, y1 = pos_from
    x2, y2 = pos_to

    # Shorten by node radius to not overlap nodes
    dx, dy = x2 - x1, y2 - y1
    dist = math.sqrt(dx * dx + dy * dy)
    if dist < 0.01:
        return

    ux, uy = dx / dist, dy / dist
    # Compute offset based on which axis is dominant
    if abs(ux) > abs(uy):
        offset_start = node_width / 2 + 0.05
        offset_end = node_width / 2 + 0.05
    else:
        offset_start = node_height / 2 + 0.05
        offset_end = node_height / 2 + 0.05

    sx = x1 + ux * offset_start
    sy = y1 + uy * offset_start
    ex = x2 - ux * offset_end
    ey = y2 - uy * offset_end

    ls = _EDGE_STYLES.get(edge_style, "-")
    arrow_style = "->" if directed else "-"

    if abs(curve) > 0.01:
        style = f"arc3,rad={curve}"
    else:
        style = "arc3,rad=0.0"

    ax.annotate("", xy=(ex, ey), xytext=(sx, sy),
                arrowprops=dict(
                    arrowstyle=f"{arrow_style}",
                    color=edge_color,
                    linestyle=ls,
                    lw=1.2,
                    connectionstyle=style,
                    shrinkA=0, shrinkB=0,
                    mutation_scale=15,
                ),
                zorder=1)

    # Edge label
    if label:
        mid_x = (sx + ex) / 2
        mid_y = (sy + ey) / 2
        if abs(curve) > 0.01:
            mid_x += curve * 0.5 * (-uy)
            mid_y += curve * 0.5 * ux
        ax.text(mid_x, mid_y, label, ha="center", va="center",
                fontsize=7.5, color="#333333",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                          edgecolor="none", alpha=0.85),
                zorder=5, fontfamily="sans-serif")


# ── Diagram type renderers ───────────────────────────────────────────────────

def _render_flowchart(block, theme):
    """Render a flowchart diagram."""
    nodes = _parse_nodes(block.nodes)
    edges = _parse_edges(block.edges)
    direction = block.direction or "TB"
    colors = block.colors or _FALLBACK_COLORS

    positions = _layout_flowchart(nodes, edges, direction)
    # boxes as wide as their longest line and as tall as their lines, the layout spread to hold them, and
    # the figure drawn at one scale so the whole of it, text and boxes alike, shrinks together to fit
    lines = [ln for n in nodes for ln in str(n["label"]).split("\n")] or [""]
    nw = max(1.6, max(len(ln) for ln in lines) * 0.085 + 0.5)
    nh = max(0.7, max(len(str(n["label"]).split("\n")) for n in nodes) * 0.3 + 0.25) if nodes else 0.7
    lr = direction == "LR"                           # the layout puts layers 2.5 apart across, 2.0 down
    sx = (nw + (0.9 if lr else 0.5)) / 2.5
    sy = (nh + (0.5 if lr else 0.8)) / 2.0
    positions = {k: (x * sx, y * sy) for k, (x, y) in positions.items()}
    xs = [x for x, _ in positions.values()] or [0.0]
    ys = [y for _, y in positions.values()] or [0.0]
    x0, x1 = min(xs) - nw / 2 - 0.4, max(xs) + nw / 2 + 0.4
    y0, y1 = min(ys) - nh / 2 - 0.4, max(ys) + nh / 2 + 0.4
    unit = 0.75                                      # inches per layout unit

    fig, ax = plt.subplots(figsize=((x1 - x0) * unit, (y1 - y0) * unit + (0.4 if block.title else 0)))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Draw edges first
    directed = block.directed if block.directed is not None else True
    for e in edges:
        if e["from"] in positions and e["to"] in positions:
            curve = e.get("curve", 0.0)
            _draw_edge(ax, positions[e["from"]], positions[e["to"]],
                       label=e.get("label", ""), directed=directed,
                       edge_color=e.get("color", "#555555"),
                       edge_style=e.get("style", "solid"),
                       node_width=nw, node_height=nh, curve=curve)

    # Draw nodes
    for i, node in enumerate(nodes):
        nid = node["id"]
        if nid not in positions:
            continue
        x, y = positions[nid]
        shape = node.get("shape", "rounded")
        color = _get_node_color(node, colors, i)
        text_color = node.get("text_color", "#FFFFFF")
        border_style = node.get("border_style", "solid")
        _draw_node(ax, x, y, node["label"], shape=shape, color=color,
                   text_color=text_color, border_style=border_style, node_width=nw, node_height=nh)

    # Title
    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=12, fontfamily="sans-serif")

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout(pad=0.5)
    # a tall chart may take more of the page than the default height rather than shrink its text; a height
    # the author set is kept
    tall = block.height if "height" in block.model_fields_set else max(block.height, min(6.5, fig.get_figheight()))
    return _fig_to_drawing(fig, block.width, tall)


def _render_tree(block, theme):
    """Render a tree diagram."""
    nodes = _parse_nodes(block.nodes)
    edges = _parse_edges(block.edges)
    colors = block.colors or _FALLBACK_COLORS

    positions = _layout_tree(nodes, edges, block.direction or "TB")

    fig, ax = plt.subplots(figsize=(block.width, block.height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Draw edges
    for e in edges:
        if e["from"] in positions and e["to"] in positions:
            _draw_edge(ax, positions[e["from"]], positions[e["to"]],
                       label=e.get("label", ""), directed=True,
                       edge_color=e.get("color", "#888888"),
                       edge_style=e.get("style", "solid"))

    # Draw nodes
    for i, node in enumerate(nodes):
        nid = node["id"]
        if nid not in positions:
            continue
        x, y = positions[nid]
        shape = node.get("shape", "rounded")
        color = _get_node_color(node, colors, i)
        text_color = node.get("text_color", "#FFFFFF")
        _draw_node(ax, x, y, node["label"], shape=shape, color=color,
                   text_color=text_color)

    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=12, fontfamily="sans-serif")

    ax.set_aspect("equal")
    ax.axis("off")
    ax.autoscale(tight=True)
    ax.margins(0.15)
    fig.tight_layout(pad=0.5)

    return _fig_to_drawing(fig, block.width, block.height)


def _render_network(block, theme):
    """Render a network/graph diagram."""
    nodes = _parse_nodes(block.nodes)
    edges = _parse_edges(block.edges)
    colors = block.colors or _FALLBACK_COLORS

    positions = _layout_network(nodes, edges)

    fig, ax = plt.subplots(figsize=(block.width, block.height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    directed = block.directed if block.directed is not None else False

    for e in edges:
        if e["from"] in positions and e["to"] in positions:
            _draw_edge(ax, positions[e["from"]], positions[e["to"]],
                       label=e.get("label", ""), directed=directed,
                       edge_color=e.get("color", "#888888"),
                       edge_style=e.get("style", "solid"))

    for i, node in enumerate(nodes):
        nid = node["id"]
        if nid not in positions:
            continue
        x, y = positions[nid]
        shape = node.get("shape", "circle")
        color = _get_node_color(node, colors, i)
        text_color = node.get("text_color", "#FFFFFF")
        _draw_node(ax, x, y, node["label"], shape=shape, color=color,
                   text_color=text_color)

    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=12, fontfamily="sans-serif")

    ax.set_aspect("equal")
    ax.axis("off")
    ax.autoscale(tight=True)
    ax.margins(0.15)
    fig.tight_layout(pad=0.5)

    return _fig_to_drawing(fig, block.width, block.height)


def _render_state(block, theme):
    """Render a state machine diagram (like flowchart with rounded states)."""
    nodes = _parse_nodes(block.nodes)
    edges = _parse_edges(block.edges)
    colors = block.colors or _FALLBACK_COLORS

    # Mark start/end nodes
    for node in nodes:
        if node.get("start"):
            node.setdefault("shape", "circle")
            node.setdefault("color", "#2C3E50")
        elif node.get("end"):
            node.setdefault("shape", "circle")
            node.setdefault("color", "#E74C3C")
            node.setdefault("border_style", "solid")
        else:
            node.setdefault("shape", "rounded")

    positions = _layout_flowchart(nodes, edges, block.direction or "TB")

    fig, ax = plt.subplots(figsize=(block.width, block.height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    for e in edges:
        if e["from"] in positions and e["to"] in positions:
            curve = e.get("curve", 0.0)
            _draw_edge(ax, positions[e["from"]], positions[e["to"]],
                       label=e.get("label", ""), directed=True,
                       edge_color=e.get("color", "#555555"),
                       edge_style=e.get("style", "solid"),
                       curve=curve)

    for i, node in enumerate(nodes):
        nid = node["id"]
        if nid not in positions:
            continue
        x, y = positions[nid]
        shape = node.get("shape", "rounded")
        color = _get_node_color(node, colors, i)
        text_color = node.get("text_color", "#FFFFFF")
        _draw_node(ax, x, y, node["label"], shape=shape, color=color,
                   text_color=text_color)

    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=12, fontfamily="sans-serif")

    ax.set_aspect("equal")
    ax.axis("off")
    ax.autoscale(tight=True)
    ax.margins(0.15)
    fig.tight_layout(pad=0.5)

    return _fig_to_drawing(fig, block.width, block.height)


def _render_sequence(block, theme):
    """Render a vertical sequence diagram with actors and messages."""
    nodes = _parse_nodes(block.nodes)
    edges = _parse_edges(block.edges)
    colors = block.colors or _FALLBACK_COLORS

    n_actors = len(nodes)
    if n_actors == 0:
        return None

    fig, ax = plt.subplots(figsize=(block.width, block.height))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Position actors along x-axis
    actor_x = {}
    spacing = max(2.0, block.width / max(n_actors, 1))
    for i, node in enumerate(nodes):
        x = (i + 0.5) * spacing
        actor_x[node["id"]] = x
        color = _get_node_color(node, colors, i)
        # Actor box at top
        box = mpatches.FancyBboxPatch(
            (x - 0.7, 0.3), 1.4, 0.6,
            boxstyle="round,pad=0.1",
            facecolor=color, edgecolor=color, linewidth=1.5,
        )
        ax.add_patch(box)
        ax.text(x, 0.6, node["label"], ha="center", va="center",
                fontsize=9, fontweight="bold", color="white",
                fontfamily="sans-serif", zorder=10)

    # Draw lifelines
    n_msgs = len(edges)
    y_bottom = -(n_msgs + 1) * 0.8
    for nid, x in actor_x.items():
        ax.plot([x, x], [0.3, y_bottom], color="#CCCCCC", linewidth=1,
                linestyle="--", zorder=0)

    # Draw messages
    for i, e in enumerate(edges):
        y = -(i + 1) * 0.8
        src_x = actor_x.get(e["from"])
        dst_x = actor_x.get(e["to"])
        if src_x is None or dst_x is None:
            continue

        style = e.get("style", "solid")
        ls = _EDGE_STYLES.get(style, "-")
        ecolor = e.get("color", "#444444")

        if src_x == dst_x:
            # Self-message (loop back)
            loop_w = 0.6
            ax.annotate("", xy=(src_x + loop_w, y - 0.3),
                        xytext=(src_x + loop_w, y),
                        arrowprops=dict(arrowstyle="->", color=ecolor,
                                        lw=1.2, linestyle=ls))
            ax.plot([src_x, src_x + loop_w], [y, y], color=ecolor,
                    linewidth=1.2, linestyle=ls)
            ax.plot([src_x + loop_w, src_x + loop_w], [y, y - 0.3],
                    color=ecolor, linewidth=1.2, linestyle=ls)
            if e.get("label"):
                ax.text(src_x + loop_w + 0.1, y - 0.15, e["label"],
                        fontsize=7.5, va="center", ha="left",
                        color="#333333", fontfamily="sans-serif")
        else:
            ax.annotate("", xy=(dst_x, y), xytext=(src_x, y),
                        arrowprops=dict(arrowstyle="->", color=ecolor,
                                        lw=1.2, linestyle=ls,
                                        mutation_scale=15))
            if e.get("label"):
                mid_x = (src_x + dst_x) / 2
                ax.text(mid_x, y + 0.12, e["label"], ha="center", va="bottom",
                        fontsize=7.5, color="#333333",
                        fontfamily="sans-serif")

    if block.title:
        ax.set_title(block.title, fontsize=11, fontweight="bold",
                     color="#222222", pad=12, fontfamily="sans-serif")

    ax.set_xlim(-0.5, n_actors * spacing + 0.5)
    ax.set_ylim(y_bottom - 0.3, 1.2)
    ax.axis("off")
    fig.tight_layout(pad=0.5)

    return _fig_to_drawing(fig, block.width, block.height)


# ── Public entry point ───────────────────────────────────────────────────────

_RENDERERS = {
    "flowchart": _render_flowchart,
    "tree": _render_tree,
    "network": _render_network,
    "graph": _render_network,
    "state": _render_state,
    "sequence": _render_sequence,
}


def render_diagram(block, theme=None):
    """Render a DiagramBlock into a list of ReportLab flowables."""
    diagram_type = block.diagram_type.lower()
    renderer = _RENDERERS.get(diagram_type)
    if renderer is None:
        from ..utils.errors import BlockRenderError
        raise BlockRenderError(
            "diagram", f"Unsupported diagram type {diagram_type!r}; supported: {', '.join(_RENDERERS)}")

    drawing = renderer(block, theme)
    if not drawing:
        return []

    from reportlab.platypus import Spacer
    gap = getattr(getattr(theme, "spacing", None), "block_gap", 8)
    return [drawing, Spacer(1, gap)]


def diagram_png(block, theme=None) -> bytes:
    """Render a DiagramBlock to PNG bytes (used by the DOCX renderer)."""
    from ..utils.errors import BlockRenderError
    renderer = _RENDERERS.get(block.diagram_type.lower())
    if renderer is None:
        raise BlockRenderError(
            "diagram", f"Unsupported diagram type {block.diagram_type!r}; supported: {', '.join(_RENDERERS)}")
    token = _PNG_MODE.set(True)
    try:
        return renderer(block, theme)
    finally:
        _PNG_MODE.reset(token)
