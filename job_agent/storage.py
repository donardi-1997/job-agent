from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = Path("data/job-agent.db")


@dataclass(frozen=True)
class JobRecord:
	id: int | None
	source: str
	external_id: str
	title: str
	company: str
	location: str
	url: str
	score: int
	band: str
	status: str = "discovered"
	created_at: str | None = None


class JobStore:
	def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
		self.path = Path(path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self._init_schema()

	def connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(self.path)
		connection.row_factory = sqlite3.Row
		return connection

	def _init_schema(self) -> None:
		with self.connect() as connection:
			connection.executescript(
				"""
				CREATE TABLE IF NOT EXISTS jobs (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					source TEXT NOT NULL,
					external_id TEXT NOT NULL,
					title TEXT NOT NULL,
					company TEXT NOT NULL DEFAULT '',
					location TEXT NOT NULL DEFAULT '',
					url TEXT NOT NULL,
					score INTEGER NOT NULL DEFAULT 0 CHECK(score BETWEEN 0 AND 100),
					band TEXT NOT NULL DEFAULT 'ignore',
					status TEXT NOT NULL DEFAULT 'discovered',
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					UNIQUE(source, external_id)
				);
				CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
				CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
				CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
				"""
			)

	def upsert_jobs(self, jobs: Iterable[JobRecord]) -> int:
		count = 0
		with self.connect() as connection:
			for job in jobs:
				data = asdict(job)
				connection.execute(
					"""
					INSERT INTO jobs(source, external_id, title, company, location, url, score, band, status)
					VALUES(:source, :external_id, :title, :company, :location, :url, :score, :band, :status)
					ON CONFLICT(source, external_id) DO UPDATE SET
						title=excluded.title,
						company=excluded.company,
						location=excluded.location,
						url=excluded.url,
						score=excluded.score,
						band=excluded.band,
						status=excluded.status
					""",
					data,
				)
				count += 1
		return count

	def list_jobs(self, *, limit: int = 100, min_score: int = 0, status: str | None = None) -> list[dict[str, object]]:
		query = "SELECT * FROM jobs WHERE score >= ?"
		params: list[object] = [min_score]
		if status:
			query += " AND status = ?"
			params.append(status)
		query += " ORDER BY score DESC, created_at DESC LIMIT ?"
		params.append(limit)
		with self.connect() as connection:
			return [dict(row) for row in connection.execute(query, params).fetchall()]

	def stats(self) -> dict[str, int | float]:
		with self.connect() as connection:
			row = connection.execute(
				"""
				SELECT
					COUNT(*) AS total,
					SUM(CASE WHEN score >= 85 THEN 1 ELSE 0 END) AS high_match,
					SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) AS applied,
					SUM(CASE WHEN status = 'saved' THEN 1 ELSE 0 END) AS saved,
					COALESCE(ROUND(AVG(score), 1), 0) AS avg_score
				FROM jobs
				"""
			).fetchone()
			return dict(row) if row else {"total": 0, "high_match": 0, "applied": 0, "saved": 0, "avg_score": 0}
