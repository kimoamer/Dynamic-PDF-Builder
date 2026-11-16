# Review and plan: a more advanced, more intelligent Dynamic PDF Builder

- **Repository:** `kimoamer/Dynamic-PDF-Builder`
- **Reviewed revision:** `001ec36` (`main`, the merge of PR #25)
- **Date:** 2026-11-13
- **Status:** M8 to M15 implemented on 2026-11-16; section 5a says which "Done when" targets are met and what blocks the rest.
- **Verified on:** Linux, Python 3.13.18, ReportLab 5.0.1, PyMuPDF 2.1, LibreOffice. Microsoft Word, Playwright and LightGBM were not available.

## 1. Summary

Dynamic PDF Builder turns Markdown, JSON or a fluent API into a designed PDF and an editable DOCX from one semantic document. Since v0.3 it has gained a design layer, a layout optimizer, five art directions, a design grammar, visual QA and a learning pipeline: about 45,000 lines of Python and 930 tests.

Three facts describe where it stands.

1. **The guard rails are strong.** A content ledger and hard gates reject any design that loses, adds or reorders the author's words. Failures are typed and fail closed, every decision is explained, and AI judgments are never recorded as human ones. The plan keeps all of this.
2. **The intelligence is rule tables and fixed weights.** Document type, purpose, direction fit, section roles, scores and the final recommendation come from regexes, lookup tables and hand-set coefficients (section 2). Nothing learned or model-based runs: no ranker has been trained, and the data cannot train one yet.
3. **The baseline is broken and nothing reports it.** CI has not executed on `main` since 4 November. On today's `main`, 35 tests fail and 4 error. At the commit before the last three merges, 2 fail. The last merge gave every art direction the same type sizes and nearly the same margins, and one of the five directions can no longer pass the gates.

So the plan starts by restoring a baseline that can be trusted (M8) and one measurable engine (M9). It then adds intelligence in four directions: understanding content (M10), searching instead of following fixed ladders (M11), learning from evidence (M12) and an optional, gated AI layer (M13). Two parallel tracks deepen the rendering (M14) and the product surface (M15).

## 2. How decisions are made today

```text
Markdown / JSON / fluent API
  -> SemanticDocument (normalize)
  -> profile -> recipe -> theme tokens -> layout plan        design("auto")
  -> candidates -> simulate -> render <=3 -> score -> repair   compose("smart")
  -> 5 directions -> render -> critique -> refine -> gates     design_variants()
  -> PDF (ReportLab) + DOCX (python-docx) -> QA (PyMuPDF, LibreOffice)
```

| Decision | How it is made | Where |
| --- | --- | --- |
| Document type, 10 profiles | Keyword regexes and block counts with fixed points | `dynamic_pdf/design/profile.py:62` |
| Purpose and audience, 11 purposes | Regex on the title, then a lookup table | `dynamic_pdf/design/art_direction.py:37` |
| Which art direction fits | Static fit table plus six if-rules | `dynamic_pdf/design/art_direction.py:54` |
| Section role | Regex on the heading plus word and exhibit counts | `dynamic_pdf/design/art_direction.py:190` |
| Layout candidates | Five fixed transforms | `dynamic_pdf/intelligence/candidates.py:107` |
| Layout score | Seven fixed weights | `dynamic_pdf/intelligence/scoring.py:26` |
| Visual index | Six fixed coefficients over a 24 x 34 ink grid drawn at 36 dpi | `dynamic_pdf/qa/visual_critique.py:20` |
| Recommendation | `fit * 6 + index` | `dynamic_pdf/intelligence/variants.py:386` |
| Refinement | A fixed ladder of adjustments | `dynamic_pdf/intelligence/variants.py:155` |
| Page forecast | Greedy simulation | `dynamic_pdf/intelligence/analysis.py:151` |
| Learned ranking | None: no model exists | `MODEL_TRAINING_AUDIT.md` |

Worth protecting: the content ledger and hard gates, strict and permissive error policy, `design_explain()` and `decisions.json`, the separation of AI and human labels, one semantic document for both formats, and the asset, SVG and Mermaid security rules.

## 3. Findings

### 3.1 Verified in this review

| # | Finding | Evidence |
| --- | --- | --- |
| F1 | **CI is not running.** The six most recent runs on `main` (PR #16 on 5 Nov to PR #25 on 7 Nov) each failed within five seconds. In the latest one, every job ended three seconds after it was created, with no runner assigned and no log. That points at an account or repository Actions setting such as billing, not at the tests. The cause is not visible through the API. The last run that executed is run 49 on 4 Nov. | GitHub Actions run 42360133628 and its four jobs |
| F2 | **`main` fails its own tests.** 891 passed, 35 failed, 4 errors. The same suite at `ef0643f`, the commit before PRs #23 to #25, in the same environment: 917 passed, 3 failed, and one of those three fails only because the comparison copy was not a git checkout. So 37 of the 39 arrived with PRs #23 to #25. | `python -m pytest -q`, 5 min 38 s; the appendix lists the tests |
| F3 | **The reviewed-quality layer flattens the five directions and breaks one.** `apply_reviewed_quality` sets one set of type sizes per script for every designed output and clamps all margins to 64 to 80 pt, after the direction's own recipe has been applied. On a multi-section proposal, four directions that specify an H1 of 16 to 30 pt all rendered no heading larger than 17 pt, and `financial_data`, which specifies 9.6 pt body text, rendered 11.5 pt. `editorial_modern` hangs headings 96 pt into a start margin designed at 150 pt, so its headings now start 10 pt left of the page edge and the clipping gate rejects it: in 3 of 3 fixtures where it was a candidate and in six tests. Evidence recipes can no longer change size, ramp or columns (seven tests). | `dynamic_pdf/design/reviewed_quality.py:49-66`, `dynamic_pdf/design/art_direction.py:680`, `dynamic_pdf/design/directions.py:85-88` |
| F4 | **Explanations no longer match the page.** `plan.typography` reports the direction's intended type, for example "Barlow 9.6/1.36", while the page carries 11.5 pt. The variant ranker reads its `base_size` and `line_height` features from that string. | `dynamic_pdf/design/art_direction.py:691`, `dynamic_pdf/intelligence/variant_ranker.py:37,53` |
| F5 | **Two optimizers that share nothing, and the stronger one is hard to reach.** `compose("smart")` and `design_variants()` have separate scores, separate rankers (10 and 22 features) and separate budgets. The dataset also records 28 measured layout facts for each candidate, and the trainer reads none of them. `export()` and the CLI cannot produce art-directed variants or use the grammar. | `dynamic_pdf/builder.py:185,347`, `dynamic_pdf/cli.py`, `tools/design_learning/layout_facts.py:123`, `scripts/train_variant_ranker.py:71` |
| F6 | **The page forecast is noisier than the thresholds it feeds.** Over 17 documents the simulator got the page count right in 15. Its predicted score differed from the rendered score by 4.1 points on average and 17.0 at most. A candidate is rendered on a predicted gain of 0.25 and preferred on a gain of 1.0. Simulated regions always span the full frame width, and utilization was over-predicted in 13 of the 17. | `dynamic_pdf/intelligence/analysis.py:210-231`, `dynamic_pdf/intelligence/composer.py:180,42` |
| F7 | **Content is counted, not understood.** A "Fiscal year" column is classified as a numeric measure and right-aligned, and the ledger rule that should tint the current period tints that year column. Default `export()` gives a four-heading manual whose content fits on one page a contents page of its own. `meta.audience` is accepted and never read. | `dynamic_pdf/design/planner.py:147-153`, `dynamic_pdf/design/art_direction.py:395`, `dynamic_pdf/design/recipes.py:84`, `dynamic_pdf/schema/document.py:22` |
| F8 | **A known Markdown defect is still open.** Two consecutive footnote definitions merge into one, and the internal marker is printed: "1 First note. IFNDEFI2: Second note." | `dynamic_pdf/markdown/parser.py:59,119` |
| F9 | **PDFs are untagged.** The catalog has `/Lang` and an outline but no `/MarkInfo` or `/StructTreeRoot`, so alt text and reading order do not reach assistive technology. | Probe with pikepdf |
| F10 | **Arabic text is stored as presentation forms.** Extracted text held 43 presentation-form characters and no base Arabic letters. A verbatim search for the source phrase fails and matches only after NFKC normalization. ReportLab 5.0.1 has an optional HarfBuzz shaping path (`uharfbuzz`) that the library does not use. | `dynamic_pdf/layout/factory.py:57-79`; ReportLab 5.0.1 `pdfbase/ttfonts.py:1442` |
| F11 | **Justified text is never hyphenated.** 0 of 70 lines broke at a hyphen in a paragraph of long words. `pyphen` is a core dependency, and ReportLab uses it only when a style sets `hyphenationLang`, which nothing does. | ReportLab 5.0.1 `platypus/paragraph.py:2103` |
| F12 | **Output is not reproducible byte for byte.** The same document rendered twice gives different SHA-256 values for both PDF and DOCX. The preference dataset uses those hashes as its record of what was judged. | Probe, two renders two seconds apart |
| F13 | **Variant rendering repeats work.** Each variant render builds a `LayoutEngine` without the figure cache the composer passes. Each variant's PDF is then opened at least four times and rasterized up to twice. | `dynamic_pdf/intelligence/variants.py:229,283-289`, `dynamic_pdf/intelligence/composer.py:143` |
| F14 | **`stream()` does not stream.** It buffers the chunks and renders once at close with the classic theme, without design or policy. | `dynamic_pdf/streaming.py:5-35` |
| F15 | **Packaging and documentation have drifted.** The version is 0.3.0 in three places. The README says fonts are downloaded on first run and also that they never are, lists two bundled fonts of 45 families, and its changelog still claims "120+ test cases, 100% pass rate". 33 `.pyc` files are tracked. The learning config holds `D:/` paths, and one test asserts that they are absolute, which only holds on Windows. | `pyproject.toml:7`, `dynamic_pdf/__init__.py:35`, `dynamic_pdf/cli.py:164`, `README.md:953,1003,1341,1370`, `config/design-learning.json`, `tests/test_m77_design_grammar.py:376` |
| F16 | **The intelligent paths depend on an AGPL package.** QA, the composer's inspection, the visual critique and the variant gates all read pages through PyMuPDF. Without it their results are reported as unverified. | `pyproject.toml:45` |

### 3.2 From the repository's own reports, not re-measured

| # | Finding | Source |
| --- | --- | --- |
| R1 | No model exists. 85 usable comparisons against a gate of 200, 23 held out, 14 Arabic, 17 bilingual, 34 judged in Word, no human audit. One AI reviewer, 18 fictional documents by one author sharing five pictures. | `docs/m710-design-quality/dataset-readiness.md`, `docs/reference-learning-bridge.md` |
| R2 | Word lags PDF: 10 to 11 of 48 designs end on a near-empty page in Word against 2 in PDF, and 5 to 6 differ in page count. | `docs/m710-design-quality/README.md` |
| R3 | Smart composition costs a median 2.3 times the baseline render, 4.1 times at most, when it changes nothing. | `benchmarks/m7/FINDINGS.md` item 9 |
| R4 | Long documents waste space: 9 of 20 handbook body pages are under 60% full. | `benchmarks/m7/FINDINGS.md` item 10 |
| R5 | Matplotlib and its dependencies are 122.5 MB of a 182.9 MB core install. Bundled fonts add about 17 MB to the wheel. | `benchmarks/m7/FINDINGS.md` item 11, `docs/m710-design-quality/README.md` |
| R6 | Chart defects and table fitting around inline code were reported and not re-checked here. | `benchmarks/m7/FINDINGS.md` items 5 and 7 |

## 4. Rules the plan keeps

1. Author content is never altered. Anything learned or model-based only chooses among designs, and the hard gates decide which designs are valid.
2. The default path stays offline, deterministic and CPU-only. Anything that calls a model is opt-in and named by the caller.
3. A claim that the engine got smarter needs a number on held-out documents.
4. One engine, one set of measured facts, one scoreboard.

Not in this plan:

- Training a ranker on the current 85 comparisons.
- Layout generated freely by a model, or body text written by one.
- Another benchmark script or gallery for each milestone, outside the scoreboard.
- A second PDF backend before the M14 spike reports.

## 5. Roadmap

Sizes are rough estimates for one engineer: S is up to a week, M two to three weeks, L four to six weeks. Numbers under "Done when" are targets to confirm against the first scoreboard run, not measurements.

### M8. Restore a trustworthy baseline (S to M)

Every later milestone is judged by tests and benchmarks, and neither can be trusted today.

**Progress (2026-11-13, branch `claude/tender-clarke-ern139`).** Decision 1 was settled conservatively:
the human-reviewed standard stays as written (its tests lock the sizes and margins), and everything
else now works within it. Done, each with tests:

- All 39 failing tests fixed, without weakening a check: evidence recipes named by a caller keep
  their typography; `editorial_modern` hangs no further than the reviewed margin; the performance
  page plans with the frame's real usable height; tests that pinned pre-standard values now check the
  property they protect. Goldens regenerated after a contact-sheet review.
- Defects found while doing it: justified Arabic paragraphs had the last line flush left and the
  indent on the left; the Arabic classic cover was flush left with its title on the author line;
  every Markdown soft break became a hard break in DOCX, so wrapped Markdown came out as broken,
  stretched lines in Word; memo field lines ran together in PDF; DOCX said it was created in 2013;
  a designed masthead repeated a title the document already opens with; a gauge given
  `{label: value}` drew 0.
- QA judged more precisely, never more loosely: margin overflow is confirmed by rendered ink, not by
  font boxes; a sentence ending in heading or caption words is not a stranded heading or detached
  caption; the DOCX check counts the contents entries actually written, and reads line breaks.
- F8 (footnotes) and F12 (reproducible output, via `SOURCE_DATE_EPOCH`) closed; the version has one
  source; `.pyc` files untracked; the learning config's `D:/` paths work on every OS; README corrected.
- Every applicable direction passes the hard gates on all 15 fixture and stress documents (64 of 64).

**Progress (2026-11-16).** M8 closed on the code side:

- F4: `plan.typography` reports the size and leading on the page (after the reviewed standard), so
  the variant ranker's `base_size` and `line_height` features read real values. Tested.
- CI installs against `constraints.txt` (known-good versions, with markers for Python 3.10), runs a
  nightly job on the newest releases without it, and adds a Windows job (Python 3.12, no LibreOffice).
  The Python 3.10, 3.11 and 3.13 jobs carry no LibreOffice and are the fast answer on each push.
- The M7 findings list was re-checked: 1, 2, 3 and 6 are closed by named tests, 4 and 5 partly, the
  rest are listed as open with the milestone that takes them (`benchmarks/m7/FINDINGS.md`).
- The changelog for M5 to M7.10 is the README's "Unreleased" entry.

Open, owner only: CI still does not execute on GitHub (F1, the repository's Actions settings), so
the Windows job and branch protection on `main` wait for that. Next: M9.

- **Get CI executing again**, then require it on `main` with branch protection. Add a fast job without LibreOffice so every push gets an answer in minutes. Run CI against a constraints file, with a scheduled job on the newest dependencies.
- **Decide what the reviewed standard is** (decision 1 in section 7). Recommended: it becomes bounds plus the default for `design("auto")`, not an override. Directions and evidence recipes keep their own values inside the bounds, and the clamp accounts for a direction's hang.
- Fix `editorial_modern` (hang against margin), the Arabic `PerformancePage` that is 12 pt taller than its frame, and `plan.typography` so that it reports compiled tokens. Regenerate `tests/golden/` only after that, reviewed on contact sheets.
- Close F8, and re-run the M7 findings list so that each item is closed by a test or listed as open.
- Make output reproducible: fixed dates and IDs in PDF and DOCX, with a test that two renders hash the same.
- Portability and hygiene: move the `D:/` paths out of the committed config, untrack `.pyc` files, keep one version source, write the changelog for M5 to M7.10 and correct the README.

Done when: CI is green and required; 0 failing tests on Linux and Windows; every direction passes the gates on the benchmark corpus or is excluded with a stated reason; two renders of one input produce identical bytes.

### M9. One engine, one scoreboard (M to L)

Two optimizers with separate scores cannot be tuned or learned as one, and the better one is not what `export()` uses.

- **`PageFacts`**: one versioned, measured description of a rendered document inside the package. It merges the geometry metrics in `scoring.py`, the page signals in `visual_critique.py` and `tools/design_learning/layout_facts.py`. Scoring, critique, ranking, training and benchmarks all read it.
- **One objective**: hard gates plus one soft score over `PageFacts` with one weights table. The layout strategies of `compose("smart")` become one more axis of the variant search, and `compose` stays as an alias.
- **Reach**: `design(direction=..., variants=n, grammar=True)` feeds `export()`, and the CLI gains `variants`, `--direction`, `--grammar` and `--brand`. Classic `render()` does not change.
- **Scoreboard**: one runner over one corpus replaces the per-milestone scripts in `benchmarks/`. It reports gate pass rate per direction, near-empty last pages, page growth, PDF and DOCX page parity, forecast error, time and memory, the diversity of valid variants and the spread of result statuses. CI compares each run with budgets.
- **Calibrate the forecast**: simulated regions take real content widths, and forecast error becomes a tracked number.
- **Stop repeating work** (F13): share the figure cache across a direction's renders, open and rasterize each PDF once, and render directions in parallel under the same budgets.

Done when: one facts schema is used everywhere; the forecast is exact on page count for at least 95% of the corpus with a mean score error under 1.5; median time for three variants is at least 30% below the M8 baseline; the CLI can produce and explain variants.

### M10. Understand the content (M to L)

The mistakes visible on rendered pages come from treating content as counts and keyword hits.

- **Typed tables**: infer each column's role (period, identifier, category, measure, currency, percent, text), its unit and precision, the table's orientation, and total and subtotal rows. Alignment, emphasis of the current period, ledger styling, landscape decisions and chart suggestions read these roles.
- **Content lint** (`builder.lint()`, CLI `lint`), warnings only: totals against column sums, percentages against 100, repeated headings, unresolved anchors, mixed digit systems, inconsistent number and date formats, images without alt text, empty sections.
- **Roles and proportion**: move the keyword lists into data files with English and Arabic coverage, give the document type a calibrated confidence with an explicit "uncertain" outcome, read `meta.audience`, and decide covers and contents pages from measured pages in both design paths.
- **References and numbering**: automatic figure and table numbers, references by `id`, lists of figures and tables, footnotes at the foot of the page.
- **Charts**: reject data that does not fit the chart type, share scales in a `figure_matrix`, format numbers by locale, and set Arabic chart text through the same path as body text.

Done when: column roles are at least 95% correct on a labelled set of 60 or more tables, and no period column is treated as a measure; each lint rule catches a planted defect with no false positive on the corpus; document type is at least 90% correct on 100 or more labelled documents with abstentions counted; no contents page appears in a document under four pages unless the author asks.

### M11. Search instead of ladders (L)

- **Page-break optimizer**: block heights are already measured exactly, so choose break points by dynamic programming over a badness function (underfilled pages, a short last page, stranded headings, exhibits parted from their lead-in, widows and orphans). Pass the result to ReportLab as hints, verify it on the real render, and fall back to today's behaviour when verification fails. This replaces `fit_pages`, much of the refinement ladder and the guesswork behind `balanced` and `compact`.
- **Refinement as a budgeted search** over the `Adjust` space: rank by forecast, render only the best few, keep the existing render budget.
- **Word parity**: express each decision with native Word properties (keep with next, keep lines, page break before, rows that cannot split), add a per-font line-height calibration to predict Word's page count, and measure in real Word on a Windows runner where licensing allows.

Done when, on the scoreboard: no near-empty last page in PDF; handbook body pages under 60% full fall from 9 of 20 to 4 or fewer; no document gains a page; Word and PDF page counts differ in at most 2 of 48 designs.

### M12. Learning that can pass its own gate (M, plus time to collect data)

- **Automate the blind AI review.** Today a model is shown contact sheets in a manual session. Script it: fixed rubric, the existing row schema, side-swapped repeats, the Message Batches API for unattended runs at half price, and the model, prompt hash and date recorded on every row. Use at least two judges and report their agreement. Rows stay `reviewer_type: "ai"`.
- **Widen the corpus with independent documents.** The gate asks for three independent author groups and asset pools, and there is one. Add documents with cleared rights, Arabic and bilingual first.
- **Collect human signal cheaply**: a small local page for A/B judgments, and `VariantSet.accept(id)` to record which design a person actually kept. Both write to `training/human_preferences/` only.
- **Features come from `PageFacts`**, not from description strings (F4).
- **Models in order**: first calibrated, monotone weights that replace `fit * 6 + index` and the fixed score weights; then LightGBM with monotone constraints only if it beats the calibrated weights by the existing 0.03 margin on held-out families.
- **House style**: a per-brand prior over directions and parameters, learned from accepted outputs and stored with the brand kit.

Done when: the existing preflight audit reports ready; held-out agreement is at least 0.60 and at least 0.03 above the fixed selector; agreement with the human audit is reported; a model still loads only when a caller names it.

### M13. Optional AI layer (M to L)

Opt-in through an `ai` extra. Nothing imports it unless the caller asks.

Contract:

- A provider interface, with a default built on the official `anthropic` SDK. The model is a setting, not a constant.
- The model returns choices, never layout coordinates and never replacement body text. Each reply is validated against a schema with structured outputs. An invalid reply or a refusal falls back to the deterministic choice and is reported.
- Every AI-chosen design passes the same gates and content ledger as any other.
- Three context levels: `brief` (structure and statistics only, the default), `text`, and `pages` (rendered pages for the critic).
- Replies are cached by content hash, facts hash, prompt hash and model, so a repeated run is reproducible and free. Reports name the model.

Features:

- **Director**: the document brief goes in; ranked directions, section treatments and emphasis come out as validated values that the existing engine executes.
- **Critic**: rendered pages and their `PageFacts` go in, as a PDF document block or page images; structured issues and adjustments from an allowed list come out, for a bounded number of rounds. This replaces the ink grid as the judgment signal. The grid stays as a cheap filter.
- **Content assistance**, each switch separate and each output labelled as AI-written and kept out of the author's ledger: alt text, subject and keywords, a summary block on request, and structure repairs returned as a diff for the caller to accept.
- **Natural-language brief**: `design(brief="...")` mapped to a validated design intent.
- **Agent surface**: a published JSON Schema for the document, and an MCP server exposing render, variants, explain and lint, with errors that name the failing field and a fix.

Done when: on held-out families the director and critic beat the deterministic selector in panel and human-audit preference; the gate rejection rate does not rise; cost and added time per document are reported; with the extra not installed, behaviour and output are unchanged.

### M14. Typography, Arabic and accessibility (L, with spikes)

- **Shaping spike, one week**: turn on ReportLab's HarfBuzz path for the bundled fonts and test joining, marks, bidi line order, justified right-to-left text, mixed runs, extraction and speed. Adopt it and delete the reshaper workarounds, or keep the reshaper and add a text mapping so that extraction returns base letters.
- **Hyphenation** for justified left-to-right body text through `hyphenationLang`, never in headings or tables, with the matching Word setting.
- **Accessibility**: a structure tree with headings, lists, table headers and figure alt text, a contrast check in QA, and PDF/UA validation in CI. A two-week spike chooses between tagging the ReportLab output and adding a second backend for accessible export.
- **DOCX editability**: real Word footnotes, then OMML math, then native charts if the cost is acceptable.
- **A QA backend without AGPL** (F16): put PyMuPDF behind an interface and evaluate a permissively licensed pair for rasterizing and text geometry.

Done when: a verbatim search finds Arabic source text in the PDF; a justified probe paragraph hyphenates and loose lines fall on the corpus; a sample passes a PDF/UA validator; QA and variants run without PyMuPDF installed.

### M15. Product surface (M)

- **Streaming that streams** (F14): incremental parsing that tolerates unfinished constructs, preview pages while the text arrives, and a final render through `export()` with design and policy.
- **Templates and data**: variables, loops and conditions over a data context, tables and charts bound to CSV, JSON or XLSX, and batch rendering with shared caches. `templates/base.py` is a stub today.
- **Packaging**: charts as an extra that stays on by default for one release, font packs, and a wheel size budget (R5).
- **Service mode**, optional: a small worker that enforces `ResourceLimits`.

### Target API

A sketch of the surface after M9, M10 and M13. `direction`, `variants`, `grammar`, `ai`, `critic`, `lint()` and `res.design` do not exist today.

```python
b = DocumentBuilder.from_markdown(md).design(direction="auto", variants=3, grammar=True, brand=kit)
b.lint()                                  # M10: warnings about the content, never edits
res = b.export_both("out", qa=True)       # exports the recommended valid design
res.design.recommended, res.design.reasons

from dynamic_pdf.ai import Critic, Director   # M13: optional extra, off unless asked for
b.design(direction="auto", variants=3, ai=Director(context="brief"), critic=Critic(rounds=2))
```

## 5a. Status after M9 to M15 (2026-11-16)

Numbers were measured on each milestone's branch before the merge, on Linux with LibreOffice
standing in for Word. "Blocked" means the code exists and the target needs something this
repository cannot supply: data, people, a key, a licence or a validator.

| Milestone | Met | Not met, and why |
| --- | --- | --- |
| M9 | One facts schema (`intelligence/facts.py`, `PageFacts` v2) read by scoring, critique, ranker, dataset and scoreboard. Forecast page count exact on 18 of 18 documents (was 13), mean score error 0.37 (was 3.19). Three-variant median time 1.18 s to 0.80 s (29 to 32% lower on a shared machine). `export()` delivers the recommended variant; CLI `variants` explains it. | `compose("smart")` is not yet an axis of the variant search (both read one weights table). Directions are not rendered in parallel. |
| M10 | Column roles 221 of 222 right on 64 labelled tables, no period column read as a measure. Nine lint rules, each catching a planted defect, one true warning on the fixtures. Document type 50 of 51 on the held-out half of 102 labelled documents. No contents page under four pages unless asked. | The labelled sets were written by the implementer, not reviewed by people. Footnotes at the foot of the page, shared scales in `figure_matrix`, crowded chart labels and numbering of charts and diagrams are open. |
| M11 | Over 32 documents: body pages under 60% full 24 to 11, lead-ins parted from their exhibit 5 to 1, no document gains a page; handbook 4 to 0 underfilled pages. Default on. | One near-empty last page remains (`wide_data`, forced by a landscape run). Word and PDF page counts differ in 7 of 32 (target 2 of 48): the causes are contents length, chart size and Arabic text in Word, not breaks. Real Word was not available. Long documents take 3 to 4 times longer to prepare when a plan is verified. |
| M12 | Scripted blind review with two or more judges and an agreement report; `VariantSet.accept()`; a local A/B page; calibrated monotone weights behind the existing gate; a model loads only when named. | Blocked: the preflight audit is not ready (69 verified comparisons of 200, 0 of 20 human decisions, one author group). Nothing was trained. |
| M13 | `dynamic_pdf.ai`: provider interface on the official SDK, schema-validated replies, deterministic fallback, a reply cache, Director, Critic, content assistance, CLI `schema`, an MCP server. Without the extra, behaviour and output are unchanged (tested). | Blocked: no API key or panel, so preference over the deterministic selector, gate rejection rate and cost were not measured. Tested with fake providers only. |
| M14 | A verbatim search finds Arabic source text in the PDF. Loose justified lines 21.3% to 1.6%. QA and variants run without PyMuPDF, on PDFium. Real Word footnotes. A contrast check. | Blocked: no PDF/UA validator could be installed (veraPDF is not on PyPI); the opt-in tagged PDF still leaves list bullets, contents entries and decoration outside the tree. HarfBuzz shaping was not adopted (it needs `rlbidi`, not on PyPI). OMML math is open. |
| M15 | Streaming that commits only complete blocks and previews mid-construct; sandboxed templates over CSV, JSON and XLSX with escaping; batch rendering with a shared figure cache; a `charts` extra (8.3 MB wheel, budget 10 MB); a service mode that enforces limits per request. | Font packs. Matplotlib stays a core dependency for this release, as planned. |

Owner decisions taken as section 7 recommends: the reviewed standard stays as bounds already
settled in M8; AI is an opt-in extra; PDF/UA is a spike, not a requirement; PyMuPDF stays
optional behind `qa/pdf_backend.py`. Decision 5 (who gives the human judgments) is still open and
is what M12 and M13 wait on.

## 6. Order and first steps

```text
M8 -> M9 -> M10 --+--> M12 -> M13
        \-> M11 --+
M14 and M15 can run beside the others once M8 is done.
```

M12's review automation and corpus work can start as soon as M9 is done. Its labels are worth most after M10 and M11, because those change the pages being judged.

If only three things happen: M8, M9, then typed tables (M10) with the page-break optimizer (M11). Those two change what readers see on the page most.

First pull requests, in order:

1. CI executing and required, the Windows-only test made portable, a constraints file.
2. The reviewed standard as bounds, the `editorial_modern` and Arabic `PerformancePage` fixes, truthful `plan.typography`, regenerated goldens.
3. Footnotes, reproducible output, version and changelog, README corrections, untracked `.pyc` files.
4. `PageFacts` and the scoreboard skeleton with today's numbers as the baseline.
5. The shared figure cache for variants and the CLI `variants` command.

## 7. Decisions for the owner

1. **Is the reviewed standard one fixed look, or bounds?** If it is one look, cut the directions down to what still differs and delete the dead evidence recipes. If it is bounds, directions vary inside them. Recommended: bounds.
2. **May the library offer an opt-in feature that needs a network and an API key?** Recommended: yes, as an extra that is off by default.
3. **Is PDF/UA a requirement?** The answer decides whether M14 needs a second PDF backend.
4. **Is AGPL acceptable for the QA and variant paths?** If not, the backend work in M14 moves forward.
5. **Who gives the human judgments?** The training gate needs 20 audit decisions, and M12 and M13 are evaluated against them.

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| Reworking the reviewed standard changes default output again | Scoreboard budgets, and a contact-sheet review before goldens are regenerated |
| The page-break optimizer disagrees with ReportLab's own breaking | Verify on the real render and fall back when it fails |
| HarfBuzz shaping conflicts with justified right-to-left text | A spike with exit criteria, and a fallback that keeps the reshaper |
| An AI layer adds cost, latency and variation | Opt-in, schema-validated, cached by hash, gated, with a reported budget per document |
| A learned ranker fits 18 documents instead of design | The existing gate, a wider corpus, monotone constraints, and calibrated weights as the bar to beat |

## Appendix: how the evidence was produced

Scratch scripts are not part of the repository.

| Check | Method | Result |
| --- | --- | --- |
| Tests at `001ec36` | `python -m pytest -q` in a clean virtual environment | 891 passed, 35 failed, 4 errors |
| Tests at `ef0643f` | Same, on `git archive ef0643f` | 917 passed, 3 failed. `test_visual_atlas::test_output_inside_a_git_repository_is_refused` fails only because an archive is not a git checkout; it passes on `main` |
| CI state | GitHub Actions API: runs on `main`, and the jobs of run 42360133628 | Six failures within five seconds each; the latest run's jobs had no runner assigned |
| Forecast accuracy | `measure_blocks` and `simulate` against a real render, 11 fixtures and 6 stress documents | Page count exact in 15 of 17; score error 4.12 mean, 17.03 max |
| Directions | `design_variants` on the stress proposal with four directions; sizes and text edges read with PyMuPDF | Largest type 17.0 pt in all four; `editorial_modern` text starts at x = -10 pt |
| Pipelines | Classic render, designed export with QA, smart composition and three variants on four fixtures | `editorial_modern` rejected in 3 of 3 appearances; smart composition kept the baseline on all four |
| Probes | Two renders hashed; footnotes; PDF catalog; Arabic extraction; hyphenation; default export of `manual.md` | See F7 to F12 |

Not examined: rendering in Microsoft Word, Mermaid through Playwright, the reference analyzer's measurements, and the DOCX renderer beyond what its tests cover.

The 39 tests that do not pass on `main`. The first two causes were traced to code. The others are read from the assertion messages and from the fact that the tests pass at `ef0643f`.

| Likely cause | Tests | Passes at `ef0643f` |
| --- | --- | --- |
| Reviewed sizes and margins override recipes | `test_evidence_recipes` (7) | Yes |
| `editorial_modern` headings clipped | `test_m77_design_grammar` (3), `test_m79_art_direction` (3) | Yes |
| Layouts moved and the goldens were not regenerated | `test_visual_qa::test_golden_fingerprints` (11) | Yes |
| Layouts moved: page counts, packing, kept groups, and a clean preflight that skips the budget check | `test_m5_quality` (2), `test_m61_scoring_safety` (1), `test_m62_quality_gates` (1), `test_m6_composer` (1) | Yes |
| Arabic `PerformancePage` is 12 pt taller than its frame | `test_archetypes[performance_ar]` (4 errors) | Yes |
| Arabic long report: cover lines overlap in PDF, and 434 one-point overflows in LibreOffice | `test_stress_documents[arabic_long_report]` (2) | Yes |
| Not traced | `test_m710_learning` (1), `test_reference_analyzer` (1) | Yes |
| Windows-only path assertion | `test_m77_design_grammar::TestWorkflow` (1) | No |
| Not traced | `test_reference_sampling` (1) | No |
