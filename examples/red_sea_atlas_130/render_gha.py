#!/usr/bin/env python3
"""Red Sea Atlas: authentic Dynamic-PDF-Builder, no paid AI/API calls.

Input is the separately versioned 130-section Arabic editorial source.
Outputs PDF, DOCX, PNG review samples and a machine-readable QA report.
Illustrative city locator maps use Basemap coastlines, not nautical charts.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "artifacts"
ASSETS = OUT / "maps"
CONTENT = ROOT / "content_ar.md"
LATLON = {
    "السويس":(29.97,32.55),"العين السخنة":(29.66,32.36),"الزعفرانة":(29.09,32.65),
    "رأس غارب":(28.36,33.08),"الغردقة":(27.26,33.80),"الجونة":(27.39,33.68),
    "سفاجا":(26.74,33.94),"القصير":(26.10,34.27),"مرسى علم":(25.06,34.90),
    "شلاتين":(23.13,35.60),"شرم الشيخ":(27.92,34.33),"دهب":(28.49,34.51),
    "نويبع":(29.04,34.66),"طابا":(29.49,34.90),"ضبا":(27.35,35.69),
    "الوجه":(26.25,36.45),"أملج":(25.05,37.27),"ينبع":(24.09,38.06),
    "رابغ":(22.80,39.03),"جدة":(21.49,39.19),"الليث":(20.15,40.26),
    "القنفذة":(19.13,41.08),"جازان":(16.89,42.57),"فرسان":(16.70,42.11),
    "العقبة":(29.53,35.00),"إيلات":(29.56,34.95),"بورتسودان":(19.62,37.22),
    "سواكن":(19.11,37.33),"طوكر":(18.43,37.73),"عقيق":(18.26,38.14),
    "دنقناب":(20.93,37.15),"مصوع":(15.61,39.46),"عصب":(13.01,42.74),
    "جيبوتي":(11.59,43.15),"الحديدة":(14.80,42.95),"المخا":(13.32,43.25),
    "ميدي":(16.32,42.80),"الصليف":(15.33,42.67)
}

def parse_sections(text):
    matches = list(re.finditer(r"(?m)^# (.+)\s*$", text))
    sections = []
    for n, hit in enumerate(matches):
        end = matches[n + 1].start() if n + 1 < len(matches) else len(text)
        title = hit.group(1).strip()
        raw = text[hit.end():end].strip()
        paragraphs = [s.strip() for s in re.split(r"\n\s*\n", raw) if s.strip()]
        sections.append((title, paragraphs))
    if len(sections) != 130:
        raise ValueError(f"Expected 130 distinct chapter/page entries, got {len(sections)}")
    return sections

def create_locator(name, coord=None, overview=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.basemap import Basemap
    ASSETS.mkdir(parents=True, exist_ok=True)
    if coord:
        lat, lon = coord
        region = "north" if lat > 26.6 else ("middle" if lat > 20 else "south")
    else:
        region = "all"
    bounds = {
        "all":(32,46,11,31.6),
        "north":(32,38,25.0,31.7),
        "middle":(32.6,41.7,18.1,28.5),
        "south":(35.5,45.2,10.8,21.1),
    }
    w, e, s, n = bounds[region]
    fig = plt.figure(figsize=(5.3, 4.1 if coord else 7.1), dpi=120)
    ax = fig.add_axes([.03,.03,.94,.94])
    m = Basemap(projection="cyl", llcrnrlon=w, urcrnrlon=e, llcrnrlat=s,
                urcrnrlat=n, resolution="l", ax=ax)
    m.drawmapboundary(fill_color="#c9e4e7", linewidth=0)
    m.fillcontinents(color="#ede4d7", lake_color="#c9e4e7")
    m.drawcoastlines(color="#7d969b", linewidth=.6)
    m.drawcountries(color="#b1b3ad", linewidth=.35)
    if coord:
        ax.scatter([lon],[lat],s=165,c="#d68a58",edgecolor="#ffffff",linewidth=2,zorder=12)
    else:
        ax.text(38.2,24.2,"RED SEA",fontsize=20,weight="bold",
                color="#327c91",rotation=73,alpha=.8,ha="center")
    ax.text(w+.22,s+.30,"SCHEMATIC REFERENCE - NOT FOR NAVIGATION",
            fontsize=5.6,color="#34576b",alpha=.65)
    ax.axis("off")
    path = ASSETS / (("locator_" + str(list(LATLON).index(name)) + ".png") if coord else "overview.png")
    fig.savefig(path, dpi=120, facecolor="#ffffff", bbox_inches="tight", pad_inches=.02)
    plt.close(fig)
    return path

def build():
    from dynamic_pdf import DocumentBuilder
    sections = parse_sections(CONTENT.read_text(encoding="utf-8"))
    b = (DocumentBuilder(theme="claude")
         .meta(title="البحر الأحمر: أطلس المدن والطبيعة والممرات",
               author="Independent Editorial Atlas",language="ar",
               subject="جغرافيا البحر الأحمر ومدنه ونظمه البيئية وتاريخه واقتصاده",
               keywords=["البحر الأحمر","الأطلس","المدن","الشعاب","الموانئ"])
         .direction("rtl").design(None))
    # The atlas has its own two-page editorial index. Disable generated duplicate TOC,
    # which otherwise adds five unrequested pages to a 130-unit reference.
    for index, (title, paragraphs) in enumerate(sections):
        if index == 0:
            b.cover_page(
                "البحر الأحمر: مدن ومياه وذاكرة مشتركة",
                subtitle="أطلس بحثي مصور | مدن ساحلية وجغرافيا وبيئة وتراث",
                date="نوفمبر 2026",layout="centered",
                background_color="#113849",text_color="#FFFFFF",
            )
            continue
        b.heading(title, level=1)
        if title == "خريطة البحر الأحمر الكبرى":
            b.image(str(create_locator("overview", overview=True)), width=270,
                    caption="مرجع جغرافي عام غير مخصص للملاحة",
                    alt_text="خريطة توضيحية لامتداد البحر الأحمر")
        if title in LATLON:
            b.image(str(create_locator(title, LATLON[title])), width=248,
                    caption="موقع تقريبي؛ ليست خريطة ملاحية",
                    alt_text="موقع ساحلي تقريبي على البحر الأحمر")
        for text in paragraphs:
            if text.startswith("ملاحظة منهجية:"):
                b.callout(text,variant="info")
            elif text.startswith("الأولوية:"):
                b.callout(text,variant="info",title="أولوية محلية")
            elif text.startswith("المراجع:"):
                if text.strip() != "المراجع:":
                    b.paragraph(text)
            elif len(text)>0:
                b.paragraph(text)
        if title == "قناة السويس في 2025":
            b.table(["السنة","عبور السفن"], [["2024","13,213"],["2025","12,758"]],
                    caption="هيئة قناة السويس، التقرير السنوي 2025")
        if index < len(sections)-1:
            b.page_break()
    return b, sections

def qa(pdf_path, sections):
    import fitz
    p = fitz.open(pdf_path)
    observations = []
    for i, page in enumerate(p,1):
        text = page.get_text(sort=True)
        overflows = []
        for block in page.get_text("blocks"):
            if len(block)<7 or block[6]!=0:
                continue
            x0,y0,x1,y1 = block[:4]
            if x0 < -1 or y0 < -1 or x1 > page.rect.width+1 or y1 > page.rect.height+1:
                overflows.append([round(x,2) for x in block[:4]])
        observations.append({"page":i,"text_chars":len(text),"blocks_outside":overflows})
    metrics = {
        "engine":"Dynamic-PDF-Builder",
        "page_count":len(p),
        "editorial_units":len(sections),
        "page_count_exactly_130":len(p)==130,
        "all_pages_nonblank":all(x["text_chars"]>10 for x in observations),
        "outside_text_blocks":sum(len(x["blocks_outside"]) for x in observations),
        "extracted_arabic_samples": [p[i].get_text()[:200] for i in (0,min(54,len(p)-1),len(p)-1)],
        "pages":observations,
    }
    (OUT/"qa.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding="utf-8")
    from PIL import Image,ImageOps,ImageDraw
    thumbs=[]
    indexes=list(range(0,len(p),max(1,len(p)//20)))[:22]
    for i in indexes:
        pix=p[i].get_pixmap(matrix=fitz.Matrix(1.0,1.0),alpha=False)
        im=Image.frombytes("RGB",[pix.width,pix.height],pix.samples)
        im.thumbnail((240,330))
        tile=Image.new("RGB",(260,364),"#eef4f3")
        tile.paste(im,((260-im.width)//2,10))
        ImageDraw.Draw(tile).text((12,340),f"PAGE {i+1}",fill="#193c48")
        thumbs.append(tile)
    columns=5
    sheet=Image.new("RGB",(columns*260, ((len(thumbs)+columns-1)//columns)*364),"#eff4f3")
    for j,im in enumerate(thumbs):
        sheet.paste(im,((j%columns)*260,(j//columns)*364))
    sheet.save(OUT/"contact_sheet.jpg",quality=88)
    print("QA",json.dumps({k:v for k,v in metrics.items() if k!="pages"},ensure_ascii=False)[:1300],flush=True)
    return metrics

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--pdf-only",action="store_true")
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    builder,sections=build()
    pdf=OUT/"Red_Sea_Atlas_DynamicPDF.pdf"
    builder.render(str(pdf))
    print("PDF generated",pdf.stat().st_size,flush=True)
    metrics=qa(pdf,sections)
    if not args.pdf_only:
        try:
            builder.render_docx(str(OUT/"Red_Sea_Atlas_DynamicPDF.docx"))
            print("DOCX generated",flush=True)
        except Exception as exc:
            (OUT/"docx_error.txt").write_text(repr(exc),encoding="utf-8")
            print("DOCX export failed:",repr(exc),flush=True)
    if metrics["page_count"]!=130 or not metrics["all_pages_nonblank"]:
        raise SystemExit("Page QA needs review; see uploaded artifact, no baseline modified")

if __name__=="__main__":
    main()
