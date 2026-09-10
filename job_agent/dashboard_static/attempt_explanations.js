(() => {
	const state = { jobId: null, attempts: [], timer: null, loading: false };

	function esc(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function ensureStyles() {
		if (document.querySelector('#attemptExplanationStyles')) return;
		const style = document.createElement('style');
		style.id = 'attemptExplanationStyles';
		style.textContent = `
			.qa-attempt-result{margin:0 0 9px;padding:10px 11px;border-radius:9px;border:1px solid rgba(139,165,255,.10);background:rgba(139,165,255,.035)}
			.qa-attempt-result strong{display:block;margin-bottom:4px;color:#bfc9dc;font-size:9px;letter-spacing:.04em;text-transform:uppercase}
			.qa-attempt-result p{margin:0;color:#8290a9;font-size:10px;line-height:1.5}.qa-attempt-result p+p{margin-top:4px}
			.qa-attempt-result.success{border-color:rgba(104,211,145,.14);background:rgba(104,211,145,.035)}
			.qa-attempt-result.warning{border-color:rgba(240,201,110,.14);background:rgba(240,201,110,.035)}
		`;
		document.head.appendChild(style);
	}

	function explain(attempt) {
		const payload = attempt?.payload || {};
		const questions = Array.isArray(payload.questions) ? payload.questions : [];
		const status = String(payload.submission_status || attempt?.submission_status || '');
		const confirmation = String(payload.confirmation_text || attempt?.confirmation_text || '').trim();
		const blocked = String(payload.blocked_reason || '').trim();
		const summary = String(payload.summary || '').trim();

		if (status === 'already_applied') {
			return {
				kind: 'success',
				title: 'Resultado del intento',
				message: confirmation || 'Computrabajo indicó que esta vacante ya tenía una postulación.',
				empty: 'No se abrió un formulario de preguntas en este intento porque la vacante ya figuraba como postulada.',
			};
		}
		if (blocked) {
			return {
				kind: 'warning',
				title: 'El flujo se detuvo antes de completar la postulación',
				message: blocked,
				empty: 'No se registraron preguntas porque el flujo se detuvo antes de llegar o completar el formulario.',
			};
		}
		if (attempt?.submitted || status === 'submitted') {
			return {
				kind: 'success',
				title: 'Postulación confirmada',
				message: confirmation || summary || 'Computrabajo confirmó la postulación.',
				empty: 'La postulación se confirmó sin preguntas adicionales registradas en este intento.',
			};
		}
		if (status === 'test_ready') {
			return {
				kind: 'success',
				title: 'Formulario listo en TEST',
				message: summary || 'El formulario quedó listo para enviar, pero TEST bloqueó el envío final.',
				empty: 'No se detectaron preguntas adicionales en este formulario.',
			};
		}
		if (status === 'test_incomplete') {
			return {
				kind: 'warning',
				title: 'Prueba incompleta',
				message: summary || 'El formulario no pudo completarse de forma determinística.',
				empty: 'El intento terminó antes de registrar preguntas reutilizables.',
			};
		}
		return {
			kind: summary ? 'warning' : '',
			title: 'Resultado del intento',
			message: summary || 'El intento terminó sin una confirmación adicional.',
			empty: questions.length ? '' : 'Este intento no alcanzó a registrar preguntas del formulario.',
		};
	}

	function enhanceCards() {
		const cards = Array.from(document.querySelectorAll('#qaAttempts .qa-attempt'));
		if (!cards.length || !state.attempts.length) return;
		cards.forEach((card, index) => {
			if (card.dataset.explainedAttempt === '1') return;
			const attempt = state.attempts[index];
			if (!attempt) return;
			const info = explain(attempt);
			const payload = attempt.payload || {};
			const questions = Array.isArray(payload.questions) ? payload.questions : [];
			if (info.message) {
				const box = document.createElement('div');
				box.className = `qa-attempt-result ${info.kind || ''}`.trim();
				box.innerHTML = `<strong>${esc(info.title)}</strong><p>${esc(info.message)}</p>`;
				const list = card.querySelector('.qa-question-list');
				if (list) card.insertBefore(box, list);
				else card.appendChild(box);
			}
			if (!questions.length && info.empty) {
				const empty = card.querySelector('.qa-empty');
				if (empty) empty.textContent = info.empty;
			}
			card.dataset.explainedAttempt = '1';
		});
	}

	async function load(jobId = state.jobId) {
		if (!jobId || state.loading) return;
		state.loading = true;
		try {
			const response = await fetch(`/api/jobs/${jobId}/attempts`, { cache: 'no-store' });
			if (!response.ok) return;
			const data = await response.json();
			state.attempts = Array.isArray(data) ? data : [];
			setTimeout(enhanceCards, 40);
		} finally {
			state.loading = false;
		}
	}

	function track(jobId) {
		if (!Number.isFinite(jobId) || jobId <= 0) return;
		state.jobId = jobId;
		setTimeout(() => load(jobId), 120);
	}

	function mount() {
		ensureStyles();
		document.addEventListener('click', (event) => {
			const target = event.target?.closest?.('[data-review-job]');
			if (target) track(Number(target.dataset.reviewJob));
		}, true);

		const history = document.querySelector('#qaAttempts');
		if (history) {
			new MutationObserver(() => {
				clearTimeout(state.timer);
				state.timer = setTimeout(() => {
					if (state.jobId) load(state.jobId);
				}, 120);
			}).observe(history, { childList: true, subtree: true });
		}
	}

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
