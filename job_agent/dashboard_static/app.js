const $ = (selector) => document.querySelector(selector);
let statusPoll = null;
let preparePoll = null;
let batchPoll = null;
let activeJobId = null;
let activeDraft = null;

async function fetchJson(url, options = undefined) { const response = await fetch(url, options); const payload = await response.json().catch(() => ({})); if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`); return payload; }
function splitCsv(value) { return value.split(',').map((item) => item.trim()).filter(Boolean); }
function escapeHtml(value) { return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;'); }
function scoreClass(score) { if (score >= 85) return 'score score-high'; if (score >= 75) return 'score score-good'; if (score >= 60) return 'score score-mid'; return 'score score-low'; }
function decisionLabel(band) { return { ignore: 'Ignorar', save: 'Guardar', recommend: 'Recomendada', prepare: 'Postular' }[band] || band || '—'; }
function renderStats(stats) { $('#totalMetric').textContent = stats.total ?? 0; $('#highMatchMetric').textContent = stats.high_match ?? 0; $('#appliedMetric').textContent = stats.applied ?? 0; $('#avgScoreMetric').textContent = stats.avg_score ?? 0; }

function renderJobs(jobs) {
	const body = $('#jobsBody'); const empty = $('#emptyState'); body.innerHTML = '';
	if (!jobs.length) { empty.classList.remove('hidden'); return; } empty.classList.add('hidden');
	for (const job of jobs) { const row = document.createElement('tr'); row.className = 'job-row'; row.innerHTML = `<td><span class="job-title">${escapeHtml(job.title)}</span><span class="job-company">${escapeHtml(job.company || job.source)}</span></td><td>${escapeHtml(job.location || 'Sin especificar')}</td><td><span class="${scoreClass(Number(job.score))}">${escapeHtml(job.score)}</span></td><td><span class="decision decision-${escapeHtml(job.band)}">${job.status === 'applied' ? 'Postulada' : escapeHtml(decisionLabel(job.band))}</span></td><td><button class="review-link" data-review-job="${job.id}">Revisar →</button></td>`; body.appendChild(row); }
	body.querySelectorAll('[data-review-job]').forEach((button) => button.addEventListener('click', () => openJob(Number(button.dataset.reviewJob))));
}
function chips(items, emptyText) { return items?.length ? items.map((item) => `<span class="skill-chip">${escapeHtml(item)}</span>`).join('') : `<span class="empty-chip">${escapeHtml(emptyText)}</span>`; }

function addFrequentAnswerRow(item = { question: '', answer: '' }) {
	const row = document.createElement('div'); row.className = 'frequent-answer-row';
	row.innerHTML = `<input class="faq-question" placeholder="Ej. ¿Cuál es tu aspiración salarial?" value="${escapeHtml(item.question)}"><input class="faq-answer" placeholder="Respuesta" value="${escapeHtml(item.answer)}"><button class="button secondary remove-faq" type="button">Quitar</button>`;
	row.querySelector('.remove-faq').addEventListener('click', () => row.remove()); $('#frequentAnswers').appendChild(row);
}
function renderProfile(profile) {
	$('#rolesInput').value = (profile.target_roles || []).join(', '); $('#skillsInput').value = (profile.skills || []).join(', '); $('#locationsInput').value = (profile.preferred_locations || []).join(', '); $('#experienceInput').value = profile.years_experience ?? 0; $('#minScoreInput').value = profile.min_score ?? 60; $('#prepareScoreInput').value = profile.prepare_application_score ?? 85; $('#excludedInput').value = (profile.excluded_terms || []).join(', '); $('#remoteInput').checked = Boolean(profile.remote_ok);
	$('#cityInput').value = profile.city || ''; $('#englishInput').value = profile.english_level || ''; $('#salaryInput').value = profile.salary_expectation || ''; $('#availabilityInput').value = profile.availability || ''; $('#workModesInput').value = (profile.preferred_work_modes || []).join(', '); $('#contractsInput').value = (profile.preferred_contract_types || []).join(', ');
	$('#frequentAnswers').innerHTML = ''; (profile.frequent_answers || []).forEach(addFrequentAnswerRow); if (!(profile.frequent_answers || []).length) addFrequentAnswerRow();
	if (profile.target_roles?.length) { $('#keywordInput').value = profile.target_roles[0]; $('#batchKeywordInput').value = profile.target_roles[0]; }
	if (profile.preferred_locations?.length) { $('#locationInput').value = profile.preferred_locations[0]; $('#batchLocationInput').value = profile.preferred_locations[0]; }
	$('#batchScoreInput').value = profile.prepare_application_score ?? 85;
}
function collectFrequentAnswers() { return [...document.querySelectorAll('.frequent-answer-row')].map((row) => ({ question: row.querySelector('.faq-question').value.trim(), answer: row.querySelector('.faq-answer').value.trim() })).filter((item) => item.question && item.answer); }
async function saveProfile(event) {
	event.preventDefault(); const button = event.submitter; button.disabled = true; $('#profileState').textContent = 'Guardando…';
	const payload = { target_roles: splitCsv($('#rolesInput').value), skills: splitCsv($('#skillsInput').value), preferred_locations: splitCsv($('#locationsInput').value), years_experience: Number($('#experienceInput').value || 0), min_score: Number($('#minScoreInput').value || 0), prepare_application_score: Number($('#prepareScoreInput').value || 0), excluded_terms: splitCsv($('#excludedInput').value), remote_ok: $('#remoteInput').checked, city: $('#cityInput').value.trim(), english_level: $('#englishInput').value.trim(), salary_expectation: $('#salaryInput').value.trim(), availability: $('#availabilityInput').value.trim(), preferred_work_modes: splitCsv($('#workModesInput').value), preferred_contract_types: splitCsv($('#contractsInput').value), frequent_answers: collectFrequentAnswers() };
	try { const profile = await fetchJson('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); renderProfile(profile); $('#profileState').textContent = 'Guardado'; $('#profileMessage').textContent = 'Perfil actualizado. Las próximas postulaciones usarán estos datos.'; } catch (error) { $('#profileState').textContent = 'Error'; $('#profileMessage').textContent = error.message; } finally { button.disabled = false; }
}

function renderBatchStatus(status) {
	const box = $('#batchStatus'); const button = $('#batchButton'); const running = ['searching', 'applying'].includes(status.state);
	box.dataset.state = running ? 'running' : status.state || 'idle'; button.disabled = running;
	button.textContent = status.state === 'searching' ? 'Buscando…' : status.state === 'applying' ? 'Postulando…' : 'Ejecutar lote';
	const titles = { idle: 'Lote listo', searching: 'Buscando candidatos', applying: 'Auto-postulación en curso', completed: 'Lote finalizado', error: 'El lote necesita atención' };
	$('#batchStatusTitle').textContent = titles[status.state] || 'Estado del lote';
	$('#batchStatusMessage').textContent = status.current_job_title ? `${status.message} · ${status.current_job_title}` : (status.message || 'Configura el umbral y la cuota para comenzar.');
	$('#batchFound').textContent = status.found ?? 0; $('#batchEligible').textContent = status.eligible ?? 0; $('#batchAttempted').textContent = status.attempted ?? 0; $('#batchSubmitted').textContent = status.submitted ?? 0; $('#batchBlocked').textContent = status.blocked ?? 0;
}
function renderBatchHistory(items) {
	const root = $('#batchHistory');
	if (!items?.length) { root.innerHTML = '<span class="empty-chip">Sin ejecuciones todavía.</span>'; return; }
	root.innerHTML = items.map((run) => `<article class="batch-history-row"><div><strong>${escapeHtml(run.keyword)}</strong><span>${escapeHtml(run.location)} · score ≥ ${run.min_score}</span></div><div class="batch-history-stats"><span>${run.found} encontradas</span><span>${run.submitted}/${run.attempted} enviadas</span><span class="batch-state batch-${escapeHtml(run.state)}">${escapeHtml(run.state)}</span></div></article>`).join('');
}
async function loadBatchHistory() { try { renderBatchHistory(await fetchJson('/api/batch/history')); } catch (error) { console.error('Unable to load batch history', error); } }
async function pollBatchStatus() {
	try {
		const status = await fetchJson('/api/batch/status'); renderBatchStatus(status);
		if (!['searching', 'applying'].includes(status.state)) {
			if (batchPoll) clearInterval(batchPoll); batchPoll = null;
			await Promise.all([loadDashboard(), loadBatchHistory()]);
		}
	} catch (error) { console.error('Unable to poll batch status', error); }
}
async function startBatch(event) {
	event.preventDefault();
	const payload = { keyword: $('#batchKeywordInput').value.trim(), location: $('#batchLocationInput').value.trim(), max_results: Number($('#batchResultsInput').value), min_score: Number($('#batchScoreInput').value), max_applications: Number($('#batchMaxInput').value), daily_limit: Number($('#batchDailyInput').value) };
	try {
		const status = await fetchJson('/api/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
		renderBatchStatus(status); if (batchPoll) clearInterval(batchPoll); batchPoll = setInterval(pollBatchStatus, 1500);
	} catch (error) { renderBatchStatus({ state: 'error', message: error.message }); }
}

function renderDraft(draft) {
	activeDraft = draft; const questions = draft.questions || []; $('#draftBox').classList.remove('hidden');
	const outcome = draft.submitted ? '<span class="answer-state">Postulación enviada</span>' : draft.blocked_reason ? `<span class="draft-warning">${escapeHtml(draft.blocked_reason)}</span>` : '';
	const confirmation = draft.confirmation_text ? `<span>${escapeHtml(draft.confirmation_text)}</span>` : '';
	$('#draftSummary').innerHTML = `<strong>${escapeHtml(draft.summary || (draft.submitted ? 'Postulación completada' : 'Respuestas guardadas'))}</strong>${outcome}${confirmation}`;
	$('#draftQuestions').innerHTML = questions.length ? questions.map((item, index) => { const options = item.options?.length ? `<div class="draft-options">Opciones: ${item.options.map(escapeHtml).join(' · ')}</div>` : ''; return `<article class="draft-question ${item.requires_user_input ? 'needs-input' : 'ready'}" data-draft-index="${index}"><div class="question-top"><span>#${index + 1}</span><strong>${escapeHtml(item.question)}</strong><em>${escapeHtml(item.confidence)}%</em></div>${options}<label class="draft-edit-label">Respuesta utilizada<input class="draft-answer-input" value="${escapeHtml(item.suggested_answer || '')}" placeholder="Respuesta"></label><label class="draft-review-toggle"><input class="draft-needs-input" type="checkbox" ${item.requires_user_input ? 'checked' : ''}> Requiere información adicional</label>${item.note ? `<p class="draft-note">${escapeHtml(item.note)}</p>` : ''}</article>`; }).join('') : '<p class="empty-chip">No se registraron preguntas en este intento.</p>';
	$('#draftMessage').textContent = draft.submitted ? 'Las respuestas usadas en la postulación quedaron guardadas localmente.' : 'Puedes corregir y guardar estas respuestas para un próximo intento.';
}
function collectDraft() { if (!activeDraft) return null; const questions = (activeDraft.questions || []).map((item, index) => { const card = document.querySelector(`[data-draft-index="${index}"]`); return { ...item, suggested_answer: card?.querySelector('.draft-answer-input')?.value.trim() || '', requires_user_input: Boolean(card?.querySelector('.draft-needs-input')?.checked) }; }); return { ...activeDraft, questions }; }
async function saveDraft() { if (!activeJobId || !activeDraft) return; try { const saved = await fetchJson(`/api/jobs/${activeJobId}/draft`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collectDraft()) }); renderDraft(saved); $('#draftMessage').textContent = 'Respuestas guardadas localmente.'; } catch (error) { $('#draftMessage').textContent = `No se pudo guardar: ${error.message}`; } }
function setPrepareStatus(status) { const box = $('#prepareStatus'); const button = $('#prepareButton'); box.dataset.state = status.state || 'idle'; const running = status.state === 'running'; button.disabled = running; button.textContent = running && status.job_id === activeJobId ? 'Postulando…' : 'Postular automáticamente'; const titles = { idle: 'Sin intento', running: 'Postulación en ejecución', completed: status.submitted ? 'Postulación enviada' : 'Intento finalizado', error: 'La postulación necesita atención' }; $('#prepareStatusTitle').textContent = titles[status.state] || 'Estado de postulación'; $('#prepareStatusMessage').textContent = status.message || 'Puedes postularte automáticamente cuando quieras.'; }
async function loadDraft(jobId) { try { const draft = await fetchJson(`/api/jobs/${jobId}/draft`); if (activeJobId === jobId) { renderDraft(draft); setPrepareStatus({ state: 'completed', job_id: jobId, submitted: Boolean(draft.submitted), message: draft.submitted ? 'Postulación enviada y respuestas guardadas.' : (draft.blocked_reason || 'Respuestas guardadas del último intento.') }); } } catch (_) { if (activeJobId === jobId) { activeDraft = null; $('#draftBox').classList.add('hidden'); setPrepareStatus({ state: 'idle', job_id: jobId }); } } }

