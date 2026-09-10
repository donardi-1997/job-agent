from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from job_agent.config import CandidateProfile, SearchPreferences
from job_agent.storage import DEFAULT_DB_PATH


class FrequentAnswer(BaseModel):
	question: str = Field(min_length=1, max_length=500)
	answer: str = Field(min_length=1, max_length=4000)

	@field_validator("question", "answer")
	@classmethod
	def clean_text(cls, value: str) -> str:
		return " ".join(value.strip().split())


class UserProfile(BaseModel):
	"""Locally persisted candidate data used by scoring and automatic applications."""

	target_roles: list[str] = Field(default_factory=lambda: ["Python Developer", "Backend Developer"])
	skills: list[str] = Field(default_factory=lambda: ["Python", "FastAPI", "AWS", "SQL", "Docker"])
	years_experience: float = Field(default=0.0, ge=0, le=50)
	preferred_locations: list[str] = Field(default_factory=lambda: ["Colombia"])
	remote_ok: bool = True
	min_score: int = Field(default=60, ge=0, le=100)
	prepare_application_score: int = Field(default=85, ge=0, le=100)
	excluded_terms: list[str] = Field(default_factory=lambda: ["english c1", "inglés c1"])
	automation_enabled: bool = True

	# User-authored context that complements the uploaded CV. It is not treated as
	# independently verified employment history or as proof of a skill.
	professional_summary: str = Field(default="", max_length=12000)

	# Application-specific facts. Empty means unknown and must never be invented.
	city: str = Field(default="", max_length=160)
	english_level: str = Field(default="", max_length=80)
	salary_expectation: str = Field(default="", max_length=160)
	availability: str = Field(default="", max_length=160)
	preferred_work_modes: list[str] = Field(default_factory=lambda: ["Remoto", "Híbrido"])
	preferred_contract_types: list[str] = Field(default_factory=list)
	frequent_answers: list[FrequentAnswer] = Field(default_factory=list, max_length=50)

	@field_validator(
		"target_roles",
		"skills",
		"preferred_locations",
		"excluded_terms",
		"preferred_work_modes",
		"preferred_contract_types",
	)
	@classmethod
	def clean_list(cls, values: list[str]) -> list[str]:
		cleaned: list[str] = []
		seen: set[str] = set()
		for value in values:
			item = " ".join(value.strip().split())
			key = item.casefold()
			if item and key not in seen:
				seen.add(key)
				cleaned.append(item)
		return cleaned

	@field_validator("city", "english_level", "salary_expectation", "availability")
	@classmethod
	def clean_optional_text(cls, value: str) -> str:
		return " ".join(value.strip().split())

	@field_validator("professional_summary")
	@classmethod
	def clean_professional_summary(cls, value: str) -> str:
		# Preserve paragraph boundaries while removing accidental trailing spaces.
		lines = [line.strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
		cleaned: list[str] = []
		previous_blank = False
		for line in lines:
			if line:
				cleaned.append(line)
				previous_blank = False
			elif cleaned and not previous_blank:
				cleaned.append("")
				previous_blank = True
		return "\n".join(cleaned).strip()

	@model_validator(mode="after")
	def validate_thresholds(self) -> UserProfile:
		if self.prepare_application_score < self.min_score:
			raise ValueError("prepare_application_score must be greater than or equal to min_score")
		return self

	def to_candidate_profile(self) -> CandidateProfile:
		return CandidateProfile(
			target_roles=tuple(self.target_roles),
			skills=tuple(self.skills),
			years_experience=self.years_experience,
			preferred_locations=tuple(self.preferred_locations),
			remote_ok=self.remote_ok,
		)

	def to_search_preferences(self) -> SearchPreferences:
		return SearchPreferences(
			keywords=tuple(self.target_roles),
			locations=tuple(self.preferred_locations),
			remote_ok=self.remote_ok,
			min_score=self.min_score,
			prepare_application_score=self.prepare_application_score,
			excluded_terms=tuple(self.excluded_terms),
			auto_submit=self.automation_enabled,
		)


class ProfileStore:
	"""Stores one local profile inside the same SQLite database used by Job Agent."""

	def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
		self.path = Path(path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		with self._connect() as connection:
			connection.execute(
				"CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
			)

	def _connect(self) -> sqlite3.Connection:
		return sqlite3.connect(self.path)

	def get(self) -> UserProfile:
		with self._connect() as connection:
			row = connection.execute("SELECT value FROM app_settings WHERE key = 'profile'").fetchone()
		if not row:
			return UserProfile()
		return UserProfile.model_validate(json.loads(row[0]))

	def save(self, profile: UserProfile) -> UserProfile:
		payload = profile.model_dump_json()
		with self._connect() as connection:
			connection.execute(
				"""
				INSERT INTO app_settings(key, value, updated_at) VALUES('profile', ?, CURRENT_TIMESTAMP)
				ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
				""",
				(payload,),
			)
		return profile
