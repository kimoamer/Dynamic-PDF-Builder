"""
Model providers and the one call every AI feature makes.

A provider turns a system prompt, user content blocks and a reply model (pydantic) into a
``Reply``. ``ask`` validates the reply against that model, caches it on disk by content hash,
facts hash, prompt hash and model, and reports what happened. Any problem, a refusal, an
invalid reply or a failed request, comes back as ``None`` with a report saying why, so the
caller keeps its deterministic choice. Nothing here runs unless a caller asks for it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Protocol, Tuple, Type

from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "claude-opus-5-5"
CONTEXTS = ("brief", "text", "pages")


def default_cache_dir() -> str:
    """Where replies are kept; empty for none. A folder that cannot be written is simply not used."""
    from ..settings import get
    folder = get("AI_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "dynamic-pdf-builder", "ai")
    return "" if folder.lower() == "off" else folder


@dataclass
class Reply:
    text: str                       # the JSON the model wrote
    model: str                      # the model that answered
    stop_reason: str = "end_turn"
    usage: dict = field(default_factory=dict)


class Provider(Protocol):
    model: str

    def complete(self, system: str, content: List[dict], reply_model: Type[BaseModel]) -> Reply: ...


class AnthropicProvider:
    """The default provider, on the official ``anthropic`` SDK (the ``ai`` extra).

    The reply is constrained with structured outputs and validated again here. The API key
    comes from the SDK's usual sources and is needed only when a request is made."""

    def __init__(self, model: Optional[str] = None, *, effort: str = "medium", max_tokens: int = 16000,
                 cache_dir: Optional[str] = None, client=None):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise ImportError('the AI layer needs the anthropic SDK: pip install "dynamic-pdf-builder[ai]"') from e
        from ..settings import get
        self.model: str = model or get("AI_MODEL") or DEFAULT_MODEL
        self.effort, self.max_tokens = effort, max_tokens
        self.cache_dir = default_cache_dir() if cache_dir is None else cache_dir
        self._client = client

    def params(self, system: str, content: List[dict], reply_model: Type[BaseModel]) -> dict:
        """Messages API parameters for one request; also used for Message Batches."""
        from anthropic import transform_schema
        return {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": [{"role": "user", "content": content}],
                "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": transform_schema(reply_model)}}}

    def complete(self, system: str, content: List[dict], reply_model: Type[BaseModel]) -> Reply:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return to_reply(self._client.messages.create(**self.params(system, content, reply_model)))


def to_reply(message) -> Reply:
    """A ``Message`` from the SDK as a ``Reply``."""
    text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
    usage = getattr(message, "usage", None)
    return Reply(text, message.model, message.stop_reason or "",
                 {"input_tokens": getattr(usage, "input_tokens", 0), "output_tokens": getattr(usage, "output_tokens", 0)})


def sha(data) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def prompt_hash(system: str, reply_model: Type[BaseModel]) -> str:
    return sha({"system": system, "schema": reply_model.model_json_schema()})


def ask(provider: Provider, *, feature: str, context: str, system: str, content: List[dict], reply_model: Type[BaseModel],
        content_hash: str, facts: object) -> Tuple[Optional[BaseModel], dict]:
    """One validated reply, or ``None`` and the reason. Never raises for the model's sake."""
    prompt = prompt_hash(system, reply_model)
    facts_hash = sha(facts)
    report = {"feature": feature, "model": provider.model, "context": context, "prompt_sha256": prompt,
              "content_sha256": content_hash, "facts_sha256": facts_hash, "cache": "off", "status": "fallback"}
    began = time.monotonic()
    cache_dir = getattr(provider, "cache_dir", None)
    path = os.path.join(cache_dir, sha(f"{content_hash}|{facts_hash}|{prompt}|{provider.model}".encode()) + ".json") if cache_dir else None
    reply = None
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                reply = Reply(**json.load(f))
            report["cache"] = "hit"
        except (OSError, ValueError, TypeError):
            reply = None                          # a damaged entry is asked again
    if reply is None:
        report["cache"] = "miss" if path else "off"
        try:
            reply = provider.complete(system, content, reply_model)
        except Exception as e:  # noqa: BLE001 - no key, no network, a bad request: keep the deterministic choice
            report.update(reason=f"request failed: {type(e).__name__}: {e}", seconds=round(time.monotonic() - began, 2))
            return None, report
    report.update(served_model=reply.model, usage=reply.usage, seconds=round(time.monotonic() - began, 2))
    if reply.stop_reason == "refusal":
        _store(path, reply, report)
        report["reason"] = "the model declined"
        return None, report
    try:
        parsed = reply_model.model_validate_json(reply.text)
    except ValidationError as e:
        report["reason"] = f"invalid reply: {e.errors()[0]['msg'] if e.errors() else e}"
        return None, report
    _store(path, reply, report)
    report["status"] = "ok"
    return parsed, report


def _store(path: Optional[str], reply: Reply, report: dict) -> None:
    if not path or report["cache"] == "hit":
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(reply), f, ensure_ascii=False)
    except OSError:
        report["cache"] = "unwritable"


def check_context(context: str) -> str:
    if context not in CONTEXTS:
        raise ValueError(f"context must be one of {CONTEXTS}")
    return context


def pdf_block(pdf: bytes) -> dict:
    import base64
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                           "data": base64.standard_b64encode(pdf).decode("ascii")}}


def text_block(data) -> dict:
    return {"type": "text", "text": data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, default=str)}
