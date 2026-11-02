"""
Render the stress corpus + fixtures to PDF and DOCX, rasterize every page and
write contact sheets plus a metrics JSON (pages, page fill, QA findings).

    python scripts/render_samples.py OUT_DIR [--only name1,name2] [--no-docx]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))
sys.path.insert(0, os.path.join(HERE, ".."))


def page_fill(pdf_bytes):
    """Per page: fraction of the text block height that holds content."""
    import pymupdf
    out = []
    for p in pymupdf.open(stream=pdf_bytes, filetype="pdf"):
        H = p.rect.height
        ys = [b[3] for b in p.get_text("blocks") if b[4].strip() and 50 < b[1] < H - 60]
        ys += [im["bbox"][3] for im in p.get_image_info()]
        top = 72
        out.append(round(max(0.0, (max(ys) - top) / (H - 2 * top)) if ys else 0.0, 2))
    return out


def main():
    import warnings
    warnings.simplefilter("ignore")
    from stress_docs import STRESS
    from conftest import fixture_text, all_fixtures
    from dynamic_pdf import DocumentBuilder
    from dynamic_pdf.qa import check_pdf, contact_sheet, docx_to_pdf, rasterize_pdf
    out = sys.argv[1]
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    os.makedirs(out, exist_ok=True)
    jobs = {k: (lambda f=f: f(os.path.join(out, "assets"))) for k, f in STRESS.items()}
    for n in all_fixtures():
        jobs["fx_" + n[:-3]] = (lambda n=n: DocumentBuilder.from_markdown(fixture_text(n)))
    metrics = {}
    for name, make in jobs.items():
        if only and name not in only:
            continue
        b = make().design("auto")
        pdf = b.render()
        sp = b.last_render.theme.spacing
        from dynamic_pdf.qa.loop import qa_context
        qa = check_pdf(pdf, margins={"left": sp.page_margin_left, "right": sp.page_margin_right},
                       heading_texts=[o.text for o in b.semantic().outline],
                       **qa_context(b.last_render.document, b.last_render.theme))
        m = {"profile": b.design_explain()["profile"], "pdf_pages": qa.pages,
             "pdf_fill": page_fill(pdf), "pdf_qa": qa.summary()}
        imgs = rasterize_pdf(pdf, os.path.join(out, name, "pdf"), dpi=50)
        contact_sheet(imgs[:16], os.path.join(out, f"{name}-pdf.png"), columns=4, thumb_width=260)
        with open(os.path.join(out, name + ".pdf"), "wb") as f:
            f.write(pdf)
        if "--no-docx" not in sys.argv:
            dx = b.render_docx()
            with open(os.path.join(out, name + ".docx"), "wb") as f:
                f.write(dx)
            from dynamic_pdf.qa import check_docx
            drep = check_docx(dx, heading_texts=[o.text for o in b.semantic().outline])
            m["docx_qa"] = drep.summary()
            dpdf = docx_to_pdf(dx)
            if dpdf:
                m["docx_pages"] = len(page_fill(dpdf))
                m["docx_fill"] = page_fill(dpdf)
                dimgs = rasterize_pdf(dpdf, os.path.join(out, name, "docx"), dpi=50)
                contact_sheet(dimgs[:16], os.path.join(out, f"{name}-docx.png"), columns=4, thumb_width=260)
        metrics[name] = m
        print(name, json.dumps(m, ensure_ascii=False))
    with open(os.path.join(out, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
