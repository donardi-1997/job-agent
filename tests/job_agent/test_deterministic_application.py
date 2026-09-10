from pathlib import Path

import pytest

from job_agent.computrabajo.application import ApplicationDraftOutput, AssistedApplicationPreparer
from job_agent.computrabajo.deterministic_application import (
    ApplicationExecutionStore,
    ApplicationPatternStore,
    DeterministicApplicationQuestion,
    DeterministicApplicationResult,
    ObservedField,
    is_safe_application_url,
)
from job_agent.storage import JobStore


def test_application_url_allowlist_is_strict() -> None:
    assert is_safe_application_url("https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-ABC") is True
    assert is_safe_application_url("https://secure.computrabajo.com/login") is True
    assert is_safe_application_url("http://co.computrabajo.com/job") is False
    assert is_safe_application_url("https://accounts.google.com/signin") is False
    assert is_safe_application_url("https://co.computrabajo.com.evil.test/job") is False


def test_application_execution_store_reports_deterministic_rate(tmp_path: Path) -> None:
    store = ApplicationExecutionStore(tmp_path / "jobs.db")
    store.record(job_id=1, mode="deterministic", submitted=True)
    store.record(job_id=2, mode="deterministic", submitted=False)
    store.record(job_id=3, mode="ai_fallback", submitted=True, unresolved_fields=1)

    stats = store.summary()

    assert stats["total"] == 3
    assert stats["deterministic"] == 2
    assert stats["ai_fallback"] == 1
    assert stats["submitted"] == 2
    assert stats["deterministic_rate"] == 66.7


def test_application_pattern_store_learns_observed_and_successful_fields(tmp_path: Path) -> None:
    store = ApplicationPatternStore(tmp_path / "jobs.db")
    fields = (
        ObservedField(
            question="¿Cuál es tu disponibilidad?",
            field_type="text",
            selector="#availability",
            required=True,
        ),
    )

    store.observe(fields)
    before = store.stats()
    store.confirm_success(fields, ["¿Cuál es tu disponibilidad?"])
    after = store.stats()

    assert before["patterns"] == 1
    assert before["proven_patterns"] == 0
    assert after["patterns"] == 1
    assert after["proven_patterns"] == 1
    assert after["successful_uses"] == 1


@pytest.mark.asyncio
async def test_preparer_does_not_call_ai_when_deterministic_submission_succeeds(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = AssistedApplicationPreparer(store=store, profile_dir=tmp_path / "browser")

    class LocalRunner:
        async def apply(self, **_: object) -> DeterministicApplicationResult:
            return DeterministicApplicationResult(
                questions=(
                    DeterministicApplicationQuestion(
                        question="Disponibilidad",
                        field_type="text",
                        options=(),
                        answer="Inmediata",
                        confidence=100,
                        requires_user_input=False,
                    ),
                ),
                application_url="https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-ABC",
                submitted=True,
                submission_status="submitted",
                confirmation_text="Postulación confirmada por Computrabajo.",
                confirmation_url="https://co.computrabajo.com/postulacion-confirmada",
                steps=3,
            )

    async def ai_must_not_run(*_: object, **__: object) -> ApplicationDraftOutput:
        raise AssertionError("AI fallback must not run after deterministic submission")

    preparer.deterministic_application = LocalRunner()  # type: ignore[assignment]
    preparer._apply_with_ai = ai_must_not_run  # type: ignore[method-assign]

    result = await preparer._apply(
        {
            "id": 999,
            "url": "https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-ABC",
            "title": "Python Developer",
        }
    )

    assert result.submitted is True
    assert result.questions[0].suggested_answer == "Inmediata"
    assert preparer.status()["state"] == "idle"
    stats = preparer.application_efficiency()
    assert stats["deterministic"] == 1
    assert stats["ai_fallback"] == 0


@pytest.mark.asyncio
async def test_preparer_uses_ai_only_after_local_unresolved_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = AssistedApplicationPreparer(store=store, profile_dir=tmp_path / "browser")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-key")

    observed = ObservedField(
        question="¿Tienes disponibilidad para viajar?",
        field_type="radio",
        selector='input[name="travel"]',
        options=("Sí", "No"),
        required=True,
    )

    class LocalRunner:
        async def apply(self, **_: object) -> DeterministicApplicationResult:
            return DeterministicApplicationResult(
                questions=(
                    DeterministicApplicationQuestion(
                        question=observed.question,
                        field_type="radio",
                        options=observed.options,
                        answer="",
                        confidence=0,
                        requires_user_input=True,
                    ),
                ),
                observed_fields=(observed,),
                application_url="https://co.computrabajo.com/job",
                fallback_reason="1 campo obligatorio sin respuesta local",
                steps=2,
            )

    async def fake_ai(*_: object, **__: object) -> ApplicationDraftOutput:
        return ApplicationDraftOutput(
            questions=[],
            application_url="https://co.computrabajo.com/job",
            submitted=False,
            submission_status="not_submitted",
            blocked_reason="Necesita respuesta del usuario",
        )

    preparer.deterministic_application = LocalRunner()  # type: ignore[assignment]
    preparer._apply_with_ai = fake_ai  # type: ignore[method-assign]

    result = await preparer._apply(
        {
            "id": 1000,
            "url": "https://co.computrabajo.com/job",
            "title": "Backend Developer",
        }
    )

    assert result.submitted is False
    stats = preparer.application_efficiency()
    assert stats["deterministic"] == 0
    assert stats["ai_fallback"] == 1
