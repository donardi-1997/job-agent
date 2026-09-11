from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from job_agent.storage import DEFAULT_DB_PATH


@dataclass(frozen=True)
class TelegramDelivery:
	configured: bool
	sent: bool
	duplicate: bool = False
	reason: str = ''


class TelegramApplicationNotifier:
	"""Send best-effort Telegram alerts for confirmed job applications.

	The bot token and chat ID are read from the environment only at send time and
	are never persisted. Delivery state is stored locally so retries do not create
	duplicate notifications for the same Computrabajo vacancy.
	"""

	def __init__(self, db_path: Path | str = DEFAULT_DB_PATH, *, timeout_seconds: float = 5.0) -> None:
		self.path = Path(db_path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.timeout_seconds = timeout_seconds
		with sqlite3.connect(self.path) as connection:
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS notification_deliveries (
					provider TEXT NOT NULL,
					event_key TEXT NOT NULL,
					sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
					PRIMARY KEY(provider, event_key)
				)
				'''
			)

	@staticmethod
	def _enabled() -> bool:
		return os.getenv('JOB_AGENT_TELEGRAM_NOTIFICATIONS', '1').strip().casefold() not in {
			'0',
			'false',
			'no',
			'off',
		}

	@staticmethod
	def _credentials() -> tuple[str, str] | None:
		token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
		chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()
		if not token or not chat_id:
			return None
		return token, chat_id

	@staticmethod
	def _event_key(job: dict[str, object]) -> str:
		external_id = str(job.get('external_id') or '').strip()
		if external_id:
			return f'computrabajo:{external_id}'
		return f"computrabajo:local:{int(job.get('id') or 0)}"

	def _already_delivered(self, event_key: str) -> bool:
		with sqlite3.connect(self.path) as connection:
			row = connection.execute(
				'SELECT 1 FROM notification_deliveries WHERE provider = ? AND event_key = ?',
				('telegram', event_key),
			).fetchone()
		return row is not None

	def _mark_delivered(self, event_key: str) -> None:
		with sqlite3.connect(self.path) as connection:
			connection.execute(
				'INSERT OR IGNORE INTO notification_deliveries(provider, event_key) VALUES(?, ?)',
				('telegram', event_key),
			)

	@staticmethod
	def _message(job: dict[str, object], confirmation_url: str = '') -> str:
		title = str(job.get('title') or 'Vacante sin título').strip()
		company = str(job.get('company') or 'Empresa no especificada').strip()
		location = str(job.get('location') or 'Ubicación no especificada').strip()
		job_url = str(job.get('url') or '').strip()
		score = job.get('score')
		lines = [
			'✅ Postulación enviada correctamente',
			'',
			f'Cargo: {title}',
			f'Empresa: {company}',
			f'Ubicación: {location}',
		]
		if isinstance(score, int):
			lines.append(f'Match: {score}/100')
		if job_url:
			lines.extend(['', f'Vacante: {job_url}'])
		if confirmation_url and confirmation_url != job_url:
			lines.append(f'Confirmación: {confirmation_url}')
		return '\n'.join(lines)

	def _send_message(self, token: str, chat_id: str, text: str) -> bool:
		payload = urlencode(
			{
				'chat_id': chat_id,
				'text': text,
				'disable_web_page_preview': 'true',
			}
		).encode('utf-8')
		request = Request(
			f'https://api.telegram.org/bot{token}/sendMessage',
			data=payload,
			headers={'Content-Type': 'application/x-www-form-urlencoded'},
			method='POST',
		)
		try:
			with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed Telegram API host
				body = response.read()
			decoded = json.loads(body.decode('utf-8'))
			return isinstance(decoded, dict) and decoded.get('ok') is True
		except Exception:
			# Notification transport must never change application outcome and must
			# never surface an exception containing the bot-token URL.
			return False

	def notify_application_success(
		self,
		job: dict[str, object],
		*,
		confirmation_url: str = '',
	) -> TelegramDelivery:
		if not self._enabled():
			return TelegramDelivery(configured=False, sent=False, reason='disabled')

		credentials = self._credentials()
		if credentials is None:
			return TelegramDelivery(configured=False, sent=False, reason='missing_credentials')

		event_key = self._event_key(job)
		if self._already_delivered(event_key):
			return TelegramDelivery(configured=True, sent=False, duplicate=True, reason='already_sent')

		token, chat_id = credentials
		if not self._send_message(token, chat_id, self._message(job, confirmation_url)):
			return TelegramDelivery(configured=True, sent=False, reason='delivery_failed')

		self._mark_delivered(event_key)
		return TelegramDelivery(configured=True, sent=True, reason='sent')
