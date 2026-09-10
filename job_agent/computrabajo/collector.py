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
from job_agent.ai_usage import AIUsageBudget, AIUsageStore, MeteredChatBrowserUse, UsageSnapshot
from job_agent.computrabajo.browser_config import allowed_domains
from job_agent.computrabajo.deterministic import DeterministicComputrabajoSearch, SearchExecutionStore
from job_agent.computrabajo.job_validation import is_valid_computrabajo_job
from job_agent.profile import ProfileStore
from job_agent.scoring import JobPosting, score_job
from job_agent.storage import JobRecord, JobStore


COMPUTRABAJO_URL = "https://co.computrabajo.com/"
DEFAULT_PROFILE_DIR = Path("data/browser-profile")
DEFAULT_BROWSER_MODEL = "bu-latest"
DEFAULT_SEARCH_AI_MAX_STEPS = 20


class SearchRequest(BaseModel):
	"""Validated user input for one Computrabajo discovery run."""

	keyword: str = Field(min_length=2, max_length=120)
	location: str = Field(default="Colombia", min_length=2, max_length=120)
	max_results: int = Field(default=20, ge=1, le=50)
	allow_ai_fallback: bool = False

	@field_validator("keyword", "location")
	@classmethod
	def normalize_text(cls, value: str) -> str:
		return " ".join(value.strip().split())


class ExtractedJob(BaseModel):
	"""One normalized Computrabajo vacancy."""

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
	mode: Literal["", "deterministic", "ai_fallback"] = ""
	fallback_reason: str = ""
	message: str = ""


