import pytest

from job_agent.followup import ContactTracker, ContactUpdate
from job_agent.storage import JobRecord, JobStore


def _job(store: JobStore, external_id: str, *, status: str = "applied") -> int:
	store.upsert_jobs(
		[
			JobRecord(
				id=None,
				source="computrabajo",
				external_id=external_id,
				title="Backend Developer",
				company="Example",
				location="Colombia",
				url=f"https://co.computrabajo.com/{external_id}",
				score=90,
				band="prepare",
				status=status,
			)
		]
	)
	with store.connect() as connection:
		row = connection.execute(
			"SELECT id FROM jobs WHERE source = ? AND external_id = ?",
			("computrabajo", external_id),
		).fetchone()
	assert row is not None
	return int(row["id"])


def test_contact_followup_is_persisted_for_applied_job(tmp_path):
	store = JobStore(tmp_path / "job-agent.db")
	job_id = _job(store, "one")
	tracker = ContactTracker(store.path)

	saved = tracker.save(
		job_id,
		ContactUpdate(
			status="contacted",
			channel="WhatsApp",
			contacted_at="2026-09-10",
			note="Entrevista inicial",
		),
	)

	assert saved["status"] == "contacted"
	assert saved["channel"] == "WhatsApp"
	assert saved["contacted_at"] == "2026-09-10"
	assert tracker.get(job_id)["note"] == "Entrevista inicial"


def test_contact_followup_rejects_non_applied_job(tmp_path):
	store = JobStore(tmp_path / "job-agent.db")
	job_id = _job(store, "two", status="saved")
	tracker = ContactTracker(store.path)

	with pytest.raises(ValueError, match="postulada"):
		tracker.save(job_id, ContactUpdate(status="contacted"))


def test_contact_rate_uses_only_resolved_followups(tmp_path):
	store = JobStore(tmp_path / "job-agent.db")
	first = _job(store, "first")
	second = _job(store, "second")
	_job(store, "third")
	tracker = ContactTracker(store.path)
	tracker.save(first, ContactUpdate(status="contacted", channel="Email"))
	tracker.save(second, ContactUpdate(status="no_contact"))
	# The third application remains pending and must not dilute the resolved-outcome rate.

	stats = tracker.stats()

	assert stats["applied"] == 3
	assert stats["contacted"] == 1
	assert stats["no_contact"] == 1
	assert stats["pending"] == 1
	assert stats["contact_rate_pct"] == 50.0
