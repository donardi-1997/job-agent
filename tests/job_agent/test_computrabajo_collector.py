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


def test_search_ai_fallback_is_bounded_and_computrabajo_only(monkeypatch: pytest.MonkeyPatch) -> None:
	request = SearchRequest(keyword="Node.js Developer", location="Colombia", max_results=25)
	task = ComputrabajoCollector._build_task(request)

	assert "Use Computrabajo only" in task
	assert "Do not navigate to Google" in task
	monkeypatch.delenv("JOB_AGENT_SEARCH_AI_MAX_STEPS", raising=False)
	assert ComputrabajoCollector._search_ai_max_steps() == 20

	monkeypatch.setenv("JOB_AGENT_SEARCH_AI_MAX_STEPS", "12")
	assert ComputrabajoCollector._search_ai_max_steps() == 12

	monkeypatch.setenv("JOB_AGENT_SEARCH_AI_MAX_STEPS", "999")
	assert ComputrabajoCollector._search_ai_max_steps() == 40


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


def test_rescore_existing_jobs_uses_professional_summary_and_preserves_status(tmp_path: Path) -> None:
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
		url="https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-python-developer-en-bogota-dc-RESCORE1",
	)
	collector._persist([job])
	before = store.list_jobs()[0]
	store.update_status(int(before["id"]), "applied")

	current = collector.profile_store.get()
	collector.profile_store.save(
		current.model_copy(
			update={"professional_summary": "Java Angular frontend mobile Kotlin Android UI design"}
		)
	)
	assert collector.rescore_existing_jobs() == 1

	after = store.get_job(int(before["id"]))
	assert after is not None
	assert int(after["score"]) < int(before["score"])
	assert after["status"] == "applied"
	assert any("Professional context matches" in reason for reason in after["match_reasons"])


def test_task_is_read_only() -> None:
	task = ComputrabajoCollector._build_task(SearchRequest(keyword="AWS Developer", location="Colombia"))

	assert "Do not apply" in task
	assert "do not click any final application/submission button" in task
	assert "CAPTCHA" in task
