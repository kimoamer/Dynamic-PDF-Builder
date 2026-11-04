"""
Fictional documents for the M7.6 media and page-system acceptance cases.

Every example runs twice from identical content: ``rich`` uses the media model and the
page system; plain drops them and keeps what the old API could say, so a before and
after compares the same words.
"""
from __future__ import annotations

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.schema.media import ImageTreatment
from dynamic_pdf.schema.page_system import Band, BandRow, Logo, PageSystem, SectionBands

TOPICS = {
    "harbour": ("The harbour authority surveyed every berth during the winter closure and logged the "
                "state of each mooring. Crews replaced worn fenders along the north quay and divers "
                "inspected the pilings beneath the ferry terminal. Dredging kept the main channel at "
                "its charted depth, and the pilots reported fewer tidal delays than in the prior year."),
    "energy": ("The district heating network added three substations this year and retired the last "
               "oil boiler on the eastern loop. Return temperatures fell after the controls upgrade, "
               "which lets the plant run its heat pumps for longer each day. Metered losses are now "
               "reported by street, so maintenance crews can go where the pipe is failing first."),
    "finance": ("Operating income rose on higher berth occupancy, while maintenance spending stayed "
                "within the approved envelope. Cash from operations covered the capital programme "
                "without new borrowing. The board kept the reserve ratio above its policy floor and "
                "moved two dredging contracts to fixed-price terms."),
    "editorial": ("Morning on the quay begins before the light does. The net menders arrive first, then "
                  "the ice truck, then the school crossing guard who has watched four decades of boats "
                  "come in. Nobody here calls it a working waterfront; it is simply where the day "
                  "starts, and where the town still agrees to meet."),
}
ARABIC = ("أَنْجَزَتْ هَيْئَةُ الْمِينَاءِ مَسْحَ الْأَرْصِفَةِ خِلَالَ فَصْلِ الشِّتَاءِ، وَسَجَّلَتْ حَالَةَ كُلِّ مَرْسًى. "
          "واستبدلت الفرق المصدّات البالية على الرصيف الشمالي، وفحص الغواصون الركائز تحت محطة العبّارات. "
          "وحافظت أعمال التجريف على عمق القناة الرئيسية، وأفاد المرشدون بتأخيرات أقل من العام السابق.")


class Kit:
    """The builder, with the media calls switched off for the plain run."""

    def __init__(self, rich: bool, theme: str, **meta):
        self.rich = rich
        self.b = DocumentBuilder(theme=theme)
        self.b.meta(**meta)

    def __getattr__(self, name):
        return getattr(self.b, name)

    def page_system(self, system):
        if self.rich:
            self.b.page_system(system)

    def page_background(self, *a, **k):
        if self.rich:
            self.b.page_background(*a, **k)

    def image_watermark(self, *a, **k):
        if self.rich:
            self.b.image_watermark(*a, **k)

    def page_section(self, name, **k):
        if self.rich:
            self.b.page_section(name, **k)

    def image(self, src, placement=None, treatment=None, height=None, border=False, shadow=False,
              source=None, **k):
        if self.rich:
            self.b.image(src, placement=placement, treatment=treatment, height=height, border=border,
                         shadow=shadow, source=source, **k)
        else:
            self.b.image(src, **k)

    def cover_page(self, title, background_image=None, layout=None, overlay_color=None, overlay_opacity=None,
                   text_color=None, background_color=None, logo=None, **k):
        if self.rich:
            extra = {"overlay_opacity": overlay_opacity} if overlay_opacity is not None else {}
            self.b.cover_page(title, background_image=background_image, layout=layout, logo=logo,
                              overlay_color=overlay_color, text_color=text_color,
                              background_color=background_color, **extra, **k)
        else:
            self.b.cover_page(title, logo=logo, **k)


def _bands(a, **values):
    head = Band(rows=[BandRow(start=[Logo(src=a["logo"], max_height=18, alt_text="Authority logo")],
                              center=["{title}"], end=["{section}"], rule_below=True)],
                accent_color="#14607a", accent_height=2.5)
    foot = Band(rows=[BandRow(left=["Saltmere Harbour Authority"], center=["Internal"],
                              right=["Page {page} of {pages}"])])
    return PageSystem(header=head, footer=foot, values=values)


