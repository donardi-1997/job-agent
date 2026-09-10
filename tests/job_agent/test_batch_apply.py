from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.computrabajo.batch import BatchApplyRequest, BatchApplyRunner
from job_agent.profile import ProfileStore, UserProfile
from job_agent.storage import JobRecord, JobStore


def _job(external_id: str, score: int, status: str = "discovered", description: str = "") -> JobRecord:
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
		description=description,
	)


def test_batch_request_validates_limits() -> None:
	request = BatchApplyRequest(keyword="Python", min_score=85, max_applications=10, daily_limit=20)
	assert request.max_applications == 10
	assert request.daily_limit == 20
	assert request.max_search_terms == 8
	assert request.max_ai_calls == 10
	assert request.max_ai_cost_usd == 0.10

	with pytest.raises(ValidationError):
		BatchApplyRequest(keyword="Python", max_applications=26)
	with pytest.raises(ValidationError):
		BatchApplyRequest(keyword="Python", daily_limit=51)
	with pytest.raises(ValidationError):
		BatchApplyRequest(max_search_terms=13)
	with pytest.raises(ValidationError):
		BatchApplyRequest(max_ai_calls=-1)
	with pytest.raises(ValidationError):
		BatchApplyRequest(max_ai_cost_usd=-0.01)


def test_batch_can_be_configured_as_zero_ai() -> None:
	request = BatchApplyRequest(max_ai_calls=0, max_ai_cost_usd=0)

	assert request.max_ai_calls == 0
	assert request.max_ai_cost_usd == 0


def test_personal_batch_uses_skills_roles_and_deduplicates_optional_term(tmp_path: Path) -> None:
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

	assert "Python Backend Developer" in terms
	assert "AWS Developer" in terms
	assert "Cloud Developer" in terms
	assert "Backend Developer" in terms
	assert sum(term.casefold() == "backend developer" for term in terms) == 1
	assert len(terms) <= 8


def test_personal_batch_adds_one_optional_custom_search_term(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	ProfileStore(store.path).save(
		UserProfile(target_roles=["Python Developer", "Backend Developer"], skills=["Python", "FastAPI"])
	)
	runner = BatchApplyRunner(store=store)

	terms = runner._search_terms(BatchApplyRequest(keyword="Shopify Developer"))

	assert "Python Backend Developer" in terms
	assert terms[-1] == "Shopify Developer"


def test_personal_batch_respects_search_term_cap(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	ProfileStore(store.path).save(
		UserProfile(target_roles=[f"Role {index}" for index in range(1, 10)], skills=[])
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


def test_batch_hard_eligibility_filters_salary_english_and_experience_before_apply(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	ProfileStore(store.path).save(
		UserProfile(
			years_experience=5,
			english_level="A2",
			min_monthly_salary_cop=4_000_000,
		)
	)
	store.upsert_jobs([
		_job("ok", 95, description="Backend Python. Salario COP 5.000.000."),
		_job("salary", 95, description="Salario COP 3.500.000 mensuales."),
		_job("english", 95, description="Inglés B1 mínimo excluyente."),
		_job("years", 95, description="Requisito obligatorio: mínimo 7 años de experiencia."),
	])
	runner = BatchApplyRunner(store=store)

	eligible = runner._current_search_jobs(["ok", "salary", "english", "years"], 85)

	assert [job["external_id"] for job in eligible] == ["ok"]


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
