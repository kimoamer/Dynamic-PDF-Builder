"""
Ready-made documents: give the data, get the whole document with every part it needs.

    from dynamic_pdf import kit
    kit("invoice", data).export("invoice.pdf")      # or .docx, or .xlsx for the lines with formulas

``kits()`` names them and ``kit_example(name)`` returns example data to start from; the CLI is
``dynamic-pdf kit invoice data.json -o invoice.pdf`` (``--example`` prints the example). A kit writes
Markdown and reads it like any other document, so the result is designed, checked and editable, and
its figures are formulas computed by the library, not by the caller.
"""
from __future__ import annotations

import copy
import json
from decimal import Decimal, InvalidOperation
from typing import Optional

from .templates.engine import escape_markdown as _esc

_INVOICE_LABELS = {
    "en": {"invoice": "Invoice", "from": "From", "to": "Bill to", "date": "Issue date", "due": "Due date",
           "tax_id": "Tax number", "item": "Description", "qty": "Qty", "price": "Unit price", "amount": "Amount",
           "subtotal": "Subtotal", "discount": "Discount", "vat": "VAT", "total": "Total due", "words": "In words",
           "payment": "Payment", "notes": "Notes", "lines": "Invoice lines"},
    "ar": {"invoice": "فاتورة", "from": "من", "to": "إلى", "date": "تاريخ الإصدار", "due": "تاريخ الاستحقاق",
           "tax_id": "الرقم الضريبي", "item": "البيان", "qty": "الكمية", "price": "سعر الوحدة", "amount": "المبلغ",
           "subtotal": "المجموع الفرعي", "discount": "الخصم", "vat": "ضريبة القيمة المضافة",
           "total": "الإجمالي المستحق", "words": "المبلغ كتابةً", "payment": "طريقة الدفع", "notes": "ملاحظات",
           "lines": "بنود الفاتورة"},
}
# a quotation is an invoice that offers rather than bills
_QUOTE_LABELS = {
    "en": {**_INVOICE_LABELS["en"], "invoice": "Quotation", "to": "Prepared for", "due": "Valid until",
           "total": "Total", "payment": "Terms", "lines": "Quoted items"},
    "ar": {**_INVOICE_LABELS["ar"], "invoice": "عرض سعر", "to": "مقدم إلى", "due": "صالح حتى",
           "total": "الإجمالي", "payment": "الشروط", "lines": "بنود العرض"},
}

_INVOICE_EXAMPLE = {
    "language": "en",
    "number": "INV-2026-014",
    "date": "17 November 2026",
    "due": "17 December 2026",
    "currency": "SAR",
    "seller": {"name": "Nile Office Supplies", "address": "King Fahd Road, Riyadh 12271",
               "tax_id": "300123456700003", "email": "billing@example.com", "phone": "+966 11 000 0000"},
    "buyer": {"name": "Delta Engineering Co.", "address": "Olaya Street, Riyadh 12244",
              "tax_id": "300987654300003"},
    "items": [{"description": "A4 paper, box of 5 reams", "quantity": 3, "price": 12.5},
              {"description": "Toner cartridge, black", "quantity": 2, "price": 1310}],
    "tax_rate": 15,
    "payment": {"Bank": "Example Bank", "IBAN": "SA00 0000 0000 0000 0000 0000"},
    "notes": "Thank you for your business.",
}


def _need(data: dict, path: str):
    value = data
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    if value in (None, "", [], {}):
        raise ValueError(f"{path!r} is missing. Fix: add it; the kit's example shows every field")
    return value


