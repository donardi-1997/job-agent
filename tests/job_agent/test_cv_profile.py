from pathlib import Path

import pytest

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

	with pytest.raises(ValueError, match='Formato no soportado'):
		service.import_bytes('cv.exe', b'not a cv')

	with pytest.raises(ValueError, match='suficiente texto'):
		service.import_bytes('cv.txt', b'too short')



def test_cv_variants_are_stored_and_selected_for_each_job(tmp_path: Path) -> None:
	db_path = tmp_path / 'job-agent.db'
	service = CVProfileService(db_path, tmp_path / 'cv')
	service.import_bytes(
		'backend.txt',
		(
			b'Backend Developer Python Developer FastAPI REST APIs PostgreSQL Docker. '
			b'Built backend services, integrations, authentication and SQL APIs with Python. '
		) * 3,
		variant_name='Backend / Python',
		activate=True,
	)
	service.import_bytes(
		'aws.txt',
		(
			b'AWS Developer Cloud Engineer Amazon Web Services Lambda API Gateway DynamoDB S3 '
			b'Cognito Bedrock RAG CI/CD GitHub Actions serverless cloud architecture. '
		) * 3,
		variant_name='AWS / Cloud',
		activate=False,
	)

	variants = service.list_variants()
	assert {item['label'] for item in variants} == {'Backend / Python', 'AWS / Cloud'}
	assert next(item for item in variants if item['is_default'])['label'] == 'Backend / Python'

	selected = service.select_for_job(
		{
			'title': 'AWS Cloud Engineer',
			'description': 'Serverless AWS role using Lambda, API Gateway, S3, DynamoDB and Bedrock.',
			'company': 'Example',
			'location': 'Colombia',
		}
	)
	assert selected is not None
	assert selected['label'] == 'AWS / Cloud'
	assert service.path_for_job({'title': 'AWS Developer', 'description': 'Lambda S3 API Gateway'}) is not None


def test_activate_variant_updates_default_profile_and_legacy_current_file(tmp_path: Path) -> None:
	db_path = tmp_path / 'job-agent.db'
	service = CVProfileService(db_path, tmp_path / 'cv')
	backend = service.import_bytes(
		'backend.txt',
		(b'Backend Developer Python FastAPI REST APIs PostgreSQL Docker cloud integration. ') * 4,
		variant_name='Backend / Python',
		activate=True,
	)
	ai = service.import_bytes(
		'ai.txt',
		(b'AI Engineer Python AWS Bedrock RAG LLM FastAPI React artificial intelligence applications. ') * 4,
		variant_name='Full Stack / AI',
		activate=False,
	)

	service.activate_variant(ai.variant_key)
	status = service.status()
	profile = ProfileStore(db_path).get()

	assert status['default_variant'] == ai.variant_key
	assert any(item['variant_key'] == backend.variant_key for item in status['variants'])
	assert 'AI Engineer' in profile.target_roles
	assert (tmp_path / 'cv' / 'current.txt').exists()
