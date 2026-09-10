from job_agent.computrabajo.application import AssistedApplicationPreparer


def test_application_task_is_draft_only_and_does_not_invent_personal_data() -> None:
	job = {
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

	task = AssistedApplicationPreparer._build_task(job, profile)

	assert "PREPARE a draft" in task
	assert "Do not submit anything" in task
	assert "Do not invent missing facts" in task or "do not invent" in task.casefold()
	assert "Never submit" in task
	assert "CAPTCHA/2FA" in task


def test_application_task_contains_only_supplied_profile_facts() -> None:
	job = {"url": "https://co.computrabajo.com/job-2", "title": "Backend Developer"}
	profile = {"skills": ["Python", "AWS"], "years_experience": 3}

	task = AssistedApplicationPreparer._build_task(job, profile)

	assert "Python" in task
	assert "AWS" in task
	assert "3" in task
	assert "salary" not in task.casefold()
