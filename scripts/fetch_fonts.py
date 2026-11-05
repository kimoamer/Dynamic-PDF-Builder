"""Maintainer tool: fetch the open-licence fonts bundled with the package.

Rendering never runs this and never touches the network. It downloads from the Google Fonts
repository, makes static Regular, Bold and Italic files where a family ships as a variable
font, keeps Latin and Arabic glyphs only so the package stays small, and writes ``catalog.json``
and each licence next to the fonts.

The PDF renderer shapes Arabic into Unicode presentation forms, which many modern fonts reach
only through OpenType rules. Where that is so, the forms are mapped onto the font's own
contextual glyphs, so nothing is redrawn.

    python scripts/fetch_fonts.py [--only cairo,lora]

A font is refused when it:
- is not under the SIL Open Font License;
- would have to be changed in any way but declares a Reserved Font Name;
- forbids embedding, which PDF and DOCX both need;
- for Arabic, lacks the presentation forms, harakat or digits the PDF renderer shapes text with.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

import unicodedata

from fontTools import subset
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dynamic_pdf", "fonts", "bundled")
RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl/{}/{}"
MAX_FILE_MB = 1.6

# directory in google/fonts, family name, script, style
FAMILIES = [
    # Arabic
    ("cairo", "Cairo", "arabic", "sans"), ("tajawal", "Tajawal", "arabic", "sans"),
    ("almarai", "Almarai", "arabic", "sans"), ("changa", "Changa", "arabic", "sans"),
    ("elmessiri", "El Messiri", "arabic", "display"), ("lateef", "Lateef", "arabic", "naskh"),
    ("scheherazadenew", "Scheherazade New", "arabic", "naskh"), ("markazitext", "Markazi Text", "arabic", "naskh"),
    ("mada", "Mada", "arabic", "sans"), ("reemkufi", "Reem Kufi", "arabic", "kufi"),
    ("harmattan", "Harmattan", "arabic", "sans"), ("notonaskharabic", "Noto Naskh Arabic", "arabic", "naskh"),
    ("notosansarabic", "Noto Sans Arabic", "arabic", "sans"), ("notokufiarabic", "Noto Kufi Arabic", "arabic", "kufi"),
    ("ibmplexsansarabic", "IBM Plex Sans Arabic", "arabic", "sans"), ("readexpro", "Readex Pro", "arabic", "sans"),
    ("lemonada", "Lemonada", "arabic", "display"), ("arefruqaa", "Aref Ruqaa", "arabic", "display"),
    ("mirza", "Mirza", "arabic", "naskh"), ("rakkas", "Rakkas", "arabic", "display"),
    ("katibeh", "Katibeh", "arabic", "display"), ("lalezar", "Lalezar", "arabic", "display"),
    ("vazirmatn", "Vazirmatn", "arabic", "sans"), ("alexandria", "Alexandria", "arabic", "sans"),
    ("baloobhaijaan2", "Baloo Bhaijaan 2", "arabic", "display"), ("kufam", "Kufam", "arabic", "kufi"),
    ("marhey", "Marhey", "arabic", "display"), ("rubik", "Rubik", "arabic", "sans"),
    ("beiruti", "Beiruti", "arabic", "sans"),
    ("fustat", "Fustat", "arabic", "sans"), ("amiriquran", "Amiri Quran", "arabic", "naskh"),
    ("gulzar", "Gulzar", "arabic", "naskh"), ("alkalami", "Alkalami", "arabic", "naskh"),
    ("notosansarabicui", "Noto Sans Arabic UI", "arabic", "sans"), ("qahiri", "Qahiri", "arabic", "kufi"),
    # Latin
    ("roboto", "Roboto", "latin", "sans"), ("opensans", "Open Sans", "latin", "sans"),
    ("lato", "Lato", "latin", "sans"), ("montserrat", "Montserrat", "latin", "sans"),
    ("sourcesans3", "Source Sans 3", "latin", "sans"), ("sourceserif4", "Source Serif 4", "latin", "serif"),
    ("merriweather", "Merriweather", "latin", "serif"), ("playfairdisplay", "Playfair Display", "latin", "display"),
    ("lora", "Lora", "latin", "serif"), ("ebgaramond", "EB Garamond", "latin", "serif"),
    ("librebaskerville", "Libre Baskerville", "latin", "serif"), ("crimsonpro", "Crimson Pro", "latin", "serif"),
    ("ptsans", "PT Sans", "latin", "sans"), ("ptserif", "PT Serif", "latin", "serif"),
    ("raleway", "Raleway", "latin", "sans"), ("nunito", "Nunito", "latin", "sans"),
    ("worksans", "Work Sans", "latin", "sans"), ("ibmplexsans", "IBM Plex Sans", "latin", "sans"),
    ("ibmplexserif", "IBM Plex Serif", "latin", "serif"), ("dmsans", "DM Sans", "latin", "sans"),
    ("poppins", "Poppins", "latin", "sans"), ("oswald", "Oswald", "latin", "display"),
    ("barlow", "Barlow", "latin", "sans"), ("firasans", "Fira Sans", "latin", "sans"),
    ("notoserif", "Noto Serif", "latin", "serif"), ("notosans", "Noto Sans", "latin", "sans"),
    ("bitter", "Bitter", "latin", "serif"), ("spectral", "Spectral", "latin", "serif"),
    ("librefranklin", "Libre Franklin", "latin", "sans"), ("manrope", "Manrope", "latin", "sans"),
]

ARABIC_NEEDS = ([0x0627, 0x0628, 0x062D, 0x0645, 0x064A, 0x0660, 0x0669, 0x064B, 0x064E, 0x0650, 0x0651, 0x0652]
                + list(range(0xFE80, 0xFEF5)) + [0xFEF5, 0xFEF7, 0xFEF9, 0xFEFB, 0xFEFC])
LATIN_NEEDS = list(range(0x20, 0x7F)) + [0xA9, 0xB0, 0xE9, 0xFC, 0x2013, 0x2014, 0x2019, 0x20AC]


KEEP = ([*range(0x20, 0x250), *range(0x2000, 0x2070), *range(0x20A0, 0x20C0), *range(0x2100, 0x2150), 0x2212,
         *range(0x2190, 0x2194), *range(0x25A0, 0x25D0), *range(0xFB00, 0xFB05)])
KEEP_ARABIC = [*range(0x600, 0x700), *range(0x750, 0x780), *range(0xFB50, 0xFE00), *range(0xFE70, 0xFF00)]
FORM_FEATURE = {"initial": "init", "medial": "medi", "final": "fina", "isolated": "isol"}


def lookups(font: TTFont, tags) -> list:
    """The substitution subtables behind these features, in any script."""
    if "GSUB" not in font:
        return []
    table = font["GSUB"].table
    wanted = {i for f in table.FeatureList.FeatureRecord if f.FeatureTag in tags for i in f.Feature.LookupListIndex}
    out = []
    for i in sorted(wanted):
        for st in table.LookupList.Lookup[i].SubTable:
            out.append(st.ExtSubTable if st.LookupType == 7 else st)
    return out


def add_forms(font: TTFont) -> bool:
    """Give each Arabic presentation form the glyph the font's own rules would pick."""
    cmap = font.getBestCmap()
    single = {tag: {} for tag in FORM_FEATURE.values()}
    for tag in single:
        for st in lookups(font, {tag}):
            if st.LookupType == 1:
                for a, b in st.mapping.items():
                    single[tag].setdefault(a, b)
    ligatures = {}
    for st in lookups(font, {"rlig", "liga", "calt", "ccmp"}):
        if st.LookupType == 4:
            for first, items in st.ligatures.items():
                for lig in items:
                    ligatures.setdefault((first, *lig.Component), lig.LigGlyph)
    added = {}
    for cp in range(0xFE70, 0xFEFD):
        if cp in cmap:
            continue
        parts = unicodedata.decomposition(chr(cp)).split()
        if len(parts) < 2 or not parts[0].startswith("<"):
            continue
        form = parts[0].strip("<>")
        if form not in FORM_FEATURE:
            continue
        base = [cmap.get(int(p, 16)) for p in parts[1:]]
        if None in base:
            continue
        tag = FORM_FEATURE[form]
        if len(base) == 1:
            glyph = base[0] if form == "isolated" else single[tag].get(base[0])
            glyph = single["isol"].get(base[0], glyph) if form == "isolated" else glyph
        else:                                     # lam with alef: try the shapes the rules join
            lam, alef = base
            first = [lam, single["init"].get(lam), single["medi"].get(lam)]
            second = [alef, single["fina"].get(alef)]
            glyph = next((ligatures[(a, b)] for a in first for b in second if (a, b) in ligatures), None)
        if glyph:
            added[cp] = glyph
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap.update(added)
    if 0xFDF2 not in font.getBestCmap():
        add_allah(font)
    return bool(added)


