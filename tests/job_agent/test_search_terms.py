from job_agent.profile import UserProfile
from job_agent.search_terms import build_personal_search_terms, derive_skill_search_terms


def test_skill_search_terms_are_job_queries_not_literal_tools() -> None:
	profile = UserProfile(
		target_roles=[],
		skills=[
			"Python",
			"FastAPI",
			"AWS",
			"AWS Lambda",
			"API Gateway",
			"DynamoDB",
			"React",
			"Angular",
			"Node.js",
			".NET",
			"Jira",
			"Confluence",
		],
	)

	terms = derive_skill_search_terms(profile, limit=8)

	assert "Python Backend Developer" in terms
	assert "AWS Developer" in terms
	assert "Serverless Developer" in terms
	assert "Full Stack Developer" in terms
	assert "Jira" not in terms
	assert "Confluence" not in terms


def test_skill_search_plan_changes_when_profile_skills_change() -> None:
	python_profile = UserProfile(target_roles=[], skills=["Python", "FastAPI", "AWS"])
	frontend_profile = UserProfile(target_roles=[], skills=["React", "Angular", "JavaScript", "Frontend Development"])

	python_terms = build_personal_search_terms(python_profile, limit=5)
	frontend_terms = build_personal_search_terms(frontend_profile, limit=5)

	assert "Python Backend Developer" in python_terms
	assert "AWS Developer" in python_terms
	assert "Frontend Developer" in frontend_terms
	assert "Full Stack Developer" in frontend_terms
	assert python_terms != frontend_terms


def test_manual_search_term_is_preserved_when_auto_plan_is_full() -> None:
	profile = UserProfile(
		target_roles=["Software Engineer"],
		skills=["Python", "FastAPI", "AWS", "Lambda", "API Gateway", "DynamoDB", "React", "Angular", "Node.js", ".NET"],
	)

	terms = build_personal_search_terms(profile, custom_term="Shopify Developer", limit=4)

	assert len(terms) == 4
	assert terms[-1] == "Shopify Developer"
