from job_agent.computrabajo.application import AssistedApplicationPreparer


def test_application_task_submits_without_inventing_personal_data() -> None:
	job = {
		"id": 1,
		"url": "https://co.computrabajo.com/job-1",
		"title": "Python Developer",
		"company": "Example SAS",
		"location": "Bogotá",
		"description": "Python backend role",
	}
	profile = {
		"target_roles": ["Python Developer"],
		"skills": ["Python", "FastAPI"],
		"years_experience": 2,
		"preferred_locations": ["Colombia"],
	}
	saved_draft = {"questions": [{"question": "Disponibilidad", "suggested_answer": "Inmediata"}]}

	task = AssistedApplicationPreparer._build_task(job, profile, saved_draft)

	assert "COMPLETE AND SUBMIT" in task
	assert "click the final application/submit/confirm action" in task
	assert "Never invent facts" in task
	assert "Never bypass CAPTCHA" in task
	assert "Inmediata" in task


def test_application_task_contains_only_supplied_profile_facts_and_saved_answers() -> None:
	job = {"id": 2, "url": "https://co.computrabajo.com/job-2", "title": "Backend Developer"}
	profile = {"skills": ["Python", "AWS"], "years_experience": 3}

	task = AssistedApplicationPreparer._build_task(job, profile, {})

	assert "Python" in task
	assert "AWS" in task
	assert "3" in task
	assert "Avoid duplicate submission" in task


def test_application_task_uses_only_secret_placeholders_for_saved_credentials() -> None:
	job = {"id": 3, "url": "https://co.computrabajo.com/job-3", "title": "Backend Developer"}

	task = AssistedApplicationPreparer._build_task(job, {}, {}, credentials_available=True)

	assert "<secret>computrabajo_user</secret>" in task
	assert "<secret>computrabajo_password</secret>" in task
	assert "Never output their values" in task
