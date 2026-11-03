"""
M7 benchmark corpus — realistic, non-confidential documents.

All organisations, people and figures are fictional. Prose is hand-written
for this corpus; long documents combine that prose with deterministic
tabular data (seeded) so every run renders identical inputs.

``CORPUS[name] = (category, size, factory)`` where ``factory()`` returns a
fresh ``DocumentBuilder``. ``size`` is "small" (1–2 pages), "medium"
(3–12) or "long" (20+).
"""
from __future__ import annotations

import random
from typing import Callable, Dict, Tuple

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.schema.blocks import ChartBlock


def _md(text: str, charts: Dict[str, dict] = None) -> DocumentBuilder:
    """Markdown → builder; a paragraph ``[[chart:key]]`` becomes that chart."""
    b = DocumentBuilder.from_markdown(text)
    if charts:
        out = []
        for blk in b._blocks:
            t = getattr(blk, "text", None)
            if blk.type == "paragraph" and isinstance(t, str) and t.strip().startswith("[[chart:"):
                out.append(ChartBlock(**charts[t.strip()[8:-2]]))
            else:
                out.append(blk)
        b._blocks = out
    return b


def _money(x: float) -> str:
    return f"({abs(x):,.0f})" if x < 0 else f"{x:,.0f}"


# ════════════════════════════ Arabic ════════════════════════════

AR_REGIONS = ["الرياض", "جدة", "مكة المكرمة", "الدمام", "المدينة المنورة", "القصيم", "أبها", "جازان", "تبوك"]

AR_CHAPTERS = [
    ("كلمة رئيس مجلس الإدارة", [
        "يسرني أن أقدم لكم التقرير السنوي لشركة وادي النور للمرافق عن عام ٢٠٢٥، وهو عام شهد توسعاً ملموساً "
        "في شبكات المياه والصرف الصحي، وارتفاعاً في رضا المشتركين، وتحسناً واضحاً في الكفاءة التشغيلية.",
        "لقد واصلنا تنفيذ استراتيجيتنا الخمسية التي تركز على ثلاثة محاور رئيسية: استدامة الموارد المائية، "
        "وتحويل الخدمات رقمياً، وتطوير الكفاءات الوطنية. وقد انعكس ذلك على نتائجنا المالية التي تجاوزت "
        "المستهدفات المعتمدة من مجلس الإدارة.",
        "وأود أن أشكر زملائي أعضاء المجلس والإدارة التنفيذية وجميع منسوبي الشركة على جهودهم، كما أشكر "
        "مساهمينا على ثقتهم المستمرة، ونتطلع إلى عام جديد من النمو المسؤول.",
    ]),
    ("الاستراتيجية والتوجهات", [
        "تهدف استراتيجية الشركة حتى عام ٢٠٣٠ إلى خفض الفاقد المائي إلى أقل من ١٢٪، ورفع نسبة إعادة استخدام "
        "المياه المعالجة إلى ٦٠٪، وتقديم جميع الخدمات الرئيسية عبر القنوات الرقمية.",
        "وقد اعتمد مجلس الإدارة خلال العام خطة استثمارية بقيمة ٢٫٤ مليار ريال تغطي إنشاء ثلاث محطات معالجة "
        "جديدة، وتحديث ما يزيد على ألف كيلومتر من الشبكات القديمة، وتركيب العدادات الذكية في المدن الرئيسية.",
        "كما أطلقت الشركة برنامجاً للشراكة مع القطاع الخاص في مجالي التشغيل والصيانة، بهدف تحسين جودة "
        "الخدمة وخفض تكلفة التشغيل للمتر المكعب الواحد.",
    ]),
    ("الأداء التشغيلي", [
        "ارتفع إجمالي كميات المياه الموزعة بنسبة ٤٫٨٪ مقارنة بالعام السابق، في حين انخفض الفاقد المائي من "
        "١٧٫٣٪ إلى ١٥٫١٪ نتيجة برامج الكشف المبكر عن التسربات واستبدال الشبكات المتهالكة.",
        "وبلغ متوسط زمن الاستجابة لبلاغات الأعطال الطارئة ثلاث ساعات وعشرين دقيقة، وهو أفضل أداء تسجله "
        "الشركة منذ تأسيسها، كما تجاوزت نسبة الالتزام بمؤشرات مستوى الخدمة ٩٤٪.",
        "ويوضح الجدول التالي أبرز المؤشرات التشغيلية حسب المنطقة خلال العام:",
    ]),
    ("الأداء المالي", [
        "حققت الشركة إيرادات بلغت ٦٫٨ مليار ريال بنمو قدره ٩٫٢٪، وارتفع صافي الربح إلى ٩١٢ مليون ريال، "
        "مدفوعاً بزيادة أعداد المشتركين وتحسن كفاءة التحصيل وانخفاض تكاليف الطاقة.",
        "وبلغت النفقات الرأسمالية ١٫٩ مليار ريال وُجّه معظمها إلى مشاريع الشبكات ومحطات المعالجة، مع "
        "المحافظة على نسبة مديونية منخفضة لا تتجاوز ٠٫٤ مرة من حقوق الملكية.",
        "وتعرض الجداول التالية ملخص الإيرادات حسب القطاع والمنطقة، مع المقارنة بالعام السابق:",
    ]),
    ("الموارد البشرية", [
        "بلغ عدد موظفي الشركة في نهاية العام ٤٬٢١٠ موظفاً، وارتفعت نسبة التوطين إلى ٨٧٪، فيما شكّلت المرأة "
        "٢١٪ من إجمالي القوى العاملة، بزيادة ثلاث نقاط مئوية عن العام السابق.",
        "ونفذت الشركة أكثر من ١٨٠ ألف ساعة تدريبية شملت برامج القيادة والسلامة المهنية والتحول الرقمي، "
        "كما أطلقت أكاديمية وادي النور للمهارات الفنية بالتعاون مع الكليات التقنية.",
    ]),
    ("الاستدامة والبيئة", [
        "عالجت الشركة خلال العام ٤١٢ مليون متر مكعب من مياه الصرف الصحي، وأُعيد استخدام ٤٨٪ منها في "
        "الري الزراعي والاستخدامات الصناعية وتشجير المدن.",
        "وانخفضت انبعاثات الكربون لكل متر مكعب منتج بنسبة ١١٪ بعد تشغيل ألواح الطاقة الشمسية في محطتي "
        "الضخ الرئيسيتين، واستبدال المضخات القديمة بأخرى عالية الكفاءة.",
    ]),
    ("الحوكمة وإدارة المخاطر", [
        "يتكون مجلس الإدارة من تسعة أعضاء، منهم خمسة أعضاء مستقلون، وتنبثق عنه لجان المراجعة والمكافآت "
        "والمخاطر والاستثمار، وقد عقد المجلس ثمانية اجتماعات خلال العام.",
        "وحدّثت الشركة سجل المخاطر المؤسسية الذي يضم أربعاً وثلاثين مخاطرة رئيسية، أبرزها شح الموارد "
        "المائية، وتقلب أسعار الطاقة، والهجمات السيبرانية على أنظمة التحكم الصناعي.",
        "ويلخص الجدول التالي أبرز المخاطر وإجراءات التخفيف المعتمدة:",
    ]),
]


