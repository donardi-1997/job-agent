from job_agent.config import CandidateProfile, SearchPreferences
from job_agent.scoring import JobPosting, score_job


def test_relevant_job_is_prepared() -> None:
	profile = CandidateProfile(
		target_roles=("python developer", "backend developer"),
		skills=("python", "fastapi", "aws"),
		preferred_locations=("Colombia",),
	)
	job = JobPosting(
		title="Python Developer",
		company="Example",
		location="Bogotá, Colombia",
		description="Backend role using Python, FastAPI and AWS.",
		url="https://example.test/job/1",
	)

	result = score_job(job, profile, SearchPreferences())

	assert result.score >= 85
	assert result.decision == "prepare"


def test_excluded_c1_requirement_is_ignored() -> None:
	profile = CandidateProfile(target_roles=("backend developer",), skills=("python",))
	job = JobPosting(
		title="Backend Developer",
		company="Example",
		location="Colombia",
		description="Python backend developer. English C1 is mandatory.",
		url="https://example.test/job/2",
	)

	result = score_job(job, profile, SearchPreferences())

	assert result.score == 0
	assert result.decision == "ignore"
