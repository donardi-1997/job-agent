from pathlib import Path

from job_agent.computrabajo.applications_sync import (
    ComputrabajoApplicationsStore,
    DeterministicApplicationsReader,
    SyncedApplication,
)
from job_agent.storage import JobRecord, JobStore


PUBLIC_URL = "https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-backend-developer-en-bogota-ABC123"
CANDIDATE_URL = "https://candidato.co.computrabajo.com/candidate/match/ABC123"


def _job(external_id: str = "local", *, status: str = "saved") -> JobRecord:
    return JobRecord(
        id=None,
        source="computrabajo",
        external_id=external_id,
        title="Backend Developer",
        company="Example SAS",
        location="Bogotá, Colombia",
        url=PUBLIC_URL,
        score=91,
        band="prepare",
        status=status,
        description="Python AWS APIs",
    )


def _sync_item(**changes: object) -> SyncedApplication:
    values: dict[str, object] = {
        "external_key": "sync-abc123",
        "title": "Backend Developer",
        "company": "Example SAS",
        "location": "Bogotá",
        "status_text": "Postulada",
        "date_text": "10/09/2026",
        "candidate_url": CANDIDATE_URL,
        "public_job_url": PUBLIC_URL,
        "raw_text": "Backend Developer Example SAS Postulada",
    }
    values.update(changes)
    return SyncedApplication(**values)  # type: ignore[arg-type]


def test_sync_promotes_matching_local_job_to_applied(tmp_path: Path) -> None:
    job_store = JobStore(tmp_path / "jobs.db")
    job_store.upsert_jobs([_job()])
    local = job_store.list_jobs(limit=10)[0]
    assert local["status"] == "saved"

    sync_store = ComputrabajoApplicationsStore(job_store.path, job_store=job_store)
    stats = sync_store.sync((_sync_item(),))

    assert stats == {"found": 1, "linked": 1, "promoted": 1, "unlinked": 0}
    assert job_store.get_job(int(local["id"]))["status"] == "applied"
    items = sync_store.list_combined()
    assert len(items) == 1
    assert items[0]["verified_in_computrabajo"] is True
    assert items[0]["origin"] == "Computrabajo"
    assert items[0]["job_id"] == int(local["id"])


def test_local_submission_plus_sync_is_shown_as_verified_by_both_sources(tmp_path: Path) -> None:
    job_store = JobStore(tmp_path / "jobs.db")
    job_store.upsert_jobs([_job(status="discovered")])
    local = job_store.list_jobs(limit=10)[0]
    job_store.save_application_attempt(
        int(local["id"]),
        {
            "mode": "real",
            "test_mode": False,
            "submitted": True,
            "submission_status": "submitted",
            "confirmation_text": "Postulación enviada",
        },
    )

    sync_store = ComputrabajoApplicationsStore(job_store.path, job_store=job_store)
    sync_store.sync((_sync_item(),))
    items = sync_store.list_combined()

    assert len(items) == 1
    assert items[0]["origin"] == "Job Agent + Computrabajo"
    assert items[0]["verified_in_computrabajo"] is True


def test_unmatched_external_application_is_kept_without_fabricating_job(tmp_path: Path) -> None:
    job_store = JobStore(tmp_path / "jobs.db")
    sync_store = ComputrabajoApplicationsStore(job_store.path, job_store=job_store)
    external = _sync_item(
        external_key="external-only",
        title="Cloud Engineer",
        company="Otra Empresa",
        public_job_url="",
        candidate_url="https://candidato.co.computrabajo.com/candidate/match/XYZ987",
    )

    stats = sync_store.sync((external,))
    items = sync_store.list_combined()

    assert stats["unlinked"] == 1
    assert job_store.list_jobs(limit=10) == []
    assert len(items) == 1
    assert items[0]["job_id"] is None
    assert items[0]["origin"] == "Computrabajo"
    assert items[0]["title"] == "Cloud Engineer"


def test_reader_rejects_rows_without_a_safe_process_or_public_vacancy_url() -> None:
    assert DeterministicApplicationsReader._parse_item(
        {
            "title": "Backend Developer",
            "company": "Example SAS",
            "candidate_url": "https://evil.example/candidate/match/ABC",
            "public_job_url": "",
        }
    ) is None

    parsed = DeterministicApplicationsReader._parse_item(
        {
            "title": "Backend Developer",
            "company": "Example SAS",
            "candidate_url": CANDIDATE_URL,
            "public_job_url": PUBLIC_URL,
        }
    )
    assert parsed is not None
    assert parsed.title == "Backend Developer"
    assert parsed.candidate_url.startswith("https://candidato.co.computrabajo.com/")
