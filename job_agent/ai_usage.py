from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from browser_use import ChatBrowserUse

from job_agent.storage import DEFAULT_DB_PATH


# Browser Use published token pricing. Keep this table explicit so cost estimates
# remain auditable instead of hiding a magic per-run number.
MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float, float]] = {
    "bu-2-0": (0.60, 0.06, 3.50),
    "bu-latest": (0.60, 0.06, 3.50),
    "bu-1-0": (0.20, 0.02, 2.00),
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


class MeteredChatBrowserUse(ChatBrowserUse):
    """ChatBrowserUse client that accumulates real token usage returned by the API."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._prompt_tokens = 0
        self._cached_tokens = 0
        self._completion_tokens = 0

    async def ainvoke(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        completion = await super().ainvoke(*args, **kwargs)
        usage = completion.usage
        if usage is not None:
            self._prompt_tokens += int(usage.prompt_tokens or 0)
            self._cached_tokens += int(usage.prompt_cached_tokens or 0)
            self._completion_tokens += int(usage.completion_tokens or 0)
        return completion

    def snapshot(self) -> UsageSnapshot:
        pricing = MODEL_PRICING_USD_PER_MILLION.get(self.model)
        estimated_cost = 0.0
        if pricing:
            input_rate, cached_rate, output_rate = pricing
            uncached = max(0, self._prompt_tokens - self._cached_tokens)
            estimated_cost = (
                uncached * input_rate
                + self._cached_tokens * cached_rate
                + self._completion_tokens * output_rate
            ) / 1_000_000
        return UsageSnapshot(
            provider=self.provider,
            model=self.model,
            prompt_tokens=self._prompt_tokens,
            cached_tokens=self._cached_tokens,
            completion_tokens=self._completion_tokens,
            total_tokens=self._prompt_tokens + self._completion_tokens,
            estimated_cost_usd=round(estimated_cost, 8),
            pricing_known=pricing is not None,
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
                       completion_tokens, total_tokens, estimated_cost_usd, pricing_known, created_at
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

        return {
            "today": period(today),
            "month": period(month),
            "all_time": period(all_time),
            "recent": [dict(row) for row in recent_rows],
            "cost_is_estimate": True,
            "note": "Tokens are measured from Browser Use responses; USD is calculated from the local pricing table.",
        }
