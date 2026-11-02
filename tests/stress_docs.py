"""
Real-world stress documents (deterministic). Each builder returns a fresh
DocumentBuilder; images are generated into ``asset_dir``.

Used by tests/test_stress_documents.py and scripts/render_samples.py.
"""
import os
import random

from dynamic_pdf import DocumentBuilder

AR_SENTENCES = [
    "حققت الشركة نمواً ملحوظاً في الإيرادات خلال الربع الثالث بفضل توسع قاعدة العملاء في القطاع الحكومي.",
    "ارتفعت تكاليف التشغيل بنسبة طفيفة نتيجة الاستثمار في البنية التحتية الرقمية وتدريب الموظفين.",
    "تواصل الإدارة تنفيذ خطة التحول الرقمي وفق الجدول الزمني المعتمد من مجلس الإدارة.",
    "تشير المؤشرات الأولية إلى تحسن رضا العملاء بعد إطلاق منصة الخدمة الذاتية الجديدة.",
    "تم توقيع ثلاث اتفاقيات شراكة استراتيجية مع مؤسسات إقليمية لتعزيز الحضور في الأسواق المجاورة.",
    "يعكس الأداء المالي قدرة الشركة على التكيف مع تقلبات السوق والحفاظ على هوامش ربح مستقرة.",
    "أوصت لجنة المراجعة بتعزيز إجراءات الرقابة الداخلية وتحديث سياسات إدارة المخاطر.",
    "بلغت نسبة التوطين في الوظائف القيادية مستوى غير مسبوق مقارنة بالأعوام السابقة.",
]
AR_SECTIONS = ["الملخص التنفيذي", "الأداء المالي", "العمليات التشغيلية", "الموارد البشرية",
               "التحول الرقمي", "إدارة المخاطر", "الحوكمة والامتثال", "الاستدامة",
               "خدمة العملاء", "المشاريع الاستراتيجية", "الشراكات", "التوقعات المستقبلية"]


def arabic_long_report():
    rnd = random.Random(11)
    b = (DocumentBuilder().meta(title="التقرير السنوي المتكامل ٢٠٢٦", author="إدارة الاستراتيجية",
                                language="ar").direction("rtl"))
    for si, sec in enumerate(AR_SECTIONS):
        b.heading(sec, level=1)
        for sub in range(3):
            b.heading(f"{sec}: المحور {sub + 1}", level=2)
            for _ in range(3):
                b.paragraph(" ".join(rnd.sample(AR_SENTENCES, 4)))
            if sub == 1:
                b.bullet_list([rnd.choice(AR_SENTENCES)[:60] for _ in range(4)])
        rows = [[f"البند {i + 1}", f"{rnd.randint(1000, 99999):,}", f"{rnd.uniform(-5, 25):.1f}%",
                 rnd.choice(["مكتمل", "قيد التنفيذ", "متأخر"])] for i in range(8 if si % 3 else 22)]
        b.table(["البند", "القيمة (ريال)", "التغير", "الحالة"], rows, caption=f"جدول {si + 1}: مؤشرات {sec}")
    return b


def bilingual_corporate():
    rnd = random.Random(5)
    b = DocumentBuilder().meta(title="Annual Corporate Report — التقرير السنوي", author="Corporate Affairs")
    b.cover_page("Annual Corporate Report 2026", subtitle="التقرير السنوي للشركة ٢٠٢٦",
                 author="Corporate Affairs | الشؤون المؤسسية", date="November 2026")
    b.table_of_contents(depth=2)
    pairs = [("Chairman's Message", "كلمة رئيس مجلس الإدارة"), ("Performance Highlights", "أبرز مؤشرات الأداء"),
             ("Operations", "العمليات"), ("Outlook", "التوقعات")]
    for en, ar in pairs:
        b.heading(en)
        b.paragraph(f"In 2026 the group delivered {rnd.randint(8, 19)}% revenue growth while investing in "
                    "people, digital channels and regional expansion. The board approved a dividend of "
                    f"SAR {rnd.uniform(1, 3):.2f} per share.")
        b.heading(ar)
        b.paragraph(" ".join(rnd.sample(AR_SENTENCES, 3)) + " بلغت الإيرادات 4.2 مليار ريال (SAR 4.2bn).")
        b.metric_row([{"label": "Revenue / الإيرادات", "value": "SAR 4.2bn", "delta": "+12%"},
                      {"label": "Net margin / هامش الربح", "value": "18.4%", "delta": "+1.1pt"},
                      {"label": "Employees / الموظفون", "value": "3,240", "delta": "+6%"}])
        b.table(["Segment", "القطاع", "Revenue (SAR m)", "Growth"],
                [["Retail", "التجزئة", "1,820", "9.5%"], ["Corporate", "الشركات", "1,410", "14.2%"],
                 ["Government", "الحكومي", "970", "17.8%"]], caption="Revenue by segment / الإيرادات حسب القطاع")
    return b


