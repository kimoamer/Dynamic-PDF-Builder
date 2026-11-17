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
    md = ["\\\n".join(letterhead + [_esc(sender[k]) for k in ("address", "email", "phone") if sender.get(k)])]
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


KITS = {"invoice": (_invoice, _INVOICE_EXAMPLE),
        "quote": (lambda d: _invoice(d, "quote"), _QUOTE_EXAMPLE),
        "letter": (_letter, _LETTER_EXAMPLE),
        "cv": (_cv, _CV_EXAMPLE)}


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
    if theme:
        b.theme(theme)
    return b


def _find(name: str):
    if name not in KITS:
        raise ValueError(f"no kit {name!r}; kits: {', '.join(kits())}")
    return KITS[name]
