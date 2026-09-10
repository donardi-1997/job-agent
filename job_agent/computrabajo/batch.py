from __future__ import annotations

import asyncio
import hashlib
import threading
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from job_agent.computrabajo.application import AssistedApplicationPreparer
from job_agent.computrabajo.collector import ComputrabajoCollector, SearchRequest
from job_agent.profile import ProfileStore
from job_agent.search_terms import build_personal_search_terms
from job_agent.storage import JobStore


class BatchApplyRequest(BaseModel):
	"""Personal batch settings. Search terms are derived from local skills and roles."""

	keyword: str = Field(default="", max_length=120)
	location: str = Field(default="Colombia", min_length=2, max_length=120)
	max_results: int = Field(default=30, ge=1, le=50)
	min_score: int = Field(default=85, ge=0, le=100)
	max_applications: int = Field(default=10, ge=1, le=25)
	daily_limit: int = Field(default=20, ge=1, le=50)
	max_search_terms: int = Field(default=8, ge=1, le=12)

	@field_validator("keyword", "location")
	@classmethod
	def normalize_text(cls, value: str) -> str:
		return " ".join(value.strip().split())


class BatchApplyStatus(BaseModel):
	state: Literal["idle", "searching", "applying", "completed", "error"] = "idle"
	run_id: int | None = None
	keyword: str = ""
	search_terms: list[str] = Field(default_factory=list)
	searches_completed: int = 0
	location: str = ""
	found: int = 0
	eligible: int = 0
	attempted: int = 0
	submitted: int = 0
	blocked: int = 0
	current_job_id: int | None = None
	current_job_title: str = ""
	current_search_term: str = ""
	message: str = ""


