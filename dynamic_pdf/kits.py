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
from decimal import Decimal, InvalidOperation
from typing import Optional

from .templates.engine import escape_markdown as _esc

_INVOICE_LABELS = {
    "en": {"invoice": "Invoice", "from": "From", "to": "Bill to", "date": "Issue date", "due": "Due date", "tax_id": "Tax number", "item": "Description",
           "qty": "Qty", "price": "Unit price", "amount": "Amount", "subtotal": "Subtotal",
           "vat": "VAT", "total": "Total due", "words": "In words", "payment": "Payment",
           "notes": "Notes", "lines": "Invoice lines"},
    "ar": {"invoice": "فاتورة", "from": "من", "to": "إلى", "date": "تاريخ الإصدار", "due": "تاريخ الاستحقاق", "tax_id": "الرقم الضريبي", "item": "البيان",
           "qty": "الكمية", "price": "سعر الوحدة", "amount": "المبلغ", "subtotal": "المجموع الفرعي",
           "vat": "ضريبة القيمة المضافة", "total": "الإجمالي المستحق", "words": "المبلغ كتابةً",
           "payment": "طريقة الدفع", "notes": "ملاحظات", "lines": "بنود الفاتورة"},
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
        raise ValueError(f"invoice: {path!r} is missing. Fix: add it; kit_example('invoice') shows every field")
    return value


def _number(value, where: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise ValueError(f"invoice: {where} is {value!r}, not a number. Fix: write it as 12.5") from None


def _money(x: Decimal) -> str:
    return f"{x:,.2f}"


def _party(title: str, p: dict, lab: dict) -> str:
    lines = [f"**{_esc(p['name'])}**"] + [_esc(p[k]) for k in ("address", "email", "phone") if p.get(k)]
    if p.get("tax_id"):
        lines.append(f"{lab['tax_id']}: {_esc(p['tax_id'])}")
    return f"### {title}\n\n" + "\\\n".join(lines) + "\n"


def _invoice(data: dict):
    from .builder import DocumentBuilder
    from .core.words import CURRENCIES
    from .schema.blocks import TwoColumnBlock
    lang = (data.get("language") or "en").lower()
    if lang not in _INVOICE_LABELS:
        raise ValueError(f"invoice: language {lang!r} is not supported. Fix: use 'en' or 'ar'")
    lab = _INVOICE_LABELS[lang]
    number, seller, buyer = _need(data, "number"), _need(data, "seller"), _need(data, "buyer")
    _need(data, "seller.name"), _need(data, "buyer.name"), _need(data, "date")
    items = _need(data, "items")
    if not isinstance(items, list):
        raise ValueError("invoice: 'items' must be a list of {description, quantity, price}")
    currency = str(data.get("currency") or "").upper()
    unit = f" ({currency})" if currency else ""

    rows = []
    for i, it in enumerate(items, start=2):
        where = f"items[{i - 2}]"
        desc = _need({"x": it}, "x.description") if isinstance(it, dict) else _need({}, where)
        qty = _number(it.get("quantity", 1), f"{where}.quantity")
        price = _number(_need({"x": it}, "x.price"), f"{where}.price")
        rows.append(f"| {_esc(desc)} | {qty.normalize():f} | {_money(price)} | =B{i}*C{i} |")
    last = len(items) + 1
    sub, vat, total = last + 1, last + 2, last + 3
    rows.append(f"| {lab['subtotal']} | | | =SUM(D2:D{last}) |")
    rate = data.get("tax_rate")
    if rate not in (None, "", 0):
        rate = _number(rate, "tax_rate")
        rows.append(f"| {lab['vat']} | | {rate.normalize():f}% | =D{sub}*C{vat} |")
        rows.append(f"| {lab['total']} | | | =D{sub}+D{vat} |")
    else:
        total = sub + 1
        rows.append(f"| {lab['total']} | | | =D{sub} |")
    words = f'=WORDS(D{total}, "{currency}")' if currency in CURRENCIES else f"=WORDS(D{total})"
    rows.append(f"| {lab['words']} | | | {words} |")

    details = [f"{lab['date']}: {_esc(data['date'])}"]
    if data.get("due"):
        details.append(f"{lab['due']}: {_esc(data['due'])}")
    head = (f"---\ntitle: {lab['invoice']} {number}\nlanguage: {lang}\ndocument_type: invoice\n---\n\n"
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


KITS = {"invoice": (_invoice, _INVOICE_EXAMPLE)}


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
    b = _find(name)[0](data)
    if theme:
        b.theme(theme)
    return b


def _find(name: str):
    if name not in KITS:
        raise ValueError(f"no kit {name!r}; kits: {', '.join(kits())}")
    return KITS[name]
