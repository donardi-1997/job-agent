from __future__ import annotations

import json
from pathlib import Path

from job_agent.computrabajo.deterministic_application import (
    DeterministicApplicationQuestion,
    DeterministicApplicationResult,
    ObservedField,
)
from job_agent.computrabajo.smoke_test import build_smoke_report, run_smoke_test
from job_agent.storage import JobRecord, JobStore


def _seed_job(path: Path) -> tuple[JobStore, int]:
    store = JobStore(path)
    store.upsert_jobs(
        [
            JobRecord(
                id=None,
                source="computrabajo",
                external_id="smoke-test-job",
                title="Backend Developer",
                company="Example SAS",
                location="Bogotá, D.C.",
                url="https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-backend-ABC",
                score=91,
                band="prepare",
            )
        ]
    )
    return store, int(store.list_jobs()[0]["id"])


def test_build_smoke_report_never_exposes_answers_or_current_values() -> None:
    field = ObservedField(
        question="¿Cuál es tu aspiración salarial?",
        field_type="text",
        selector="#salary",
        required=True,
        current_value="SUPER-PRIVATE-CURRENT-VALUE",
    )
    result = DeterministicApplicationResult(
        questions=(
            DeterministicApplicationQuestion(
                question=field.question,
                field_type=field.field_type,
                options=(),
                answer="SUPER-PRIVATE-ANSWER",
                confidence=100,
                requires_user_input=False,
                note="Resuelto localmente.",
            ),
        ),
        observed_fields=(field,),
        application_url="https://co.computrabajo.com/job",
        submitted=True,
        submission_status="already_applied",
        mode="test",
        test_mode=True,
        steps=2,
    )

    report = build_smoke_report(
        {
            "id": 4,
            "source": "computrabajo",
            "external_id": "abc",
            "title": "Backend Developer",
            "company": "Example SAS",
            "location": "Bogotá",
            "url": "https://co.computrabajo.com/job",
            "score": 90,
        },
        result,
    )
    serialized = json.dumps(report, ensure_ascii=False)

    assert "SUPER-PRIVATE-ANSWER" not in serialized
    assert "SUPER-PRIVATE-CURRENT-VALUE" not in serialized
    assert report["safety"]["submitted_by_smoke_test"] is False
    assert report["result"]["submitted_by_smoke_test"] is False
    assert report["result"]["preexisting_submission_state"] is True
    assert report["coverage"]["resolved_required_fields"] == 1


def test_run_smoke_test_forces_test_mode_and_writes_diagnostic_report(tmp_path: Path) -> None:
    store, job_id = _seed_job(tmp_path / "jobs.db")
    captured: dict[str, object] = {}

    class FakeDeterministicRunner:
        async def apply(self, **kwargs: object) -> DeterministicApplicationResult:
            captured.update(kwargs)
            field = ObservedField(
                question="¿Tienes experiencia con FastAPI?",
                field_type="radio",
                selector='input[name="fastapi"]',
                options=("Sí", "No"),
                required=True,
            )
            return DeterministicApplicationResult(
                questions=(
                    DeterministicApplicationQuestion(
                        question=field.question,
                        field_type=field.field_type,
                        options=field.options,
                        answer="Sí",
                        confidence=100,
                        requires_user_input=False,
                        note="Resuelto localmente.",
                    ),
                ),
                observed_fields=(field,),
                application_url="https://co.computrabajo.com/postulacion",
                submission_status="test_ready",
                ready_to_submit=True,
                mode="test",
                test_mode=True,
                steps=3,
            )

    report, output_path = run_smoke_test(
        job_id,
        db_path=store.path,
        profile_dir=tmp_path / "browser-profile",
        report_dir=tmp_path / "smoke-reports",
        deterministic_runner=FakeDeterministicRunner(),
    )

    assert captured["mode"] == "test"
    assert report["mode"] == "test"
    assert report["safety"]["final_submit_blocked"] is True
    assert report["safety"]["paid_ai_used"] is False
    assert report["result"]["ready_to_submit"] is True
    assert report["coverage"]["observed_fields"] == 1
    assert report["coverage"]["resolved_fields"] == 1
    assert report["coverage"]["unresolved_fields"] == 0
    assert output_path.exists()
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["result"]["submitted_by_smoke_test"] is False


def test_run_smoke_test_rejects_non_computrabajo_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    store.upsert_jobs(
        [
            JobRecord(
                id=None,
                source="linkedin",
                external_id="other-source",
                title="Backend Developer",
                company="Example SAS",
                location="Colombia",
                url="https://www.linkedin.com/jobs/view/123",
                score=90,
                band="prepare",
            )
        ]
    )
    job_id = int(store.list_jobs()[0]["id"])

    try:
        run_smoke_test(job_id, db_path=store.path, report_dir=tmp_path / "reports")
    except ValueError as exc:
        assert "solo admite vacantes de Computrabajo" in str(exc)
    else:
        raise AssertionError("Expected non-Computrabajo job to be rejected")