async function openJob(jobId) { try { const job = await fetchJson(`/api/jobs/${jobId}`); activeJobId = jobId; $('#drawerTitle').textContent = job.title; $('#drawerCompany').textContent = [job.company, job.location].filter(Boolean).join(' · '); $('#drawerScore').textContent = `${job.score}%`; $('#drawerDecision').textContent = job.status === 'applied' ? 'Postulada' : decisionLabel(job.band); $('#matchedSkills').innerHTML = chips(job.matched_skills, 'Sin coincidencias directas.'); $('#missingSkills').innerHTML = chips(job.missing_skills, 'Sin brechas configuradas.'); $('#matchReasons').innerHTML = (job.match_reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join('') || '<li>Sin razones adicionales.</li>'; $('#drawerDescription').textContent = job.description || 'Sin descripción almacenada.'; $('#drawerOpenLink').href = job.url; $('#jobDrawer').classList.add('open'); $('#drawerBackdrop').classList.add('open'); $('#jobDrawer').setAttribute('aria-hidden', 'false'); document.body.classList.add('drawer-open'); await loadDraft(jobId); } catch (error) { console.error(error); } }
function closeDrawer() { $('#jobDrawer').classList.remove('open'); $('#drawerBackdrop').classList.remove('open'); $('#jobDrawer').setAttribute('aria-hidden', 'true'); document.body.classList.remove('drawer-open'); activeJobId = null; activeDraft = null; }
async function updateJobStatus(status) { if (!activeJobId) return; await fetchJson(`/api/jobs/${activeJobId}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }); await loadDashboard(); closeDrawer(); }
async function pollPrepareStatus() { try { const status = await fetchJson('/api/prepare/status'); if (activeJobId === status.job_id) setPrepareStatus(status); if (status.state !== 'running') { if (preparePoll) clearInterval(preparePoll); preparePoll = null; if (status.job_id) await loadDraft(status.job_id); await loadDashboard(); } } catch (error) { console.error(error); } }
async function prepareApplication() { if (!activeJobId) return; const jobId = activeJobId; try { const status = await fetchJson(`/api/jobs/${jobId}/prepare`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); setPrepareStatus(status); if (preparePoll) clearInterval(preparePoll); preparePoll = setInterval(pollPrepareStatus, 1500); } catch (error) { setPrepareStatus({ state: 'error', job_id: jobId, message: error.message }); } }
function renderSearchStatus(status) { const box = $('#searchStatus'); const button = $('#searchButton'); box.dataset.state = status.state || 'idle'; button.disabled = status.state === 'running'; button.textContent = status.state === 'running' ? 'Buscando…' : 'Iniciar búsqueda'; const titles = { idle: 'Agente listo', running: 'Búsqueda en ejecución', completed: 'Búsqueda completada', error: 'La búsqueda necesita atención' }; $('#searchStatusTitle').textContent = titles[status.state] || 'Estado del agente'; $('#searchStatusMessage').textContent = status.message || 'Configura tu búsqueda y ejecútala cuando quieras.'; }
async function loadDashboard() { const query = new URLSearchParams({ min_score: String(Number($('#scoreFilter').value || 0)) }); if ($('#statusFilter').value) query.set('status', $('#statusFilter').value); try { const [stats, jobs, state] = await Promise.all([fetchJson('/api/stats'), fetchJson(`/api/jobs?${query}`), fetchJson('/api/search/status')]); renderStats(stats); renderJobs(jobs); renderSearchStatus(state); } catch (error) { console.error(error); } }
async function loadProfile() { try { renderProfile(await fetchJson('/api/profile')); } catch (error) { $('#profileMessage').textContent = error.message; } }
async function pollSearchStatus() { const status = await fetchJson('/api/search/status'); renderSearchStatus(status); if (status.state !== 'running') { if (statusPoll) clearInterval(statusPoll); statusPoll = null; await loadDashboard(); } }
async function startSearch(event) { event.preventDefault(); const payload = { keyword: $('#keywordInput').value.trim(), location: $('#locationInput').value.trim(), max_results: Number($('#maxResultsInput').value) }; try { const state = await fetchJson('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); renderSearchStatus(state); if (statusPoll) clearInterval(statusPoll); statusPoll = setInterval(pollSearchStatus, 1500); } catch (error) { renderSearchStatus({ state: 'error', message: error.message }); } }

$('#refreshButton').addEventListener('click', () => Promise.all([loadDashboard(), loadProfile(), loadBatchHistory()])); $('#focusSearchButton').addEventListener('click', () => { $('#search').scrollIntoView({ behavior: 'smooth' }); $('#keywordInput').focus(); }); $('#searchForm').addEventListener('submit', startSearch); $('#batchForm').addEventListener('submit', startBatch); $('#profileForm').addEventListener('submit', saveProfile); $('#addFrequentAnswer').addEventListener('click', () => addFrequentAnswerRow()); $('#saveDraftButton').addEventListener('click', saveDraft); $('#scoreFilter').addEventListener('change', loadDashboard); $('#statusFilter').addEventListener('change', loadDashboard); $('#drawerClose').addEventListener('click', closeDrawer); $('#drawerBackdrop').addEventListener('click', closeDrawer); $('#prepareButton').addEventListener('click', prepareApplication); document.querySelectorAll('[data-job-status]').forEach((button) => button.addEventListener('click', () => updateJobStatus(button.dataset.jobStatus))); document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawer(); });
Promise.all([loadDashboard(), loadProfile(), loadBatchHistory()]).then(async () => { const search = await fetchJson('/api/search/status').catch(() => null); if (search?.state === 'running') statusPoll = setInterval(pollSearchStatus, 1500); const prep = await fetchJson('/api/prepare/status').catch(() => null); if (prep?.state === 'running') preparePoll = setInterval(pollPrepareStatus, 1500); const batch = await fetchJson('/api/batch/status').catch(() => null); if (batch) renderBatchStatus(batch); if (batch && ['searching', 'applying'].includes(batch.state)) batchPoll = setInterval(pollBatchStatus, 1500); });