def ar_annual_report() -> DocumentBuilder:
    rnd = random.Random(2025)
    b = (DocumentBuilder().meta(title="التقرير السنوي ٢٠٢٥ — شركة وادي النور للمرافق",
                                author="إدارة الاتصال المؤسسي", language="ar").direction("rtl"))
    b.cover_page("التقرير السنوي ٢٠٢٥", subtitle="شركة وادي النور للمرافق (شركة افتراضية)",
                 author="إدارة الاتصال المؤسسي", date="مارس ٢٠٢٦")
    b.table_of_contents(depth=2)
    for ci, (title, paras) in enumerate(AR_CHAPTERS):
        b.heading(title, level=1)
        for p in paras:
            b.paragraph(p)
        if ci == 0:
            b.metric_row([{"label": "الإيرادات", "value": "٦٫٨ مليار", "delta": "+٩٫٢٪"},
                          {"label": "صافي الربح", "value": "٩١٢ مليون", "delta": "+١٢٪"},
                          {"label": "المشتركون", "value": "٢٫١ مليون", "delta": "+٥٪"}])
        if ci == 1:
            b.heading("المبادرات الاستراتيجية", level=2)
            b.numbered_list(["خفض الفاقد المائي عبر العدادات الذكية وأنظمة رصد الضغط",
                             "التوسع في إعادة استخدام المياه المعالجة للأغراض الزراعية والصناعية",
                             "رقمنة رحلة المشترك من طلب الخدمة حتى السداد",
                             "تطوير الكفاءات الوطنية في التشغيل والصيانة"])
        if ci == 2:
            rows = [[r, f"{rnd.randint(180, 620)}", f"{rnd.uniform(11, 19):.1f}٪",
                     f"{rnd.uniform(2.5, 4.5):.1f} ساعة", f"{rnd.uniform(88, 98):.1f}٪"] for r in AR_REGIONS]
            b.table(["المنطقة", "المياه الموزعة (مليون م³)", "الفاقد", "زمن الاستجابة", "رضا المشتركين"],
                    rows, caption="جدول ١: المؤشرات التشغيلية حسب المنطقة")
            for q in ("الربع الأول", "الربع الثاني", "الربع الثالث", "الربع الرابع"):
                b.heading(f"أداء {q}", level=2)
                b.paragraph(f"شهد {q} استقراراً في الإمدادات رغم ارتفاع درجات الحرارة، ونفذت فرق الصيانة "
                            f"{rnd.randint(900, 1600)} عملية إصلاح وقائي، وتم استبدال {rnd.randint(40, 95)} "
                            "كيلومتراً من الشبكات، مع الالتزام الكامل بمعايير السلامة المهنية.")
                b.bullet_list([f"عدد البلاغات المغلقة: {rnd.randint(12000, 26000):,}",
                               f"نسبة الإغلاق خلال المدة المحددة: {rnd.uniform(90, 98):.1f}٪",
                               f"التوصيلات الجديدة: {rnd.randint(4000, 9000):,}"])
        if ci == 3:
            segs = ["المياه السكنية", "المياه التجارية", "الصرف الصحي", "المياه المعالجة", "خدمات أخرى"]
            rows, tot0, tot1 = [], 0, 0
            for s in segs:
                a, c = rnd.randint(300, 2400), rnd.randint(300, 2600)
                tot0, tot1 = tot0 + a, tot1 + c
                rows.append([s, f"{a:,}", f"{c:,}", f"{(c - a) / a * 100:+.1f}٪"])
            b.table(["القطاع", "٢٠٢٤ (مليون ريال)", "٢٠٢٥ (مليون ريال)", "التغير"], rows,
                    caption="جدول ٢: الإيرادات حسب القطاع", footer_row=["الإجمالي", f"{tot0:,}", f"{tot1:,}",
                                                                      f"{(tot1 - tot0) / tot0 * 100:+.1f}٪"])
            b.chart("bar", data={r: rnd.randint(500, 1700) for r in AR_REGIONS},
                    title="الإيرادات حسب المنطقة (مليون ريال)", height=3.2)
            months = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر",
                      "أكتوبر", "نوفمبر", "ديسمبر"]
            b.paragraph("ويبين الجدول التالي التدفقات النقدية الشهرية من الأنشطة التشغيلية:")
            b.table(["الشهر", "المتحصلات", "المدفوعات", "صافي التدفق"],
                    [[m, f"{(a := rnd.randint(420, 640)):,}", f"{(c := rnd.randint(330, 560)):,}", _money(a - c)]
                     for m in months], caption="جدول ٣: التدفقات النقدية التشغيلية (مليون ريال)")
        if ci == 4:
            b.table(["الفئة", "العدد", "نسبة التوطين", "ساعات التدريب"],
                    [["الإدارة العليا", "64", "92٪", "3,200"], ["المهندسون", "1,180", "84٪", "61,400"],
                     ["الفنيون", "2,140", "88٪", "92,800"], ["الإداريون", "826", "91٪", "24,100"]],
                    caption="جدول ٤: توزيع القوى العاملة")
        if ci == 6:
            risks = [("شح الموارد المائية", "مرتفع", "تنويع المصادر وزيادة إعادة الاستخدام"),
                     ("تقلب أسعار الطاقة", "متوسط", "عقود طويلة الأجل والطاقة الشمسية"),
                     ("الهجمات السيبرانية", "مرتفع", "مركز عمليات أمنية على مدار الساعة"),
                     ("تأخر المشاريع", "متوسط", "مكتب لإدارة المشاريع ومؤشرات أداء أسبوعية"),
                     ("تقادم الأصول", "متوسط", "خطة استبدال مبنية على تقييم الحالة")]
            b.table(["المخاطرة", "الدرجة", "إجراءات التخفيف"], [list(r) for r in risks],
                    caption="جدول ٥: أبرز المخاطر المؤسسية")
    b.heading("الأداء حسب المنطقة", level=1)
    b.paragraph("يستعرض هذا الفصل أداء كل منطقة تشغيلية على حدة، بما في ذلك كميات المياه الموزعة ونسب "
                "الفاقد ومؤشرات رضا المشتركين، مع أبرز المشاريع المنفذة خلال العام.")
    months = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر",
              "أكتوبر", "نوفمبر", "ديسمبر"]
    for r in AR_REGIONS:
        b.heading(f"منطقة {r}", level=2)
        b.paragraph(f"واصلت منطقة {r} تنفيذ برنامج استبدال الشبكات، وبلغ عدد المشتركين فيها "
                    f"{rnd.randint(180, 520):,} ألف مشترك. وانخفض الفاقد المائي بمقدار "
                    f"{rnd.uniform(0.8, 3.1):.1f} نقطة مئوية بعد تركيب {rnd.randint(20, 90)} ألف عداد ذكي، "
                    "كما جرى تحديث مركز التحكم الإقليمي وربطه بمنصة المراقبة المركزية.")
        b.paragraph("ويعرض الجدول التالي المؤشرات الشهرية للمنطقة خلال العام:")
        b.table(["الشهر", "المياه الموزعة (ألف م³)", "الفاقد", "البلاغات", "رضا المشتركين"],
                [[m, f"{rnd.randint(9000, 26000):,}", f"{rnd.uniform(11, 19):.1f}٪", f"{rnd.randint(800, 2600):,}",
                  f"{rnd.uniform(86, 97):.1f}٪"] for m in months], caption=f"المؤشرات الشهرية — منطقة {r}")
        b.heading(f"أبرز مشاريع منطقة {r}", level=3)
        b.paragraph(f"ركزت مشاريع منطقة {r} على رفع موثوقية الإمداد في الأحياء الجديدة وتقليل الانقطاعات "
                    "المخططة، مع التنسيق مع البلديات لتقليل أثر أعمال الحفر على حركة المرور والسكان.")
        b.bullet_list([f"استبدال {rnd.randint(30, 120)} كيلومتراً من خطوط التوزيع القديمة",
                       f"إنشاء خزان أرضي بسعة {rnd.randint(20, 80)} ألف متر مكعب",
                       f"ربط {rnd.randint(8, 30)} ألف منزل بشبكة الصرف الصحي",
                       "تشغيل نظام لرصد الضغط والتسربات على مدار الساعة"])
        b.table(["المشروع", "القيمة (مليون ريال)", "تاريخ البدء", "الإنجاز"],
                [[f"مشروع {r} {k + 1}", f"{rnd.randint(15, 240)}", f"{rnd.randint(2022, 2025)}",
                  f"{rnd.randint(15, 100)}٪"] for k in range(6)], caption=f"مشاريع منطقة {r}")
    b.heading("خدمة المشتركين والتحول الرقمي", level=1)
    for t in ["تجاوز عدد مستخدمي التطبيق الإلكتروني مليون مستخدم نشط شهرياً، وأصبحت ٨٢٪ من طلبات الخدمة "
              "تُقدّم رقمياً دون الحاجة إلى زيارة مراكز الخدمة.",
              "وأطلقت الشركة خدمة الإشعارات الاستباقية التي تبلغ المشتركين بالانقطاعات المخططة قبل ثمان وأربعين "
              "ساعة، مما أسهم في خفض البلاغات المتكررة بنسبة ٢٧٪.",
              "كما جرى توحيد مراكز الاتصال في مركز وطني واحد يعمل على مدار الساعة، وارتفعت نسبة حل الطلبات "
              "من الاتصال الأول إلى ٧٨٪."]:
        b.paragraph(t)
    b.table(["القناة", "عدد الطلبات (ألف)", "متوسط زمن الإنجاز", "رضا المشتركين"],
            [[c, f"{rnd.randint(40, 900):,}", f"{rnd.uniform(0.5, 6):.1f} يوم", f"{rnd.uniform(80, 96):.1f}٪"]
             for c in ["التطبيق الإلكتروني", "الموقع الإلكتروني", "مركز الاتصال", "مراكز الخدمة",
                       "الرسائل النصية", "وسائل التواصل الاجتماعي"]], caption="طلبات الخدمة حسب القناة")
    b.heading("الجودة والامتثال", level=1)
    for t in ["حافظت الشركة على شهادات أنظمة الإدارة للجودة والبيئة والسلامة المهنية وأمن المعلومات، واجتازت "
              "عمليات التدقيق الخارجية دون ملاحظات جوهرية.",
              "وبلغت نسبة مطابقة عينات المياه للمواصفات القياسية الوطنية ٩٩٫٨٪ من أصل أكثر من مئة وعشرين ألف عينة "
              "جرى تحليلها في المختبرات المعتمدة خلال العام."]:
        b.paragraph(t)
    b.table(["المعيار", "عدد العينات", "نسبة المطابقة", "الحد المسموح"],
            [[p, f"{rnd.randint(4000, 16000):,}", f"{rnd.uniform(99.2, 100):.1f}٪", lim] for p, lim in
             [("العكارة", "٥ وحدات"), ("الكلور المتبقي", "٠٫٢–٠٫٥ ملغم/لتر"), ("الأس الهيدروجيني", "٦٫٥–٨٫٥"),
              ("الأملاح الذائبة", "١٠٠٠ ملغم/لتر"), ("النترات", "٥٠ ملغم/لتر"), ("الفلوريد", "١٫٥ ملغم/لتر"),
              ("البكتيريا القولونية", "صفر"), ("الرصاص", "٠٫٠١ ملغم/لتر"), ("الحديد", "٠٫٣ ملغم/لتر"),
              ("الكبريتات", "٢٥٠ ملغم/لتر")]], caption="نتائج فحوصات جودة المياه")
    b.heading("سجل المشاريع الرأسمالية", level=1)
    b.paragraph("يتضمن السجل التالي المشاريع الرأسمالية الجارية التي تتجاوز قيمتها عشرين مليون ريال، "
                "ونسبة الإنجاز الفعلية مقارنة بالمخطط في نهاية العام.")
    kinds = ["محطة معالجة", "خط نقل رئيسي", "خزان استراتيجي", "شبكة توزيع", "محطة ضخ"]
    b.table(["المشروع", "المنطقة", "القيمة (مليون ريال)", "الإنجاز الفعلي", "الإنجاز المخطط"],
            [[f"{rnd.choice(kinds)} {i + 1}", rnd.choice(AR_REGIONS), f"{rnd.randint(20, 640):,}",
              f"{(a := rnd.randint(10, 100))}٪", f"{min(100, a + rnd.randint(-8, 12))}٪"] for i in range(64)],
            caption="جدول ٧: المشاريع الرأسمالية الجارية")
    b.heading("القوائم المالية الموحدة المختصرة", level=1)
    b.paragraph("تُعرض القوائم التالية بملايين الريالات ما لم يُذكر خلاف ذلك، وقد راجعها مراجع الحسابات "
                "الخارجي وأصدر بشأنها رأياً غير معدل.")
    items = ["النقد وما في حكمه", "الذمم المدينة", "المخزون", "الممتلكات والمعدات", "أصول حق الاستخدام",
             "الأصول غير الملموسة", "إجمالي الأصول", "الذمم الدائنة", "القروض قصيرة الأجل",
             "القروض طويلة الأجل", "مخصص نهاية الخدمة", "إجمالي المطلوبات", "رأس المال",
             "الاحتياطي النظامي", "الأرباح المبقاة", "إجمالي حقوق الملكية"]
    b.table(["البند", "٢٠٢٥", "٢٠٢٤"], [[i, f"{rnd.randint(200, 9000):,}", f"{rnd.randint(200, 9000):,}"]
                                       for i in items], caption="جدول ٦: قائمة المركز المالي الموحدة")
    for n, (h, t) in enumerate([("السياسات المحاسبية", "أُعدت القوائم المالية وفقاً للمعايير الدولية للتقرير "
                                 "المالي المعتمدة في المملكة، وعلى أساس التكلفة التاريخية باستثناء الأدوات "
                                 "المالية المقاسة بالقيمة العادلة."),
                                ("الأحكام والتقديرات", "تتطلب القوائم المالية استخدام تقديرات تؤثر في المبالغ "
                                 "المعروضة، وأهمها الأعمار الإنتاجية للأصول ومخصص الخسائر الائتمانية المتوقعة."),
                                ("الأحداث اللاحقة", "لا توجد أحداث لاحقة جوهرية بعد تاريخ القوائم المالية "
                                 "تستوجب التعديل أو الإفصاح.")], 1):
        b.heading(f"إيضاح {n}: {h}", level=2)
        b.paragraph(t)
    return b


