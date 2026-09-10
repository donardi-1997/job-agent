(() => {
	const formatter = new Intl.NumberFormat('es-CO');

	function mount() {
		if (document.querySelector('#salaryPolicyPanel')) return;
		const profileForm = document.querySelector('#profileForm');
		const salaryExpectation = document.querySelector('#salaryInput')?.closest('label');
		if (!profileForm || !salaryExpectation) return;

		const panel = document.createElement('div');
		panel.id = 'salaryPolicyPanel';
		panel.className = 'wide salary-policy-panel';
		panel.innerHTML = `
			<div class="salary-policy-copy">
				<strong>Regla salarial dura</strong>
				<span>Si el salario máximo publicado queda por debajo de este valor, Job Agent NO se postula. Si la vacante no publica salario, no se descarta por este criterio.</span>
			</div>
			<div class="salary-policy-actions">
				<label>Salario mínimo mensual (COP)
					<input id="minSalaryPolicyInput" type="number" min="0" max="100000000" step="100000" value="4000000">
				</label>
				<button class="button secondary" id="saveSalaryPolicyButton" type="button">Guardar mínimo</button>
				<span id="salaryPolicyState">$4.000.000 COP</span>
			</div>`;
		profileForm.insertBefore(panel, salaryExpectation);

		const style = document.createElement('style');
		style.textContent = `
			.salary-policy-panel{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:end;padding:16px;border:1px solid rgba(245,166,35,.35);border-radius:14px;background:rgba(245,166,35,.06)}
			.salary-policy-copy{display:flex;flex-direction:column;gap:5px}.salary-policy-copy strong{font-size:13px}.salary-policy-copy span{font-size:11px;line-height:1.5;opacity:.78}
			.salary-policy-actions{display:flex;align-items:end;gap:10px;flex-wrap:wrap}.salary-policy-actions label{min-width:220px}.salary-policy-actions #salaryPolicyState{font-size:11px;opacity:.78;min-width:120px;padding-bottom:10px}
			@media(max-width:760px){.salary-policy-panel{grid-template-columns:1fr}.salary-policy-actions{align-items:stretch}.salary-policy-actions label,.salary-policy-actions button{width:100%}}
		`;
		document.head.appendChild(style);
		panel.querySelector('#saveSalaryPolicyButton').addEventListener('click', save);
	}

	function render(value, message = '') {
		const input = document.querySelector('#minSalaryPolicyInput');
		const state = document.querySelector('#salaryPolicyState');
		if (input) input.value = String(value ?? 4000000);
		if (state) state.textContent = message || `$${formatter.format(Number(value || 0))} COP`;
	}

	async function load() {
		mount();
		try {
			const response = await fetch('/api/profile/min-salary', { cache: 'no-store' });
			const payload = await response.json();
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			render(payload.min_monthly_salary_cop);
		} catch (error) {
			render(4000000, 'No se pudo cargar');
			console.error('Unable to load salary policy', error);
		}
	}

	async function save() {
		const input = document.querySelector('#minSalaryPolicyInput');
		const button = document.querySelector('#saveSalaryPolicyButton');
		const state = document.querySelector('#salaryPolicyState');
		const value = Number(input?.value || 0);
		if (!Number.isFinite(value) || value < 0) {
			if (state) state.textContent = 'Valor inválido';
			return;
		}
		if (button) button.disabled = true;
		if (state) state.textContent = 'Guardando…';
		try {
			const response = await fetch('/api/profile/min-salary', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ min_monthly_salary_cop: Math.trunc(value) }),
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			render(payload.min_monthly_salary_cop, `$${formatter.format(payload.min_monthly_salary_cop)} COP · regla activa`);
			if (typeof window.loadDashboard === 'function') void window.loadDashboard();
		} catch (error) {
			if (state) state.textContent = error.message;
		} finally {
			if (button) button.disabled = false;
		}
	}

	mount();
	load();
})();
