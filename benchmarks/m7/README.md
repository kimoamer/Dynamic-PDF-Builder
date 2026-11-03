# M7 — visual quality and performance benchmark

Offline, CPU-only. All documents in `corpus.py` are fictional.

```bash
python benchmarks/m7/run.py benchmarks/m7/out              # all documents (≈10 min, needs PyMuPDF + LibreOffice)
python benchmarks/m7/run.py benchmarks/m7/out --docs proposal,letter
```

Outputs in `out/`: `report.md` (automated metrics, quality gates, performance and packaging audit),
`results.json`, `perf.json`, `results/*.json` (one per document and variant) and `gallery/index.html`.

## Human review

1. Open `out/gallery/index.html` in a browser (works from disk, no network).
2. Each document shows the two variants blind as **A** and **B**: PDF contact sheets and the DOCX rendered by
   LibreOffice. Choose A, B or Tie, optionally tick reasons and add a note. Automated metrics stay folded
   until you open them.
3. Click **Export judgments (JSON)** and commit the file under `benchmarks/m7/preferences/`.
4. Validate and summarise:

```bash
python benchmarks/m7/preferences.py validate benchmarks/m7/preferences/*.json
python benchmarks/m7/preferences.py summary benchmarks/m7/out/results.json benchmarks/m7/preferences/*.json
```

Judgments are tied to each variant's `layout_id` (a hash of the rendered geometry); judgments of a layout that
has since changed are ignored by `summary`. Nothing in this directory creates or infers a human judgment.