def ar_financial_statements() -> DocumentBuilder:
    b = (DocumentBuilder().meta(title="القوائم المالية الأولية — الربع الثالث ٢٠٢٥", author="الإدارة المالية",
                                language="ar").direction("rtl"))
    b.heading("القوائم المالية الأولية الموجزة للفترة المنتهية في ٣٠ سبتمبر ٢٠٢٥", level=1)
    b.paragraph("شركة الأفق للتجزئة (شركة افتراضية) — شركة مساهمة. جميع المبالغ بآلاف الريالات السعودية.")
    b.heading("قائمة الدخل", level=2)
    rows = [["المبيعات", "1,284,310", "1,176,902", "3,702,118", "3,412,560"],
            ["تكلفة المبيعات", "(902,114)", "(839,447)", "(2,611,903)", "(2,437,018)"],
            ["مجمل الربح", "382,196", "337,455", "1,090,215", "975,542"],
            ["مصاريف بيع وتسويق", "(141,870)", "(128,312)", "(409,220)", "(377,904)"],
            ["مصاريف عمومية وإدارية", "(62,418)", "(59,903)", "(181,664)", "(173,128)"],
            ["الربح التشغيلي", "177,908", "149,240", "499,331", "424,510"],
            ["تكاليف التمويل", "(18,204)", "(16,880)", "(53,912)", "(49,301)"],
            ["الزكاة", "(4,442)", "(3,309)", "(11,135)", "(9,380)"],
            ["صافي ربح الفترة", "155,262", "129,051", "434,284", "365,829"]]
    b.table(["البند", "الربع الثالث ٢٠٢٥", "الربع الثالث ٢٠٢٤", "تسعة أشهر ٢٠٢٥", "تسعة أشهر ٢٠٢٤"], rows,
            caption="قائمة الدخل الأولية الموجزة")
    b.heading("قائمة المركز المالي", level=2)
    rows = [["الأصول المتداولة", "", ""], ["النقد وما في حكمه", "214,880", "176,402"],
            ["المخزون", "688,190", "612,774"], ["ذمم مدينة ودفعات مقدمة", "93,412", "88,019"],
            ["الأصول غير المتداولة", "", ""], ["ممتلكات ومعدات", "1,402,336", "1,358,120"],
            ["أصول حق الاستخدام", "918,774", "944,501"], ["إجمالي الأصول", "3,317,592", "3,179,816"],
            ["المطلوبات", "", ""], ["ذمم دائنة", "702,118", "655,930"], ["التزامات إيجار", "961,402", "988,117"],
            ["قروض", "410,000", "450,000"], ["إجمالي المطلوبات", "2,073,520", "2,094,047"],
            ["حقوق الملكية", "1,244,072", "1,085,769"]]
    b.table(["البند", "٣٠ سبتمبر ٢٠٢٥", "٣١ ديسمبر ٢٠٢٤"], rows, caption="قائمة المركز المالي الأولية")
    b.heading("قائمة التدفقات النقدية", level=2)
    b.table(["البند", "تسعة أشهر ٢٠٢٥", "تسعة أشهر ٢٠٢٤"],
            [["صافي النقد من الأنشطة التشغيلية", "512,904", "471,330"],
             ["صافي النقد المستخدم في الأنشطة الاستثمارية", "(198,416)", "(233,870)"],
             ["صافي النقد المستخدم في الأنشطة التمويلية", "(276,010)", "(214,552)"],
             ["صافي التغير في النقد", "38,478", "22,908"]], caption="قائمة التدفقات النقدية الأولية")
    b.heading("إيضاحات مختارة", level=2)
    for t in ["١. أُعدت هذه القوائم وفقاً لمعيار المحاسبة الدولي رقم ٣٤ «التقرير المالي الأولي».",
              "٢. لا تتضمن القوائم الأولية جميع الإفصاحات المطلوبة في القوائم السنوية، ويجب قراءتها مع "
              "القوائم المالية السنوية للعام المنتهي في ٣١ ديسمبر ٢٠٢٤.",
              "٣. افتتحت الشركة خلال الفترة أحد عشر متجراً جديداً، ليصل إجمالي المتاجر إلى ١٤٢ متجراً.",
              "٤. وافقت الجمعية العامة على توزيع أرباح نقدية بواقع ١٫٢ ريال للسهم عن النصف الأول."]:
        b.paragraph(t)
    return b


