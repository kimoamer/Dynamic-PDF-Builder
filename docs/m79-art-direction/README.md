# M7.9: التوجيه الفني وتعدد التصاميم

كل المستندات هنا أصلية وخيالية، وصورها مولدة برمجيًا. لا يوجد في هذا المجلد أي عمل فني من المراجع التجارية.

## الاستخدام

```python
from dynamic_pdf.intelligence.variants import VariantBudget

result = builder.design_variants(
    n=3,                                  # من 1 إلى 5
    brand={"primary": "#0F5E73", "logo": "logo.png"},
    budget=VariantBudget(max_renders=40, max_refinements=5, max_seconds=120),
    office=False,                         # True يفتح كل DOCX في LibreOffice
)
result.recommended        # أقوى تصميم صالح، أو None
result.reasons            # لماذا اختير، ولماذا لم يُختر غيره
result.fallback           # True إذا رُفضت كل التصاميم: يبقى render() هو الناتج الثابت
result.export("out/")     # ملفات PDF وDOCX وdecisions.json
```

لا يتغير ناتج `render()` و`render_docx()` الافتراضي. `families=[...]` يحدد الاتجاهات بدل الاختيار التلقائي.

## النتيجة

| | |
|---|---|
| المستندات | 12 (منها 3 عربية أو ثنائية اللغة) |
| التصاميم المولدة | 36 |
| التي اجتازت البوابات | 36 |
| التوصيات | `financial_data` 5، `executive_premium` 2، `corporate_conservative` 2، `editorial_modern` 2، `arabic_institutional` 1 |
| زمن المستند الواحد | من 1.46 إلى 19.73 ثانية، الوسيط 6.215 (مع LibreOffice ورسم الصفحات) |
| ذروة ذاكرة Python | من 5.8 إلى 288.1 ميغابايت (tracemalloc، لا يشمل ذاكرة العمليات الخارجية) |
| LibreOffice | LibreOffice 24.2.7.2 420(Build:2) |
| Microsoft Word | **لم يُشغَّل: التوافق غير متحقق منه** |

الصفحات بصيغة PDF/DOCX. ★ التوصية.

| المستند | الأساس | التصاميم | ثوانٍ | ميغابايت |
|---|---|---|---|---|
| annual_report | 6/5 | executive_premium ★ 9/9، editorial_modern 6/6، financial_data 4/3 | 19.73 | 93.5 |
| financial_statements | 4/4 | financial_data ★ 3/3، corporate_conservative 5/5، executive_premium 5/5 | 8.22 | 21.8 |
| board_paper | 2/2 | corporate_conservative ★ 2/2، financial_data 2/2، executive_premium 2/2 | 1.46 | 5.8 |
| technical_manual | 4/3 | financial_data ★ 3/3، corporate_conservative 5/4، executive_premium 5/5 | 5.84 | 42.5 |
| research_paper | 3/3 | corporate_conservative ★ 4/4، financial_data 3/2، executive_premium 5/5 | 6.11 | 8.7 |
| proposal | 4/3 | editorial_modern ★ 3/3، executive_premium 4/4، corporate_conservative 5/4 | 6.32 | 40.0 |
| impact_report | 4/4 | editorial_modern ★ 4/3، executive_premium 5/4، corporate_conservative 5/5 | 11.67 | 68.9 |
| policy_brief | 2/2 | corporate_conservative 3/2، financial_data ★ 2/2، editorial_modern 3/2 | 5.74 | 15.8 |
| arabic_annual | 4/4 | arabic_institutional 6/6، executive_premium ★ 8/8، editorial_modern 6/6 | 14.12 | 288.1 |
| arabic_financial | 2/2 | arabic_institutional 2/3، financial_data ★ 2/2، corporate_conservative 3/4 | 4.56 | 7.6 |
| bilingual_institutional | 3/3 | arabic_institutional ★ 3/3، executive_premium 3/3، corporate_conservative 4/4 | 5.24 | 114.3 |
| sustainability_report | 4/3 | financial_data ★ 3/3، executive_premium 5/5، editorial_modern 4/4 | 10.52 | 59.4 |

المعرض الكامل، وفيه كل صفحات كل مستند قبل وبعد مع ملفات PDF وDOCX، موجود محليًا في
`D:\Packages\M79_Art_Direction_Review\index.html`. ولإعادة توليده:

```bash
python benchmarks/m79/run.py OUT_DIR --keep-files
```

البيانات الكاملة في [results.json](results.json). مثالان كاملان، الصف الأول هو الأساس:
[annual_report](before-after-annual_report.jpg) و[arabic_annual](before-after-arabic_annual.jpg).

## ما الذي تغيّر بصريًا

هذه ملاحظات مراجع آلي (Claude) بعد مشاهدة صفحات كل المستندات بدقة منخفضة، وليست حكمًا بشريًا. لم يراجعها أي إنسان بعد.
الملاحظات لكل تصميم في [assessments.json](../../benchmarks/m79/assessments.json).

