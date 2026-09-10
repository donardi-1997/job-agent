(() => {
	const state = { page: 1, pageSize: 10, pages: 1, total: 0 };
	let loading = false;

	function escape(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function ensureStyles() {
		if (document.querySelector('#applicationsViewStyles')) return;
		const style = document.createElement('style');
		style.id = 'applicationsViewStyles';
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
		if (!value) return { date: 'Fecha no disponible', time: '' };
		const normalized = String(value).includes('T') ? String(value) : String(value).replace(' ', 'T') + 'Z';
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

	function mount() {
		ensureStyles();
		if (document.querySelector('#applications')) return;
		const jobs = document.querySelector('#jobs');
		const profile = document.querySelector('#profile');
		if (!jobs || !profile) return;

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
				<div><h2>Mis postulaciones</h2><p>Solo envíos confirmados. Los intentos en modo prueba no aparecen aquí.</p></div>
				<span class="applications-count"><strong id="applicationsCount">0</strong> enviadas</span>
			</div>
			<div class="applications-table-wrap">
				<table class="applications-table">
					<thead><tr><th>Vacante</th><th>Fecha de postulación</th><th>Score</th><th>Estado</th><th></th></tr></thead>
					<tbody id="applicationsBody"></tbody>
				</table>
				<div class="applications-empty" id="applicationsEmpty" hidden><strong>Aún no hay postulaciones reales</strong><span>Las pruebas TEST no cuentan como envíos. Cuando una postulación REAL sea confirmada aparecerá aquí.</span></div>
			</div>
			<div class="applications-pagination" id="applicationsPagination">
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
			const response = await fetch(`/api/applications?page=${state.page}&page_size=${state.pageSize}`, { cache: 'no-store' });
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			state.page = Number(payload.page || 1);
			state.pages = Math.max(1, Number(payload.pages || 1));
			state.total = Number(payload.total || 0);
			render(payload);
		} catch (error) {
			console.error('Unable to load confirmed applications', error);
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
			row.innerHTML = `
				<td><span class="application-title">${escape(job.title)}</span><span class="application-company">${escape(job.company || job.source)} · ${escape(job.location || 'Sin ubicación')}</span></td>
				<td class="application-date"><strong>${escape(applied.date)}</strong><span>${escape(applied.time)}</span></td>
				<td><span class="${window.scoreClass ? window.scoreClass(Number(job.score)) : 'score'}">${escape(job.score)}%</span></td>
				<td><span class="application-status">${escape(statusLabel(job.application_status))}</span>${job.application_confirmation ? `<span class="application-confirmation">${escape(job.application_confirmation)}</span>` : ''}</td>
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
