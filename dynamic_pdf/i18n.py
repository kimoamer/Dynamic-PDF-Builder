"""Localized fixed labels (only strings the engine itself generates)."""

LABELS = {
    "en": {"toc": "Table of Contents", "prepared_by": "Prepared by", "references": "References",
           "abstract": "Abstract", "keywords": "Keywords", "continued": "continued",
           "figure": "Figure", "source": "Source", "table": "Table", "section": "Section",
           "lof": "List of Figures", "lot": "List of Tables"},
    "ar": {"toc": "جدول المحتويات", "prepared_by": "إعداد", "references": "المراجع",
           "abstract": "الملخص", "keywords": "الكلمات المفتاحية", "continued": "تابع",
           "figure": "شكل", "source": "المصدر", "table": "جدول", "section": "القسم",
           "lof": "قائمة الأشكال", "lot": "قائمة الجداول"},
}


def label(key: str, language: str = "en") -> str:
    lang = (language or "en").split("-")[0].lower()
    return LABELS.get(lang, LABELS["en"]).get(key, LABELS["en"][key])
