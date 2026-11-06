"""
Render DOCX through Microsoft Word on this machine, so a design is judged in the program people use.

Each file gets its own Word process with a time limit, opened read-only. Only the Word process
started here is ever stopped. Windows with Word installed only; nothing at runtime needs this.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import subprocess
import tempfile
from typing import Dict, List

SCRIPT = r"""
param([string]$File, [string]$Target, [string]$PidFile)
$before = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object Id)
$word = New-Object -ComObject Word.Application
$mine = @(Get-Process WINWORD | ForEach-Object Id) | Where-Object { $before -notcontains $_ }
Set-Content -Path $PidFile -Value ($mine -join ",")
$word.Visible = $false
$word.DisplayAlerts = 0
$doc = $word.Documents.Open($File, $false, $true, $false)
"version " + $word.Build
"pages " + $doc.ComputeStatistics(2)
$doc.ExportAsFixedFormat($Target, 17)
$doc.Close(0)
$word.Quit()
"""


def export(folder: str, out: str, limit: int = 60) -> Dict[str, object]:
    """Every DOCX under ``folder`` to a PDF under ``out``, named after its relative path."""
    os.makedirs(out, exist_ok=True)
    rows: List[dict] = []
    build = None
    with tempfile.TemporaryDirectory() as tmp:
        script, pid_file = os.path.join(tmp, "word.ps1"), os.path.join(tmp, "pid.txt")
        with open(script, "w", encoding="utf-8") as f:
            f.write(SCRIPT)
        for path in sorted(glob.glob(os.path.join(folder, "**", "*.docx"), recursive=True)):
            name = os.path.relpath(path, folder).replace(os.sep, "__")[:-5]
            target = os.path.abspath(os.path.join(out, name + ".pdf"))
            command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-File", os.path.abspath(path),
                       "-Target", target, "-PidFile", pid_file]
            try:
                run = subprocess.run(command, capture_output=True, text=True, timeout=limit)
                found = re.search(r"pages (\d+)", run.stdout)
                build = (re.search(r"version (\S+)", run.stdout) or [None, build])[1]
                ok = run.returncode == 0 and os.path.isfile(target) and bool(found)
                def digest(filename):
                    with open(filename, "rb") as content:
                        return hashlib.sha256(content.read()).hexdigest()
                rows.append({"file": name, "pages": int(found.group(1)) if found else None,
                             "ok": ok, "docx_sha256": digest(path) if ok else None,
                             "pdf_sha256": digest(target) if ok else None})
            except subprocess.TimeoutExpired:
                rows.append({"file": name, "pages": None, "ok": False, "error": f"no result in {limit} seconds"})
                if os.path.exists(pid_file):
                    with open(pid_file, encoding="utf-8-sig") as f:
                        for pid in filter(None, f.read().strip().split(",")):
                            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    result = {"word_build": build, "files": rows}
    with open(os.path.join(out, "word.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return {"word_build": build, "exported": sum(r["ok"] for r in rows), "failed": [r["file"] for r in rows if not r["ok"]], "folder": out}
