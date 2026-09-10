from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.profile import ProfileStore, UserProfile


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
	)

	store.save(profile)
	loaded = store.get()

	assert loaded.target_roles == ["Python Developer", "Backend Developer"]
	assert loaded.skills == ["Python", "FastAPI"]
	assert loaded.years_experience == 2.5
	assert loaded.min_score == 65
	assert loaded.prepare_application_score == 88


def test_profile_validates_numeric_ranges() -> None:
	with pytest.raises(ValidationError):
		UserProfile(min_score=101)

	with pytest.raises(ValidationError):
		UserProfile(years_experience=-1)