def add_allah(font: TTFont) -> None:
    """The shaper writes the word Allah as one character. A font without it gets a glyph built
    from its own letters, left to right on the page: heh, lam, lam, alef."""
    cmap = font.getBestCmap()
    letters = [cmap.get(c) for c in (0xFEEA, 0xFEE0, 0xFEDF, 0xFE8D)]
    if None in letters:
        return
    pen = TTGlyphPen(font.getGlyphSet())
    x = 0
    for name in letters:
        pen.addComponent(name, (1, 0, 0, 1, x, 0))
        x += font["hmtx"][name][0]
    font.setGlyphOrder([*font.getGlyphOrder(), "allah"])
    font["glyf"]["allah"] = pen.glyph()
    font["hmtx"]["allah"] = (x, 0)
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap[0xFDF2] = "allah"


def slim(font: TTFont, script: str) -> TTFont:
    """Only what these documents can set, without hinting, so the package stays small."""
    options = subset.Options(layout_features=["*"], name_IDs=["*"], notdef_outline=True, hinting=False,
                             glyph_names=False, legacy_kern=True, drop_tables=["DSIG"])
    tool = subset.Subsetter(options)
    tool.populate(unicodes=KEEP + (KEEP_ARABIC if script == "arabic" else []))
    tool.subset(font)
    return font


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def listing(folder: str) -> list:
    out = subprocess.run(["gh", "api", f"repos/google/fonts/contents/ofl/{folder}", "--jq", ".[].name"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise RuntimeError(out.stderr.strip()[:120])
    return out.stdout.split("\n")


def rename(font: TTFont, family: str, style: str) -> None:
    """Names, and the bold and italic flags, so Word and ReportLab see one four-style family."""
    plain = family.replace(" ", "")
    bold, italic = "Bold" in style, "Italic" in style
    for rec in list(font["name"].names):
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
            font["name"].removeNames(nameID=rec.nameID)
    full = family if style == "Regular" else f"{family} {style}"
    for nid, value in ((1, family), (2, style), (3, f"{plain}-{style}"), (4, full), (6, f"{plain}-{style}")):
        font["name"].setName(value, nid, 3, 1, 0x409)
        font["name"].setName(value, nid, 1, 0, 0)
    os2, head = font["OS/2"], font["head"]
    os2.fsSelection &= ~0b1100001
    os2.fsSelection |= (0x20 if bold else 0) | (0x01 if italic else 0) | (0 if bold or italic else 0x40)
    head.macStyle = (1 if bold else 0) | (2 if italic else 0)
    os2.usWeightClass = 700 if bold else 400


def static(data: bytes, family: str, style: str) -> TTFont:
    font = TTFont(io.BytesIO(data))
    if "fvar" in font:
        axes = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
        if "wght" in axes:
            lo = next(a for a in font["fvar"].axes if a.axisTag == "wght")
            axes["wght"] = min(lo.maxValue, max(lo.minValue, 700 if "Bold" in style else 400))
        font = instancer.instantiateVariableFont(font, axes, inplace=False)
    rename(font, family, style)
    return font


def pick(names: list, style: str):
    """The file that gives this style: a static file, else the family's variable font."""
    fonts = [n for n in names if n.lower().endswith(".ttf")]
    want = {"Regular": "-Regular.ttf", "Bold": "-Bold.ttf", "Italic": "-Italic.ttf"}[style]
    hit = next((n for n in fonts if n.endswith(want)), None)
    if hit:
        return hit, False
    var = [n for n in fonts if "[" in n]
    italic = [n for n in var if "Italic" in n]
    roman = [n for n in var if "Italic" not in n]
    if style == "Italic":
        return (italic[0], True) if italic else (None, False)
    if roman:
        return roman[0], True
    return None, False


def check(font: TTFont, script: str) -> list:
    cmap = set(font.getBestCmap())
    needs = ARABIC_NEEDS if script == "arabic" else LATIN_NEEDS
    missing = [hex(c) for c in needs if c not in cmap]
    problems = [f"{len(missing)} needed characters missing, e.g. {missing[:4]}"] if missing else []
    if script == "arabic":
        table, chart = font["glyf"], font.getBestCmap()
        if table[chart[0x0661]] == table[chart[0x31]]:
            problems.append("Arabic-Indic digits drawn as Latin digits")
    if font["OS/2"].fsType & 0x0002 or (font["OS/2"].fsType & 0x0200):
        problems.append("embedding restricted")
    if "glyf" not in font:
        problems.append("no TrueType outlines")
    return problems


def natural_line(font: TTFont) -> float:
    """The line height Word gives this font, in ems."""
    o = font["OS/2"]
    size = (o.sTypoAscender - o.sTypoDescender + o.sTypoLineGap) if o.fsSelection & 128 else o.usWinAscent + o.usWinDescent
    return round(size / font["head"].unitsPerEm, 3)


def fetch(folder: str, family: str, script: str, style_group: str) -> dict:
    names = listing(folder)
    if "OFL.txt" not in names:
        raise RuntimeError("no OFL.txt")
    licence = get(RAW.format(folder, "OFL.txt"))
    reserved = re.search(rb"Reserved Font Name", licence.split(b"This Font Software is licensed")[0]) is not None
    plain = family.replace(" ", "")
    files, line = {}, None
    for style in ("Regular", "Bold", "Italic"):
        if style == "Italic" and script == "arabic":
            continue
        name, variable = pick(names, style)
        if name is None:
            continue
        if variable and reserved:
            raise RuntimeError("variable font with a Reserved Font Name")
        data = get(RAW.format(folder, urllib.parse.quote(name)))
        font = TTFont(io.BytesIO(data)) if reserved else static(data, family, style)
        if not reserved:
            if script == "arabic":
                add_forms(font)
            font = slim(font, script)
        problems = check(font, script)
        if problems:
            raise RuntimeError("; ".join(problems))
        buf = io.BytesIO()
        font.save(buf)
        if len(buf.getvalue()) > MAX_FILE_MB * 1e6:
            raise RuntimeError(f"{len(buf.getvalue()) / 1e6:.1f} MB is too large to bundle")
        out = f"{plain}-{style}.ttf"
        open(os.path.join(ROOT, out), "wb").write(buf.getvalue())
        files[style.lower()] = out
        line = line or natural_line(font)
    if "regular" not in files:
        raise RuntimeError("no regular style")
    open(os.path.join(ROOT, "LICENSES", f"{plain}-OFL.txt"), "wb").write(licence)
    return {"script": script, "style": style_group, "files": files, "licence": "OFL-1.1",
            "line": line, "source": f"google/fonts ofl/{folder}", "reserved_name": reserved, "adapted": not reserved}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = set(filter(None, a.only.split(",")))
    path = os.path.join(ROOT, "catalog.json")
    catalog = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    refused = {}
    for folder, family, script, group in FAMILIES:
        if only and folder not in only:
            continue
        try:
            catalog[family] = fetch(folder, family, script, group)
            print("ok     ", family, flush=True)
        except Exception as e:                    # a refused family is reported, never half-kept
            catalog.pop(family, None)
            refused[family] = str(e)[:140]
            print("refused", family, "-", str(e)[:120], flush=True)
    json.dump(dict(sorted(catalog.items())), open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    count = {s: sum(1 for v in catalog.values() if v["script"] == s) for s in ("arabic", "latin")}
    print(count, "refused", len(refused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