def _number(value, where: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise ValueError(f"{where} is {value!r}, not a number. Fix: write it as 12.5") from None


def _money(x: Decimal) -> str:
    """Two decimals, or more when the figure has them: a unit price of 0.333 is not 0.33."""
    return f"{x:,.{max(2, -x.normalize().as_tuple().exponent)}f}"


def _party(title: str, p: dict, lab: dict) -> str:
    lines = [f"**{_esc(p['name'])}**"] + [_esc(p[k]) for k in ("address", "email", "phone") if p.get(k)]
    if p.get("tax_id"):
        lines.append(f"{lab['tax_id']}: {_esc(p['tax_id'])}")
    return f"### {title}\n\n" + "\\\n".join(lines) + "\n"


def _invoice(data: dict, kind: str = "invoice"):
    from .builder import DocumentBuilder
    from .core.words import CURRENCIES
    from .schema.blocks import TwoColumnBlock
    lang = (data.get("language") or "en").lower()
    if lang not in _INVOICE_LABELS:
        raise ValueError(f"language {lang!r} is not supported. Fix: use 'en' or 'ar'")
    lab = (_QUOTE_LABELS if kind == "quote" else _INVOICE_LABELS)[lang]
    number, seller, buyer = _need(data, "number"), _need(data, "seller"), _need(data, "buyer")
    _need(data, "seller.name"), _need(data, "buyer.name"), _need(data, "date")
    items = _need(data, "items")
    if not isinstance(items, list):
        raise ValueError(f"'items' must be a list of {{description, quantity, price}}")
    currency = str(data.get("currency") or "").upper()
    unit = f" ({currency})" if currency else ""

    rows = []
    for i, it in enumerate(items, start=2):
        where = f"items[{i - 2}]"
        desc = _need({"x": it}, "x.description") if isinstance(it, dict) else _need({}, where)
        qty = _number(it.get("quantity", 1), f"{where}.quantity")
        price = _number(_need({"x": it}, "x.price"), f"{where}.price")
        rows.append(f"| {_esc(desc)} | {qty.normalize():f} | {_money(price)} | =ROUND(B{i}*C{i}, 2) |")
    # rows count from 1 (the header) as in a spreadsheet; each figure below is a formula, rounded to
    # cents where it is computed, so the printed figures add up to the printed total
    sub = r = len(items) + 2
    rows.append(f"| {lab['subtotal']} | | | =SUM(D2:D{sub - 1}) |")
    net = f"D{sub}"
    discount = data.get("discount")
    if discount not in (None, "", 0):
        r += 1
        text = str(discount).strip()
        amount = _number(text.rstrip("%"), "discount")
        if amount < 0:
            raise ValueError(f"discount is {discount!r}. Fix: write it as a positive amount or percent, e.g. 150 or '10%'")
        rows.append(f"| {lab['discount']} | | {amount.normalize():f}% | =ROUND(-D{sub}*C{r}, 2) |" if text.endswith("%")
                    else f"| {lab['discount']} | | | -{_money(amount)} |")
        net = f"D{sub}+D{r}"
    parts = [net]
    rate = data.get("tax_rate")
    if rate not in (None, "", 0):
        r += 1
        rate = _number(rate, "tax_rate")
        rows.append(f"| {lab['vat']} | | {rate.normalize():f}% | =ROUND(({net})*C{r}, 2) |")
        parts.append(f"D{r}")
    total = r = r + 1
    rows.append(f"| {lab['total']} | | | ={'+'.join(parts)} |")
    words = f'=WORDS(D{total}, "{currency}")' if currency in CURRENCIES else f"=WORDS(D{total})"
    rows.append(f"| {lab['words']} | | | {words} |")

    details = [f"{lab['date']}: {_esc(data['date'])}"]
    if data.get("due"):
        details.append(f"{lab['due']}: {_esc(data['due'])}")
    title = json.dumps(f"{lab['invoice']} {number}", ensure_ascii=False)
    head = (f"---\ntitle: {title}\nlanguage: {lang}\ndocument_type: invoice\n---\n\n"
            f"# {lab['invoice']} {_esc(number)}\n\n" + "\n".join(details) + "\n")
    md = [f"| {lab['item']} | {lab['qty']} | {lab['price']}{unit} | {lab['amount']}{unit} |\n"
          "|---|---:|---:|---:|\n" + "\n".join(rows) + f"\n\nTable: {lab['lines']} {{#invoice}}\n"]
    if data.get("payment"):
        pay = data["payment"]
        pay = "\n".join(f"{_esc(k)}: {_esc(v)}" for k, v in pay.items()) if isinstance(pay, dict) else _esc(pay)
        md.append(f"## {lab['payment']}\n\n{pay}\n")
    if data.get("notes"):
        md.append(f"## {lab['notes']}\n\n{_esc(data['notes'])}\n")
    b = DocumentBuilder.from_markdown(head)
    # seller and buyer side by side, each written as Markdown so it reads like the rest
    sides = [DocumentBuilder.from_markdown(_party(lab[k], p, lab))._blocks for k, p in (("from", seller), ("to", buyer))]
    b._blocks += [TwoColumnBlock(left=sides[0], right=sides[1])] + DocumentBuilder.from_markdown("\n".join(md))._blocks
    return b


_QUOTE_EXAMPLE = {**copy.deepcopy(_INVOICE_EXAMPLE), "number": "Q-2026-031", "due": "17 December 2026",
                  "discount": "5%", "payment": {"Delivery": "Within 10 working days", "Payment": "30 days from invoice"},
                  "notes": "Prices include delivery within Riyadh."}

_LETTER_LABELS = {
    "en": {"ref": "Reference", "date": "Date", "subject": "Subject", "salutation": "Dear {name},",
           "closing": "Yours sincerely,", "cc": "cc", "enclosures": "Enclosures"},
    "ar": {"ref": "الرقم", "date": "التاريخ", "subject": "الموضوع", "salutation": "السيد/ {name} المحترم،",
           "closing": "وتفضلوا بقبول فائق الاحترام،", "cc": "نسخة إلى", "enclosures": "المرفقات"},
}

_LETTER_EXAMPLE = {
    "language": "en",
    "sender": {"name": "Nile Office Supplies", "address": "King Fahd Road, Riyadh 12271",
               "email": "info@example.com", "phone": "+966 11 000 0000"},
    "date": "17 November 2026",
    "reference": "NOS/2026/118",
    "recipient": {"name": "Ms Sara Ahmed", "title": "Procurement Manager", "organisation": "Delta Engineering Co.",
                  "address": "Olaya Street, Riyadh 12244"},
    "subject": "Renewal of the supply agreement",
    "body": "Thank you for the trust Delta Engineering has placed in us over the past year.\n\n"
            "Our supply agreement ends on 31 December 2026. We propose to renew it for a further year on the same "
            "terms, with the prices in the enclosed quotation.\n\n"
            "We would be glad to meet at your convenience to discuss any change you would like.",
    "signature": {"name": "Omar Hassan", "title": "Sales Director"},
    "enclosures": ["Quotation Q-2026-031"],
}


def _lines(*values) -> str:
    """Non-empty values, one per line, as one paragraph."""
    return "\\\n".join(_esc(v) for v in values if v)


def _letter(data: dict):
    from .builder import DocumentBuilder
    from .schema.blocks import SignatureBlock
    lang = (data.get("language") or "en").lower()
    if lang not in _LETTER_LABELS:
        raise ValueError(f"language {lang!r} is not supported. Fix: use 'en' or 'ar'")
    lab = _LETTER_LABELS[lang]
    to, body = _need(data, "recipient"), _need(data, "body")
    _need(data, "recipient.name"), _need(data, "date"), _need(data, "signature.name")
    sender, sign = data.get("sender") or {}, data["signature"]
    subject = data.get("subject")
    head = ["---", f"title: {json.dumps(subject or '', ensure_ascii=False)}", f"language: {lang}",
            "document_type: letter", f"author: {json.dumps(sender.get('name') or sign['name'], ensure_ascii=False)}",
            "---", ""]
    letterhead = [f"**{_esc(sender['name'])}**"] if sender.get("name") else []
    # with a logo the sender is the letterhead at the head of the page, not a block in the text
    md = [] if data.get("logo") else \
        ["\\\n".join(letterhead + [_esc(sender[k]) for k in ("address", "email", "phone") if sender.get(k)])]
    meta = [f"{lab['ref']}: {_esc(data['reference'])}" if data.get("reference") else "",
            f"{lab['date']}: {_esc(data['date'])}"]
    md.append("\n".join(x for x in meta if x))
    md.append(_lines(to["name"], to.get("title"), to.get("organisation"), to.get("address")))
    if subject:
        md.append(f"**{lab['subject']}: {_esc(subject)}**")
    md.append(_esc(data.get("salutation") or lab["salutation"].format(name=to["name"])))
    # the body is the author's own text: Markdown, as in any document
    md += body if isinstance(body, list) else [body]
    md.append(_esc(data.get("closing") or lab["closing"]))
    b = DocumentBuilder.from_markdown("\n".join(head) + "\n\n".join(x for x in md if x) + "\n")
    b._blocks.append(SignatureBlock(name=sign["name"], title=sign.get("title")))
    tail = []
    for key in ("enclosures", "cc"):
        if data.get(key):
            items = data[key] if isinstance(data[key], list) else [data[key]]
            tail.append(f"{lab[key]}: " + ", ".join(_esc(x) for x in items))
    if tail:
        b._blocks += DocumentBuilder.from_markdown("\n".join(tail) + "\n")._blocks
    return b


_CV_LABELS = {
    "en": {"summary": "Summary", "experience": "Experience", "education": "Education", "skills": "Skills",
           "languages": "Languages", "certifications": "Certifications", "comma": ", ",
           "span": "{start} – {end}", "since": "{start} – Present"},
    "ar": {"summary": "الملخص", "experience": "الخبرات", "education": "التعليم", "skills": "المهارات",
           "languages": "اللغات", "certifications": "الشهادات", "comma": "، ",
           "span": "من {start} إلى {end}", "since": "من {start} حتى الآن"},
}

_CV_EXAMPLE = {
    "language": "en",
    "name": "Layla Mansour",
    "headline": "Financial analyst",
    "contact": {"email": "layla@example.com", "phone": "+20 100 000 0000", "location": "Cairo, Egypt",
                "links": ["linkedin.com/in/example"]},
    "summary": "Financial analyst with six years in corporate planning and reporting. Builds the models, "
               "budgets and board reports that management decides on.",
    "experience": [
        {"role": "Senior financial analyst", "organisation": "Delta Engineering Co.", "location": "Cairo",
         "start": "2022", "end": None,
         "points": ["Built the five-year plan and the monthly board pack", "Cut the month-end close from 9 to 5 days"]},
        {"role": "Financial analyst", "organisation": "Nile Office Supplies", "location": "Alexandria",
         "start": "2019", "end": "2022", "points": ["Ran budgeting for 14 branches"]},
    ],
    "education": [{"degree": "BCom, Accounting", "institution": "Cairo University", "start": "2015", "end": "2019",
                   "note": "Graduated with distinction"}],
    "skills": {"Finance": ["Financial modelling", "Budgeting", "IFRS reporting"], "Tools": ["Excel", "Power BI", "SQL"]},
    "languages": ["Arabic (native)", "English (fluent)"],
    "certifications": ["CMA, 2023"],
}


def _cv(data: dict):
    from .builder import DocumentBuilder
    lang = (data.get("language") or "en").lower()
    if lang not in _CV_LABELS:
        raise ValueError(f"language {lang!r} is not supported. Fix: use 'en' or 'ar'")
    lab = _CV_LABELS[lang]
    name = _need(data, "name")
    contact = data.get("contact") or {}
    reach = [contact.get(k) for k in ("email", "phone", "location")] + list(contact.get("links") or [])
    md = ["---", f"title: {json.dumps(name, ensure_ascii=False)}", f"author: {json.dumps(name, ensure_ascii=False)}",
          f"language: {lang}", "document_type: general", "numbering: false", "---", "", f"# {_esc(name)}", ""]
    # the headline and the contact line are one paragraph, so they take the direction of the headline
    head = ([f"**{_esc(data['headline'])}**"] if data.get("headline") else []) + \
        ([" | ".join(_esc(x) for x in reach if x)] if any(reach) else [])
    if head:
        md += ["\\\n".join(head), ""]
    if data.get("summary"):
        md += [f"## {lab['summary']}", "", data["summary"], ""]      # the person's own words: Markdown

    def dated(e):
        start, end = _esc(e.get("start") or ""), _esc(e.get("end") or "")
        if start:
            return lab["span"].format(start=start, end=end) if end else lab["since"].format(start=start)
        return end

    for key, title, what, where in (("experience", "experience", "role", "organisation"),
                                    ("education", "education", "degree", "institution")):
        entries = data.get(key) or []
        if entries:
            md += [f"## {lab[title]}", ""]
        for i, e in enumerate(entries):
            if not isinstance(e, dict) or not e.get(what):
                raise ValueError(f"'{key}[{i}].{what}' is missing. Fix: add it; the kit's example shows every field")
            # the layout parsers expect: the title as a heading, then "organisation | location | dates"
            md += [f"### {_esc(e[what])}", ""]
            line = [_esc(e.get(where) or ""), _esc(e.get("location") or ""), dated(e)]
            if any(line):
                md += [" | ".join(x for x in line if x), ""]
            if e.get("note"):
                md += [_esc(e["note"]), ""]
            md += [f"- {p}" for p in e.get("points") or []] + [""]
    skills = data.get("skills")
    if skills:
        md += [f"## {lab['skills']}", ""]
        md += ([f"- **{_esc(k)}:** {lab['comma'].join(_esc(x) for x in v)}" for k, v in skills.items()]
               if isinstance(skills, dict) else [f"- {_esc(x)}" for x in skills]) + [""]
    for key in ("languages", "certifications"):
        if data.get(key):
            md += [f"## {lab[key]}", ""] + [f"- {_esc(x)}" for x in data[key]] + [""]
    b = DocumentBuilder.from_markdown("\n".join(md))
    return _for_ats(b, lang)


def _for_ats(b, lang: str):
    """What applicant tracking systems read well: no running header or footer (no name or page number
    repeated in the text), paragraphs set flush to the start edge and never hyphenated (a keyword split
    over two lines is lost), and a tagged PDF whose structure gives the reading order."""
    from .schema.blocks import RichTextBlock
    from .schema.page_system import PageSystem
    b._meta.page_system, b._meta.tagged = PageSystem(), True
    edge = "right" if lang == "ar" else "left"
    b._blocks = [RichTextBlock(text=x.text, alignment=edge) if x.type == "paragraph" else x for x in b._blocks]
    return b


_FEASIBILITY_LABELS = {
    "en": {"prepared": "Prepared by", "date": "Date", "summary": "Summary", "assumptions": "Assumptions",
           "rate": "Discount rate", "flows": "Cash flows", "year": "Year", "investment": "Investment",
           "revenue": "Revenue", "costs": "Operating costs", "net": "Net cash flow", "cumulative": "Cumulative",
           "total": "Total", "npv": "NPV at {rate}", "irr": "IRR",
           "results": "Results", "payback": "Payback period: {years} years.", "no_payback":
           "The investment is not recovered within the period studied.", "chart": "Net cash flow by year",
           "risks": "Risks", "conclusion": "Conclusion",
           "reading": "At a discount rate of {rate}, the net present value is {npv} and the internal rate of "
                      "return is {irr}."},
    "ar": {"prepared": "إعداد", "date": "التاريخ", "summary": "الملخص", "assumptions": "الافتراضات",
           "rate": "معدل الخصم", "flows": "التدفقات النقدية", "year": "السنة", "investment": "الاستثمار",
           "revenue": "الإيرادات", "costs": "تكاليف التشغيل", "net": "صافي التدفق النقدي", "cumulative": "التراكمي",
           "total": "الإجمالي", "npv": "صافي القيمة الحالية ({rate})", "irr": "معدل العائد الداخلي",
           "results": "النتائج", "payback": "فترة الاسترداد: {years} سنة.", "no_payback":
           "لا يُسترد الاستثمار خلال الفترة المدروسة.", "chart": "صافي التدفق النقدي حسب السنة",
           "risks": "المخاطر", "conclusion": "الخلاصة",
           "reading": "عند معدل خصم {rate} يبلغ صافي القيمة الحالية {npv}، ويبلغ معدل العائد الداخلي {irr}."},
}

_FEASIBILITY_EXAMPLE = {
    "language": "en",
    "title": "Feasibility study: a second production line",
    "prepared_by": "Finance department",
    "date": "November 2026",
    "currency": "EGP",
    "summary": "A second line would raise capacity by 40% to meet the orders the plant now turns away.",
    "discount_rate": "12%",
    "years": [{"year": "2026", "investment": 2500000},
              {"year": "2027", "revenue": 1800000, "costs": 950000},
              {"year": "2028", "revenue": 2600000, "costs": 1300000},
              {"year": "2029", "revenue": 3100000, "costs": 1500000},
              {"year": "2030", "revenue": 3300000, "costs": 1600000}],
    "assumptions": ["Prices rise with inflation; figures are in 2026 pounds",
                    "The line runs two shifts from the second year"],
    "risks": ["A delay in delivering the machines would move every inflow by a year"],
}


def _rate(value) -> Decimal:
    """12%, "12%", 12 or 0.12, as a fraction."""
    text = str(value).strip()
    r = _number(text.rstrip("%"), "discount_rate")
    return r / 100 if text.endswith("%") or r > 1 else r


def _feasibility(data: dict):
    from .builder import DocumentBuilder
    from .core.formulas import _npv
    from .schema.blocks import ChartBlock
    lang = (data.get("language") or "en").lower()
    if lang not in _FEASIBILITY_LABELS:
        raise ValueError(f"language {lang!r} is not supported. Fix: use 'en' or 'ar'")
    lab = _FEASIBILITY_LABELS[lang]
    title, years = _need(data, "title"), _need(data, "years")
    rate = _rate(_need(data, "discount_rate"))
    if not isinstance(years, list) or len(years) < 2:
        raise ValueError("'years' needs at least two years, the first with the investment. Fix: see the kit's example")
    unit = f" ({str(data['currency']).upper()})" if data.get("currency") else ""
    pct = f"{(rate * 100).normalize():f}%"

    rows, nets, figures = [], [], []
    for i, y in enumerate(years):
        r = i + 2
        if not isinstance(y, dict) or not y.get("year"):
            raise ValueError(f"'years[{i}].year' is missing. Fix: add it; the kit's example shows every field")
        inv, rev, cost = (_number(y.get(k) or 0, f"years[{i}].{k}") for k in ("investment", "revenue", "costs"))
        nets.append(rev - cost - inv)
        figures += [inv, rev, cost]
    # whole amounts are written whole: 2,500,000 rather than 2,500,000.00 down a column of millions
    places = max([-f.normalize().as_tuple().exponent for f in figures] + [0])
    places = max(places, 2) if places else 0

    def show(x):
        return f"{x:,.{places}f}"
    for i, (y, inv, rev, cost) in enumerate(zip(years, figures[0::3], figures[1::3], figures[2::3])):
        r = i + 2
        cumulative = f"=E{r}" if i == 0 else f"=F{r - 1}+E{r}"
        rows.append(f"| {_esc(y['year'])} | {show(inv)} | {show(rev)} | {show(cost)} | =C{r}-D{r}-B{r} | {cumulative} |")
    last = len(years) + 1
    rows.append(f"| {lab['total']} | =SUM(B2:B{last}) | =SUM(C2:C{last}) | =SUM(D2:D{last}) | =SUM(E2:E{last}) | |")
    npv_row, irr_row = last + 2, last + 3
    rows.append(f"| {lab['npv'].format(rate=pct)} | | | | =E2+NPV({pct}, E3:E{last}) | |")
    rows.append(f"| {lab['irr']} | | | | =IRR(E2:E{last}) | |")

    # payback: the year the cumulative flow turns positive, with the part of that year it takes
    cum, payback = Decimal(0), None
    for t, v in enumerate(nets):
        if cum < 0 <= cum + v and t > 0:
            payback = (t - 1) + (-cum / v)
            break
        cum += v
    head = ["---", f"title: {json.dumps(title, ensure_ascii=False)}", f"language: {lang}", "document_type: financial_report",
            "numbering: false"] + ([f"author: {json.dumps(data['prepared_by'], ensure_ascii=False)}"] if data.get("prepared_by") else []) + \
           ["---", "", f"# {_esc(title)}", ""]
    meta = [f"{lab['prepared']}: {_esc(data['prepared_by'])}" if data.get("prepared_by") else "",
            f"{lab['date']}: {_esc(data['date'])}" if data.get("date") else ""]
    md = head + ["\n".join(x for x in meta if x), ""]
    if data.get("summary"):
        md += [f"## {lab['summary']}", "", data["summary"], ""]
    md += [f"## {lab['assumptions']}", "", f"- {lab['rate']}: {pct}"] + [f"- {_esc(a)}" for a in data.get("assumptions") or []] + [""]
    md += [f"## {lab['flows']}", "",
           f"| {lab['year']} | {lab['investment']}{unit} | {lab['revenue']}{unit} | {lab['costs']}{unit} | "
           f"{lab['net']}{unit} | {lab['cumulative']}{unit} |", "|---|---:|---:|---:|---:|---:|"] + rows + \
          ["", f"Table: {lab['flows']} {{#flows}}", "", f"## {lab['results']}", "",
           lab["reading"].format(rate=pct, npv=f"{{=flows!E{npv_row}}}", irr=f"{{=flows!E{irr_row}}}") + " " +
           (lab["payback"].format(years=f"{payback:.1f}") if payback is not None else lab["no_payback"]), ""]
    for key in ("risks",):
        if data.get(key):
            md += [f"## {lab[key]}", ""] + [f"- {_esc(x)}" for x in data[key]] + [""]
    if data.get("conclusion"):
        md += [f"## {lab['conclusion']}", "", data["conclusion"], ""]
    b = DocumentBuilder.from_markdown("\n".join(md))
    # one series: one colour, with the years that cost money in a second
    chart = ChartBlock(chart_type="bar", title=lab["chart"] + unit,
                       data={str(y["year"]): float(v) for y, v in zip(years, nets)},
                       colors=["#B4413C" if v < 0 else "#1F4E79" for v in nets])
    at = next(i for i, x in enumerate(b._blocks) if x.type == "table") + 1
    b._blocks.insert(at, chart)
    return b


_STATEMENT_LABELS = {
    "en": {"title": "Financial statements", "amounts": "All amounts in {currency}", "item": "Item",
           "income": "Statement of profit or loss", "revenue_total": "Total revenue", "gross": "Gross profit",
           "operating": "Operating profit", "before_tax": "Profit before tax", "net": "Profit for the year",
           "position": "Statement of financial position", "assets": "Assets", "equity_liabilities": "Equity and liabilities",
           "non_current_assets": "Non-current assets", "current_assets": "Current assets",
           "total_non_current_assets": "Total non-current assets", "total_current_assets": "Total current assets",
           "total_assets": "Total assets", "equity": "Equity", "total_equity": "Total equity",
           "non_current_liabilities": "Non-current liabilities", "current_liabilities": "Current liabilities",
           "total_non_current_liabilities": "Total non-current liabilities",
           "total_current_liabilities": "Total current liabilities", "total_equity_liabilities": "Total equity and liabilities",
           "notes": "Notes"},
    "ar": {"title": "القوائم المالية", "amounts": "جميع المبالغ بـ {currency}", "item": "البند",
           "income": "قائمة الأرباح أو الخسائر", "revenue_total": "إجمالي الإيرادات", "gross": "مجمل الربح",
           "operating": "الربح التشغيلي", "before_tax": "الربح قبل الضريبة", "net": "صافي ربح السنة",
           "position": "قائمة المركز المالي", "assets": "الأصول", "equity_liabilities": "حقوق الملكية والالتزامات",
           "non_current_assets": "الأصول غير المتداولة", "current_assets": "الأصول المتداولة",
           "total_non_current_assets": "إجمالي الأصول غير المتداولة", "total_current_assets": "إجمالي الأصول المتداولة",
           "total_assets": "إجمالي الأصول", "equity": "حقوق الملكية", "total_equity": "إجمالي حقوق الملكية",
           "non_current_liabilities": "الالتزامات غير المتداولة", "current_liabilities": "الالتزامات المتداولة",
           "total_non_current_liabilities": "إجمالي الالتزامات غير المتداولة",
           "total_current_liabilities": "إجمالي الالتزامات المتداولة",
           "total_equity_liabilities": "إجمالي حقوق الملكية والالتزامات", "notes": "إيضاحات"},
}

_STATEMENTS_EXAMPLE = {
    "language": "en",
    "company": "Delta Engineering Co.",
    "period": "For the year ended 31 December 2026",
    "currency": "EGP",
    "periods": ["2026", "2025"],
    "income": {
        "revenue": [{"label": "Sales", "values": [10800000, 9400000]}],
        "cost_of_sales": [{"label": "Cost of sales", "values": [6200000, 5500000]}],
        "operating_expenses": [{"label": "Selling and distribution", "values": [950000, 870000]},
                               {"label": "General and administrative", "values": [1100000, 1020000]}],
        "other": [{"label": "Finance costs", "values": [-180000, -210000]}],
        "tax": [{"label": "Income tax", "values": [535500, 405000]}],
    },
    "position": {
        "non_current_assets": [{"label": "Property, plant and equipment", "values": [7400000, 6900000]}],
        "current_assets": [{"label": "Inventories", "values": [1600000, 1450000]},
                           {"label": "Trade receivables", "values": [2100000, 1900000]},
                           {"label": "Cash", "values": [1250000, 840000]}],
        "equity": [{"label": "Share capital", "values": [5000000, 5000000]},
                   {"label": "Retained earnings", "values": [3984500, 2150000]}],
        "non_current_liabilities": [{"label": "Long-term loans", "values": [1800000, 2200000]}],
        "current_liabilities": [{"label": "Trade payables", "values": [1565500, 1740000]}],
    },
    "notes": ["Prepared under International Financial Reporting Standards."],
}


def _statements(data: dict):
    from .builder import DocumentBuilder
    lang = (data.get("language") or "en").lower()
    if lang not in _STATEMENT_LABELS:
        raise ValueError(f"language {lang!r} is not supported. Fix: use 'en' or 'ar'")
    lab = _STATEMENT_LABELS[lang]
    company, periods = _need(data, "company"), data.get("periods") or [""]
    income, position = _need(data, "income"), _need(data, "position")
    cols = "BCDEFG"[:len(periods)]

    def lines(section: dict, key: str, sign: int = 1):
        """[(label, [values])] of one section; costs are entered as positive amounts and shown in brackets."""
        out = []
        for i, item in enumerate(section.get(key) or []):
            where = f"{key}[{i}]"
            if not isinstance(item, dict) or not item.get("label"):
                raise ValueError(f"'{where}.label' is missing. Fix: add it; the kit's example shows every field")
            values = item.get("values", [item.get("amount")])
            if not isinstance(values, list) or len(values) != len(periods):
                raise ValueError(f"'{where}.values' needs one amount for each of the periods {periods}")
            out.append((item["label"], [sign * _number(v, f"{where}.values") for v in values]))
        return out

    def show(v: Decimal) -> str:
        text = f"{abs(v):,.{2 if v != v.to_integral() else 0}f}"
        return f"({text})" if v < 0 else text

    class Table:
        def __init__(self):
            self.rows = []

        def head(self, label):
            self.rows.append(f"| **{_esc(label)}** |" + " |" * len(cols))

        def add(self, items):
            start = len(self.rows) + 2
            for label, values in items:
                self.rows.append(f"| {_esc(label)} | " + " | ".join(show(v) for v in values) + " |")
            return start, len(self.rows) + 1                    # the spreadsheet rows they took

        def formula(self, label, make):
            self.rows.append(f"| {label} | " + " | ".join("=" + make(c) for c in cols) + " |")
            return len(self.rows) + 1

        def markdown(self, title=None, anchor=None):
            head = f"| {lab['item']} | " + " | ".join(_esc(p) for p in periods) + " |"
            caption = ["", f"Table: {title} {{#{anchor}}}"] if title else []
            return [head, "|---|" + "---:|" * len(cols)] + self.rows + caption + [""]

    def total(items):
        return [sum((v[k] for _, v in items), Decimal(0)) for k in range(len(periods))]

    def summed(a, b):
        return (lambda c: f"SUM({c}{a}:{c}{b})") if b >= a else (lambda c: "0")

    # statement of profit or loss
    t = Table()
    rev = lines(income, "revenue")
    a, b = t.add(rev)
    r_rev = t.formula(lab["revenue_total"], summed(a, b))
    a, b = t.add(lines(income, "cost_of_sales", -1))
    r_gross = t.formula(f"**{lab['gross']}**", lambda c: f"{c}{r_rev}+" + summed(a, b)(c))
    a, b = t.add(lines(income, "operating_expenses", -1))
    r_op = t.formula(f"**{lab['operating']}**", lambda c: f"{c}{r_gross}+" + summed(a, b)(c))
    a, b = t.add(lines(income, "other"))
    r_pbt = t.formula(f"**{lab['before_tax']}**", lambda c: f"{c}{r_op}+" + summed(a, b)(c))
    a, b = t.add(lines(income, "tax", -1))
    t.formula(f"**{lab['net']}**", lambda c: f"{c}{r_pbt}+" + summed(a, b)(c))
    income_md = t.markdown()                                  # its heading already names it

    # statement of financial position: assets, then equity and liabilities, which must agree
    groups = {k: lines(position, k) for k in ("non_current_assets", "current_assets", "equity",
                                               "non_current_liabilities", "current_liabilities")}
    assets = [sum(x) for x in zip(total(groups["non_current_assets"]), total(groups["current_assets"]))]
    claims = [sum(x) for x in zip(*(total(groups[k]) for k in ("equity", "non_current_liabilities", "current_liabilities")))]
    for p, x, y in zip(periods, assets, claims):
        if x != y:
            raise ValueError(f"the statement of financial position does not balance{' in ' + str(p) if p else ''}: "
                             f"assets {x:,} but equity and liabilities {y:,} (a difference of {x - y:,}). "
                             "Fix: check the amounts; total assets must equal equity plus liabilities")
    t = Table()
    subtotal = []
    for key in ("non_current_assets", "current_assets"):
        t.head(lab[key])
        a, b = t.add(groups[key])
        subtotal.append(t.formula(lab["total_" + key], summed(a, b)))
    t.formula(f"**{lab['total_assets']}**", lambda c: "+".join(f"{c}{r}" for r in subtotal))
    assets_md = t.markdown(lab["assets"], "assets")
    t, subtotal = Table(), []
    for key in ("equity", "non_current_liabilities", "current_liabilities"):
        t.head(lab[key])
        a, b = t.add(groups[key])
        subtotal.append(t.formula(lab["total_" + key], summed(a, b)))
    t.formula(f"**{lab['total_equity_liabilities']}**", lambda c: "+".join(f"{c}{r}" for r in subtotal))
    claims_md = t.markdown(lab["equity_liabilities"], "equity-liabilities")

    title = data.get("title") or lab["title"]
    head = ["---", f"title: {json.dumps(company, ensure_ascii=False)}", f"subject: {json.dumps(title, ensure_ascii=False)}",
            f"language: {lang}", "document_type: financial_report", "numbering: false", "---", "", f"# {_esc(company)}", ""]
    sub = [_esc(title)] + ([_esc(data["period"])] if data.get("period") else []) + \
          ([lab["amounts"].format(currency=_esc(data["currency"]))] if data.get("currency") else [])
    md = head + ["\\\n".join(sub), "", f"## {lab['income']}", ""] + income_md + \
        [f"## {lab['position']}", ""] + assets_md + claims_md
    if data.get("notes"):
        md += [f"## {lab['notes']}", ""] + [f"{i}. {_esc(n)}" for i, n in enumerate(data["notes"], 1)] + [""]
    return DocumentBuilder.from_markdown("\n".join(md))


_CERTIFICATE_LABELS = {
    "en": {"title": "Certificate of Completion", "certify": "This is to certify that",
           "completed": "has successfully completed", "date": "Date", "number": "Certificate no."},
    "ar": {"title": "شهادة إتمام", "certify": "نشهد بأن",
           "completed": "قد أتمّ بنجاح", "completed_f": "قد أتمّت بنجاح", "date": "التاريخ", "number": "رقم الشهادة"},
}

_CERTIFICATE_EXAMPLE = {
    "language": "en",
    "organisation": "Nile Training Academy",
    "recipient": "Layla Mansour",
    "achievement": "Financial Modelling for Managers",
    "details": "24 hours of instruction, passed with distinction",
    "date": "17 November 2026",
    "number": "NTA-2026-0412",
    "signatures": [{"name": "Omar Hassan", "title": "Programme Director"},
                   {"name": "Sara Ahmed", "title": "Dean"}],
}


def _certificate(data: dict):
    """A landscape page set in the middle: the organisation, the title, the person, what they did,
    the date and number, and one or two signatures side by side."""
    from .builder import DocumentBuilder
    from .schema.blocks import RichTextBlock, SignatureBlock, SpacerBlock, TwoColumnBlock
    from .schema.enums import Orientation
    from .schema.page_system import PageSystem
    lang = (data.get("language") or "en").lower()
    if lang not in _CERTIFICATE_LABELS:
        raise ValueError(f"language {lang!r} is not supported. Fix: use 'en' or 'ar'")
    lab = _CERTIFICATE_LABELS[lang]
    who, what = _need(data, "recipient"), _need(data, "achievement")
    title = data.get("title") or lab["title"]
    completed = lab.get("completed_f") if lang == "ar" and str(data.get("gender", "")).lower() in ("f", "female", "أنثى") \
        else lab["completed"]

    def line(text, size=None, bold=False, color=None):
        return RichTextBlock(text=_esc(text), font_size=size, bold=bold, color=color, alignment="center")
    b = DocumentBuilder().meta(title=f"{title}: {who}", language=lang)
    b._meta.orientation, b._meta.page_system = Orientation.LANDSCAPE, PageSystem()
    b.document_type("general")
    blocks = [SpacerBlock(height=56)]
    if data.get("logo"):
        from .schema.blocks import ImageBlock
        blocks = [SpacerBlock(height=24), ImageBlock(src=data["logo"], height=52, alignment="center",
                                                     alt_text=data.get("organisation") or "Logo"), SpacerBlock(height=10)]
    if data.get("organisation"):
        blocks.append(line(data["organisation"], 13, True))
    blocks += [SpacerBlock(height=14), line(title, 32, True, "#1F3A5F"), SpacerBlock(height=22),
               line(lab["certify"], 12), SpacerBlock(height=6), line(who, 28, True), SpacerBlock(height=6),
               line(completed, 12), SpacerBlock(height=4), line(what, 17, True)]
    if data.get("details"):
        blocks.append(line(data["details"], 11))
    facts = [f"{lab['date']}: {data['date']}" if data.get("date") else "",
             f"{lab['number']}: {data['number']}" if data.get("number") else ""]
    if any(facts):
        blocks += [SpacerBlock(height=10), line(" | ".join(x for x in facts if x), 10, color="#555555")]
    signs = [SignatureBlock(name=x["name"], title=x.get("title"), line_width=220)
             for x in (data.get("signatures") or []) if isinstance(x, dict) and x.get("name")]
    if signs:
        blocks.append(SpacerBlock(height=28))
        blocks.append(TwoColumnBlock(left=[signs[0]], right=signs[1:2]) if len(signs) > 1 else signs[0])
    b._blocks = blocks
    return b


KITS = {"invoice": (_invoice, _INVOICE_EXAMPLE),
        "quote": (lambda d: _invoice(d, "quote"), _QUOTE_EXAMPLE),
        "letter": (_letter, _LETTER_EXAMPLE),
        "cv": (_cv, _CV_EXAMPLE),
        "feasibility": (_feasibility, _FEASIBILITY_EXAMPLE),
        "statements": (_statements, _STATEMENTS_EXAMPLE),
        "certificate": (_certificate, _CERTIFICATE_EXAMPLE)}


def kits() -> list:
    """The names of the ready-made documents."""
    return sorted(KITS)


def kit_example(name: str) -> dict:
    """Example data for a kit: a starting point to change."""
    return copy.deepcopy(_find(name)[1])


def kit(name: str, data: dict, theme: Optional[str] = None):
    """A ``DocumentBuilder`` holding the whole document for ``data``; export it as usual.
    Missing or malformed data raises ``ValueError`` naming the field and the fix."""
    if not isinstance(data, dict):
        raise ValueError(f"{name}: the data must be an object (a dict); kit_example({name!r}) shows one")
    try:
        b = _find(name)[0](data)
    except ValueError as e:
        raise ValueError(f"{name}: {e}") from None
    if data.get("logo") and name in _LOGO_HEADER:       # the brand at the head of every page
        party = data.get("seller") or data.get("sender") or {}
        values = {"company": party.get("name") or data.get("company") or data.get("prepared_by"),
                  **{k: party.get(k) for k in ("address", "website", "email", "phone")}}
        b.page_system(_LOGO_HEADER[name], logo=data["logo"], **{k: str(v) for k, v in values.items() if v})
    if theme:
        b.theme(theme)
    return b


# which header carries a kit's logo; a CV keeps none (applicant tracking systems), a certificate sets it on the page
_LOGO_HEADER = {"invoice": "modern", "quote": "modern", "letter": "letterhead", "feasibility": "report",
                "statements": "report"}


def _find(name: str):
    if name not in KITS:
        raise ValueError(f"no kit {name!r}; kits: {', '.join(kits())}")
    return KITS[name]
