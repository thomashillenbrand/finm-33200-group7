"""Env-var resolution for model identifiers.

Model identifiers are configuration with no hardcoded fallback in the source
(see `.env.example`). Each task module exposes a private `_resolve_*_model`
callable: explicit arg (where supported) > env var, else it raises RuntimeError.
These tests pin that contract so future edits can't reintroduce a silent
hardcoded default or break A/B model selection during iter-3 eval.
"""

import pytest


def test_extractor_resolver_explicit_wins(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_MODEL", "openai:gpt-via-env")
    from extractor.extract import _resolve_extractor_model
    assert _resolve_extractor_model("openai:gpt-explicit") == "openai:gpt-explicit"


def test_extractor_resolver_env_used_when_no_explicit(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_MODEL", "openai:gpt-via-env")
    from extractor.extract import _resolve_extractor_model
    assert _resolve_extractor_model(None) == "openai:gpt-via-env"


def test_extractor_resolver_raises_when_unset(monkeypatch):
    monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
    from extractor.extract import _resolve_extractor_model
    with pytest.raises(RuntimeError, match="EXTRACTOR_MODEL"):
        _resolve_extractor_model(None)


def test_verifier_agent_resolver_env_used(monkeypatch):
    monkeypatch.setenv("VERIFIER_AGENT_MODEL", "openai:via-env")
    from verifier.agent import _resolve_agent_model
    assert _resolve_agent_model() == "openai:via-env"


def test_verifier_agent_resolver_raises_when_unset(monkeypatch):
    monkeypatch.delenv("VERIFIER_AGENT_MODEL", raising=False)
    from verifier.agent import _resolve_agent_model
    with pytest.raises(RuntimeError, match="VERIFIER_AGENT_MODEL"):
        _resolve_agent_model()


def test_verifier_parser_resolver_independent_from_agent(monkeypatch):
    """Parser model is its own env var; setting the agent's must not satisfy it."""
    monkeypatch.setenv("VERIFIER_AGENT_MODEL", "openai:agent-only")
    monkeypatch.setenv("VERIFIER_PARSER_MODEL", "openai:parser-only")
    from verifier.agent import _resolve_parser_model
    assert _resolve_parser_model() == "openai:parser-only"


def test_verifier_parser_resolver_raises_when_unset(monkeypatch):
    monkeypatch.setenv("VERIFIER_AGENT_MODEL", "openai:agent-only")
    monkeypatch.delenv("VERIFIER_PARSER_MODEL", raising=False)
    from verifier.agent import _resolve_parser_model
    with pytest.raises(RuntimeError, match="VERIFIER_PARSER_MODEL"):
        _resolve_parser_model()


def test_embedding_resolver_env_used(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    from verifier.index import _resolve_embedding_model
    assert _resolve_embedding_model() == "text-embedding-3-large"


def test_embedding_resolver_raises_when_unset(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    from verifier.index import _resolve_embedding_model
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        _resolve_embedding_model()
