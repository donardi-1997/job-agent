from pathlib import Path

import pytest

from job_agent.computrabajo import AssistedApplicationPreparer
from job_agent.computrabajo.cost_aware_application import CostAwareApplicationPreparer
from job_agent.computrabajo.deterministic_application import (
    DeterministicApplicationQuestion,
    DeterministicApplicationResult,
    ObservedField,
)
from job_agent.computrabajo.question_resolver import QuestionResolution, QuestionResolutionBatch
from job_agent.storage import JobStore


def test_dashboard_export_uses_cost_aware_preparer() -> None:
    assert AssistedApplicationPreparer is CostAwareApplicationPreparer


@pytest.mark.asyncio
async def test_unknown_question_uses_compact_resolver_then_deterministic_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = CostAwareApplicationPreparer(store=store, profile_dir=tmp_path / "browser")
    preparer.mode_store.set("real")
    monkeypatch.setenv("JOB_AGENT_ZERO_COST", "0")
    monkeypatch.setenv("JOB_AGENT_QUESTION_LLM", "1")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-key")

    field = ObservedField(
        question="¿Cuál es tu disponibilidad?",
        field_type="text",
        selector="#availability",
        required=True,
    )

    class Runner:
        calls = 0

        async def apply(self, *, saved_draft: dict[str, object], **_: object) -> DeterministicApplicationResult:
            self.calls += 1
            saved = saved_draft.get("questions") or []
            if not saved:
                return DeterministicApplicationResult(
                    questions=(
                        DeterministicApplicationQuestion(
                            question=field.question,
                            field_type="text",
                            options=(),
                            answer="",
                            confidence=0,
                            requires_user_input=True,
                        ),
                    ),
                    observed_fields=(field,),
                    application_url="https://co.computrabajo.com/job",
                    fallback_reason="1 campo obligatorio sin respuesta local",
                    mode="real",
                    test_mode=False,
                )
            return DeterministicApplicationResult(
                questions=(
                    DeterministicApplicationQuestion(
                        question=field.question,
                        field_type="text",
                        options=(),
                        answer="Inmediata",
                        confidence=100,
                        requires_user_input=False,
                    ),
                ),
                observed_fields=(field,),
                application_url="https://candidato.co.computrabajo.com/match/abc",
                submitted=True,
                submission_status="submitted",
                confirmation_text="Postulación confirmada por Computrabajo.",
                mode="real",
                test_mode=False,
            )

    class Resolver:
        async def resolve(self, **_: object) -> QuestionResolutionBatch:
            return QuestionResolutionBatch(
                resolutions=[
                    QuestionResolution(
                        question=field.question,
                        answer="Inmediata",
                        confidence=100,
                        supported=True,
                    )
                ]
            )

    async def full_agent_must_not_run(*_: object, **__: object):
        raise AssertionError("Full Browser Use agent must not run when compact resolution enables deterministic replay")

    runner = Runner()
    preparer.deterministic_application = runner  # type: ignore[assignment]
    preparer.question_resolver = Resolver()  # type: ignore[assignment]
    preparer._apply_with_ai = full_agent_must_not_run  # type: ignore[method-assign]

    result = await preparer._apply(
        {
            "id": 123,
            "title": "Backend Developer",
            "company": "Example SAS",
            "url": "https://co.computrabajo.com/job",
        }
    )

    assert runner.calls == 2
    assert result.submitted is True
    assert result.mode == "real"
    assert result.test_mode is False
    assert result.questions[0].suggested_answer == "Inmediata"
    assert preparer.form_memory.stats()["proven_forms"] == 1


@pytest.mark.asyncio
async def test_unsupported_new_question_stops_without_full_browser_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = CostAwareApplicationPreparer(store=store, profile_dir=tmp_path / "browser")
    preparer.mode_store.set("real")
    monkeypatch.setenv("JOB_AGENT_ZERO_COST", "0")
    monkeypatch.setenv("JOB_AGENT_QUESTION_LLM", "1")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-key")

    class Runner:
        async def apply(self, **_: object) -> DeterministicApplicationResult:
            return DeterministicApplicationResult(
                questions=(
                    DeterministicApplicationQuestion(
                        question="¿Cuál es tu número de licencia profesional?",
                        field_type="text",
                        options=(),
                        answer="",
                        confidence=0,
                        requires_user_input=True,
                    ),
                ),
                application_url="https://co.computrabajo.com/job",
                fallback_reason="Campo obligatorio desconocido",
                mode="real",
                test_mode=False,
            )

    class Resolver:
        async def resolve(self, **_: object) -> QuestionResolutionBatch:
            return QuestionResolutionBatch(
                resolutions=[
                    QuestionResolution(
                        question="¿Cuál es tu número de licencia profesional?",
                        supported=False,
                        confidence=0,
                        reason="El perfil no contiene ese dato.",
                    )
                ]
            )

    async def full_agent_must_not_run(*_: object, **__: object):
        raise AssertionError("Full agent must not try to invent an unsupported personal fact")

    preparer.deterministic_application = Runner()  # type: ignore[assignment]
    preparer.question_resolver = Resolver()  # type: ignore[assignment]
    preparer._apply_with_ai = full_agent_must_not_run  # type: ignore[method-assign]

    result = await preparer._apply({"id": 124, "title": "Developer", "url": "https://co.computrabajo.com/job"})

    assert result.submitted is False
    assert result.submission_status == "needs_attention"
    assert result.questions[0].requires_user_input is True
    assert "no está respaldada" in result.blocked_reason
