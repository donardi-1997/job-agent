from pathlib import Path

from job_agent.storage import JobRecord, JobStore


def test_job_detail_metadata_and_status_are_persisted(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	store.upsert_jobs(
		[
			JobRecord(
				id=None,
				source="computrabajo",
				external_id="job-1",
				title="Python Developer",
				company="Example SAS",
				location="Bogotá",
				url="https://co.computrabajo.com/job-1",
				score=90,
				band="prepare",
				description="Python FastAPI AWS role",
				match_reasons=("Target role matches: 1", "Skill matches: 3/4"),
				matched_skills=("Python", "FastAPI", "AWS"),
				missing_skills=("Docker",),
			)
		]
	)

	job = store.list_jobs()[0]
	detail = store.get_job(int(job["id"]))

	assert detail is not None
	assert detail["description"] == "Python FastAPI AWS role"
	assert detail["matched_skills"] == ["Python", "FastAPI", "AWS"]
	assert detail["missing_skills"] == ["Docker"]

	updated = store.update_status(int(job["id"]), "saved")
	assert updated is not None
	assert updated["status"] == "saved"


def test_upsert_does_not_overwrite_user_review_status(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	job = JobRecord(
		id=None,
		source="computrabajo",
		external_id="same-job",
		title="Backend Developer",
		company="Example",
		location="Colombia",
		url="https://co.computrabajo.com/same-job",
		score=80,
		band="recommend",
	)
	store.upsert_jobs([job])
	job_id = int(store.list_jobs()[0]["id"])
	store.update_status(job_id, "ignored")
	store.upsert_jobs([job])

	assert store.get_job(job_id)["status"] == "ignored"
