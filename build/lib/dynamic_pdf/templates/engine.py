"""
A small, sandboxed template language for Markdown and JSON documents.

    # Invoice {{ invoice.number }}
    {% for item in items %}
    - {{ loop.index }}. {{ item.name }}: {{ item.price }}
    {% endfor %}
    {% if not paid %}Payment is due by {{ due }}.{% endif %}
    {{ lines | table }}

Tags: ``{{ expr }}``, ``{% for x in expr %}…{% endfor %}`` (with ``loop.index``,
``loop.first``, ``loop.last``), ``{% if [not] expr %}…{% elif … %}…{% else %}…{% endif %}``.
An expression is a dotted path (``a.b.0``) and optional filters: ``safe``, ``table``,
``headers``, ``rows``, ``chart("label", "value", …)``. Nothing is evaluated as code:
paths only index dicts and lists. A missing variable raises ``TemplateError`` naming it.

Values are escaped so data cannot add Markdown structure (headings, lists, links,
emphasis, tables, fences, math) unless marked ``| safe``. A tag alone on its line
leaves no blank line behind.
"""
import re
from typing import Any, List

from ..utils.errors import TemplateError

_TAG = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}")
_PATH = re.compile(r"[A-Za-z_]\w*(?:\.\w+)*$")
_FILTER = re.compile(r"\s*([A-Za-z_]\w*)\s*(?:\((.*)\))?\s*$")
_ARG = re.compile(r"""\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|(-?\d+(?:\.\d+)?))\s*(?:,|$)""")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


class Raw:
    """A value that is inserted as is (``| safe``, or a filter that builds structure)."""

    def __init__(self, value):
        self.value = value


# ─── Escaping ────────────────────────────────────────────────────────────────

def escape_markdown(value: str, line_start: bool = False) -> str:
    """Escape ``value`` so Markdown reads it as plain text (backslash escapes only;
    the text that renders is unchanged). Line breaks become spaces, so data cannot
    start a block of its own."""
    s = re.sub(r"[ \t]*[\r\n]+[ \t]*", " ", str(value))
    s = re.sub(r"([\\`*_\[\]<>|^])", r"\\\1", s)
    s = re.sub(r"([~=$:-])\1+", lambda m: "".join("\\" + c for c in m.group()), s)
    s = re.sub(r"&(?=#?\w+;)", r"\\&", s)
    if line_start:
        s = s.lstrip()
        s = re.sub(r"^(\d{1,9})([.)])", r"\1\\\2", s)
        s = re.sub(r"^([#+=:-])", r"\\\1", s)
    return s


def _escape_data(value):
    """Escape every string inside a typed value (JSON binding)."""
    if isinstance(value, Raw):
        return value.value
    if isinstance(value, str):
        return escape_markdown(value)
    if isinstance(value, dict):
        return {k: _escape_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_escape_data(v) for v in value]
    return value


# ─── Filters ─────────────────────────────────────────────────────────────────

def _records(value, name: str):
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise TemplateError(f"'{name}' is not a list of records")
    if value and all(isinstance(r, (list, tuple)) for r in value):
        headers = [str(h) for h in value[0]]
        return headers, [list(r) + [""] * (len(headers) - len(r)) for r in value[1:]]
    headers: List[str] = []
    for r in value:
        if not isinstance(r, dict):
            raise TemplateError(f"'{name}' mixes records and other values")
        headers += [str(k) for k in r if str(k) not in headers]
    return headers, [[r.get(h, "") for h in headers] for r in value]


def _cell(v) -> str:
    return "" if v is None else str(v)


def _f_table(value, name):
    headers, body = _records(value, name)
    if not headers:
        raise TemplateError(f"'{name}' has no columns to make a table")
    row = lambda cells: "| " + " | ".join(escape_markdown(_cell(c)) or " " for c in cells) + " |"
    lines = [row(headers), "| " + " | ".join("---" for _ in headers) + " |"]
    lines += [row(r) for r in body]
    return Raw("\n".join(lines))


def _f_headers(value, name):
    return _records(value, name)[0]


def _f_rows(value, name):
    return [[_cell(c) for c in r] for r in _records(value, name)[1]]


def _f_chart(value, name, label=None, *series):
    """Records → chart data: ``chart("region", "sales")`` gives ``{region: sales}``,
    several value columns give ``{"categories": […], "series": {col: […]}}``."""
    headers, body = _records(value, name)
    label = label or headers[0]
    series = series or tuple(h for h in headers if h != label)[:1]
    for col in (label, *series):
        if col not in headers:
            raise TemplateError(f"'{name}' has no column '{col}'")
    li, cols = headers.index(label), [headers.index(c) for c in series]

    def num(v, col):
        try:
            return float(str(v).replace(",", "")) if v not in (None, "") else 0.0
        except ValueError:
            raise TemplateError(f"'{name}' column '{col}' has a non-numeric value {v!r}") from None
    cats = [_cell(r[li]) for r in body]
    if len(cols) == 1:
        return Raw(dict(zip(cats, (num(r[cols[0]], series[0]) for r in body))))
    return Raw({"categories": cats,
                "series": {s: [num(r[c], s) for r in body] for s, c in zip(series, cols)}})


