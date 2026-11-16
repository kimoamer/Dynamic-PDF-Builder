"""
Optional AI layer (the ``ai`` extra). Nothing imports this package unless a caller does.

A model only chooses among designs the engine already makes, every value it returns is
validated, an invalid reply or a refusal keeps the deterministic choice and says so, and every
design still passes the same hard gates and content ledger. Replies are cached on disk by
content, facts, prompt and model, and every report names the model.

    from dynamic_pdf.ai import Critic, Director
    made = builder.design_variants(n=3, ai=Director(context="brief"), critic=Critic(rounds=2))
"""
from . import assist
from .design import ADJUSTMENTS, Critic, Director
from .provider import CONTEXTS, DEFAULT_MODEL, AnthropicProvider, Provider, Reply, ask

__all__ = ["ADJUSTMENTS", "CONTEXTS", "DEFAULT_MODEL", "AnthropicProvider", "Critic", "Director", "Provider", "Reply",
           "ask", "assist"]
