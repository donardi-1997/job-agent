from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.profile import FrequentAnswer, ProfileStore, UserProfile


def test_profile_store_round_trip(tmp_path: Path) -> None:
	store = ProfileStore(tmp_path / "profile.db")
	profile = UserProfile(
		target_roles=[" Python Developer ", "Python Developer", "Backend Developer"],
		skills=["Python", "FastAPI"],
		preferred_locations=["Colombia", "Bogotá"],
		years_experience=2.5,
		remote_ok=True,
		min_score=65,
		prepare_application_score=88,
		professional_summary="Backend developer focused on Python and AWS.\n\nI build automation and AI/RAG projects.",
		city="Bogotá",
		english_level="B1",
		salary_expectation="4.000.000 COP",
		availability="15 días",
		preferred_work_modes=["Remoto", "Híbrido", "Remoto"],
		preferred_contract_types=["Indefinido"],
		frequent_answers=[FrequentAnswer(question="¿Disponibilidad?", answer="15 días")],
	)

	store.save(profile)
	loaded = store.get()

	assert loaded.target_roles == ["Python Developer", "Backend Developer"]
	assert loaded.skills == ["Python", "FastAPI"]
	assert loaded.years_experience == 2.5
	assert loaded.min_score == 65
	assert loaded.prepare_application_score == 88
	assert loaded.professional_summary == "Backend developer focused on Python and AWS.\n\nI build automation and AI/RAG projects."
	assert loaded.city == "Bogotá"
	assert loaded.english_level == "B1"
	assert loaded.salary_expectation == "4.000.000 COP"
	assert loaded.preferred_work_modes == ["Remoto", "Híbrido"]
	assert loaded.frequent_answers[0].answer == "15 días"


def test_profile_validates_numeric_ranges_and_thresholds() -> None:
	with pytest.raises(ValidationError):
		UserProfile(min_score=101)

	with pytest.raises(ValidationError):
		UserProfile(years_experience=-1)

	with pytest.raises(ValidationError):
		UserProfile(min_score=90, prepare_application_score=80)

	with pytest.raises(ValidationError):
		UserProfile(professional_summary="x" * 12001)


def test_frequent_answer_requires_question_and_answer() -> None:
	with pytest.raises(ValidationError):
		FrequentAnswer(question="", answer="algo")
