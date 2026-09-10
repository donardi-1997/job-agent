from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from browser_use import Agent, Browser
from job_agent.ai_usage import AIUsageStore, MeteredChatBrowserUse, UsageSnapshot
from job_agent.answer_memory import AnswerMemory
from job_agent.computrabajo.browser_config import allowed_domains
from job_agent.computrabajo.deterministic_application import (
    ApplicationExecutionStore,
    ApplicationPatternStore,
    DeterministicApplicationResult,
    DeterministicApplicationRunner,
)
from job_agent.credentials import CredentialStore
from job_agent.profile import ProfileStore
from job_agent.storage import ApplicationModeStore, JobStore


DEFAULT_PROFILE_DIR = Path("data/browser-profile")
DEFAULT_BROWSER_MODEL = "bu-latest"
DEFAULT_APPLICATION_AI_MAX_STEPS = 35


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
    mode: Literal["test", "real"] = "test"
    test_mode: bool = True
    ready_to_submit: bool = False


class PreparationStatus(BaseModel):
    state: Literal["idle", "running", "completed", "error"] = "idle"
    job_id: int | None = None
    message: str = ""
    questions: int = 0
    submitted: bool = False
    mode: Literal["", "deterministic", "ai_fallback"] = ""
    fallback_reason: str = ""