def ar_memo() -> DocumentBuilder:
    return _md("""---
title: تعميم داخلي — تحديث سياسة العمل المرن
language: ar
direction: rtl
---
# تعميم داخلي رقم ١٤/٢٠٢٥

**إلى:** جميع منسوبي الشركة
**من:** إدارة الموارد البشرية
**التاريخ:** ٢ نوفمبر ٢٠٢٥

يسر إدارة الموارد البشرية إبلاغكم بتحديث سياسة العمل المرن اعتباراً من الأول من ديسمبر ٢٠٢٥، وذلك بعد
تقييم التجربة التي استمرت ستة أشهر وأظهرت تحسناً في الإنتاجية ورضا الموظفين.

## أبرز التعديلات

- يحق للموظف العمل عن بُعد يومين في الأسبوع بعد موافقة المدير المباشر.
- تبدأ ساعات الحضور المرنة من السابعة صباحاً وحتى العاشرة صباحاً.
- تُستثنى الوظائف الميدانية ووظائف خدمة العملاء المباشرة من العمل عن بُعد.

## الإجراءات المطلوبة

1. تقديم طلب العمل المرن عبر بوابة الخدمات الذاتية.
2. الاتفاق مع المدير المباشر على أهداف أسبوعية قابلة للقياس.
3. الالتزام بسياسة أمن المعلومات عند العمل من خارج المكتب.

للاستفسار يرجى التواصل مع فريق علاقات الموظفين على التحويلة ٤٤١٠.
""")


# ════════════════════════════ English ════════════════════════════

def en_executive_report() -> DocumentBuilder:
    charts = {
        "rev": dict(chart_type="line", title="Monthly recurring revenue ($M)", height=3.0,
                    data={"Jan": 8.1, "Feb": 8.4, "Mar": 8.9, "Apr": 9.2, "May": 9.6, "Jun": 10.3,
                          "Jul": 10.8, "Aug": 11.0, "Sep": 11.7}),
        "mix": dict(chart_type="donut", title="Revenue by segment", height=3.0, width=4.5,
                    data={"Enterprise": 54, "Mid-market": 29, "SMB": 17}),
    }
    return _md("""---
title: Q3 2025 Executive Performance Report
author: Office of the CFO, Lumen Analytics (fictional)
---
# Executive Summary

Lumen Analytics closed the third quarter with $33.5M in revenue, 21% above the same quarter last year and 4% ahead
of plan. Growth came primarily from enterprise expansions, while new-logo acquisition in the mid-market slowed as
sales cycles lengthened. Operating margin improved to 14.2% as hosting costs fell after the storage migration.

Three decisions are requested from the board this quarter: approval of the European data-centre investment,
a revised hiring plan for customer success, and the updated pricing for the analytics add-on.

# Financial Performance

Recurring revenue grew every month of the quarter. Net revenue retention reached 118%, driven by seat expansion
in financial services and the launch of usage-based billing for the forecasting module.

[[chart:rev]]

| Metric | Q3 2025 | Q3 2024 | Change |
|---|---:|---:|---:|
| Revenue ($M) | 33.5 | 27.7 | +21% |
| Gross margin | 78.4% | 74.9% | +3.5 pt |
| Operating margin | 14.2% | 9.8% | +4.4 pt |
| Free cash flow ($M) | 6.1 | 3.2 | +91% |
| Net revenue retention | 118% | 112% | +6 pt |

Enterprise customers now account for more than half of revenue. The mid-market share declined slightly as two
large renewals moved into the enterprise tier after expanding their contracts.

[[chart:mix]]

# Operations

Platform availability was 99.97% against a target of 99.95%. Mean time to restore service fell from 41 to 23
minutes after the on-call rotation was reorganised by product area. The storage migration completed two weeks
early and reduced hosting cost per customer by 18%.

> **Risk to watch:** two of the five largest customers renew in Q1 2026 and are evaluating consolidation
> onto a single analytics vendor. Account plans are in place for both.

# Decisions Requested

1. Approve a capital budget of $4.2M for the Frankfurt data centre, required by three enterprise prospects
   with EU data-residency clauses.
2. Approve 14 additional customer-success roles, funded by the improved operating margin.
3. Endorse the new add-on pricing of $18 per seat per month, effective January 2026.

# Outlook

We maintain full-year guidance of $128–131M in revenue and expect operating margin between 13% and 15%. The main
upside is earlier closure of the public-sector framework; the main downside is further mid-market slowdown.
""", charts)


def bilingual_board_report() -> DocumentBuilder:
    b = DocumentBuilder().meta(title="Board Report — تقرير مجلس الإدارة", author="Corporate Secretariat")
    b.cover_page("Board Report Q3 2025", subtitle="تقرير مجلس الإدارة — الربع الثالث ٢٠٢٥",
                 author="Gulf Horizon Logistics (fictional) | الخليج للخدمات اللوجستية", date="October 2025")
    sections = [
        ("Performance Overview", "نظرة عامة على الأداء",
         "Shipment volumes grew 12% year on year to 1.84 million TEU, supported by the new Dammam rail link. "
         "On-time delivery improved to 96.1% and claims fell by a third after the warehouse scanning roll-out.",
         "ارتفعت أحجام الشحن بنسبة ١٢٪ لتبلغ ١٫٨٤ مليون حاوية نمطية بدعم من خط السكة الحديدية الجديد، "
         "وتحسنت نسبة التسليم في الموعد إلى ٩٦٫١٪ وانخفضت المطالبات بمقدار الثلث."),
        ("Financial Results", "النتائج المالية",
         "Revenue reached SAR 2.31bn (+9%), and net profit SAR 286m (+14%). Capital expenditure of SAR 410m "
         "was directed to cold-chain capacity and fleet electrification pilots.",
         "بلغت الإيرادات ٢٫٣١ مليار ريال بنمو ٩٪، وصافي الربح ٢٨٦ مليون ريال بنمو ١٤٪، ووُجّهت النفقات "
         "الرأسمالية البالغة ٤١٠ ملايين ريال إلى سلاسل التبريد وتجارب كهربة الأسطول."),
        ("Safety and People", "السلامة والموظفون",
         "The lost-time injury rate fell to 0.21 per million hours. Saudization reached 41% across operations, "
         "with 380 graduates joining the logistics apprenticeship programme.",
         "انخفض معدل الإصابات المضيعة للوقت إلى ٠٫٢١ لكل مليون ساعة عمل، وبلغت نسبة التوطين ٤١٪، "
         "وانضم ٣٨٠ خريجاً إلى برنامج التدريب المنتهي بالتوظيف."),
    ]
    for en_h, ar_h, en, ar in sections:
        b.heading(f"{en_h} | {ar_h}", level=1)
        b.paragraph(en)
        b.paragraph(ar)
    b.table(["Indicator", "المؤشر", "Q3 2025", "Q3 2024"],
            [["Volume (k TEU)", "الأحجام (ألف حاوية)", "1,840", "1,643"],
             ["On-time delivery", "التسليم في الموعد", "96.1%", "93.4%"],
             ["Revenue (SAR m)", "الإيرادات (مليون ريال)", "2,310", "2,119"],
             ["Net profit (SAR m)", "صافي الربح (مليون ريال)", "286", "251"],
             ["LTIR", "معدل الإصابات", "0.21", "0.34"]], caption="Key indicators / المؤشرات الرئيسية")
    b.chart("grouped_bar", data={"categories": ["Q1", "Q2", "Q3"],
                                 "series": {"2024": [1.51, 1.58, 1.64], "2025": [1.66, 1.75, 1.84]}},
            title="Volume by quarter (m TEU) / الأحجام الفصلية", height=3.0)
    b.heading("Resolutions | القرارات", level=1)
    b.numbered_list(["Approve the interim dividend of SAR 0.75 per share — اعتماد توزيع أرباح مرحلية "
                     "بواقع ٠٫٧٥ ريال للسهم",
                     "Approve the Jubail cold-store investment — اعتماد الاستثمار في مستودع التبريد بالجبيل",
                     "Appoint the external auditor for 2026 — تعيين مراجع الحسابات الخارجي لعام ٢٠٢٦"])
    return b


