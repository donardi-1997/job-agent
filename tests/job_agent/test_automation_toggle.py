from pathlib import Path

from job_agent.profile import ProfileStore, UserProfile


def test_automation_enabled_defaults_to_true() -> None:
    profile = UserProfile()

    assert profile.automation_enabled is True
    assert profile.to_search_preferences().auto_submit is True


def test_profile_store_persists_automation_toggle(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "job-agent.db")
    profile = UserProfile(automation_enabled=False)

    store.save(profile)
    loaded = store.get()

    assert loaded.automation_enabled is False
    assert loaded.to_search_preferences().auto_submit is False
