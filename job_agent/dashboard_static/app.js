const $ = (selector) => document.querySelector(selector);

async function fetchJson(url) {
	const response = await fetch(url);
	if (!response.ok) throw new Error(`HTTP ${response.status}`);
	return response.json();
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

async function loadDashboard() {
	const minScore = Number($('#scoreFilter').value || 0);
	const status = $('#statusFilter').value;
	const query = new URLSearchParams({ min_score: String(minScore) });
	if (status) query.set('status', status);

	try {
		const [stats, jobs] = await Promise.all([
			fetchJson('/api/stats'),
			fetchJson(`/api/jobs?${query.toString()}`),
		]);
		renderStats(stats);
		renderJobs(jobs);
	} catch (error) {
		console.error('Unable to load dashboard', error);
	}
}

$('#refreshButton').addEventListener('click', loadDashboard);
$('#scoreFilter').addEventListener('change', loadDashboard);
$('#statusFilter').addEventListener('change', loadDashboard);
loadDashboard();
