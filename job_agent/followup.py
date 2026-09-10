from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from job_agent.storage import DEFAULT_DB_PATH


ContactStatus = Literal["pending", "contacted", "no_contact"]


class ContactUpdate(BaseModel):
	status: ContactStatus = "pending"
	channel: str = Field(default="", max_length=80)
	note: str = Field(default="", max_length=2000)
	contacted_at: str = Field(default="", max_length=40)

	@field_validator("channel", "note", "contacted_at")
	@classmethod
	def clean_text(cls, value: str) -> str:
		return " ".join(value.strip().split())


class ContactTracker:
	"""Stores personal follow-up outcomes for submitted job applications."""

	def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
		self.path = Path(path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		with self._connect() as connection:
			connection.executescript(
				"""
				CREATE TABLE IF NOT EXISTS application_contacts (
					job_id INTEGER PRIMARY KEY,
					status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','contacted','no_contact')),
					channel TEXT NOT NULL DEFAULT '',
					note TEXT NOT NULL DEFAULT '',
					contacted_at TEXT NOT NULL DEFAULT '',
					created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
				);
				CREATE INDEX IF NOT EXISTS idx_application_contacts_status ON application_contacts(status);
				"""
			)

	def _connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(self.path)
		connection.row_factory = sqlite3.Row
		return connection

	def get(self, job_id: int) -> dict[str, object]:
		with self._connect() as connection:
			row = connection.execute("SELECT * FROM application_contacts WHERE job_id = ?", (job_id,)).fetchone()
		if row:
			return dict(row)
		return {
			"job_id": job_id,
			"status": "pending",
			"channel": "",
			"note": "",
			"contacted_at": "",
		}

	def save(self, job_id: int, update: ContactUpdate) -> dict[str, object]:
		with self._connect() as connection:
			job = connection.execute("SELECT id, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
			if not job:
				raise ValueError("Vacante no encontrada.")
			if str(job["status"]) != "applied":
				raise ValueError("Solo puedes registrar seguimiento de una vacante postulada.")
			contacted_at = update.contacted_at if update.status == "contacted" else ""
			connection.execute(
				"""
				INSERT INTO application_contacts(job_id, status, channel, note, contacted_at, created_at, updated_at)
				VALUES(?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
				ON CONFLICT(job_id) DO UPDATE SET
					status=excluded.status,
					channel=excluded.channel,
					note=excluded.note,
					contacted_at=excluded.contacted_at,
					updated_at=CURRENT_TIMESTAMP
				""",
				(job_id, update.status, update.channel, update.note, contacted_at),
			)
		return self.get(job_id)

	def stats(self) -> dict[str, object]:
		with self._connect() as connection:
			row = connection.execute(
				"""
				SELECT
					COUNT(*) AS applied,
					COALESCE(SUM(CASE WHEN c.status = 'contacted' THEN 1 ELSE 0 END), 0) AS contacted,
					COALESCE(SUM(CASE WHEN c.status = 'no_contact' THEN 1 ELSE 0 END), 0) AS no_contact,
					COALESCE(SUM(CASE WHEN c.status IS NULL OR c.status = 'pending' THEN 1 ELSE 0 END), 0) AS pending
				FROM jobs j
				LEFT JOIN application_contacts c ON c.job_id = j.id
				WHERE j.status = 'applied'
				"""
			).fetchone()
		applied = int(row["applied"] or 0)
		contacted = int(row["contacted"] or 0)
		resolved = contacted + int(row["no_contact"] or 0)
		return {
			"applied": applied,
			"contacted": contacted,
			"no_contact": int(row["no_contact"] or 0),
			"pending": int(row["pending"] or 0),
			"contact_rate_pct": round((contacted / resolved * 100), 1) if resolved else 0.0,
		}
