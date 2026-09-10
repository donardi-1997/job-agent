(() => {
	function esc(value) {
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
				let payload = [];
				try { payload = JSON.parse(xhr.responseText || '[]'); } catch (_) {}
				if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
				else reject(new Error(payload.error || `HTTP ${xhr.status}`));
			};
			xhr.onerror = () => reject(new Error('No se pudo cargar Mis postulaciones.'));
			xhr.send();
		});
	}

	function ensureStyles() {
		if (document.querySelector('#applicationsListStyles')) return;
		const style = document.createElement('style');
		style.id = 'applicationsListStyles';
		style.textContent = `
			.applications-list-panel{margin-top:18px}.applications-list-count{display:inline-flex;padding:6px 9px;border-radius:999px;background:rgba(104,211,145,.07);color:#8ddfab;font-size:10px;font-weight:800}.applications-list-empty{padding:34px 20px;text-align:center;color:#77849e;font-size:11px}.metric-card[data-open-applications]{cursor:pointer}.metric-card[data-open-applications]:hover{border-color:rgba(104,211,145,.25)}
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
				<div><h2>Mis postulaciones</h2><p>Solo vacantes marcadas como enviadas. Abre cualquiera para revisar sus preguntas y respuestas.</p></div>
				<span class="applications-list-count"><strong id="applicationsListCount">0</strong>&nbsp;enviadas</span>
			</div>
			<div class="table-wrap">
				<table><thead><tr><th>Vacante</th><th>Ubicación</th><th>Score</th><th>Estado</th><th></th></tr></thead><tbody id="applicationsListBody"></tbody></table>
				<div class="applications-list-empty" id="applicationsListEmpty" hidden>Aún no hay postulaciones reales enviadas.</div>
			</div>`;
		profile.insertAdjacentElement('beforebegin', panel);

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

	async function load() {
		const body = document.querySelector('#applicationsListBody');
		const empty = document.querySelector('#applicationsListEmpty');
		const count = document.querySelector('#applicationsListCount');
		if (!body || !empty || !count) return;
		try {
			const jobs = await xhrJson('/api/jobs?status=applied&min_score=0');
			const items = Array.isArray(jobs) ? jobs : [];
			count.textContent = String(items.length);
			body.innerHTML = '';
			empty.hidden = items.length > 0;
			for (const job of items) {
				const row = document.createElement('tr');
				row.innerHTML = `<td><span class="job-title">${esc(job.title)}</span><span class="job-company">${esc(job.company || job.source)}</span></td><td>${esc(job.location || 'Sin especificar')}</td><td><span class="score score-high">${esc(job.score)}</span></td><td><span class="decision decision-prepare">Postulada</span></td><td><button class="review-link" type="button" data-application-review="${job.id}">Revisar preguntas →</button></td>`;
				body.appendChild(row);
			}
			body.querySelectorAll('[data-application-review]').forEach((button) => {
				button.addEventListener('click', () => {
					const id = Number(button.dataset.applicationReview);
					if (typeof window.openJob === 'function') window.openJob(id);
				});
			});
		} catch (error) {
			body.innerHTML = '';
			empty.hidden = false;
			empty.textContent = error.message;
		}
	}

	window.refreshApplicationsList = load;
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