class BatchApplyRunner:
	"""Runs skill-driven multi-query discovery and sequential auto-application."""

	def __init__(
		self,
		store: JobStore | None = None,
		collector: ComputrabajoCollector | None = None,
		preparer: AssistedApplicationPreparer | None = None,
	) -> None:
		self.store = store or JobStore()
		self.collector = collector or ComputrabajoCollector(store=self.store)
		self.preparer = preparer or AssistedApplicationPreparer(store=self.store)
		self.profile_store = ProfileStore(self.store.path)
		self._lock = threading.Lock()
		self._status = BatchApplyStatus()

	def status(self) -> dict[str, object]:
		with self._lock:
			return self._status.model_dump()

	@staticmethod
	def _unique_terms(values: list[str], limit: int) -> list[str]:
		result: list[str] = []
		seen: set[str] = set()
		for raw in values:
			value = " ".join(str(raw).strip().split())
			key = value.casefold()
			if value and key not in seen:
				seen.add(key)
				result.append(value)
			if len(result) >= limit:
				break
		return result

	def _search_terms(self, request: BatchApplyRequest) -> list[str]:
		profile = self.profile_store.get()
		terms = build_personal_search_terms(
			profile,
			custom_term=request.keyword,
			limit=request.max_search_terms,
		)
		if not terms:
			raise ValueError("Agrega skills o cargos objetivo en Mi perfil para construir búsquedas automáticas.")
		return terms

	def start(self, request: BatchApplyRequest) -> bool:
		search_terms = self._search_terms(request)
		with self._lock:
			if self._status.state in {"searching", "applying"}:
				return False
			label = " · ".join(search_terms)
			run_id = self.store.create_batch_run(
				keyword=label,
				location=request.location,
				min_score=request.min_score,
				max_applications=request.max_applications,
			)
			self._status = BatchApplyStatus(
				state="searching",
				run_id=run_id,
				keyword=label,
				search_terms=search_terms,
				location=request.location,
				message=f"Construí {len(search_terms)} búsquedas automáticas desde tus skills y cargos objetivo…",
			)
		threading.Thread(
			target=self._worker,
			args=(request, run_id, search_terms),
			daemon=True,
			name="personal-batch-auto-apply",
		).start()
		return True

	def _set_status(self, **changes: object) -> None:
		with self._lock:
			data = self._status.model_dump()
			data.update(changes)
			self._status = BatchApplyStatus.model_validate(data)

	def _current_search_jobs(self, external_ids: list[str], min_score: int) -> list[dict[str, object]]:
		if not external_ids:
			return []
		placeholders = ",".join("?" for _ in external_ids)
		query = f"""
			SELECT * FROM jobs
			WHERE external_id IN ({placeholders})
			  AND score >= ?
			  AND status NOT IN ('applied', 'ignored')
			ORDER BY score DESC, created_at DESC
		"""
		with self.store.connect() as connection:
			rows = connection.execute(query, [*external_ids, min_score]).fetchall()
		return [self.store._decode_row(row) for row in rows]

	@staticmethod
	def _is_access_block(result: object) -> bool:
		blocked_reason = str(getattr(result, "blocked_reason", "") or "").casefold()
		return any(token in blocked_reason for token in ("captcha", "2fa", "anti-bot", "bot detection", "access control"))

	def _worker(self, request: BatchApplyRequest, run_id: int, search_terms: list[str]) -> None:
		try:
			already_today = self.store.count_submitted_today()
			remaining_daily = max(0, request.daily_limit - already_today)
			if remaining_daily == 0:
				message = f"Límite diario alcanzado: {request.daily_limit} postulaciones confirmadas."
				self.store.update_batch_run(run_id, state="completed", message=message)
				self._set_status(state="completed", message=message)
				return

			# max_results is a global discovery budget, not a per-keyword multiplier.
			per_term = max(1, min(50, (request.max_results + len(search_terms) - 1) // len(search_terms)))
			remaining_results = request.max_results
			external_ids: set[str] = set()
			found_urls: set[str] = set()
			searches_completed = 0

			for term in search_terms:
				if remaining_results <= 0:
					break
				term_limit = min(per_term, remaining_results)
				self._set_status(
					state="searching",
					current_search_term=term,
					message=f"Buscando “{term}” en Computrabajo…",
				)
				search_output = asyncio.run(
					self.collector._collect(
						SearchRequest(keyword=term, location=request.location, max_results=term_limit)
					)
				)
				self.collector._persist(search_output.jobs)
				searches_completed += 1

				for job in search_output.jobs:
					url = str(job.url)
					found_urls.add(url)
					external_ids.add(hashlib.sha256(url.encode("utf-8")).hexdigest()[:24])

				remaining_results = max(0, request.max_results - len(found_urls))
				self._set_status(
					searches_completed=searches_completed,
					found=len(found_urls),
				)

			eligible_jobs = self._current_search_jobs(sorted(external_ids), request.min_score)
			quota = min(request.max_applications, remaining_daily, len(eligible_jobs))
			self.store.update_batch_run(run_id, found=len(found_urls), eligible=len(eligible_jobs))
			self._set_status(
				found=len(found_urls),
				eligible=len(eligible_jobs),
				current_search_term="",
			)

			if quota == 0:
				message = (
					f"Se revisaron {searches_completed} búsquedas generadas desde tu perfil y no hay vacantes nuevas "
					"que cumplan el umbral y la cuota configurados."
				)
				self.store.update_batch_run(run_id, state="completed", message=message)
				self._set_status(state="completed", message=message)
				return

			attempted = 0
			submitted = 0
			blocked = 0
			for job in eligible_jobs[:quota]:
				job_id = int(job["id"])
				self._set_status(
					state="applying",
					current_job_id=job_id,
					current_job_title=str(job.get("title") or ""),
					message=f"Postulando a {job.get('title', 'vacante')}…",
				)
				result = asyncio.run(self.preparer._apply(job))
				payload = result.model_dump()
				self.store.save_application_draft(job_id, payload)
				self.store.save_application_attempt(job_id, payload)
				attempted += 1
				if result.submitted:
					submitted += 1
					self.store.update_status(job_id, "applied")
				else:
					blocked += 1

				self.store.update_batch_run(
					run_id,
					attempted=attempted,
					submitted=submitted,
					blocked=blocked,
				)
				self._set_status(attempted=attempted, submitted=submitted, blocked=blocked)

				if self._is_access_block(result):
					break

			message = (
				f"Lote personal finalizado: {searches_completed} búsquedas automáticas, {len(found_urls)} vacantes únicas, "
				f"{submitted} enviadas de {attempted} intentos."
			)
			self.store.update_batch_run(
				run_id,
				state="completed",
				attempted=attempted,
				submitted=submitted,
				blocked=blocked,
				message=message,
			)
			self._set_status(
				state="completed",
				attempted=attempted,
				submitted=submitted,
				blocked=blocked,
				current_job_id=None,
				current_job_title="",
				current_search_term="",
				message=message,
			)
		except Exception as exc:
			message = str(exc)
			self.store.update_batch_run(run_id, state="error", message=message)
			self._set_status(
				state="error",
				message=message,
				current_job_id=None,
				current_job_title="",
				current_search_term="",
			)
