"""Every theme, as Microsoft Word itself lays it out (Windows only).

    python -m benchmarks.word.check build OUT     # the DOCX and our PDF of each theme, English and Arabic
    python -m benchmarks.word.check word OUT      # Word opens each DOCX and saves it as PDF
    python -m benchmarks.word.check sheets OUT    # contact sheets of Word's pages, and report.json

Word runs one document at a time in a child process with a time limit, so a dialog that
waits for a person cannot hang the run.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

LANGS = ("en", "ar")


def _looks():
    from dynamic_pdf.design.looks import LOOKS
    return list(LOOKS)


def build(out: Path) -> None:
    from dynamic_pdf import DocumentBuilder
    from dynamic_pdf.schema.blocks import MetricItem, MetricRowBlock
    from .sample import AR, EN
    out.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        for name in _looks():
            b = DocumentBuilder.from_markdown(EN if lang == "en" else AR)
            for i, blk in enumerate(b._blocks):       # the sample's figures as a real row of key figures
                if blk.type == "callout" and "|" in blk.text:
                    rows = [[c.strip() for c in ln.split("|")] for ln in blk.text.splitlines() if "|" in ln]
                    b._blocks[i] = MetricRowBlock(metrics=[MetricItem(label=r[0], value=r[1], delta=r[2])
                                                           for r in rows])
            b.theme(name)
            (out / f"{name}_{lang}.docx").write_bytes(b.render_docx())
            (out / f"{name}_{lang}.ours.pdf").write_bytes(b.render())
            print("built", name, lang, flush=True)


def convert_one(src: Path, dst: Path) -> dict:
    """Word opens ``src`` and writes ``dst``: by its own PDF export, or, where an unlicensed Office
    allows only viewing and printing, through the Microsoft Print to PDF printer."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible, word.DisplayAlerts = False, 0
    info: dict = {"file": src.name}
    try:
        doc = word.Documents.Open(str(src), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False,
                                  Visible=False)
        info["word_pages"] = doc.ComputeStatistics(2)          # wdStatisticPages
        try:
            doc.ExportAsFixedFormat(str(dst), 17)               # wdExportFormatPDF
            info["route"] = "export"
        except Exception as e:  # noqa: BLE001 - recorded, then the printer is tried
            info["export_error"] = str(e)[:300]
            word.ActivePrinter = "Microsoft Print to PDF"
            doc.PrintOut(Background=False, OutputFileName=str(dst), PrintToFile=True)
            info["route"] = "print"
        doc.Close(False)
    finally:
        word.Quit()
    return info


def word(out: Path) -> None:
    results = []
    for src in sorted(out.glob("*.docx")):
        dst = src.with_suffix(".word.pdf")
        began = time.monotonic()
        try:
            run = subprocess.run([sys.executable, "-m", "benchmarks.word.check", "one", str(src), str(dst)],
                                 capture_output=True, text=True, timeout=300)
            line = (run.stdout.strip().splitlines() or ["{}"])[-1]
            try:
                info = json.loads(line)
            except ValueError:
                info = {"file": src.name}
            if run.returncode:
                info["error"] = (run.stderr or run.stdout)[-600:]
        except subprocess.TimeoutExpired:            # Word is waiting on a dialog nobody can answer
            info = {"file": src.name, "error": "Word did not finish within 300 s"}
        info["seconds"] = round(time.monotonic() - began, 1)
        info["pdf"] = dst.exists() and dst.stat().st_size > 0
        results.append(info)
        print(json.dumps(info), flush=True)
        subprocess.run(["taskkill", "/f", "/im", "WINWORD.EXE"], capture_output=True)
    (out / "word.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")


def _fonts(pdf: Path) -> list:
    """Font names a PDF names in the clear (Word writes its font dictionaries uncompressed)."""
    names = re.findall(rb"/BaseFont\s*/([A-Za-z0-9+#\-_,]+)", pdf.read_bytes())
    return sorted({n.decode(errors="replace").split("+")[-1] for n in names})


def sheets(out: Path) -> None:
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    report = {i["file"]: i for i in json.loads((out / "word.json").read_text(encoding="utf-8"))}
    for lang in LANGS:
        for part, names in enumerate((_looks()[:4], _looks()[4:]), 1):
            rows = []
            for name in names:
                src = out / f"{name}_{lang}.word.pdf"
                info = report.get(f"{name}_{lang}.docx", {})
                if src.exists() and src.stat().st_size:
                    doc = pdfium.PdfDocument(str(src))
                    pages = [doc[i].render(scale=0.62).to_pil() for i in range(min(3, len(doc)))]
                    info["word_pdf_pages"] = len(doc)
                    info["ours_pages"] = len(pdfium.PdfDocument(str(out / f"{name}_{lang}.ours.pdf")))
                    info["fonts"] = _fonts(src)
                else:
                    pages = [Image.new("RGB", (369, 522), "white")]
                w, h = pages[0].size
                row = Image.new("RGB", ((w + 4) * 3, h + 18), "#dddddd")
                ImageDraw.Draw(row).text((4, 3), f"{name} {lang} - Word {info.get('route', 'FAILED')}", fill="#cc0000")
                for i, pg in enumerate(pages):
                    row.paste(pg, (i * (w + 4), 18))
                rows.append(row)
            sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 6 for r in rows)), "#555555")
            y = 0
            for r in rows:
                sheet.paste(r, (0, y))
                y += r.height + 6
            sheet.save(out / f"word_{lang}_{part}.png")
    (out / "report.json").write_text(json.dumps(list(report.values()), indent=1, ensure_ascii=False),
                                     encoding="utf-8")


if __name__ == "__main__":
    step, *rest = sys.argv[1:]
    if step == "one":
        print(json.dumps(convert_one(Path(rest[0]).resolve(), Path(rest[1]).resolve())))
    else:
        {"build": build, "word": word, "sheets": sheets}[step](Path(rest[0]).resolve())
