"""Six fictional, deterministic comparison fixtures. No real client information."""
from pathlib import Path
from PIL import Image, ImageDraw
from dynamic_pdf import DocumentBuilder
from dynamic_pdf.schema.page_system import Band, BandRow, Logo, PageSystem

EN = ("The operations team inspected the production line and recorded each maintenance task. "
      "The inspection links the image to the work described in this section. Equipment settings, "
      "staff training and quality checks remain in the original record. The next review will "
      "compare these observations with the approved schedule and the measured output.")
AR = ("رَاجَعَ فَرِيقُ التَّشْغِيلِ خُطَّةَ الْإِنْتَاجِ وَسَجَّلَ نَتَائِجَ الْفَحْصِ. "
      "توضح الصورة حالة المعدات المرتبطة بهذا القسم، وتظل جميع الملاحظات جزءًا من التقرير. "
      "يشمل التقييم إجراءات الصيانة وتدريب العاملين ومراجعة الجودة، مع الحفاظ على ترتيب "
      "البيانات والأرقام دون حذف أو تغيير. بلغت الكمية المسجلة 1250 وحدة خلال الفترة.")


def assets(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    paths={k:str(folder/(k+".png")) for k in ("portrait","wide","screenshot","tiny","logo")}
    for name,size in [("portrait",(1200,1500)),("wide",(1800,800))]:
        im=Image.new("RGB",size,"#edf2f3");d=ImageDraw.Draw(im);w,h=size
        d.rectangle((0,h*.6,w,h),fill="#d7e3de")
        for j in range(3):
            x=w*(.1+.28*j)
            d.rounded_rectangle((x,h*.2,x+w*.2,h*.77),radius=18,fill=["#506f80","#73938b","#b5b4a5"][j])
            d.rectangle((x+w*.04,h*.28,x+w*.16,h*.36),fill="#ebf1ed")
        im.save(paths[name],dpi=(180,180))
    im=Image.new("RGB",(1600,900),"white");d=ImageDraw.Draw(im)
    d.rectangle((40,40,1560,100),fill="#dfe8ee")
    for y in range(150,850,100):
        d.line((40,y,1560,y),fill="#95a3af",width=2)
        for x in range(60,1500,240):d.text((x,y+30),f"{x//60:02}   {y*2}",fill="#182e40",font_size=26)
    im.save(paths["screenshot"],dpi=(200,200))
    im=Image.new("RGB",(90,60),"#416b77");im.save(paths["tiny"])
    im=Image.new("RGBA",(400,100),(0,0,0,0));d=ImageDraw.Draw(im)
    d.rectangle((10,10,90,90),fill="#2c6372");d.text((110,20),"FIELD LAB",fill="#2c6372",font_size=40)
    im.save(paths["logo"])
    return paths


def image(b,src,kind="unknown",caption="Inspection record",**hints):
    b.image(src,caption=caption,alt_text=caption,source="Fictional test fixture")
    b._blocks[-1].hints={"media_kind":kind,**hints}


def make_case(name,a):
    ar=name=="arabic_dense_bands"
    profile={"executive_narrative":"executive_report","technical_figure":"technical_manual",
             "arabic_dense_bands":"executive_report","near_page_end":"proposal",
             "short_bilingual":"letter","low_dpi":"corporate_memo"}[name]
    b=DocumentBuilder(theme="modern_minimal")
    b.meta(title="تقرير متابعة التشغيل" if ar else name.replace("_"," ").title(),
           language="ar" if ar else "en")
    b._meta.document_type=profile
    b._meta.direction="rtl" if ar else "ltr"
    b.design(profile)
    b.heading("مراجعة التشغيل" if ar else "Operations review",level=1)
    if name=="executive_narrative":
        b.paragraph(EN)
        image(b,a["portrait"],"photo")
        for _ in range(9):b.paragraph(EN)
    elif name=="technical_figure":
        b.paragraph(EN)
        image(b,a["screenshot"],"screenshot",min_display_width=350)
        b.paragraph(EN)
        b.table(["Step","Action","Check"],[[str(i),"Inspect equipment","Record result"] for i in range(1,9)])
    elif ar:
        b.page_system(PageSystem(
            header=Band(rows=[
                BandRow(start=[Logo(src=a["logo"],max_height=19,alt_text="شعار اختباري")],
                        center=["{title}"],end=["FIELD LAB 2026"],size=10,rule_below=True),
                BandRow(start=["قسم الإنتاج ومتابعة التشغيل"],end=["{period}"],size=10),
                BandRow(start=["{company}"],end=["{department}"],size=10),
                BandRow(start=["تقرير داخلي للمراجعة والمتابعة"],end=["{code}"],size=10)]),
            footer=Band(rows=[BandRow(start=["العنوان الرئيسي للمصنع"],end=["صفحة {page} من {pages}"],size=9),
                              BandRow(start=["{website}"],end=["{email}"],size=9),
                              BandRow(start=["مراجعة الإدارة المختصة"],end=["{phone}"],size=9)]),
            values={"period":"نوفمبر 2026","company":"شركة الاختبارات الصناعية",
                    "department":"إدارة الجودة","code":"QA-2026-011", "website":"example.test",
                    "email":"qa@example.test","phone":"010 000 0000","date":"2026-11-05"}))
        b.paragraph(AR)
        image(b,a["portrait"],"photo",caption="صورة المعدات في منطقة التشغيل")
        for _ in range(7):b.paragraph(AR)
    elif name=="near_page_end":
        for _ in range(4):b.paragraph(EN)
        image(b,a["portrait"],"photo")
        for _ in range(5):b.paragraph(EN)
    elif name=="short_bilingual":
        b.paragraph("A short inspection note accompanies the following equipment image.")
        image(b,a["wide"],"photo",caption="معدات التشغيل  Equipment view")
        b.paragraph("تمت مراجعة المعدات واعتماد الملاحظات الواردة في سجل الفحص.")
        b.paragraph("Reference 1250 / November 2026.")
    elif name=="low_dpi":
        b.paragraph(EN)
        image(b,a["tiny"],"photo")
        for _ in range(3):b.paragraph(EN)
    return b


CASES=("executive_narrative","technical_figure","arabic_dense_bands",
       "near_page_end","short_bilingual","low_dpi")
