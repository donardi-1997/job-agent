from pathlib import Path

from job_agent.cv_profile import CVProfileService
from job_agent.profile import ProfileStore


def test_cv_import_updates_search_profile_from_explicit_evidence(tmp_path: Path) -> None:
	db_path = tmp_path / 'job-agent.db'
	service = CVProfileService(db_path, tmp_path / 'cv')
	content = b"""
	Adrian Guerra
	Backend Developer / Python Developer
	Experience building REST APIs with Python, FastAPI, PostgreSQL and Docker.
	Cloud projects with AWS, Lambda, API Gateway, S3 and Amazon Bedrock.
	Worked with RAG and LLM applications. GitHub Actions CI/CD.
	"""

	result = service.import_bytes('cv.txt', content)
	profile = ProfileStore(db_path).get()

	assert result.text_chars >= 100
	assert 'Backend Developer' in result.detected_roles
	assert 'Python Developer' in result.detected_roles
	assert 'Python' in result.detected_skills
	assert 'FastAPI' in result.detected_skills
	assert 'AWS' in result.detected_skills
	assert 'Docker' in result.detected_skills
	assert profile.target_roles == list(result.detected_roles)
	assert profile.skills == list(result.detected_skills)
	assert (tmp_path / 'cv' / 'current.txt').exists()


def test_cv_import_preserves_application_specific_profile_facts(tmp_path: Path) -> None:
	db_path = tmp_path / 'job-agent.db'
	profile_store = ProfileStore(db_path)
	profile_store.save(
		profile_store.get().model_copy(
			update={'salary_expectation': '4.000.000 COP', 'availability': 'Inmediata', 'english_level': 'A2'}
		)
	)
	service = CVProfileService(db_path, tmp_path / 'cv')
	service.import_bytes(
		'cv.txt',
		b'Backend Developer with Python and FastAPI. AWS cloud projects, Docker, SQL and REST APIs. ' * 3,
	)
	profile = profile_store.get()

	assert profile.salary_expectation == '4.000.000 COP'
	assert profile.availability == 'Inmediata'
	assert profile.english_level == 'A2'


def test_cv_import_rejects_unsupported_and_too_short_files(tmp_path: Path) -> None:
	service = CVProfileService(tmp_path / 'job-agent.db', tmp_path / 'cv')

	try:
		service.import_bytes('cv.exe', b'not a cv')
		except ValueError as exc:
		assert 'Formato no soportado' in str(exc)
	else:
		raise AssertionError('Unsupported CV extension should fail')

	try:
		service.import_bytes('cv.txt', b'too short')
		except ValueError as exc:
		assert 'suficiente texto' in str(exc)
	else:
		raise AssertionError('Too-short CV should fail')
