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
from job_agent.storage import ApplicationModeStore, JobRecord, JobStore


def _seed_job(store: JobStore, external_id: str = "application-test") -> int:
    store.upsert_jobs(
        [
            JobRecord(
                id=None,
                source="computrabajo",
                external_id=external_id,
                title="Python Developer",
                company="Example SAS",
                location="Colombia",
                url="https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-ABC",
                score=95,
                band="prepare",
            )
        ]
    )
    return int(store.list_jobs()[0]["id"])


def test_application_url_allowlist_is_strict() -> None:
    assert is_safe_application_url("https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-ABC") is True
    assert is_safe_application_url("https://secure.computrabajo.com/login") is True
    assert is_safe_application_url("http://co.computrabajo.com/job") is False
    assert is_safe_application_url("https://accounts.google.com/signin") is False
    assert is_safe_application_url("https://co.computrabajo.com.evil.test/job") is False


def test_application_mode_defaults_to_test_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    modes = ApplicationModeStore(path)

    assert modes.get() == "test"
    assert modes.set("real") == "real"
    assert ApplicationModeStore(path).get() == "real"
    assert modes.set("test") == "test"
    assert ApplicationModeStore(path).get() == "test"


def test_application_mode_rejects_invalid_values(tmp_path: Path) -> None:
    modes = ApplicationModeStore(tmp_path / "jobs.db")

    with pytest.raises(ValueError, match="mode must"):
        modes.set("preview")


def test_application_mode_store_is_compatible_with_profile_settings_schema(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    ApplicationModeStore(path)
    # Constructing a preparer after the mode store exercises the shared app_settings schema.
    preparer = AssistedApplicationPreparer(store=JobStore(path), profile_dir=tmp_path / "browser")

    assert preparer.mode_store.get() == "test"
    assert preparer.profile_store.get().automation_enabled is True


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
async def test_test_mode_never_calls_ai_and_never_reports_submitted(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = AssistedApplicationPreparer(store=store, profile_dir=tmp_path / "browser")
    assert preparer.mode_store.get() == "test"

    class LocalRunner:
        async def apply(self, **_: object) -> DeterministicApplicationResult:
            # Deliberately return an inconsistent/malicious result to verify the
            # application-layer invariant still forces TEST to unsubmitted.
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
                application_url="https://co.computrabajo.com/job",
                submitted=True,
                submission_status="submitted",
                confirmation_text="Should be discarded",
                confirmation_url="https://co.computrabajo.com/confirmation",
                mode="test",
                test_mode=True,
                ready_to_submit=True,
            )

    async def ai_must_not_run(*_: object, **__: object) -> ApplicationDraftOutput:
        raise AssertionError("AI fallback must never receive control in TEST mode")

    preparer.deterministic_application = LocalRunner()  # type: ignore[assignment]
    preparer._apply_with_ai = ai_must_not_run  # type: ignore[method-assign]

    result = await preparer._apply(
        {
            "id": 999,
            "url": "https://co.computrabajo.com/job",
            "title": "Python Developer",
        }
    )

    assert result.mode == "test"
    assert result.test_mode is True
    assert result.submitted is False
    assert result.submission_status == "test_ready"
    assert result.ready_to_submit is True
    assert result.confirmation_text == ""
    assert result.confirmation_url == ""
    assert preparer.application_efficiency()["ai_fallback"] == 0


@pytest.mark.asyncio
async def test_test_mode_stops_locally_on_unknown_required_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = AssistedApplicationPreparer(store=store, profile_dir=tmp_path / "browser")
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-key-that-must-not-be-used")

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
                mode="test",
                test_mode=True,
            )

    async def ai_must_not_run(*_: object, **__: object) -> ApplicationDraftOutput:
        raise AssertionError("TEST mode must not call Browser Use even when an API key exists")

    preparer.deterministic_application = LocalRunner()  # type: ignore[assignment]
    preparer._apply_with_ai = ai_must_not_run  # type: ignore[method-assign]

    result = await preparer._apply({"id": 1000, "url": "https://co.computrabajo.com/job", "title": "Backend Developer"})

    assert result.submitted is False
    assert result.submission_status == "test_incomplete"
    assert result.ready_to_submit is False
    assert result.questions[0].requires_user_input is True
    assert preparer.application_efficiency()["ai_fallback"] == 0


