"""
Deterministic visual descriptors of a page, composition labels, distinctiveness and the shortlist.

Everything here is a measurement or an inferred category. Nothing here says a page
looks good: ``distinctiveness`` only ranks how far a page sits from its nearest
neighbours, and only a human reviewer can accept a page as inspiration.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set, Tuple

GW, GH = 24, 32                 # analysis grid; the same for every page, so compositions compare across formats
SW, SH = 12, 16                 # layout signature grid (192 bits)
BASE = 10                       # base image pixels per grid cell
INK_DIFF, SOLID_DIFF = 24, 6

LABELS = {
    "cover_title": "Cover or title page",
    "section_opener": "Chapter or section opener",
    "image_led": "Image-led page",
    "full_bleed": "Full-bleed page",
    "split_image_text": "Split image and text",
    "editorial_asymmetric": "Asymmetric editorial layout",
    "multi_column": "Multi-column text",
    "infographic": "Infographic",
    "data_story": "Data storytelling",
    "kpi_dashboard": "KPI or dashboard page",
    "financial_table": "Financial table in context",
    "large_type": "Large typography",
    "open_whitespace": "Open whitespace",
    "pull_quote": "Pull quote or lead statement",
    "callout": "Callout panel",
    "accent_band": "Accent band",
    "visual_separator": "Visual separator",
    "arabic_rtl": "Arabic RTL composition",
    "bilingual": "Bilingual composition",
    "repeating_system": "Repeating page system",
    "alternating_layout": "Alternating layout",
}
LAYOUT_TYPES = ("blank", "full_page_visual", "image_led", "split", "display", "chart_or_diagram", "table",
                "multi_column_text", "single_column_text", "mixed")
# labels a page can have because of what surrounds it, or that say little about its composition
CONTEXT_LABELS = {"repeating_system", "arabic_rtl", "bilingual", "visual_separator"}


def _r(x: float, n: int = 3) -> float:
    return round(float(x), n)


def _hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(v) for v in rgb[:3])


def _largest_rect(cells: List[List[bool]]) -> Tuple[int, Tuple[int, int, int, int]]:
    """Largest all-True rectangle: (area, (x0, y0, x1, y1)) in grid cells, ties to the top left."""
    if not cells:
        return 0, (0, 0, 0, 0)
    w = len(cells[0])
    heights = [0] * w
    best, box = 0, (0, 0, 0, 0)
    for y, row in enumerate(cells):
        heights = [h + 1 if c else 0 for h, c in zip(heights, row)]
        stack: List[int] = []
        for x in range(w + 1):
            cur = heights[x] if x < w else 0
            while stack and heights[stack[-1]] >= cur:
                h = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                area = h * (x - left)
                if area > best:
                    best, box = area, (left, y - h + 1, x, y + 1)
            stack.append(x)
    return best, box


def _norm_box(box, gw=GW, gh=GH) -> List[float]:
    return [_r(box[0] / gw), _r(box[1] / gh), _r(box[2] / gw), _r(box[3] / gh)]


def _background(base) -> Tuple[tuple, float]:
    """Most common border colour (16 levels per channel) and its share of the border."""
    w, h = base.size
    px = base.load()
    border = [px[x, y] for x in range(0, w, 3) for y in (0, h - 1)] + [px[x, y] for y in range(0, h, 3) for x in (0, w - 1)]
    c = Counter((r >> 4, g >> 4, b >> 4) for r, g, b in border)
    key, n = min(c.items(), key=lambda kv: (-kv[1], kv[0]))
    same = [p for p in border if (p[0] >> 4, p[1] >> 4, p[2] >> 4) == key]
    return tuple(sum(p[i] for p in same) // len(same) for i in range(3)), n / len(border)


def _diff_mask(img, bg, threshold: int):
    from PIL import Image, ImageChops
    r, g, b = ImageChops.difference(img, Image.new("RGB", img.size, bg)).split()
    return ImageChops.lighter(r, ImageChops.lighter(g, b)).point(lambda v: 255 if v > threshold else 0)


def _grid(mask, w: int, h: int) -> List[List[int]]:
    from PIL import Image
    data = mask.resize((w, h), Image.BOX).tobytes()
    return [list(data[y * w:(y + 1) * w]) for y in range(h)]


def _bands(base, solid: List[List[int]]) -> List[dict]:
    """Uniform full-width or full-height stripes of a colour other than the background."""
    from PIL import ImageStat
    out = []
    W, H = base.size

    def runs(flags):
        start = None
        for i, f in enumerate(list(flags) + [False]):
            if f and start is None:
                start = i
            elif not f and start is not None:
                yield start, i
                start = None
    rows = [sum(c >= 200 for c in row) >= GW * 0.92 for row in solid]
    cols = [sum(solid[y][x] >= 200 for y in range(GH)) >= GH * 0.92 for x in range(GW)]
    for axis, flags, n in (("horizontal", rows, GH), ("vertical", cols, GW)):
        for a, b in runs(flags):
            if (b - a) / n > 0.3:
                continue
            box = (0, a * H // n, W, b * H // n) if axis == "horizontal" else (a * W // n, 0, b * W // n, H)
            st = ImageStat.Stat(base.crop(box))
            if max(st.stddev) <= 22:
                out.append({"axis": axis, "start": _r(a / n), "end": _r(b / n), "color": _hex(st.mean)})
    return out


def raster_features(im) -> dict:
    """Composition measured from pixels: covers text set as outlines, vector art and pictures alike."""
    from PIL import Image, ImageFilter, ImageStat
    base = im.convert("RGB").resize((GW * BASE, GH * BASE), Image.BOX)
    bg, bg_share = _background(base)
    ink_mask = _diff_mask(base, bg, INK_DIFF)
    solid_mask = _diff_mask(base.filter(ImageFilter.MedianFilter(7)), bg, SOLID_DIFF)
    ink, solid = _grid(ink_mask, GW, GH), _grid(solid_mask, GW, GH)
    total = sum(map(sum, ink)) or 1
    ink_share = sum(map(sum, ink)) / (255 * GW * GH)
    solid_share = sum(map(sum, solid)) / (255 * GW * GH)
    cx = sum((x + .5) * v for row in ink for x, v in enumerate(row)) / total / GW
    cy = sum((y + .5) * v for y, row in enumerate(ink) for v in row) / total / GH
    half = lambda cells: sum(map(sum, cells)) or 0                        # noqa: E731
    left, right = half([r[:GW // 2] for r in ink]), half([r[GW // 2:] for r in ink])
    top, bottom = half(ink[:GH // 2]), half(ink[GH // 2:])
    empty_area, empty_box = _largest_rect([[v < 10 for v in row] for row in ink])
    solid_area, solid_box = _largest_rect([[v >= 170 for v in row] for row in solid])
    largest = {"share": _r(solid_area / (GW * GH)), "box": _norm_box(solid_box), "uniform": None, "color": None}
    if solid_area:
        b = solid_box
        st = ImageStat.Stat(base.crop((b[0] * BASE, b[1] * BASE, b[2] * BASE, b[3] * BASE)))
        largest["uniform"] = max(st.stddev) <= 22
        largest["color"] = _hex(st.mean)
    W, H = ink_mask.size
    px = ink_mask.load()
    edge = {"top": sum(px[x, 1] > 0 for x in range(W)) / W, "bottom": sum(px[x, H - 2] > 0 for x in range(W)) / W,
            "left": sum(px[1, y] > 0 for y in range(H)) / H, "right": sum(px[W - 2, y] > 0 for y in range(H)) / H}
    hsv = base.convert("HSV")
    sat = ImageStat.Stat(hsv.split()[1], ink_mask).mean[0] / 255 if ink_share > 0.002 else 0.0
    pal = base.quantize(8, method=Image.MEDIANCUT)
    hist = pal.histogram()[:8]
    sig = 0
    for row in _grid(ink_mask, SW, SH):
        for v in row:
            sig = (sig << 1) | (v > 30)
    return {"ink_share": _r(ink_share), "solid_share": _r(solid_share),
            "largest_solid": largest,
            "largest_empty": {"share": _r(empty_area / (GW * GH)), "box": _norm_box(empty_box)},
            "centroid": [_r(cx), _r(cy)],
            "balance": {"left_right": _r((left - right) / (left + right or 1)),
                        "top_bottom": _r((top - bottom) / (top + bottom or 1))},
            "edge_contact": {k: _r(v) for k, v in edge.items()},
            "background": _hex(bg), "background_share": _r(bg_share),
            "background_luminance": _r((0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) / 255),
            "colourfulness": _r(sat), "palette_colours": sum(n / (W * H) >= 0.02 for n in hist),
            "bands": _bands(base, solid), "signature": f"{sig:048x}"}


def _is_digit(ch: str) -> bool:
    return ch.isdigit() or ch in "٪%"


def text_facts(page, body: Optional[float]) -> dict:
    """Counts from the live text. The text itself is not kept."""
    body = body or 10.0
    W = page.rect.width
    numeric_big = numeric_mid = quotes = statements = digits = chars = 0
    mass = {"arabic": [0, 0], "latin": [0, 0]}          # characters in the left and right half
    for block in page.get_text("dict")["blocks"]:
        lines = block.get("lines", [])
        spans = [sp for ln in lines for sp in ln["spans"] if sp["text"].strip()]
        text = "".join(sp["text"] for sp in spans).strip()
        if not text:
            continue
        for ln in lines:
            t = "".join(sp["text"] for sp in ln["spans"]).strip()
            n = sum(_is_digit(c) for c in t)
            if t and n and len(t) <= 16 and n / len(t) >= 0.3:
                size = max(sp["size"] for sp in ln["spans"])
                numeric_big += size >= 1.8 * body
                numeric_mid += 1.3 * body <= size < 1.8 * body
        digits += sum(_is_digit(c) for c in text)
        chars += len(text)
        big = sum(len(sp["text"]) for sp in spans if sp["size"] >= 1.3 * body) / max(sum(len(sp["text"]) for sp in spans), 1)
        if big >= 0.8 and len(text) >= 30 and text[0] in "\u201c\u201d\"\u00ab\u00bb\u2018\u201e":
            quotes += 1
        elif big >= 0.8 and len(text) >= 70 and len(lines) >= 2 and sum(_is_digit(c) for c in text) / len(text) < 0.1:
            statements += 1
        side = 0 if (block["bbox"][0] + block["bbox"][2]) / 2 < W / 2 else 1
        mass["arabic"][side] += sum("\u0600" <= c <= "\u06ff" or "\ufb50" <= c <= "\ufefc" for c in text)
        mass["latin"][side] += sum(c.isascii() and c.isalpha() for c in text)
    return {"numeric_big": numeric_big, "numeric_mid": numeric_mid, "quote_blocks": quotes, "statement_blocks": statements,
            "digit_share": _r(digits / chars) if chars else 0.0, "script_mass": mass}


def picture_light_share(im, box: List[float]) -> float:
    """Near-white share of a picture region. A scanned letter is a picture of mostly white paper."""
    from PIL import Image
    W, H = im.size
    crop = im.crop((int(box[0] * W), int(box[1] * H), max(int(box[2] * W), int(box[0] * W) + 1),
                    max(int(box[3] * H), int(box[1] * H) + 1))).convert("L").resize((64, 64), Image.BOX)
    return _r(sum(crop.histogram()[225:]) / (64 * 64))


def geometry_facts(pf: dict, body: Optional[float], text: dict) -> dict:
    """Analyzer measurements of one page, reduced to shares of the page."""
    size = pf["size"]["value"]
    W, H = size["width_pt"], size["height_pt"]
    area = W * H
    share = lambda b: max(0.0, (b[2] - b[0]) * (b[3] - b[1])) / area          # noqa: E731
    blocks = pf["text_blocks"]["value"]
    sizes = [b["size_pt"] for b in blocks]
    imgs = pf["images"]["value"]
    vec = pf["vector_graphics"]["value"]
    tabs = pf["tables"]["value"]
    cols = pf["columns"]["value"]
    widths = [b - a for a, b in cols["intervals"]] if cols else []
    rules = pf["rules"]["value"]
    dens = pf["density"]["value"]
    big = max((i["bbox"] for i in imgs), key=share, default=None)
    return {"chars": pf["chars"]["value"], "script": pf["script"]["value"]["class"],
            "text_blocks": len(blocks), "heading_blocks": sum(b["role"] == "heading_candidate" for b in blocks),
            "short_blocks": sum(b["lines"] <= 2 for b in blocks),
            "max_size_pt": max(sizes) if sizes else None,
            "display_ratio": _r(max(sizes) / body, 2) if sizes and body else None,
            "columns": cols["count"] if cols else 1,
            "column_ratio": _r(max(widths) / max(min(widths), 1), 2) if len(widths) >= 2 else 1.0,
            "text_share": dens["text_area_share"], "image_share": dens["image_area_share"],
            "image_count": len(imgs), "largest_image": _r(share(big)) if big else 0.0,
            "largest_image_box": [_r(big[0] / W), _r(big[1] / H), _r(big[2] / W), _r(big[3] / H)] if big else None,
            "vector_regions": len(vec), "vector_share": _r(min(1, sum(share(g["bbox"]) for g in vec))),
            "filled_shapes": pf["shapes"]["value"]["filled_shapes"],
            "table_count": len(tabs), "table_share": _r(min(1, sum(share(t["bbox"]) for t in tabs))),
            "rules": len(rules), "thick_rules": sum(r["thickness_pt"] >= 1.5 and r["length_pt"] >= 0.1 * W for r in rules),
            **{k: text[k] for k in ("numeric_big", "numeric_mid", "quote_blocks", "statement_blocks", "digit_share")},
            "script_mass": text["script_mass"]}


def _add(out: List[dict], label: str, confidence: str, evidence: str) -> None:
    out.append({"label": label, "confidence": confidence, "evidence": evidence})


def classify(r: dict, g: Optional[dict], page: int, pages: int) -> List[dict]:
    """Composition labels of one page, each with the measurement behind it."""
    out: List[dict] = []
    if r["ink_share"] < 0.004:
        return out
    ls, empty = r["largest_solid"], r["largest_empty"]
    edges = sum(v >= 0.85 for v in r["edge_contact"].values())
    g = g or {}
    chars = g.get("chars", 0)
    ratio = g.get("display_ratio") or 0
    size = g.get("max_size_pt") or 0
    scan = g.get("picture_light_share", 0) >= 0.6          # a picture of a white page, usually a scanned letter
    backdrop = g.get("largest_image", 0) >= 0.85 and chars >= 600   # a tinted page behind running text
    placed = 0.0 if scan or backdrop else g.get("largest_image", 0)
    # a varied region counts as a picture only where text does not explain it: a panel of table text is not one
    drawn = ls["share"] if ls["uniform"] is False and (chars < 500 or g.get("vector_share", 0) >= 0.3) else 0.0
    picture = 0.0 if scan else drawn
    image = max(placed, picture)
    display = (ratio >= 2.5 or size >= 24) and not scan

    box = g.get("largest_image_box")
    bleeds = sum((box[0] <= 0.01, box[1] <= 0.01, box[2] >= 0.99, box[3] >= 0.99)) if box and placed >= 0.5 else 0
    if bleeds >= 3 and placed >= 0.85:
        _add(out, "full_bleed", "high" if bleeds == 4 else "medium", f"a picture over {placed:.0%} of the page "
             f"runs off {bleeds} edges")
    elif edges >= 3 and r["ink_share"] >= 0.8 and chars < 600 and not backdrop and \
            (picture >= 0.5 or placed >= 0.7 or r["background_luminance"] < 0.6):
        _add(out, "full_bleed", "high" if edges == 4 else "medium", f"ink reaches {edges} page edges; "
             f"ink covers {r['ink_share']:.0%}")
    if image >= 0.4:
        _add(out, "image_led", "high" if placed >= 0.4 else "medium",
             f"largest picture covers {image:.0%} of the page")
    low_text = chars < 450
    if page <= 2 and low_text and not scan and (display or image >= 0.25 or r["solid_share"] >= 0.3):
        _add(out, "cover_title", "high" if page == 1 else "medium", f"page {page}, {chars} characters, "
             f"largest type {ratio:g}× body")
    elif page > 2 and low_text and display and g.get("text_blocks", 0) <= 12:
        _add(out, "section_opener", "medium", f"{chars} characters, largest type {ratio:g}× body")
    elif page > 2 and low_text and r["solid_share"] >= 0.6 and g.get("text_blocks", 0) <= 8 and chars and not scan:
        _add(out, "section_opener", "low", f"{chars} characters on a page {r['solid_share']:.0%} solid")
    if 0.2 <= image < 0.75 and chars >= 150:
        b = g.get("largest_image_box") if placed >= picture else ls["box"]
        if b and (b[2] <= 0.75 or b[0] >= 0.25 or b[3] <= 0.75 or b[1] >= 0.25):
            _add(out, "split_image_text", "medium", f"picture {image:.0%} beside {chars} characters")
    cols = g.get("columns", 1)
    if cols >= 2 and chars >= 400:
        _add(out, "multi_column", "high" if cols >= 3 else "medium", f"{cols} text columns")
    tabular = g.get("table_share", 0) >= 0.2 or g.get("digit_share", 0) >= 0.12
    if chars >= 300 and not tabular and (g.get("column_ratio", 1) >= 1.4 or
                                         (abs(r["balance"]["left_right"]) >= 0.3 and image < 0.4)):
        _add(out, "editorial_asymmetric", "medium", f"column width ratio {g.get('column_ratio', 1):g}, "
             f"left-right balance {r['balance']['left_right']:+.2f}")
    if g.get("vector_share", 0) >= 0.2 and g.get("short_blocks", 0) >= 6 and g.get("table_count", 0) == 0 and \
            r["palette_colours"] >= 3:
        _add(out, "infographic", "medium", f"drawings cover {g['vector_share']:.0%}, "
             f"{g['short_blocks']} short text blocks, {r['palette_colours']} colours")
    elif g.get("filled_shapes", 0) >= 8 and r["palette_colours"] >= 3 and chars < 800 and placed < 0.3 and \
            g.get("table_count", 0) == 0 and r["solid_share"] >= 0.1:
        _add(out, "infographic", "low", f"{g['filled_shapes']} filled shapes in {r['palette_colours']} colours, "
             f"{chars} characters")
    if g.get("vector_share", 0) >= 0.1 and g.get("heading_blocks", 0) >= 1 and chars >= 200:
        _add(out, "data_story", "low", f"drawing region {g['vector_share']:.0%} with a heading and {chars} characters")
    if g.get("numeric_big", 0) >= 3:
        _add(out, "kpi_dashboard", "medium", f"{g['numeric_big']} large numerals")
    elif g.get("numeric_big", 0) >= 1 and g.get("numeric_mid", 0) >= 4:
        _add(out, "kpi_dashboard", "low", f"a large numeral with {g['numeric_mid']} smaller ones")
    if (g.get("table_count", 0) or g.get("digit_share", 0) >= 0.2) and g.get("digit_share", 0) >= 0.12 and \
            (g.get("heading_blocks", 0) >= 1 or ratio >= 1.3) and chars >= 200:
        _add(out, "financial_table", "medium" if g.get("table_count", 0) else "low",
             f"{g.get('table_count', 0)} ruled tables, {g['digit_share']:.0%} digits, a heading above")
    if ratio >= 3 or size >= 36:
        _add(out, "large_type", "high", f"largest type {size:g} pt, {ratio:g}× body")
    # a wide gap under the last line is text running out, not a composition
    text_runout = empty["box"][3] >= 0.8 and empty["box"][2] - empty["box"][0] >= 0.6 and not display
    if empty["share"] >= 0.3 and r["ink_share"] >= 0.02 and not text_runout and not scan:
        _add(out, "open_whitespace", "medium", f"largest empty area covers {empty['share']:.0%}")
    if g.get("quote_blocks", 0):
        _add(out, "pull_quote", "medium", f"{g['quote_blocks']} enlarged blocks opening with a quotation mark")
    elif g.get("statement_blocks", 0) and chars >= 150:
        _add(out, "pull_quote", "low", f"{g['statement_blocks']} enlarged passages set apart from the body")
    if ls["uniform"] and 0.03 <= ls["share"] <= 0.5 and g.get("text_blocks", 0) >= 1 and not tabular:
        _add(out, "callout", "low", f"uniform panel {ls['color']} covers {ls['share']:.0%}")
    if r["bands"]:
        b = r["bands"][0]
        _add(out, "accent_band", "medium", f"{len(r['bands'])} uniform {b['axis']} band(s), {b['color']}")
    if g.get("thick_rules", 0) >= 1:
        _add(out, "visual_separator", "low", f"{g['thick_rules']} thick rules")
    script = g.get("script")
    if script == "arabic_rtl":
        _add(out, "arabic_rtl", "high", "Arabic text layer")
    elif script == "bilingual":
        m = g.get("script_mass", {})
        ar, la = m.get("arabic", [0, 0]), m.get("latin", [0, 0])
        mirrored = ar[1] > 3 * ar[0] and la[0] > 3 * la[1]
        _add(out, "bilingual", "high" if mirrored else "medium",
             "Arabic and Latin on opposite halves" if mirrored else "Arabic and Latin text on one page")
    return out


def layout_type(r: dict, g: Optional[dict], labels: Set[str]) -> str:
    if r["ink_share"] < 0.004:
        return "blank"
    g = g or {}
    if "full_bleed" in labels:
        return "full_page_visual"
    if "split_image_text" in labels:
        return "split"
    if "image_led" in labels:
        return "image_led"
    if labels & {"cover_title", "section_opener"} or ("large_type" in labels and g.get("chars", 0) < 450):
        return "display"
    if g.get("vector_share", 0) >= 0.2:
        return "chart_or_diagram"
    if g.get("table_share", 0) >= 0.25:
        return "table"
    if g.get("columns", 1) >= 2:
        return "multi_column_text"
    if g.get("chars", 0) >= 300 and g.get("image_count", 0) == 0:
        return "single_column_text"
    return "mixed"


# ── relations between pages ─────────────────────────────────────────────

def _vector(p: dict) -> List[float]:
    r, g = p["raster"], p.get("geometry") or {}
    e = r["edge_contact"]
    return [r["ink_share"], r["solid_share"], r["largest_solid"]["share"], r["largest_empty"]["share"],
            r["centroid"][0], r["centroid"][1], (r["balance"]["left_right"] + 1) / 2,
            (r["balance"]["top_bottom"] + 1) / 2, r["colourfulness"], r["palette_colours"] / 8,
            1 - r["background_luminance"], sum(e.values()) / 4, g.get("text_share", 0), g.get("largest_image", 0),
            g.get("vector_share", 0), g.get("table_share", 0), min(g.get("display_ratio") or 0, 8) / 8,
            min(g.get("columns", 1), 4) / 4, min(math.log1p(g.get("chars", 0)) / 9, 1)]


def _mirror(sig: int) -> int:
    out = 0
    for y in range(SH):
        row = (sig >> ((SH - 1 - y) * SW)) & ((1 << SW) - 1)
        out = (out << SW) | int(f"{row:0{SW}b}"[::-1], 2)
    return out


def _distance(a, b) -> float:
    """0 = same composition. Half the layout signature, half the composition vector."""
    h = bin(a[0] ^ b[0]).count("1") / (SW * SH)
    v = math.sqrt(sum((x - y) ** 2 for x, y in zip(a[1], b[1])) / len(a[1]))
    return 0.5 * h + 0.5 * min(v * 2, 1)


def _prepared(p: dict) -> tuple:
    return int(p["raster"]["signature"], 16), _vector(p)


def _knn(i: int, group: List[int], prep: List[tuple], k: int = 5) -> float:
    d = sorted(_distance(prep[i], prep[j]) for j in group if j != i)[:k]
    return sum(d) / len(d) if d else 0.0


def _percentiles(values: Dict[int, float]) -> Dict[int, float]:
    order = sorted(values, key=lambda i: (values[i], i))
    n = max(len(order) - 1, 1)
    return {i: rank / n for rank, i in enumerate(order)}


def relate_pages(pages: List[dict], cluster_distance: float = 0.14) -> None:
    """Clusters, distinctiveness, chapters and document-level labels, in place. ``pages`` are all good pages."""
    live = [i for i, p in enumerate(pages) if p["layout_type"] != "blank"]
    prep = [_prepared(p) for p in pages]
    # greedy leader clustering, in document order
    leaders: List[int] = []
    for i, p in enumerate(pages):
        if p["layout_type"] == "blank":
            p["cluster"] = "blank"
            continue
        best = min(leaders, key=lambda j: (_distance(prep[i], prep[j]), j), default=None)
        if best is None or _distance(prep[i], prep[best]) > cluster_distance:
            leaders.append(i)
            best = i
        p["cluster"] = f"L{leaders.index(best) + 1:03d}"
    corpus_size = Counter(pages[i]["cluster"] for i in live)
    by_doc: Dict[str, List[int]] = defaultdict(list)
    for i in live:
        by_doc[pages[i]["sha256"]].append(i)
    doc_size = {sha: Counter(pages[i]["cluster"] for i in idx) for sha, idx in by_doc.items()}

    corpus_d = {i: _knn(i, live, prep) for i in live}
    corpus_rank = _percentiles(corpus_d)
    doc_rank: Dict[int, float] = {}
    for idx in by_doc.values():
        doc_rank.update(_percentiles({i: _knn(i, idx, prep) for i in idx}))
    for i, p in enumerate(pages):
        if i not in corpus_d:
            p["distinctiveness"] = {"score": 0.0, "nearest_distance": 0.0, "corpus_rank": 0.0, "document_rank": 0.0}
            p["cluster_size"] = {"corpus": 0, "document": 0}
            continue
        p["distinctiveness"] = {"score": _r((corpus_rank[i] + doc_rank[i]) / 2), "nearest_distance": _r(corpus_d[i]),
                                "corpus_rank": _r(corpus_rank[i]), "document_rank": _r(doc_rank[i])}
        p["cluster_size"] = {"corpus": corpus_size[p["cluster"]], "document": doc_size[p["sha256"]][p["cluster"]]}

    for sha, idx in by_doc.items():
        n = len(idx)
        openers = [pages[i]["page"] for i in idx if _has(pages[i], "section_opener")]
        bins = max(1, min(8, n // 6))
        for pos, i in enumerate(idx):
            p = pages[i]
            p["chapter"] = sum(o <= p["page"] for o in openers) if len(openers) >= 3 else pos * bins // n
            if p["cluster_size"]["document"] >= max(3, 0.05 * n):
                _add(p["labels"], "repeating_system", "medium", f"same layout on {p['cluster_size']['document']} "
                     f"pages of this document")
        for a, b in zip(idx, idx[1:]):
            if pages[b]["page"] != pages[a]["page"] + 1:
                continue
            same = 1 - bin(prep[a][0] ^ prep[b][0]).count("1") / (SW * SH)
            mirrored = 1 - bin(_mirror(prep[a][0]) ^ prep[b][0]).count("1") / (SW * SH)
            if mirrored >= 0.86 and mirrored - same >= 0.08:
                for i in (a, b):
                    if not _has(pages[i], "alternating_layout"):
                        _add(pages[i]["labels"], "alternating_layout", "medium", "mirrors its neighbouring page")


def _has(p: dict, label: str) -> bool:
    return any(x["label"] == label for x in p["labels"])


def spread_of(page: int, pages: int, rtl: bool, sheet: bool) -> dict:
    """How a page is viewed as a spread. ``order`` runs left to right on screen."""
    if sheet:
        return {"kind": "sheet", "order": [page], "reads": "right_to_left" if rtl else "left_to_right"}
    lo = page if page % 2 == 0 else page - 1
    pair = [p for p in (lo, lo + 1) if 2 <= p <= pages]
    if page == 1 or len(pair) < 2:
        return {"kind": "single", "order": [page], "reads": "right_to_left" if rtl else "left_to_right"}
    return {"kind": "facing", "order": pair[::-1] if rtl else pair,
            "reads": "right_to_left" if rtl else "left_to_right"}


# ── shortlist ───────────────────────────────────────────────────────────

def _key(p: dict) -> Tuple[str, int]:
    return p["sha256"], p["page"]


def shortlist(pages: List[dict], kept: Set[Tuple[str, int]], rejected: Set[Tuple[str, int]], target: int = 120,
              min_per_document: int = 4, max_document_share: float = 0.16, per_label: int = 6,
              max_per_cluster: int = 3, max_per_chapter: int = 3) -> dict:
    """Diverse candidates: every document, every label and many chapters; no document or layout dominates.

    ``kept`` pages (human pinned or accepted) always stay, and ``rejected`` pages are never proposed again.
    """
    by_key = {_key(p): p for p in pages}
    pool = sorted((p for p in pages if p["layout_type"] != "blank" and _key(p) not in rejected), key=_key)
    prep = {_key(p): _prepared(p) for p in pool}
    picked: List[dict] = []
    chosen: Set[Tuple[str, int]] = set()
    near: Dict[tuple, float] = {k: 0.0 for k in prep}      # similarity to the closest chosen page
    reasons: Dict[tuple, List[str]] = defaultdict(list)
    doc_n: Counter = Counter()
    cluster_n: Counter = Counter()
    chapter_n: Counter = Counter()
    label_n: Counter = Counter()
    type_n: Counter = Counter()
    doc_cap = max(min_per_document, math.ceil(target * max_document_share))

    def take(p: dict, why: str) -> None:
        k = _key(p)
        picked.append(p)
        chosen.add(k)
        reasons[k].append(why)
        if k in prep:
            for other, vec in prep.items():
                near[other] = max(near[other], 1 - _distance(prep[k], vec))
        doc_n[p["sha256"]] += 1
        cluster_n[p["cluster"]] += 1
        chapter_n[(p["sha256"], p["chapter"])] += 1
        type_n[p["layout_type"]] += 1
        for x in p["labels"]:
            label_n[x["label"]] += 1

    def gain(p: dict) -> float:
        names = [x["label"] for x in p["labels"] if x["label"] not in CONTEXT_LABELS]
        fresh = sum(label_n[n] == 0 for n in names)
        return (p["distinctiveness"]["score"] + 0.3 * min(fresh, 2) + (0.25 if type_n[p["layout_type"]] == 0 else 0)
                - 0.8 * near[_key(p)] - 0.5 * doc_n[p["sha256"]] / doc_cap - 0.15 * chapter_n[(p["sha256"], p["chapter"])]
                - 0.3 * cluster_n[p["cluster"]] - 3 * type_n[p["layout_type"]] / target)

    def best(cands: List[dict]) -> Optional[dict]:
        return max(cands, key=lambda p: (round(gain(p), 9), p["sha256"], -p["page"]), default=None)

    def free(p: dict, caps: bool = True) -> bool:
        if _key(p) in chosen:
            return False
        return not caps or (doc_n[p["sha256"]] < doc_cap and cluster_n[p["cluster"]] < max_per_cluster and
                            chapter_n[(p["sha256"], p["chapter"])] < max_per_chapter)

    for k in sorted(kept):
        if k in by_key:
            take(by_key[k], "kept by a human reviewer")
    for sha in sorted({p["sha256"] for p in pool}):
        doc_pages = [p for p in pool if p["sha256"] == sha]
        while doc_n[sha] < min_per_document:
            p = best([q for q in doc_pages if free(q, caps=False)])
            if p is None:
                break
            take(p, f"document coverage: among the most distinct pages of {p['file'].rsplit('/', 1)[-1]}")
    freq = Counter(x["label"] for p in pool for x in p["labels"])
    for level in range(1, per_label + 1):                  # one more of every label per round, rarest first
        for label in sorted(freq, key=lambda n: (freq[n], n)):
            goal = min(level, 2 if label in CONTEXT_LABELS else level)
            if label_n[label] >= goal or len(picked) >= target:
                continue
            has = [p for p in pool if any(x["label"] == label for x in p["labels"])]
            cands = [p for p in has if free(p)]
            if level == 1 and not cands:                    # a label found in one document still gets its example
                cands = [p for p in has if free(p, caps=False)]
            # prefer a document this label has not come from yet
            seen = {q["sha256"] for q in picked if any(x["label"] == label for x in q["labels"])}
            p = best([q for q in cands if q["sha256"] not in seen] or cands)
            if p is not None:
                take(p, f"label coverage: {LABELS[label]} ({freq[label]} pages in the corpus)")
    while len(picked) < target:
        p = best([q for q in pool if free(q)])
        if p is None:
            break
        c = p["cluster_size"]
        take(p, f"distinct layout: {c['corpus']} page(s) share this layout in the corpus, "
                f"rank {p['distinctiveness']['score']:.2f}")

    n = max(len(picked), 1)
    entries = [{"sha256": p["sha256"], "doc_id": p["doc_id"], "file": p["file"], "page": p["page"],
                "source": "human" if _key(p) in kept else "algorithm", "layout_type": p["layout_type"],
                "labels": [x["label"] for x in p["labels"]], "cluster": p["cluster"], "chapter": p["chapter"],
                "distinctiveness": p["distinctiveness"]["score"], "reasons": reasons[_key(p)]}
               for p in sorted(picked, key=lambda q: (q["file"], q["page"]))]
    by_file = Counter(p["file"] for p in picked)
    return {"method": "greedy selection: human-kept pages, then every document, every label, then the most distinct "
                      "remaining page; penalised for similarity to chosen pages, and capped per document, layout "
                      "and chapter. Distinctiveness measures difference, not quality.",
            "parameters": {"target": target, "min_per_document": min_per_document,
                           "max_document_share": max_document_share, "per_label": per_label,
                           "max_per_cluster": max_per_cluster, "max_per_chapter": max_per_chapter},
            "coverage": {"pages": len(picked), "by_document": dict(sorted(by_file.items())),
                         "largest_document_share": _r(max(by_file.values(), default=0) / n),
                         "by_label": dict(sorted(label_n.items())), "by_layout_type": dict(sorted(type_n.items())),
                         "layouts": len(cluster_n), "largest_layout_share": _r(max(cluster_n.values(), default=0) / n),
                         "chapters": len(chapter_n)},
            "entries": entries}
