(() => {
	function mount() {
		const panel = document.querySelector('#batch');
		if (!panel || document.querySelector('#applicationEfficiency')) return;
		const searchPlan = document.querySelector('#automaticSearchPlan');
		const card = document.createElement('div');
		card.id = 'applicationEfficiency';
		card.className = 'personal-note';
		card.innerHTML = `
			<strong>Postulaciones con aprendizaje local</strong>
			<span id="applicationEfficiencyStatus">Midiendo dependencia de IA…</span>
			<div class="batch-kpis">
				<span><strong id="applicationDeterministicRate">0%</strong> sin IA</span>
				<span><strong id="applicationDeterministicRuns">0</strong> locales</span>
				<span><strong id="applicationFallbackRuns">0</strong> fallback IA</span>
				<span><strong id="applicationProvenPatterns">0</strong> patrones confirmados</span>
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
			const response = await fetch('/api/application/efficiency', { cache: 'no-store' });
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			document.querySelector('#applicationDeterministicRate').textContent = `${Number(payload.deterministic_rate || 0).toFixed(1)}%`;
			document.querySelector('#applicationDeterministicRuns').textContent = payload.deterministic || 0;
			document.querySelector('#applicationFallbackRuns').textContent = payload.ai_fallback || 0;
			document.querySelector('#applicationProvenPatterns').textContent = payload.proven_patterns || 0;
			status.textContent = payload.total
				? `${payload.total} intentos medidos · ${payload.patterns || 0} patrones de formulario observados. La IA solo entra cuando el flujo local no puede resolver el caso con seguridad.`
				: 'Aún no hay postulaciones medidas. Cada intento enseñará respuestas y patrones al motor local.';
		} catch (error) {
			status.textContent = `No se pudo cargar la métrica: ${error.message}`;
		}
	}

	window.refreshApplicationEfficiency = refresh;
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
