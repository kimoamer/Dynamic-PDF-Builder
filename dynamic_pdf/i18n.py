"""Localized fixed labels (only strings the engine itself generates)."""

LABELS = {
    "en": {"toc": "Table of Contents", "prepared_by": "Prepared by", "references": "References",
           "abstract": "Abstract", "keywords": "Keywords", "continued": "continued"},
    "ar": {"toc": "جدول المحتويات", "prepared_by": "إعداد", "references": "المراجع",
           "abstract": "الملخص", "keywords": "الكلمات المفتاحية", "continued": "تابع"},
}


def label(key: str, language: str = "en") -> str:
    lang = (language or "en").split("-")[0].lower()
    return LABELS.get(lang, LABELS["en"]).get(key, LABELS["en"][key])