def executive_proposal():
    b = (DocumentBuilder().meta(title="Customer Data Platform Proposal", author="Northwind Consulting",
                                subject="Prepared for Contoso Retail"))
    b.heading("Executive Summary")
    b.paragraph("Contoso Retail wants a single, trusted view of every customer across 340 stores and the "
                "online channel. We propose a phased customer data platform that unifies loyalty, "
                "e-commerce and point-of-sale data within 16 weeks, with measurable uplift in campaign "
                "conversion from the first release.")
    b.metric_row([{"label": "Timeline", "value": "16 weeks"}, {"label": "Investment", "value": "$612k"},
                  {"label": "Expected ROI", "value": "3.4x", "delta": "year one"}])
    b.heading("Objectives")
    b.bullet_list(["Unify 11 customer data sources into one governed profile",
                   "Cut campaign audience preparation from 5 days to 2 hours",
                   "Meet PDPL consent and retention requirements by design"])
    b.heading("Scope of Work")
    b.numbered_list([{"text": "Discovery and data audit", "children": ["Source inventory", "Quality baseline"]},
                     {"text": "Platform build", "children": ["Identity resolution", "Consent service"]},
                     "Activation and training"])
    b.heading("Timeline and Milestones")
    b.table(["Phase", "Weeks", "Milestone", "Owner"],
            [["Discovery", "1–3", "Audit report signed off", "Northwind"],
             ["Build", "4–11", "Unified profile in production", "Joint"],
             ["Activation", "12–16", "First personalised campaign live", "Contoso"]],
            caption="Delivery plan")
    b.heading("Investment")
    b.table(["Item", "Amount (USD)"], [["Discovery", "68,000"], ["Platform build", "412,000"],
                                       ["Activation & training", "132,000"]],
            footer_row=["Total", "612,000"])
    b.heading("Why Northwind")
    b.paragraph("We have delivered nine customer data programmes for regional retailers, and our team "
                "includes the architects who designed the market's two largest loyalty platforms.")
    b.heading("Next Steps")
    b.paragraph("Approve the statement of work by 30 November so discovery can begin on 7 December.")
    return b


def financial_complex():
    rnd = random.Random(3)
    b = DocumentBuilder().meta(title="Consolidated Financial Statements FY2026", author="Group Finance")
    b.heading("Consolidated Income Statement")
    b.paragraph("All figures in SAR thousands unless stated otherwise. Comparative figures restated for IFRS 17.")
    lines = ["Revenue", "Cost of sales", "Gross profit", "Selling expenses", "General & admin",
             "Depreciation", "Amortisation", "Operating profit", "Finance income", "Finance costs",
             "Share of associates", "Profit before zakat", "Zakat", "Net profit"]
    rows = []
    for q in range(6):
        for ln in lines:
            rows.append([f"Q{q % 4 + 1} {2025 + q // 4}", ln] +
                        [f"{rnd.randint(-90000, 990000):,}" for _ in range(5)])
    b.table(["Period", "Line item", "Retail", "Corporate", "Government", "Eliminations", "Group"], rows,
            caption="Quarterly segment income statement")
    b.heading("Balance Sheet")
    bs = [[f"Account {i:03d} — {rnd.choice(['Receivables', 'Inventory', 'PP&E', 'Intangibles', 'Payables', 'Borrowings'])}",
           f"{rnd.randint(1000, 900000):,}", f"{rnd.randint(1000, 900000):,}", f"{rnd.uniform(-30, 30):.1f}%"]
          for i in range(60)]
    b.table(["Account", "FY2026", "FY2025", "Change"], bs, caption="Statement of financial position",
            footer_row=["Total", "41,280,114", "38,902,551", "6.1%"])
    b.heading("Notes")
    b.paragraph("Segment eliminations reflect intra-group sales at arm's length. Borrowings include "
                "SAR 2.1bn of sukuk maturing in 2029.")
    return b


