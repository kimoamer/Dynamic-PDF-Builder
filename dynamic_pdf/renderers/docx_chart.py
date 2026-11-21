"""
Charts as native Word charts: the data and the formatting can be edited in Word, and the
labels are real text (Arabic is shaped by Word). Bars, columns, grouped and stacked bars,
lines, areas, pies and doughnuts; the other types stay pictures.

The chart part carries its values in the chart itself. When ``openpyxl`` is installed (the
``xlsx`` extra) a workbook with the same values is embedded too, so Word's "Edit Data" opens it.
"""
from __future__ import annotations

import io
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml

CT_CHART = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NS = ('xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
# chart type -> (Word chart, bar direction, grouping)
NATIVE = {"bar": ("bar", "col", "clustered"), "vertical_bar": ("bar", "col", "clustered"),
          "horizontal_bar": ("bar", "bar", "clustered"), "grouped_bar": ("bar", "col", "clustered"),
          "stacked_bar": ("bar", "col", "stacked"), "line": ("line", None, "standard"),
          "area": ("area", None, "stacked"), "pie": ("pie", None, None), "donut": ("doughnut", None, None)}
ONE_SERIES = {"bar", "vertical_bar", "horizontal_bar", "pie", "donut"}


def series_of(key: str, data) -> Tuple[List[str], Dict[str, List[float]]]:
    """(categories, {series: values}), read as the PDF chart reads them."""
    from .chart import _check_data, _multi_series, _simple
    _check_data(key, data)
    multi = isinstance(data, dict) and data and (
        "series" in data or isinstance(next(iter(data.values())), dict))
    if key in ONE_SERIES or not multi:
        labels, values = _simple(data)
        return [str(x) for x in labels], {"": values}
    cats, series = _multi_series(data)
    return [str(x) for x in cats], {str(k): [float(v) for v in vals] for k, vals in series.items()}


def _col(n: int) -> str:
    return chr(ord("A") + n) if n < 26 else _col(n // 26 - 1) + chr(ord("A") + n % 26)


def _strs(values, ref: Optional[str]) -> str:
    pts = "".join(f'<c:pt idx="{i}"><c:v>{escape(v)}</c:v></c:pt>' for i, v in enumerate(values))
    body = f'<c:ptCount val="{len(values)}"/>{pts}'
    return f"<c:strRef><c:f>{ref}</c:f><c:strCache>{body}</c:strCache></c:strRef>" if ref else f"<c:strLit>{body}</c:strLit>"


def _nums(values, ref: Optional[str]) -> str:
    pts = "".join(f'<c:pt idx="{i}"><c:v>{v:g}</c:v></c:pt>' for i, v in enumerate(values))
    body = f'<c:formatCode>General</c:formatCode><c:ptCount val="{len(values)}"/>{pts}'
    return f"<c:numRef><c:f>{ref}</c:f><c:numCache>{body}</c:numCache></c:numRef>" if ref else f"<c:numLit>{body}</c:numLit>"


def _ceiling(series: Dict[str, List[float]], stacked: bool) -> Optional[float]:
    """A round top for the value axis, above the tallest bar and its label: LibreOffice's own
    can sit under the tallest bar and cut it off."""
    cols = list(zip(*series.values())) if series else []
    tops = [sum(v for v in col if v > 0) if stacked else max(col) for col in cols]
    top = max(tops, default=0.0)
    if top <= 0:
        return None
    import math
    unit = 10 ** math.floor(math.log10(top))
    step = next(unit * k for k in (0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10) if top / (unit * k) <= 6)
    return math.ceil(top * 1.08 / step) * step


def _step(top: float) -> float:
    """A round tick step that divides ``top`` exactly into at most eight parts, so the top is a tick."""
    import math
    unit = 10 ** math.floor(math.log10(top))
    for k in (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10):
        parts = top / (unit * k)
        if parts <= 8 + 1e-9 and abs(parts - round(parts)) < 1e-6:
            return unit * k
    return top / 4


def _fill(hex_colour: str) -> str:
    return f'<c:spPr><a:solidFill><a:srgbClr val="{hex_colour.lstrip("#").upper()}"/></a:solidFill></c:spPr>'


def _line(hex_colour: str, width: int = 22225) -> str:
    return (f'<c:spPr><a:ln w="{width}" cap="rnd"><a:solidFill><a:srgbClr val="{hex_colour.lstrip("#").upper()}"/>'
            f'</a:solidFill></a:ln></c:spPr>')


def _labels(**show) -> str:
    flags = ("showLegendKey", "showVal", "showCatName", "showSerName", "showPercent", "showBubbleSize")
    return "<c:dLbls>" + "".join(f'<c:{f} val="{int(show.get(f, False))}"/>' for f in flags) + "</c:dLbls>"


def _slice_labels(colours: List[str], n: int) -> str:
    """Percent labels for a pie's slices, each in white or near-black, whichever reads on its slice."""
    from .chart import _ink
    flags = ("showLegendKey", "showVal", "showCatName", "showSerName", "showPercent", "showBubbleSize")
    on = "".join(f'<c:{f} val="{int(f == "showPercent")}"/>' for f in flags)
    each = []
    for j in range(n):
        ink = "FFFFFF" if _ink(colours[j % len(colours)]) == "white" else "222222"
        each.append(f'<c:dLbl><c:idx val="{j}"/><c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="900">'
                    f'<a:solidFill><a:srgbClr val="{ink}"/></a:solidFill></a:defRPr></a:pPr>'
                    f'<a:endParaRPr lang="en-US"/></a:p></c:txPr>{on}</c:dLbl>')
    return "<c:dLbls>" + "".join(each) + on + "</c:dLbls>"


def _title(text: str, size: int) -> str:
    return (f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{size}" b="1"/></a:pPr>'
            f'<a:r><a:rPr lang="en-US" sz="{size}" b="1"/><a:t>{escape(text)}</a:t></a:r></a:p></c:rich></c:tx>'
            '<c:overlay val="0"/></c:title>')


def chart_xml(key: str, cats: List[str], series: Dict[str, List[float]], colours: List[str], *,
              title: Optional[str], x_label: Optional[str], y_label: Optional[str], legend: bool,
              font: str, arabic_font: str, workbook: bool) -> bytes:
    kind, direction, grouping = NATIVE[key]
    n = len(cats)
    sers = []
    for i, (name, values) in enumerate(series.items()):
        col = _col(i + 1)
        tx = (f"<c:tx>{_strs([name], f'Sheet1!${col}$1' if workbook else None)}</c:tx>" if name else "")
        cat = f"<c:cat>{_strs(cats, f'Sheet1!$A$2:$A${n + 1}' if workbook else None)}</c:cat>"
        val = f"<c:val>{_nums(values, f'Sheet1!${col}$2:${col}${n + 1}' if workbook else None)}</c:val>"
        head = f'<c:idx val="{i}"/><c:order val="{i}"/>{tx}'
        if kind in ("pie", "doughnut") or (kind == "bar" and key in ONE_SERIES):
            # one series whose points each take their own colour, as in the PDF
            points = "".join(f'<c:dPt><c:idx val="{j}"/><c:invertIfNegative val="0"/><c:bubble3D val="0"/>{_fill(colours[j % len(colours)])}</c:dPt>'
                             if kind == "bar" else
                             f'<c:dPt><c:idx val="{j}"/><c:bubble3D val="0"/>{_fill(colours[j % len(colours)])}</c:dPt>'
                             for j in range(n))
            if kind == "bar":
                sers.append(f'<c:ser>{head}{_fill(colours[0])}<c:invertIfNegative val="0"/>{points}'
                            f'{_labels(showVal=True)}{cat}{val}</c:ser>')
            else:
                sers.append(f'<c:ser>{head}{points}{_slice_labels(colours, n)}{cat}{val}</c:ser>')
        elif kind == "bar":
            show = grouping == "clustered"
            sers.append(f'<c:ser>{head}{_fill(colours[i % len(colours)])}<c:invertIfNegative val="0"/>'
                        f'{_labels(showVal=show)}{cat}{val}</c:ser>')
        elif kind == "line":
            c = colours[i % len(colours)]
            marker = f'<c:marker><c:symbol val="circle"/><c:size val="5"/>{_fill(c)}</c:marker>'
            sers.append(f'<c:ser>{head}{_line(c)}{marker}{cat}{val}<c:smooth val="0"/></c:ser>')
        else:                                                    # area
            sers.append(f'<c:ser>{head}{_fill(colours[i % len(colours)])}{cat}{val}</c:ser>')
    axes = '<c:axId val="500"/><c:axId val="501"/>'
    vary = '<c:varyColors val="1"/>' if kind in ("pie", "doughnut") else '<c:varyColors val="0"/>'
    if kind == "bar":
        body = (f'<c:barChart><c:barDir val="{direction}"/><c:grouping val="{grouping}"/>{vary}{"".join(sers)}'
                f'<c:gapWidth val="{60 if grouping == "clustered" else 70}"/>'
                + ('<c:overlap val="100"/>' if grouping == "stacked" else "") + f"{axes}</c:barChart>")
    elif kind == "line":
        body = f'<c:lineChart><c:grouping val="standard"/>{vary}{"".join(sers)}<c:marker val="1"/>{axes}</c:lineChart>'
    elif kind == "area":
        body = f'<c:areaChart><c:grouping val="{grouping}"/>{vary}{"".join(sers)}{axes}</c:areaChart>'
    elif kind == "pie":
        body = f'<c:pieChart>{vary}{"".join(sers)}<c:firstSliceAng val="0"/></c:pieChart>'
    else:
        body = f'<c:doughnutChart>{vary}{"".join(sers)}<c:firstSliceAng val="0"/><c:holeSize val="50"/></c:doughnutChart>'
    if kind not in ("pie", "doughnut"):
        cat_pos, val_pos = ("l", "b") if direction == "bar" else ("b", "l")
        grey = '<c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="D0D0D0"/></a:solidFill></a:ln></c:spPr>'
        ceiling = _ceiling(series, grouping in ("stacked", "percentStacked"))
        scaled = ceiling is not None and grouping != "percentStacked"
        # with no value below zero the axis starts at zero and counts up in round steps: left to
        # itself LibreOffice steps down from the top and can start below zero (-1, 1, 3 ...)
        floor = scaled and all(v >= 0 for vals in series.values() for v in vals)
        top = (f'<c:max val="{ceiling:g}"/>' + ('<c:min val="0"/>' if floor else "")) if scaled else ""
        unit = f'<c:majorUnit val="{_step(ceiling):g}"/>' if floor else ""
        body += (f'<c:catAx><c:axId val="500"/><c:scaling><c:orientation val="{"maxMin" if direction == "bar" else "minMax"}"/></c:scaling>'
                 f'<c:delete val="0"/><c:axPos val="{cat_pos}"/>' + (_title(x_label, 900) if x_label else "")
                 + f'<c:numFmt formatCode="General" sourceLinked="1"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
                 f'<c:tickLblPos val="nextTo"/>{grey}<c:crossAx val="501"/><c:crosses val="autoZero"/><c:auto val="1"/>'
                 '<c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
                 f'<c:valAx><c:axId val="501"/><c:scaling><c:orientation val="minMax"/>{top}</c:scaling><c:delete val="0"/>'
                 f'<c:axPos val="{val_pos}"/><c:majorGridlines><c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="EEEEEE"/>'
                 '</a:solidFill></a:ln></c:spPr></c:majorGridlines>' + (_title(y_label, 900) if y_label else "")
                 + '<c:numFmt formatCode="General" sourceLinked="1"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
                 '<c:tickLblPos val="nextTo"/><c:spPr><a:ln><a:noFill/></a:ln></c:spPr><c:crossAx val="500"/>'
                 # bars read top-down, so the value axis crosses at the last category: the bottom
                 f'<c:crosses val="{"max" if direction == "bar" else "autoZero"}"/><c:crossBetween val="between"/>{unit}</c:valAx>')
    keyed = legend and (kind in ("pie", "doughnut") or len(series) > 1)
    text = (f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="900"><a:solidFill><a:srgbClr val="444444"/></a:solidFill>'
            f'<a:latin typeface="{escape(font)}"/><a:cs typeface="{escape(arabic_font)}"/></a:defRPr></a:pPr>'
            '<a:endParaRPr lang="en-US"/></a:p></c:txPr>')
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><c:chartSpace {NS}><c:roundedCorners val="0"/>'
           '<c:chart>' + (_title(title, 1100) + '<c:autoTitleDeleted val="0"/>' if title else '<c:autoTitleDeleted val="1"/>')
           + f'<c:plotArea><c:layout/>{body}</c:plotArea>'
           + ('<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>' if keyed else "")
           + '<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
           '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>' + text
           + ('<c:externalData r:id="rIdWorkbook"><c:autoUpdate val="0"/></c:externalData>' if workbook else "")
           + '</c:chartSpace>')
    return xml.encode("utf-8")


def workbook_bytes(cats: List[str], series: Dict[str, List[float]]) -> Optional[bytes]:
    """The values as a workbook for Word's "Edit Data", or None without openpyxl."""
    try:
        from openpyxl import Workbook
    except ImportError:
        return None
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([""] + [name or "Value" for name in series])
    for i, cat in enumerate(cats):
        ws.append([cat] + [values[i] for values in series.values()])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def add_chart(run, document_part, xml_for, cats, series, *, width_pt: float, height_pt: float, shape_id: int, alt: str):
    """Put the chart in ``run``. ``xml_for(workbook)`` writes the chart part."""
    package = document_part.package
    book = workbook_bytes(cats, series)
    part = Part(package.next_partname("/word/charts/chart%d.xml"), CT_CHART, xml_for(book is not None), package)
    if book is not None:
        sheet = Part(package.next_partname("/word/embeddings/Microsoft_Excel_Worksheet%d.xlsx"), CT_XLSX, book, package)
        part.rels.add_relationship(RT.PACKAGE, sheet, "rIdWorkbook")
    rid = document_part.relate_to(part, RT.CHART)
    emu = 12700
    drawing = parse_xml(
        '<w:drawing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{int(width_pt * emu)}" cy="{int(height_pt * emu)}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{shape_id}" name="Chart {shape_id}" descr="{escape(alt, {chr(34): "&quot;"})}"/>'
        '<wp:cNvGraphicFramePr/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        f'<c:chart r:id="{rid}"/></a:graphicData></a:graphic></wp:inline></w:drawing>')
    run._r.append(drawing)