def corporate_background(a, rich=True):
    k = Kit(rich, "corporate_dark", title="Saltmere Harbour Annual Review", language="en")
    k.page_system(_bands(a))
    k.cover_page("Saltmere Harbour Annual Review", background_image=a["harbour"], logo=a["logo"],
                 layout="left_aligned", subtitle="Moorings, dredging and the year ahead",
                 author="Operations Office", date="November 2026")
    k.page_background(a["paper"], scope="every_page", opacity=.5, alt_text="Pale paper texture")
    k.heading("The year in review", level=1)
    for _ in range(3):
        k.paragraph(TOPICS["harbour"])
    k.heading("Works on the north quay", level=2)
    k.image(a["harbour"], placement="full_width", height=190, treatment=ImageTreatment(fit="cover", focal_y=.55),
            caption="North quay after resurfacing", figure_number=1, source="Authority survey",
            alt_text="Illustration of the quay at dusk")
    for _ in range(3):
        k.paragraph(TOPICS["harbour"])
    return k


def editorial_floats(a, rich=True):
    k = Kit(rich, "modern_minimal", title="The Early Tide", language="en")
    k.page_system(PageSystem(footer=Band(rows=[BandRow(start=["The Early Tide"], end=["{page}"])]), first_page="none"))
    k.cover_page("The Early Tide", background_image=a["dawn"], layout="split",
                 subtitle="A season on the Saltmere waterfront", author="Features Desk", date="Autumn 2026")
    k.heading("Before the light", level=1)
    k.paragraph(TOPICS["editorial"])
    k.image(a["plant"], placement="float_end", caption="Net store, east wall", figure_number=1,
            alt_text="Flat colour study of a store room", source="Studio illustration")
    for _ in range(4):
        k.paragraph(TOPICS["editorial"])
    k.heading("The ice truck", level=2)
    k.image(a["dawn"], placement="float_start", alt_text="Dawn over the hills")
    for _ in range(3):
        k.paragraph(TOPICS["editorial"])
    k.image(a["harbour"], placement="full_bleed", height=210, treatment=ImageTreatment(fit="cover"),
            alt_text="The harbour at dusk")
    for _ in range(2):
        k.paragraph(TOPICS["editorial"])
    return k


def arabic_bilingual(a, rich=True):
    k = Kit(rich, "government", title="التقرير السنوي لميناء سالتمير", language="ar")
    k.page_system(PageSystem(
        header=Band(rows=[BandRow(start=[Logo(src=a["logo"], max_height=18, alt_text="شعار الهيئة")],
                                  center=["التقرير السنوي"], end=["Annual Review 2026"], rule_below=True)]),
        footer=Band(rows=[BandRow(start=["هيئة ميناء سالتمير"], end=["صفحة {page} من {pages}"])])))
    k.cover_page("التقرير السنوي لميناء سالتمير", background_image=a["harbour"], layout="split",
                 subtitle="Saltmere Harbour Annual Review", date="تشرين الثاني 2026")
    k.heading("مُلَخَّصُ الْعَام", level=1)
    k.paragraph(ARABIC)
    k.image(a["plant"], placement="float_start", caption="غرفة المضخات في الرصيف الشرقي", figure_number=1,
            alt_text="رسم توضيحي لغرفة المضخات")
    for _ in range(3):
        k.paragraph(ARABIC)
    k.heading("أعمال الرصيف الشمالي", level=2)
    k.paragraph(ARABIC)
    k.image(a["harbour"], placement="float_end", alt_text="رسم توضيحي للميناء")
    for _ in range(3):
        k.paragraph(ARABIC)
    return k


def financial_report(a, rich=True):
    k = Kit(rich, "data_report", title="Saltmere Harbour Financial Statements 2026", language="en")
    k.page_system(PageSystem(
        header=Band(rows=[BandRow(left=["{title}"], right=["{section}"], rule_below=True, size=8)]),
        footer=Band(rows=[BandRow(left=["Audited figures, SAR thousands"], center=["Ref {code}"],
                                  right=["{page} / {pages}"], size=7.5)]),
        values={"code": "SHA-FS-26"}))
    k.cover_page("Financial Statements 2026", background_color="#16324a", layout="left_aligned", logo=a["logo"],
                 subtitle="Saltmere Harbour Authority", date="Year ended 30 June 2026")
    k.heading("Results at a glance", level=1)
    k.paragraph(TOPICS["finance"])
    k.table(["Item", "2026", "2025", "Change"],
            [["Berth income", "48,210", "44,960", "7.2%"], ["Pilotage", "12,404", "12,110", "2.4%"],
             ["Maintenance", "(18,730)", "(18,020)", "3.9%"], ["Operating surplus", "21,884", "19,050", "14.9%"]],
            caption="Summary of operations")
    k.image(a["harbour"], placement="full_width", height=150, treatment=ImageTreatment(fit="cover", focal_y=.6),
            caption="Dredging on the main channel", figure_number=1, alt_text="Illustration of the channel")
    k.heading("Capital programme", level=1)
    k.paragraph(TOPICS["finance"])
    k.table(["Project", "Budget", "Spent", "Status"],
            [["North quay surfacing", "9,400", "9,120", "Complete"], ["Ferry pilings", "6,100", "2,840", "Under way"],
             ["Channel survey vessel", "3,650", "3,650", "Complete"]], caption="Capital projects")
    for _ in range(2):
        k.paragraph(TOPICS["finance"])
    return k