class AssistedApplicationPreparer:
    """Complete Computrabajo applications locally first, using AI only as fallback in REAL mode."""

    def __init__(self, store: JobStore | None = None, profile_dir: Path | str = DEFAULT_PROFILE_DIR) -> None:
        self.store = store or JobStore()
        self.profile_store = ProfileStore(self.store.path)
        self.mode_store = ApplicationModeStore(self.store.path)
        self.answer_memory = AnswerMemory(self.store.path)
        self.usage_store = AIUsageStore(self.store.path)
        self.credential_store = CredentialStore(self.store.path)
        self.application_execution_store = ApplicationExecutionStore(self.store.path)
        self.pattern_store = ApplicationPatternStore(self.store.path)
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.deterministic_application = DeterministicApplicationRunner(
            self.profile_dir,
            self.answer_memory,
            self.pattern_store,
        )
        self._lock = threading.Lock()
        self._status = PreparationStatus()
        self._last_mode: Literal["", "deterministic", "ai_fallback"] = ""
        self._last_fallback_reason = ""

    def status(self) -> dict[str, object]:
        with self._lock:
            return self._status.model_dump()

    def application_efficiency(self) -> dict[str, object]:
        execution = self.application_execution_store.summary()
        patterns = self.pattern_store.stats()
        return {
            **execution,
            "patterns": patterns["patterns"],
            "proven_patterns": patterns["proven_patterns"],
            "pattern_observations": patterns["observations"],
            "pattern_successful_uses": patterns["successful_uses"],
        }

    def application_mode(self) -> dict[str, str]:
        return {"mode": self.mode_store.get()}

    def set_application_mode(self, mode: str) -> dict[str, str]:
        return {"mode": self.mode_store.set(mode)}

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
                message="Intentando primero la postulación local sin IA…",
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
                else result.summary or result.blocked_reason or "La postulación no pudo completarse."
            )
            with self._lock:
                self._status = PreparationStatus(
                    state="completed",
                    job_id=job_id,
                    questions=len(result.questions),
                    submitted=result.submitted,
                    mode=self._last_mode,
                    fallback_reason=self._last_fallback_reason,
                    message=message,
                )
        except Exception as exc:
            with self._lock:
                self._status = PreparationStatus(
                    state="error",
                    job_id=job_id,
                    mode=self._last_mode,
                    fallback_reason=self._last_fallback_reason,
                    message=str(exc),
                )

    def _sensitive_credentials(self) -> dict[str, dict[str, str]] | None:
        credentials = self.credential_store.load_computrabajo()
        if not credentials:
            return None
        username, password = credentials
        secrets = {"computrabajo_user": username, "computrabajo_password": password}
        return {
            "https://co.computrabajo.com": secrets,
            "https://secure.computrabajo.com": secrets,
        }

    def _record_execution(
        self,
        *,
        job_id: int,
        mode: str,
        submitted: bool,
        unresolved_fields: int = 0,
        fallback_reason: str = "",
    ) -> None:
        try:
            self.application_execution_store.record(
                job_id=job_id,
                mode=mode,
                submitted=submitted,
                unresolved_fields=unresolved_fields,
                fallback_reason=fallback_reason,
            )
        except Exception:
            pass

    @staticmethod
    def _from_deterministic(result: DeterministicApplicationResult) -> ApplicationDraftOutput:
        questions = [
            ApplicationQuestion(
                question=item.question,
                field_type=item.field_type,
                options=list(item.options),
                suggested_answer=item.answer,
                confidence=item.confidence,
                requires_user_input=item.requires_user_input,
                note=item.note,
            )
            for item in result.questions
        ]
        if result.test_mode and result.ready_to_submit:
            summary = "Formulario completado en modo prueba. Listo para enviar."
        elif result.test_mode:
            summary = result.blocked_reason or result.fallback_reason or "Formulario inspeccionado en modo prueba."
        elif result.submitted:
            summary = "Postulación completada localmente sin IA."
        else:
            summary = result.blocked_reason or result.fallback_reason or "Intento determinístico finalizado."
        return ApplicationDraftOutput(
            questions=questions,
            application_url=result.application_url,
            login_required=result.login_required,
            blocked_reason=result.blocked_reason,
            summary=summary,
            submitted=result.submitted,
            submission_status=result.submission_status,
            confirmation_text=result.confirmation_text,
            confirmation_url=result.confirmation_url,
            mode=result.mode if result.mode in {"test", "real"} else "test",
            test_mode=result.test_mode,
            ready_to_submit=result.ready_to_submit,
        )

    @staticmethod
    def _enforce_test_invariant(output: ApplicationDraftOutput) -> ApplicationDraftOutput:
        """Defense in depth: TEST results can never be represented as submitted."""
        unresolved = any(item.requires_user_input for item in output.questions)
        ready = bool(output.ready_to_submit) and not output.blocked_reason and not unresolved
        return output.model_copy(
            update={
                "mode": "test",
                "test_mode": True,
                "submitted": False,
                "submission_status": "test_ready" if ready else "test_incomplete",
                "ready_to_submit": ready,
                "confirmation_text": "",
                "confirmation_url": "",
                "summary": (
                    "Formulario completado en modo prueba. Listo para enviar."
                    if ready
                    else output.summary or output.blocked_reason or "Formulario incompleto en modo prueba."
                ),
            }
        )

    async def _apply(self, job: dict[str, object]) -> ApplicationDraftOutput:
        load_dotenv()
        profile = self.profile_store.get()
        if not profile.automation_enabled:
            raise RuntimeError("La automatización está desactivada. No se inició una nueva postulación.")

        self._last_mode = ""
        self._last_fallback_reason = ""
        job_id = int(job["id"])
        saved_draft = self.store.get_application_draft(job_id) or {}
        application_mode = self.mode_store.get()

        local_result: DeterministicApplicationResult | None = None
        try:
            local_result = await self.deterministic_application.apply(
                job=job,
                profile=profile,
                saved_draft=saved_draft,
                mode=application_mode,
            )

            # TEST mode is deliberately deterministic-only. This is the backend safety
            # boundary: Browser Use never receives control in TEST mode, so a prompt or
            # model mistake cannot click a final submission action.
            if application_mode == "test":
                self._last_mode = "deterministic"
                self._last_fallback_reason = local_result.fallback_reason
                output = self._enforce_test_invariant(self._from_deterministic(local_result))
                unresolved = sum(1 for item in output.questions if item.requires_user_input)
                self._record_execution(
                    job_id=job_id,
                    mode="deterministic",
                    submitted=False,
                    unresolved_fields=unresolved,
                    fallback_reason=local_result.fallback_reason,
                )
                return output

            if local_result.terminal_without_ai:
                self._last_mode = "deterministic"
                unresolved = sum(1 for item in local_result.questions if item.requires_user_input)
                self._record_execution(
                    job_id=job_id,
                    mode="deterministic",
                    submitted=local_result.submitted,
                    unresolved_fields=unresolved,
                )
                output = self._from_deterministic(local_result)
                if output.submitted:
                    self.answer_memory.remember_questions(
                        [item.model_dump() for item in output.questions],
                        submitted=True,
                    )
                return output
            fallback_reason = local_result.fallback_reason or "El flujo local no pudo completar la postulación."
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}"
            if application_mode == "test":
                self._last_mode = "deterministic"
                self._last_fallback_reason = fallback_reason
                self._record_execution(
                    job_id=job_id,
                    mode="deterministic",
                    submitted=False,
                    fallback_reason=fallback_reason,
                )
                return ApplicationDraftOutput(
                    mode="test",
                    test_mode=True,
                    submitted=False,
                    submission_status="test_incomplete",
                    ready_to_submit=False,
                    summary=f"Modo prueba detenido de forma segura: {fallback_reason}",
                )

        self._last_fallback_reason = fallback_reason
        fallback_enabled = os.getenv("JOB_AGENT_APPLICATION_AI_FALLBACK", "1").strip().casefold() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if not fallback_enabled:
            raise RuntimeError(f"Postulación local incompleta y fallback de IA desactivado. {fallback_reason}")
        if not os.getenv("BROWSER_USE_API_KEY"):
            raise RuntimeError(
                "La postulación determinística no pudo completar el flujo y no hay BROWSER_USE_API_KEY para el fallback. "
                f"Detalle: {fallback_reason}"
            )

        self._last_mode = "ai_fallback"
        try:
            result = await self._apply_with_ai(job, profile.model_dump(), saved_draft, application_mode)
        except Exception:
            unresolved = (
                sum(1 for item in local_result.questions if item.requires_user_input)
                if local_result is not None
                else 0
            )
            self._record_execution(
                job_id=job_id,
                mode="ai_fallback",
                submitted=False,
                unresolved_fields=unresolved,
                fallback_reason=fallback_reason,
            )
            raise

        unresolved = (
            sum(1 for item in local_result.questions if item.requires_user_input)
            if local_result is not None
            else 0
        )
        self._record_execution(
            job_id=job_id,
            mode="ai_fallback",
            submitted=result.submitted,
            unresolved_fields=unresolved,
            fallback_reason=fallback_reason,
        )

        if result.submitted and result.questions and local_result is not None and local_result.observed_fields:
            self.pattern_store.confirm_success(
                local_result.observed_fields,
                [item.question for item in result.questions],
            )
        return result

    @staticmethod
    def _application_ai_max_steps() -> int:
        raw = os.getenv("JOB_AGENT_APPLICATION_AI_MAX_STEPS", str(DEFAULT_APPLICATION_AI_MAX_STEPS))
        try:
            return max(10, min(70, int(raw)))
        except ValueError:
            return DEFAULT_APPLICATION_AI_MAX_STEPS

    async def _apply_with_ai(
        self,
        job: dict[str, object],
        profile: dict[str, object],
        saved_draft: dict[str, object],
        application_mode: str = "real",
    ) -> ApplicationDraftOutput:
        known_answers = self.answer_memory.context_for_agent(self.profile_store.get())
        sensitive_credentials = self._sensitive_credentials()
        browser = Browser(
            user_data_dir=str(self.profile_dir.resolve()),
            headless=False,
            allowed_domains=allowed_domains(),
        )
        requested_model = os.getenv("JOB_AGENT_BROWSER_MODEL", DEFAULT_BROWSER_MODEL)
        job_id = int(job["id"])

        def persist_live_usage(snapshot: UsageSnapshot) -> None:
            self.usage_store.record_safely(
                "application",
                snapshot,
                job_id=job_id,
                metadata={
                    "title": str(job.get("title") or ""),
                    "mode": "ai_fallback",
                    "granularity": "llm_invocation",
                    "requested_model": requested_model,
                },
            )

        llm = MeteredChatBrowserUse(model=requested_model, on_usage=persist_live_usage)
        try:
            agent = Agent(
                task=self._build_task(
                    job,
                    profile,
                    saved_draft,
                    known_answers,
                    credentials_available=bool(sensitive_credentials),
                    application_mode=application_mode,
                ),
                llm=llm,
                browser=browser,
                sensitive_data=sensitive_credentials,
                output_model_schema=ApplicationDraftOutput,
                use_vision="auto",
                extend_system_message=(
                    "Complete the user's job application on Computrabajo and submit it when the required fields can be answered "
                    "from the supplied local profile, deterministic known-answer memory, saved answers, or unambiguous page context. "
                    "Reuse deterministic known answers verbatim when the question is equivalent instead of re-inferring them. "
                    "When sensitive_data placeholders are available, use them only in native Computrabajo login fields and never reveal "
                    "or repeat their values. Record every non-secret application answer actually used. Do not invent personal facts, "
                    "qualifications, employment history, salary facts, legal declarations, or answers that are not supported by supplied "
                    "data. Never bypass CAPTCHA, 2FA, bot detection, or access controls. If such a challenge blocks the application, stop "
                    "and report it accurately. Google OAuth navigation is allowed only for the user's Computrabajo sign-in. Never change "
                    "Google account settings, security settings, recovery information, or credentials."
                ),
            )
            history = await agent.run(max_steps=self._application_ai_max_steps())
            output = history.structured_output
            if output is None:
                raise RuntimeError(f"No se pudo obtener un resultado estructurado. Resultado: {(history.final_result() or '')[:300]}")
            result = output if isinstance(output, ApplicationDraftOutput) else ApplicationDraftOutput.model_validate(output)
            if application_mode == "test":
                result = self._enforce_test_invariant(result)
            else:
                updates: dict[str, object] = {"mode": "real", "test_mode": False}
                if result.submitted and result.submission_status == "not_submitted":
                    updates["submission_status"] = "submitted"
                result = result.model_copy(update=updates)
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
        *,
        credentials_available: bool = False,
        application_mode: str = "real",
    ) -> str:
        login_instruction = (
            "If Computrabajo requires native login, use the sensitive placeholders <secret>computrabajo_user</secret> and "
            "<secret>computrabajo_password</secret> only in the appropriate Computrabajo login fields. Never output their values."
            if credentials_available
            else "If login is required and the persistent browser session is not authenticated, report login_required=true."
        )
        return f"""
Open this Computrabajo vacancy: {job.get('url', '')}

Goal: {"COMPLETE the job application for the user. Do not submit it; stop immediately before the final submission action." if application_mode == "test" else "COMPLETE AND SUBMIT the job application for the user."}

A deterministic local attempt already ran before this AI fallback. Use deterministic known answers first, then the local candidate profile and any previously saved draft answers. A saved answer takes precedence when it clearly corresponds to the same question. Do not re-infer an answer already present in deterministic memory. Navigate the application flow, fill every answer you can support, and continue through intermediate steps. {"Never click or trigger the final application/submit/confirm action in TEST mode." if application_mode == "test" else "click the final application/submit/confirm action when the form is ready."}

{login_instruction}

For every application question or field encountered, record in the final structured output:
- exact question/label
- field type
- selectable options if present
- the answer actually entered/selected
- confidence 0-100
- requires_user_input=false when it was completed successfully
- a short note when useful

Never include passwords, authentication tokens, secret placeholders, or login credentials in the application-question output.

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
