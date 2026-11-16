"""
The blind AI review, scripted: every sheet of a batch, sent to two or more judges through the
Message Batches API, answered against a fixed rubric, and recorded in the existing row schema.

    python -m tools.design_learning preferences review <batch> --judge MODEL --judge MODEL

The first run submits one request per sheet and judge, then waits for the results (``--no-wait``
returns at once; run the same command again to collect). Judges see only the sheet image, with
sides labelled A and B; the key is read after the answers, by ``record``. Reversed repeats are
separate requests, so a judge cannot remember the first showing. Every row stays
``reviewer_type: "ai"`` and carries the model, the review date, the method and the prompt hash.
``agreement.json`` reports how often the judges agree.
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import time
from collections import Counter, defaultdict
from itertools import combinations
from typing import Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, create_model, model_validator

from .pipeline import _dump, _jsonl, _load
from .preferences import CRITERIA, record

RUBRIC = (
    "You judge two designs of the same document, shown as one image: row A holds the pages of one design, row B "
    "the pages of the other. Judge only what you can see. Prefer the design a careful reader would rather read "
    "and keep, by these criteria: " + ", ".join(CRITERIA) + ". Score each criterion that applies from -2 to 2: "
    "positive favours A, negative favours B, 0 is equal; leave a criterion null when it does not apply. Answer "
    "A, B, tie, or abstain when the image is unreadable. Except when you abstain, give a short visual reason and "
    "cite the pages it rests on as A1, B3 and so on. Say how sure you are: high, medium or low."
)
METHOD = ("blind whole-document sheets, labels A/B, PDF pages viewed as images; one request per sheet and judge "
          "through the Message Batches API, with a fixed rubric; reversed repeats are separate requests")
RUN_FILE = "ai-review.json"

Criteria = create_model("Criteria", **{c: (Optional[int], Field(None, ge=-2, le=2)) for c in CRITERIA})


class Answer(BaseModel):
    preferred: Literal["A", "B", "tie", "abstain"]
    criteria: Criteria
    justification: str = ""
    confidence: Literal["high", "medium", "low"]
    pages: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reasoned(self):
        if self.preferred != "abstain" and not (self.justification.strip() and self.pages):
            raise ValueError("an answer needs a visual reason and pages")
        if any(not re.fullmatch(r"[AB][1-9]\d*", p) for p in self.pages):
            raise ValueError("pages are cited as A1 or B3")
        return self


def prompt_sha256() -> str:
    from dynamic_pdf.ai.provider import prompt_hash
    return prompt_hash(RUBRIC, Answer)


def _sheets(batch_dir: str, source: str) -> List[str]:
    folder = os.path.join(batch_dir, "sheets-word" if source == "word" else "sheets")
    return sorted(f[:-4] for f in os.listdir(folder) if f.endswith(".jpg")) if os.path.isdir(folder) else []


def requests(batch_dir: str, judges: List[str], source: str = "pdf") -> List[dict]:
    """One Message Batches request per sheet and judge. Nothing in it names a design."""
    from dynamic_pdf.ai.provider import AnthropicProvider
    folder = os.path.join(batch_dir, "sheets-word" if source == "word" else "sheets")
    out = []
    for j, judge in enumerate(judges):
        provider = AnthropicProvider(model=judge, cache_dir="", client=object())
        for cid in _sheets(batch_dir, source):
            with open(os.path.join(folder, cid + ".jpg"), "rb") as f:
                image = base64.standard_b64encode(f.read()).decode("ascii")
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
                       {"type": "text", "text": "Which design is better? Answer in the required format."}]
            out.append({"custom_id": f"j{j}-{cid}", "params": provider.params(RUBRIC, content, Answer)})
    return out


def run(batch_dir: str, dataset: str, judges: List[str], *, client=None, source: str = "pdf", date: Optional[str] = None,
        wait: bool = True, poll: float = 60.0, sleep: Callable[[float], None] = time.sleep,
        human_audit: Optional[str] = None) -> dict:
    """Submit the batch, or collect it if it was submitted before. ``human_audit`` is the people's
    judgments file; where they judged the same sheets, agreement with them is reported too."""
    if len(judges) < 2 or len(set(judges)) < len(judges):
        raise SystemExit("name at least two different judges, so their agreement can be reported")
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    path = os.path.join(batch_dir, RUN_FILE)
    state = _load(path)
    if state and state.get("collected"):
        raise SystemExit("this batch was already reviewed; draw fresh sheets in a new batch to review again")
    if state is None:
        reqs = requests(batch_dir, judges, source)
        if not reqs:
            raise SystemExit("no sheets to review: run `preferences sheets` first")
        made = client.messages.batches.create(requests=reqs)
        state = {"message_batch": made.id, "judges": judges, "source": source, "requests": len(reqs),
                 "prompt_sha256": prompt_sha256(), "review_date": date or datetime.date.today().isoformat(),
                 "submitted": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        _dump(path, state)
    elif state["judges"] != judges or state["source"] != source:
        raise SystemExit(f"this batch was submitted for {state['judges']} on {state['source']} pages; use the same")
    while True:
        status = client.messages.batches.retrieve(state["message_batch"]).processing_status
        if status == "ended" or not wait:
            break
        sleep(poll)
    if status != "ended":
        return {"message_batch": state["message_batch"], "status": status, "note": "run the same command again to collect"}
    return collect(batch_dir, dataset, client, state, _jsonl(human_audit) if human_audit else [])


def collect(batch_dir: str, dataset: str, client, state: dict, humans: List[dict] = ()) -> dict:
    from dynamic_pdf.ai.provider import to_reply
    answers: Dict[int, List[dict]] = defaultdict(list)
    refused: List[dict] = []
    for item in client.messages.batches.results(state["message_batch"]):
        j, cid = item.custom_id.split("-", 1)
        j = int(j[1:])
        why = None
        if item.result.type != "succeeded":
            why = item.result.type
        else:
            reply = to_reply(item.result.message)
            if reply.stop_reason == "refusal":
                why = "refusal"
            else:
                try:
                    a = Answer.model_validate_json(reply.text)
                except ValueError as e:
                    why = f"invalid: {str(e).splitlines()[0]}"
                else:
                    answers[j].append({"comparison": cid, "preferred": a.preferred, "confidence": a.confidence,
                                       "criteria": {k: v for k, v in a.criteria.model_dump().items() if v is not None},
                                       "justification": a.justification, "pages": a.pages,
                                       "formats_inspected": [state["source"]]})
        if why:
            refused.append({"judge": state["judges"][j], "comparison": cid, "reason": why})
    recorded = {}
    for j, judge in enumerate(state["judges"]):
        rows = sorted(answers[j], key=lambda r: r["comparison"])
        file = os.path.join(batch_dir, f"answers-ai-{j}.jsonl")
        with open(file, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        recorded[judge] = record(batch_dir, file, dataset, model=judge, date=state["review_date"], method=METHOD,
                                 source=state["source"], extra={"prompt_sha256": state["prompt_sha256"],
                                                                "message_batch": state["message_batch"]})["recorded"]
    batch = os.path.basename(batch_dir.rstrip("/\\"))
    report = agreement([r for r in _jsonl(dataset) if r["batch"] == batch and r.get("message_batch") == state["message_batch"]],
                       [h for h in humans if h.get("batch") == batch])
    report.update(recorded=recorded, not_recorded=refused)
    _dump(os.path.join(batch_dir, "agreement.json"), report)
    _dump(os.path.join(batch_dir, RUN_FILE), {**state, "collected": True})
    return report


def _kappa(x: List[str], y: List[str]) -> Optional[float]:
    n = len(x)
    if not n:
        return None
    seen = sum(a == b for a, b in zip(x, y)) / n
    cx, cy = Counter(x), Counter(y)
    chance = sum(cx[k] * cy[k] for k in cx) / (n * n)
    return round((seen - chance) / (1 - chance), 3) if chance < 1 else 1.0


def agreement(rows: List[dict], humans: List[dict] = ()) -> dict:
    """How often each pair of judges gave the same answer to the same sheet, how often each judge
    agreed with itself when the sides were swapped, and how often it agreed with people."""
    by: Dict[tuple, Dict[str, str]] = defaultdict(dict)
    for r in rows:
        by[(r["batch"], r["comparison"])][r["model"]] = r["preferred"]
    judges = sorted({r["model"] for r in rows})
    pairs = []
    for a, b in combinations(judges, 2):
        both = [v for v in by.values() if a in v and b in v]
        x, y = [v[a] for v in both], [v[b] for v in both]
        clear = [(p, q) for p, q in zip(x, y) if p in ("A", "B") and q in ("A", "B")]
        pairs.append({"judges": [a, b], "sheets": len(both), "same_answer": sum(p == q for p, q in zip(x, y)),
                      "cohen_kappa": _kappa(x, y), "both_clear": len(clear), "clear_agreed": sum(p == q for p, q in clear)})
    swapped = {}
    for judge in judges:
        mine = [r for r in rows if r["model"] == judge]
        key = lambda r: (r["document"], frozenset((r["a"]["candidate"], r["b"]["candidate"])))  # noqa: E731
        first = {key(r): r for r in mine if not r["reversed_repeat"]}
        won = lambda r: {"A": r["a"]["candidate"], "B": r["b"]["candidate"]}.get(r["preferred"])  # noqa: E731
        reps = [(first[key(r)], r) for r in mine if r["reversed_repeat"] and key(r) in first]
        swapped[judge] = {"repeats": len(reps), "consistent": sum(won(a) == won(b) for a, b in reps)}
    people: Dict[tuple, List[str]] = defaultdict(list)
    for h in humans:
        if h.get("reviewer_type") == "human":
            people[(h["batch"], h["comparison"])].append(h["preferred"])
    with_humans = {}
    for judge in judges:
        seen = [(by[k][judge], p) for k, ps in people.items() if judge in by.get(k, {}) for p in ps]
        with_humans[judge] = {"judgments": len(seen), "same_answer": sum(a == p for a, p in seen)}
    return {"judges": judges, "pairs": pairs, "reversed_repeats": swapped, "with_humans": with_humans,
            "note": "AI judges agreeing with each other is not evidence of quality; it bounds how noisy one judge is."}


__all__ = ["METHOD", "RUBRIC", "Answer", "agreement", "collect", "prompt_sha256", "requests", "run"]
