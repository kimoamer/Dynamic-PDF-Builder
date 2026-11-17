"""One place for what the environment can set; what the caller passes always wins."""
import sys

import pytest

from dynamic_pdf import settings
from dynamic_pdf.policy import RenderPolicy, ResourceLimits


def test_the_caller_wins_then_the_variable_then_the_default(monkeypatch):
    for name in settings.SETTINGS:
        monkeypatch.delenv(settings.PREFIX + name, raising=False)
    assert RenderPolicy().error_mode == "strict" and ResourceLimits().max_pages is None
    monkeypatch.setenv("DYNAMIC_PDF_ERROR_MODE", "permissive")
    monkeypatch.setenv("DYNAMIC_PDF_MAX_PAGES", "40")
    monkeypatch.setenv("DYNAMIC_PDF_RENDER_TIMEOUT_S", "")           # empty counts as unset
    assert RenderPolicy().error_mode == "permissive" and RenderPolicy().limits.max_pages == 40
    assert RenderPolicy().limits.render_timeout_s is None
    assert RenderPolicy(error_mode="strict").error_mode == "strict" and ResourceLimits(max_pages=7).max_pages == 7
    monkeypatch.setenv("DYNAMIC_PDF_ERROR_MODE", "loose")
    with pytest.raises(ValueError, match="strict"):
        RenderPolicy()
    monkeypatch.setenv("DYNAMIC_PDF_MAX_PAGES", "many")
    with pytest.raises(ValueError, match="DYNAMIC_PDF_MAX_PAGES"):
        ResourceLimits()
    with pytest.raises(KeyError):
        settings.get("NOT_A_SETTING")


def test_the_ai_model_and_cache_come_from_the_environment_when_the_caller_names_none(monkeypatch, tmp_path):
    pytest.importorskip("anthropic")
    from dynamic_pdf.ai import DEFAULT_MODEL, AnthropicProvider
    from dynamic_pdf.ai.provider import default_cache_dir
    monkeypatch.delenv("DYNAMIC_PDF_AI_MODEL", raising=False)
    assert AnthropicProvider(client=object()).model == DEFAULT_MODEL
    monkeypatch.setenv("DYNAMIC_PDF_AI_MODEL", "another-model")
    assert AnthropicProvider(client=object()).model == "another-model"
    assert AnthropicProvider("named-in-code", client=object()).model == "named-in-code"
    monkeypatch.setenv("DYNAMIC_PDF_AI_CACHE", str(tmp_path))
    assert default_cache_dir() == str(tmp_path)
    monkeypatch.setenv("DYNAMIC_PDF_AI_CACHE", "off")
    assert default_cache_dir() == "" and AnthropicProvider(client=object()).cache_dir == ""


def test_accept_never_picks_a_place_to_write(monkeypatch, tmp_path):
    from dynamic_pdf import DocumentBuilder
    made = DocumentBuilder().heading("Report").paragraph("Text. " * 30).design_variants(n=1, families=["corporate_conservative"])
    monkeypatch.delenv("DYNAMIC_PDF_PREFERENCES_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="DYNAMIC_PDF_PREFERENCES_DIR"):
        made.accept("corporate_conservative", "A. Person")
    assert not list(tmp_path.iterdir())                              # nothing appeared in the working folder
    monkeypatch.setenv("DYNAMIC_PDF_PREFERENCES_DIR", str(tmp_path / "kept" / "human_preferences"))
    made.accept("corporate_conservative", "A. Person")
    assert (tmp_path / "kept" / "human_preferences" / "accepted.jsonl").is_file()


def test_a_host_that_started_pyplot_keeps_its_backend(monkeypatch):
    matplotlib = pytest.importorskip("matplotlib")
    from dynamic_pdf.utils.optional import require_matplotlib
    asked = []
    monkeypatch.setattr(matplotlib, "use", asked.append)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", object())
    require_matplotlib()
    assert asked == []
    monkeypatch.delitem(sys.modules, "matplotlib.pyplot")
    require_matplotlib()
    assert asked == ["Agg"]


def test_every_setting_is_documented():
    with open("docs/CONFIGURATION.md", encoding="utf-8") as f:
        doc = f.read()
    assert [n for n in settings.SETTINGS if f"`{settings.PREFIX}{n}`" not in doc] == []
