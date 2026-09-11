from pathlib import Path

import pytest

from job_agent.computrabajo.application import ApplicationDraftOutput
from job_agent.computrabajo.notifying_application import NotifyingApplicationPreparer
from job_agent.telegram_notifications import TelegramApplicationNotifier


def _job() -> dict[str, object]:
	return {
		'id': 41,
		'source': 'computrabajo',
		'external_id': 'telegram-test-job',
		'title': 'Backend Developer',
		'company': 'Example SAS',
		'location': 'Bogotá',
		'url': 'https://co.computrabajo.com/ofertas-de-trabajo/test',
		'score': 92,
	}


def test_notifier_is_inert_without_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
	monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
	monkeypatch.setenv('JOB_AGENT_TELEGRAM_NOTIFICATIONS', '1')
	notifier = TelegramApplicationNotifier(tmp_path / 'jobs.db')

	delivery = notifier.notify_application_success(_job())

	assert delivery.configured is False
	assert delivery.sent is False
	assert delivery.reason == 'missing_credentials'


def test_notifier_sends_once_and_deduplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
	monkeypatch.setenv('TELEGRAM_CHAT_ID', '123456')
	monkeypatch.setenv('JOB_AGENT_TELEGRAM_NOTIFICATIONS', '1')
	notifier = TelegramApplicationNotifier(tmp_path / 'jobs.db')
	sent: list[tuple[str, str, str]] = []

	def fake_send(token: str, chat_id: str, text: str) -> bool:
		sent.append((token, chat_id, text))
		return True

	monkeypatch.setattr(notifier, '_send_message', fake_send)

	first = notifier.notify_application_success(_job())
	second = notifier.notify_application_success(_job())

	assert first.sent is True
	assert second.sent is False
	assert second.duplicate is True
	assert len(sent) == 1
	assert sent[0][0] == 'test-token'
	assert sent[0][1] == '123456'
	assert 'Backend Developer' in sent[0][2]
	assert 'Example SAS' in sent[0][2]
	assert '92/100' in sent[0][2]


def test_failed_delivery_is_not_marked_as_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
	monkeypatch.setenv('TELEGRAM_CHAT_ID', '123456')
	notifier = TelegramApplicationNotifier(tmp_path / 'jobs.db')
	attempts = 0

	def fake_send(_token: str, _chat_id: str, _text: str) -> bool:
		nonlocal attempts
		attempts += 1
		return False

	monkeypatch.setattr(notifier, '_send_message', fake_send)

	first = notifier.notify_application_success(_job())
	second = notifier.notify_application_success(_job())

	assert first.reason == 'delivery_failed'
	assert second.reason == 'delivery_failed'
	assert attempts == 2


def test_only_confirmed_real_new_submission_triggers_notification() -> None:
	success = ApplicationDraftOutput(
		submitted=True,
		submission_status='submitted',
		mode='real',
		test_mode=False,
	)
	already_applied = success.model_copy(update={'submission_status': 'already_applied'})
	test_mode = success.model_copy(update={'mode': 'test', 'test_mode': True, 'submission_status': 'test_ready'})
	failed = success.model_copy(update={'submitted': False, 'submission_status': 'not_submitted'})

	assert NotifyingApplicationPreparer._should_notify(success) is True
	assert NotifyingApplicationPreparer._should_notify(already_applied) is False
	assert NotifyingApplicationPreparer._should_notify(test_mode) is False
	assert NotifyingApplicationPreparer._should_notify(failed) is False
