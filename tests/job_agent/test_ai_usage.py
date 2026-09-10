from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_use import ChatBrowserUse
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


def test_bu_latest_is_priced_as_resolved_bu_2() -> None:
    llm = MeteredChatBrowserUse(model="bu-latest", api_key="test-key")
    llm._prompt_tokens = 1_000_000
    llm._cached_tokens = 250_000
    llm._completion_tokens = 100_000

    snapshot = llm.snapshot()

    assert llm.requested_model == "bu-latest"
    assert snapshot.model == "bu-2-0"
    assert snapshot.pricing_known is True
    assert snapshot.estimated_cost_usd == 0.815


@pytest.mark.asyncio
async def test_usage_listener_receives_each_llm_response_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = []

    async def fake_ainvoke(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=10_000,
                prompt_cached_tokens=2_000,
                completion_tokens=1_000,
            )
        )

    monkeypatch.setattr(ChatBrowserUse, "ainvoke", fake_ainvoke)
    llm = MeteredChatBrowserUse(model="bu-latest", api_key="test-key", on_usage=observed.append)

    await llm.ainvoke([])
    await llm.ainvoke([])

    assert len(observed) == 2
    assert all(item.model == "bu-2-0" for item in observed)
    assert all(item.total_tokens == 11_000 for item in observed)
    assert llm.snapshot().total_tokens == 22_000


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


def test_store_repairs_old_bu_latest_estimates(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    store = AIUsageStore(path)
    with store._connect() as connection:
        connection.execute(
            """
            INSERT INTO ai_usage_events(
                operation, provider, model, prompt_tokens, cached_tokens,
                completion_tokens, total_tokens, estimated_cost_usd, pricing_known
            ) VALUES('application', 'browser-use', 'bu-latest', 1000000, 250000, 100000, 1100000, 0.355, 1)
            """
        )

    repaired = AIUsageStore(path).summary()

    assert repaired["all_time"]["cost_usd"] == 0.815
    assert repaired["recent"][0]["model"] == "bu-2-0"


def test_record_safely_never_breaks_workflow(tmp_path: Path) -> None:
    llm = MeteredChatBrowserUse(model="bu-latest", api_key="test-key")
    store = AIUsageStore(tmp_path / "jobs.db")

    store.record = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("telemetry failed"))  # type: ignore[method-assign]

    assert store.record_safely("search", llm.snapshot()) is None
