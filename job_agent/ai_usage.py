from __future__ import annotations

import inspect
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from browser_use import ChatBrowserUse

from job_agent.storage import DEFAULT_DB_PATH


# Browser Use token pricing in USD per million tokens for concrete models.
# Aliases are resolved before pricing so bu-latest cannot silently use an old table.
MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float, float]] = {
    "bu-2-0": (0.60, 0.06, 3.50),
}
MODEL_ALIASES: dict[str, str] = {
    "bu-latest": "bu-2-0",
    "bu-1-0": "bu-2-0",
}


@dataclass(frozen=True)
class UsageSnapshot:
    provider: str
    model: str
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    pricing_known: bool


UsageListener = Callable[[UsageSnapshot], object]


class MeteredChatBrowserUse(ChatBrowserUse):
    """ChatBrowserUse client with live, per-invocation token metering.

    Browser Use normalizes aliases such as ``bu-latest`` to ``bu-2-0``. Pricing
    therefore follows the effective model, not the alias originally requested.

    ``on_usage`` is called immediately after every successful LLM response that
    includes usage. This lets Job Agent persist spend while a long browser agent
    is still running, instead of waiting until the whole application finishes.
    """

    def __init__(self, *args: Any, on_usage: UsageListener | None = None, **kwargs: Any) -> None:
        requested_model = kwargs.get("model")
        if requested_model is None and args and isinstance(args[0], str):
            requested_model = args[0]
        self._requested_model = str(requested_model) if requested_model else ""
        self._on_usage = on_usage
        super().__init__(*args, **kwargs)
        if not self._requested_model:
            self._requested_model = str(self.model)
        self._prompt_tokens = 0
        self._cached_tokens = 0
        self._completion_tokens = 0

    @property
    def requested_model(self) -> str:
        return self._requested_model

    def _effective_model(self) -> str:
        model = str(self.model)
        return MODEL_ALIASES.get(model, model)

    def _snapshot_for(self, prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> UsageSnapshot:
        model = self._effective_model()
        pricing = MODEL_PRICING_USD_PER_MILLION.get(model)
        estimated_cost = 0.0
        if pricing:
            input_rate, cached_rate, output_rate = pricing
            uncached = max(0, prompt_tokens - cached_tokens)
            estimated_cost = (
                uncached * input_rate
                + cached_tokens * cached_rate
                + completion_tokens * output_rate
            ) / 1_000_000
        return UsageSnapshot(
            provider=self.provider,
            model=model,
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=round(estimated_cost, 8),
            pricing_known=pricing is not None,
        )

    async def ainvoke(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        completion = await super().ainvoke(*args, **kwargs)
        usage = completion.usage
        if usage is not None:
            prompt_tokens = int(usage.prompt_tokens or 0)
            cached_tokens = int(usage.prompt_cached_tokens or 0)
            completion_tokens = int(usage.completion_tokens or 0)
            self._prompt_tokens += prompt_tokens
            self._cached_tokens += cached_tokens
            self._completion_tokens += completion_tokens

            delta = self._snapshot_for(prompt_tokens, cached_tokens, completion_tokens)
            if self._on_usage is not None and delta.total_tokens > 0:
                try:
                    callback_result = self._on_usage(delta)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                except Exception:
                    # Telemetry must never break browser automation.
                    pass
        return completion

    def snapshot(self) -> UsageSnapshot:
        """Aggregate usage accumulated by this client instance."""
        return self._snapshot_for(
            self._prompt_tokens,
            self._cached_tokens,
            self._completion_tokens,
        )


class AIUsageStore:
    """Persists local AI usage events in the Job Agent SQLite database."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ai_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    job_id INTEGER,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    pricing_known INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_ai_usage_created_at ON ai_usage_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_usage_job_id ON ai_usage_events(job_id, created_at DESC);
                """
            )
            # Earlier Job Agent versions priced bu-latest with a stale table even
            # though Browser Use 0.13.10 resolves it to bu-2-0. Repair those local
            # estimates from the token columns without altering token counts.
            input_rate, cached_rate, output_rate = MODEL_PRICING_USD_PER_MILLION["bu-2-0"]
            connection.execute(
                """
                UPDATE ai_usage_events
                SET model = 'bu-2-0',
                    estimated_cost_usd = (
                        (CASE WHEN prompt_tokens > cached_tokens THEN prompt_tokens - cached_tokens ELSE 0 END) * ?
                        + cached_tokens * ?
                        + completion_tokens * ?
                    ) / 1000000.0,
                    pricing_known = 1
                WHERE model IN ('bu-latest', 'bu-1-0')
                """,
                (input_rate, cached_rate, output_rate),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def record(
        self,
        operation: str,
        snapshot: UsageSnapshot,
        *,
        job_id: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO ai_usage_events(
                    operation, provider, model, job_id, prompt_tokens, cached_tokens,
                    completion_tokens, total_tokens, estimated_cost_usd, pricing_known, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation,
                    snapshot.provider,
                    snapshot.model,
                    job_id,
                    snapshot.prompt_tokens,
                    snapshot.cached_tokens,
                    snapshot.completion_tokens,
                    snapshot.total_tokens,
                    snapshot.estimated_cost_usd,
                    1 if snapshot.pricing_known else 0,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def record_safely(
        self,
        operation: str,
        snapshot: UsageSnapshot,
        *,
        job_id: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> int | None:
        """Best-effort telemetry: usage logging must never break the user workflow."""
        try:
            return self.record(operation, snapshot, job_id=job_id, metadata=metadata)
        except Exception:
            return None

    def summary(self) -> dict[str, object]:
        with self._connect() as connection:
            all_time = connection.execute(
                """
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(total_tokens), 0) AS tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) AS cost
                FROM ai_usage_events
                """
            ).fetchone()
            today = connection.execute(
                """
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(total_tokens), 0) AS tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) AS cost
                FROM ai_usage_events
                WHERE date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()
            month = connection.execute(
                """
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(total_tokens), 0) AS tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) AS cost
                FROM ai_usage_events
                WHERE strftime('%Y-%m', created_at, 'localtime') = strftime('%Y-%m', 'now', 'localtime')
                """
            ).fetchone()
            recent_rows = connection.execute(
                """
                SELECT operation, provider, model, job_id, prompt_tokens, cached_tokens,
                       completion_tokens, total_tokens, estimated_cost_usd, pricing_known, metadata, created_at
                FROM ai_usage_events
                ORDER BY created_at DESC, id DESC LIMIT 20
                """
            ).fetchall()

        def period(row: sqlite3.Row) -> dict[str, object]:
            return {
                "calls": int(row["calls"]),
                "tokens": int(row["tokens"]),
                "cost_usd": round(float(row["cost"]), 6),
            }

        recent: list[dict[str, object]] = []
        for row in recent_rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(str(item.get("metadata") or "{}"))
            except json.JSONDecodeError:
                item["metadata"] = {}
            recent.append(item)

        return {
            "today": period(today),
            "month": period(month),
            "all_time": period(all_time),
            "recent": recent,
            "cost_is_estimate": True,
            "note": "Each Browser Use LLM response is persisted immediately; USD is estimated from returned token usage and the effective model pricing table.",
        }