def proposal() -> DocumentBuilder:
    return _md("""---
title: Managed Cloud Migration Proposal
author: Harbor & Pine Consulting (fictional)
subject: Prepared for Meridian Health Network (fictional)
---
# Executive Summary

Meridian Health Network operates 46 on-premise applications across two ageing data centres whose hardware
support ends in June 2026. We propose a phased migration of 38 applications to a managed cloud landing zone,
retiring eight legacy systems, in 30 weeks and within a fixed fee of $1.48M.

The approach keeps patient-facing systems available throughout, meets HIPAA safeguards from day one and
reduces annual infrastructure cost by an estimated 27%.

# Objectives

- Exit both data centres before hardware support expires.
- Achieve 99.95% availability for clinical systems after migration.
- Establish infrastructure-as-code and automated compliance evidence.
- Transfer operational knowledge to Meridian's platform team.

# Approach

## Phase 1 — Discovery and landing zone (weeks 1–8)

We inventory dependencies, classify data, and build a landing zone with network segmentation, identity
federation, logging and backup policies defined as code.

## Phase 2 — Migration waves (weeks 9–26)

Applications move in five waves grouped by dependency and risk. Each wave follows the same runbook: rehearsal,
data synchronisation, cut-over during an agreed maintenance window, and a two-week hypercare period.

| Wave | Applications | Window | Risk |
|---|---|---|---|
| 1 | Intranet, document management, HR | Weeks 9–11 | Low |
| 2 | Finance, procurement, analytics | Weeks 12–15 | Medium |
| 3 | Laboratory information system | Weeks 16–19 | High |
| 4 | Scheduling and patient portal | Weeks 20–23 | High |
| 5 | Remaining shared services | Weeks 24–26 | Medium |

## Phase 3 — Optimisation and handover (weeks 27–30)

We right-size resources, enable cost alerts and complete the knowledge-transfer programme.

# Commercials

| Item | Fee (USD) |
|---|---:|
| Discovery and landing zone | 312,000 |
| Migration waves 1–5 | 948,000 |
| Optimisation and handover | 146,000 |
| Programme management | 74,000 |
| **Total (fixed fee)** | **1,480,000** |

Payment is due against milestone acceptance. Cloud consumption is billed directly to Meridian.

# Why Harbor & Pine

We have completed 23 healthcare migrations since 2019 without an unplanned clinical outage, and our team
holds current security and cloud-architecture certifications.

# Next Steps

1. Confirm scope and the wave plan in a workshop the week of 17 November.
2. Sign the statement of work by 5 December.
3. Mobilise the team on 12 January 2026.
""")


def business_memo() -> DocumentBuilder:
    return _md("""---
title: Memo — Travel Policy Update
author: Finance Operations
---
# Memorandum

**To:** All staff
**From:** Finance Operations
**Date:** 3 November 2025
**Re:** Updated travel and expense policy

From 1 December 2025 all travel must be booked through the corporate portal at least 14 days in advance.
Economy class remains the default for flights under six hours; premium economy is permitted above six hours
with director approval.

## Key changes

- Daily meal allowance increases from $55 to $62 in tier-one cities.
- Receipts are required for every expense above $25.
- Claims must be submitted within 30 days of return.

Questions can be sent to the finance helpdesk. Thank you for your cooperation.
""")


def academic_paper() -> DocumentBuilder:
    return _md("""---
title: Sleep Duration and Short-Term Recall in Adults — A Randomised Study
author: R. Okafor, L. Haddad and M. Sato (fictional)
---
# Abstract

We examined whether a single night of restricted sleep affects short-term verbal recall. In a randomised
controlled design, 124 adults were assigned to restricted (5 h) or habitual (8 h) sleep. Recall on a 30-word
list declined by 14.2% after restriction compared with habitual sleep (d = 0.61, p < 0.001).[^1]

**Keywords:** sleep restriction, working memory, recall, randomised trial

# Introduction

Sleep supports memory consolidation through hippocampal replay and synaptic down-scaling [1, 2]. Prior
laboratory studies have reported recall deficits after total sleep deprivation [3], but evidence for partial
restriction — the more common real-world condition — is mixed [4, 5]. We therefore tested a single night of
partial restriction in a sample large enough to detect moderate effects.

# Methods

## Participants

Adults aged 19–54 without diagnosed sleep disorders were recruited through university mailing lists. After
exclusions, 124 participants were randomised (62 per arm). Sleep was verified by wrist actigraphy.

## Procedure

Participants learned a 30-word list at 21:00 and were tested at 09:00 the following morning. The primary
outcome was the number of correctly recalled words. Effect sizes were computed as

$$ d = \\frac{\\bar{x}_1 - \\bar{x}_2}{s_p} $$

where $s_p$ is the pooled standard deviation.

## Analysis

We fitted a linear model with condition, age and baseline recall as predictors. Analyses were pre-registered
and conducted in R 4.4 [6].

# Results

| Condition | n | Mean recall | SD | 95% CI |
|---|---:|---:|---:|---|
| Habitual sleep (8 h) | 62 | 18.3 | 3.9 | 17.3–19.3 |
| Restricted sleep (5 h) | 62 | 15.7 | 4.6 | 14.5–16.9 |

Restricted sleep reduced recall by 2.6 words on average (β = −2.58, SE = 0.71, p < 0.001). The effect did not
vary with age (interaction p = 0.42).[^2]

# Discussion

A single night of partial restriction produced a moderate recall deficit comparable to that reported after
total deprivation in smaller samples [3]. The findings support consolidation accounts in which early-night
slow-wave sleep is particularly important [1]. Limitations include the single-night design and a sample of
mostly university-educated adults.

# Conclusion

Even one night of five-hour sleep measurably impairs next-day recall. Public guidance on sleep before
examinations and safety-critical work should reflect this.

# References

1. Diekelmann, S., & Born, J. (2010). The memory function of sleep. *Nature Reviews Neuroscience*, 11(2), 114–126.
2. Tononi, G., & Cirelli, C. (2014). Sleep and the price of plasticity. *Neuron*, 81(1), 12–34.
3. Walker, M. P. (2009). The role of sleep in cognition and emotion. *Annals of the NY Academy of Sciences*, 1156, 168–197.
4. Lim, J., & Dinges, D. F. (2010). A meta-analysis of the impact of short-term sleep deprivation. *Psychological Bulletin*, 136(3), 375–389.
5. Cousins, J. N., & Fernández, G. (2019). The impact of sleep deprivation on declarative memory. *Progress in Brain Research*, 246, 27–53.
6. R Core Team (2024). *R: A language and environment for statistical computing*. Vienna: R Foundation.

[^1]: Study data and analysis scripts are available from the corresponding author on request.
[^2]: Sensitivity analyses excluding participants with actigraphy-verified sleep outside the protocol gave the same result.
""")


