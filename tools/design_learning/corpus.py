"""
The documents the learned selector is trained and tested on, with where each came from.

Four sources. Three are fictional documents written for this repository (the M7.9 corpus, the
M7 benchmark corpus, the test fixtures and stress documents); they share an origin, so they are
only weakly independent of one another. The fourth is real text by other people: Wikipedia
articles (CC BY-SA 4.0), with pictures from Wikimedia Commons. Their text and pictures are
fetched into a local cache and never committed; the manifest keeps the title, URL, licence,
retrieval date and hash of each.

    python -m tools.design_learning.corpus fetch training/ai_preferences_v2/wikipedia-cache
"""
from __future__ import annotations

import datetime
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT = "layout-eval-script/1.0 (generic research client)"
LICENCE = "CC BY-SA 4.0 (text, Wikipedia contributors); pictures under the free licence on each Wikimedia Commons file page"
ARTICLES = {
    "en": ["Tide", "Photosynthesis", "Suez Canal", "Honey bee", "Volcano", "Printing press", "Coffee", "Bridge",
           "Solar energy", "Library",
           # added for evaluation only; new titles go at the end, so a document keeps its name
           "Lighthouse", "Glacier", "Paper", "Silk Road", "Olive", "Camel", "Telescope", "Compass", "Bread", "Rice", "Tea",
           "Salt", "Glass", "Cement", "Wind power", "Irrigation", "Desalination", "Rail transport", "Bicycle", "Clock",
           "Calendar", "Map", "Museum", "Earthquake", "Coral reef", "Mangrove", "Date palm", "Cotton", "Pyramid",
           "Lunar eclipse", "Monsoon", "Oasis", "Dam", "Aqueduct (water supply)", "Windmill", "Pottery"],
    "ar": ["مد وجزر", "نهر النيل", "القاهرة", "طاقة شمسية", "ابن خلدون", "الخوارزمي", "البحر الأحمر", "قمح"],
}
_SKIP = re.compile(r"^(see also|references|external links|notes|further reading|bibliography|citations|sources|footnotes|"
                   r"انظر أيضا|انظر أيضًا|اقرأ أيضا|مراجع|المراجع|وصلات خارجية|مصادر|المصادر|هوامش|ملاحظات|روابط خارجية|معرض صور)$", re.I)
_FILE = re.compile(r"^(file|image|ملف|صورة):", re.I)
_PICTURE = re.compile(r"\.(jpe?g|png)$", re.I)


# ── Wikipedia ──────────────────────────────────────────────────────────────────────────

def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def _strip_nested(text: str, open_: str, close: str) -> str:
    """Remove ``open_ ... close`` spans, nested ones included (templates, tables)."""
    out, depth, i = [], 0, 0
    while i < len(text):
        if text.startswith(open_, i):
            depth += 1
            i += len(open_)
        elif depth and text.startswith(close, i):
            depth -= 1
            i += len(close)
        else:
            if not depth:
                out.append(text[i])
            i += 1
    return "".join(out)


def _links(text: str, pictures: List[Tuple[str, str]]) -> str:
    """``[[a|b]]`` reads as b. A picture link is taken out and kept, with its caption."""
    out, i = [], 0
    while i < len(text):
        if not text.startswith("[[", i):
            out.append(text[i])
            i += 1
            continue
        depth, j = 1, i + 2
        while j < len(text) and depth:
            if text.startswith("[[", j):
                depth, j = depth + 1, j + 2
            elif text.startswith("]]", j):
                depth, j = depth - 1, j + 2
            else:
                j += 1
        inner = text[i + 2:j - 2]
        parts = inner.split("|")
        if _FILE.match(parts[0].strip()):
            name = parts[0].split(":", 1)[1].strip()
            caption = _links(parts[-1], []) if len(parts) > 1 and "=" not in parts[-1] and not parts[-1].endswith("px") else ""
            if _PICTURE.search(name):
                pictures.append((name, caption.strip()))
        elif ":" in parts[0] and not parts[0].startswith(":") and len(parts[0].split(":")[0]) < 12:
            pass                                  # categories, interwiki
        else:
            out.append(_links(parts[-1], []))
        i = j
    return "".join(out)


