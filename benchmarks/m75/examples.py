"""Fictional content for the M7.5 archetype examples. Every name, figure and place here is invented."""
from __future__ import annotations

from dynamic_pdf import DocumentBuilder

FLOW_EN = [
    "The harbour authority moved its last diesel tug to shore power in March, two years ahead of the plan "
    "agreed with the port council. The change cut idle running at the outer berths and gave the engineering "
    "team its first full year of clean metering data.",
    "Most of the saving came from a simple rule: no vessel holds its engines on standby once a berth is "
    "confirmed. The rule took six weeks to agree and has since been adopted by all four pilot crews.",
]
FLOW_AR = [
    "نَقَلَت هيئةُ الميناء آخرَ قاطرةٍ تعمل بالديزل إلى الطاقة الساحلية في شهر مارس، قبل الموعد المتفق عليه بعامين. "
    "وقد خفَّض هذا التغييرُ التشغيلَ الخامل في الأرصفة الخارجية، ومنح فريقَ الهندسة أوَّلَ عامٍ كاملٍ من بيانات القياس الدقيقة.",
    "جاء معظمُ الوفر من قاعدةٍ بسيطة: لا تُبقي أيُّ سفينةٍ محركاتها في وضع الاستعداد بعد تأكيد الرصيف. "
    "واستغرق الاتفاق على القاعدة ستة أسابيع، ثم اعتمدتها أطقمُ الإرشاد الأربعة.",
]
CHAPTERS_EN = ["The year in review", "Operations", "People and safety", "Financial review", "Outlook"]
CHAPTERS_AR = ["مراجعة العام", "العمليات", "الأفراد والسلامة", "المراجعة المالية", "النظرة المستقبلية"]


def _base(title, rtl=False, recipe=None):
    b = DocumentBuilder()
    b.meta(title=title, language="ar" if rtl else "en", author="Saltmere Harbour Authority (fictional)")
    if recipe:
        b.design(recipe=recipe, recipe_gate="preview")
    else:
        b.design()
    return b


def opener_en():
    b = _base("Saltmere Harbour Authority: Annual Review", recipe="editorial_executive")
    b.section_opener(
        "Operations: a quieter, cleaner harbour", label="02", chapters=CHAPTERS_EN, current=1,
        standfirst="Shore power reached every working berth this year, and the outer harbour recorded its "
                   "lowest idle running since metering began.",
        points=["All four pilot crews now follow one standby rule",
                "Berth changes fell by a fifth after the new booking window",
                "Dredging moved to the winter tide tables"])
    b.heading("Shore power at the outer berths", level=2)
    for t in FLOW_EN:
        b.paragraph(t)
    return b


def opener_ar():
    b = _base("هيئة ميناء سالتمير: التقرير السنوي", rtl=True, recipe="arabic_bilingual")
    b.section_opener(
        "العمليات: ميناءٌ أهدأ وأنظف", label="٠٢", chapters=CHAPTERS_AR, current=1,
        standfirst="وصلت الطاقةُ الساحلية إلى كلِّ رصيفٍ عامل هذا العام، وسجَّل الميناءُ الخارجيُّ أدنى تشغيلٍ خاملٍ منذ بدء القياس.",
        points=["تتبع أطقمُ الإرشاد الأربعة قاعدةَ استعدادٍ واحدة",
                "انخفضت تغييراتُ الأرصفة بمقدار الخُمس بعد نافذة الحجز الجديدة",
                "انتقلت أعمالُ التجريف إلى جداول مدِّ الشتاء"])
    b.heading("الطاقة الساحلية في الأرصفة الخارجية", level=2)
    for t in FLOW_AR:
        b.paragraph(t)
    return b


