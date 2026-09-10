from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.computrabajo.batch import BatchApplyRequest, BatchApplyRunner
from job_agent.profile import ProfileStore, UserProfile
from job_agent.storage import JobRecord, JobStore


def _job(external_id: str, score: int, status: str = "discovered") -> JobRecord:
	return JobRecord(
		id=None,
		source="computrabajo",
		external_id=external_id,
		title=f"Python Developer {external_id}",
		company="Example SAS",
		location="Colombia",
		url=f"https://co.computrabajo.com/{external_id}",
		score=score,
		band="prepare" if score >= 85 else "recommend",
		status=status,
	)


def test_batch_request_validates_limits() -> None:
	request = BatchApplyRequest(keyword="Python", min_score=85, max_applications=10, daily_limit=20)
	assert request.max_applications == 10
	assert request.daily_limit == 20
	assert request.max_search_terms == 8

	with pytest.raises(ValidationError):
		BatchApplyRequest(keyword="Python", max_applications=26)
	with pytest.raises(ValidationError):
		BatchApplyRequest(keyword="Python", daily_limit=51)
	with pytest.raises(ValidationError):
		BatchApplyRequest(max_search_terms=13)


def test_personal_batch_uses_profile_roles_and_deduplicates_optional_term(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	ProfileStore(store.path).save(
		UserProfile(
			target_roles=["Python Developer", "Backend Developer", "AWS Developer", "AI Engineer"],
			skills=["Python", "FastAPI", "AWS"],
		)
	)
	runner = BatchApplyRunner(store=store)

	request = BatchApplyRequest(keyword="backend developer", max_search_terms=8)
	terms = runner._search_terms(request)

	assert terms == ["Python Developer", "Backend Developer", "AWS Developer", "AI Engineer"]


def test_personal_batch_adds_one_optional_custom_search_term(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	ProfileStore(store.path).save(UserProfile(target_roles=["Python Developer", "Backend Developer"]))
	runner = BatchApplyRunner(store=store)

	terms = runner._search_terms(BatchApplyRequest(keyword="FastAPI Developer"))

	assert terms == ["Python Developer", "Backend Developer", "FastAPI Developer"]


def test_personal_batch_respects_search_term_cap(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	ProfileStore(store.path).save(
		UserProfile(target_roles=[f"Role {index}" for index in range(1, 10)])
	)
	runner = BatchApplyRunner(store=store)

	terms = runner._search_terms(BatchApplyRequest(max_search_terms=3))

	assert terms == ["Role 1", "Role 2", "Role 3"]


def test_batch_eligibility_excludes_applied_ignored_and_low_score(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	store.upsert_jobs([
		_job("eligible", 92),
		_job("low", 75),
		_job("applied", 95, "applied"),
		_job("ignored", 90, "ignored"),
	])
	runner = BatchApplyRunner(store=store)
	eligible = runner._current_search_jobs(["eligible", "low", "applied", "ignored"], 85)

	assert [job["external_id"] for job in eligible] == ["eligible"]


def test_batch_history_and_daily_submitted_count_are_persisted(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	store.upsert_jobs([_job("submitted", 95)])
	job_id = int(store.list_jobs()[0]["id"])
	store.save_application_attempt(job_id, {"submitted": True, "submission_status": "submitted"})

	run_id = store.create_batch_run(
		keyword="Python Developer · Backend Developer",
		location="Colombia",
		min_score=85,
		max_applications=10,
	)
	store.update_batch_run(run_id, state="completed", found=12, eligible=4, attempted=4, submitted=3, blocked=1)

	assert store.count_submitted_today() == 1
	history = store.list_batch_runs()
	assert history[0]["id"] == run_id
	assert history[0]["submitted"] == 3
	assert history[0]["state"] == "completed"
