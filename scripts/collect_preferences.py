"""
Collect human layout preferences (input for the optional LightGBM ranker).

    python scripts/collect_preferences.py OUT_DIR [--docs a,b,c]

For every corpus document, renders each *valid* composition candidate
(baseline, balanced, compact, editorial, data — whichever apply), writes one
contact sheet per candidate and a ``pairs.csv`` listing every candidate pair
with its geometry metrics. A human opens the two sheets of each pair and fills
the ``preferred`` column with ``left``, ``right`` or ``equal``.

Nothing is labelled automatically: the training script refuses rows whose
``preferred`` field is empty.
"""
import csv
import io
import itertools
import json
import os
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))
sys.path.insert(0, os.path.join(HERE, ".."))


def main():
    warnings.simplefilter("ignore")
    from conftest import all_fixtures, fixture_text
    from dynamic_pdf import DocumentBuilder
    from dynamic_pdf.intelligence.analysis import measure_blocks
    from dynamic_pdf.intelligence.candidates import apply
    from dynamic_pdf.intelligence.geometry import Geometry
    from dynamic_pdf.intelligence.scoring import score_layout
    from dynamic_pdf.layout.engine import LayoutEngine
    from dynamic_pdf.qa import contact_sheet, rasterize_pdf
    from stress_docs import STRESS

    out = sys.argv[1]
    only = set(sys.argv[sys.argv.index("--docs") + 1].split(",")) if "--docs" in sys.argv else None
    os.makedirs(out, exist_ok=True)
    jobs = {k: (lambda f=f: f(os.path.join(out, "assets"))) for k, f in STRESS.items()}
    for n in all_fixtures():
        jobs["fx_" + n[:-3]] = (lambda n=n: DocumentBuilder.from_markdown(fixture_text(n)))
    rows = []
    for name, make in jobs.items():
        if only and name not in only:
            continue
        b = make().design()
        doc, theme = b._prepared()
        ms, fg = measure_blocks(doc, theme)
        page_w = fg.width + theme.spacing.page_margin_left + theme.spacing.page_margin_right
        variants = {"baseline": (doc, theme)}
        for cand in ("balanced", "compact", "editorial", "data"):
            d, t, _ = apply(cand, doc, theme, page_w, ms)
            variants[cand] = (d, t)
        metrics = {}
        for cand, (d, t) in variants.items():
            geo = Geometry()
            buf = io.BytesIO()
            LayoutEngine(d, theme=t, geometry=geo).render(buf)
            s = score_layout(geo, d, t)
            if not s.valid:
                continue                    # only valid layouts are ever ranked
            metrics[cand] = s.metrics
            imgs = rasterize_pdf(buf.getvalue(), os.path.join(out, name, cand), dpi=45)
            contact_sheet(imgs[:12], os.path.join(out, f"{name}__{cand}.png"), columns=6, thumb_width=200)
        for a, c in itertools.combinations(sorted(metrics), 2):
            rows.append({"pair_id": f"{name}:{a}:{c}", "document": name, "left": a, "right": c,
                         "left_sheet": f"{name}__{a}.png", "right_sheet": f"{name}__{c}.png",
                         "left_metrics": json.dumps(metrics[a]), "right_metrics": json.dumps(metrics[c]),
                         "preferred": ""})
        print(name, sorted(metrics))
    with open(os.path.join(out, "pairs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["pair_id"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} pairs written to {os.path.join(out, 'pairs.csv')} — fill 'preferred' "
          "with left / right / equal after viewing the two sheets")


if __name__ == "__main__":
    main()
