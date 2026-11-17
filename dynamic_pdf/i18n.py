"""Localized fixed labels (only strings the engine itself generates)."""

LABELS = {
    "en": {"toc": "Table of Contents", "prepared_by": "Prepared by", "references": "References",
           "abstract": "Abstract", "keywords": "Keywords", "continued": "continued",
           "figure": "Figure", "source": "Source", "table": "Table", "section": "Section",
           "lof": "List of Figures", "lot": "List of Tables", "equation": "Equation"},
    "ar": {"toc": "جدول المحتويات", "prepared_by": "إعداد", "references": "المراجع",
           "abstract": "الملخص", "keywords": "الكلمات المفتاحية", "continued": "تابع",
           "figure": "شكل", "source": "المصدر", "table": "جدول", "section": "القسم",
           "lof": "قائمة الأشكال", "lot": "قائمة الجداول", "equation": "المعادلة"},
}


def label(key: str, language: str = "en") -> str:
    lang = (language or "en").split("-")[0].lower()
    return LABELS.get(lang, LABELS["en"]).get(key, LABELS["en"][key])


_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def written_number(number: str, text: str) -> str:
    """A generated number (a heading's, a list item's) in Arabic-Indic digits when it numbers
    right-to-left ``text`` in a document that writes its own figures that way; else as given."""
    from . import policy as _policy
    from .core.normalize import is_rtl_text
    col = _policy._current.get()
    if getattr(col, "digits", "western") == "arabic" and is_rtl_text(text):
        return number.translate(_INDIC)
    return number


def digit_style(doc) -> str:
    """``"arabic"`` when the document writes its figures in Arabic-Indic digits more than in
    Western ones, else ``"western"``. Generated figures (chart labels) follow it."""
    from .core.normalize import block_text
    arabic = western = 0
    for b in doc.blocks:
        for s in block_text(b):
            arabic += sum("\u0660" <= c <= "\u0669" or "\u06f0" <= c <= "\u06f9" for c in s)
            western += sum("0" <= c <= "9" for c in s)
    return "arabic" if arabic > western else "western"
