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


def test_professional_summary_contributes_context_component_without_ai() -> None:
	base_profile = CandidateProfile(
		target_roles=("backend developer",),
		skills=("python", "fastapi", "aws"),
		preferred_locations=("Colombia",),
	)
	profile = CandidateProfile(
		target_roles=base_profile.target_roles,
		skills=base_profile.skills,
		preferred_locations=base_profile.preferred_locations,
		professional_summary=(
			"Backend especializado en Python FastAPI AWS Lambda API Gateway Bedrock RAG, "
			"automatización e integraciones API."
		),
	)
	job = JobPosting(
		title="Backend Developer",
		company="Example",
		location="Bogotá, Colombia",
		description="Python FastAPI backend on AWS using Lambda, API Gateway, Bedrock and RAG.",
		url="https://example.test/job/3",
	)

	base_result = score_job(job, base_profile, SearchPreferences())
	result = score_job(job, profile, SearchPreferences())

	assert result.score > base_result.score
	assert result.decision == "prepare"
	assert any("Contexto profesional" in reason for reason in result.reasons)


def test_professional_summary_distinguishes_contextually_unrelated_jobs() -> None:
	profile = CandidateProfile(
		target_roles=("software engineer",),
		skills=("python",),
		preferred_locations=("Colombia",),
		professional_summary="AWS Lambda FastAPI Python RAG Bedrock APIs backend cloud automation",
	)
	relevant = JobPosting(
		title="Software Engineer",
		company="Example",
		location="Colombia",
		description="Build Python FastAPI APIs on AWS Lambda and Bedrock for RAG automation.",
		url="https://example.test/job/relevant",
	)
	unrelated = JobPosting(
		title="Software Engineer",
		company="Example",
		location="Colombia",
		description="Maintain legacy desktop UI applications and manual reporting workflows.",
		url="https://example.test/job/unrelated",
	)

	relevant_result = score_job(relevant, profile, SearchPreferences())
	unrelated_result = score_job(unrelated, profile, SearchPreferences())

	assert relevant_result.score > unrelated_result.score



def test_scoring_v2_rewards_fresh_strategic_matches() -> None:
	profile = CandidateProfile(
		target_roles=("aws developer",),
		skills=("python", "aws", "lambda", "bedrock"),
		years_experience=5,
		preferred_locations=("Colombia",),
		professional_summary="AWS Certified Developer Associate. Python AWS Lambda Bedrock RAG serverless.",
	)
	fresh = JobPosting(
		title="AWS Developer",
		company="Example",
		location="Colombia",
		description="Python AWS Lambda Bedrock serverless. AWS certification preferred.",
		url="https://example.test/fresh",
	)
	stale = JobPosting(
		title=fresh.title,
		company=fresh.company,
		location=fresh.location,
		description=fresh.description,
		url="https://example.test/stale",
		first_seen_at="2020-01-01 00:00:00",
	)

	fresh_result = score_job(fresh, profile, SearchPreferences())
	stale_result = score_job(stale, profile, SearchPreferences())

	assert fresh_result.score > stale_result.score
	assert fresh_result.decision == "prepare"
	assert any("Cloud/certificaciones" in reason for reason in fresh_result.reasons)
	assert any("Recencia" in reason for reason in fresh_result.reasons)