def long_report(a, rich=True):
    k = Kit(rich, "academic", title="Eastern Loop Heat Network Review", language="en")
    system = _bands(a).model_copy(update={"sections": {
        "annex": SectionBands(header=Band(rows=[BandRow(start=["Annexes"], end=["{title}"], rule_below=True)]))}})
    k.page_system(system)
    k.cover_page("Eastern Loop Heat Network Review", background_image=a["plant"], layout="centered",
                 subtitle="Three years of operation", date="2026")
    k.image_watermark(a["logo"], opacity=.06)
    for number, title in enumerate(("Network", "Plant", "Customers", "Losses", "Outlook"), start=1):
        k.heading(f"{number}. {title}", level=1)
        for j in range(4):
            k.paragraph(TOPICS["energy"])
            if j == 1:
                k.image(a["plant"] if number % 2 else a["dawn"], width=300, height=170, caption=f"{title} study",
                        figure_number=number, treatment=ImageTreatment(fit="cover"), alt_text=f"{title} illustration")
        k.heading(f"{title} detail", level=2)
        for _ in range(3):
            k.paragraph(TOPICS["energy"])
    k.page_section("annex")
    k.page_background(a["paper"], scope="sections", sections=["annex"], opacity=.6, alt_text="Paper texture")
    k.heading("Annex A: Substations", level=1)
    for _ in range(4):
        k.paragraph(TOPICS["energy"])
    return k


def image_failures(a, rich=True):
    """Missing, corrupted, oversized and low-resolution images, on the permissive policy."""
    k = Kit(rich, "modern_minimal", title="Image failure cases", language="en")
    k.b.quality("permissive")
    k.heading("Handling bad images", level=1)
    k.paragraph(TOPICS["harbour"])
    k.image(a["tiny"], width=420, caption="Low resolution: a warning, still placed", alt_text="tiny")
    k.paragraph(TOPICS["harbour"])
    k.image(a["corrupt"], caption="Corrupted file", alt_text="corrupt")
    k.paragraph(TOPICS["harbour"])
    k.image(a["huge"], caption="Over the pixel limit", alt_text="huge")
    k.paragraph(TOPICS["harbour"])
    k.image(a["harbour"] + ".missing", caption="Missing file", alt_text="missing")
    k.paragraph(TOPICS["harbour"])
    return k


def _hf_doc(k, topic="harbour", pages=3, text=None):
    for n in range(pages):
        k.heading(f"Section {n + 1}" if text is None else f"القسم {n + 1}", level=1)
        for _ in range(7):
            k.paragraph(text or TOPICS[topic])
    return k


def hf_simple(a, rich=True):
    k = Kit(rich, "modern_minimal", title="Simple header", language="en")
    k.page_system(PageSystem(header=Band(rows=[BandRow(left=["{title}"], right=["{date}"])]),
                             footer=Band(rows=[BandRow(center=["{page}"])]), values={"date": "November 2026"}))
    return _hf_doc(k)


def hf_dense_header(a, rich=True):
    k = Kit(rich, "corporate_dark", title="Quay Inspection Register", language="en")
    k.page_system(PageSystem(
        header=Band(rows=[
            BandRow(start=[Logo(src=a["logo"], max_height=22, alt_text="Authority logo"), "Saltmere Harbour Authority"],
                    center=["{title}", "{section}"], end=["{date}", "Page {page} of {pages}"], rule_below=True, size=8.5),
            BandRow(start=["Period: {period}"], center=["Engineering Department"], end=["Ref {code}"], size=7.5)],
            accent_color="#14607a", accent_height=3, bleed=True),
        footer=Band(rows=[BandRow(center=["{page}"])]),
        values={"period": "Q3 2026", "code": "SHA-ENG-0192", "date": "4 November 2026"}))
    return _hf_doc(k)


