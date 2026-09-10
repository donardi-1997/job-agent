(() => {
	const state = {
		page: 1,
		pageSize: 10,
		total: 0,
		pages: 1,
		start: 0,
		end: 0,
		hasPrevious: false,
		hasNext: false,
	};

	const originalFetch = window.fetch.bind(window);

	function ensureStyles() {
		if (document.querySelector('#jobPaginationStyles')) return;
		const style = document.createElement('style');
		style.id = 'jobPaginationStyles';
		style.textContent = `
			.jobs-pagination{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 20px;border-top:1px solid rgba(255,255,255,.07);background:rgba(7,12,25,.35)}
			.jobs-pagination-info{display:flex;flex-direction:column;gap:3px;color:#8f9ab3;font-size:11px}.jobs-pagination-info strong{color:#dce4f5;font-size:12px}
			.jobs-pagination-actions{display:flex;align-items:center;gap:8px}.jobs-pagination button{min-width:92px}.jobs-pagination select{height:37px;color:#edf2fb;background:rgba(7,12,25,.75);border:1px solid rgba(255,255,255,.1);border-radius:9px;padding:0 9px}
			.jobs-pagination button:disabled{opacity:.4;cursor:not-allowed;transform:none}
			@media(max-width:620px){.jobs-pagination{align-items:stretch;flex-direction:column}.jobs-pagination-actions{display:grid;grid-template-columns:1fr auto 1fr}.jobs-pagination button{min-width:0}}
		`;
		document.head.appendChild(style);
	}

	function mount() {
		ensureStyles();
		const panel = document.querySelector('#jobs');
		const table = panel?.querySelector('.table-wrap');
		if (!panel || !table || document.querySelector('#jobsPagination')) return;
		const root = document.createElement('div');
		root.id = 'jobsPagination';
		root.className = 'jobs-pagination';
		root.innerHTML = `
			<div class="jobs-pagination-info">
				<strong id="jobsPaginationPage">Página 1 de 1</strong>
				<span id="jobsPaginationRange">0 vacantes</span>
			</div>
			<div class="jobs-pagination-actions">
				<button class="button secondary" id="jobsPrevPage" type="button">← Anterior</button>
				<select id="jobsPageSize" aria-label="Vacantes por página">
					<option value="10" selected>10 / página</option>
					<option value="20">20 / página</option>
					<option value="50">50 / página</option>
				</select>
				<button class="button secondary" id="jobsNextPage" type="button">Siguiente →</button>
			</div>`;
		table.insertAdjacentElement('afterend', root);
		root.querySelector('#jobsPrevPage').addEventListener('click', () => goToPage(state.page - 1));
		root.querySelector('#jobsNextPage').addEventListener('click', () => goToPage(state.page + 1));
		root.querySelector('#jobsPageSize').addEventListener('change', (event) => {
			state.pageSize = Number(event.target.value || 10);
			state.page = 1;
			window.loadDashboard?.();
		});
		renderControls();
	}

	function renderControls() {
		const page = document.querySelector('#jobsPaginationPage');
		const range = document.querySelector('#jobsPaginationRange');
		const prev = document.querySelector('#jobsPrevPage');
		const next = document.querySelector('#jobsNextPage');
		const size = document.querySelector('#jobsPageSize');
		if (!page || !range || !prev || !next || !size) return;
		page.textContent = `Página ${state.page} de ${state.pages}`;
		range.textContent = state.total
			? `${state.start}–${state.end} de ${state.total} vacantes`
			: '0 vacantes';
		prev.disabled = !state.hasPrevious;
		next.disabled = !state.hasNext;
		size.value = String(state.pageSize);
	}

	function goToPage(page) {
		if (page < 1 || page > state.pages || page === state.page) return;
		state.page = page;
		window.loadDashboard?.();
		document.querySelector('#jobs')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	function updateFromEnvelope(payload) {
		state.page = Number(payload.page || 1);
		state.pageSize = Number(payload.page_size || state.pageSize);
		state.total = Number(payload.total || 0);
		state.pages = Math.max(1, Number(payload.pages || 1));
		state.start = Number(payload.start || 0);
		state.end = Number(payload.end || 0);
		state.hasPrevious = Boolean(payload.has_previous);
		state.hasNext = Boolean(payload.has_next);
		renderControls();
	}

	window.fetch = async (input, init) => {
		const raw = typeof input === 'string' ? input : input?.url;
		if (!raw) return originalFetch(input, init);
		let url;
		try { url = new URL(raw, window.location.origin); } catch (_) { return originalFetch(input, init); }
		if (url.origin !== window.location.origin || url.pathname !== '/api/jobs') {
			return originalFetch(input, init);
		}

		url.searchParams.set('page', String(state.page));
		url.searchParams.set('page_size', String(state.pageSize));
		const requestUrl = `${url.pathname}${url.search}`;
		const response = await originalFetch(requestUrl, init);
		if (!response.ok) return response;

		const payload = await response.clone().json().catch(() => null);
		if (!payload || !Array.isArray(payload.items)) return response;
		updateFromEnvelope(payload);

		const headers = new Headers(response.headers);
		headers.set('Content-Type', 'application/json; charset=utf-8');
		return new Response(JSON.stringify(payload.items), {
			status: response.status,
			statusText: response.statusText,
			headers,
		});
	};

	for (const selector of ['#scoreFilter', '#statusFilter']) {
		document.addEventListener('change', (event) => {
			if (event.target?.matches?.(selector)) state.page = 1;
		}, true);
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', mount);
	} else {
		mount();
	}

	setTimeout(() => window.loadDashboard?.(), 0);
})();

(() => {
	const state = { page: 1, pageSize: 10, pages: 1, total: 0 };
	let loading = false;

	function escapeHtml(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function xhrJson(url) {
		return new Promise((resolve, reject) => {
			const xhr = new XMLHttpRequest();
			xhr.open('GET', url, true);
			xhr.setRequestHeader('Cache-Control', 'no-cache');
			xhr.onload = () => {
				let payload = {};
				try { payload = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
				if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
				else reject(new Error(payload.error || `HTTP ${xhr.status}`));
			};
			xhr.onerror = () => reject(new Error('No se pudo consultar el historial de postulaciones.'));
			xhr.send();
		});
	}

	function ensureStyles() {
		if (document.querySelector('#applicationsHistoryStyles')) return;
		const style = document.createElement('style');
		style.id = 'applicationsHistoryStyles';
		style.textContent = `
			.applications-panel{margin-top:18px}.applications-count{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border-radius:999px;border:1px solid rgba(104,211,145,.2);background:rgba(104,211,145,.07);color:#8ce1ad;font-size:11px;font-weight:800}
			.applications-table-wrap{overflow-x:auto}.applications-table{width:100%;border-collapse:collapse}.applications-table th,.applications-table td{padding:15px 20px;text-align:left;border-bottom:1px solid rgba(255,255,255,.055)}.applications-table th{color:#7f8aa4;font-size:11px;text-transform:uppercase;letter-spacing:.08em}.applications-table td{color:#cfd6e7;font-size:13px}.applications-table tr:hover{background:rgba(255,255,255,.025)}
			.application-title{display:block;color:#f3f6fd;font-weight:750}.application-company{display:block;margin-top:3px;color:#75819b;font-size:11px}.application-date strong,.application-date span{display:block}.application-date strong{color:#dce4f5;font-size:12px}.application-date span{margin-top:3px;color:#7f8ca6;font-size:11px}.application-status{display:inline-flex;padding:5px 8px;border-radius:8px;background:rgba(104,211,145,.08);color:#88e2a8;font-size:11px;font-weight:750}.application-confirmation{display:block;margin-top:5px;max-width:360px;color:#73809a;font-size:10px;line-height:1.4}
			.applications-empty{padding:48px 24px;text-align:center;color:#7e89a3}.applications-empty strong{display:block;margin-bottom:7px;color:#dce3f2}.applications-pagination{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 20px}.applications-page-info{color:#8f9ab3;font-size:11px}.applications-page-actions{display:flex;align-items:center;gap:8px}.applications-page-actions select{height:37px;color:#edf2fb;background:rgba(7,12,25,.75);border:1px solid rgba(255,255,255,.1);border-radius:9px;padding:0 9px}.applications-page-actions button:disabled{opacity:.4;cursor:not-allowed;transform:none}
			.metric-card[data-open-applications]{cursor:pointer}.metric-card[data-open-applications]:hover{border-color:rgba(104,211,145,.25)}
			@media(max-width:620px){.applications-table thead{display:none}.applications-table,.applications-table tbody,.applications-table tr,.applications-table td{display:block;width:100%}.applications-table tr{padding:14px 16px;border-bottom:1px solid rgba(255,255,255,.07)}.applications-table td{padding:5px 0;border:0}.applications-pagination{align-items:stretch;flex-direction:column}.applications-page-actions{display:grid;grid-template-columns:1fr auto 1fr}}
		`;
		document.head.appendChild(style);
	}

	function formatAppliedAt(value) {
		if (!value) return { date: 'Registrada como postulada', time: '' };
		const normalized = String(value).includes('T') ? String(value) : `${String(value).replace(' ', 'T')}Z`;
		const date = new Date(normalized);
		if (Number.isNaN(date.getTime())) return { date: String(value), time: '' };
		return {
			date: new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium', timeZone: 'America/Bogota' }).format(date),
			time: new Intl.DateTimeFormat('es-CO', { timeStyle: 'short', timeZone: 'America/Bogota' }).format(date),
		};
	}

	function statusLabel(status) {
		return status === 'already_applied' ? 'Ya estaba postulada' : 'Enviada';
	}

	async function latestSubmittedAttempt(jobId) {
		try {
			const attempts = await window.fetch(`/api/jobs/${jobId}/attempts`, { cache: 'no-store' }).then((response) => response.ok ? response.json() : []);
			if (!Array.isArray(attempts)) return null;
			return attempts.find((attempt) => attempt?.submitted === true) || null;
		} catch (_) {
			return null;
		}
	}

	function mount() {
		ensureStyles();
		if (document.querySelector('#applications')) return;
		const profile = document.querySelector('#profile');
		if (!profile) return;

		const navJobs = document.querySelector('nav a[href="#jobs"]');
		if (navJobs && !document.querySelector('nav a[href="#applications"]')) {
			const link = document.createElement('a');
			link.className = 'nav-item';
			link.href = '#applications';
			link.textContent = 'Mis postulaciones';
			navJobs.insertAdjacentElement('afterend', link);
		}

		const panel = document.createElement('section');
		panel.className = 'panel applications-panel';
		panel.id = 'applications';
		panel.innerHTML = `
			<div class="panel-header">
				<div><h2>Mis postulaciones</h2><p>Vacantes enviadas realmente. Los intentos en modo prueba no aparecen aquí.</p></div>
				<span class="applications-count"><strong id="applicationsCount">0</strong> postuladas</span>
			</div>
			<div class="applications-table-wrap">
				<table class="applications-table">
					<thead><tr><th>Vacante</th><th>Fecha de postulación</th><th>Score</th><th>Estado</th><th></th></tr></thead>
					<tbody id="applicationsBody"></tbody>
				</table>
				<div class="applications-empty" id="applicationsEmpty" hidden><strong>Aún no hay postulaciones reales</strong><span>Las pruebas TEST no cuentan. Cuando una postulación REAL quede enviada aparecerá aquí.</span></div>
			</div>
			<div class="applications-pagination">
				<span class="applications-page-info" id="applicationsPageInfo">0 postulaciones</span>
				<div class="applications-page-actions">
					<button class="button secondary" id="applicationsPrev" type="button">← Anterior</button>
					<select id="applicationsPageSize" aria-label="Postulaciones por página"><option value="10">10 / página</option><option value="20">20 / página</option><option value="50">50 / página</option></select>
					<button class="button secondary" id="applicationsNext" type="button">Siguiente →</button>
				</div>
			</div>`;
		profile.insertAdjacentElement('beforebegin', panel);

		panel.querySelector('#applicationsPrev').addEventListener('click', () => goToPage(state.page - 1));
		panel.querySelector('#applicationsNext').addEventListener('click', () => goToPage(state.page + 1));
		panel.querySelector('#applicationsPageSize').addEventListener('change', (event) => {
			state.pageSize = Number(event.target.value || 10);
			state.page = 1;
			loadApplications();
		});

		const appliedMetric = document.querySelector('#appliedMetric')?.closest('.metric-card');
		if (appliedMetric) {
			appliedMetric.dataset.openApplications = '1';
			appliedMetric.title = 'Ver mis postulaciones';
			appliedMetric.addEventListener('click', () => panel.scrollIntoView({ behavior: 'smooth', block: 'start' }));
		}

		document.querySelector('#refreshButton')?.addEventListener('click', loadApplications);
		const metric = document.querySelector('#appliedMetric');
		if (metric) new MutationObserver(() => loadApplications()).observe(metric, { childList: true, characterData: true, subtree: true });
		loadApplications();
	}

	async function loadApplications() {
		if (loading) return;
		loading = true;
		try {
			const payload = await xhrJson(`/api/jobs?status=applied&min_score=0&page=${state.page}&page_size=${state.pageSize}`);
			const items = Array.isArray(payload.items) ? payload.items : [];
			const hydrated = await Promise.all(items.map(async (job) => {
				const attempt = await latestSubmittedAttempt(job.id);
				return {
					...job,
					applied_at: attempt?.created_at || '',
					application_status: attempt?.submission_status || 'submitted',
					application_confirmation: attempt?.confirmation_text || '',
				};
			}));
			state.page = Number(payload.page || 1);
			state.pages = Math.max(1, Number(payload.pages || 1));
			state.total = Number(payload.total || 0);
			render({ ...payload, items: hydrated });
		} catch (error) {
			console.error('Unable to load applied jobs', error);
		} finally {
			loading = false;
		}
	}

	function render(payload) {
		const body = document.querySelector('#applicationsBody');
		const empty = document.querySelector('#applicationsEmpty');
		const count = document.querySelector('#applicationsCount');
		const info = document.querySelector('#applicationsPageInfo');
		const prev = document.querySelector('#applicationsPrev');
		const next = document.querySelector('#applicationsNext');
		if (!body || !empty || !count || !info || !prev || !next) return;

		const items = Array.isArray(payload.items) ? payload.items : [];
		body.innerHTML = '';
		count.textContent = String(payload.total || 0);
		empty.hidden = items.length > 0;

		for (const job of items) {
			const applied = formatAppliedAt(job.applied_at);
			const row = document.createElement('tr');
			const scoreCss = Number(job.score) >= 85 ? 'score score-high' : Number(job.score) >= 75 ? 'score score-good' : Number(job.score) >= 60 ? 'score score-mid' : 'score score-low';
			row.innerHTML = `
				<td><span class="application-title">${escapeHtml(job.title)}</span><span class="application-company">${escapeHtml(job.company || job.source)} · ${escapeHtml(job.location || 'Sin ubicación')}</span></td>
				<td class="application-date"><strong>${escapeHtml(applied.date)}</strong><span>${escapeHtml(applied.time)}</span></td>
				<td><span class="${scoreCss}">${escapeHtml(job.score)}%</span></td>
				<td><span class="application-status">${escapeHtml(statusLabel(job.application_status))}</span>${job.application_confirmation ? `<span class="application-confirmation">${escapeHtml(job.application_confirmation)}</span>` : ''}</td>
				<td><button class="review-link" type="button" data-application-job="${Number(job.id)}">Revisar →</button></td>`;
			body.appendChild(row);
		}
		body.querySelectorAll('[data-application-job]').forEach((button) => {
			button.addEventListener('click', () => window.openJob?.(Number(button.dataset.applicationJob)));
		});

		info.textContent = payload.total
			? `Página ${payload.page} de ${payload.pages} · ${payload.start}–${payload.end} de ${payload.total}`
			: '0 postulaciones';
		prev.disabled = !payload.has_previous;
		next.disabled = !payload.has_next;
	}

	function goToPage(page) {
		if (page < 1 || page > state.pages || page === state.page) return;
		state.page = page;
		loadApplications();
		document.querySelector('#applications')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	window.loadApplications = loadApplications;
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
