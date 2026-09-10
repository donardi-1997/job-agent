from __future__ import annotations

import os

from dotenv import load_dotenv
from browser_use import Agent, Browser

from job_agent.ai_usage import AIUsageBudget, MeteredChatBrowserUse, UsageSnapshot
from job_agent.answer_memory import normalize_question
from job_agent.computrabajo.application import (
    ApplicationDraftOutput,
    AssistedApplicationPreparer as BaseApplicationPreparer,
    RealApplicationDraftOutput,
)
from job_agent.computrabajo.browser_config import allowed_domains
from job_agent.computrabajo.deterministic_application import DeterministicApplicationResult
from job_agent.computrabajo.form_memory import ApplicationFormMemory
from job_agent.computrabajo.question_resolver import CompactQuestionResolver


DEFAULT_COST_AWARE_AI_MAX_STEPS = 18
DEFAULT_BROWSER_MODEL = "bu-latest"


class CostAwareApplicationPreparer(BaseApplicationPreparer):
    """Application orchestration optimized to avoid full browser-agent calls.

    Order of work:
    deterministic browser -> local answer memory -> compact question LLM ->
    deterministic replay -> full Browser Use agent only for genuinely unknown
    navigation/form structure.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.question_resolver = CompactQuestionResolver(self.store.path)
        self.form_memory = ApplicationFormMemory(self.store.path)

    def application_efficiency(self) -> dict[str, object]:
        return {**super().application_efficiency(), **self.form_memory.stats()}

    @staticmethod
    def _application_ai_max_steps() -> int:
        raw = os.getenv("JOB_AGENT_APPLICATION_AI_MAX_STEPS", str(DEFAULT_COST_AWARE_AI_MAX_STEPS))
        try:
            return max(8, min(35, int(raw)))
        except ValueError:
            return DEFAULT_COST_AWARE_AI_MAX_STEPS

    @staticmethod
    def _unresolved_questions(result: DeterministicApplicationResult) -> list[dict[str, object]]:
        return [
            {
                "question": item.question,
                "field_type": item.field_type,
                "options": list(item.options),
            }
            for item in result.questions
            if item.requires_user_input and item.question.strip()
        ]

    @staticmethod
    def _merge_resolved_answers(
        saved_draft: dict[str, object],
        local_result: DeterministicApplicationResult,
        resolutions: object,
    ) -> tuple[dict[str, object], int]:
        payload = dict(saved_draft)
        existing = payload.get("questions")
        questions = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
        by_key = {
            normalize_question(str(item.get("question") or "")): index
            for index, item in enumerate(questions)
            if normalize_question(str(item.get("question") or ""))
        }
        local_by_key = {
            normalize_question(item.question): item
            for item in local_result.questions
            if normalize_question(item.question)
        }
        applied = 0
        items = getattr(resolutions, "resolutions", [])
        for resolution in items:
            if not bool(getattr(resolution, "supported", False)):
                continue
            answer = str(getattr(resolution, "answer", "") or "").strip()
            question = str(getattr(resolution, "question", "") or "").strip()
            key = normalize_question(question)
            local = local_by_key.get(key)
            if not answer or local is None:
                continue
            item = {
                "question": local.question,
                "field_type": local.field_type,
                "options": list(local.options),
                "suggested_answer": answer,
                "confidence": int(getattr(resolution, "confidence", 90) or 90),
                "requires_user_input": False,
                "note": "Resuelta por micro-LLM usando únicamente hechos compactos del perfil; pendiente de confirmación por envío real.",
            }
            if key in by_key:
                questions[by_key[key]] = item
            else:
                by_key[key] = len(questions)
                questions.append(item)
            applied += 1
        payload["questions"] = questions
        return payload, applied

    def _observe_form(self, result: DeterministicApplicationResult, *, successful: bool = False) -> None:
        if not result.observed_fields:
            return
        try:
            self.form_memory.observe(result.observed_fields)
            if successful:
                self.form_memory.confirm_success(result.observed_fields)
        except Exception:
            # Form-memory telemetry must never break an application.
            pass

    def _real_output(self, result: DeterministicApplicationResult) -> ApplicationDraftOutput:
        output = self._from_deterministic(result)
        return output.model_copy(update={"mode": "real", "test_mode": False})

    async def _apply(
        self,
        job: dict[str, object],
        *,
        ai_budget: AIUsageBudget | None = None,
    ) -> ApplicationDraftOutput:
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
            self._observe_form(local_result)

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
                output = self._real_output(local_result)
                if output.submitted:
                    self._observe_form(local_result, successful=True)
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

        # Unknown questions are not a reason to launch a full browser agent. Resolve
        # the exact questions in one compact text-only call and replay the form locally.
        unresolved = self._unresolved_questions(local_result) if local_result is not None else []
        resolver_enabled = os.getenv("JOB_AGENT_QUESTION_LLM", "1").strip().casefold() not in {"0", "false", "no", "off"}
        resolver_used = False
        if unresolved and resolver_enabled and os.getenv("BROWSER_USE_API_KEY") and local_result is not None:
            resolver_used = True
            try:
                resolutions = await self.question_resolver.resolve(
                    job=job,
                    profile=profile,
                    questions=unresolved,
                    ai_budget=ai_budget,
                )
                replay_draft, resolved_count = self._merge_resolved_answers(saved_draft, local_result, resolutions)
                if resolved_count:
                    replay = await self.deterministic_application.apply(
                        job=job,
                        profile=profile,
                        saved_draft=replay_draft,
                        mode="real",
                    )
                    self._observe_form(replay)
                    local_result = replay
                    saved_draft = replay_draft
                    fallback_reason = replay.fallback_reason or fallback_reason
                    if replay.terminal_without_ai:
                        self._last_mode = "ai_fallback"
                        self._last_fallback_reason = "micro_question_resolver"
                        output = self._real_output(replay)
                        remaining = sum(1 for item in output.questions if item.requires_user_input)
                        self._record_execution(
                            job_id=job_id,
                            mode="ai_fallback",
                            submitted=output.submitted,
                            unresolved_fields=remaining,
                            fallback_reason="micro_question_resolver",
                        )
                        if output.submitted:
                            self._observe_form(replay, successful=True)
                            self.answer_memory.remember_questions(
                                [item.model_dump() for item in output.questions],
                                submitted=True,
                            )
                        return output
            except Exception as exc:
                fallback_reason = f"Micro-resolvedor de preguntas: {type(exc).__name__}: {exc}"

        remaining_questions = self._unresolved_questions(local_result) if local_result is not None else []
        if remaining_questions:
            self._last_mode = "ai_fallback" if resolver_used else "deterministic"
            self._last_fallback_reason = fallback_reason
            output = self._real_output(local_result)
            reason = (
                "Quedan preguntas obligatorias cuya respuesta no está respaldada por el perfil o la memoria. "
                "Se detuvo sin lanzar un agente completo para evitar gasto e información inventada."
            )
            self._record_execution(
                job_id=job_id,
                mode="ai_fallback" if resolver_used else "deterministic",
                submitted=False,
                unresolved_fields=len(remaining_questions),
                fallback_reason=reason,
            )
            return output.model_copy(
                update={
                    "blocked_reason": reason,
                    "summary": reason,
                    "submitted": False,
                    "submission_status": "needs_attention",
                    "ready_to_submit": False,
                }
            )

        # Only unknown navigation/DOM structure reaches the expensive full agent.
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
                "La postulación determinística no pudo completar la navegación y no hay BROWSER_USE_API_KEY para el fallback. "
                f"Detalle: {fallback_reason}"
            )

        self._last_mode = "ai_fallback"
        try:
            result = await self._apply_with_ai(
                job,
                profile.model_dump(),
                saved_draft,
                application_mode,
                ai_budget=ai_budget,
            )
        except Exception:
            unresolved_count = (
                sum(1 for item in local_result.questions if item.requires_user_input)
                if local_result is not None
                else 0
            )
            self._record_execution(
                job_id=job_id,
                mode="ai_fallback",
                submitted=False,
                unresolved_fields=unresolved_count,
                fallback_reason=fallback_reason,
            )
            raise

        unresolved_count = (
            sum(1 for item in local_result.questions if item.requires_user_input)
            if local_result is not None
            else 0
        )
        self._record_execution(
            job_id=job_id,
            mode="ai_fallback",
            submitted=result.submitted,
            unresolved_fields=unresolved_count,
            fallback_reason=fallback_reason,
        )
        if result.submitted and local_result is not None:
            self._observe_form(local_result, successful=True)
        if result.submitted and result.questions and local_result is not None and local_result.observed_fields:
            self.pattern_store.confirm_success(
                local_result.observed_fields,
                [item.question for item in result.questions],
            )
        return result

    async def _apply_with_ai(
        self,
        job: dict[str, object],
        profile: dict[str, object],
        saved_draft: dict[str, object],
        application_mode: str = "real",
        *,
        ai_budget: AIUsageBudget | None = None,
    ) -> ApplicationDraftOutput:
        """Rare full-browser fallback, sharing the same batch AI budget."""
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

        llm = MeteredChatBrowserUse(
            model=requested_model,
            on_usage=persist_live_usage,
            usage_budget=ai_budget,
        )
        try:
            result_schema = RealApplicationDraftOutput if application_mode == "real" else ApplicationDraftOutput
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
                output_model_schema=result_schema,
                use_vision="auto",
                extend_system_message=(
                    "Use the full browser agent only for navigation or form structure that the deterministic runner could not handle. "
                    "Reuse supplied answers verbatim when equivalent. Never invent personal facts. Never bypass CAPTCHA, 2FA, bot "
                    "detection, or access controls. When finished, call done with exactly one data object containing the complete "
                    "structured result; all fields belong inside done.data."
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
