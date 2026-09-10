from pathlib import Path

import pytest

from job_agent.storage import JobRecord, JobStore


def _seed_job(store: JobStore, external_id: str = "job-1") -> int:
	store.upsert_jobs([
		JobRecord(id=None, source="computrabajo", external_id=external_id, title="Python Developer", company="Example SAS", location="Bogotá", url=f"https://co.computrabajo.com/{external_id}", score=90, band="prepare", description="Python FastAPI AWS role", match_reasons=("Target role matches: 1", "Skill matches: 3/4"), matched_skills=("Python", "FastAPI", "AWS"), missing_skills=("Docker",))
	])
	return int(store.list_jobs()[0]["id"])


def test_job_detail_metadata_and_status_are_persisted(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	job_id = _seed_job(store)
	detail = store.get_job(job_id)
	assert detail is not None
	assert detail["description"] == "Python FastAPI AWS role"
	assert detail["matched_skills"] == ["Python", "FastAPI", "AWS"]
	assert detail["missing_skills"] == ["Docker"]
	updated = store.update_status(job_id, "saved")
	assert updated is not None
	assert updated["status"] == "saved"


def test_upsert_does_not_overwrite_user_review_status(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	job_id = _seed_job(store, "same-job")
	store.update_status(job_id, "ignored")
	store.upsert_jobs([JobRecord(id=None, source="computrabajo", external_id="same-job", title="Backend Developer", company="Example", location="Colombia", url="https://co.computrabajo.com/same-job", score=80, band="recommend")])
	assert store.get_job(job_id)["status"] == "ignored"


def test_application_draft_is_persisted_and_updated(tmp_path: Path) -> None:
	path = tmp_path / "jobs.db"
	store = JobStore(path)
	job_id = _seed_job(store)
	first = {"questions": [{"question": "¿Cuántos años de experiencia tienes?", "suggested_answer": "2", "confidence": 90}], "summary": "Draft one"}
	store.save_application_draft(job_id, first)
	reopened = JobStore(path)
	draft = reopened.get_application_draft(job_id)
	assert draft is not None
	assert draft["summary"] == "Draft one"
	assert draft["questions"][0]["suggested_answer"] == "2"
	reopened.save_application_draft(job_id, {"questions": [], "summary": "Draft two"})
	updated = reopened.get_application_draft(job_id)
	assert updated is not None
	assert updated["summary"] == "Draft two"
	assert updated["job_id"] == job_id


def test_application_attempt_saves_answers_and_confirmation(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	job_id = _seed_job(store)
	payload = {
		"questions": [
			{"question": "¿Disponibilidad?", "suggested_answer": "Inmediata", "confidence": 100, "requires_user_input": False}
		],
		"mode": "real",
		"test_mode": False,
		"submitted": True,
		"submission_status": "submitted",
		"confirmation_text": "Postulación enviada",
		"confirmation_url": "https://co.computrabajo.com/confirmacion",
	}
	attempt_id = store.save_application_attempt(job_id, payload)
	attempts = store.list_application_attempts(job_id)
	assert attempt_id > 0
	assert len(attempts) == 1
	assert attempts[0]["submitted"] is True
	assert attempts[0]["confirmation_text"] == "Postulación enviada"
	assert attempts[0]["payload"]["questions"][0]["suggested_answer"] == "Inmediata"
	assert store.get_job(job_id)["status"] == "applied"


def test_real_submission_status_promotes_saved_job_even_if_boolean_was_false(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	job_id = _seed_job(store, "real-evidence")
	store.update_status(job_id, "saved")

	store.save_application_attempt(job_id, {
		"mode": "real",
		"test_mode": False,
		"submitted": False,
		"submission_status": "submitted",
		"confirmation_text": "Postulación enviada correctamente",
	})

	assert store.get_job(job_id)["status"] == "applied"
	attempt = store.list_application_attempts(job_id)[0]
	assert attempt["submitted"] is True


def test_test_attempt_never_promotes_job_to_applied(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	job_id = _seed_job(store, "test-safety")
	store.update_status(job_id, "saved")

	store.save_application_attempt(job_id, {
		"mode": "test",
		"test_mode": True,
		"submitted": False,
		"submission_status": "test_ready",
		"confirmation_text": "",
	})

	assert store.get_job(job_id)["status"] == "saved"


def test_applied_status_cannot_be_downgraded_to_saved(tmp_path: Path) -> None:
	store = JobStore(tmp_path / "jobs.db")
	job_id = _seed_job(store, "terminal-applied")
	store.update_status(job_id, "applied")

	with pytest.raises(ValueError, match="postulación confirmada"):
		store.update_status(job_id, "saved")

	assert store.get_job(job_id)["status"] == "applied"


def test_reopen_reconciles_existing_real_submission_evidence(tmp_path: Path) -> None:
	path = tmp_path / "jobs.db"
	store = JobStore(path)
	job_id = _seed_job(store, "reconcile-existing")
	store.update_status(job_id, "saved")

	# Simulate an older persisted attempt created before the applied-state invariant.
	with store.connect() as connection:
		connection.execute(
			"""
			INSERT INTO application_attempts(job_id, payload, submitted, submission_status, confirmation_text, confirmation_url)
			VALUES (?, ?, 0, 'submitted', 'Postulación enviada', '')
			""",
			(job_id, '{"mode":"real","test_mode":false,"submitted":false,"submission_status":"submitted","confirmation_text":"Postulación enviada"}'),
		)

	assert store.get_job(job_id)["status"] == "saved"
	reopened = JobStore(path)
	assert reopened.get_job(job_id)["status"] == "applied"