_FILTERS = {"safe": lambda v, n: Raw(v.value if isinstance(v, Raw) else v), "table": _f_table,
            "headers": _f_headers, "rows": _f_rows, "chart": _f_chart}


# ─── Parsing ─────────────────────────────────────────────────────────────────

def _parse(src: str) -> list:
    root: list = []
    stack = [("root", root, None, 0)]          # (kind, body list, node, line)
    pos = 0
    for m in _TAG.finditer(src):
        start, end = m.span()
        line = src.count("\n", 0, start) + 1
        if m.group(2) is not None:             # a block tag alone on its line takes the line
            ls = src.rfind("\n", 0, start) + 1
            le = src.find("\n", end)
            le = len(src) if le == -1 else le
            if ls >= pos and not src[ls:start].strip() and not src[end:le].strip():
                start, end = ls, min(le + 1, len(src))
        body = stack[-1][1]
        if start > pos:
            body.append(src[pos:start])
        pos = end
        if m.group(1) is not None:
            body.append(("var", m.group(1).strip(), line))
            continue
        words = m.group(2).split()
        tag = words[0] if words else ""
        if tag == "for":
            if len(words) < 4 or words[2] != "in" or not re.fullmatch(r"[A-Za-z_]\w*", words[1]):
                raise TemplateError(f"line {line}: expected '{{% for name in expr %}}'")
            node = ["for", words[1], " ".join(words[3:]), [], line]
            body.append(node)
            stack.append(("for", node[3], node, line))
        elif tag == "if":
            node = ["if", [(" ".join(words[1:]), [])], None, line]
            body.append(node)
            stack.append(("if", node[1][0][1], node, line))
        elif tag in ("elif", "else"):
            kind, _, node, _ = stack[-1]
            if kind != "if" or node[2] is not None:
                raise TemplateError(f"line {line}: '{{% {tag} %}}' without a matching '{{% if %}}'")
            if tag == "elif":
                node[1].append((" ".join(words[1:]), []))
                new = node[1][-1][1]
            else:
                node[2] = new = []
            stack[-1] = ("if", new, node, stack[-1][3])
        elif tag in ("endfor", "endif"):
            if stack[-1][0] != tag[3:]:
                raise TemplateError(f"line {line}: unexpected '{{% {tag} %}}'")
            stack.pop()
        else:
            raise TemplateError(f"line {line}: unknown tag '{{% {m.group(2).strip()} %}}'")
    if len(stack) > 1:
        kind, _, _, line = stack[-1]
        raise TemplateError(f"line {line}: '{{% {kind} %}}' is never closed (missing '{{% end{kind} %}}')")
    if pos < len(src):
        root.append(src[pos:])
    return root


# ─── Rendering ───────────────────────────────────────────────────────────────

