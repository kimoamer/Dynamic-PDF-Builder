"""Agent-authored editorial atlas exercised through the real Dynamic-PDF-Builder MCP server.
The script runs deterministic tool calls; ChatGPT is the editorial decision maker.
"""
import anyio, json, re, sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from render_gha import parse_sections, LATLON, create_locator

BASE=Path(__file__).resolve().parent
OUT=BASE/"mcp_agent_results"
REGIONS=[
 (9,23,"جغرافيا البحر الأحمر وأحواضه"),
 (24,41,"الموائل البحرية والشعاب المرجانية"),
 (42,54,"التاريخ والتراث على ضفتي البحر"),
 (55,68,"الساحل المصري وسيناء"),
 (69,78,"المدن والمرافئ السعودية"),
 (79,92,"مدن العقبة والضفة الأفريقية واليمن"),
 (93,105,"القناة والموانئ والتجارة"),
 (106,119,"المخاطر البيئية وإدارة السواحل"),
 (120,125,"السياسات ومستقبل المدن الساحلية")
]
OPENERS=[
 "الموقع والتكوين الجيولوجي والخلجان والمضائق عوامل مترابطة؛ لا يصح استنتاج ظروف مدينة من متوسط الحوض كله.",
 "تتصل الشعاب المرجانية بالأعشاب والمانجروف والصيد والسياحة، وتتفاوت آثار الحرارة والتلوث بين المواقع.",
 "التراث هنا شبكة طرق ومرافئ ومجتمعات حرفية، لا مبانٍ منفصلة عن البحر والتبادل التاريخي.",
 "تختلف أولويات المدن المصرية بين خدمات القناة والصناعة والسياحة وصون الشعاب والخدمات المحلية.",
 "تجمع السواحل السعودية أرخبيلات ومرافئ ومراكز حضرية؛ تحتاج كل منطقة أدوات قياس واستدامة ملائمة.",
 "تجاور المدن البحر نفسه مع اختلاف أدوار الموانئ والسياقات الاجتماعية؛ هذه قراءة جغرافية وليست دليل سفر آنيًا.",
 "يتغير عدد السفن نتيجة التجارة والأمن البحري؛ لا يجوز الخلط بين العبور والحمولة والقيمة المحلية.",
 "الاحترار والصرف والتصريف الملحي والتآكل تحديات متقاطعة، ويجب مراقبة كلٍّ منها بمؤشرات محددة.",
 "المقترحات أدناه تحليلية وليست قرارات أو التزامات صادرة عن أي حكومة."
]
MAP_CITIES={"السويس","الغردقة","شرم الشيخ","ينبع","جدة","العقبة","بورتسودان","مصوع","الحديدة"}
def compose(sections,max_entries=None):
    md=["---","title: 'البحر الأحمر | أطلس المدن والطبيعة'","language: ar","direction: rtl",
        "document_type: executive_report","audience: researchers and planners","theme: magazine",
        "cover: centered","cover_color: '#113849'","header: modern","numbering: true",
        "---","","# البحر الأحمر: مدن ومياه وذاكرة مشتركة",
        "قراءة تحليلية مستقلة لشواطئ البحر الأحمر ومدنه وموانئه ونظمه البيئية. الخرائط توضيحية وغير صالحة للملاحة.",
        "","[TOC]","","# منهجية البحث",
        "يُفصل في هذه النسخة بين الرقم المنشور والاستنتاج التحريري والتوصية؛ كل بيانات الملاحة تقترن بمصدرها وسنتها.",
        ""]
    used=0
    for ix,(a,b,title) in enumerate(REGIONS):
        md.extend(["# "+title,OPENERS[ix],""])
        for n in range(a,b+1):
            if max_entries and used>=max_entries: break
            heading,paragraphs=sections[n-1]
            md.extend(["## "+heading,""])
            if heading in MAP_CITIES:
                img=create_locator(heading,LATLON[heading])
                md.extend(["![الموقع التقريبي لمدينة "+heading+"]("+str(img)+' "خريطة توضيحية غير ملاحية")',""])
            for p in paragraphs:
                if p.startswith("المراجع:"):
                    keys=re.findall(r"S\d+",p)
                    if keys:md.extend(["**المراجع:** "+", ".join(keys),""])
                elif p.startswith("ملاحظة منهجية:"):
                    md.extend(["**حدود التفسير:** "+p.split(":",1)[1].strip(),""])
                else:md.extend([p,""])
            if n==95:
                tick=chr(96)*3
                md.extend(["### قناة السويس بالأرقام","","طبقًا للتقرير السنوي الرسمي انخفض عدد السفن العابرة من 13,213 في 2024 إلى 12,758 في 2025، أي 3.4٪.",
                  tick+"chart {#fig-suez}",
                  '{"type":"bar","title":"عبور السفن في قناة السويس","data":{"2024":13213,"2025":12758},"y_label":"سفينة"}',
                  tick,"",
                  "| المؤشر | 2024 | 2025 |","|---|---:|---:|",
                  "| السفن العابرة | 13,213 | 12,758 |",
                  "**الحمولة الصافية:** 524.5 مليون طن في 2024، و522.1 مليون طن في 2025 وفق التقرير الرسمي؛ وهي مقياس مختلف عن عدد السفن.","",
                  "Table: إحصاءات قناة السويس الرسمية 2025 مقارنة بـ2024 {#tab-suez}","",
                  "[المصدر: الهيئة](https://www.suezcanal.gov.eg/English/Downloads/DownloadsDocLibrary/Navigation%20Reports/Annual%20Reports%E2%80%8B%E2%80%8B%E2%80%8B/2025.pdf)",""])
            used+=1
        if max_entries and used>=max_entries:break
    if max_entries is None:
        md.extend(["# المراجع الأصلية",""])
        for _,paras in sections[127:129]:
            for p in paras:
                for line in p.splitlines():
                    if re.match(r"\[S\d+\]",line):md.extend(["- "+line,""])
    return "\n".join(md)

