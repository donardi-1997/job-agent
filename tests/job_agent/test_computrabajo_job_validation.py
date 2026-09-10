from pathlib import Path

from job_agent.computrabajo.job_validation import (
    is_valid_computrabajo_job,
    purge_invalid_computrabajo_jobs,
)
from job_agent.storage import JobRecord, JobStore


VALID_URL = "https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-backend-developer-en-bogota-ABC123"
ERROR_URL = "https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-error-DEF456"


def _record(external_id: str, title: str, url: str) -> JobRecord:
    return JobRecord(
        id=None,
        source="computrabajo",
        external_id=external_id,
        title=title,
        company="Example SAS" if title != "403 Forbidden" else "computrabajo",
        location="Bogotá, Colombia" if title != "403 Forbidden" else "",
        url=url,
        score=90 if title != "403 Forbidden" else 3,
        band="prepare" if title != "403 Forbidden" else "ignore",
        description="Backend Python AWS" if title != "403 Forbidden" else "403 Forbidden",
    )


def test_validates_canonical_vacancy_and_rejects_error_pages() -> None:
    assert is_valid_computrabajo_job(title="Backend Developer", url=VALID_URL, description="Python AWS")
    assert not is_valid_computrabajo_job(title="403 Forbidden", url=ERROR_URL, description="403 Forbidden")
    assert not is_valid_computrabajo_job(
        title="Backend Developer",
        url="https://co.computrabajo.com/trabajo-de-python-developer",
        description="Python AWS",
    )
    assert not is_valid_computrabajo_job(
        title="Backend Developer",
        url="https://evil.example/ofertas-de-trabajo/oferta-de-trabajo-de-backend-123",
        description="Python AWS",
    )


def test_purge_removes_historical_403_job_and_attempt_but_keeps_real_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    store.upsert_jobs([
        _record("valid", "Backend Developer", VALID_URL),
        _record("error", "403 Forbidden", ERROR_URL),
    ])
    jobs = store.list_jobs(limit=20)
    error_job = next(job for job in jobs if job["external_id"] == "error")
    valid_job = next(job for job in jobs if job["external_id"] == "valid")

    store.save_application_attempt(
        int(error_job["id"]),
        {
            "mode": "real",
            "test_mode": False,
            "submitted": True,
            "submission_status": "submitted",
            "confirmation_text": "Postulación enviada",
        },
    )
    assert store.get_job(int(error_job["id"]))["status"] == "applied"

    removed = purge_invalid_computrabajo_jobs(store.path)

    assert removed == 1
    assert store.get_job(int(error_job["id"])) is None
    assert store.get_job(int(valid_job["id"])) is not None
    assert store.list_application_attempts(int(error_job["id"])) == []