class _Renderer:
    def __init__(self, context: dict, mode: str):
        self.scopes = [dict(context)]
        self.mode = mode                       # "markdown" | "json" | "plain"
        self.out: List[str] = []
        self.line = ""                         # text of the current output line so far
        self.fence = None                      # open code fence marker in the output

    def emit(self, text: str) -> None:
        self.out.append(text)
        parts = (self.line + text).split("\n")
        for done in parts[:-1]:
            m = _FENCE.match(done)
            if m and self.fence is None:
                self.fence = m.group(1)
            elif m and self.fence and m.group(1)[0] == self.fence[0] and len(m.group(1)) >= len(self.fence) \
                    and not done.strip().strip(m.group(1)[0]):
                self.fence = None
        self.line = parts[-1]

    def lookup(self, path: str, line: int):
        if not _PATH.match(path):
            raise TemplateError(f"line {line}: invalid expression {path!r} (only dotted names are allowed)")
        head, *rest = path.split(".")
        for scope in reversed(self.scopes):
            if head in scope:
                value = scope[head]
                break
        else:
            raise TemplateError(f"line {line}: undefined variable '{head}'")
        for i, key in enumerate(rest):
            if isinstance(value, dict) and key in value:
                value = value[key]
            elif isinstance(value, (list, tuple)) and key.isdigit() and int(key) < len(value):
                value = value[int(key)]
            else:
                raise TemplateError(f"line {line}: undefined variable '{'.'.join([head, *rest[:i + 1]])}'")
        return value

    def evaluate(self, expr: str, line: int):
        path, *filters = expr.split("|")
        value = self.lookup(path.strip(), line)
        for f in filters:
            m = _FILTER.match(f)
            if not m or m.group(1) not in _FILTERS:
                raise TemplateError(f"line {line}: unknown filter {f.strip()!r}; "
                                    f"available: {', '.join(sorted(_FILTERS))}")
            args, raw = [], m.group(2) or ""
            while raw.strip():
                a = _ARG.match(raw)
                if not a:
                    raise TemplateError(f"line {line}: invalid filter arguments {m.group(2)!r}")
                args.append(a.group(1) if a.group(1) is not None else a.group(2) if a.group(2) is not None
                            else float(a.group(3)) if "." in a.group(3) else int(a.group(3)))
                raw = raw[a.end():]
            try:
                value = _FILTERS[m.group(1)](value, path.strip(), *args)
            except TypeError:
                raise TemplateError(f"line {line}: wrong arguments for filter {m.group(1)!r}") from None
        return value

    def condition(self, expr: str, line: int) -> bool:
        words = expr.split()
        negate = bool(words) and words[0] == "not"
        if negate:
            expr = " ".join(words[1:])
        if not expr.strip():
            raise TemplateError(f"line {line}: empty condition")
        value = self.evaluate(expr, line)
        value = value.value if isinstance(value, Raw) else value
        return not value if negate else bool(value)

    def text(self, value, expr: str, line: int) -> str:
        raw = isinstance(value, Raw)
        value = value.value if raw else value
        if isinstance(value, (dict, list, tuple)):
            raise TemplateError(f"line {line}: '{expr}' is a {type(value).__name__}; "
                                "use a filter such as '| table' or a loop")
        s = "" if value is None else str(value)
        if raw or self.mode == "plain":
            return s
        if self.fence:                          # inside a code fence the text is literal
            if any(_FENCE.match(ln) for ln in s.split("\n")):
                raise TemplateError(f"line {line}: the value of '{expr}' would close the code fence")
            return s
        if self.line.count("`") % 2:            # inside an inline code span
            if "`" in s:
                raise TemplateError(f"line {line}: the value of '{expr}' contains '`' inside inline code")
            return re.sub(r"\s*[\r\n]+\s*", " ", s)
        return escape_markdown(s, line_start=self.mode == "markdown" and not self.line.strip())

    def run(self, nodes: list) -> None:
        for node in nodes:
            if isinstance(node, str):
                self.emit(node)
            elif node[0] == "var":
                _, expr, line = node
                self.emit(self.text(self.evaluate(expr, line), expr, line))
            elif node[0] == "for":
                _, name, expr, body, line = node
                items = self.evaluate(expr, line)
                items = items.value if isinstance(items, Raw) else items
                if isinstance(items, dict):
                    items = list(items.values())
                if not isinstance(items, (list, tuple)):
                    raise TemplateError(f"line {line}: '{expr}' is not a list")
                for i, item in enumerate(items):
                    self.scopes.append({name: item, "loop": {
                        "index": i + 1, "index0": i, "first": i == 0, "last": i == len(items) - 1}})
                    try:
                        self.run(body)
                    finally:
                        self.scopes.pop()
            else:
                _, branches, other, line = node
                for cond, body in branches:
                    if self.condition(cond, line):
                        self.run(body)
                        break
                else:
                    self.run(other or [])


def render_template(source: str, context: dict, mode: str = "markdown") -> str:
    """Render a template string. ``mode="markdown"`` escapes values for Markdown,
    ``"json"`` for the inline Markdown of JSON text fields, ``"plain"`` not at all."""
    if mode not in ("markdown", "json", "plain"):
        raise ValueError(f"mode must be 'markdown', 'json' or 'plain', got {mode!r}")
    r = _Renderer(context or {}, mode)
    r.run(_parse(source))
    return "".join(r.out)


_WHOLE = re.compile(r"\s*\{\{(.*?)\}\}\s*")


def render_json_template(obj: Any, context: dict) -> Any:
    """Render every string of a parsed JSON document. A string that is a single
    ``{{ expr }}`` whose value is not text takes the value itself (a list of table
    rows, chart data, a number), with every string inside it escaped."""
    if isinstance(obj, dict):
        return {k: render_json_template(v, context) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render_json_template(v, context) for v in obj]
    if not isinstance(obj, str):
        return obj
    m = _WHOLE.fullmatch(obj)
    if m and "{{" not in m.group(1) and "{%" not in obj:
        value = _Renderer(context or {}, "json").evaluate(m.group(1).strip(), 1)
        inner = value.value if isinstance(value, Raw) else value
        if not isinstance(inner, str):
            return _escape_data(value)
    return render_template(obj, context, mode="json")


__all__ = ["render_template", "render_json_template", "escape_markdown", "TemplateError"]