def technical_manual() -> DocumentBuilder:
    return _md("""---
title: Ledgerline API — Integration Manual v2.3
author: Ledgerline Platform Team (fictional)
---
# Overview

The Ledgerline API lets accounting systems create invoices, record payments and reconcile bank transactions.
All endpoints use JSON over HTTPS and require OAuth 2.0 client-credential tokens.

```mermaid
flowchart LR
    Client[Accounting system] --> Auth[Token service]
    Client --> API[Ledgerline API]
    API --> Ledger[(Ledger store)]
    API --> Bank[Bank feed connector]
```

# Authentication

Request a token with your client ID and secret. Tokens expire after 3600 seconds; cache them and refresh
before expiry rather than requesting one per call.

```python
import requests

def get_token(client_id: str, client_secret: str) -> str:
    resp = requests.post(
        "https://auth.ledgerline.example/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
```

> **Note:** never embed secrets in client-side code. Store them in your platform's secret manager.

# Creating an Invoice

Send a `POST` to `/v2/invoices`. Amounts are integers in minor units (cents) to avoid rounding errors.

```json
{
  "customer_id": "cus_8841",
  "currency": "EUR",
  "due_date": "2025-12-15",
  "lines": [
    {"description": "Consulting, October", "quantity": 12, "unit_amount": 15000},
    {"description": "Travel expenses", "quantity": 1, "unit_amount": 42350}
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `customer_id` | string | yes | Existing customer identifier |
| `currency` | string | yes | ISO 4217 code |
| `due_date` | date | no | Defaults to 30 days after issue |
| `lines` | array | yes | One or more invoice lines |
| `reference` | string | no | Your own reference, max 64 characters |

# Recording Payments

Payments are matched to invoices by `invoice_id`. Partial payments are allowed; the invoice status changes to
`paid` when the outstanding amount reaches zero.

```bash
curl -X POST https://api.ledgerline.example/v2/payments \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"invoice_id": "inv_2291", "amount": 222350, "paid_at": "2025-11-02"}'
```

# Error Handling

| Status | Code | Meaning | Action |
|---|---|---|---|
| 400 | `invalid_request` | Malformed body or field | Fix the request; do not retry |
| 401 | `invalid_token` | Token missing or expired | Refresh the token and retry once |
| 409 | `duplicate` | Idempotency key reused | Treat as success |
| 429 | `rate_limited` | Too many requests | Retry after the `Retry-After` header |
| 503 | `unavailable` | Temporary outage | Retry with exponential backoff |

Retry only idempotent requests, and always send an `Idempotency-Key` header with `POST` requests.

# Webhooks

Ledgerline sends signed webhooks for `invoice.paid`, `payment.failed` and `reconciliation.completed`. Verify
the `X-Ledgerline-Signature` header with your webhook secret before processing the payload.

```python
import hashlib, hmac

def verify(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

# Rate Limits

| Plan | Requests per minute | Burst |
|---|---:|---:|
| Starter | 120 | 20 |
| Business | 600 | 100 |
| Enterprise | 3,000 | 500 |

# Changelog

- **2.3** — Added reconciliation webhooks and the `reference` field.
- **2.2** — Partial payments; deprecated `/v1/payments`.
- **2.1** — Idempotency keys for all `POST` endpoints.
""")


def financial_statements() -> DocumentBuilder:
    b = DocumentBuilder().meta(title="Consolidated Financial Statements FY2025",
                               author="Northwind Manufacturing plc (fictional)")
    b.heading("Consolidated Income Statement", level=1)
    b.paragraph("For the year ended 30 June 2025. All amounts in £ thousands unless otherwise stated.")
    inc = [["Revenue", "3", "412,880", "388,214"], ["Cost of sales", "", "(281,402)", "(268,991)"],
           ["Gross profit", "", "131,478", "119,223"], ["Distribution costs", "", "(22,114)", "(21,870)"],
           ["Administrative expenses", "", "(48,902)", "(46,335)"], ["Other operating income", "4", "3,118", "2,404"],
           ["Operating profit", "", "63,580", "53,422"], ["Finance income", "6", "1,204", "688"],
           ["Finance costs", "6", "(9,880)", "(10,412)"], ["Profit before tax", "", "54,904", "43,698"],
           ["Income tax expense", "7", "(13,726)", "(10,487)"], ["Profit for the year", "", "41,178", "33,211"],
           ["Basic earnings per share (pence)", "8", "32.4", "26.1"],
           ["Diluted earnings per share (pence)", "8", "32.1", "25.9"]]
    b.table(["", "Note", "2025", "2024"], inc, caption="Consolidated income statement")
    b.heading("Consolidated Statement of Financial Position", level=1)
    sofp = [["Non-current assets", "", "", ""], ["Property, plant and equipment", "10", "214,560", "205,118"],
            ["Right-of-use assets", "11", "18,402", "20,116"], ["Intangible assets", "12", "41,880", "43,207"],
            ["Deferred tax assets", "7", "3,115", "3,902"], ["Current assets", "", "", ""],
            ["Inventories", "13", "68,914", "64,102"], ["Trade and other receivables", "14", "72,330", "69,841"],
            ["Cash and cash equivalents", "15", "38,207", "29,550"], ["Total assets", "", "457,408", "435,836"],
            ["Current liabilities", "", "", ""], ["Trade and other payables", "16", "(61,940)", "(58,302)"],
            ["Borrowings", "17", "(12,000)", "(15,000)"], ["Lease liabilities", "11", "(4,118)", "(4,206)"],
            ["Non-current liabilities", "", "", ""], ["Borrowings", "17", "(98,000)", "(110,000)"],
            ["Lease liabilities", "11", "(15,902)", "(17,880)"], ["Retirement benefit obligation", "18", "(9,412)", "(11,904)"],
            ["Net assets", "", "256,036", "218,544"], ["Share capital", "19", "12,700", "12,700"],
            ["Retained earnings", "", "243,336", "205,844"], ["Total equity", "", "256,036", "218,544"]]
    b.table(["", "Note", "30 Jun 2025", "30 Jun 2024"], sofp, caption="Consolidated statement of financial position")
    b.heading("Segment Information", level=1)
    b.paragraph("The group has four reportable segments based on the products manufactured. Inter-segment sales "
                "are priced on an arm's-length basis.")
    seg = [["Industrial pumps", "148,220", "139,904", "24,118", "21,602", "62,410", "8,214"],
           ["Valves and actuators", "112,904", "106,330", "17,902", "15,880", "48,102", "6,118"],
           ["Flow measurement", "86,412", "79,118", "14,330", "11,204", "31,880", "4,402"],
           ["Aftermarket services", "65,344", "62,862", "11,904", "10,736", "12,904", "1,880"],
           ["Unallocated", "—", "—", "(4,674)", "(6,000)", "59,264", "312"],
           ["Group", "412,880", "388,214", "63,580", "53,422", "214,560", "20,926"]]
    b.table(["Segment", "Revenue 2025", "Revenue 2024", "Op. profit 2025", "Op. profit 2024", "PP&E", "Capex"],
            seg, caption="Segment revenue, operating profit and assets (£000)")
    b.heading("Notes to the Financial Statements", level=1)
    notes = [("1. Basis of preparation", "The financial statements have been prepared in accordance with UK-adopted "
              "international accounting standards on the historical-cost basis, except for derivative instruments "
              "and pension assets measured at fair value."),
             ("3. Revenue", "Revenue is recognised when control of goods passes to the customer, generally on delivery. "
              "Service revenue is recognised over time as the work is performed."),
             ("7. Taxation", "The effective tax rate of 25.0% (2024: 24.0%) reflects the increase in the UK main rate "
              "of corporation tax and non-deductible expenses."),
             ("17. Borrowings", "The group has a £180m revolving credit facility maturing in 2028, of which £110m was "
              "drawn at the year end. Covenants were met throughout the year.")]
    for h, t in notes:
        b.heading(h, level=2)
        b.paragraph(t)
    b.table(["Maturity", "< 1 year", "1–2 years", "2–5 years", "> 5 years", "Total"],
            [["Borrowings", "12,000", "18,000", "80,000", "—", "110,000"],
             ["Lease liabilities", "4,118", "3,902", "8,330", "3,670", "20,020"],
             ["Trade payables", "61,940", "—", "—", "—", "61,940"]], caption="Contractual maturity analysis (£000)")
    return b


