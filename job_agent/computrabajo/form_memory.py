from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from job_agent.answer_memory import normalize_question
from job_agent.computrabajo.deterministic_application import ObservedField
from job_agent.storage import DEFAULT_DB_PATH


def form_fingerprint(fields: tuple[ObservedField, ...]) -> str:
    """Build a stable fingerprint from semantic form structure, not brittle selectors."""
    if not fields:
        return ""
    payload = [
        {
            "question": normalize_question(field.question),
            "type": field.field_type,
            "options": [normalize_question(option) for option in field.options],
            "required": bool(field.required),
        }
        for field in fields
        if field.field_type != "password" and normalize_question(field.question)
    ]
    if not payload:
        return ""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class ApplicationFormMemory:
    """Remember Computrabajo form shapes and which ones led to confirmed submissions."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS application_form_fingerprints (
                    fingerprint TEXT PRIMARY KEY,
                    fields_json TEXT NOT NULL DEFAULT '[]',
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    successful_uses INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_application_form_success
                    ON application_form_fingerprints(successful_uses DESC, last_seen_at DESC);
                """
            )

    @staticmethod
    def _payload(fields: tuple[ObservedField, ...]) -> str:
        return json.dumps(
            [
                {
                    "question": field.question,
                    "field_type": field.field_type,
                    "options": list(field.options),
                    "required": field.required,
                }
                for field in fields
                if field.field_type != "password"
            ],
            ensure_ascii=False,
        )

    def observe(self, fields: tuple[ObservedField, ...]) -> str:
        fingerprint = form_fingerprint(fields)
        if not fingerprint:
            return ""
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO application_form_fingerprints(
                    fingerprint, fields_json, seen_count, successful_uses,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES(?, ?, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    fields_json=excluded.fields_json,
                    seen_count=application_form_fingerprints.seen_count + 1,
                    last_seen_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (fingerprint, self._payload(fields)),
            )
        return fingerprint

    def confirm_success(self, fields: tuple[ObservedField, ...]) -> str:
        fingerprint = form_fingerprint(fields)
        if not fingerprint:
            return ""
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO application_form_fingerprints(
                    fingerprint, fields_json, seen_count, successful_uses,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES(?, ?, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    fields_json=excluded.fields_json,
                    successful_uses=application_form_fingerprints.successful_uses + 1,
                    last_seen_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (fingerprint, self._payload(fields)),
            )
        return fingerprint

    def is_proven(self, fields: tuple[ObservedField, ...]) -> bool:
        fingerprint = form_fingerprint(fields)
        if not fingerprint:
            return False
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT successful_uses FROM application_form_fingerprints WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        return bool(row and int(row[0]) > 0)

    def stats(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(CASE WHEN successful_uses > 0 THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(seen_count), 0),
                       COALESCE(SUM(successful_uses), 0)
                FROM application_form_fingerprints
                """
            ).fetchone()
        return {
            "forms": int(row[0]) if row else 0,
            "proven_forms": int(row[1]) if row else 0,
            "form_observations": int(row[2]) if row else 0,
            "form_successful_uses": int(row[3]) if row else 0,
        }
