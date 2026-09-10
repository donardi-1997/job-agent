from pathlib import Path

from job_agent.computrabajo.batch import BatchApplyRunner
from job_agent.config import CandidateProfile, SearchPreferences
from job_agent.profile import ProfileStore, UserProfile
from job_agent.salary_policy import DEFAULT_MIN_MONTHLY_SALARY_COP, assess_salary_text
from job_agent.scoring import JobPosting, score_job
from job_agent.storage import JobRecord, JobStore


def test_default_salary_floor_is_four_million_cop() -> None:
	assert UserProfile().min_monthly_salary_cop == 4_000_000
	assert SearchPreferences().min_monthly_salary_cop == 4_000_000
	assert DEFAULT_MIN_MONTHLY_SALARY_COP == 4_000_000


def test_fixed_salary_below_floor_is_blocked() -> None:
	assessment = assess_salary_text("Salario: $ 3.500.000 COP mensual", 4_000_000)
	assert assessment.published is True
	assert assessment.maximum_cop == 3_500_000
	assert assessment.blocked is True


def test_fixed_salary_at_floor_is_allowed() -> None:
	assessment = assess_salary_text("Salario mensual $4.000.000", 4_000_000)
	assert assessment.published is True
	assert assessment.maximum_cop == 4_000_000
	assert assessment.blocked is False


def test_range_entirely_below_floor_is_blocked() -> None:
	assessment = assess_salary_text("Rango salarial: 3,2 millones a 3,8 millones mensuales", 4_000_000)
	assert assessment.minimum_cop == 3_200_000
	assert assessment.maximum_cop == 3_800_000
	assert assessment.blocked is True


def test_range_reaching_floor_is_not_automatically_blocked() -> None:
	assessment = assess_salary_text("Salario: 3,5 millones a 4,5 millones al mes", 4_000_000)
	assert assessment.minimum_cop == 3_500_000
	assert assessment.maximum_cop == 4_500_000
	assert assessment.blocked is False


def test_missing_salary_is_not_blocked() -> None:
	assessment = assess_salary_text("Buscamos Python Developer con AWS y FastAPI.", 4_000_000)
	assert assessment.published is False
	assert assessment.blocked is False


def test_explicit_annual_salary_is_not_misread_as_monthly() -> None:
	assessment = assess_salary_text("Salario: $36.000.000 COP anual", 4_000_000)
	assert assessment.published is False
	assert assessment.blocked is False


def test_scoring_hard_ignores_job_below_salary_floor() -> None:
	profile = CandidateProfile(
		target_roles=("Python Developer",),
		skills=("Python", "AWS"),
		preferred_locations=("Colombia",),
	)
	preferences = SearchPreferences(min_score=60, prepare_application_score=85, min_monthly_salary_cop=4_000_000)
	job = JobPosting(
		title="Python Developer",
		company="Example SAS",
		location="Colombia",
		description="Python AWS. Salario: $3.900.000 COP mensual.",
		url="https://co.computrabajo.com/example",
	)

	result = score_job(job, profile, preferences)
	assert result.score == 0
	assert result.decision == "ignore"
	assert any("inferior al mínimo" in reason for reason in result.reasons)


def _job(external_id: str, description: str) -> JobRecord:
	return JobRecord(
		id=None,
		source="computrabajo",
		external_id=external_id,
		title="Python Developer",
		company="Example SAS",
		location="Colombia",
		url=f"https://co.computrabajo.com/{external_id}",
		score=95,
		band="prepare",
		status="discovered",
		description=description,
	)


def test_batch_eligibility_rechecks_salary_floor_before_application(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	ProfileStore(store.path).save(UserProfile(min_monthly_salary_cop=4_000_000))
	store.upsert_jobs([
		_job("low", "Salario: $3.500.000 COP mensual"),
		_job("ok", "Salario: $4.200.000 COP mensual"),
	])
	runner = BatchApplyRunner(store=store)

	eligible = runner._current_search_jobs(["low", "ok"], 85)
	assert [job["external_id"] for job in eligible] == ["ok"]
