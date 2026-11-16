"""
A small local page where a person judges the blind A/B sheets of a batch.

    python -m tools.design_learning preferences judge <batch> --reviewer "Full Name"

It serves on 127.0.0.1 only, shows one sheet at a time with nothing but the labels A and B,
and appends each judgment to ``training/human_preferences/human-audit.jsonl`` in the form the
preflight audit reads (``--human-audit``). The key stays on the server. Nothing is written to
the AI rows.
"""
from __future__ import annotations

import datetime
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs

from .pipeline import _jsonl, _load

FORMAT = "dynamic-pdf-builder/human-preference"
CHOICES = ("A", "B", "tie", "abstain")
CONFIDENCE = ("high", "medium", "low")


class Judging:
    def __init__(self, batch_dir: str, out: str, reviewer: str, source: str = "pdf"):
        if os.path.basename(os.path.dirname(os.path.abspath(out))) != "human_preferences":
            raise SystemExit("human judgments are written only to a human_preferences folder")
        if not reviewer.strip():
            raise SystemExit("a reviewer name is required: these are human judgments")
        self.batch_dir, self.out, self.reviewer, self.source = batch_dir, out, reviewer.strip(), source
        word = source == "word"
        self.sheets = os.path.join(batch_dir, "sheets-word" if word else "sheets")
        self.key = {k["comparison"]: k for k in _load(os.path.join(batch_dir, "key-word.json" if word else "key.json"))["comparisons"]}
        self.cands = {(c["document"], c["candidate"]): c for c in _jsonl(os.path.join(batch_dir, "candidates.jsonl"))}
        self.batch = os.path.basename(batch_dir.rstrip("/\\"))

    def done(self) -> set:
        return {r["comparison"] for r in _jsonl(self.out) if r.get("batch") == self.batch and r.get("reviewer") == self.reviewer}

    def todo(self) -> list:
        done = self.done()
        return [c for c in sorted(self.key) if c not in done and os.path.isfile(os.path.join(self.sheets, c + ".jpg"))]

    def judge(self, comparison: str, preferred: str, evidence: str, confidence: str, date: Optional[str] = None) -> dict:
        k = self.key.get(comparison)
        if k is None:
            raise ValueError("no such comparison")
        if preferred not in CHOICES or confidence not in CONFIDENCE:
            raise ValueError("choose A, B, tie or abstain, and a confidence")
        if preferred != "abstain" and not evidence.strip():
            raise ValueError("say what you saw on the pages that decided it")
        a, b = self.cands[(k["document"], k["a"])], self.cands[(k["document"], k["b"])]
        row = {"format": FORMAT, "batch": self.batch, "comparison": comparison, "document": k["document"],
               "document_hash": a["document_hash"],
               "a": {s: a[s] for s in ("candidate", "pdf_sha256", "docx_sha256")},
               "b": {s: b[s] for s in ("candidate", "pdf_sha256", "docx_sha256")},
               "preferred": preferred, "confidence": confidence, "visual_evidence": evidence.strip(),
               "formats_inspected": [self.source], "reversed_repeat": k["reversed_repeat"], "reviewer_type": "human",
               "reviewer": self.reviewer, "review_date": date or datetime.date.today().isoformat(), "tool": "ab_page"}
        os.makedirs(os.path.dirname(os.path.abspath(self.out)), exist_ok=True)
        with open(self.out, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>A/B judgment</title><style>body{{font:16px system-ui;margin:16px;max-width:100%}}img{{max-width:100%;border:1px solid #888}}
fieldset{{margin:12px 0}}textarea{{width:100%;min-height:4em}}button{{font-size:16px;padding:6px 16px}}</style>
<body>{body}</body></html>"""


def _form(j: Judging, cid: str, error: str = "") -> str:
    left = len(j.todo())
    radios = "".join(f'<label><input type="radio" name="preferred" value="{c}" required> {c}</label> ' for c in CHOICES)
    conf = "".join(f'<label><input type="radio" name="confidence" value="{c}"{" checked" if c == "medium" else ""}> {c}</label> '
                   for c in CONFIDENCE)
    err = f'<p role="alert" style="color:#a00">{html.escape(error)}</p>' if error else ""
    return PAGE.format(body=f"""<p>{html.escape(j.reviewer)} &middot; {left} left &middot; {html.escape(cid)}</p>{err}
<img src="/img/{html.escape(cid)}.jpg" alt="Row A and row B: pages of two designs of one document">
<form method="post" action="/c/{html.escape(cid)}"><fieldset><legend>Which design would you rather read and keep?</legend>{radios}</fieldset>
<fieldset><legend>How sure are you?</legend>{conf}</fieldset>
<label>What on the pages decided it (cite pages as A2, B1)<textarea name="evidence"></textarea></label>
<p><button>Save and next</button></p></form>""")


def handler(j: Judging):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, kind: str = "text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _next(self):
            todo = j.todo()
            if not todo:
                return self._send(200, PAGE.format(body="<p>Every sheet of this batch has your judgment. Thank you.</p>").encode())
            self.send_response(303)
            self.send_header("Location", f"/c/{todo[0]}")
            self.end_headers()

        def do_GET(self):
            if self.path == "/":
                return self._next()
            if self.path.startswith("/c/") and self.path[3:] in j.key:
                return self._send(200, _form(j, self.path[3:]).encode())
            name = self.path[5:-4] if self.path.startswith("/img/") and self.path.endswith(".jpg") else None
            if name in j.key and os.path.isfile(os.path.join(j.sheets, name + ".jpg")):
                with open(os.path.join(j.sheets, name + ".jpg"), "rb") as f:
                    return self._send(200, f.read(), "image/jpeg")
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            cid = self.path[3:] if self.path.startswith("/c/") else None
            if cid not in j.key:
                return self._send(404, b"not found", "text/plain")
            size = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(size).decode("utf-8")).items()}
            try:
                j.judge(cid, form.get("preferred", ""), form.get("evidence", ""), form.get("confidence", "medium"))
            except ValueError as e:
                return self._send(400, _form(j, cid, str(e)).encode())
            self._next()
    return Handler


def serve(j: Judging, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), handler(j))


__all__ = ["Judging", "serve"]