def hf_dense_footer(a, rich=True):
    k = Kit(rich, "government", title="Tenders Bulletin", language="en")
    k.page_system(PageSystem(
        header=Band(rows=[BandRow(left=["{title}"], right=["{section}"])]),
        footer=Band(rows=[
            BandRow(left=["Saltmere Harbour Authority", "12 Pier Road"], center=["CONFIDENTIAL", "Ref {code}"],
                    right=["Page {page} of {pages}", "{date}"], rule_below=True, size=8),
            BandRow(left=["tenders@saltmere.example"], center=["+000 555 0142"], right=["saltmere.example"], size=7)]),
        values={"code": "TB-26-11", "date": "November 2026"}))
    return _hf_doc(k)


def hf_odd_even(a, rich=True):
    k = Kit(rich, "academic", title="Tide Tables Handbook", language="en")
    k.page_system(PageSystem(
        header=Band(rows=[BandRow(right=["{chapter}"], rule_below=True)]),
        even_header=Band(rows=[BandRow(left=["{title}"], rule_below=True)]),
        footer=Band(rows=[BandRow(right=["{page}"])]),
        even_footer=Band(rows=[BandRow(left=["{page}"])]), first_page="same"))
    return _hf_doc(k, pages=4)


def hf_arabic(a, rich=True):
    k = Kit(rich, "government", title="دليل عمليات الميناء", language="ar")
    k.page_system(PageSystem(
        header=Band(rows=[BandRow(start=[Logo(src=a["logo"], max_height=20, alt_text="شعار")], center=["{title}"],
                                  end=["الإصدار الثالث"], rule_below=True)]),
        footer=Band(rows=[BandRow(start=["سري"], center=["هيئة ميناء سالتمير"], end=["صفحة {page} من {pages}"])])))
    return _hf_doc(k, text=ARABIC)


def hf_bilingual(a, rich=True):
    k = Kit(rich, "government", title="Port Operations Guide", language="en")
    k.page_system(PageSystem(
        header=Band(rows=[BandRow(left=["Port Operations Guide"], center=[Logo(src=a["logo"], max_height=20, alt_text="Logo")],
                                  right=["دليل عمليات الميناء"], rule_below=True)]),
        footer=Band(rows=[BandRow(left=["Saltmere Harbour Authority"], center=["{page}"], right=["هيئة ميناء سالتمير"])])))
    return _hf_doc(k)


def hf_cover_none(a, rich=True):
    k = Kit(rich, "corporate_dark", title="Cover Without Bands", language="en")
    k.page_system(_bands(a).model_copy(update={"first_page": "none"}))
    k.cover_page("Cover Without Bands", background_image=a["dawn"], layout="centered", subtitle="The bands start on page two")
    return _hf_doc(k, pages=2)


def hf_section(a, rich=True):
    k = Kit(rich, "data_report", title="Section Bands", language="en")
    k.page_system(_bands(a).model_copy(update={"sections": {
        "appendix": SectionBands(header=Band(rows=[BandRow(left=["Appendix"], right=["{title}"], fill="#14607a", size=9)],
                                             bleed=True),
                                 footer=Band(rows=[BandRow(center=["Appendix page {page}"])]))}}))
    _hf_doc(k, pages=2)
    k.page_section("appendix")
    k.heading("Appendix", level=1)
    for _ in range(5):
        k.paragraph(TOPICS["harbour"])
    return k


EXAMPLES = {
    "corporate_background": ("Corporate report, page background, transparent logo", corporate_background),
    "editorial_floats": ("Editorial report, floats with wrapped text", editorial_floats),
    "arabic_bilingual": ("Arabic and bilingual report, mirrored placement", arabic_bilingual),
    "financial_report": ("Financial report, tables, captions and imagery", financial_report),
    "long_report": ("Long report, repeated layers and section bands", long_report),
    "image_failures": ("Missing, corrupted, oversized and low-resolution images", image_failures),
    "hf_simple": ("Header 1: simple", hf_simple),
    "hf_dense_header": ("Header 2: dense header", hf_dense_header),
    "hf_dense_footer": ("Header 3: dense footer, three columns and a second line", hf_dense_footer),
    "hf_odd_even": ("Header 4: alternating odd and even pages", hf_odd_even),
    "hf_arabic": ("Header 5: Arabic RTL", hf_arabic),
    "hf_bilingual": ("Header 6: bilingual", hf_bilingual),
    "hf_cover_none": ("Header 7: cover without bands", hf_cover_none),
    "hf_section": ("Header 8: section-specific bands", hf_section),
}