def performance_en():
    b = _base("Saltmere Harbour Authority: Results", recipe="editorial_executive")
    years = ["2023", "2024", "2025", "2026"]
    b.performance_page(
        "Twelve months at the harbour", eyebrow="Performance 2026",
        standfirst="Tonnage grew for the third year while energy per vessel call fell, the first time both "
                   "have moved the right way together.",
        hero={"value": "18.4m", "label": "tonnes handled", "delta": "+7.2% on 2025",
              "note": "Container and bulk cargo at all berths"},
        tiles=[{"value": "96.1%", "label": "On-time berthing", "delta": "+2.3 pts"},
               {"value": "1,284", "label": "Vessel calls", "delta": "+61"},
               {"value": "0.21", "label": "Injury rate per million hours", "delta": "−0.13"},
               {"value": "41%", "label": "Shore power share of energy", "delta": "+9 pts"}],
        trends=[{"label": "Revenue (£m)", "periods": years, "values": [112, 121, 133, 148]},
                {"label": "Operating margin (%)", "periods": years, "values": [18.2, 19.4, 21.0, 23.6]},
                {"label": "Net cash (£m)", "periods": years, "values": [-14, -6, 3, 11]}],
        highlights=["The outer breakwater repair finished under budget",
                    "The apprenticeship intake doubled to 38",
                    "Night pilotage restarted on the north channel",
                    "A second ferry slip opened in September"])
    b.heading("What changed", level=2)
    for t in FLOW_EN:
        b.paragraph(t)
    return b


def performance_ar():
    b = _base("هيئة ميناء سالتمير: النتائج", rtl=True, recipe="arabic_bilingual")
    years = ["٢٠٢٣", "٢٠٢٤", "٢٠٢٥", "٢٠٢٦"]
    b.performance_page(
        "اثنا عشر شهرًا في الميناء", eyebrow="الأداء ٢٠٢٦",
        standfirst="نمت الحمولةُ للعام الثالث على التوالي بينما انخفضت الطاقةُ لكلِّ زيارةِ سفينة، وهي المرَّةُ الأولى التي يتحسَّن فيها المؤشران معًا.",
        hero={"value": "١٨٫٤ مليون", "label": "طنٍّ جرت مناولته", "delta": "+٧٫٢٪ مقارنةً بعام ٢٠٢٥",
              "note": "الحاويات والبضائع السائبة في جميع الأرصفة"},
        tiles=[{"value": "٩٦٫١٪", "label": "الرسوُّ في الموعد", "delta": "+٢٫٣ نقطة"},
               {"value": "١٬٢٨٤", "label": "زيارات السفن", "delta": "+٦١"},
               {"value": "٠٫٢١", "label": "معدل الإصابات لكل مليون ساعة", "delta": "−٠٫١٣"},
               {"value": "٤١٪", "label": "حصة الطاقة الساحلية", "delta": "+٩ نقاط"}],
        trends=[{"label": "الإيرادات (مليون)", "periods": years, "values": [112, 121, 133, 148],
                 "display": ["١١٢", "١٢١", "١٣٣", "١٤٨"]},
                {"label": "هامش التشغيل (٪)", "periods": years, "values": [18.2, 19.4, 21.0, 23.6],
                 "display": ["١٨٫٢", "١٩٫٤", "٢١٫٠", "٢٣٫٦"]},
                {"label": "صافي النقد (مليون)", "periods": years, "values": [-14, -6, 3, 11],
                 "display": ["−١٤", "−٦", "٣", "١١"]}],
        highlights=["اكتمل إصلاحُ حاجز الأمواج الخارجي بأقلَّ من الميزانية",
                    "تضاعف عددُ المتدربين الجدد إلى ٣٨",
                    "استؤنف الإرشادُ الليلي في القناة الشمالية",
                    "افتُتح مرسى ثانٍ للعبَّارات في سبتمبر"])
    b.heading("ما الذي تغيَّر", level=2)
    for t in FLOW_AR:
        b.paragraph(t)
    return b


