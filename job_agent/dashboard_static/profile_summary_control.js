(() => {
	function escapeSummary(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function ensureStyles() {
		if (document.querySelector('#profileSummaryStyles')) return;
		const style = document.createElement('style');
		style.id = 'profileSummaryStyles';
		style.textContent = `
			.profile-summary-card{padding:18px;border:1px solid rgba(255,255,255,.075);border-radius:14px;background:rgba(5,10,22,.28)}
			.profile-summary-card textarea{width:100%;min-height:190px;resize:vertical;margin-top:12px;padding:13px 14px;border-radius:10px;line-height:1.55;font:inherit;box-sizing:border-box}
			.profile-summary-meta{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:9px;color:#74819a;font-size:10px}
			.profile-summary-actions{display:flex;justify-content:flex-end;align-items:center;gap:12px;margin-top:12px}
			.profile-summary-message{margin-right:auto;color:#8290aa;font-size:10px}
		`;
		document.head.appendChild(style);
	}

	async function loadSummary() {
		try {
			const response = await fetch('/api/profile', { cache: 'no-store' });
			if (!response.ok) return;
			const profile = await response.json();
			const textarea = document.querySelector('#professionalSummaryInput');
			if (textarea && document.activeElement !== textarea) {
				textarea.value = profile.professional_summary || '';
				updateCount();
			}
		} catch (error) {
			console.error('Unable to load professional summary', error);
		}
	}

	function updateCount() {
		const textarea = document.querySelector('#professionalSummaryInput');
		const counter = document.querySelector('#professionalSummaryCount');
		if (textarea && counter) counter.textContent = `${textarea.value.length.toLocaleString('es-CO')} / 12.000 caracteres`;
	}

	async function saveSummary() {
		const textarea = document.querySelector('#professionalSummaryInput');
		const button = document.querySelector('#professionalSummarySave');
		const message = document.querySelector('#professionalSummaryMessage');
		if (!textarea || !button || !message) return;
		button.disabled = true;
		message.textContent = 'Guardando…';
		try {
			const response = await fetch('/api/profile/summary', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ professional_summary: textarea.value }),
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			textarea.value = payload.professional_summary || '';
			updateCount();
			message.textContent = 'Descripción guardada localmente.';
		} catch (error) {
			message.textContent = `No se pudo guardar: ${error.message}`;
		} finally {
			button.disabled = false;
		}
	}

	function mount() {
		ensureStyles();
		const form = document.querySelector('#profileForm');
		if (!form || document.querySelector('#profileSummaryCard')) return;
		const card = document.createElement('section');
		card.id = 'profileSummaryCard';
		card.className = 'profile-summary-card wide';
		card.innerHTML = `
			<div class="section-heading">
				<div>
					<p class="eyebrow">CONTEXTO PROFESIONAL · ESCRITO POR MÍ</p>
					<h3>Descripción profesional / Contexto de mi CV</h3>
					<p>Complementa el archivo con tu enfoque profesional, proyectos relevantes y los roles que quieres priorizar. No convierte automáticamente afirmaciones en skills verificadas.</p>
				</div>
				<span class="safe-pill">LOCAL</span>
			</div>
			<textarea id="professionalSummaryInput" maxlength="12000" placeholder="Ej. Desarrollador enfocado en backend con Python y FastAPI, experiencia construyendo productos propios en AWS, automatizaciones, integraciones y soluciones de IA/RAG. Busco principalmente roles Backend, Python, AWS o AI Engineer..."></textarea>
			<div class="profile-summary-meta"><span>Se usa como contexto adicional en las postulaciones; el CV sigue siendo la evidencia técnica principal.</span><span id="professionalSummaryCount">0 / 12.000 caracteres</span></div>
			<div class="profile-summary-actions"><span id="professionalSummaryMessage" class="profile-summary-message">Todo permanece en tu perfil local.</span><button id="professionalSummarySave" class="button secondary" type="button">Guardar descripción</button></div>`;
		const cvCard = document.querySelector('#cvProfileCard');
		if (cvCard) cvCard.insertAdjacentElement('afterend', card);
		else form.insertBefore(card, form.firstElementChild);
		card.querySelector('#professionalSummaryInput').addEventListener('input', updateCount);
		card.querySelector('#professionalSummarySave').addEventListener('click', saveSummary);
		loadSummary();
	}

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
