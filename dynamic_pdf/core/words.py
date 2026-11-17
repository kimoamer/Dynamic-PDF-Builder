"""
An amount in words, in Arabic (تفقيط) or English, as invoices, cheques and receipts write it.

    amount_in_words(1250.5, "ar", "SAR")  ->  "فقط ألف ومئتان وخمسون ريالاً وخمسون هللةً لا غير"
    amount_in_words(1250.5, "en", "SAR")  ->  "One thousand two hundred fifty riyals and fifty halalas only"

Arabic counts its noun by the rules invoices follow: one and two take the noun alone or dual,
three to ten the plural, eleven to ninety-nine the accusative singular, and round hundreds and
thousands the genitive singular; a feminine noun (هللة, بيسة) takes feminine numbers. Amounts
are rounded half away from zero to the currency's minor unit.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Tuple

# ── Arabic ─────────────────────────────────────────────────────────────────────────────

_ONES_M = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة"]
_ONES_F = ["", "واحدة", "اثنتان", "ثلاث", "أربع", "خمس", "ست", "سبع", "ثماني", "تسع", "عشر"]
_TENS_AR = {2: "عشرون", 3: "ثلاثون", 4: "أربعون", 5: "خمسون", 6: "ستون", 7: "سبعون", 8: "ثمانون", 9: "تسعون"}
_HUNDREDS = ["", "مائة", "مئتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]
# singular, dual, plural, accusative singular
_SCALES_AR = [(10 ** 9, ("مليار", "ملياران", "مليارات", "ملياراً")),
              (10 ** 6, ("مليون", "مليونان", "ملايين", "مليوناً")),
              (10 ** 3, ("ألف", "ألفان", "آلاف", "ألفاً"))]

# code: (major forms, major feminine, minor forms, minor feminine, minor units)
_CURRENCY_AR = {
    "SAR": (("ريال", "ريالان", "ريالات", "ريالاً"), False, ("هللة", "هللتان", "هللات", "هللةً"), True, 100),
    "QAR": (("ريال", "ريالان", "ريالات", "ريالاً"), False, ("درهم", "درهمان", "دراهم", "درهماً"), False, 100),
    "OMR": (("ريال", "ريالان", "ريالات", "ريالاً"), False, ("بيسة", "بيستان", "بيسات", "بيسةً"), True, 1000),
    "EGP": (("جنيه", "جنيهان", "جنيهات", "جنيهاً"), False, ("قرش", "قرشان", "قروش", "قرشاً"), False, 100),
    "AED": (("درهم", "درهمان", "دراهم", "درهماً"), False, ("فلس", "فلسان", "فلوس", "فلساً"), False, 100),
    "KWD": (("دينار", "ديناران", "دنانير", "ديناراً"), False, ("فلس", "فلسان", "فلوس", "فلساً"), False, 1000),
    "BHD": (("دينار", "ديناران", "دنانير", "ديناراً"), False, ("فلس", "فلسان", "فلوس", "فلساً"), False, 1000),
    "JOD": (("دينار", "ديناران", "دنانير", "ديناراً"), False, ("فلس", "فلسان", "فلوس", "فلساً"), False, 1000),
    "USD": (("دولار", "دولاران", "دولارات", "دولاراً"), False, ("سنت", "سنتان", "سنتات", "سنتاً"), False, 100),
    "EUR": (("يورو", "يورو", "يورو", "يورو"), False, ("سنت", "سنتان", "سنتات", "سنتاً"), False, 100),
}


def _below_100_ar(n: int, fem: bool) -> str:
    ones = _ONES_F if fem else _ONES_M
    if n <= 10:
        return ones[n]
    if n == 11:
        return "إحدى عشرة" if fem else "أحد عشر"
    if n == 12:
        return "اثنتا عشرة" if fem else "اثنا عشر"
    if n < 20:
        return f"{ones[n - 10]} {'عشرة' if fem else 'عشر'}"
    tens, unit = divmod(n, 10)
    if not unit:
        return _TENS_AR[tens]
    first = ("إحدى" if fem else "واحد") if unit == 1 else ones[unit]
    return f"{first} و{_TENS_AR[tens]}"


def _below_1000_ar(n: int, fem: bool = False, construct: bool = False) -> str:
    """``construct``: a noun follows a round two hundred, which then reads مئتا."""
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append("مئتا" if hundreds == 2 and construct and not rest else _HUNDREDS[hundreds])
    if rest:
        parts.append(_below_100_ar(rest, fem))
    return " و".join(parts)


def _counted_ar(n: int, forms: Tuple[str, str, str, str], fem: bool = False, joined: bool = False) -> str:
    """``n`` of a counted noun: ألف، ألفان، ثلاثة آلاف، أحد عشر ألفاً، مائة ألف. ``joined``: another
    noun follows it directly (ألفا ريال، أحد عشر ألف ريال), so it is in construct."""
    one, two, plural, acc = forms
    if n == 1:
        return one
    if n == 2:
        return two[:-1] if joined else two
    rest = n % 100
    if rest == 1 and n > 100:
        return f"{_below_1000_ar(n - 1, fem, construct=True)} و{one}" if n < 1000 else f"{number_ar(n - 1, fem)} و{one}"
    if rest == 2 and n > 100:
        return f"{_below_1000_ar(n - 2, fem, construct=True)} و{two}" if n < 1000 else f"{number_ar(n - 2, fem)} و{two}"
    words = number_ar(n, fem, construct=True)
    if 3 <= rest <= 10:
        return f"{words} {plural}"
    if 11 <= rest <= 99:
        return f"{words} {one if joined else acc}"
    return f"{words} {one}"


def number_ar(n: int, fem: bool = False, construct: bool = False) -> str:
    """A whole number in Arabic words; ``fem`` when what it counts is feminine."""
    if n == 0:
        return "صفر"
    parts = []
    for size, forms in _SCALES_AR:
        count, n = divmod(n, size)
        if count:
            parts.append(_counted_ar(count, forms, joined=construct and not n))
    if n:
        parts.append(_below_1000_ar(n, fem, construct))
    return " و".join(parts)


def _money_ar(n: int, forms, fem: bool) -> str:
    one, two, plural, acc = forms
    if n == 1:
        return f"{one} {'واحدة' if fem else 'واحد'}"
    if n == 2:
        return two
    rest = n % 100
    words = number_ar(n, fem, construct=rest == 0)
    if 3 <= rest <= 10:
        return f"{words} {plural}"
    if 11 <= rest <= 99:
        return f"{words} {acc}"
    return f"{words} {one}"


# ── English ────────────────────────────────────────────────────────────────────────────

_ONES_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
            "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS_EN = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES_EN = [(10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand")]
_CURRENCY_EN = {
    "SAR": (("riyal", "riyals"), ("halala", "halalas"), 100), "QAR": (("riyal", "riyals"), ("dirham", "dirhams"), 100),
    "OMR": (("rial", "rials"), ("baisa", "baisa"), 1000), "EGP": (("pound", "pounds"), ("piaster", "piasters"), 100),
    "AED": (("dirham", "dirhams"), ("fils", "fils"), 100), "KWD": (("dinar", "dinars"), ("fils", "fils"), 1000),
    "BHD": (("dinar", "dinars"), ("fils", "fils"), 1000), "JOD": (("dinar", "dinars"), ("fils", "fils"), 1000),
    "USD": (("dollar", "dollars"), ("cent", "cents"), 100), "EUR": (("euro", "euros"), ("cent", "cents"), 100),
    "GBP": (("pound", "pounds"), ("penny", "pence"), 100),
}


def number_en(n: int) -> str:
    if n < 20:
        return _ONES_EN[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _TENS_EN[tens] + (f"-{_ONES_EN[unit]}" if unit else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES_EN[hundreds]} hundred" + (f" {number_en(rest)}" if rest else "")
    parts = []
    for size, name in _SCALES_EN:
        count, n = divmod(n, size)
        if count:
            parts.append(f"{number_en(count)} {name}")
    if n:
        parts.append(number_en(n))
    return " ".join(parts)


# ── amounts ────────────────────────────────────────────────────────────────────────────

CURRENCIES = sorted(set(_CURRENCY_AR) | set(_CURRENCY_EN))


def amount_in_words(value, language: str = "ar", currency: Optional[str] = None) -> str:
    """``value`` (a number or a Decimal) in words. With a ``currency`` code it is read as money:
    major and minor units, framed as invoices frame it (فقط ... لا غير / ... only)."""
    lang = (language or "ar").split("-")[0].lower()
    code = (currency or "").strip().upper() or None
    table = _CURRENCY_AR if lang == "ar" else _CURRENCY_EN
    if code and code not in table:
        raise ValueError(f"no words for currency {currency!r}; known: {', '.join(sorted(table))}")
    amount = Decimal(str(value))
    negative = amount < 0
    amount = abs(amount)
    if code:
        units = table[code][-1]
        minor_places = len(str(units)) - 1
        amount = amount.quantize(Decimal(1).scaleb(-minor_places), rounding=ROUND_HALF_UP)
        major, minor = int(amount), int((amount - int(amount)) * units)
        if lang == "ar":
            forms, fem, sub_forms, sub_fem, _ = table[code]
            text = "صفر " + forms[0] if not major and not minor else _money_ar(major, forms, fem) if major else ""
            if minor:
                text = (text + " و" if text else "") + _money_ar(minor, sub_forms, sub_fem)
            return f"فقط {'سالب ' if negative else ''}{text} لا غير"
        (one, many), (sub_one, sub_many), _ = table[code]
        parts = [f"{number_en(major)} {one if major == 1 else many}"] if major or not minor else []
        if minor:
            parts.append(f"{number_en(minor)} {sub_one if minor == 1 else sub_many}")
        text = ("minus " if negative else "") + " and ".join(parts) + " only"
        return text[0].upper() + text[1:]
    whole = int(amount)
    frac = format(amount, "f").split(".")[1].rstrip("0") if "." in format(amount, "f") else ""
    if lang == "ar":
        text = number_ar(whole) + (f" فاصلة {number_ar(int(frac))}" if frac else "")
        return ("سالب " if negative else "") + text
    text = number_en(whole) + (" point " + " ".join(_ONES_EN[int(d)] for d in frac) if frac else "")
    text = ("minus " if negative else "") + text
    return text[0].upper() + text[1:]
