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

	// Reset before the existing bubbling handlers issue their next filtered fetch.
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

	// The base script starts its initial request before this extension is appended.
	// Re-run once after mounting so the visible table always uses server pagination.
	setTimeout(() => window.loadDashboard?.(), 0);
})();
