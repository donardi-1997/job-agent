const $ = (selector) => document.querySelector(selector);
let statusPoll = null;
let preparePoll = null;
let activeJobId = null;

async function fetchJson(url, options = undefined) {
	const response = await fetch(url, options);
	const payload = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
	return payload;
}

function splitCsv(value) { return value.split(',').map((item) => item.trim()).filter(Boolean); }
function escapeHtml(value) { return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;'); }
function scoreClass(score) { if (score >= 85) return 'score score-high'; if (score >= 75) return 'score score-good'; if (score >= 60) return 'score score-mid'; return 'score score-low'; }
function decisionLabel(band) { return { ignore: 'Ignorar', save: 'Guardar', recommend: 'Recomendada', prepare: 'Preparar' }[band] || band || '—'; }

function renderStats(stats) {
	$('#totalMetric').textContent = stats.total ?? 0;
	$('#highMatchMetric').textContent = stats.high_match ?? 0;
	$('#appliedMetric').textContent = stats.applied ?? 0;
	$('#avgScoreMetric').textContent = stats.avg_score ?? 0;
}

function renderJobs(jobs) {
	const body = $('#jobsBody');
	const empty = $('#emptyState');
	body.innerHTML = '';
	if (!jobs.length) { empty.classList.remove('hidden'); return; }
	empty.classList.add('hidden');
	for (const job of jobs) {
		const row = document.createElement('tr');
		row.className = 'job-row';
		row.innerHTML = `<td><span class="job-title">${escapeHtml(job.title)}</span><span class="job-company">${escapeHtml(job.company || job.source)}</span></td><td>${escapeHtml(job.location || 'Sin especificar')}</td><td><span class="${scoreClass(Number(job.score))}">${escapeHtml(job.score)}</span></td><td><span class="decision decision-${escapeHtml(job.band)}">${escapeHtml(decisionLabel(job.band))}</span></td><td><button class="review-link" data-review-job="${job.id}">Revisar →</button></td>`;
		body.appendChild(row);
	}
	body.querySelectorAll('[data-review-job]').forEach((button) => button.addEventListener('click', () => openJob(Number(button.dataset.reviewJob))));
}

function chips(items, emptyText) {
	if (!items?.length) return `<span class="empty-chip">${escapeHtml(emptyText)}</span>`;
	return items.map((item) => `<span class="skill-chip">${escapeHtml(item)}</span>`).join('');
}

function renderDraft(draft) {
	const box = $('#draftBox');
	const questions = draft.questions || [];
	box.classList.remove('hidden');
	$('#draftSummary').innerHTML = `<strong>${escapeHtml(draft.summary || 'Borrador preparado')}</strong>${draft.blocked_reason ? `<span class="draft-warning">${escapeHtml(draft.blocked_reason)}</span>` : ''}`;
	$('#draftQuestions').innerHTML = questions.length ? questions.map((item, index) => {
		const options = item.options?.length ? `<div class="draft-options">Opciones: ${item.options.map(escapeHtml).join(' · ')}</div>` : '';
		const answer = item.suggested_answer ? escapeHtml(item.suggested_answer) : 'Necesita tu respuesta';
		const state = item.requires_user_input ? 'needs-input' : 'ready';
		return `<article class="draft-question ${state}"><div class="question-top"><span>#${index + 1}</span><strong>${escapeHtml(item.question)}</strong><em>${escapeHtml(item.confidence)}%</em></div>${options}<div class="suggested-answer"><small>Respuesta sugerida</small><p>${answer}</p></div>${item.note ? `<p class="draft-note">${escapeHtml(item.note)}</p>` : ''}<span class="answer-state">${item.requires_user_input ? 'Requiere revisión' : 'Lista para revisar'}</span></article>`;
	}).join('') : '<p class="empty-chip">No se detectaron preguntas visibles en el flujo.</p>';
}

function renderPrepareStatus(status) {
	const box = $('#prepareStatus');
	const button = $('#prepareButton');
	box.dataset.state = status.state || 'idle';
	const runningForThisJob = status.state === 'running' && status.job_id === activeJobId;
	button.disabled = status.state === 'running';
	button.textContent = runningForThisJob ? 'Preparando…' : 'Preparar postulación';
	const titles = { idle: 'Sin borrador', running: 'Preparando postulación', completed: 'Borrador preparado', error: 'La preparación necesita atención' };
	$('#prepareStatusTitle').textContent = titles[status.state] || 'Estado de preparación';
	$('#prepareStatusMessage').textContent = status.message || 'Puedes preparar la postulación cuando quieras.';
}

async function loadDraft(jobId) {
	try {
		const draft = await fetchJson(`/api/jobs/${jobId}/draft`);
		if (activeJobId === jobId) {
			renderDraft(draft);
			renderPrepareStatus({ state: 'completed', job_id: jobId, message: `Borrador guardado · ${draft.questions?.length || 0} preguntas/campos.` });
		}
	} catch (_) {
		if (activeJobId === jobId) {
			$('#draftBox').classList.add('hidden');
			renderPrepareStatus({ state: 'idle', job_id: jobId, message: 'Puedes preparar la postulación cuando quieras.' });
		}
	}
}

async function openJob(jobId) {
	try {
		const job = await fetchJson(`/api/jobs/${jobId}`);
		activeJobId = jobId;
		$('#drawerTitle').textContent = job.title;
		$('#drawerCompany').textContent = [job.company, job.location].filter(Boolean).join(' · ');
		$('#drawerScore').textContent = `${job.score}%`;
		$('#drawerDecision').textContent = decisionLabel(job.band);
		$('#matchedSkills').innerHTML = chips(job.matched_skills, 'No se detectaron coincidencias directas de skills.');
		$('#missingSkills').innerHTML = chips(job.missing_skills, 'No hay brechas contra las skills configuradas.');
		$('#matchReasons').innerHTML = (job.match_reasons || []).length ? job.match_reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join('') : '<li>Sin razones adicionales registradas.</li>';
		$('#drawerDescription').textContent = job.description || 'Computrabajo no entregó una descripción para esta vacante.';
		$('#drawerOpenLink').href = job.url;
		$('#jobDrawer').classList.add('open');
		$('#drawerBackdrop').classList.add('open');
		$('#jobDrawer').setAttribute('aria-hidden', 'false');
		document.body.classList.add('drawer-open');
		await loadDraft(jobId);
	} catch (error) { console.error('Unable to open job detail', error); }
}

function closeDrawer() {
	$('#jobDrawer').classList.remove('open');
	$('#drawerBackdrop').classList.remove('open');
	$('#jobDrawer').setAttribute('aria-hidden', 'true');
	document.body.classList.remove('drawer-open');
	activeJobId = null;
}

async function updateJobStatus(status) {
	if (!activeJobId) return;
	try {
		await fetchJson(`/api/jobs/${activeJobId}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
		await loadDashboard();
		closeDrawer();
	} catch (error) { console.error('Unable to update job status', error); }
}

async function pollPrepareStatus() {
	try {
		const status = await fetchJson('/api/prepare/status');
		if (activeJobId === status.job_id) renderPrepareStatus(status);
		if (status.state !== 'running') {
			if (preparePoll) clearInterval(preparePoll);
			preparePoll = null;
			if (status.state === 'completed' && status.job_id) await loadDraft(status.job_id);
		}
	} catch (error) { console.error('Unable to poll preparation status', error); }
}

async function prepareApplication() {
	if (!activeJobId) return;
	const jobId = activeJobId;
	$('#draftBox').classList.add('hidden');
	try {
		const status = await fetchJson(`/api/jobs/${jobId}/prepare`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
		renderPrepareStatus(status);
		if (preparePoll) clearInterval(preparePoll);
		preparePoll = setInterval(pollPrepareStatus, 1500);
	} catch (error) { renderPrepareStatus({ state: 'error', job_id: jobId, message: error.message }); }
}

function renderSearchStatus(status) {
	const box = $('#searchStatus'); const button = $('#searchButton');
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
	const minScore = Number($('#scoreFilter').value || 0); const status = $('#statusFilter').value;
	const query = new URLSearchParams({ min_score: String(minScore) }); if (status) query.set('status', status);
	try {
		const [stats, jobs, searchStatus] = await Promise.all([fetchJson('/api/stats'), fetchJson(`/api/jobs?${query}`), fetchJson('/api/search/status')]);
		renderStats(stats); renderJobs(jobs); renderSearchStatus(searchStatus);
	} catch (error) { console.error('Unable to load dashboard', error); }
}

async function loadProfile() { try { renderProfile(await fetchJson('/api/profile')); } catch (error) { $('#profileMessage').textContent = `No se pudo cargar el perfil: ${error.message}`; } }

async function saveProfile(event) {
	event.preventDefault(); const button = event.submitter; button.disabled = true; $('#profileState').textContent = 'Guardando…';
	const payload = { target_roles: splitCsv($('#rolesInput').value), skills: splitCsv($('#skillsInput').value), preferred_locations: splitCsv($('#locationsInput').value), years_experience: Number($('#experienceInput').value || 0), min_score: Number($('#minScoreInput').value || 0), prepare_application_score: Number($('#prepareScoreInput').value || 0), excluded_terms: splitCsv($('#excludedInput').value), remote_ok: $('#remoteInput').checked };
	try { const profile = await fetchJson('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); renderProfile(profile); $('#profileState').textContent = 'Guardado'; $('#profileMessage').textContent = 'Perfil actualizado. Las próximas vacantes usarán esta configuración.'; }
	catch (error) { $('#profileState').textContent = 'Error'; $('#profileMessage').textContent = error.message; }
	finally { button.disabled = false; }
}

async function pollSearchStatus() {
	try { const status = await fetchJson('/api/search/status'); renderSearchStatus(status); if (status.state !== 'running') { if (statusPoll) clearInterval(statusPoll); statusPoll = null; await loadDashboard(); } }
	catch (error) { console.error('Unable to poll search status', error); }
}

async function startSearch(event) {
	event.preventDefault();
	const payload = { keyword: $('#keywordInput').value.trim(), location: $('#locationInput').value.trim(), max_results: Number($('#maxResultsInput').value) };
	try { const status = await fetchJson('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); renderSearchStatus(status); if (statusPoll) clearInterval(statusPoll); statusPoll = setInterval(pollSearchStatus, 1500); }
	catch (error) { renderSearchStatus({ state: 'error', message: error.message }); }
}

$('#refreshButton').addEventListener('click', () => Promise.all([loadDashboard(), loadProfile()]));
$('#focusSearchButton').addEventListener('click', () => { $('#search').scrollIntoView({ behavior: 'smooth', block: 'center' }); $('#keywordInput').focus(); });
$('#searchForm').addEventListener('submit', startSearch); $('#profileForm').addEventListener('submit', saveProfile);
$('#scoreFilter').addEventListener('change', loadDashboard); $('#statusFilter').addEventListener('change', loadDashboard);
$('#drawerClose').addEventListener('click', closeDrawer); $('#drawerBackdrop').addEventListener('click', closeDrawer);
$('#prepareButton').addEventListener('click', prepareApplication);
document.querySelectorAll('[data-job-status]').forEach((button) => button.addEventListener('click', () => updateJobStatus(button.dataset.jobStatus)));
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawer(); });

Promise.all([loadDashboard(), loadProfile()]).then(async () => {
	const searchStatus = await fetchJson('/api/search/status').catch(() => null);
	if (searchStatus?.state === 'running') statusPoll = setInterval(pollSearchStatus, 1500);
	const preparationStatus = await fetchJson('/api/prepare/status').catch(() => null);
	if (preparationStatus?.state === 'running') preparePoll = setInterval(pollPrepareStatus, 1500);
});