- **الأساس:** كل المستندات تبدو واحدة: شريط برتقالي، تذييل أسود، رسوم بألوان متعددة، حرف استهلالي في كل قسم، ولا غلاف.
- **بعد M7.9:** لكل اتجاه غلاف وعناوين وترويسة وكثافة ومعالجة صور خاصة به، ويبقى ثابتًا داخل المستند.
- الفرق بين التصاميم واضح في بنية الصفحة، لا في اللون فقط. يسجل `differs_from` في results.json جوانب الاختلاف.

### تراجعات ونقاط ضعف ما زالت موجودة

- **صفحات أخيرة شبه فارغة:** `policy_brief` (corporate وeditorial) و`proposal` (corporate). حاول التحسين المحدود ولم ينجح، لأن الصفحة السابقة ممتلئة.
- **صفحة 4 في `arabic_annual` editorial** فيها ثلاثة أسطر. جُرّب التغيير وتراجع عنه النظام لأن المؤشر انخفض.
- **تضخم الصفحات:** `executive_premium` يصل إلى ضعف صفحات الأساس في `arabic_annual`. ما زال مقبولًا لكنه قد لا يناسب كل قارئ.
- **`research_paper`:** عنوان References مكرر. مصدره بنية المستند نفسه، وهو موجود في الأساس أيضًا.
- **قص صورة `annual_report` editorial:** يقتطع أعلى القمر قليلًا.
- **DOCX:** الأشرطة العربية داخل الهوامش لا تمتد إلى حافة الصفحة كما في PDF، وبعض المستندات تختلف بصفحة بين PDF وLibreOffice.
- **الترقيم في العربية:** الرقم يقع في الطرف الخطأ من العنوان في ميزة الترقيم الموجودة سابقًا. تجنبته الاتجاهات بعدم الترقيم في RTL، لكن الميزة نفسها لم تُصلَح.
- **الخطوط:** الخطوط المضمنة Amiri وJetBrains Mono فقط، لذلك تختلف التصاميم العربية في التكوين لا في نوع الخط.
- **`n=5` للمستندات اللاتينية** يعطي 4 تصاميم، لأن الاتجاه العربي لا يُعرض إلا لمستند RTL أو ثنائي اللغة.
- **درجة `index`** مقياس للترتيب من قياسات الصفحات، وليست تقييمًا جماليًا. قد يخالف حكم إنسان.

## عيوب كشفتها مشاهدة الصفحات فقط

- عناوين DOCX البيضاء لم تكن مرئية في LibreOffice، لأنه تجاهل التظليل المباشر على نمط العنوان. اجتازت كل الفحوص الآلية. الإصلاح: نمط فقرة `Heading N Band`.
- عناوين DOCX كانت تلتف بجانب الصورة العائمة. الإصلاح: فاصل `w:clear="all"` قبل العنوان التالي.
- رقم لاتيني في الطرف الخطأ من العناوين العربية.
- صفحة رسم وحيدة في `annual_report` editorial، بعد أن كان الفحص يعدّها مقصودة.

## مبادئ الأطلس المتاحة وقت التشغيل

لا يقرأ وقت التشغيل ملفات الأطلس. المبادئ مكتوبة قواعدَ في الكود، ولا يستورد `dynamic_pdf` شيئًا من `tools`.
981 صفحة من 1,064 لم تُر إلا ضمن لوحات مصغرة، فالأدلة عليها أضعف.

| المبدأ | الحالة | أين |
|---|---|---|
| شيء واحد يملأ الصفحة | متاح | `statement` و`performance_page` |
| إبراز الفترة الحالية باللون أو الحجم | متاح | آخر عمود في الرسوم، `current_col` في الجداول |
| ذكر الأرقام مرة واحدة في الثنائي اللغة | جزئي | لا تكرار من التصميم، لكن لا دمج لما كرره الكاتب |
| تعليق النص من خط عمودي ثابت | متاح | عناوين `hang` |
| الفراغ المقصود فوق الكتلة | متاح | `drop` |
| قاعدة أو تظليل واحد للتجميع | متاح | جداول ledger وعناوين `rule` |
| عكس الصفحة كاملة للعربية | متاح | الهوامش والأشرطة في RTL |
| تكرار نظام هادئ | متاح | `PageSystem` لكل اتجاه |

| النمط | الحالة |
|---|---|
| `asymmetric_opener`، `performance_page`، `parallel_ledger` | موجود من قبل، ومستخدم الآن |
| `statement_page` | أضيف في M7.9 |
| `image_slab_divider` | جزئي: شريط الصورة فقط |
| `editorial_sink`، `figure_matrix` | **غير منفذ** |

## البوابات

يُرفض التصميم عند فقد نص أو رقم أو تغييره أو إضافة نص، وعند فشل فحوص PDF وDOCX والوسائط، وعند القص أو العناوين اليتيمة أو الهندسة غير الآمنة.
القياسات الجمالية منفصلة عنها ولا ترفض تصميمًا. لم يُرفض أي تصميم في هذا التشغيل، لذا تثبت الاختبارات الرفض بأعطال مقصودة في `tests/test_m79_art_direction.py`.