@pytest.mark.asyncio
async def test_real_mode_preserves_deterministic_submission(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = AssistedApplicationPreparer(store=store, profile_dir=tmp_path / "browser")
    preparer.mode_store.set("real")

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
                mode="real",
                test_mode=False,
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
    assert result.mode == "real"
    assert result.test_mode is False
    assert result.questions[0].suggested_answer == "Inmediata"
    stats = preparer.application_efficiency()
    assert stats["deterministic"] == 1
    assert stats["ai_fallback"] == 0


@pytest.mark.asyncio
async def test_real_mode_uses_ai_only_after_local_unresolved_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JobStore(tmp_path / "jobs.db")
    preparer = AssistedApplicationPreparer(store=store, profile_dir=tmp_path / "browser")
    preparer.mode_store.set("real")
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
                mode="real",
                test_mode=False,
            )

    async def fake_ai(*_: object, **__: object) -> ApplicationDraftOutput:
        return ApplicationDraftOutput(
            questions=[],
            application_url="https://co.computrabajo.com/job",
            submitted=False,
            submission_status="not_submitted",
            blocked_reason="Necesita respuesta del usuario",
            mode="real",
            test_mode=False,
        )

    preparer.deterministic_application = LocalRunner()  # type: ignore[assignment]
    preparer._apply_with_ai = fake_ai  # type: ignore[method-assign]

    result = await preparer._apply({"id": 1000, "url": "https://co.computrabajo.com/job", "title": "Backend Developer"})

    assert result.submitted is False
    stats = preparer.application_efficiency()
    assert stats["deterministic"] == 0
    assert stats["ai_fallback"] == 1


def test_test_mode_prompt_explicitly_forbids_final_submission() -> None:
    task = AssistedApplicationPreparer._build_task(
        {"id": 1, "url": "https://co.computrabajo.com/job", "title": "Backend Developer"},
        {},
        {},
        application_mode="test",
    )

    assert "Do not submit it" in task
    assert "Never click or trigger the final application/submit/confirm action in TEST mode" in task


def test_test_attempt_payload_is_persisted_without_marking_submitted(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    job_id = _seed_job(store)
    payload = ApplicationDraftOutput(
        mode="test",
        test_mode=True,
        ready_to_submit=True,
        submitted=False,
        submission_status="test_ready",
        summary="Formulario completado en modo prueba. Listo para enviar.",
    ).model_dump()

    store.save_application_attempt(job_id, payload)
    attempt = store.list_application_attempts(job_id)[0]

    assert attempt["submitted"] is False
    assert attempt["submission_status"] == "test_ready"
    assert attempt["payload"]["mode"] == "test"
    assert attempt["payload"]["ready_to_submit"] is True
    assert store.get_job(job_id)["status"] != "applied"


def test_test_result_does_not_increment_successful_pattern_counter(tmp_path: Path) -> None:
    patterns = ApplicationPatternStore(tmp_path / "jobs.db")
    fields = (
        ObservedField(
            question="¿Cuál es tu disponibilidad?",
            field_type="text",
            selector="#availability",
            required=True,
        ),
    )
    patterns.observe(fields)

    # A TEST-ready form is an observation, not evidence of a successful submission.
    result = DeterministicApplicationResult(
        observed_fields=fields,
        mode="test",
        test_mode=True,
        ready_to_submit=True,
        submission_status="test_ready",
    )

    assert result.submitted is False
    stats = patterns.stats()
    assert stats["patterns"] == 1
    assert stats["proven_patterns"] == 0
    assert stats["successful_uses"] == 0
