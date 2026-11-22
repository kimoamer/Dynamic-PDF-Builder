"""Acceptance test with real agents: each gets a plain request and the MCP server, nothing else (no tool
names, no file access, no shell), and the files it leaves are judged by the library's own checks.

    python benchmarks/agent/run.py OUT [scenario ...]

Needs the `claude` CLI (Claude Code), signed in, and the mcp extra. Each scenario runs in its own empty
folder; the result is OUT/results.json and a line per scenario. Not part of CI: it calls a model.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

SCENARIOS = {
    "invoice_en": ("Make an invoice as a PDF: Nile Trading Co. (Cairo) bills Delta Foods Ltd. (Alexandria), "
                   "invoice 2026-114 dated 20 November 2026, for 40 cartons of olive oil at 310 EGP, 12 boxes of "
                   "dates at 95 EGP and delivery at 450 EGP, with 14% VAT. Check it before you finish.",
                   {"pdf": 1}),
    "report_ar": ("اكتب تقريرًا قصيرًا بالعربية عن أداء فروع شركة في ثلاث مدن (القاهرة 18.4 مليون، الإسكندرية 12.1، "
                  "أسوان 6.3) فيه جدول ورسم بياني وخلاصة، وسلّمه PDF وملف Word قابل للتعديل. راجع الصفحات قبل "
                  "التسليم.", {"pdf": 1, "docx": 1}),
    "missing_data": ("Make a PDF invoice for Delta Foods Ltd. I don't have the line items yet. Do not invent "
                     "anything: tell me exactly what is missing.", {}),
    "long_report": ("Write a twelve-page project report in English on a school water programme (context, method, "
                    "results with two tables and a chart, risks, next steps), deliver it as a PDF, and check every "
                    "page, not only the first ones.", {"pdf": 1}),
}


def run(out: str, name: str) -> dict:
    prompt, expect = SCENARIOS[name]
    work = os.path.join(out, name)
    files = os.path.join(work, "files")
    os.makedirs(files, exist_ok=True)
    config = {"mcpServers": {"dpb": {"command": sys.executable,
                                     "args": ["-m", "dynamic_pdf.ai.mcp_server", "--out-dir", os.path.abspath(files)]}}}
    with open(os.path.join(work, "mcp.json"), "w") as f:
        json.dump(config, f)
    proc = subprocess.run(["claude", "-p", prompt, "--mcp-config", "mcp.json", "--strict-mcp-config",
                           "--allowedTools", "mcp__dpb", "--disallowedTools", "Bash,Write,Edit,Read,WebFetch,WebSearch",
                           "--output-format", "json", "--max-turns", "40"],
                          cwd=work, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL,
                          env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.dirname(
                              os.path.abspath(__file__))))})
    try:
        reply = json.loads(proc.stdout)
    except ValueError:
        reply = {"result": proc.stdout[-2000:], "is_error": True}
    made = sorted(os.listdir(files))
    found = {ext: sum(f.endswith("." + ext) for f in made) for ext in ("pdf", "docx", "xlsx")}
    checked = {f: _check(os.path.join(files, f)) for f in made if f.endswith(".pdf")}
    ok = all(found.get(ext, 0) >= n for ext, n in expect.items()) and all(c["passed"] for c in checked.values())
    if not expect:                          # nothing to make: the reply names what is missing, no file written
        ok = not made and "item" in (reply.get("result") or "").lower()
    return {"scenario": name, "ok": ok, "files": made, "checked": checked, "turns": reply.get("num_turns"),
            "cost_usd": reply.get("total_cost_usd"), "reply": (reply.get("result") or "")[-1500:]}


def _check(path: str) -> dict:
    """The PDF's own pages, read back: page count and whether text sits off the page or overlaps."""
    import pymupdf
    doc = pymupdf.open(path)
    off = sum(1 for p in doc for b in p.get_text("dict")["blocks"]
              if b.get("lines") and (b["bbox"][2] > p.rect.width + 1 or b["bbox"][3] > p.rect.height + 1))
    return {"pages": len(doc), "text_off_page": off, "passed": off == 0 and len(doc) > 0}


def main(argv) -> int:
    out = argv[0] if argv else "agent-acceptance"
    names = argv[1:] or list(SCENARIOS)
    results = [run(out, n) for n in names]
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    for r in results:
        print(f"{r['scenario']}: {'PASS' if r['ok'] else 'FAIL'} files={r['files']} turns={r['turns']}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
