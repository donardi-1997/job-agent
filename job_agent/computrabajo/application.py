from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from browser_use import Agent, Browser
from job_agent.ai_usage import AIUsageStore, MeteredChatBrowserUse
from job_agent.answer_memory import AnswerMemory
from job_agent.computrabajo.browser_config import allowed_domains
from job_agent.profile import ProfileStore
from job_agent.storage import JobStore


DEFAULT_PROFILE_DIR = Path("data/browser-profile")
DEFAULT_BROWSER_MODEL = "bu-latest"


class ApplicationQuestion(BaseModel):
	"""One application field together with the answer that was used or proposed."""

	question: str = Field(min_length=1, max_length=1000)
	field_type: str = Field(default="text", max_length=80)
	options: list[str] = Field(default_factory=list)
	suggested_answer: str = Field(default="", max_length=4000)
	confidence: int = Field(default=0, ge=0, le=100)
	requires_user_input: bool = False
	note: str = Field(default="", max_length=1000)


class ApplicationDraftOutput(BaseModel):
	"""Structured result of one full application attempt."""

	questions: list[ApplicationQuestion] = Field(default_factory=list)
	application_url: str = ""
	login_required: bool = False
	blocked_reason: str = ""
	summary: str = ""
	submitted: bool = False
	submission_status: str = "not_submitted"
	confirmation_text: str = ""
	confirmation_url: str = ""


class PreparationStatus(BaseModel):
	state: Literal["idle", "running", "completed", "error"] = "idle"
	job_id: int | None = None
	message: str = ""
	questions: int = 0
	submitted: bool = False


