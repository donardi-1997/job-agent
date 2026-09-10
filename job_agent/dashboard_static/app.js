const $ = (selector) => document.querySelector(selector);

let statusPoll = null;

async function fetchJson(url, options = undefined) {
	const response = await fetch(url, options);
	const payload = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
	return payload;
}

function renderStats(stats) {
	$('#totalMetric').textContent = stats.total ?? 0;
	$('#highMatchMetric').textContent = stats.high_match ?? 0;
	$('#appliedMetric').textContent = stats.applied ?? 0;
	$('#avgScoreMetric').textContent = stats.avg_score ?? 0;
}

function escapeHtml(value) {
	return String(value ?? '')
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#039;');
}

function renderJobs(jobs) {
	const body = $('#jobsBody');
	const empty = $('#emptyState');
	body.innerHTML = '';

	if (!jobs.length) {
		empty.classList.remove('hidden');
		return;
	}

	empty.classList.add('hidden');
	for (const job of jobs) {
		const row = document.createElement('tr');
		row.innerHTML = `
			<td><span class="job-title">${escapeHtml(job.title)}</span><span class="job-company">${escapeHtml(job.company || job.source)}</span></td>
			<td>${escapeHtml(job.location || 'Sin especificar')}</td>
			<td><span class="score">${escapeHtml(job.score)}</span></td>
			<td><span class="status">${escapeHtml(job.status)}</span></td>
			<td><a class="open-link" href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer">Abrir ↗</a></td>
		`;
		body.appendChild(row);
	}
}

function renderSearchStatus(status) {
	const box = $('#searchStatus');
	const button = $('#searchButton');
	box.dataset.state = status.state || 'idle';
	button.disabled = status.state === 'running';
	button.textContent = status.state === 'running' ? 'Buscando…' : 'Iniciar búsqueda';

	const titles = {
		idle: 'Agente listo',
		running: 'Búsqueda en ejecución',
		completed: 'Búsqueda completada',
		error: 'La búsqueda necesita atención',
	};
	$('#searchStatusTitle').textContent = titles[status.state] || 'Estado del agente';
	$('#searchStatusMessage').textContent = status.message || 'Configura tu búsqueda y ejecútala cuando quieras.';
}

async function loadDashboard() {
	const minScore = Number($('#scoreFilter').value || 0);
	const status = $('#statusFilter').value;
	const query = new URLSearchParams({ min_score: String(minScore) });
	if (status) query.set('status', status);

	try {
		const [stats, jobs, searchStatus] = await Promise.all([
			fetchJson('/api/stats'),
			fetchJson(`/api/jobs?${query.toString()}`),
			fetchJson('/api/search/status'),
		]);
		renderStats(stats);
		renderJobs(jobs);
		renderSearchStatus(searchStatus);
	} catch (error) {
		console.error('Unable to load dashboard', error);
	}
}

async function pollSearchStatus() {
	try {
		const status = await fetchJson('/api/search/status');
		renderSearchStatus(status);
		if (status.state !== 'running') {
			if (statusPoll) window.clearInterval(statusPoll);
			statusPoll = null;
			await loadDashboard();
		}
	} catch (error) {
		console.error('Unable to poll search status', error);
	}
}

async function startSearch(event) {
	event.preventDefault();
	const payload = {
		keyword: $('#keywordInput').value.trim(),
		location: $('#locationInput').value.trim(),
		max_results: Number($('#maxResultsInput').value),
	};

	try {
		const status = await fetchJson('/api/search', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
		});
		renderSearchStatus(status);
		if (statusPoll) window.clearInterval(statusPoll);
		statusPoll = window.setInterval(pollSearchStatus, 1500);
	} catch (error) {
		renderSearchStatus({ state: 'error', message: error.message });
	}
}

$('#refreshButton').addEventListener('click', loadDashboard);
$('#focusSearchButton').addEventListener('click', () => {
	$('#search').scrollIntoView({ behavior: 'smooth', block: 'center' });
	$('#keywordInput').focus();
});
$('#searchForm').addEventListener('submit', startSearch);
$('#scoreFilter').addEventListener('change', loadDashboard);
$('#statusFilter').addEventListener('change', loadDashboard);
loadDashboard().then(async () => {
	const status = await fetchJson('/api/search/status').catch(() => null);
	if (status?.state === 'running') statusPoll = window.setInterval(pollSearchStatus, 1500);
});
