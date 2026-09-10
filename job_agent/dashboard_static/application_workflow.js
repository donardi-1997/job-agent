(() => {
	const state = {
		jobId: null,
		poll: null,
		attempts: [],
	};

	function esc(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function normalize(value) {
		return String(value || '')
			.normalize('NFD')
			.replace(/[\u0300-\u036f]/g, '')
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, ' ')
			.trim();
	}

	async function json(url, options) {
		const response = await window.fetch(url, options);
		const payload = await response.json().catch(() => ({}));
		if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
		return payload;
	}

	function ensureStyles() {
		if (document.querySelector('#applicationWorkflowStyles')) return;
		const style = document.createElement('style');
		style.id = 'applicationWorkflowStyles';
		style.textContent = `
			.application-actions-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.real-apply-button{background:linear-gradient(135deg,#69d08f,#45b877)!important;color:#07120b!important;border-color:transparent!important;font-weight:850}.application-action-note{margin:9px 0 0;color:#7e8ba5;font-size:10px;line-height:1.5}
			.application-qa-history{margin-top:16px;padding:16px;border:1px solid rgba(139,165,255,.12);border-radius:14px;background:rgba(5,10,22,.32)}.qa-history-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}.qa-history-head h3{margin:0 0 4px;color:#dfe6f5;font-size:13px}.qa-history-head p{margin:0;color:#78859e;font-size:10px;line-height:1.5}.qa-history-count{padding:5px 8px;border-radius:999px;background:rgba(139,165,255,.08);color:#9badff;font-size:10px;font-weight:800}
			.qa-attempts{display:grid;gap:10px}.qa-attempt{padding:12px;border:1px solid rgba(255,255,255,.065);border-radius:11px;background:rgba(3,8,18,.38)}.qa-attempt-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}.qa-attempt-meta{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.qa-mode,.qa-state{display:inline-flex;padding:4px 7px;border-radius:7px;font-size:9px;font-weight:850;letter-spacing:.05em}.qa-mode-test{color:#f0c96e;background:rgba(240,201,110,.08)}.qa-mode-real{color:#8ce0aa;background:rgba(104,211,145,.08)}.qa-state{color:#8e9bb5;background:rgba(255,255,255,.05)}.qa-attempt-date{color:#68758e;font-size:9px}.qa-question-list{display:grid;gap:8px}.qa-question{padding:10px;border-radius:9px;background:rgba(255,255,255,.025)}.qa-question strong{display:block;color:#cfd8ea;font-size:10px;line-height:1.45}.qa-future-row{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:7px}.qa-future-row input{min-width:0;padding:9px 10px;color:#e4eaf6;background:rgba(7,12,25,.72);border:1px solid rgba(255,255,255,.08);border-radius:8px;outline:none}.qa-future-row input:focus{border-color:rgba(139,165,255,.45)}.qa-save-future{padding:8px 10px!important;white-space:nowrap}.qa-note{margin-top:5px;color:#6f7c94;font-size:9px}.qa-empty{padding:16px;text-align:center;color:#77849e;font-size:10px}.future-answer-hint{margin:10px 0 0;padding:9px 10px;border-radius:9px;background:rgba(139,165,255,.045);color:#8290aa;font-size:10px;line-height:1.5}
			@media(max-width:620px){.application-actions-grid{grid-template-columns:1fr}.qa-attempt-head{align-items:flex-start;flex-direction:column}.qa-future-row{grid-template-columns:1fr}.qa-save-future{width:100%}}
		`;
		document.head.appendChild(style);
	}

	function updateModeUi(mode) {
		const select = document.querySelector('#applicationModeSelect');
		if (select) select.value = mode;
		const warning = document.querySelector('#applicationModeWarning');
		if (warning) {
			warning.textContent = mode === 'real'
				? 'Modo real activo. Las postulaciones pueden enviarse automáticamente.'
				: 'Modo prueba activo. Los formularios pueden completarse, pero Job Agent no enviará ninguna postulación.';
		}
	}

	async function setMode(mode) {
		await json('/api/application/mode', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ mode }),
		});
		updateModeUi(mode);
	}

	function setButtonsRunning(running, mode = '') {
		const testButton = document.querySelector('#prepareButton');
		const realButton = document.querySelector('#realApplyButton');
		if (testButton) {
			testButton.disabled = running;
			testButton.textContent = running && mode === 'test' ? 'Probando formulario…' : 'Probar formulario (TEST)';
		}
		if (realButton) {
			realButton.disabled = running;
			realButton.textContent = running && mode === 'real' ? 'Postulando…' : 'Postular ahora (REAL)';
		}
	}

	async function runApplication(mode) {
		if (!state.jobId) return;
		setButtonsRunning(true, mode);
		try {
			await setMode(mode);
			const status = await json(`/api/jobs/${state.jobId}/prepare`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: '{}',
			});
			if (typeof window.setPrepareStatus === 'function') window.setPrepareStatus(status);
			if (state.poll) clearInterval(state.poll);
			state.poll = setInterval(async () => {
				try {
					const current = await json('/api/prepare/status');
					if (typeof window.setPrepareStatus === 'function' && current.job_id === state.jobId) {
						window.setPrepareStatus(current);
					}
					if (current.state !== 'running') {
						clearInterval(state.poll);
						state.poll = null;
						setButtonsRunning(false);
						if (typeof window.loadDraft === 'function' && current.job_id) await window.loadDraft(current.job_id);
						if (typeof window.loadDashboard === 'function') await window.loadDashboard();
						await loadAttempts(state.jobId);
					}
				} catch (error) {
					clearInterval(state.poll);
					state.poll = null;
					setButtonsRunning(false);
					if (typeof window.setPrepareStatus === 'function') {
						window.setPrepareStatus({ state: 'error', job_id: state.jobId, message: error.message });
					}
				}
			}, 1200);
		} catch (error) {
			setButtonsRunning(false);
			if (typeof window.setPrepareStatus === 'function') {
				window.setPrepareStatus({ state: 'error', job_id: state.jobId, message: error.message });
			}
		}
	}

	function enhanceApplicationActions() {
		const button = document.querySelector('#prepareButton');
		if (!button || document.querySelector('#realApplyButton')) return;
		button.textContent = 'Probar formulario (TEST)';
		button.classList.add('test-apply-button');
		button.addEventListener('click', (event) => {
			event.preventDefault();
			event.stopImmediatePropagation();
			runApplication('test');
		}, true);

		const grid = document.createElement('div');
		grid.className = 'application-actions-grid';
		button.parentNode.insertBefore(grid, button);
		grid.appendChild(button);
		const real = document.createElement('button');
		real.id = 'realApplyButton';
		real.type = 'button';
		real.className = 'button primary real-apply-button';
		real.textContent = 'Postular ahora (REAL)';
		real.addEventListener('click', () => runApplication('real'));
		grid.appendChild(real);

		const note = document.createElement('p');
		note.className = 'application-action-note';
		note.textContent = 'TEST completa sin enviar. REAL reutiliza tu perfil, borrador y memoria aprendida y envía solo cuando Computrabajo confirma el flujo.';
		grid.insertAdjacentElement('afterend', note);
	}

	function enhanceDraftEditor() {
		const save = document.querySelector('#saveDraftButton');
		if (save) save.textContent = 'Guardar ajustes para futuras vacantes';
		for (const label of document.querySelectorAll('.draft-edit-label')) {
			if (label.dataset.futureLabel === '1') continue;
			label.dataset.futureLabel = '1';
			for (const node of label.childNodes) {
				if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
					node.textContent = 'Respuesta / ajuste para próximas vacantes';
					break;
				}
			}
		}
		const box = document.querySelector('#draftBox');
		if (box && !box.querySelector('.future-answer-hint')) {
			const hint = document.createElement('div');
			hint.className = 'future-answer-hint';
			hint.textContent = 'Al editar una respuesta y guardar, se convierte en un ajuste manual prioritario para preguntas equivalentes de futuras vacantes.';
			box.querySelector('.profile-actions')?.insertAdjacentElement('beforebegin', hint);
		}
	}

	function mountHistory() {
		if (document.querySelector('#applicationQaHistory')) return;
		const applicationSection = document.querySelector('.application-section');
		if (!applicationSection) return;
		const section = document.createElement('section');
		section.id = 'applicationQaHistory';
		section.className = 'application-qa-history';
		section.innerHTML = `
			<div class="qa-history-head">
				<div><h3>Preguntas y respuestas de esta vacante</h3><p>Cada intento se conserva por separado. Puedes corregir cualquier respuesta y guardarla como regla para futuras vacantes.</p></div>
				<span class="qa-history-count" id="qaHistoryCount">0 intentos</span>
			</div>
			<div class="qa-attempts" id="qaAttempts"><div class="qa-empty">Abre una vacante para ver su historial.</div></div>`;
		applicationSection.insertAdjacentElement('afterend', section);
	}

	function formatDate(value) {
		if (!value) return '';
		const normalized = String(value).includes('T') ? String(value) : `${String(value).replace(' ', 'T')}Z`;
		const date = new Date(normalized);
		if (Number.isNaN(date.getTime())) return String(value);
		return new Intl.DateTimeFormat('es-CO', {
			dateStyle: 'medium',
			timeStyle: 'short',
			timeZone: 'America/Bogota',
		}).format(date);
	}

	function attemptLabel(attempt) {
		const payload = attempt?.payload || {};
		if (attempt?.submitted) return payload.submission_status === 'already_applied' ? 'Ya estaba postulada' : 'Enviada';
		if (payload.submission_status === 'test_ready') return 'Lista para enviar';
		if (payload.submission_status === 'test_incomplete') return 'Prueba incompleta';
		return payload.blocked_reason ? 'Requiere atención' : 'No enviada';
	}

	async function getDraftOrFallback(fallbackPayload) {
		try {
			return await json(`/api/jobs/${state.jobId}/draft`);
		} catch (_) {
			return { ...(fallbackPayload || {}), questions: [...(fallbackPayload?.questions || [])] };
		}
	}

	async function saveFutureAnswer(question, answer, fallbackPayload, button) {
		const cleanAnswer = String(answer || '').trim();
		if (!question || !cleanAnswer || !state.jobId) return;
		const originalText = button.textContent;
		button.disabled = true;
		button.textContent = 'Guardando…';
		try {
			const draft = await getDraftOrFallback(fallbackPayload);
			const questions = Array.isArray(draft.questions) ? [...draft.questions] : [];
			const target = normalize(question);
			let found = false;
			for (let i = 0; i < questions.length; i += 1) {
				if (normalize(questions[i]?.question) !== target) continue;
				questions[i] = {
					...questions[i],
					suggested_answer: cleanAnswer,
					confidence: 100,
					requires_user_input: false,
					note: 'Ajuste manual guardado para futuras vacantes.',
				};
				found = true;
				break;
			}
			if (!found) {
				questions.push({
					question,
					field_type: 'text',
					options: [],
					suggested_answer: cleanAnswer,
					confidence: 100,
					requires_user_input: false,
					note: 'Ajuste manual guardado para futuras vacantes.',
				});
			}
			const payload = {
				...draft,
				questions,
				mode: draft.mode === 'real' ? 'real' : 'test',
				test_mode: draft.mode === 'real' ? false : true,
			};
			await json(`/api/jobs/${state.jobId}/draft`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			button.textContent = 'Guardada ✓';
			if (typeof window.loadDraft === 'function') await window.loadDraft(state.jobId);
			setTimeout(() => { button.textContent = originalText; button.disabled = false; }, 1200);
		} catch (error) {
			button.textContent = 'Error';
			button.title = error.message;
			setTimeout(() => { button.textContent = originalText; button.disabled = false; }, 1800);
		}
	}

	function renderAttempts(items) {
		state.attempts = Array.isArray(items) ? items : [];
		const root = document.querySelector('#qaAttempts');
		const count = document.querySelector('#qaHistoryCount');
		if (!root || !count) return;
		count.textContent = `${state.attempts.length} intento${state.attempts.length === 1 ? '' : 's'}`;
		if (!state.attempts.length) {
			root.innerHTML = '<div class="qa-empty">Todavía no hay intentos para esta vacante. Usa TEST para inspeccionarla o REAL para postular.</div>';
			return;
		}
		root.innerHTML = state.attempts.map((attempt, attemptIndex) => {
			const payload = attempt.payload || {};
			const mode = payload.mode === 'real' ? 'real' : 'test';
			const questions = Array.isArray(payload.questions) ? payload.questions : [];
			const qHtml = questions.length ? questions.map((item, questionIndex) => `
				<div class="qa-question">
					<strong>${esc(item.question || 'Pregunta')}</strong>
					<div class="qa-future-row">
						<input data-qa-answer="${attemptIndex}:${questionIndex}" value="${esc(item.suggested_answer || '')}" placeholder="Respuesta">
						<button class="button secondary qa-save-future" type="button" data-qa-save="${attemptIndex}:${questionIndex}">Guardar para futuras</button>
					</div>
					${item.note ? `<div class="qa-note">${esc(item.note)}</div>` : ''}
				</div>`).join('') : '<div class="qa-empty">Este intento no registró preguntas.</div>';
			return `<article class="qa-attempt">
				<div class="qa-attempt-head"><div class="qa-attempt-meta"><span class="qa-mode qa-mode-${mode}">${mode.toUpperCase()}</span><span class="qa-state">${esc(attemptLabel(attempt))}</span></div><span class="qa-attempt-date">${esc(formatDate(attempt.created_at))}</span></div>
				<div class="qa-question-list">${qHtml}</div>
			</article>`;
		}).join('');

		root.querySelectorAll('[data-qa-save]').forEach((button) => {
			button.addEventListener('click', async () => {
				const [attemptIndex, questionIndex] = String(button.dataset.qaSave || '').split(':').map(Number);
				const attempt = state.attempts[attemptIndex];
				const item = attempt?.payload?.questions?.[questionIndex];
				const input = root.querySelector(`[data-qa-answer="${attemptIndex}:${questionIndex}"]`);
				if (!item || !input) return;
				await saveFutureAnswer(item.question, input.value, attempt.payload, button);
			});
		});
	}

	async function loadAttempts(jobId) {
		if (!jobId) return;
		try {
			renderAttempts(await json(`/api/jobs/${jobId}/attempts`));
		} catch (error) {
			const root = document.querySelector('#qaAttempts');
			if (root) root.innerHTML = `<div class="qa-empty">No se pudo cargar el historial: ${esc(error.message)}</div>`;
		}
	}

	function trackJob(jobId) {
		if (!Number.isFinite(jobId) || jobId <= 0) return;
		state.jobId = jobId;
		setTimeout(() => {
			loadAttempts(jobId);
			enhanceDraftEditor();
		}, 80);
	}

	function mount() {
		ensureStyles();
		mountHistory();
		enhanceApplicationActions();
		enhanceDraftEditor();

		document.addEventListener('click', (event) => {
			const target = event.target?.closest?.('[data-review-job]');
			if (target) trackJob(Number(target.dataset.reviewJob));
		}, true);

		const originalOpenJob = window.openJob;
		if (typeof originalOpenJob === 'function' && !originalOpenJob.__qaWrapped) {
			const wrapped = async function(jobId) {
				trackJob(Number(jobId));
				const result = await originalOpenJob(jobId);
				await loadAttempts(Number(jobId));
				enhanceDraftEditor();
				return result;
			};
			wrapped.__qaWrapped = true;
			window.openJob = wrapped;
		}

		const draftRoot = document.querySelector('#draftQuestions');
		if (draftRoot) {
			new MutationObserver(() => enhanceDraftEditor()).observe(draftRoot, { childList: true, subtree: true });
		}
	}

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
