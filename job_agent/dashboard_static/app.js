const $ = (selector) => document.querySelector(selector);
let statusPoll = null;

async function fetchJson(url, options = undefined) {
	const response = await fetch(url, options);
	const payload = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
	return payload;
}

function splitCsv(value) {
	return value.split(',').map((item) => item.trim()).filter(Boolean);
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

function scoreClass(score) {
	if (score >= 85) return 'score score-high';
	if (score >= 75) return 'score score-good';
	if (score >= 60) return 'score score-mid';
	return 'score score-low';
}

function decisionLabel(band) {
	return { ignore: 'Ignorar', save: 'Guardar', recommend: 'Recomendada', prepare: 'Preparar' }[band] || band || '—';
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
			<td><span class="${scoreClass(Number(job.score))}">${escapeHtml(job.score)}</span></td>
			<td><span class="decision decision-${escapeHtml(job.band)}">${escapeHtml(decisionLabel(job.band))}</span></td>
			<td><a class="open-link" href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer">Abrir ↗</a></td>`;
		body.appendChild(row);
	}
}

function renderSearchStatus(status) {
	const box = $('#searchStatus');
	const button = $('#searchButton');
	box.dataset.state = status.state || 'idle';
	button.disabled = status.state === 'running';
	button.textContent = status.state === 'running' ? 'Buscando…' : 'Iniciar búsqueda';
	const titles = { idle: 'Agente listo', running: 'Búsqueda en ejecución', completed: 'Búsqueda completada', error: 'La búsqueda necesita atención' };
	$('#searchStatusTitle').textContent = titles[status.state] || 'Estado del agente';
	$('#searchStatusMessage').textContent = status.message || 'Configura tu búsqueda y ejecútala cuando quieras.';
}

function renderProfile(profile) {
	$('#rolesInput').value = (profile.target_roles || []).join(', ');
	$('#skillsInput').value = (profile.skills || []).join(', ');
	$('#locationsInput').value = (profile.preferred_locations || []).join(', ');
	$('#experienceInput').value = profile.years_experience ?? 0;
	$('#minScoreInput').value = profile.min_score ?? 60;
	$('#prepareScoreInput').value = profile.prepare_application_score ?? 85;
	$('#excludedInput').value = (profile.excluded_terms || []).join(', ');
	$('#remoteInput').checked = Boolean(profile.remote_ok);
	if (profile.target_roles?.length) $('#keywordInput').value = profile.target_roles[0];
	if (profile.preferred_locations?.length) $('#locationInput').value = profile.preferred_locations[0];
}

async function loadDashboard() {
	const minScore = Number($('#scoreFilter').value || 0);
	const status = $('#statusFilter').value;
	const query = new URLSearchParams({ min_score: String(minScore) });
	if (status) query.set('status', status);
	try {
		const [stats, jobs, searchStatus] = await Promise.all([
			fetchJson('/api/stats'), fetchJson(`/api/jobs?${query}`), fetchJson('/api/search/status'),
		]);
		renderStats(stats);
		renderJobs(jobs);
		renderSearchStatus(searchStatus);
	} catch (error) {
		console.error('Unable to load dashboard', error);
	}
}

async function loadProfile() {
	try { renderProfile(await fetchJson('/api/profile')); }
	catch (error) { $('#profileMessage').textContent = `No se pudo cargar el perfil: ${error.message}`; }
}

async function saveProfile(event) {
	event.preventDefault();
	const button = event.submitter;
	button.disabled = true;
	$('#profileState').textContent = 'Guardando…';
	const payload = {
		target_roles: splitCsv($('#rolesInput').value),
		skills: splitCsv($('#skillsInput').value),
		preferred_locations: splitCsv($('#locationsInput').value),
		years_experience: Number($('#experienceInput').value || 0),
		min_score: Number($('#minScoreInput').value || 0),
		prepare_application_score: Number($('#prepareScoreInput').value || 0),
		excluded_terms: splitCsv($('#excludedInput').value),
		remote_ok: $('#remoteInput').checked,
	};
	try {
		const profile = await fetchJson('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
		renderProfile(profile);
		$('#profileState').textContent = 'Guardado';
		$('#profileMessage').textContent = 'Perfil actualizado. Las próximas vacantes usarán esta configuración.';
	} catch (error) {
		$('#profileState').textContent = 'Error';
		$('#profileMessage').textContent = error.message;
	} finally { button.disabled = false; }
}

async function pollSearchStatus() {
	try {
		const status = await fetchJson('/api/search/status');
		renderSearchStatus(status);
		if (status.state !== 'running') {
			if (statusPoll) clearInterval(statusPoll);
			statusPoll = null;
			await loadDashboard();
		}
	} catch (error) { console.error('Unable to poll search status', error); }
}

async function startSearch(event) {
	event.preventDefault();
	const payload = { keyword: $('#keywordInput').value.trim(), location: $('#locationInput').value.trim(), max_results: Number($('#maxResultsInput').value) };
	try {
		const status = await fetchJson('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
		renderSearchStatus(status);
		if (statusPoll) clearInterval(statusPoll);
		statusPoll = setInterval(pollSearchStatus, 1500);
	} catch (error) { renderSearchStatus({ state: 'error', message: error.message }); }
}

$('#refreshButton').addEventListener('click', () => Promise.all([loadDashboard(), loadProfile()]));
$('#focusSearchButton').addEventListener('click', () => { $('#search').scrollIntoView({ behavior: 'smooth', block: 'center' }); $('#keywordInput').focus(); });
$('#searchForm').addEventListener('submit', startSearch);
$('#profileForm').addEventListener('submit', saveProfile);
$('#scoreFilter').addEventListener('change', loadDashboard);
$('#statusFilter').addEventListener('change', loadDashboard);

Promise.all([loadDashboard(), loadProfile()]).then(async () => {
	const status = await fetchJson('/api/search/status').catch(() => null);
	if (status?.state === 'running') statusPoll = setInterval(pollSearchStatus, 1500);
});
