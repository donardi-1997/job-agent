from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.computrabajo.collector import ComputrabajoCollector, ExtractedJob, SearchRequest
from job_agent.profile import UserProfile
from job_agent.storage import JobStore


def test_search_request_normalizes_text_and_limits_results() -> None:
	request = SearchRequest(keyword="  Python   Developer ", location="  Bogotá   D.C. ", max_results=20)

	assert request.keyword == "Python Developer"
	assert request.location == "Bogotá D.C."
	assert request.max_results == 20

	with pytest.raises(ValidationError):
		SearchRequest(keyword="x", location="Colombia", max_results=20)

	with pytest.raises(ValidationError):
		SearchRequest(keyword="Python", location="Colombia", max_results=51)


def test_persist_deduplicates_jobs_and_uses_local_profile(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	collector = ComputrabajoCollector(store=store, profile_dir=tmp_path / "browser-profile")
	collector.profile_store.save(
		UserProfile(
			target_roles=["Python Developer"],
			skills=["Python", "FastAPI", "AWS"],
			preferred_locations=["Colombia"],
		)
	)
	job = ExtractedJob(
		title="Python Developer",
		company="Example SAS",
		location="Bogotá, Colombia",
		description="Backend role using Python, FastAPI and AWS.",
		url="https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-developer-en-bogota-dc-ABC123",
	)

	assert collector._persist([job]) == 1
	assert collector._persist([job]) == 1

	jobs = store.list_jobs()
	assert len(jobs) == 1
	assert jobs[0]["source"] == "computrabajo"
	assert jobs[0]["title"] == "Python Developer"
	assert jobs[0]["score"] >= 85
	assert jobs[0]["band"] == "prepare"


def test_task_is_read_only() -> None:
	task = ComputrabajoCollector._build_task(SearchRequest(keyword="AWS Developer", location="Colombia"))

	assert "Do not apply" in task
	assert "do not click any final application/submission button" in task
	assert "CAPTCHA" in task
