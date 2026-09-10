(() => {
	let nativeFetch = null;

	function mountBudgetControls() {
		const form = document.querySelector('#batchForm');
		const submit = document.querySelector('#batchButton');
		if (!form || !submit || document.querySelector('#batchAiCallsInput')) return;

		const calls = document.createElement('label');
		calls.innerHTML = 'Máx. llamadas IA <span>Por lote</span><input id="batchAiCallsInput" type="number" min="0" max="100" value="10">';
		const cost = document.createElement('label');
		cost.innerHTML = 'Máx. gasto IA USD <span>Estimado</span><input id="batchAiCostInput" type="number" min="0" max="10" step="0.01" value="0.10">';
		form.insertBefore(calls, submit);
		form.insertBefore(cost, submit);

		// app.js builds the batch payload. Intercept only this one local POST so the
		// budget controls can be added without duplicating the batch submission logic.
		if (!nativeFetch) {
			nativeFetch = window.fetch.bind(window);
			window.fetch = (input, init) => {
				const url = typeof input === 'string' ? input : (input?.url || '');
				if (url === '/api/batch' && String(init?.method || 'GET').toUpperCase() === 'POST' && typeof init?.body === 'string') {
					try {
						const payload = JSON.parse(init.body);
						payload.max_ai_calls = Number(document.querySelector('#batchAiCallsInput')?.value || 0);
						payload.max_ai_cost_usd = Number(document.querySelector('#batchAiCostInput')?.value || 0);
						return nativeFetch(input, { ...init, body: JSON.stringify(payload) });
					} catch (_) {
						// Fall through to the original request if the local payload is malformed.
					}
				}
				return nativeFetch(input, init);
			};
		}
	}

	function mount() {
		const panel = document.querySelector('#batch');
		if (!panel || document.querySelector('#applicationEfficiency')) return;
		mountBudgetControls();
		const searchPlan = document.querySelector('#automaticSearchPlan');
		const card = document.createElement('div');
		card.id = 'applicationEfficiency';
		card.className = 'personal-note';
		card.innerHTML = `
			<strong>Ahorro de IA · deterministic first</strong>
			<span id="applicationEfficiencyStatus">Midiendo dependencia de IA…</span>
			<div class="batch-kpis">
				<span><strong id="applicationDeterministicRate">0%</strong> postulaciones sin IA</span>
				<span><strong id="applicationDeterministicRuns">0</strong> locales</span>
				<span><strong id="applicationFallbackRuns">0</strong> con IA</span>
				<span><strong id="applicationProvenPatterns">0</strong> campos aprendidos</span>
				<span><strong id="applicationProvenForms">0</strong> formularios confirmados</span>
				<span><strong id="batchAiBudgetLive">0/10</strong> IA lote</span>
			</div>`;
		if (searchPlan) searchPlan.insertAdjacentElement('afterend', card);
		else panel.prepend(card);
		refresh();
		window.setInterval(refresh, 5000);
	}

	async function refresh() {
		const status = document.querySelector('#applicationEfficiencyStatus');
		if (!status) return;
		try {
			const [response, batchResponse] = await Promise.all([
				fetch('/api/application/efficiency', { cache: 'no-store' }),
				fetch('/api/batch/status', { cache: 'no-store' }),
			]);
			const payload = await response.json().catch(() => ({}));
			const batch = await batchResponse.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			document.querySelector('#applicationDeterministicRate').textContent = `${Number(payload.deterministic_rate || 0).toFixed(1)}%`;
			document.querySelector('#applicationDeterministicRuns').textContent = payload.deterministic || 0;
			document.querySelector('#applicationFallbackRuns').textContent = payload.ai_fallback || 0;
			document.querySelector('#applicationProvenPatterns').textContent = payload.proven_patterns || 0;
			document.querySelector('#applicationProvenForms').textContent = payload.proven_forms || 0;
			const calls = Number(batch.ai_calls || 0);
			const maxCalls = Number(batch.ai_max_calls ?? document.querySelector('#batchAiCallsInput')?.value ?? 10);
			const cost = Number(batch.ai_cost_usd || 0);
			const maxCost = Number(batch.ai_max_cost_usd ?? document.querySelector('#batchAiCostInput')?.value ?? 0.10);
			document.querySelector('#batchAiBudgetLive').textContent = `${calls}/${maxCalls} · $${cost.toFixed(3)}/$${maxCost.toFixed(2)}`;
			status.textContent = payload.total
				? `${payload.total} intentos medidos · ${payload.forms || 0} formas de formulario observadas. Preguntas conocidas se resuelven localmente; preguntas nuevas usan una llamada compacta antes de considerar Browser Use completo. Búsqueda IA: desactivada por defecto.`
				: 'Aún no hay postulaciones medidas. Búsqueda IA desactivada por defecto; cada formulario exitoso alimentará la memoria local.';
		} catch (error) {
			status.textContent = `No se pudo cargar la métrica: ${error.message}`;
		}
	}

	window.refreshApplicationEfficiency = refresh;
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
