from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, HttpUrl, field_validator

from browser_use import Agent, Browser, ChatBrowserUse
from job_agent.config import CandidateProfile, SearchPreferences
from job_agent.scoring import JobPosting, score_job
from job_agent.storage import JobRecord, JobStore


COMPUTRABAJO_URL = "https://co.computrabajo.com/"
DEFAULT_PROFILE_DIR = Path("data/browser-profile")


class SearchRequest(BaseModel):
	"""Validated user input for one Computrabajo discovery run."""

	keyword: str = Field(min_length=2, max_length=120)
	location: str = Field(default="Colombia", min_length=2, max_length=120)
	max_results: int = Field(default=20, ge=1, le=50)

	@field_validator("keyword", "location")
	@classmethod
	def normalize_text(cls, value: str) -> str:
		return " ".join(value.strip().split())


class ExtractedJob(BaseModel):
	"""One job vacancy extracted from Computrabajo by Browser Use."""

	title: str
	company: str = ""
	location: str = ""
	description: str = ""
	url: HttpUrl


class SearchOutput(BaseModel):
	"""Structured Browser Use output for a Computrabajo search."""

	jobs: list[ExtractedJob] = Field(default_factory=list)


class SearchRunStatus(BaseModel):
	"""Observable state for the dashboard while a search runs."""

	state: Literal["idle", "running", "completed", "error"] = "idle"
	keyword: str = ""
	location: str = ""
	found: int = 0
	persisted: int = 0
	message: str = ""


class ComputrabajoCollector:
	"""Runs local Browser Use discovery jobs and persists normalized vacancies."""

	def __init__(self, store: JobStore | None = None, profile_dir: Path | str = DEFAULT_PROFILE_DIR) -> None:
		self.store = store or JobStore()
		self.profile_dir = Path(profile_dir)
		self.profile_dir.mkdir(parents=True, exist_ok=True)
		self._lock = threading.Lock()
		self._status = SearchRunStatus()

	def status(self) -> dict[str, object]:
		with self._lock:
			return self._status.model_dump()

	def start(self, request: SearchRequest) -> bool:
		"""Start one background search. Returns False if another search is already running."""

		with self._lock:
			if self._status.state == "running":
				return False
			self._status = SearchRunStatus(
				state="running",
				keyword=request.keyword,
				location=request.location,
				message="Abriendo Computrabajo en el navegador local…",
			)

		thread = threading.Thread(target=self._worker, args=(request,), daemon=True, name="computrabajo-search")
		thread.start()
		return True

	def _worker(self, request: SearchRequest) -> None:
		try:
			result = asyncio.run(self._collect(request))
			persisted = self._persist(result.jobs, request)
			with self._lock:
				self._status = SearchRunStatus(
					state="completed",
					keyword=request.keyword,
					location=request.location,
					found=len(result.jobs),
					persisted=persisted,
					message=f"Búsqueda terminada: {len(result.jobs)} vacantes encontradas.",
				)
		except Exception as exc:
			with self._lock:
				self._status = SearchRunStatus(
					state="error",
					keyword=request.keyword,
					location=request.location,
					message=str(exc),
				)

	async def _collect(self, request: SearchRequest) -> SearchOutput:
		load_dotenv()
		if not os.getenv("BROWSER_USE_API_KEY"):
			raise RuntimeError(
				"Falta BROWSER_USE_API_KEY. Agrégala al archivo .env para usar el agente de Browser Use."
			)

		browser = Browser(
			user_data_dir=str(self.profile_dir.resolve()),
			headless=False,
			allowed_domains=["co.computrabajo.com"],
		)
		try:
			task = self._build_task(request)
			agent = Agent(
				task=task,
				llm=ChatBrowserUse(),
				browser=browser,
				output_model_schema=SearchOutput,
				use_vision="auto",
				extend_system_message=(
					"This is a read-only job discovery task. Never apply to a job, never submit a form, "
					"never change account data, and never attempt to bypass CAPTCHA, 2FA, bot detection, "
					"or any access control. If a challenge blocks discovery, stop and report it."
				),
			)
			history = await agent.run(max_steps=60)
			output = history.structured_output
			if output is None:
				final_result = history.final_result() or ""
				raise RuntimeError(f"Browser Use no devolvió vacantes estructuradas. Resultado: {final_result[:300]}")
			if isinstance(output, SearchOutput):
				return output
			return SearchOutput.model_validate(output)
		finally:
			await browser.stop()

	@staticmethod
	def _build_task(request: SearchRequest) -> str:
		return f"""
Open {COMPUTRABAJO_URL} and search for jobs in Colombia.
Search term: {request.keyword!r}
Location: {request.location!r}

Collect up to {request.max_results} distinct jobs from the search results, prioritizing recent and relevant results.
For every result return: exact job title, company, displayed location, a useful job-description/re requirements summary, and the canonical Computrabajo vacancy URL.
Open individual vacancy pages when needed to capture enough description for later matching.
Do not apply, do not click any final application/submission button, do not modify the user's account, and do not send messages.
If login is requested but browsing public results is still possible, continue without logging in.
If CAPTCHA, 2FA, or an anti-bot challenge blocks the task, stop instead of trying to bypass it.
Return only data that belongs to actual job vacancies on co.computrabajo.com.
""".strip()

	def _persist(self, jobs: list[ExtractedJob], request: SearchRequest) -> int:
		profile = self._profile_from_env(request)
		preferences = SearchPreferences()
		records: list[JobRecord] = []
		for item in jobs:
			url = str(item.url)
			posting = JobPosting(
				title=item.title,
				company=item.company,
				location=item.location,
				description=item.description,
				url=url,
			)
			match = score_job(posting, profile, preferences)
			external_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
			records.append(
				JobRecord(
					id=None,
					source="computrabajo",
					external_id=external_id,
					title=item.title,
					company=item.company,
					location=item.location,
					url=url,
					score=match.score,
					band=match.decision,
					status="discovered",
				)
			)
		return self.store.upsert_jobs(records)

	@staticmethod
	def _profile_from_env(request: SearchRequest) -> CandidateProfile:
		roles = tuple(
			part.strip() for part in os.getenv("JOB_AGENT_TARGET_ROLES", request.keyword).split(",") if part.strip()
		)
		skills = tuple(part.strip() for part in os.getenv("JOB_AGENT_SKILLS", "").split(",") if part.strip())
		locations = tuple(
			part.strip() for part in os.getenv("JOB_AGENT_LOCATIONS", request.location).split(",") if part.strip()
		)
		return CandidateProfile(
			target_roles=roles,
			skills=skills,
			preferred_locations=locations,
			remote_ok=True,
		)