class ComputrabajoCollector:
	"""Discover vacancies locally first, using an LLM only as an opt-in bounded fallback."""

	def __init__(self, store: JobStore | None = None, profile_dir: Path | str = DEFAULT_PROFILE_DIR) -> None:
		self.store = store or JobStore()
		self.profile_store = ProfileStore(self.store.path)
		self.usage_store = AIUsageStore(self.store.path)
		self.search_execution_store = SearchExecutionStore(self.store.path)
		self.profile_dir = Path(profile_dir)
		self.profile_dir.mkdir(parents=True, exist_ok=True)
		self.deterministic_search = DeterministicComputrabajoSearch(self.profile_dir)
		self._lock = threading.Lock()
		self._status = SearchRunStatus()
		self._last_collection_mode: Literal["", "deterministic", "ai_fallback"] = ""
		self._last_fallback_reason = ""

	def status(self) -> dict[str, object]:
		with self._lock:
			return self._status.model_dump()

	def last_collection_info(self) -> dict[str, str]:
		return {"mode": self._last_collection_mode, "fallback_reason": self._last_fallback_reason}

	def search_efficiency(self) -> dict[str, object]:
		return self.search_execution_store.summary()

	def start(self, request: SearchRequest) -> bool:
		with self._lock:
			if self._status.state == "running":
				return False
			self._status = SearchRunStatus(
				state="running",
				keyword=request.keyword,
				location=request.location,
				message="Buscando primero con extracción local sin IA…",
			)
		threading.Thread(target=self._worker, args=(request,), daemon=True, name="computrabajo-search").start()
		return True

	def _worker(self, request: SearchRequest) -> None:
		try:
			result = asyncio.run(self._collect(request))
			persisted = self._persist(result.jobs)
			info = self.last_collection_info()
			mode = info["mode"]
			label = "sin IA" if mode == "deterministic" else "con fallback de IA"
			with self._lock:
				self._status = SearchRunStatus(
					state="completed",
					keyword=request.keyword,
					location=request.location,
					found=len(result.jobs),
					persisted=persisted,
					mode=mode,
					fallback_reason=info["fallback_reason"],
					message=f"Búsqueda terminada {label}: {len(result.jobs)} vacantes encontradas.",
				)
		except Exception as exc:
			info = self.last_collection_info()
			with self._lock:
				self._status = SearchRunStatus(
					state="error",
					keyword=request.keyword,
					location=request.location,
					mode=info["mode"],
					fallback_reason=info["fallback_reason"],
					message=str(exc),
				)

	def _record_search_execution(self, request: SearchRequest, mode: str, found: int, fallback_reason: str = "") -> None:
		try:
			self.search_execution_store.record(
				keyword=request.keyword,
				location=request.location,
				mode=mode,
				found=found,
				fallback_reason=fallback_reason,
			)
		except Exception:
			# Telemetry must never break job discovery.
			pass

	@staticmethod
	def _valid_jobs(jobs: list[ExtractedJob], limit: int | None = None) -> list[ExtractedJob]:
		valid: list[ExtractedJob] = []
		for item in jobs:
			if not is_valid_computrabajo_job(
				title=item.title,
				url=str(item.url),
				description=item.description,
			):
				continue
			valid.append(item)
			if limit is not None and len(valid) >= limit:
				break
		return valid

	async def _collect(
		self,
		request: SearchRequest,
		*,
		ai_budget: AIUsageBudget | None = None,
	) -> SearchOutput:
		"""Try deterministic Chrome/CDP extraction, then optionally fall back to Browser Use AI."""
		load_dotenv()
		self._last_collection_mode = ""
		self._last_fallback_reason = ""
		fallback_reason = ""
		try:
			deterministic = await self.deterministic_search.collect(
				keyword=request.keyword,
				location=request.location,
				max_results=request.max_results,
			)
			if deterministic.jobs:
				output = SearchOutput(
					jobs=[
						ExtractedJob(
							title=job.title,
							company=job.company,
							location=job.location,
							description=job.description,
							url=job.url,
						)
						for job in deterministic.jobs
					]
				)
				output = SearchOutput(jobs=self._valid_jobs(output.jobs, request.max_results))
				if output.jobs:
					self._last_collection_mode = "deterministic"
					self._record_search_execution(request, "deterministic", len(output.jobs))
					return output
			fallback_reason = deterministic.reason or "La extracción determinística no devolvió vacantes válidas."
		except Exception as exc:
			fallback_reason = f"{type(exc).__name__}: {exc}"

		self._last_fallback_reason = fallback_reason
		# Search AI is opt-in per request, with an environment override retained for
		# unattended/manual power users. The batch never opts in by default.
		env_fallback = os.getenv("JOB_AGENT_SEARCH_AI_FALLBACK", "0").strip().casefold() not in {"0", "false", "no", "off"}
		fallback_enabled = request.allow_ai_fallback or env_fallback
		if not fallback_enabled:
			raise RuntimeError(f"Búsqueda local sin resultados y fallback de IA desactivado. {fallback_reason}")
		if not os.getenv("BROWSER_USE_API_KEY"):
			raise RuntimeError(
				"La búsqueda determinística no pudo extraer vacantes y no hay BROWSER_USE_API_KEY para el fallback de IA. "
				f"Detalle: {fallback_reason}"
			)

		output = await self._collect_with_ai(request, ai_budget=ai_budget)
		self._last_collection_mode = "ai_fallback"
		self._record_search_execution(request, "ai_fallback", len(output.jobs), fallback_reason)
		return output

	@staticmethod
	def _search_ai_max_steps() -> int:
		raw = os.getenv("JOB_AGENT_SEARCH_AI_MAX_STEPS", str(DEFAULT_SEARCH_AI_MAX_STEPS))
		try:
			return max(8, min(40, int(raw)))
		except ValueError:
			return DEFAULT_SEARCH_AI_MAX_STEPS

	async def _collect_with_ai(
		self,
		request: SearchRequest,
		*,
		ai_budget: AIUsageBudget | None = None,
	) -> SearchOutput:
		browser = Browser(
			user_data_dir=str(self.profile_dir.resolve()),
			headless=False,
			allowed_domains=allowed_domains(),
		)
		requested_model = os.getenv("JOB_AGENT_BROWSER_MODEL", DEFAULT_BROWSER_MODEL)

		def persist_live_usage(snapshot: UsageSnapshot) -> None:
			self.usage_store.record_safely(
				"search",
				snapshot,
				metadata={
					"keyword": request.keyword,
					"location": request.location,
					"mode": "ai_fallback",
					"fallback_reason": self._last_fallback_reason,
					"granularity": "llm_invocation",
					"requested_model": requested_model,
				},
			)

		llm = MeteredChatBrowserUse(
			model=requested_model,
			on_usage=persist_live_usage,
			usage_budget=ai_budget,
		)
		try:
			agent = Agent(
				task=self._build_task(request),
				llm=llm,
				browser=browser,
				output_model_schema=SearchOutput,
				# Discovery is text/DOM extraction. Disabling vision avoids expensive
				# screenshot capture and the ScreenshotWatchdog timeouts seen on long lists.
				use_vision=False,
				extend_system_message=(
					"This is read-only job discovery on Computrabajo only. Do not navigate to Google, Bing, or any external "
					"search engine/site. Never apply, submit a form, change account data, send messages, or bypass CAPTCHA, "
					"2FA, bot detection, or access controls. Stop if such a challenge blocks discovery. Use only pages under "
					"the configured Computrabajo allowlist."
				),
			)
			history = await agent.run(max_steps=self._search_ai_max_steps())
			output = history.structured_output
			if output is None:
				raise RuntimeError(f"Browser Use no devolvió vacantes estructuradas. Resultado: {(history.final_result() or '')[:300]}")
			normalized = output if isinstance(output, SearchOutput) else SearchOutput.model_validate(output)
			return SearchOutput(jobs=self._valid_jobs(normalized.jobs, request.max_results))
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
Use Computrabajo only. Do not navigate to Google, Bing, or another external search engine or website.
Do not apply, do not click any final application/submission button, do not modify the account, and do not send messages.
If CAPTCHA, 2FA, or anti-bot protection blocks the task, stop instead of bypassing it.
Return only actual vacancies on co.computrabajo.com.
""".strip()

	def _record_for_job(
		self,
		*,
		external_id: str,
		title: str,
		company: str,
		location: str,
		url: str,
		description: str,
		status: str = "discovered",
	) -> JobRecord:
		settings = self.profile_store.get()
		profile = settings.to_candidate_profile()
		preferences = settings.to_search_preferences()
		posting = JobPosting(
			title=title,
			company=company,
			location=location,
			description=description,
			url=url,
		)
		match = score_job(posting, profile, preferences)
		text = f"{title} {description}".casefold()
		matched_skills = tuple(skill for skill in profile.skills if skill.casefold() in text)
		missing_skills = tuple(skill for skill in profile.skills if skill.casefold() not in text)
		return JobRecord(
			id=None,
			source="computrabajo",
			external_id=external_id,
			title=title,
			company=company,
			location=location,
			url=url,
			score=match.score,
			band=match.decision,
			status=status,
			description=description,
			match_reasons=match.reasons,
			matched_skills=matched_skills,
			missing_skills=missing_skills,
		)

	def _persist(self, jobs: list[ExtractedJob]) -> int:
		records: list[JobRecord] = []
		for item in self._valid_jobs(jobs):
			url = str(item.url)
			records.append(
				self._record_for_job(
					external_id=hashlib.sha256(url.encode("utf-8")).hexdigest()[:24],
					title=item.title,
					company=item.company,
					location=item.location,
					url=url,
					description=item.description,
				)
			)
		return self.store.upsert_jobs(records)

	def rescore_existing_jobs(self) -> int:
		"""Recalculate all stored Computrabajo vacancies after the local profile changes."""
		jobs = self.store.list_jobs(limit=10000)
		records: list[JobRecord] = []
		for job in jobs:
			if str(job.get("source") or "") != "computrabajo":
				continue
			if not is_valid_computrabajo_job(
				title=job.get("title"),
				url=job.get("url"),
				description=job.get("description"),
			):
				continue
			records.append(
				self._record_for_job(
					external_id=str(job.get("external_id") or ""),
					title=str(job.get("title") or ""),
					company=str(job.get("company") or ""),
					location=str(job.get("location") or ""),
					url=str(job.get("url") or ""),
					description=str(job.get("description") or ""),
					status=str(job.get("status") or "discovered"),
				)
			)
		if records:
			self.store.upsert_jobs(records)
		return len(records)
