from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = Path("data/job-agent.db")
ALLOWED_STATUSES = {"discovered", "saved", "applied", "ignored"}

class ApplicationModeStore:
	"""Persist the local application safety mode."""
	ALLOWED_MODES = {"test", "real"}
	def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
		self.path = Path(path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		with sqlite3.connect(self.path) as connection:
			connection.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
	def get(self) -> str:
		with sqlite3.connect(self.path) as connection:
			row = connection.execute("SELECT value FROM app_settings WHERE key='application_mode'").fetchone()
		return str(row[0]) if row and row[0] in self.ALLOWED_MODES else "test"
	def set(self, mode: str) -> str:
		if mode not in self.ALLOWED_MODES:
			raise ValueError("mode must be 'test' or 'real'")
		with sqlite3.connect(self.path) as connection:
			connection.execute("INSERT INTO app_settings(key,value) VALUES('application_mode',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mode,))
		return mode


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

				CREATE TABLE IF NOT EXISTS application_attempts (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					job_id INTEGER NOT NULL,
					payload TEXT NOT NULL,
					submitted INTEGER NOT NULL DEFAULT 0,
					submission_status TEXT NOT NULL DEFAULT 'not_submitted',
					confirmation_text TEXT NOT NULL DEFAULT '',
					confirmation_url TEXT NOT NULL DEFAULT '',
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
				);
				CREATE INDEX IF NOT EXISTS idx_application_attempts_job_id ON application_attempts(job_id, created_at DESC);

				CREATE TABLE IF NOT EXISTS batch_runs (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					keyword TEXT NOT NULL,
					location TEXT NOT NULL,
					min_score INTEGER NOT NULL,
					max_applications INTEGER NOT NULL,
					state TEXT NOT NULL DEFAULT 'running',
					found INTEGER NOT NULL DEFAULT 0,
					eligible INTEGER NOT NULL DEFAULT 0,
					attempted INTEGER NOT NULL DEFAULT 0,
					submitted INTEGER NOT NULL DEFAULT 0,
					blocked INTEGER NOT NULL DEFAULT 0,
					message TEXT NOT NULL DEFAULT '',
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

	def save_application_attempt(self, job_id: int, payload: dict[str, object]) -> int:
		if not self.get_job(job_id):
			raise ValueError("Vacante no encontrada.")
		with self.connect() as connection:
			cursor = connection.execute(
				"""
				INSERT INTO application_attempts(
					job_id, payload, submitted, submission_status, confirmation_text, confirmation_url
				) VALUES (?, ?, ?, ?, ?, ?)
				""",
				(
					job_id,
					json.dumps(payload, ensure_ascii=False),
					1 if payload.get("submitted") else 0,
					str(payload.get("submission_status") or "not_submitted"),
					str(payload.get("confirmation_text") or ""),
					str(payload.get("confirmation_url") or ""),
				),
			)
			return int(cursor.lastrowid)

	def list_application_attempts(self, job_id: int, limit: int = 20) -> list[dict[str, object]]:
		with self.connect() as connection:
			rows = connection.execute(
				"SELECT * FROM application_attempts WHERE job_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
				(job_id, limit),
			).fetchall()
		result: list[dict[str, object]] = []
		for row in rows:
			item = dict(row)
			try:
				item["payload"] = json.loads(str(item["payload"]))
			except json.JSONDecodeError:
				item["payload"] = {}
			item["submitted"] = bool(item["submitted"])
			result.append(item)
		return result

	def count_submitted_today(self) -> int:
		with self.connect() as connection:
			row = connection.execute(
				"SELECT COUNT(*) FROM application_attempts WHERE submitted = 1 AND date(created_at, 'localtime') = date('now', 'localtime')"
			).fetchone()
			return int(row[0]) if row else 0

	def create_batch_run(self, *, keyword: str, location: str, min_score: int, max_applications: int) -> int:
		with self.connect() as connection:
			cursor = connection.execute(
				"INSERT INTO batch_runs(keyword, location, min_score, max_applications) VALUES(?, ?, ?, ?)",
				(keyword, location, min_score, max_applications),
			)
			return int(cursor.lastrowid)

	def update_batch_run(self, run_id: int, **values: object) -> None:
		allowed = {"state", "found", "eligible", "attempted", "submitted", "blocked", "message"}
		parts: list[str] = []
		params: list[object] = []
		for key, value in values.items():
			if key in allowed:
				parts.append(f"{key} = ?")
				params.append(value)
		if not parts:
			return
		parts.append("updated_at = CURRENT_TIMESTAMP")
		params.append(run_id)
		with self.connect() as connection:
			connection.execute(f"UPDATE batch_runs SET {', '.join(parts)} WHERE id = ?", params)

	def list_batch_runs(self, limit: int = 20) -> list[dict[str, object]]:
		with self.connect() as connection:
			rows = connection.execute(
				"SELECT * FROM batch_runs ORDER BY created_at DESC, id DESC LIMIT ?",
				(limit,),
			).fetchall()
		return [dict(row) for row in rows]

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
					COALESCE(SUM(CASE WHEN score >= 85 THEN 1 ELSE 0 END), 0) AS high_match,
					COALESCE(SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END), 0) AS applied,
					COALESCE(SUM(CASE WHEN status = 'saved' THEN 1 ELSE 0 END), 0) AS saved,
					COALESCE(SUM(CASE WHEN status = 'ignored' THEN 1 ELSE 0 END), 0) AS ignored,
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
