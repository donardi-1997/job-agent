from pathlib import Path

from job_agent.ai_usage import AIUsageStore, MeteredChatBrowserUse


def test_metered_browser_use_calculates_bu_2_cost() -> None:
    llm = MeteredChatBrowserUse(model="bu-2-0", api_key="test-key")
    llm._prompt_tokens = 1_000_000
    llm._cached_tokens = 250_000
    llm._completion_tokens = 100_000

    snapshot = llm.snapshot()

    assert snapshot.prompt_tokens == 1_000_000
    assert snapshot.cached_tokens == 250_000
    assert snapshot.completion_tokens == 100_000
    assert snapshot.total_tokens == 1_100_000
    assert snapshot.pricing_known is True
    assert snapshot.estimated_cost_usd == 0.815


def test_metered_browser_use_calculates_bu_latest_cost() -> None:
    llm = MeteredChatBrowserUse(model="bu-latest", api_key="test-key")
    llm._prompt_tokens = 1_000_000
    llm._cached_tokens = 250_000
    llm._completion_tokens = 100_000

    snapshot = llm.snapshot()

    assert snapshot.pricing_known is True
    assert snapshot.estimated_cost_usd == 0.355


def test_ai_usage_store_summarizes_periods(tmp_path: Path) -> None:
    llm = MeteredChatBrowserUse(model="bu-2-0", api_key="test-key")
    llm._prompt_tokens = 10_000
    llm._cached_tokens = 2_000
    llm._completion_tokens = 1_000
    store = AIUsageStore(tmp_path / "jobs.db")

    store.record("search", llm.snapshot(), metadata={"keyword": "Python"})
    store.record("application", llm.snapshot(), job_id=12)

    summary = store.summary()

    assert summary["today"]["calls"] == 2
    assert summary["month"]["calls"] == 2
    assert summary["all_time"]["tokens"] == 22_000
    assert len(summary["recent"]) == 2
    assert summary["cost_is_estimate"] is True


def test_record_safely_never_breaks_workflow(tmp_path: Path) -> None:
    llm = MeteredChatBrowserUse(model="bu-latest", api_key="test-key")
    store = AIUsageStore(tmp_path / "jobs.db")

    store.record = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("telemetry failed"))  # type: ignore[method-assign]

    assert store.record_safely("search", llm.snapshot()) is None
