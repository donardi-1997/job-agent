(() => {
	function escapePlan(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function mount() {
		const panel = document.querySelector('#batch');
		if (!panel || document.querySelector('#automaticSearchPlan')) return;
		const note = panel.querySelector('.personal-note');
		const card = document.createElement('div');
		card.id = 'automaticSearchPlan';
		card.className = 'personal-note';
		card.innerHTML = `
			<strong>Búsquedas automáticas desde mis skills</strong>
			<span id="automaticSearchPlanStatus">Calculando plan local…</span>
			<div class="chip-list" id="automaticSearchPlanTerms"></div>
			<div id="searchEfficiency" style="margin-top:10px;font-size:12px;opacity:.82">Eficiencia de búsqueda: sin historial todavía.</div>`;
		if (note) note.insertAdjacentElement('afterend', card);
		else panel.prepend(card);
		refresh();
		window.setInterval(refresh, 5000);
	}

	async function refresh() {
		const status = document.querySelector('#automaticSearchPlanStatus');
		const terms = document.querySelector('#automaticSearchPlanTerms');
		const efficiency = document.querySelector('#searchEfficiency');
		if (!status || !terms) return;
		try {
			const [planResponse, efficiencyResponse] = await Promise.all([
				fetch('/api/search/plan', { cache: 'no-store' }),
				fetch('/api/search/efficiency', { cache: 'no-store' }),
			]);
			const payload = await planResponse.json().catch(() => ({}));
			if (!planResponse.ok) throw new Error(payload.error || `HTTP ${planResponse.status}`);
			status.textContent = `${payload.skills_count || 0} skills → ${payload.terms?.length || 0} consultas determinísticas. No usa IA para generar este plan.`;
			terms.innerHTML = payload.terms?.length
				? payload.terms.map((term) => `<span class="skill-chip">${escapePlan(term)}</span>`).join('')
				: '<span class="empty-chip">Agrega skills o cargos objetivo en Mi perfil.</span>';

			if (efficiency && efficiencyResponse.ok) {
				const stats = await efficiencyResponse.json();
				if (Number(stats.total || 0) > 0) {
					efficiency.innerHTML = `<strong>${Number(stats.deterministic_rate || 0).toFixed(1)}% sin IA</strong> · ${stats.deterministic || 0} búsquedas locales · ${stats.ai_fallback || 0} fallbacks · ${stats.jobs_found || 0} vacantes extraídas`;
				} else {
					efficiency.textContent = 'Eficiencia de búsqueda: sin historial todavía. La próxima búsqueda intentará primero el extractor local.';
				}
			}
		} catch (error) {
			status.textContent = `No se pudo construir el plan: ${error.message}`;
			terms.innerHTML = '';
		}
	}

	window.refreshAutomaticSearchPlan = refresh;
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