_LEDGER = [
    {"title": "Income", "title_alt": "الدخل", "rows": [
        {"label": "Port dues", "label_alt": "رسوم الميناء", "values": ["84,210", "76,940", "71,305"]},
        {"label": "Pilotage", "label_alt": "الإرشاد البحري", "values": ["31,482", "28,116", "26,870"]},
        {"label": "Property rents", "label_alt": "إيجارات العقارات", "values": ["19,730", "18,404", "17,992"]},
        {"label": "Other income", "label_alt": "إيرادات أخرى", "values": ["12,578", "9,540", "5,833"]},
        {"label": "Total income", "label_alt": "إجمالي الدخل", "values": ["148,000", "133,000", "122,000"],
         "total": True}]},
    {"title": "Expenditure", "title_alt": "المصروفات", "rows": [
        {"label": "Staff costs", "label_alt": "تكاليف الموظفين", "values": ["(52,300)", "(49,870)", "(47,215)"]},
        {"label": "Energy and fuel", "label_alt": "الطاقة والوقود", "values": ["(14,120)", "(16,440)", "(17,900)"]},
        {"label": "Maintenance and dredging", "label_alt": "الصيانة والتجريف",
         "values": ["(27,950)", "(25,330)", "(24,105)"]},
        {"label": "Depreciation", "label_alt": "الإهلاك", "values": ["(18,700)", "(17,960)", "(16,780)"]},
        {"label": "Total expenditure", "label_alt": "إجمالي المصروفات",
         "values": ["(113,070)", "(109,600)", "(106,000)"], "total": True}],
     "note": "Figures in £000. Brackets show costs. All amounts are fictional."},
    {"title": "Financial position", "title_alt": "المركز المالي", "rows": [
        {"label": "Non-current assets", "label_alt": "الأصول غير المتداولة",
         "values": ["402,650", "388,120", "371,940"]},
        {"label": "Cash and deposits", "label_alt": "النقد والودائع", "values": ["38,410", "27,060", "19,380"]},
        {"label": "Borrowings", "label_alt": "القروض", "values": ["(27,400)", "(24,060)", "(33,380)"]},
        {"label": "Net assets", "label_alt": "صافي الأصول", "values": ["413,660", "391,120", "357,940"],
         "total": True}]},
]


def ledger_bilingual():
    b = _base("Saltmere Harbour Authority: Summary Accounts", recipe="arabic_bilingual")
    b.heading("Summary accounts | ملخص الحسابات", level=1)
    b.paragraph("The figures below are stated once and labelled in both languages.")
    b.paragraph("تُذكر الأرقام أدناه مرَّةً واحدة، وتُعنون باللغتين.")
    b.parallel_ledger(["2026", "2025", "2024"], _LEDGER, label_header="£000", label_header_alt="بالألف جنيه")
    return b


def ledger_en():
    b = _base("Saltmere Harbour Authority: Summary Accounts", recipe="editorial_executive")
    sections = [{"title": s["title"], "note": s.get("note"),
                 "rows": [{k: v for k, v in r.items() if k != "label_alt"} for r in s["rows"]]} for s in _LEDGER]
    b.heading("Summary accounts", level=1)
    b.paragraph("Three years of figures, with the current year carried by tone and size rather than a legend.")
    b.parallel_ledger(["2026", "2025", "2024"], sections, label_header="£000")
    return b


def ledger_ar():
    b = _base("هيئة ميناء سالتمير: ملخص الحسابات", rtl=True, recipe="arabic_bilingual")
    digits = str.maketrans("0123456789,", "٠١٢٣٤٥٦٧٨٩٬")
    sections = [{"title": s["title_alt"], "rows": [
        {"label": r["label_alt"], "values": [v.translate(digits) for v in r["values"]],
         "total": r.get("total", False)} for r in s["rows"]]} for s in _LEDGER]
    b.heading("ملخص الحسابات", level=1)
    b.paragraph("ثلاثةُ أعوامٍ من الأرقام، ويظهر العامُ الحالي بالدرجة اللونية والحجم بدلًا من مفتاحٍ للرموز.")
    b.parallel_ledger(["٢٠٢٦", "٢٠٢٥", "٢٠٢٤"], sections, label_header="بالألف جنيه")
    return b


EXAMPLES = {
    "opener_en": ("asymmetric_opener", opener_en),
    "opener_ar": ("asymmetric_opener", opener_ar),
    "performance_en": ("performance_page", performance_en),
    "performance_ar": ("performance_page", performance_ar),
    "ledger_en": ("parallel_ledger", ledger_en),
    "ledger_ar": ("parallel_ledger", ledger_ar),
    "ledger_bilingual": ("parallel_ledger", ledger_bilingual),
}
