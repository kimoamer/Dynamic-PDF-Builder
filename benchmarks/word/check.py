"""Every theme as Microsoft Word lays it out, and every workbook as Microsoft Excel computes it
(Windows only).

    python -m benchmarks.word.check build OUT     # each theme's DOCX and our PDF; workbooks and the values we show
    python -m benchmarks.word.check word OUT      # Word opens each DOCX and saves it as PDF
    python -m benchmarks.word.check excel OUT     # Excel opens each workbook, recalculates, compares, saves as PDF
    python -m benchmarks.word.check sheets OUT    # contact sheets of Word's and Excel's pages, and report.json

Each file is opened in a child process with a time limit, so a dialog that waits for a person
cannot hang the run.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

LANGS = ("en", "ar")
WORKBOOK_KITS = ("feasibility", "invoice", "quote", "statements")


def _looks():
    from dynamic_pdf.design.looks import LOOKS
    return list(LOOKS)


def _shown(b, data: bytes) -> dict:
    """Every formula cell of the workbook ``b`` wrote, with the value our document shows for it and how
    far apart two values may be at the places it is shown to."""
    import io

    import openpyxl
    from dynamic_pdf.core.table_types import read_cell
    doc = b.build()
    tables = [d for s, d in zip(b._blocks, doc.blocks) if getattr(s, "type", None) == "table"]
    expected = {}
    for ws, d in zip(openpyxl.load_workbook(io.BytesIO(data)).worksheets, tables):
        grid = [list(d.headers)] + [list(r) for r in d.rows] + ([list(d.footer_row)] if d.footer_row else [])
        for row in ws.iter_rows():
            for cell in row:
                if not (isinstance(cell.value, str) and cell.value.startswith("=")):
                    continue
                text = str(grid[cell.row - 1][cell.column - 1])
                read = read_cell(text)
                if read.value is None:
                    continue
                places = len(m.group(1)) if (m := re.search(r"[.٫](\d+)", text)) else 0
                scale = 100 if read.kind == "percent" else 1
                expected[f"{ws.title}!{cell.coordinate}"] = {
                    "formula": cell.value, "ours": text, "value": read.value / scale,
                    "tolerance": 0.5 * 10 ** -places / scale + 1e-9}
    return expected


def build(out: Path) -> None:
    from dynamic_pdf import DocumentBuilder, kit, kit_example
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
    books = {f"kit_{k}": kit(k, kit_example(k)) for k in WORKBOOK_KITS}
    books.update({f"report_{lang}": DocumentBuilder.from_markdown(EN if lang == "en" else AR) for lang in LANGS})
    for name, b in books.items():
        data = b.render_xlsx()
        (out / f"{name}.xlsx").write_bytes(data)
        (out / f"{name}.expected.json").write_text(json.dumps(_shown(b, data), ensure_ascii=False, indent=1),
                                                   encoding="utf-8")
        print("built", name, flush=True)


def word_one(src: Path, dst: Path) -> dict:
    """Word opens ``src`` and writes ``dst``: by its own PDF export, or, where an unlicensed Office
    allows only viewing and printing, through the Microsoft Print to PDF printer."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible, word.DisplayAlerts = False, 0
    info: dict = {"file": src.name, "word": f"{word.Version} build {word.Build}"}
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


def excel_one(src: Path, dst: Path) -> dict:
    """Excel opens ``src``, recalculates every formula, and each result is compared with the value
    our document shows for that cell; then the workbook is saved as PDF."""
    import pythoncom
    import win32com.client
    expected = json.loads(src.with_suffix(".expected.json").read_text(encoding="utf-8"))
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible, xl.DisplayAlerts = False, False
    info: dict = {"file": src.name, "excel": f"{xl.Version} build {xl.Build}", "formulas": len(expected)}
    try:
        wb = xl.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True)
        xl.CalculateFull()
        wrong = []
        for key, e in expected.items():
            sheet, address = key.rsplit("!", 1)
            got = wb.Worksheets(sheet).Range(address).Value
            # an error cell (#VALUE!, #NAME? ...) comes back as a large negative integer code
            if not isinstance(got, (int, float)) or abs(got - e["value"]) > e["tolerance"]:
                wrong.append({"cell": key, "formula": e["formula"], "ours": e["ours"], "excel": got})
        info["mismatches"] = wrong
        try:
            wb.ExportAsFixedFormat(0, str(dst))                 # xlTypePDF
            info["route"] = "export"
        except Exception as e:  # noqa: BLE001 - recorded; the values were still compared
            info["export_error"] = str(e)[:300]
        wb.Close(False)
    finally:
        xl.Quit()
    return info


APPS = {"word": ("*.docx", "WINWORD.EXE", word_one), "excel": ("*.xlsx", "EXCEL.EXE", excel_one)}


