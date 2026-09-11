from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from job_agent.answer_memory import AnswerMemory, normalize_question
from job_agent.async_runtime import run_async
from job_agent.computrabajo.deterministic_application import (
    ApplicationPatternStore,
    DeterministicApplicationResult,
    DeterministicApplicationRunner,
)
from job_agent.profile import ProfileStore
from job_agent.storage import DEFAULT_DB_PATH, JobStore


DEFAULT_PROFILE_DIR = Path("data/browser-profile")
DEFAULT_SMOKE_REPORT_DIR = Path("data/smoke-tests")


class DeterministicSmokeRunner(Protocol):
    async def apply(self, **kwargs: object) -> DeterministicApplicationResult: ...


def _field_key(question: str, field_type: str) -> tuple[str, str]:
    return normalize_question(question), field_type.strip().casefold()


def select_smoke_job_id(*, db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Pick the best safe, application-ready Computrabajo vacancy from local storage."""
    store = JobStore(db_path)
    profile = ProfileStore(store.path).get()
    candidates = store.list_jobs(limit=100, min_score=profile.prepare_application_score)
    for job in candidates:
        if str(job.get("source") or "").strip().casefold() != "computrabajo":
            continue
        if str(job.get("status") or "").strip().casefold() in {"applied", "ignored"}:
            continue
        job_id = job.get("id")
        if isinstance(job_id, int) and job_id > 0:
            return job_id
    raise ValueError(
        "No hay una vacante de Computrabajo elegible para smoke test con score >= "
        f"{profile.prepare_application_score}. Ejecuta una búsqueda o indica un JOB_ID explícito."
    )


def build_smoke_report(job: dict[str, object], result: DeterministicApplicationResult) -> dict[str, Any]:
    """Build a diagnostic report without persisting candidate answers or field values."""
    questions = {
        _field_key(item.question, item.field_type): item
        for item in result.questions
        if normalize_question(item.question)
    }

    fields: list[dict[str, object]] = []
    resolved_required = 0
    unresolved_required = 0
    required_fields = 0

    for field in result.observed_fields:
        question = questions.get(_field_key(field.question, field.field_type))
        resolved = bool(question and not question.requires_user_input)
        if field.required:
            required_fields += 1
            if resolved or bool(field.current_value):
                resolved_required += 1
            else:
                unresolved_required += 1
        fields.append(
            {
                "question": field.question,
                "field_type": field.field_type,
                "selector": field.selector,
                "options": list(field.options),
                "required": field.required,
                "current_value_present": bool(field.current_value),
                "resolved_locally": resolved,
                "requires_user_input": bool(question.requires_user_input) if question else bool(field.required),
                "note": question.note if question else "",
            }
        )

    observed_fields = len(result.observed_fields)
    resolved_fields = sum(1 for item in fields if bool(item["resolved_locally"]) or bool(item["current_value_present"]))
    unresolved_fields = sum(1 for item in fields if bool(item["requires_user_input"]))
    resolution_rate = round(resolved_fields / observed_fields * 100, 1) if observed_fields else 0.0
    required_resolution_rate = round(resolved_required / required_fields * 100, 1) if required_fields else 100.0

    # The deterministic TEST runner never clicks a recognized final submit action.
    # If the page already contains a success/already-applied confirmation, the raw
    # result can describe that pre-existing state. The smoke report itself must never
    # claim that this run submitted an application.
    preexisting_submission_state = bool(result.submitted) or result.submission_status in {"submitted", "already_applied"}

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "test",
        "safety": {
            "final_submit_blocked": True,
            "paid_ai_used": False,
            "submitted_by_smoke_test": False,
        },
        "job": {
            "id": int(job.get("id") or 0),
            "source": str(job.get("source") or ""),
            "external_id": str(job.get("external_id") or ""),
            "title": str(job.get("title") or ""),
            "company": str(job.get("company") or ""),
            "location": str(job.get("location") or ""),
            "url": str(job.get("url") or ""),
            "score": int(job.get("score") or 0),
        },
        "result": {
            "application_url": result.application_url,
            "login_required": result.login_required,
            "blocked_reason": result.blocked_reason,
            "fallback_reason": result.fallback_reason,
            "page_state_submission_status": result.submission_status,
            "preexisting_submission_state": preexisting_submission_state,
            "ready_to_submit": result.ready_to_submit,
            "steps": result.steps,
            "submitted_by_smoke_test": False,
        },
        "coverage": {
            "observed_fields": observed_fields,
            "resolved_fields": resolved_fields,
            "unresolved_fields": unresolved_fields,
            "required_fields": required_fields,
            "resolved_required_fields": resolved_required,
            "unresolved_required_fields": unresolved_required,
            "resolution_rate": resolution_rate,
            "required_resolution_rate": required_resolution_rate,
        },
        "fields": fields,
    }


def run_smoke_test(
    job_id: int,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    profile_dir: Path | str = DEFAULT_PROFILE_DIR,
    report_dir: Path | str = DEFAULT_SMOKE_REPORT_DIR,
    deterministic_runner: DeterministicSmokeRunner | None = None,
) -> tuple[dict[str, Any], Path]:
    """Inspect and fill one real Computrabajo application in TEST mode without submitting it."""
    store = JobStore(db_path)
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Vacante {job_id} no encontrada.")
    if str(job.get("source") or "").strip().casefold() != "computrabajo":
        raise ValueError("El smoke test solo admite vacantes de Computrabajo.")

    profile = ProfileStore(store.path).get()
    saved_draft = store.get_application_draft(job_id) or {}
    runner = deterministic_runner or DeterministicApplicationRunner(
        profile_dir,
        AnswerMemory(store.path),
        ApplicationPatternStore(store.path),
    )

    result = run_async(
        runner.apply(
            job=job,
            profile=profile,
            saved_draft=saved_draft,
            mode="test",
        )
    )
    report = build_smoke_report(job, result)

    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"computrabajo-job-{job_id}-{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, output_path
