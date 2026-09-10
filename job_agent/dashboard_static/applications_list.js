(() => {
	let syncPoll = null;

	function esc(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	async function requestJson(url, options = {}) {
		const response = await window.fetch(url, {
			cache: 'no-store',
			...options,
			headers: {
				'Cache-Control': 'no-cache',
				...(options.headers || {}),
			},
		});
		const payload = await response.json().catch(() => ({}));
		if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
		return payload;
	}

	function ensureStyles() {
		if (document.querySelector('#applicationsListStyles')) return;
		const style = document.createElement('style');
		style.id = 'applicationsListStyles';
		style.textContent = `
			.applications-list-panel{margin-top:18px}.applications-list-count{display:inline-flex;padding:6px 9px;border-radius:999px;background:rgba(104,211,145,.07);color:#8ddfab;font-size:10px;font-weight:800}.applications-list-empty{padding:34px 20px;text-align:center;color:#77849e;font-size:11px}.metric-card[data-open-applications]{cursor:pointer}.metric-card[data-open-applications]:hover{border-color:rgba(104,211,145,.25)}
			.applications-header-actions{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.applications-sync-button{white-space:nowrap}.applications-sync-status{padding:10px 14px;border-top:1px solid rgba(255,255,255,.055);color:#7f8da6;font-size:10px;line-height:1.5}.applications-sync-status[data-state="running"]{color:#9badff}.applications-sync-status[data-state="completed"]{color:#8ddfab}.applications-sync-status[data-state="error"]{color:#e3a2a2}
			.application-origin{display:inline-flex;padding:4px 7px;border-radius:7px;font-size:9px;font-weight:800;white-space:nowrap}.application-origin-local{color:#9badff;background:rgba(139,165,255,.08)}.application-origin-verified{color:#8ddfab;background:rgba(104,211,145,.08)}.application-origin-external{color:#f0c96e;background:rgba(240,201,110,.08)}.application-date{display:block;margin-top:5px;color:#66748e;font-size:9px}.application-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.application-external-link{font-size:10px;color:#9badff;text-decoration:none;font-weight:750}.application-external-link:hover{text-decoration:underline}
			@media(max-width:760px){.applications-header-actions{width:100%;justify-content:flex-start}.applications-list-panel .table-wrap{overflow-x:auto}.applications-list-panel table{min-width:880px}}
		`;
		document.head.appendChild(style);
	}

	function mount() {
		ensureStyles();
		if (document.querySelector('#applications')) return;
		const profile = document.querySelector('#profile');
		if (!profile) return;

		const jobsLink = document.querySelector('nav a[href="#jobs"]');
		if (jobsLink && !document.querySelector('nav a[href="#applications"]')) {
			const link = document.createElement('a');
			link.className = 'nav-item';
			link.href = '#applications';
			link.textContent = 'Mis postulaciones';
			jobsLink.insertAdjacentElement('afterend', link);
		}

		const panel = document.createElement('section');
		panel.id = 'applications';
		panel.className = 'panel applications-list-panel';
		panel.innerHTML = `
			<div class="panel-header">
				<div><h2>Mis postulaciones</h2><p>Postulaciones de Job Agent y procesos verificados directamente en tu cuenta de Computrabajo.</p></div>
				<div class="applications-header-actions">
					<span class="applications-list-count"><strong id="applicationsListCount">0</strong>&nbsp;postulaciones</span>
					<button class="button secondary applications-sync-button" id="syncComputrabajoApplications" type="button">Sincronizar Computrabajo</button>
				</div>
			</div>
			<div class="table-wrap">
				<table><thead><tr><th>Vacante</th><th>Ubicación</th><th>Score</th><th>Origen</th><th>Estado</th><th></th></tr></thead><tbody id="applicationsListBody"></tbody></table>
				<div class="applications-list-empty" id="applicationsListEmpty" hidden>Aún no hay postulaciones registradas.</div>
			</div>
			<div class="applications-sync-status" id="applicationsSyncStatus" data-state="idle">Sincroniza para contrastar Job Agent con candidato.co.computrabajo.com.</div>`;
		profile.insertAdjacentElement('beforebegin', panel);

		const syncButton = document.querySelector('#syncComputrabajoApplications');
		syncButton?.addEventListener('click', synchronize);

		const metric = document.querySelector('#appliedMetric')?.closest('.metric-card');
		if (metric) {
			metric.dataset.openApplications = '1';
			metric.title = 'Ver mis postulaciones';
			metric.addEventListener('click', () => panel.scrollIntoView({ behavior: 'smooth', block: 'start' }));
		}

		const appliedMetric = document.querySelector('#appliedMetric');
		if (appliedMetric) {
			let previous = appliedMetric.textContent;
			new MutationObserver(() => {
				if (appliedMetric.textContent !== previous) {
					previous = appliedMetric.textContent;
					load();
				}
			}).observe(appliedMetric, { childList: true, characterData: true, subtree: true });
		}

		load();
		document.querySelector('#refreshButton')?.addEventListener('click', load);
	}

	function originClass(item) {
		if (item.origin === 'Job Agent + Computrabajo') return 'application-origin-verified';
		if (item.origin === 'Computrabajo') return 'application-origin-external';
		return 'application-origin-local';
	}

	function render(payload) {
		const body = document.querySelector('#applicationsListBody');
		const empty = document.querySelector('#applicationsListEmpty');
		const count = document.querySelector('#applicationsListCount');
		if (!body || !empty || !count) return;
		const items = Array.isArray(payload?.items) ? payload.items : [];
		count.textContent = String(items.length);
		body.innerHTML = '';
		empty.hidden = items.length > 0;

		for (const item of items) {
			const row = document.createElement('tr');
			const score = item.score === null || item.score === undefined ? '—' : esc(item.score);
			const date = item.date_text ? `<span class="application-date">${esc(item.date_text)}</span>` : '';
			const review = item.job_id
				? `<button class="review-link" type="button" data-application-review="${Number(item.job_id)}">Revisar preguntas →</button>`
				: '';
			const external = item.candidate_url
				? `<a class="application-external-link" href="${esc(item.candidate_url)}" target="_blank" rel="noopener noreferrer">Abrir proceso ↗</a>`
				: '';
			row.innerHTML = `<td><span class="job-title">${esc(item.title)}</span><span class="job-company">${esc(item.company || 'Computrabajo')}</span>${date}</td><td>${esc(item.location || 'Sin especificar')}</td><td><span class="score ${item.score === null || item.score === undefined ? '' : 'score-high'}">${score}</span></td><td><span class="application-origin ${originClass(item)}">${esc(item.origin)}</span></td><td><span class="decision decision-prepare">${esc(item.status || 'Postulada')}</span></td><td><div class="application-actions">${review}${external}</div></td>`;
			body.appendChild(row);
		}
		body.querySelectorAll('[data-application-review]').forEach((button) => {
			button.addEventListener('click', () => {
				const id = Number(button.dataset.applicationReview);
				if (typeof window.openJob === 'function') window.openJob(id);
			});
		});
	}

	function renderSyncStatus(status) {
		const box = document.querySelector('#applicationsSyncStatus');
		const button = document.querySelector('#syncComputrabajoApplications');
		if (!box || !button) return;
		const state = status?.state || 'idle';
		box.dataset.state = state;
		box.textContent = status?.message || 'Sincronización lista.';
		button.disabled = state === 'running';
		button.textContent = state === 'running' ? 'Sincronizando…' : 'Sincronizar Computrabajo';
	}

	async function load() {
		const body = document.querySelector('#applicationsListBody');
		const empty = document.querySelector('#applicationsListEmpty');
		if (!body || !empty) return;
		try {
			const payload = await requestJson('/api/computrabajo/applications');
			render(payload);
			if (payload.sync) renderSyncStatus(payload.sync);
		} catch (error) {
			body.innerHTML = '';
			empty.hidden = false;
			empty.textContent = error.message;
		}
	}

	async function synchronize() {
		if (syncPoll) clearInterval(syncPoll);
		try {
			const status = await requestJson('/api/computrabajo/applications/sync', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: '{}',
			});
			renderSyncStatus(status);
			syncPoll = setInterval(async () => {
				try {
					const current = await requestJson('/api/computrabajo/applications/sync/status');
					renderSyncStatus(current);
					if (current.state !== 'running') {
						clearInterval(syncPoll);
						syncPoll = null;
						await load();
						if (typeof window.loadDashboard === 'function') await window.loadDashboard();
					}
				} catch (error) {
					clearInterval(syncPoll);
					syncPoll = null;
					renderSyncStatus({ state: 'error', message: error.message });
				}
			}, 1200);
		} catch (error) {
			renderSyncStatus({ state: 'error', message: error.message });
		}
	}

	window.refreshApplicationsList = load;
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
