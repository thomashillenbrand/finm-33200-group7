"""Tests for the chat-completion cache configuration in verifier.agent."""

from pathlib import Path

import pytest

from verifier.agent import _configure_cache, _LLM_CACHE_PATH


def test_configure_cache_disables_when_false(monkeypatch):
    """Passing enabled=False must clear the global LLM cache."""
    calls = []

    def fake_set_llm_cache(cache):
        calls.append(cache)

    monkeypatch.setattr("verifier.agent.set_llm_cache", fake_set_llm_cache)
    _configure_cache(False)
    assert calls == [None]


def test_configure_cache_sets_sqlite_when_true(tmp_path, monkeypatch):
    """Passing enabled=True must install a SQLiteCache at the configured path."""
    custom = tmp_path / "llm_cache.sqlite"
    monkeypatch.setattr("verifier.agent._LLM_CACHE_PATH", custom)
    calls = []

    def fake_set_llm_cache(cache):
        calls.append(cache)

    monkeypatch.setattr("verifier.agent.set_llm_cache", fake_set_llm_cache)
    _configure_cache(True)
    assert len(calls) == 1
    # langchain_community.cache.SQLiteCache stores its db path as `database_path`
    # on construction; just check the parent dir was created.
    assert custom.parent.exists()


def test_llm_cache_path_lives_under_pulled_data_cache():
    """Default location is pulled_data/.cache/llm_cache.sqlite (gitignored)."""
    p = Path(_LLM_CACHE_PATH)
    assert p.name == "llm_cache.sqlite"
    assert p.parent.name == ".cache"
    assert p.parent.parent.name == "pulled_data"
