from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, HttpUrl, field_validator

from browser_use import Agent, Browser
from job_agent.ai_usage import AIUsageStore, MeteredChatBrowserUse
from job_agent.profile import ProfileStore
from job_agent.scoring import JobPosting, score_job
from job_agent.storage import JobRecord, JobStore


COMPUTRABAJO_URL = "https://co.computrabajo.com/"
DEFAULT_PROFILE_DIR = Path("data/browser-profile")
DEFAULT_BROWSER_MODEL = "bu-latest"


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
	jobs: list[ExtractedJob] = Field(default_factory=list)


class SearchRunStatus(BaseModel):
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
		self.profile_store = ProfileStore(self.store.path)
		self.usage_store = AIUsageStore(self.store.path)
		self.profile_dir = Path(profile_dir)
		self.profile_dir.mkdir(parents=True, exist_ok=True)
		self._lock = threading.Lock()
		self._status = SearchRunStatus()

	def status(self) -> dict[str, object]:
		with self._lock:
			return self._status.model_dump()

	def start(self, request: SearchRequest) -> bool:
		with self._lock:
			if self._status.state == "running":
				return False
			self._status = SearchRunStatus(
				state="running",
				keyword=request.keyword,
				location=request.location,
				message="Abriendo Computrabajo en el navegador local…",
			)
		threading.Thread(target=self._worker, args=(request,), daemon=True, name="computrabajo-search").start()
		return True

	def _worker(self, request: SearchRequest) -> None:
		try:
			result = asyncio.run(self._collect(request))
			persisted = self._persist(result.jobs)
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
				self._status = SearchRunStatus(state="error", keyword=request.keyword, location=request.location, message=str(exc))

	async def _collect(self, request: SearchRequest) -> SearchOutput:
		load_dotenv()
		if not os.getenv("BROWSER_USE_API_KEY"):
			raise RuntimeError("Falta BROWSER_USE_API_KEY. Agrégala al archivo .env para usar Browser Use.")
		browser = Browser(
			user_data_dir=str(self.profile_dir.resolve()),
			headless=False,
			allowed_domains=["co.computrabajo.com"],
		)
		llm = MeteredChatBrowserUse(model=os.getenv("JOB_AGENT_BROWSER_MODEL", DEFAULT_BROWSER_MODEL))
		try:
			agent = Agent(
				task=self._build_task(request),
				llm=llm,
				browser=browser,
				output_model_schema=SearchOutput,
				use_vision="auto",
				extend_system_message=(
					"This is read-only job discovery. Never apply, submit a form, change account data, send messages, "
					"or bypass CAPTCHA, 2FA, bot detection, or access controls. Stop if such a challenge blocks discovery."
				),
			)
			try:
				history = await agent.run(max_steps=60)
			finally:
				self.usage_store.record_safely(
					"search",
					llm.snapshot(),
					metadata={"keyword": request.keyword, "location": request.location},
				)
			output = history.structured_output
			if output is None:
				raise RuntimeError(f"Browser Use no devolvió vacantes estructuradas. Resultado: {(history.final_result() or '')[:300]}")
			return output if isinstance(output, SearchOutput) else SearchOutput.model_validate(output)
		finally:
			await browser.stop()

	@staticmethod
	def _build_task(request: SearchRequest) -> str:
		return f"""
Open {COMPUTRABAJO_URL} and search for jobs in Colombia.
Search term: {request.keyword!r}
Location: {request.location!r}
Collect up to {request.max_results} distinct, recent and relevant jobs.
Return exact title, company, displayed location, useful description/requirements summary, and canonical Computrabajo vacancy URL.
Open vacancy pages only when needed for enough description to score the job later; avoid unnecessary navigation.
Do not apply, do not click any final application/submission button, do not modify the account, and do not send messages.
If CAPTCHA, 2FA, or anti-bot protection blocks the task, stop instead of bypassing it.
Return only actual vacancies on co.computrabajo.com.
""".strip()

	def _persist(self, jobs: list[ExtractedJob]) -> int:
		settings = self.profile_store.get()
		profile = settings.to_candidate_profile()
		preferences = settings.to_search_preferences()
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
			text = f"{item.title} {item.description}".casefold()
			matched_skills = tuple(skill for skill in profile.skills if skill.casefold() in text)
			missing_skills = tuple(skill for skill in profile.skills if skill.casefold() not in text)
			records.append(
				JobRecord(
					id=None,
					source="computrabajo",
					external_id=hashlib.sha256(url.encode("utf-8")).hexdigest()[:24],
					title=item.title,
					company=item.company,
					location=item.location,
					url=url,
					score=match.score,
					band=match.decision,
					status="discovered",
					description=item.description,
					match_reasons=match.reasons,
					matched_skills=matched_skills,
					missing_skills=missing_skills,
				)
			)
		return self.store.upsert_jobs(records)