class AssistedApplicationPreparer:
	"""Completes a Computrabajo application using local profile data and saved answers."""

	def __init__(self, store: JobStore | None = None, profile_dir: Path | str = DEFAULT_PROFILE_DIR) -> None:
		self.store = store or JobStore()
		self.profile_store = ProfileStore(self.store.path)
		self.answer_memory = AnswerMemory(self.store.path)
		self.usage_store = AIUsageStore(self.store.path)
		self.profile_dir = Path(profile_dir)
		self.profile_dir.mkdir(parents=True, exist_ok=True)
		self._lock = threading.Lock()
		self._status = PreparationStatus()

	def status(self) -> dict[str, object]:
		with self._lock:
			return self._status.model_dump()

	def start(self, job_id: int) -> bool:
		with self._lock:
			if self._status.state == "running":
				return False
			job = self.store.get_job(job_id)
			if not job:
				raise ValueError("Vacante no encontrada.")
			self._status = PreparationStatus(
				state="running",
				job_id=job_id,
				message="Abriendo la vacante, reutilizando respuestas conocidas y completando la postulación…",
			)
		threading.Thread(target=self._worker, args=(job_id,), daemon=True, name="application-runner").start()
		return True

	def _worker(self, job_id: int) -> None:
		try:
			job = self.store.get_job(job_id)
			if not job:
				raise RuntimeError("Vacante no encontrada.")
			result = asyncio.run(self._apply(job))
			payload = result.model_dump()
			self.store.save_application_draft(job_id, payload)
			self.store.save_application_attempt(job_id, payload)
			if result.submitted:
				self.store.update_status(job_id, "applied")
			message = (
				result.confirmation_text
				if result.submitted and result.confirmation_text
				else "Postulación enviada correctamente."
				if result.submitted
				else result.blocked_reason or "La postulación no pudo completarse."
			)
			with self._lock:
				self._status = PreparationStatus(
					state="completed",
					job_id=job_id,
					questions=len(result.questions),
					submitted=result.submitted,
					message=message,
				)
		except Exception as exc:
			with self._lock:
				self._status = PreparationStatus(state="error", job_id=job_id, message=str(exc))

	async def _apply(self, job: dict[str, object]) -> ApplicationDraftOutput:
		load_dotenv()
		if not os.getenv("BROWSER_USE_API_KEY"):
			raise RuntimeError("Falta BROWSER_USE_API_KEY. Agrégala al archivo .env para realizar postulaciones.")

		profile = self.profile_store.get()
		if not profile.automation_enabled:
			raise RuntimeError("La automatización está desactivada. No se inició una nueva postulación.")
		saved_draft = self.store.get_application_draft(int(job["id"])) or {}
		known_answers = self.answer_memory.context_for_agent(profile)
		browser = Browser(
			user_data_dir=str(self.profile_dir.resolve()),
			headless=False,
			allowed_domains=allowed_domains(),
		)
		llm = MeteredChatBrowserUse(model=os.getenv("JOB_AGENT_BROWSER_MODEL", DEFAULT_BROWSER_MODEL))
		try:
			agent = Agent(
				task=self._build_task(job, profile.model_dump(), saved_draft, known_answers),
				llm=llm,
				browser=browser,
				output_model_schema=ApplicationDraftOutput,
				use_vision="auto",
				extend_system_message=(
					"Complete the user's job application on Computrabajo and submit it when the required fields can be answered "
					"from the supplied local profile, deterministic known-answer memory, saved answers, or unambiguous page context. "
					"Reuse deterministic known answers verbatim when the question is equivalent instead of re-inferring them. "
					"Record every answer actually used. Do not invent personal facts, qualifications, employment history, salary facts, "
					"legal declarations, or answers that are not supported by supplied data. Never bypass CAPTCHA, 2FA, bot detection, "
					"or access controls. If such a challenge blocks the application, stop and report it accurately. "
					"Google OAuth navigation is allowed only for the user's Computrabajo sign-in. Never change Google account settings, "
					"security settings, recovery information, or credentials."
				),
			)
			try:
				history = await agent.run(max_steps=70)
			finally:
				self.usage_store.record_safely(
					"application",
					llm.snapshot(),
					job_id=int(job["id"]),
					metadata={"title": str(job.get("title") or "")},
				)
			output = history.structured_output
			if output is None:
				raise RuntimeError(f"No se pudo obtener un resultado estructurado. Resultado: {(history.final_result() or '')[:300]}")
			result = output if isinstance(output, ApplicationDraftOutput) else ApplicationDraftOutput.model_validate(output)
			self.answer_memory.remember_questions(
				[item.model_dump() for item in result.questions],
				submitted=result.submitted,
			)
			return result
		finally:
			await browser.stop()

	@staticmethod
	def _build_task(
		job: dict[str, object],
		profile: dict[str, object],
		saved_draft: dict[str, object],
		known_answers: list[dict[str, str]] | None = None,
	) -> str:
		return f"""
Open this Computrabajo vacancy: {job.get('url', '')}

Goal: COMPLETE AND SUBMIT the job application for the user.

Use deterministic known answers first, then the local candidate profile and any previously saved draft answers. A saved answer takes precedence when it clearly corresponds to the same question. Do not re-infer an answer already present in deterministic memory. Navigate the application flow, fill every answer you can support, continue through intermediate steps, and click the final application/submit/confirm action when the form is ready.

For every application question or field encountered, record in the final structured output:
- exact question/label
- field type
- selectable options if present
- the answer actually entered/selected
- confidence 0-100
- requires_user_input=false when it was completed successfully
- a short note when useful

After the final action, verify whether Computrabajo shows a success/confirmation state. Set submitted=true only when there is positive evidence that the application was submitted. Capture confirmation_text and confirmation_url when available.

Deterministic known-answer memory (reuse only for equivalent questions):
{known_answers or []}

Local candidate profile:
{profile}

Previously saved answers/draft:
{saved_draft}

Vacancy title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Stored description: {job.get('description', '')}

Important constraints:
- Never invent facts about the user.
- Never bypass CAPTCHA, 2FA, bot detection, or another access control. If one blocks the flow, stop and set blocked_reason.
- Do not alter unrelated account/profile settings.
- Avoid duplicate submission if the page already indicates this vacancy was previously applied to; report that state instead.
""".strip()
