from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = Path("data/job-agent.db")
ALLOWED_STATUSES = {"discovered", "saved", "applied", "ignored"}
QUEUE_STATES = {"scored", "shortlisted", "ready", "applying", "applied", "blocked", "needs_user", "ignored"}


class ApplicationModeStore:
	"""Persist the local application safety mode in the shared settings table."""

	ALLOWED_MODES = {"test", "real"}

	def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
		self.path = Path(path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		with sqlite3.connect(self.path) as connection:
			connection.execute(
				"""
				CREATE TABLE IF NOT EXISTS app_settings (
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL,
					updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
				)
				"""
			)

	def get(self) -> str:
		with sqlite3.connect(self.path) as connection:
			row = connection.execute("SELECT value FROM app_settings WHERE key = 'application_mode'").fetchone()
		return str(row[0]) if row and row[0] in self.ALLOWED_MODES else "test"

	def set(self, mode: str) -> str:
		if mode not in self.ALLOWED_MODES:
			raise ValueError("mode must be 'test' or 'real'")
		with sqlite3.connect(self.path) as connection:
			connection.execute(
				"""
				INSERT INTO app_settings(key, value, updated_at)
				VALUES('application_mode', ?, CURRENT_TIMESTAMP)
				ON CONFLICT(key) DO UPDATE SET
					value = excluded.value,
					updated_at = CURRENT_TIMESTAMP
				""",
				(mode,),
			)
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
		self.reconcile_application_statuses()

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
					first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					times_seen INTEGER NOT NULL DEFAULT 1,
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

				CREATE TABLE IF NOT EXISTS application_queue (
					job_id INTEGER PRIMARY KEY,
					state TEXT NOT NULL DEFAULT 'scored',
					priority INTEGER NOT NULL DEFAULT 0,
					reason TEXT NOT NULL DEFAULT '',
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
				);
				CREATE INDEX IF NOT EXISTS idx_application_queue_state_priority
					ON application_queue(state, priority DESC, updated_at DESC);

				CREATE TABLE IF NOT EXISTS search_checkpoints (
					source TEXT NOT NULL,
					keyword_normalized TEXT NOT NULL,
					location_normalized TEXT NOT NULL,
					last_run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					found INTEGER NOT NULL DEFAULT 0,
					new_jobs INTEGER NOT NULL DEFAULT 0,
					PRIMARY KEY(source, keyword_normalized, location_normalized)
				);

				CREATE TABLE IF NOT EXISTS job_discovery_terms (
					job_id INTEGER NOT NULL,
					keyword_normalized TEXT NOT NULL,
					location_normalized TEXT NOT NULL,
					last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					PRIMARY KEY(job_id, keyword_normalized, location_normalized),
					FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
				);
				CREATE INDEX IF NOT EXISTS idx_job_discovery_terms_lookup
					ON job_discovery_terms(keyword_normalized, location_normalized, last_seen_at DESC);

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
				"first_seen_at": "ALTER TABLE jobs ADD COLUMN first_seen_at TEXT NOT NULL DEFAULT ''",
				"last_seen_at": "ALTER TABLE jobs ADD COLUMN last_seen_at TEXT NOT NULL DEFAULT ''",
				"times_seen": "ALTER TABLE jobs ADD COLUMN times_seen INTEGER NOT NULL DEFAULT 1",
			}
			for column, statement in migrations.items():
				if column not in columns:
					connection.execute(statement)
			connection.execute("UPDATE jobs SET first_seen_at = created_at WHERE first_seen_at = ''")
			connection.execute("UPDATE jobs SET last_seen_at = created_at WHERE last_seen_at = ''")

	@staticmethod
	def _decode_row(row: sqlite3.Row) -> dict[str, object]:
		data = dict(row)
		for key in ("match_reasons", "matched_skills", "missing_skills"):
			try:
				data[key] = json.loads(str(data.get(key) or "[]"))
			except json.JSONDecodeError:
				data[key] = []
		return data

	@staticmethod
	def _payload_confirms_real_submission(payload: dict[str, object]) -> bool:
		"""Recognize positive submission evidence while never promoting TEST attempts."""
		mode = str(payload.get("mode") or "").strip().casefold()
		if mode == "test" or bool(payload.get("test_mode")):
			return False
		if bool(payload.get("submitted")):
			return True
		status = str(payload.get("submission_status") or "").strip().casefold()
		if status in {"submitted", "already_applied"}:
			return True
		confirmation = " ".join(str(payload.get("confirmation_text") or "").casefold().split())
		markers = (
			"postulación enviada",
			"postulacion enviada",
			"postulación realizada",
			"postulacion realizada",
			"candidatura enviada",
			"aplicación enviada",
			"aplicacion enviada",
			"te has postulado correctamente",
			"postulación exitosa",
			"postulacion exitosa",
			"ya te postulaste",
			"ya has aplicado",
			"ya estás postulado",
			"ya estas postulado",
		)
		return any(marker in confirmation for marker in markers)

	def reconcile_application_statuses(self) -> int:
		"""Repair attempts/jobs whose persisted non-TEST evidence already proves submission."""
		with self.connect() as connection:
			rows = connection.execute(
				"SELECT id, job_id, payload, submitted, submission_status, confirmation_text FROM application_attempts"
			).fetchall()
			confirmed_attempts: list[tuple[int, int]] = []
			for row in rows:
				try:
					payload = json.loads(str(row["payload"] or "{}"))
				except json.JSONDecodeError:
					payload = {}
				if not isinstance(payload, dict):
					payload = {}
				payload.setdefault("submitted", bool(row["submitted"]))
				payload.setdefault("submission_status", str(row["submission_status"] or ""))
				payload.setdefault("confirmation_text", str(row["confirmation_text"] or ""))
				if self._payload_confirms_real_submission(payload):
					confirmed_attempts.append((int(row["id"]), int(row["job_id"])))

			repaired = 0
			for attempt_id, job_id in confirmed_attempts:
				attempt_cursor = connection.execute(
					"UPDATE application_attempts SET submitted = 1 WHERE id = ? AND submitted = 0",
					(attempt_id,),
				)
				job_cursor = connection.execute(
					"UPDATE jobs SET status = 'applied' WHERE id = ? AND status <> 'applied'",
					(job_id,),
				)
				repaired += max(0, attempt_cursor.rowcount) + max(0, job_cursor.rowcount)
			return repaired

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
						description, match_reasons, matched_skills, missing_skills,
						first_seen_at, last_seen_at, times_seen
					)
					VALUES(
						:source, :external_id, :title, :company, :location, :url, :score, :band, :status,
						:description, :match_reasons, :matched_skills, :missing_skills,
						CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1
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
						missing_skills=excluded.missing_skills,
						last_seen_at=CURRENT_TIMESTAMP,
						times_seen=jobs.times_seen + 1
					""",
					data,
				)
				count += 1
		return count

	@staticmethod
	def _normalize_search_value(value: object) -> str:
		return " ".join(str(value or "").casefold().split())

	def existing_external_ids(self, source: str, external_ids: Iterable[str]) -> set[str]:
		values = [str(value) for value in external_ids if str(value)]
		if not values:
			return set()
		placeholders = ",".join("?" for _ in values)
		with self.connect() as connection:
			rows = connection.execute(
				f"SELECT external_id FROM jobs WHERE source = ? AND external_id IN ({placeholders})",
				[source, *values],
			).fetchall()
		return {str(row["external_id"]) for row in rows}

	def record_job_discovery_terms(
		self,
		*,
		source: str,
		external_ids: Iterable[str],
		keyword: str,
		location: str,
	) -> None:
		values = [str(value) for value in external_ids if str(value)]
		if not values:
			return
		keyword_key = self._normalize_search_value(keyword)
		location_key = self._normalize_search_value(location)
		placeholders = ",".join("?" for _ in values)
		with self.connect() as connection:
			rows = connection.execute(
				f"SELECT id FROM jobs WHERE source = ? AND external_id IN ({placeholders})",
				[source, *values],
			).fetchall()
			for row in rows:
				connection.execute(
					"""
					INSERT INTO job_discovery_terms(job_id, keyword_normalized, location_normalized, last_seen_at)
					VALUES(?, ?, ?, CURRENT_TIMESTAMP)
					ON CONFLICT(job_id, keyword_normalized, location_normalized) DO UPDATE SET
						last_seen_at=CURRENT_TIMESTAMP
					""",
					(int(row["id"]), keyword_key, location_key),
				)

	def jobs_for_search_term(
		self,
		*,
		keyword: str,
		location: str,
		max_age_hours: int = 72,
	) -> list[dict[str, object]]:
		keyword_key = self._normalize_search_value(keyword)
		location_key = self._normalize_search_value(location)
		age = f"-{max(1, int(max_age_hours))} hours"
		with self.connect() as connection:
			rows = connection.execute(
				"""
				SELECT j.*
				FROM job_discovery_terms d
				JOIN jobs j ON j.id = d.job_id
				WHERE d.keyword_normalized = ?
				  AND d.location_normalized = ?
				  AND datetime(d.last_seen_at) >= datetime('now', ?)
				ORDER BY j.score DESC, j.last_seen_at DESC
				""",
				(keyword_key, location_key, age),
			).fetchall()
		return [self._decode_row(row) for row in rows]

	def search_due(
		self,
		*,
		source: str,
		keyword: str,
		location: str,
		refresh_after_hours: int = 6,
	) -> bool:
		keyword_key = self._normalize_search_value(keyword)
		location_key = self._normalize_search_value(location)
		with self.connect() as connection:
			row = connection.execute(
				"""
				SELECT last_run_at FROM search_checkpoints
				WHERE source = ? AND keyword_normalized = ? AND location_normalized = ?
				""",
				(source, keyword_key, location_key),
			).fetchone()
		if not row:
			return True
		with self.connect() as connection:
			fresh = connection.execute(
				"SELECT datetime(?) > datetime('now', ?)",
				(str(row["last_run_at"]), f"-{max(0, int(refresh_after_hours))} hours"),
			).fetchone()
		return not bool(fresh and fresh[0])

	def record_search_checkpoint(
		self,
		*,
		source: str,
		keyword: str,
		location: str,
		found: int,
		new_jobs: int,
	) -> None:
		keyword_key = self._normalize_search_value(keyword)
		location_key = self._normalize_search_value(location)
		with self.connect() as connection:
			connection.execute(
				"""
				INSERT INTO search_checkpoints(
					source, keyword_normalized, location_normalized, last_run_at, found, new_jobs
				) VALUES(?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
				ON CONFLICT(source, keyword_normalized, location_normalized) DO UPDATE SET
					last_run_at=CURRENT_TIMESTAMP,
					found=excluded.found,
					new_jobs=excluded.new_jobs
				""",
				(source, keyword_key, location_key, int(found), int(new_jobs)),
			)

	def queue_job(self, job_id: int, state: str, *, priority: int = 0, reason: str = "") -> None:
		if state not in QUEUE_STATES:
			raise ValueError(f"Unsupported queue state: {state}")
		with self.connect() as connection:
			connection.execute(
				"""
				INSERT INTO application_queue(job_id, state, priority, reason, created_at, updated_at)
				VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
				ON CONFLICT(job_id) DO UPDATE SET
					state=excluded.state,
					priority=excluded.priority,
					reason=excluded.reason,
					updated_at=CURRENT_TIMESTAMP
				""",
				(job_id, state, int(priority), str(reason)[:1000]),
			)

	def refresh_application_queue(self, *, min_score: int = 75, ready_score: int = 85) -> int:
		jobs = self.list_jobs(limit=10000)
		count = 0
		for job in jobs:
			job_id = int(job["id"])
			status = str(job.get("status") or "discovered")
			score = int(job.get("score") or 0)
			if status == "applied":
				state, reason = "applied", "Postulación ya confirmada."
			elif status == "ignored":
				state, reason = "ignored", "Vacante descartada por el usuario."
			elif score >= ready_score:
				state, reason = "ready", f"Score {score} ≥ {ready_score}; lista para postular."
			elif score >= min_score:
				state, reason = "shortlisted", f"Score {score} ≥ {min_score}; preseleccionada."
			else:
				state, reason = "scored", f"Score {score}; no consume navegador todavía."
			self.queue_job(job_id, state, priority=score * 100, reason=reason)
			count += 1
		return count

	def list_application_queue(self, *, limit: int = 100, state: str | None = None) -> list[dict[str, object]]:
		query = """
			SELECT q.state AS queue_state, q.priority, q.reason AS queue_reason,
			       q.updated_at AS queue_updated_at, j.*
			FROM application_queue q
			JOIN jobs j ON j.id = q.job_id
		"""
		params: list[object] = []
		if state:
			query += " WHERE q.state = ?"
			params.append(state)
		query += " ORDER BY q.priority DESC, j.last_seen_at DESC LIMIT ?"
		params.append(limit)
		with self.connect() as connection:
			rows = connection.execute(query, params).fetchall()
		return [self._decode_row(row) for row in rows]

	def queue_stats(self) -> dict[str, int]:
		with self.connect() as connection:
			rows = connection.execute(
				"SELECT state, COUNT(*) AS total FROM application_queue GROUP BY state"
			).fetchall()
		result = {state: 0 for state in QUEUE_STATES}
		for row in rows:
			result[str(row["state"])] = int(row["total"])
		return result

	def get_job(self, job_id: int) -> dict[str, object] | None:
		with self.connect() as connection:
			row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
		return self._decode_row(row) if row else None

	def update_status(self, job_id: int, status: str) -> dict[str, object] | None:
		if status not in ALLOWED_STATUSES:
			raise ValueError(f"Unsupported status: {status}")
		with self.connect() as connection:
			row = connection.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
			if not row:
				return None
			current = str(row["status"])
			if current == "applied" and status != "applied":
				raise ValueError("Una vacante con postulación confirmada no puede volver a un estado anterior.")
			connection.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
		queue_state = "applied" if status == "applied" else "ignored" if status == "ignored" else "shortlisted" if status == "saved" else "scored"
		self.queue_job(job_id, queue_state, priority=int((self.get_job(job_id) or {}).get("score") or 0) * 100, reason=f"Estado de vacante: {status}.")
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
		confirmed = self._payload_confirms_real_submission(payload)
		stored_payload = dict(payload)
		if confirmed:
			stored_payload["submitted"] = True
			if str(stored_payload.get("submission_status") or "") not in {"submitted", "already_applied"}:
				stored_payload["submission_status"] = "submitted"
		with self.connect() as connection:
			cursor = connection.execute(
				"""
				INSERT INTO application_attempts(
					job_id, payload, submitted, submission_status, confirmation_text, confirmation_url
				) VALUES (?, ?, ?, ?, ?, ?)
				""",
				(
					job_id,
					json.dumps(stored_payload, ensure_ascii=False),
					1 if confirmed else 0,
					str(stored_payload.get("submission_status") or "not_submitted"),
					str(stored_payload.get("confirmation_text") or ""),
					str(stored_payload.get("confirmation_url") or ""),
				),
			)
			if confirmed:
				connection.execute("UPDATE jobs SET status = 'applied' WHERE id = ?", (job_id,))
				connection.execute(
					"""
					INSERT INTO application_queue(job_id, state, priority, reason, created_at, updated_at)
					VALUES(?, 'applied', 10000, 'Postulación confirmada.', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
					ON CONFLICT(job_id) DO UPDATE SET
						state='applied', priority=10000, reason='Postulación confirmada.', updated_at=CURRENT_TIMESTAMP
					""",
					(job_id,),
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
		query += " ORDER BY score DESC, last_seen_at DESC, created_at DESC LIMIT ?"
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
			result = dict(row) if row else {
				"total": 0,
				"high_match": 0,
				"applied": 0,
				"saved": 0,
				"ignored": 0,
				"avg_score": 0,
			}
			queue = self.queue_stats()
			result["queue_ready"] = queue.get("ready", 0)
			result["queue_needs_user"] = queue.get("needs_user", 0)
			return result
