from __future__ import annotations

import os

from job_agent import enforce_zero_cost_policy


def test_zero_cost_policy_disables_every_paid_ai_path(monkeypatch) -> None:
    monkeypatch.setenv("JOB_AGENT_ZERO_COST", "1")
    monkeypatch.setenv("JOB_AGENT_SEARCH_AI_FALLBACK", "1")
    monkeypatch.setenv("JOB_AGENT_QUESTION_LLM", "1")
    monkeypatch.setenv("JOB_AGENT_APPLICATION_AI_FALLBACK", "1")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "should-not-be-usable")

    assert enforce_zero_cost_policy() is True
    assert os.environ["JOB_AGENT_SEARCH_AI_FALLBACK"] == "0"
    assert os.environ["JOB_AGENT_QUESTION_LLM"] == "0"
    assert os.environ["JOB_AGENT_APPLICATION_AI_FALLBACK"] == "0"
    assert os.environ["BROWSER_USE_API_KEY"] == ""


def test_paid_ai_requires_explicit_zero_cost_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("JOB_AGENT_ZERO_COST", "0")
    monkeypatch.setenv("JOB_AGENT_SEARCH_AI_FALLBACK", "1")
    monkeypatch.setenv("JOB_AGENT_QUESTION_LLM", "1")
    monkeypatch.setenv("JOB_AGENT_APPLICATION_AI_FALLBACK", "1")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "explicit-key")

    assert enforce_zero_cost_policy() is False
    assert os.environ["JOB_AGENT_SEARCH_AI_FALLBACK"] == "1"
    assert os.environ["JOB_AGENT_QUESTION_LLM"] == "1"
    assert os.environ["JOB_AGENT_APPLICATION_AI_FALLBACK"] == "1"
    assert os.environ["BROWSER_USE_API_KEY"] == "explicit-key"