def decoded(result):
    if result.is_error:raise RuntimeError(result.content[0].text[:700])
    s=result.content[0].text
    try:return json.loads(s)
    except ValueError:return s

def geometry(path):
    import fitz
    from PIL import Image,ImageDraw
    doc=fitz.open(path);rows=[];thumbs=[]
    for i,p in enumerate(doc):
        t=p.get_text();imgs=len(p.get_images());bad=sum(
            1 for b in p.get_text("blocks") if len(b)>=7 and b[6]==0 and
            (b[0]<-1 or b[1]<-1 or b[2]>p.rect.width+1 or b[3]>p.rect.height+1))
        rows.append({"page":i+1,"chars":len(t),"images":imgs,"outside":bad})
        if i % max(1,len(doc)//16)==0 or i==len(doc)-1:
            pix=p.get_pixmap(matrix=fitz.Matrix(.75,.75),alpha=False)
            im=Image.frombytes("RGB",[pix.width,pix.height],pix.samples)
            im.thumbnail((224,315));tile=Image.new("RGB",(250,350),"#edf2f2")
            tile.paste(im,((250-im.width)//2,4));ImageDraw.Draw(tile).text((9,326),str(i+1),fill="#183944")
            thumbs.append(tile)
    grid=Image.new("RGB",(1250,350*((len(thumbs)+4)//5)),"#edf2f2")
    for i,t in enumerate(thumbs):grid.paste(t,((i%5)*250,(i//5)*350))
    grid.save(OUT/"contact_sheet.jpg",quality=91)
    return {"page_count":len(doc),"median_chars":sorted(x["chars"] for x in rows)[len(doc)//2],
            "empty_or_sparse":[x["page"] for x in rows if x["chars"]<260 and x["images"]==0],
            "outside":sum(x["outside"] for x in rows),"page_details":rows}

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sections=parse_sections((BASE/"content_ar.md").read_text(encoding="utf-8"))
    full=compose(sections);pilot=compose(sections,6)
    (OUT/"agent_authored.md").write_text(full,encoding="utf-8")
    trace={"content_units":len(sections),"units_under_500_chars":sum(len(" ".join(p))<500 for _,p in sections),
           "imposed_page_breaks":0,"decisions":"Editorial semantic chapters, selective city maps, sourced chart; natural pagination.",
           "steps":[]}
    params=StdioServerParameters(command=sys.executable,cwd=str(BASE.parents[1]),
                args=["-m","dynamic_pdf.ai.mcp_server","--out-dir",str(OUT)])
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            info=await client.initialize();names={t.name for t in (await client.list_tools()).tools}
            expected={"guide","schema","lint","explain","variants","review","render","kit"}
            assert expected<=names,expected-names
            trace["discovery"]={"tools":sorted(names),"instructions":info.instructions[:250]}
            async def call(name,payload):
                try:
                    value=decoded(await client.call_tool(name,payload))
                    trace["steps"].append({"name":name,"ok":True,
                        "pages":value.get("pages") if isinstance(value,dict) else None,
                        "status":value.get("status") if isinstance(value,dict) else None})
                    return value
                except Exception as error:
                    trace["steps"].append({"name":name,"ok":False,"error":str(error)[:400]})
                    # The agent acts on the MCP refusal contract, not on an invented API.
                    # A direction id is not a document type: retry the supported "auto" mode.
                    if payload.get("design") == "editorial_modern" and ("Unknown document type" in str(error)):
                        trace.setdefault("recoveries",[]).append({
                            "tool":name,"reason":"art-direction id was passed to document-type parameter",
                            "fix":"design=auto; retain Arabic profile through content metadata and variant review"})
                        return await call(name,{**payload,"design":"auto"})
                    return {"error":str(error)[:900]}
            for topic in ("markdown","arabic","design","review-and-changes"):await call("guide",{"topic":topic})
            await call("schema",{})
            trace["variants"]=await call("variants",{"markdown":pilot,"n":2,"folder":"design_variants"})
            trace["recommended_design"]=trace["variants"].get("recommended") if isinstance(trace["variants"],dict) else None
            trace["selection_note"]="MCP render does not accept variants direction ids in its design parameter; use auto and review chosen outcome."
            trace["lint"]=await call("lint",{"markdown":full})
            trace["design_explain"]=await call("explain",{"markdown":full,"design":"editorial_modern"})
            trace["pdf_review"]=await call("review",{"markdown":full,"design":"editorial_modern","folder":"review_pdf","dpi":60})
            trace["pdf"]=await call("render",{"markdown":full,"design":"editorial_modern","filename":"RedSea_Agent.pdf"})
            trace["word"]=await call("render",{"markdown":full,"design":"editorial_modern","filename":"RedSea_Agent.docx"})
            trace["docx_review"]=await call("review",{"markdown":full,"design":"editorial_modern","format":"docx","folder":"review_docx","dpi":60})
    if (OUT/"RedSea_Agent.pdf").exists():trace["external_qa"]=geometry(OUT/"RedSea_Agent.pdf")
    qa=trace.get("external_qa",{})
    trace["accepted_130"]=125<=qa.get("page_count",0)<=135 and qa.get("median_chars",0)>=900 and len(qa.get("empty_or_sparse",[]))<=5
    trace["acceptance"]="PASS" if trace["accepted_130"] and trace["pdf"].get("status")=="ok" and trace["word"].get("status")=="ok" else "NEEDS_REVISION"
    (OUT/"trace.json").write_text(json.dumps(trace,ensure_ascii=False,indent=2)[:150000],encoding="utf-8")
    print(json.dumps({"acceptance":trace["acceptance"],"pages":qa.get("page_count"),"short_units":trace["units_under_500_chars"],"steps":trace["steps"]},ensure_ascii=False),flush=True)
    if trace["acceptance"]!="PASS":raise SystemExit("QUALITY_GATE_FAILED: content insufficient or unverified; no fake 130-page success")
if __name__=="__main__":anyio.run(main)