def academic_paper():
    b = DocumentBuilder().meta(title="Sleep Duration and Short-Term Recall", author="A. Rahman, J. Smith")
    b.abstract([{"label": "Background", "text": "Sleep supports memory consolidation, but dose effects are unclear."},
                {"label": "Methods", "text": "120 adults were randomised to 4, 6 or 8 hours of sleep."},
                {"label": "Results", "text": "Recall improved 12% from 4 to 8 hours (p < 0.01)."},
                {"label": "Conclusion", "text": "Recall scales with sleep duration up to 8 hours."}],
               keywords=["sleep", "memory", "recall"])
    sections = {"Introduction": 4, "Methods": 5, "Results": 4, "Discussion": 5, "Limitations": 2}
    for title, n in sections.items():
        b.heading(title)
        for i in range(n):
            b.paragraph(f"{title} paragraph {i + 1}. Participants completed a 40-item word list task after "
                        "each night; recall was scored blind by two raters with inter-rater agreement of "
                        "0.91. Effects were estimated with mixed models including participant random "
                        "intercepts [1], and sensitivity analyses excluded caffeine users [2].")
        if title == "Methods":
            b.math(r"y_{ij} = \beta_0 + \beta_1 \mathrm{sleep}_{ij} + u_j + \varepsilon_{ij}")
        if title == "Results":
            b.table(["Condition", "n", "Mean recall", "SD"],
                    [["4 h", "40", "21.3", "4.1"], ["6 h", "40", "23.0", "3.8"], ["8 h", "40", "23.9", "3.5"]],
                    caption="Recall by condition", table_number=1)
            b.chart("bar", data={"4 h": 21.3, "6 h": 23.0, "8 h": 23.9}, title="Mean recall by condition")
    b.bibliography([{"key": "1", "authors": "Bates, D. et al.", "title": "Fitting linear mixed-effects models",
                     "source": "Journal of Statistical Software 67(1)", "year": "2015", "doi": "10.18637/jss.v067.i01"},
                    {"key": "2", "authors": "Walker, M.", "title": "Why We Sleep", "source": "Scribner", "year": "2017"}])
    return b


def technical_manual(asset_dir):
    from PIL import Image, ImageDraw
    os.makedirs(asset_dir, exist_ok=True)
    shot = os.path.join(asset_dir, "screenshot.png")
    im = Image.new("RGB", (1200, 700), "#F4F6F9")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1200, 70], fill="#1F3A5F")
    d.rectangle([40, 120, 560, 640], outline="#9AA5B1", width=4)
    d.rectangle([620, 120, 1160, 360], fill="#DCE6F2")
    im.save(shot)
    b = DocumentBuilder().meta(title="Widget Server Administration Manual", author="Platform Team")
    b.heading("Overview")
    b.paragraph("Widget Server is a self-hosted job scheduler. This manual covers installation, "
                "configuration, operations and troubleshooting.")
    b.diagram("flowchart", nodes=[{"id": "c", "label": "Client"}, {"id": "a", "label": "API"},
                                  {"id": "q", "label": "Queue"}, {"id": "w", "label": "Workers"}],
              edges=[("c", "a"), ("a", "q"), ("q", "w")], title="Request flow", width=5, height=3)
    b.heading("Installation")
    b.heading("Requirements", level=2)
    b.bullet_list(["Linux x86_64, kernel 5.10+", "PostgreSQL 14+", "2 vCPU / 4 GB RAM minimum"])
    b.heading("Installing the package", level=2)
    b.code("bash", "curl -fsSL https://example.com/widget/install.sh -o install.sh\n"
                   "sha256sum --check install.sh.sha256\nsudo bash install.sh --prefix /opt/widget\n"
                   "sudo systemctl enable --now widget-server")
    b.callout("Always verify the installer checksum before running it as root.", variant="warning",
              title="Security")
    b.heading("Configuration")
    b.code("toml", "[server]\nlisten = \"0.0.0.0:8080\"\nworkers = 8\n\n[database]\n"
                   "url = \"postgres://widget@db/widget\"\npool_size = 20\n\n[scheduler]\n"
                   "max_retries = 5\nbackoff = \"exponential\"  # linear | exponential | fixed\n"
                   "very_long_option_name_for_testing_wrapping_behaviour = \"" + "x" * 90 + "\"",
           filename="/etc/widget/server.toml")
    b.table(["Key", "Default", "Description"],
            [["listen", "127.0.0.1:8080", "Address and port for the HTTP API"],
             ["workers", "4", "Worker processes; set to the number of vCPUs"],
             ["pool_size", "10", "Maximum database connections per process"],
             ["max_retries", "3", "Retries before a job is marked failed"]], caption="Configuration keys")
    b.heading("Operations")
    b.image(shot, caption="The operations dashboard", alt_text="Dashboard with job list and status panel")
    for i in range(1, 7):
        b.heading(f"Procedure {i}: {['Rotating keys', 'Scaling workers', 'Backups', 'Restores', 'Upgrades', 'Draining a node'][i - 1]}", level=2)
        b.numbered_list([f"Step {s}: run `widget admin {['check', 'apply', 'verify'][s % 3]} --node n{i}`"
                         for s in range(1, 5)])
        b.paragraph("Confirm the result in the dashboard before continuing to the next procedure.")
    b.heading("Troubleshooting")
    b.definition_list([{"term": "E1001 database unreachable", "definition": "Check `[database].url` and network ACLs."},
                       {"term": "E2040 worker crash loop", "definition": "Inspect `journalctl -u widget-server`."}])
    return b


STRESS = {
    "arabic_long_report": lambda d: arabic_long_report(),
    "bilingual_corporate": lambda d: bilingual_corporate(),
    "executive_proposal": lambda d: executive_proposal(),
    "financial_complex": lambda d: financial_complex(),
    "academic_paper": lambda d: academic_paper(),
    "technical_manual": technical_manual,
}
