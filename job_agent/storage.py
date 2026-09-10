from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = Path("data/job-agent.db")
ALLOWED_STATUSES = {"discovered", "saved", "applied", "ignored"}


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
	description: str = ""
	match_reasons: tuple[str, ...] = ()
	matched_skills: tuple[str, ...] = ()
	missing_skills: tuple[str, ...] = ()
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

	def _column_names(self, connection: sqlite3.Connection) -> set[str]:
		return {str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}

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
					description TEXT NOT NULL DEFAULT '',
					match_reasons TEXT NOT NULL DEFAULT '[]',
					matched_skills TEXT NOT NULL DEFAULT '[]',
					missing_skills TEXT NOT NULL DEFAULT '[]',
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					UNIQUE(source, external_id)
				);
				CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
				CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
				CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);

				CREATE TABLE IF NOT EXISTS application_drafts (
					job_id INTEGER PRIMARY KEY,
					payload TEXT NOT NULL,
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
				);
				"""
			)

			columns = self._column_names(connection)
			migrations = {
				"description": "ALTER TABLE jobs ADD COLUMN description TEXT NOT NULL DEFAULT ''",
				"match_reasons": "ALTER TABLE jobs ADD COLUMN match_reasons TEXT NOT NULL DEFAULT '[]'",
				"matched_skills": "ALTER TABLE jobs ADD COLUMN matched_skills TEXT NOT NULL DEFAULT '[]'",
				"missing_skills": "ALTER TABLE jobs ADD COLUMN missing_skills TEXT NOT NULL DEFAULT '[]'",
			}
			for column, statement in migrations.items():
				if column not in columns:
					connection.execute(statement)

	@staticmethod
	def _decode_row(row: sqlite3.Row) -> dict[str, object]:
		data = dict(row)
		for key in ("match_reasons", "matched_skills", "missing_skills"):
			try:
				data[key] = json.loads(str(data.get(key) or "[]"))
			except json.JSONDecodeError:
				data[key] = []
		return data

	def upsert_jobs(self, jobs: Iterable[JobRecord]) -> int:
		count = 0
		with self.connect() as connection:
			for job in jobs:
				data = asdict(job)
				data["match_reasons"] = json.dumps(data["match_reasons"], ensure_ascii=False)
				data["matched_skills"] = json.dumps(data["matched_skills"], ensure_ascii=False)
				data["missing_skills"] = json.dumps(data["missing_skills"], ensure_ascii=False)
				connection.execute(
					"""
					INSERT INTO jobs(
						source, external_id, title, company, location, url, score, band, status,
						description, match_reasons, matched_skills, missing_skills
					)
					VALUES(
						:source, :external_id, :title, :company, :location, :url, :score, :band, :status,
						:description, :match_reasons, :matched_skills, :missing_skills
					)
					ON CONFLICT(source, external_id) DO UPDATE SET
						title=excluded.title,
						company=excluded.company,
						location=excluded.location,
						url=excluded.url,
						score=excluded.score,
						band=excluded.band,
						description=excluded.description,
						match_reasons=excluded.match_reasons,
						matched_skills=excluded.matched_skills,
						missing_skills=excluded.missing_skills
					""",
					data,
				)
				count += 1
		return count

	def get_job(self, job_id: int) -> dict[str, object] | None:
		with self.connect() as connection:
			row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
		return self._decode_row(row) if row else None

	def update_status(self, job_id: int, status: str) -> dict[str, object] | None:
		if status not in ALLOWED_STATUSES:
			raise ValueError(f"Unsupported status: {status}")
		with self.connect() as connection:
			cursor = connection.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
			if cursor.rowcount == 0:
				return None
		return self.get_job(job_id)

	def save_application_draft(self, job_id: int, payload: dict[str, object]) -> dict[str, object]:
		if not self.get_job(job_id):
			raise ValueError("Vacante no encontrada.")
		encoded = json.dumps(payload, ensure_ascii=False)
		with self.connect() as connection:
			connection.execute(
				"""
				INSERT INTO application_drafts(job_id, payload, created_at, updated_at)
				VALUES(?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
				ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP
				""",
				(job_id, encoded),
			)
		return self.get_application_draft(job_id) or {}

	def get_application_draft(self, job_id: int) -> dict[str, object] | None:
		with self.connect() as connection:
			row = connection.execute(
				"SELECT payload, created_at, updated_at FROM application_drafts WHERE job_id = ?",
				(job_id,),
			).fetchone()
		if not row:
			return None
		try:
			payload = json.loads(str(row["payload"]))
		except json.JSONDecodeError:
			payload = {}
		if not isinstance(payload, dict):
			payload = {}
		payload["job_id"] = job_id
		payload["created_at"] = row["created_at"]
		payload["updated_at"] = row["updated_at"]
		return payload

	def list_jobs(self, *, limit: int = 100, min_score: int = 0, status: str | None = None) -> list[dict[str, object]]:
		query = "SELECT * FROM jobs WHERE score >= ?"
		params: list[object] = [min_score]
		if status:
			query += " AND status = ?"
			params.append(status)
		query += " ORDER BY score DESC, created_at DESC LIMIT ?"
		params.append(limit)
		with self.connect() as connection:
			return [self._decode_row(row) for row in connection.execute(query, params).fetchall()]

	def stats(self) -> dict[str, int | float]:
		with self.connect() as connection:
			row = connection.execute(
				"""
				SELECT
					COUNT(*) AS total,
					SUM(CASE WHEN score >= 85 THEN 1 ELSE 0 END) AS high_match,
					SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) AS applied,
					SUM(CASE WHEN status = 'saved' THEN 1 ELSE 0 END) AS saved,
					SUM(CASE WHEN status = 'ignored' THEN 1 ELSE 0 END) AS ignored,
					COALESCE(ROUND(AVG(score), 1), 0) AS avg_score
				FROM jobs
				"""
			).fetchone()
			return dict(row) if row else {
				"total": 0,
				"high_match": 0,
				"applied": 0,
				"saved": 0,
				"ignored": 0,
				"avg_score": 0,
			}
