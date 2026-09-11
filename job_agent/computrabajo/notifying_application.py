from __future__ import annotations

from job_agent.async_runtime import run_async
from job_agent.computrabajo.application import ApplicationDraftOutput, PreparationStatus
from job_agent.computrabajo.cost_aware_application import CostAwareApplicationPreparer
from job_agent.telegram_notifications import TelegramApplicationNotifier


class NotifyingApplicationPreparer(CostAwareApplicationPreparer):
	"""Cost-aware Computrabajo preparer with best-effort success notifications."""

	def __init__(self, *args: object, **kwargs: object) -> None:
		super().__init__(*args, **kwargs)
		self.telegram_notifier = TelegramApplicationNotifier(self.store.path)

	@staticmethod
	def _should_notify(result: ApplicationDraftOutput) -> bool:
		return bool(
			result.submitted
			and result.submission_status == 'submitted'
			and result.mode == 'real'
			and not result.test_mode
		)

	def _worker(self, job_id: int) -> None:
		try:
			job = self.store.get_job(job_id)
			if not job:
				raise RuntimeError('Vacante no encontrada.')

			result = run_async(self._apply(job))
			payload = result.model_dump()
			self.store.save_application_draft(job_id, payload)
			self.store.save_application_attempt(job_id, payload)
			if result.submitted:
				self.store.update_status(job_id, 'applied')

			notification_warning = ''
			if self._should_notify(result):
				try:
					delivery = self.telegram_notifier.notify_application_success(
						job,
						confirmation_url=result.confirmation_url,
					)
					if delivery.configured and not delivery.sent and not delivery.duplicate:
						notification_warning = ' La postulación quedó guardada, pero Telegram no pudo notificar.'
				except Exception:
					# Defense in depth: notification failures must never turn a successful
					# application into an application error.
					notification_warning = ' La postulación quedó guardada, pero Telegram no pudo notificar.'

			message = (
				result.confirmation_text
				if result.submitted and result.confirmation_text
				else 'Postulación enviada correctamente.'
				if result.submitted
				else result.summary or result.blocked_reason or 'La postulación no pudo completarse.'
			)
			with self._lock:
				self._status = PreparationStatus(
					state='completed',
					job_id=job_id,
					questions=len(result.questions),
					submitted=result.submitted,
					mode=self._last_mode,
					fallback_reason=self._last_fallback_reason,
					message=f'{message}{notification_warning}',
				)
		except Exception as exc:
			with self._lock:
				self._status = PreparationStatus(
					state='error',
					job_id=job_id,
					mode=self._last_mode,
					fallback_reason=self._last_fallback_reason,
					message=str(exc),
				)
