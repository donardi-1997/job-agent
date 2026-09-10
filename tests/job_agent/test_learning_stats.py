from job_agent.answer_memory import AnswerMemory
from job_agent.storage import JobRecord, JobStore


def test_learning_stats_measure_answer_coverage(tmp_path):
	db_path = tmp_path / "job-agent.db"
	store = JobStore(db_path)
	store.upsert_jobs([
		JobRecord(
			id=None,
			source="computrabajo",
			external_id="learning-one",
			title="Backend Developer",
			company="Example SAS",
			location="Colombia",
			url="https://co.computrabajo.com/learning-one",
			score=90,
			band="prepare",
			status="applied",
		)
	])
	job_id = int(store.list_jobs()[0]["id"])
	store.save_application_attempt(
		job_id,
		{
			"submitted": True,
			"submission_status": "submitted",
			"questions": [
				{"question": "¿Cuál es tu ciudad de residencia?", "suggested_answer": "Bogotá"},
				{"question": "¿Puedes viajar?", "suggested_answer": "Sí"},
			],
		},
	)
	memory = AnswerMemory(db_path)
	memory.remember("¿Cuál es tu ciudad de residencia?", "Bogotá", confidence=100)

	stats = memory.stats()

	assert stats["encountered_questions"] == 2
	assert stats["learned_questions"] == 1
	assert stats["answer_coverage_pct"] == 50.0
	assert stats["submitted_applications"] == 1