def run_app(out: Path, app: str) -> None:
    pattern, image, _ = APPS[app]
    results = []
    for src in sorted(out.glob(pattern)):
        dst = src.with_suffix(f".{app}.pdf")
        began = time.monotonic()
        try:
            run = subprocess.run([sys.executable, "-m", "benchmarks.word.check", "one", app, str(src), str(dst)],
                                 capture_output=True, text=True, timeout=300)
            line = (run.stdout.strip().splitlines() or ["{}"])[-1]
            try:
                info = json.loads(line)
            except ValueError:
                info = {"file": src.name}
            if run.returncode:
                info["error"] = (run.stderr or run.stdout)[-600:]
        except subprocess.TimeoutExpired:            # the program is waiting on a dialog nobody can answer
            info = {"file": src.name, "error": f"{app} did not finish within 300 s"}
        info["seconds"] = round(time.monotonic() - began, 1)
        info["pdf"] = dst.exists() and dst.stat().st_size > 0
        results.append(info)
        print(json.dumps(info, ensure_ascii=False, default=str), flush=True)
        subprocess.run(["taskkill", "/f", "/im", image], capture_output=True)
    (out / f"{app}.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str),
                                     encoding="utf-8")


def _fonts(pdf: Path) -> list:
    """Font names a PDF names in the clear (Word writes its font dictionaries uncompressed)."""
    names = re.findall(rb"/BaseFont\s*/([A-Za-z0-9+#\-_,]+)", pdf.read_bytes())
    return sorted({n.decode(errors="replace").split("+")[-1] for n in names})


def _percents(pdf: Path) -> list:
    """Each Arabic percent sign the PDF draws to the right of its number."""
    import pymupdf
    from dynamic_pdf.qa.percent_geometry import misplaced_arabic_percent
    return [text for page in pymupdf.open(str(pdf)) for _, text in misplaced_arabic_percent(page.get_text("rawdict"))]


def _sheet(rows, path: Path) -> None:
    from PIL import Image
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 6 for r in rows)), "#555555")
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 6
    sheet.save(path)


def _row(pdf: Path, label: str, pages: int):
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    shots = ([pdfium.PdfDocument(str(pdf))[i].render(scale=0.62).to_pil()
              for i in range(min(pages, len(pdfium.PdfDocument(str(pdf)))))]
             if pdf.exists() and pdf.stat().st_size else [Image.new("RGB", (369, 522), "white")])
    w, h = shots[0].size
    row = Image.new("RGB", ((w + 4) * 3, h + 18), "#dddddd")
    ImageDraw.Draw(row).text((4, 3), label, fill="#cc0000")
    for i, pg in enumerate(shots):
        row.paste(pg, (i * (w + 4), 18))
    return row


def sheets(out: Path) -> None:
    import pypdfium2 as pdfium
    report = {}
    for app in APPS:
        path = out / f"{app}.json"
        if path.exists():
            report.update({i["file"]: i for i in json.loads(path.read_text(encoding="utf-8"))})
    for lang in LANGS:
        for part, names in enumerate((_looks()[:4], _looks()[4:]), 1):
            rows = []
            for name in names:
                src = out / f"{name}_{lang}.word.pdf"
                info = report.get(f"{name}_{lang}.docx", {})
                if src.exists() and src.stat().st_size:
                    info["word_pdf_pages"] = len(pdfium.PdfDocument(str(src)))
                    info["ours_pages"] = len(pdfium.PdfDocument(str(out / f"{name}_{lang}.ours.pdf")))
                    info["fonts"] = _fonts(src)
                    if lang == "ar":              # Word set each percent sign after its number (to its left)
                        info["percent_misplaced"] = _percents(src)
                rows.append(_row(src, f"{name} {lang} - Word {info.get('route', 'FAILED')}", 3))
            _sheet(rows, out / f"word_{lang}_{part}.png")
    books = sorted(out.glob("*.xlsx"))
    if books:
        rows = []
        for book in books:
            info = report.get(book.name, {})
            wrong = len(info.get("mismatches", []))
            rows.append(_row(book.with_suffix(".excel.pdf"),
                             f"{book.stem} - Excel {info.get('route', 'FAILED')} - {info.get('formulas', 0)} formulas, "
                             f"{wrong} differ", 3))
        _sheet(rows, out / "excel.png")
    (out / "report.json").write_text(json.dumps(list(report.values()), indent=1, ensure_ascii=False, default=str),
                                     encoding="utf-8")


if __name__ == "__main__":
    step, *rest = sys.argv[1:]
    if step == "one":
        app, src, dst = rest
        print(json.dumps(APPS[app][2](Path(src).resolve(), Path(dst).resolve()), ensure_ascii=False, default=str))
    elif step in APPS:
        run_app(Path(rest[0]).resolve(), step)
    else:
        {"build": build, "sheets": sheets}[step](Path(rest[0]).resolve())
