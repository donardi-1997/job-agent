from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from browser_use import Agent, Browser, ChatBrowserUse
from job_agent.profile import ProfileStore
from job_agent.storage import JobStore


DEFAULT_PROFILE_DIR = Path("data/browser-profile")


class ApplicationQuestion(BaseModel):
	"""One field or question found in a job application flow."""

	question: str = Field(min_length=1, max_length=1000)
	field_type: str = Field(default="text", max_length=80)
	options: list[str] = Field(default_factory=list)
	suggested_answer: str = Field(default="", max_length=4000)
	confidence: int = Field(default=0, ge=0, le=100)
	requires_user_input: bool = True
	note: str = Field(default="", max_length=1000)


class ApplicationDraftOutput(BaseModel):
	"""Structured, non-submitted application preparation result."""

	questions: list[ApplicationQuestion] = Field(default_factory=list)
	application_url: str = ""
	login_required: bool = False
	blocked_reason: str = ""
	summary: str = ""


class PreparationStatus(BaseModel):
	state: Literal["idle", "running", "completed", "error"] = "idle"
	job_id: int | None = None
	message: str = ""
	questions: int = 0


class AssistedApplicationPreparer:
	"""Inspects an application flow and prepares answers without submitting it."""

	def __init__(self, store: JobStore | None = None, profile_dir: Path | str = DEFAULT_PROFILE_DIR) -> None:
		self.store = store or JobStore()
		self.profile_store = ProfileStore(self.store.path)
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
				message="Abriendo la vacante y revisando el flujo de postulación…",
			)
		threading.Thread(target=self._worker, args=(job_id,), daemon=True, name="application-preparer").start()
		return True

	def _worker(self, job_id: int) -> None:
		try:
			job = self.store.get_job(job_id)
			if not job:
				raise RuntimeError("Vacante no encontrada.")
			result = asyncio.run(self._prepare(job))
			self.store.save_application_draft(job_id, result.model_dump())
			with self._lock:
				self._status = PreparationStatus(
					state="completed",
					job_id=job_id,
					questions=len(result.questions),
					message=(result.blocked_reason or f"Borrador preparado con {len(result.questions)} preguntas/campos."),
				)
		except Exception as exc:
			with self._lock:
				self._status = PreparationStatus(state="error", job_id=job_id, message=str(exc))

	async def _prepare(self, job: dict[str, object]) -> ApplicationDraftOutput:
		load_dotenv()
		if not os.getenv("BROWSER_USE_API_KEY"):
			raise RuntimeError("Falta BROWSER_USE_API_KEY. Agrégala al archivo .env para preparar postulaciones.")

		profile = self.profile_store.get()
		browser = Browser(
			user_data_dir=str(self.profile_dir.resolve()),
			headless=False,
			allowed_domains=["co.computrabajo.com"],
		)
		try:
			agent = Agent(
				task=self._build_task(job, profile.model_dump()),
				llm=ChatBrowserUse(),
				browser=browser,
				output_model_schema=ApplicationDraftOutput,
				use_vision="auto",
				extend_system_message=(
					"You are preparing a draft only. You may inspect an application form when opening it is clearly non-submitting. "
					"Never submit an application, never click a final submit/send/apply confirmation, never send a message, "
					"never change account/profile data, and never bypass CAPTCHA, 2FA, bot detection, or access controls. "
					"Do not invent personal facts. Mark unknown personal answers as requires_user_input=true."
				),
			)
			history = await agent.run(max_steps=45)
			output = history.structured_output
			if output is None:
				raise RuntimeError(f"No se pudo generar un borrador estructurado. Resultado: {(history.final_result() or '')[:300]}")
			return output if isinstance(output, ApplicationDraftOutput) else ApplicationDraftOutput.model_validate(output)
		finally:
			await browser.stop()

	@staticmethod
	def _build_task(job: dict[str, object], profile: dict[str, object]) -> str:
		return f"""
Open this Computrabajo vacancy: {job.get('url', '')}

Goal: inspect the application flow and PREPARE a draft of answers. Do not submit anything.
If the application form can be opened without creating/submitting an application, inspect its visible fields and questions. If opening it might itself submit/create the application, do not click it; report that in blocked_reason.

For every visible application question or field, return:
- exact question/label
- field type
- selectable options if present
- a suggested answer only when supported by the local profile or vacancy data
- confidence 0-100
- requires_user_input=true when the answer needs information not present in the profile
- a short note explaining uncertainty when useful

Local candidate profile (use only these facts; do not invent missing facts):
{profile}

Vacancy title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Stored description: {job.get('description', '')}

Never submit, confirm, send, apply, upload/replace a CV, alter profile/account data, or answer CAPTCHA/2FA. Stop before any action that can create or finalize an application.
""".strip()