def _drawable(text: str) -> str:
    """Without the characters some bundled family cannot draw (an article quotes other scripts), and
    without the brackets they leave empty. A document must be renderable in every direction."""
    from dynamic_pdf.fonts import font_catalog
    from dynamic_pdf.qa.glyphs import uncovered_chars
    missing = set()
    for family in font_catalog():
        missing |= set(uncovered_chars([text], family))
    if missing:
        text = text.translate({ord(c): None for c in missing})
        text = re.sub(r"\([\s,;:،؛]*\)", "", text)
    return text


def wikitext_to_markdown(text: str, title: str, *, max_words: int = 1300) -> Tuple[str, List[Tuple[str, str]]]:
    """An article's prose as Markdown, and its pictures as (file name, caption). References, tables,
    templates and the closing lists of links are left out; the text is cut at whole paragraphs."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>/]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<(math|gallery|timeline|syntaxhighlight|code|pre|nowiki)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    text = _strip_nested(_strip_nested(text, "{{", "}}"), "{|", "|}")
    pictures: List[Tuple[str, str]] = []
    text = _links(text, pictures)
    text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    def emphasis(t: str) -> str:               # after a line is classed: bold must not read as a list marker
        return t.replace("'''''", "").replace("'''", "**").replace("''", "*")

    lines, words, skipping, out = text.splitlines(), 0, False, []
    for line in lines:
        line = line.strip()
        head = re.fullmatch(r"(={2,6})\s*(.+?)\s*\1", line)
        if head:
            name = re.sub(r"[*_`']", "", head.group(2)).strip()
            skipping = bool(_SKIP.match(name))
            if not skipping and words < max_words:
                out += ["", "#" * min(3, len(head.group(1)) - 1) + " " + name, ""]
            continue
        if skipping or not line or words >= max_words:
            continue
        if line[0] in "*#":
            marker, item = ("- " if line[0] == "*" else "1. "), line.lstrip("*#: ").strip()
            if item:
                out.append(marker + emphasis(item))
                words += len(item.split())
            continue
        line = line.lstrip(":; ").strip()
        if len(line.split()) < 4 or line.startswith(("|", "!", "{", "}")):
            continue
        line = re.sub(r"[$|\\]", "", line)         # nothing that would start maths, a table or an escape
        out += ["", emphasis(line), ""]
        words += len(line.split())
    body = _drawable(re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip())
    while re.search(r"^#+ [^\n]*\n*(?=#|\Z)", body, flags=re.M):            # a heading with nothing under it
        body = re.sub(r"^#+ [^\n]*\n*(?=#|\Z)", "", body, flags=re.M).strip()
    return f'---\ntitle: "{title}"\nauthor: Wikipedia contributors\n---\n\n{body}\n', pictures


def fetch(cache: str, *, pictures_each: int = 2, pause: float = 1.2) -> dict:
    """Fetch the articles and their first pictures into ``cache`` and write its manifest. An article
    already in the cache is kept as it is: documents rendered from it must stay what was judged."""
    os.makedirs(cache, exist_ok=True)
    have = {}
    if os.path.isfile(os.path.join(cache, "manifest.json")):
        with open(os.path.join(cache, "manifest.json"), encoding="utf-8") as f:
            have = {a["name"]: a for a in json.load(f)["articles"]}
    manifest = []
    for lang, titles in ARTICLES.items():
        for n, title in enumerate(titles, 1):
            name = f"wiki_{lang}_{n:02d}"
            if name in have and have[name]["title"] == title and os.path.isfile(os.path.join(cache, name + ".md")):
                manifest.append(have[name])
                continue
            url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
            raw = _get(f"https://{lang}.wikipedia.org/w/index.php?title={urllib.parse.quote(title.replace(' ', '_'))}"
                       "&action=raw").decode("utf-8")
            time.sleep(pause)
            target = re.match(r"\s*#[^\[\n]*\[\[([^\]|#]+)", raw)        # a redirect page: follow it once
            if target:
                url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(target.group(1).strip().replace(' ', '_'))}"
                raw = _get(f"https://{lang}.wikipedia.org/w/index.php?title="
                           f"{urllib.parse.quote(target.group(1).strip().replace(' ', '_'))}&action=raw").decode("utf-8")
                time.sleep(pause)
            md, pics = wikitext_to_markdown(raw, title)
            kept = []
            for file_name, caption in pics[:6]:
                if len(kept) >= pictures_each:
                    break
                ext = ".png" if file_name.lower().endswith(".png") else ".jpg"
                local = f"{name}_{len(kept) + 1}{ext}"
                try:
                    data = _get("https://commons.wikimedia.org/wiki/Special:FilePath/"
                                + urllib.parse.quote(file_name.replace(" ", "_")) + "?width=900")
                except Exception:  # noqa: BLE001 - a picture that cannot be fetched is left out
                    data = b""
                time.sleep(pause)
                if data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG":
                    with open(os.path.join(cache, local), "wb") as f:
                        f.write(data)
                    kept.append({"file": local, "commons": file_name, "caption": caption,
                                 "page": "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(file_name.replace(" ", "_")),
                                 "sha256": hashlib.sha256(data).hexdigest()})
            with open(os.path.join(cache, name + ".md"), "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
            manifest.append({"name": name, "language": lang, "title": title, "url": url, "licence": LICENCE,
                             "retrieved": datetime.date.today().isoformat(), "words": len(md.split()),
                             "text_sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(), "pictures": kept})
            print(name, title, len(md.split()), "words,", len(kept), "pictures", flush=True)
    with open(os.path.join(cache, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"note": "Text and pictures are cached locally and not committed.", "articles": manifest}, f,
                  ensure_ascii=False, indent=1)
    return {"articles": len(manifest), "pictures": sum(len(m["pictures"]) for m in manifest)}


def _wikipedia(cache: str) -> Dict[str, dict]:
    from dynamic_pdf import DocumentBuilder
    path = os.path.join(cache, "manifest.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        articles = json.load(f)["articles"]
    out = {}
    for a in articles:
        def make(assets, a=a):
            with open(os.path.join(cache, a["name"] + ".md"), encoding="utf-8") as f:
                md = f.read()
            # each picture goes under a main heading, in the order the article gives them
            parts = re.split(r"(?m)^(?=# )", md)
            for k, pic in enumerate(a["pictures"]):
                if k + 1 < len(parts):
                    alt = re.sub(r'[\[\]()"]', "", pic["caption"] or a["title"])      # nothing that ends the picture's own markup
                    parts[k + 1] = parts[k + 1].rstrip() + f'\n\n![{alt}]({os.path.join(cache, pic["file"])} "{alt}")\n\n'
            b = DocumentBuilder.from_markdown("".join(parts))
            if a["language"] == "ar":
                b.direction("rtl")
            return b, None
        out[a["name"]] = {"make": make, "group": f"wikipedia-{a['language']}-contributors",
                          "pool": f"wikimedia-commons-{a['language']}" if a["pictures"] else None,
                          "family": f"wiki_{a['language']}",
                          "source": a["url"], "licence": a["licence"]}
    return out


# ── the repository's own documents ─────────────────────────────────────────────────────

def _module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def documents(wikipedia_cache: Optional[str] = None) -> Dict[str, dict]:
    """name -> {make(assets) -> (builder, brand), group, pool, family, source, licence}."""
    out: Dict[str, dict] = {}
    m79 = _module("m79_corpus", "benchmarks/m79/corpus.py")
    with open(os.path.join(ROOT, "training", "document-split.json"), encoding="utf-8") as f:
        old = {d: fam for fam, ds in json.load(f)["families"].items() for d in ds}
    for name, fn in m79.DOCUMENTS.items():
        out[name] = {"make": lambda assets, fn=fn: fn(m79.make_assets(os.path.join(assets, "m79"))),
                     "group": "repository-m79-fictional", "pool": "m79-generated-pictures", "family": "m79_" + old.get(name, "other"),
                     "source": "benchmarks/m79/corpus.py", "licence": "MIT (this repository)"}
    m7 = _module("m7_corpus", "benchmarks/m7/corpus.py")
    for name, (_, _, fn) in m7.CORPUS.items():
        out["m7_" + name] = {"make": lambda assets, fn=fn: (fn(), None), "group": "repository-m7-fictional",
                             "pool": "m7-generated-figures", "family": "m7_" + name.split("_")[0],
                             "source": "benchmarks/m7/corpus.py", "licence": "MIT (this repository)"}
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    stress = _module("stress_docs_corpus", "tests/stress_docs.py")
    for name, fn in stress.STRESS.items():
        out["stress_" + name] = {"make": lambda assets, fn=fn: (fn(os.path.join(assets, "stress")), None),
                                 "group": "repository-tests-fictional", "pool": "tests-generated-figures",
                                 "family": "tests_stress", "source": "tests/stress_docs.py", "licence": "MIT (this repository)"}
    from dynamic_pdf import DocumentBuilder
    fixtures = os.path.join(ROOT, "tests", "fixtures")
    for file in sorted(os.listdir(fixtures)):
        if file.endswith(".md"):
            def make(assets, file=file):
                with open(os.path.join(fixtures, file), encoding="utf-8") as f:
                    return DocumentBuilder.from_markdown(f.read()), None
            out["fixture_" + file[:-3]] = {"make": make, "group": "repository-tests-fictional", "pool": None,
                                           "family": "tests_fixtures", "source": "tests/fixtures/" + file,
                                           "licence": "MIT (this repository)"}
    if wikipedia_cache:
        out.update(_wikipedia(wikipedia_cache))
    return out


EVALUATION_GROUPS = ("repository-m7-fictional", "wikipedia-en-contributors")     # never train: other authors, other pictures


def describe(root: str) -> dict:
    """Write ``document-split.json``, ``provenance.json`` and the Wikipedia sources of the rendered
    documents into ``root``. A family, an author group and a picture pool each sit on one side of
    the split, and no picture file is used on both."""
    cache = os.path.join(root, "wikipedia-cache")
    docs, hashes = documents(cache), {}
    for name in sorted(os.listdir(os.path.join(root, "batches"))):
        path = os.path.join(root, "batches", name, "candidates.jsonl")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                hashes.update({c["document"]: c["document_hash"] for c in map(json.loads, f)})
    families: Dict[str, List[str]] = {}
    for d in sorted(hashes):
        families.setdefault(docs[d]["family"], []).append(d)
    held = sorted({docs[d]["family"] for d in hashes if docs[d]["group"] in EVALUATION_GROUPS})
    with open(os.path.join(cache, "manifest.json"), encoding="utf-8") as f:
        articles = json.load(f)["articles"]
    side = {a["name"]: docs[a["name"]]["group"] in EVALUATION_GROUPS for a in articles}
    shas = [{p["sha256"] for a in articles if side[a["name"]] is s for p in a["pictures"]} for s in (True, False)]
    if shas[0] & shas[1]:
        raise SystemExit(f"{len(shas[0] & shas[1])} picture(s) are used on both sides of the split")
    out = {"document-split.json": {
               "note": "A family, an author group and a picture pool are never split between training and evaluation. "
                       "The three repository groups were written for this repository and share that origin.",
               "families": families, "evaluation_families": held},
           "provenance.json": {
               "note": "Where each rendered document came from. Wikipedia text and pictures are not kept in the repository.",
               "documents": [{"document": d, "document_hash": h, "author_group": docs[d]["group"], "asset_pool": docs[d]["pool"],
                              "source": docs[d]["source"], "licence": docs[d]["licence"]} for d, h in sorted(hashes.items())]},
           "wikipedia-sources.json": {
               "note": "Fetch again with: python -m tools.design_learning.corpus fetch <root>/wikipedia-cache",
               "articles": [{**{k: a[k] for k in ("name", "language", "title", "url", "licence", "retrieved", "words", "text_sha256")},
                             "pictures": [{k: p[k] for k in ("commons", "page", "sha256")} for p in a["pictures"]]}
                            for a in articles]}}
    for file, content in out.items():
        with open(os.path.join(root, file), "w", encoding="utf-8", newline="\n") as f:
            json.dump(content, f, ensure_ascii=False, indent=1)
    return {"documents": len(hashes), "families": len(families), "evaluation_families": held,
            "evaluation_documents": sum(len(families[f]) for f in held)}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "fetch":
        print(json.dumps(fetch(sys.argv[2])))
    elif len(sys.argv) == 3 and sys.argv[1] == "describe":
        print(json.dumps(describe(sys.argv[2])))
    else:
        raise SystemExit(__doc__)