def chart_analytics_report() -> DocumentBuilder:
    b = DocumentBuilder().meta(title="E-commerce Analytics Review — H1 2025", author="Insights Team, Brightcart (fictional)")
    b.heading("Summary", level=1)
    b.paragraph("Gross merchandise value rose 16% to $412M in the first half. Mobile now drives 63% of orders, "
                "conversion improved after the checkout redesign, and return rates fell in apparel after the "
                "size-guide launch. The figures below support the recommendations at the end of this report.")
    b.metric_row([{"label": "GMV", "value": "$412M", "delta": "+16%"},
                  {"label": "Orders", "value": "5.1M", "delta": "+11%"},
                  {"label": "Conversion", "value": "3.4%", "delta": "+0.4 pt"}])
    figs = [
        ("Traffic and Conversion", "Weekly sessions grew steadily; the checkout redesign in week 14 lifted "
         "conversion immediately and the gain held through the half.",
         dict(chart_type="line", title="Conversion rate by month (%)",
              data={"Jan": 2.9, "Feb": 3.0, "Mar": 3.0, "Apr": 3.5, "May": 3.6, "Jun": 3.7})),
        ("Channel Mix", "Paid search remains the largest acquisition channel, but email and organic "
         "search grew fastest and carry the lowest acquisition cost.",
         dict(chart_type="horizontal_bar", title="Orders by channel (thousands)",
              data={"Paid search": 1480, "Organic search": 1210, "Email": 860, "Social": 740, "Affiliates": 510,
                    "Direct": 300})),
        ("Device Share", "Mobile overtook desktop for every category except furniture, where customers "
         "still compare items on larger screens before buying.",
         dict(chart_type="pie", title="Orders by device", width=4.5,
              data={"Mobile": 63, "Desktop": 29, "Tablet": 8})),
        ("Category Performance", "Electronics and home grew fastest; apparel grew more slowly but with higher "
         "margin after returns fell.",
         dict(chart_type="grouped_bar", title="GMV by category ($M)",
              data={"categories": ["Apparel", "Electronics", "Home", "Beauty", "Furniture"],
                    "series": {"H1 2024": [92, 88, 61, 42, 72], "H1 2025": [98, 112, 79, 49, 74]}})),
        ("Basket Size", "Average order value rose in every month, helped by bundles and the free-shipping "
         "threshold change in March.",
         dict(chart_type="area", title="Average order value ($)",
              data={"Jan": 74, "Feb": 76, "Mar": 79, "Apr": 81, "May": 80, "Jun": 83})),
        ("Returns", "Apparel returns fell from 24% to 19% after the size guide; electronics returns remain low.",
         dict(chart_type="bar", title="Return rate by category (%)",
              data={"Apparel": 19, "Electronics": 6, "Home": 9, "Beauty": 4, "Furniture": 11})),
        ("Funnel", "The largest drop-off is between product view and add-to-cart, which is where the "
         "recommendations below focus.",
         dict(chart_type="funnel", title="Purchase funnel (millions of sessions)",
              data={"Sessions": 150, "Product view": 92, "Add to cart": 21, "Checkout": 8.4, "Order": 5.1})),
        ("Customer Satisfaction", "Net promoter score improved by six points; delivery speed is the most "
         "frequent reason given by promoters.",
         dict(chart_type="gauge", title="Net promoter score", width=4.5, data={"NPS": 47})),
    ]
    for h, p, c in figs:
        b.heading(h, level=2)
        b.paragraph(p)
        b.add_block(ChartBlock(height=3.6, **c))
    b.heading("Recommendations", level=1)
    b.numbered_list(["Extend the checkout redesign patterns to the product page, targeting add-to-cart.",
                     "Shift 10% of paid-search budget to email and organic content.",
                     "Roll the size-guide approach out to footwear.",
                     "Test a lower free-shipping threshold for furniture."])
    b.table(["Category", "GMV H1 2024 ($M)", "GMV H1 2025 ($M)", "Growth", "Return rate"],
            [["Apparel", "92", "98", "6.5%", "19%"], ["Electronics", "88", "112", "27.3%", "6%"],
             ["Home", "61", "79", "29.5%", "9%"], ["Beauty", "42", "49", "16.7%", "4%"],
             ["Furniture", "72", "74", "2.8%", "11%"]], caption="Category detail")
    return b


def letter() -> DocumentBuilder:
    return _md("""---
title: Letter of Engagement
author: Okafor & Lindqvist Chartered Accountants (fictional)
---
Okafor & Lindqvist Chartered Accountants
14 Wharf Street, Bristol BS1 4RN

3 November 2025

Ms Elena Marsh
Finance Director
Greenvale Foods Ltd (fictional)
22 Mill Lane, Bath BA2 3QT

Dear Ms Marsh,

**Engagement for the audit of the financial statements for the year ending 31 March 2026**

Thank you for appointing us as auditors of Greenvale Foods Ltd. This letter sets out the scope of our work,
our respective responsibilities and the basis of our fees.

We will conduct our audit in accordance with International Standards on Auditing (UK) and report to the
members whether the financial statements give a true and fair view. Management remains responsible for
preparing the financial statements and for maintaining adequate internal controls.

Our fee for the audit is £38,500 plus VAT, invoiced in three instalments. Any additional work requested
outside this scope will be agreed with you in advance.

Please confirm your agreement by signing and returning a copy of this letter.

Yours sincerely,

Adaeze Okafor
Engagement Partner
""")


def invoice() -> DocumentBuilder:
    return _md("""---
title: Invoice INV-2025-0418
author: Studio Kite Design Ltd (fictional)
---
# Invoice INV-2025-0418

**Studio Kite Design Ltd** · 7 Canal Yard, Leeds LS1 4AP · VAT GB 284 1190 37

**Bill to:** Fernhill Books Ltd, 3 Market Row, York YO1 8RX
**Issue date:** 3 November 2025 · **Due date:** 3 December 2025

| Description | Qty | Unit price (£) | Amount (£) |
|---|---:|---:|---:|
| Brand identity refresh — discovery workshop | 1 | 1,800.00 | 1,800.00 |
| Logo and typography system | 1 | 4,200.00 | 4,200.00 |
| Bookshop signage designs | 3 | 650.00 | 1,950.00 |
| Website template designs | 6 | 420.00 | 2,520.00 |
| Print-ready artwork preparation | 8 | 95.00 | 760.00 |
| **Subtotal** | | | **11,230.00** |
| VAT at 20% | | | 2,246.00 |
| **Total due** | | | **13,476.00** |

**Payment:** bank transfer to Studio Kite Design Ltd, sort code 20-45-77, account 41882916. Please quote the
invoice number as the payment reference.

Thank you for your business.
""")


