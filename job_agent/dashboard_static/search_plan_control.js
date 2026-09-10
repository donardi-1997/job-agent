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
			<div class="chip-list" id="automaticSearchPlanTerms"></div>`;
		if (note) note.insertAdjacentElement('afterend', card);
		else panel.prepend(card);
		refresh();
		window.setInterval(refresh, 5000);
	}

	async function refresh() {
		const status = document.querySelector('#automaticSearchPlanStatus');
		const terms = document.querySelector('#automaticSearchPlanTerms');
		if (!status || !terms) return;
		try {
			const response = await fetch('/api/search/plan', { cache: 'no-store' });
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			status.textContent = `${payload.skills_count || 0} skills → ${payload.terms?.length || 0} consultas determinísticas. No usa IA para generar este plan.`;
			terms.innerHTML = payload.terms?.length
				? payload.terms.map((term) => `<span class="skill-chip">${escapePlan(term)}</span>`).join('')
				: '<span class="empty-chip">Agrega skills o cargos objetivo en Mi perfil.</span>';
		} catch (error) {
			status.textContent = `No se pudo construir el plan: ${error.message}`;
			terms.innerHTML = '';
		}
	}

	window.refreshAutomaticSearchPlan = refresh;
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