HANDBOOK = [
    ("Welcome", [
        "This handbook explains how we work, what you can expect from Fernway Engineering and what we expect "
        "from you. It applies to all employees in the United Kingdom and should be read together with your "
        "contract of employment.",
        "Policies change from time to time. The current version is always on the intranet, and significant "
        "changes are announced by email at least four weeks before they take effect."]),
    ("Working Hours and Flexibility", [
        "Standard hours are 37.5 per week, Monday to Friday. Core hours are 10:00 to 15:30; outside those hours "
        "you may arrange your day with your manager to suit your work and personal commitments.",
        "Hybrid working is available for roles that do not require a physical presence. Most teams agree two "
        "office days per week, chosen to maximise collaboration rather than attendance for its own sake.",
        "Overtime must be approved in advance. Time off in lieu is recorded in the HR system and must be taken "
        "within three months."]),
    ("Leave", [
        "Full-time employees receive 27 days of annual leave plus public holidays, rising by one day for each "
        "two years of service up to 32 days. Up to five days may be carried into the next year.",
        "Family leave exceeds the statutory minimum: 26 weeks of full pay for birth or adoption leave and "
        "six weeks of full pay for partners.",
        "Compassionate leave of up to ten days is available on the death or serious illness of a close family "
        "member. Managers may agree more where circumstances require it."]),
    ("Pay and Benefits", [
        "Salaries are paid monthly on the 25th. Pay is reviewed annually in April against market data and "
        "individual performance.",
        "The pension scheme matches employee contributions up to 8% of salary. Other benefits include private "
        "medical insurance, life assurance at four times salary and an annual wellbeing allowance."]),
    ("Health and Safety", [
        "Everyone is responsible for safety. Stop any task you believe is unsafe and report hazards and near "
        "misses through the safety app; reports can be anonymous.",
        "Site visits require a completed induction, appropriate protective equipment and a signed risk "
        "assessment. Lone working on sites is not permitted."]),
    ("Conduct and Ethics", [
        "We expect honesty, respect and professionalism in all dealings with colleagues, clients and the "
        "public. Discrimination, harassment and bullying are not tolerated.",
        "Gifts and hospitality above £50 must be declared. Conflicts of interest, including outside "
        "employment, must be disclosed to your manager and the compliance team."]),
    ("Information Security", [
        "Protect company and client information. Use only approved devices and services, lock your screen "
        "when you leave your desk and never share passwords.",
        "Report suspected phishing or data loss immediately to the IT service desk. Early reporting limits "
        "harm and is never treated as a disciplinary matter in itself."]),
    ("Learning and Development", [
        "Every employee has an annual development budget of £1,500 and five learning days. Chartership and "
        "professional qualifications are funded in full where relevant to your role.",
        "Mentoring is available at all levels; ask the people team to be matched with a mentor outside your "
        "reporting line."]),
    ("Performance", [
        "Objectives are agreed at the start of the year and reviewed quarterly. Conversations focus on "
        "progress, support needed and development rather than ratings alone.",
        "Where performance falls short, your manager will agree a support plan with clear expectations and "
        "reasonable time to improve before any formal process starts."]),
    ("Grievance and Disciplinary Procedures", [
        "Raise concerns informally with your manager first where possible. If that is not appropriate, submit "
        "a written grievance to the people team, who will acknowledge it within five working days.",
        "Disciplinary matters follow the ACAS code of practice. You may be accompanied at any formal meeting by "
        "a colleague or trade-union representative."]),
    ("Leaving the Company", [
        "Notice periods are set out in your contract. Return all equipment and documents by your last day; "
        "outstanding leave is paid or deducted in the final salary.",
        "We hold exit interviews to learn from your experience. Participation is voluntary and feedback is "
        "reported anonymously."]),
]


def policy_handbook() -> DocumentBuilder:
    rnd = random.Random(7)
    b = DocumentBuilder().meta(title="Employee Handbook 2026", author="People Team, Fernway Engineering (fictional)")
    b.cover_page("Employee Handbook 2026", subtitle="Fernway Engineering Ltd (fictional)", author="People Team",
                 date="January 2026")
    b.table_of_contents(depth=2)
    for ci, (title, paras) in enumerate(HANDBOOK):
        b.heading(title, level=1)
        for p in paras:
            b.paragraph(p)
        b.heading("Frequently asked questions", level=2)
        for qn in range(3):
            b.paragraph(f"**Q{qn + 1}.** How does the {title.lower()} policy apply to part-time or fixed-term "
                        "employees? It applies pro rata to contracted hours, with any differences set out in the "
                        "individual contract and confirmed in writing by the people team.")
        b.heading("Responsibilities", level=2)
        b.table(["Role", "Responsibility", "Timescale"],
                [["Employee", f"Follow the {title.lower()} policy and raise questions early", "Ongoing"],
                 ["Line manager", "Apply the policy fairly and record decisions", "Within 5 working days"],
                 ["People team", "Advise, keep records and review the policy", "Annually"],
                 ["Executive sponsor", "Approve material changes", "As required"]],
                caption=f"Responsibilities — {title}")
        b.heading("Procedure", level=2)
        b.numbered_list([f"Read the {title.lower()} guidance on the intranet.",
                         "Discuss your situation with your line manager.",
                         "Submit the request or report through the HR system.",
                         "Receive a written outcome and keep a copy for your records."])
        if ci in (2, 3):
            b.table(["Years of service", "Annual leave (days)", "Carry-over (days)", "Pension match"],
                    [[str(y), str(min(32, 27 + y // 2)), "5", f"{min(8, 4 + y // 2)}%"] for y in range(0, 12, 1)],
                    caption="Entitlements by length of service")
        if ci == 4:
            b.table(["Month", "Reports", "Near misses", "Lost-time injuries", "Closed actions"],
                    [[m, str(rnd.randint(20, 60)), str(rnd.randint(5, 25)), str(rnd.randint(0, 2)),
                      str(rnd.randint(18, 58))] for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                                                          "Aug", "Sep", "Oct", "Nov", "Dec"]],
                    caption="Safety reporting 2025")
        b.callout(f"Need help with {title.lower()}? Contact people@fernway.example or ext. 2200.",
                  variant="info")
    b.heading("Appendix A — Glossary", level=1)
    terms = [("Annual leave", "Paid holiday entitlement excluding public holidays."),
             ("Core hours", "The period during which all employees are expected to be available."),
             ("Grievance", "A formal written concern raised by an employee about their work."),
             ("Hybrid working", "A pattern combining office and remote working agreed with a manager."),
             ("Line manager", "The person you report to day to day."),
             ("Near miss", "An unplanned event that did not cause harm but had the potential to do so."),
             ("Notice period", "The time either party must give to end the employment contract."),
             ("People team", "The human-resources function."),
             ("Pro rata", "In proportion to contracted hours."),
             ("Time off in lieu", "Paid time off given instead of overtime pay.")] * 2
    b.table(["Term", "Meaning"], [[t if i < 10 else f"{t} (see also)", m] for i, (t, m) in enumerate(terms)],
            caption="Glossary of terms")
    b.heading("Appendix B — Forms and Templates", level=1)
    for form in ("Flexible working request", "Leave request", "Expense claim", "Incident report",
                 "Conflict of interest declaration", "Training request"):
        b.heading(form, level=2)
        b.paragraph(f"The {form.lower()} form is completed in the HR system. Attach supporting documents and "
                    "submit it to your line manager, who will respond within five working days.")
        b.checklist([{"text": "Employee details completed", "checked": False},
                     {"text": "Manager reviewed", "checked": False},
                     {"text": "People team recorded the outcome", "checked": False}])
    b.heading("Appendix C — Policy Index", level=1)
    b.table(["Policy", "Owner", "Last review", "Next review"],
            [[t, "People team" if i % 2 else "Compliance", f"{rnd.randint(1, 12):02d}/2025",
              f"{rnd.randint(1, 12):02d}/2026"] for i, (t, _) in enumerate(HANDBOOK)], caption="Policy index")
    return b


CORPUS: Dict[str, Tuple[str, str, Callable[[], DocumentBuilder]]] = {
    "ar_annual_report": ("Arabic corporate report", "long", ar_annual_report),
    "ar_financial_statements": ("Arabic financial statements", "medium", ar_financial_statements),
    "ar_memo": ("Arabic internal memo", "small", ar_memo),
    "en_executive_report": ("English executive report", "medium", en_executive_report),
    "bilingual_board_report": ("Bilingual executive report", "medium", bilingual_board_report),
    "proposal": ("Business proposal", "medium", proposal),
    "business_memo": ("Business memo", "small", business_memo),
    "academic_paper": ("Academic paper with citations", "medium", academic_paper),
    "technical_manual": ("Technical manual (code, diagram)", "medium", technical_manual),
    "financial_statements": ("Financial statements (complex tables)", "medium", financial_statements),
    "chart_analytics_report": ("Chart-heavy analytical report", "medium", chart_analytics_report),
    "letter": ("Formal letter", "small", letter),
    "invoice": ("Invoice", "small", invoice),
    "policy_handbook": ("Long policy handbook", "long", policy_handbook),
}
