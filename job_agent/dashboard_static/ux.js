(() => {
	const qs = (selector, root = document) => root.querySelector(selector);
	const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
	let jobViewApplying = false;
	let jobDataLoaded = false;

	function ensureToastRegion() {
		let region = qs('.toast-region');
		if (!region) {
			region = document.createElement('div');
			region.className = 'toast-region';
			region.setAttribute('aria-live', 'polite');
			region.setAttribute('aria-atomic', 'false');
			document.body.appendChild(region);
		}
		return region;
	}

	function showToast(title, message = '', tone = 'info', timeout = 3200) {
		const region = ensureToastRegion();
		const toast = document.createElement('div');
		toast.className = `ux-toast ${tone}`;
		toast.innerHTML = `<div></div><div><strong>${escapeForHtml(title)}</strong>${message ? `<span>${escapeForHtml(message)}</span>` : ''}</div><button type="button" aria-label="Cerrar notificación">×</button>`;
		toast.firstElementChild.remove();
		const close = () => {
			if (!toast.isConnected) return;
			toast.classList.add('leaving');
			setTimeout(() => toast.remove(), 190);
		};
		qs('button', toast).addEventListener('click', close);
		region.appendChild(toast);
		if (timeout > 0) setTimeout(close, timeout);
	}

	function escapeForHtml(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function injectMobileNavigation() {
		const sidebar = qs('.sidebar');
		if (!sidebar || qs('.mobile-toolbar')) return;

		const toolbar = document.createElement('header');
		toolbar.className = 'mobile-toolbar';
		toolbar.innerHTML = `
			<div class="mobile-toolbar-left">
				<button class="mobile-menu-button" id="mobileMenuButton" type="button" aria-label="Abrir navegación" aria-expanded="false"><span></span></button>
				<div class="mobile-brand"><strong>SearchJob</strong><span>Workspace local</span></div>
			</div>
			<div class="mobile-mode-pill" id="mobileModePill">PRUEBA</div>
			<button class="mobile-refresh-button" id="mobileRefreshButton" type="button" aria-label="Actualizar dashboard">↻</button>`;
		document.body.prepend(toolbar);

		const backdrop = document.createElement('div');
		backdrop.className = 'sidebar-backdrop';
		backdrop.setAttribute('aria-hidden', 'true');
		document.body.appendChild(backdrop);

		const menuButton = qs('#mobileMenuButton');
		const setOpen = (open) => {
			document.body.classList.toggle('mobile-menu-open', open);
			menuButton.setAttribute('aria-expanded', String(open));
			menuButton.setAttribute('aria-label', open ? 'Cerrar navegación' : 'Abrir navegación');
		};

		menuButton.addEventListener('click', () => setOpen(!document.body.classList.contains('mobile-menu-open')));
		backdrop.addEventListener('click', () => setOpen(false));
		qsa('.nav-item', sidebar).forEach((item) => item.addEventListener('click', () => setOpen(false)));

		qs('#mobileRefreshButton').addEventListener('click', () => {
			const button = qs('#mobileRefreshButton');
			button.classList.add('spinning');
			qs('#refreshButton')?.click();
			setTimeout(() => button.classList.remove('spinning'), 700);
		});
	}

	function setupNavigationTracking() {
		const links = qsa('.nav-item[href^="#"]');
		if (!links.length) return;
		const sections = links
			.map((link) => ({ link, section: qs(link.getAttribute('href')) }))
			.filter((item) => item.section);

		const activate = (link) => {
			links.forEach((item) => {
				const active = item === link;
				item.classList.toggle('active', active);
				if (active) item.setAttribute('aria-current', 'page');
				else item.removeAttribute('aria-current');
			});
		};

		sections.forEach(({ link }) => link.addEventListener('click', () => activate(link)));
		if (!('IntersectionObserver' in window)) return;

		const observer = new IntersectionObserver(
			(entries) => {
				const visible = entries
					.filter((entry) => entry.isIntersecting)
					.sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
				if (!visible) return;
				const match = sections.find(({ section }) => section === visible.target);
				if (match) activate(match.link);
			},
			{ rootMargin: '-18% 0px -62% 0px', threshold: [0.05, 0.2, 0.5] },
		);
		sections.forEach(({ section }) => observer.observe(section));
	}

	function enhanceJobTable() {
		const body = qs('#jobsBody');
		if (!body) return;
		const labels = ['Vacante', 'Ubicación', 'Score', 'Decisión', 'Acciones'];
		const decorate = () => {
			qsa('tr', body).forEach((row) => {
				qsa('td', row).forEach((cell, index) => cell.setAttribute('data-label', labels[index] || 'Dato'));
				if (row.dataset.uxBound) return;
				row.dataset.uxBound = '1';
				row.setAttribute('tabindex', '0');
				row.setAttribute('role', 'button');
				row.addEventListener('click', (event) => {
					if (event.target.closest('button, a, input, select, label')) return;
					qs('[data-review-job]', row)?.click();
				});
				row.addEventListener('keydown', (event) => {
					if (event.key !== 'Enter' && event.key !== ' ') return;
					event.preventDefault();
					qs('[data-review-job]', row)?.click();
				});
			});
		};
		decorate();
		new MutationObserver(decorate).observe(body, { childList: true, subtree: true });
	}

	function bindApplicationMode(select) {
		if (!select || select.dataset.uxBound) return;
		select.dataset.uxBound = '1';
		let previous = select.value;
		const panel = select.closest('.application-mode-panel');
		const mobilePill = qs('#mobileModePill');

		const paint = () => {
			panel?.setAttribute('data-mode', select.value);
			if (mobilePill) {
				mobilePill.textContent = select.value === 'real' ? 'MODO REAL' : 'PRUEBA';
				mobilePill.classList.toggle('real', select.value === 'real');
			}
			syncOperationalRail();
			syncModeAwareActions();
		};

		select.addEventListener('change', (event) => {
			if (select.value === 'real' && previous !== 'real') {
				const accepted = window.confirm(
					'Modo REAL permite enviar postulaciones automáticamente. Actívalo solo si quieres que SearchJob pueda enviar formularios en Computrabajo.',
				);
				if (!accepted) {
					select.value = previous;
					event.preventDefault();
					event.stopImmediatePropagation();
					paint();
					showToast('Modo real no activado', 'El agente continúa en modo prueba.', 'warning');
					return;
				}
				showToast('Modo real activado', 'Las acciones de postulación mostrarán una confirmación antes de ejecutarse.', 'warning', 4200);
			} else if (select.value === 'test' && previous !== 'test') {
				showToast('Modo prueba activado', 'Los formularios podrán completarse, pero no enviarse.', 'success');
			}
			previous = select.value;
			paint();
		}, true);
		paint();
	}

	function observeApplicationMode() {
		const tryBind = () => bindApplicationMode(qs('#applicationModeSelect'));
		tryBind();
		new MutationObserver(tryBind).observe(document.body, { childList: true, subtree: true });
	}

	function currentMode() {
		return qs('#applicationModeSelect')?.value || 'test';
	}

	function setupRealModeConfirmations() {
		qs('#batchForm')?.addEventListener('submit', (event) => {
			if (currentMode() !== 'real') return;
			const max = Number(qs('#batchMaxInput')?.value || 0);
			const accepted = window.confirm(
				`Vas a ejecutar un lote en modo REAL. SearchJob podrá enviar hasta ${max || 'varias'} postulaciones elegibles. ¿Continuar?`,
			);
			if (accepted) return;
			event.preventDefault();
			event.stopImmediatePropagation();
			showToast('Lote cancelado', 'No se envió ninguna postulación desde esta acción.', 'warning');
		}, true);

		qs('#prepareButton')?.addEventListener('click', (event) => {
			if (currentMode() !== 'real') return;
			const accepted = window.confirm(
				'Esta acción puede enviar una postulación real a la vacante abierta. ¿Quieres continuar?',
			);
			if (accepted) return;
			event.preventDefault();
			event.stopImmediatePropagation();
			showToast('Postulación cancelada', 'La vacante quedó sin enviar.', 'warning');
		}, true);
	}

	function observeStateElement(selector, successTitle, errorTitle) {
		const element = qs(selector);
		if (!element) return;
		let last = element.dataset.state || 'idle';
		new MutationObserver(() => {
			const state = element.dataset.state || 'idle';
			if (state === last) return;
			last = state;
			if (state === 'completed') showToast(successTitle, '', 'success');
			if (state === 'error') showToast(errorTitle, 'Revisa el detalle mostrado en el panel.', 'error', 4500);
		}).observe(element, { attributes: true, attributeFilter: ['data-state'] });
	}

	function observeProfileSave() {
		const state = qs('#profileState');
		if (!state) return;
		let last = state.textContent;
		new MutationObserver(() => {
			const value = state.textContent;
			if (value === last) return;
			last = value;
			if (value === 'Guardado') showToast('Perfil guardado', 'Los próximos scores y formularios usarán la información actualizada.', 'success');
			if (value === 'Error') showToast('No se pudo guardar el perfil', qs('#profileMessage')?.textContent || '', 'error', 4500);
			updateProfileReadiness();
		}).observe(state, { childList: true, subtree: true });
	}

	function improveAccessibility() {
		qs('#drawerClose')?.setAttribute('aria-label', 'Cerrar detalle de vacante');
		qs('#refreshButton')?.setAttribute('title', 'Actualizar métricas, vacantes y perfil');
		qs('#focusSearchButton')?.setAttribute('title', 'Ir a búsqueda manual');
		qsa('input, select').forEach((control) => {
			if (!control.autocomplete && control.type !== 'checkbox') control.setAttribute('autocomplete', 'off');
		});
	}

	function setupKeyboardNavigation() {
		document.addEventListener('keydown', (event) => {
			if (event.key === 'Escape' && document.body.classList.contains('mobile-menu-open')) {
				document.body.classList.remove('mobile-menu-open');
				qs('#mobileMenuButton')?.setAttribute('aria-expanded', 'false');
			}
			if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey) {
				const active = document.activeElement;
				if (active?.matches('input, textarea, select, [contenteditable="true"]')) return;
				event.preventDefault();
				qs('#search')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
				setTimeout(() => qs('#keywordInput')?.focus(), 250);
			}
		});
	}

	function injectRefinementStyles() {
		if (qs('#uxRefinementStyles')) return;
		const style = document.createElement('style');
		style.id = 'uxRefinementStyles';
		style.textContent = `
			.ux-system-rail{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:-4px 0 18px;padding:8px;border:1px solid var(--line);border-radius:15px;background:rgba(7,11,20,.46);box-shadow:var(--shadow-soft)}
			.ux-system-item{display:flex;align-items:center;gap:10px;min-width:0;padding:10px 12px;border:1px solid transparent;border-radius:11px;background:rgba(255,255,255,.018)}
			.ux-system-dot{width:7px;height:7px;flex:0 0 7px;border-radius:50%;background:var(--success);box-shadow:0 0 0 4px rgba(98,214,161,.07)}
			.ux-system-dot.warning{background:var(--warning);box-shadow:0 0 0 4px rgba(244,200,106,.07)}
			.ux-system-dot.danger{background:var(--danger);box-shadow:0 0 0 4px rgba(251,142,154,.08)}
			.ux-system-copy{min-width:0}.ux-system-copy span,.ux-system-copy strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ux-system-copy span{color:#637087;font-size:8px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.ux-system-copy strong{margin-top:2px;color:#dfe7f4;font-size:11px}
			body.ux-real-mode .ux-system-rail{border-color:rgba(251,142,154,.22);box-shadow:0 12px 35px rgba(65,20,28,.16)}
			.ux-jobs-toolbar{display:grid;grid-template-columns:minmax(220px,1.5fr) minmax(170px,.7fr) auto auto;align-items:end;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line);background:rgba(4,9,18,.24)}
			.ux-jobs-toolbar label{display:grid;gap:6px;color:#69778e;font-size:8px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.ux-jobs-toolbar input,.ux-jobs-toolbar select{width:100%;min-height:39px;padding:9px 11px;border:1px solid var(--line);border-radius:10px;color:#edf3fb;background:rgba(4,9,18,.62);outline:none}.ux-jobs-toolbar input:focus,.ux-jobs-toolbar select:focus{border-color:rgba(142,168,255,.58);box-shadow:0 0 0 3px rgba(142,168,255,.09)}
			.ux-job-summary{align-self:center;justify-self:end;color:#7c899f;font-size:10px;white-space:nowrap}.ux-job-summary strong{color:#eef3fb;font-size:12px}
			.ux-filtered-empty{margin:14px 18px 18px;padding:20px;border:1px dashed var(--line-strong);border-radius:12px;color:#8190a6;text-align:center;background:rgba(255,255,255,.012)}
			.job-row.ux-filtered{display:none!important}
			.ux-profile-readiness{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,.45fr);align-items:center;gap:20px;margin:18px 0 -2px;padding:15px 16px;border:1px solid rgba(142,168,255,.13);border-radius:14px;background:linear-gradient(120deg,rgba(142,168,255,.055),rgba(255,255,255,.015))}
			.ux-profile-readiness-copy span{display:block;color:#73819a;font-size:8px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.ux-profile-readiness-copy strong{display:block;margin:4px 0 3px;color:#edf3fb;font-size:13px}.ux-profile-readiness-copy p{margin:0;color:#75839a;font-size:10px;line-height:1.45}
			.ux-readiness-meter{display:grid;gap:7px}.ux-readiness-track{height:7px;overflow:hidden;border-radius:999px;background:rgba(148,163,184,.1)}.ux-readiness-fill{height:100%;width:0;border-radius:inherit;background:linear-gradient(90deg,var(--primary),var(--success));transition:width .2s ease}.ux-readiness-meta{display:flex;justify-content:space-between;color:#6b7890;font-size:9px}.ux-readiness-meta strong{color:#cfd9e9}
			.ux-action-hint{display:block;margin:8px 0 0;color:#718097;font-size:10px;line-height:1.45}.ux-action-hint.safe{color:#78cda3}.ux-action-hint.real{color:#e7a0a9}.prepare-button.ux-test-action{color:#bcebd3;border:1px solid rgba(98,214,161,.22);background:rgba(98,214,161,.08);box-shadow:none}.prepare-button.ux-test-action:hover:not(:disabled){background:rgba(98,214,161,.12);box-shadow:none}
			body.ux-dashboard-loading .metric-card strong{opacity:.35;animation:ux-pulse 1s ease-in-out infinite alternate}.ux-dashboard-loading .ux-job-summary{opacity:.55}@keyframes ux-pulse{to{opacity:.8}}
			@media(max-width:1100px){.ux-system-rail{grid-template-columns:repeat(2,minmax(0,1fr))}.ux-jobs-toolbar{grid-template-columns:minmax(0,1fr) minmax(160px,.7fr);}.ux-job-summary{justify-self:start}.ux-jobs-toolbar .ux-clear-filters{justify-self:end}}
			@media(max-width:700px){.ux-system-rail{grid-template-columns:1fr 1fr;margin-top:0}.ux-system-item{padding:9px}.ux-jobs-toolbar{grid-template-columns:1fr;padding:13px}.ux-jobs-toolbar .ux-clear-filters{justify-self:stretch;width:100%}.ux-job-summary{justify-self:start}.ux-profile-readiness{grid-template-columns:1fr;gap:12px;margin-top:14px}.ux-filtered-empty{margin:10px}}
			@media(max-width:430px){.ux-system-rail{grid-template-columns:1fr}.ux-system-item:nth-child(1),.ux-system-item:nth-child(2){display:none}}
		`;
		document.head.appendChild(style);
	}

	function injectOperationalRail() {
		if (qs('#uxSystemRail')) return;
		const topbar = qs('.topbar');
		if (!topbar) return;
		const rail = document.createElement('section');
		rail.id = 'uxSystemRail';
		rail.className = 'ux-system-rail';
		rail.setAttribute('aria-label', 'Estado operativo de SearchJob');
		rail.innerHTML = `
			<div class="ux-system-item"><span class="ux-system-dot"></span><div class="ux-system-copy"><span>Datos</span><strong>Local · este PC</strong></div></div>
			<div class="ux-system-item"><span class="ux-system-dot"></span><div class="ux-system-copy"><span>Costo</span><strong>Zero-cost por defecto</strong></div></div>
			<div class="ux-system-item"><span class="ux-system-dot warning" id="uxAutomationDot"></span><div class="ux-system-copy"><span>Automatización</span><strong id="uxAutomationState">Comprobando…</strong></div></div>
			<div class="ux-system-item"><span class="ux-system-dot warning" id="uxModeDot"></span><div class="ux-system-copy"><span>Postulación</span><strong id="uxModeState">Comprobando…</strong></div></div>`;
		topbar.after(rail);
		syncOperationalRail();
	}

	function syncOperationalRail() {
		const modeSelect = qs('#applicationModeSelect');
		const mode = modeSelect?.value;
		const modeState = qs('#uxModeState');
		const modeDot = qs('#uxModeDot');
		if (modeState) modeState.textContent = mode ? (mode === 'real' ? 'REAL · puede enviar' : 'PRUEBA · no envía') : 'Comprobando…';
		if (modeDot) {
			modeDot.classList.toggle('danger', mode === 'real');
			modeDot.classList.toggle('warning', !mode || mode === 'test');
		}
		document.body.classList.toggle('ux-real-mode', mode === 'real');

		const automation = window.jobAgentAutomationEnabled;
		const automationState = qs('#uxAutomationState');
		const automationDot = qs('#uxAutomationDot');
		if (automationState) automationState.textContent = automation === undefined ? 'Comprobando…' : automation ? 'Activa' : 'Pausada · solo búsqueda';
		if (automationDot) {
			automationDot.classList.toggle('warning', automation === undefined || automation === false);
			automationDot.classList.toggle('danger', false);
		}
	}

	function injectJobViewControls() {
		if (qs('#uxJobControls')) return;
		const panel = qs('#jobs');
		const header = qs('.panel-header', panel);
		if (!panel || !header) return;
		const controls = document.createElement('div');
		controls.id = 'uxJobControls';
		controls.className = 'ux-jobs-toolbar';
		controls.innerHTML = `
			<label>Buscar en resultados<input id="jobTextFilter" type="search" placeholder="Cargo, empresa o ubicación" autocomplete="off"></label>
			<label>Ordenar<select id="jobSortSelect"><option value="score-desc">Mejor score primero</option><option value="score-asc">Menor score primero</option><option value="title-asc">Cargo A–Z</option><option value="company-asc">Empresa A–Z</option></select></label>
			<button class="button secondary ux-clear-filters" id="clearJobFilters" type="button">Limpiar filtros</button>
			<div class="ux-job-summary" id="uxJobVisibleSummary" aria-live="polite">Cargando vacantes…</div>`;
		header.after(controls);
		const filteredEmpty = document.createElement('div');
		filteredEmpty.id = 'uxFilteredEmpty';
		filteredEmpty.className = 'ux-filtered-empty';
		filteredEmpty.hidden = true;
		filteredEmpty.textContent = 'No hay vacantes que coincidan con este texto. Prueba otro término o limpia los filtros.';
		qs('.table-wrap', panel)?.after(filteredEmpty);
	}

	function jobRowData(row) {
		return {
			title: qs('.job-title', row)?.textContent?.trim() || '',
			company: qs('.job-company', row)?.textContent?.trim() || '',
			location: qsa('td', row)[1]?.textContent?.trim() || '',
			score: Number((qs('.score', row)?.textContent || '0').replace(/[^0-9.-]/g, '')) || 0,
		};
	}

	function applyJobViewControls() {
		const body = qs('#jobsBody');
		if (!body || jobViewApplying) return;
		jobViewApplying = true;
		const rows = qsa('tr.job-row', body);
		const term = (qs('#jobTextFilter')?.value || '').trim().toLocaleLowerCase('es');
		const sort = qs('#jobSortSelect')?.value || 'score-desc';
		const decorated = rows.map((row, index) => ({ row, index, data: jobRowData(row) }));
		decorated.sort((a, b) => {
			if (sort === 'score-asc') return a.data.score - b.data.score || a.index - b.index;
			if (sort === 'title-asc') return a.data.title.localeCompare(b.data.title, 'es', { sensitivity: 'base' }) || a.index - b.index;
			if (sort === 'company-asc') return a.data.company.localeCompare(b.data.company, 'es', { sensitivity: 'base' }) || a.index - b.index;
			return b.data.score - a.data.score || a.index - b.index;
		});
		const fragment = document.createDocumentFragment();
		let visible = 0;
		decorated.forEach(({ row, data }) => {
			const haystack = `${data.title} ${data.company} ${data.location}`.toLocaleLowerCase('es');
			const matches = !term || haystack.includes(term);
			row.classList.toggle('ux-filtered', !matches);
			if (matches) visible += 1;
			fragment.appendChild(row);
		});
		body.appendChild(fragment);
		const summary = qs('#uxJobVisibleSummary');
		if (summary) {
			if (!jobDataLoaded) summary.textContent = 'Cargando vacantes…';
			else summary.innerHTML = `<strong>${visible}</strong> de ${rows.length} visibles`;
		}
		const filteredEmpty = qs('#uxFilteredEmpty');
		if (filteredEmpty) filteredEmpty.hidden = !jobDataLoaded || rows.length === 0 || visible > 0;
		setTimeout(() => { jobViewApplying = false; }, 0);
	}

	function setupJobViewControls() {
		injectJobViewControls();
		qs('#jobTextFilter')?.addEventListener('input', applyJobViewControls);
		qs('#jobSortSelect')?.addEventListener('change', applyJobViewControls);
		qs('#clearJobFilters')?.addEventListener('click', () => {
			const text = qs('#jobTextFilter');
			const sort = qs('#jobSortSelect');
			const score = qs('#scoreFilter');
			const status = qs('#statusFilter');
			if (text) text.value = '';
			if (sort) sort.value = 'score-desc';
			if (score) score.value = '0';
			if (status) status.value = '';
			applyJobViewControls();
			score?.dispatchEvent(new Event('change', { bubbles: true }));
		});
		const body = qs('#jobsBody');
		if (body) {
			new MutationObserver(() => {
				if (jobViewApplying) return;
				jobDataLoaded = true;
				applyJobViewControls();
			}).observe(body, { childList: true });
		}
		applyJobViewControls();
	}

	function injectProfileReadiness() {
		if (qs('#uxProfileReadiness')) return;
		const panel = qs('#profile');
		const heading = qs('.section-heading', panel);
		if (!panel || !heading) return;
		const readiness = document.createElement('div');
		readiness.id = 'uxProfileReadiness';
		readiness.className = 'ux-profile-readiness';
		readiness.innerHTML = `
			<div class="ux-profile-readiness-copy"><span>Preparación para pruebas</span><strong id="uxReadinessTitle">Revisando tu perfil…</strong><p id="uxReadinessDetail">Comprobando los datos que suelen aparecer en formularios.</p></div>
			<div class="ux-readiness-meter"><div class="ux-readiness-track" role="progressbar" aria-label="Completitud del perfil" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="ux-readiness-fill" id="uxReadinessFill"></div></div><div class="ux-readiness-meta"><span id="uxReadinessCount">0/8 datos</span><strong id="uxReadinessPercent">0%</strong></div></div>`;
		heading.after(readiness);
	}

	function updateProfileReadiness() {
		if (!qs('#uxProfileReadiness')) return;
		const checks = [
			['Cargos objetivo', Boolean(qs('#rolesInput')?.value.trim())],
			['Skills', Boolean(qs('#skillsInput')?.value.trim())],
			['Ciudad', Boolean(qs('#cityInput')?.value.trim())],
			['Nivel de inglés', Boolean(qs('#englishInput')?.value.trim())],
			['Pretensión salarial', Boolean(qs('#salaryInput')?.value.trim())],
			['Disponibilidad', Boolean(qs('#availabilityInput')?.value.trim())],
			['Ubicaciones', Boolean(qs('#locationsInput')?.value.trim())],
			['Experiencia', Number(qs('#experienceInput')?.value || 0) > 0],
		];
		const complete = checks.filter(([, ok]) => ok).length;
		const missing = checks.filter(([, ok]) => !ok).map(([label]) => label);
		const percent = Math.round((complete / checks.length) * 100);
		const title = qs('#uxReadinessTitle');
		const detail = qs('#uxReadinessDetail');
		const fill = qs('#uxReadinessFill');
		const count = qs('#uxReadinessCount');
		const percentLabel = qs('#uxReadinessPercent');
		const track = qs('.ux-readiness-track');
		if (title) title.textContent = complete === checks.length ? 'Perfil listo para probar formularios' : complete >= 6 ? 'Casi listo para las pruebas' : 'Completa tu perfil antes de probar';
		if (detail) {
			if (!missing.length) detail.textContent = 'Los datos básicos para resolver formularios están completos. Las preguntas específicas seguirán fallando de forma segura si no hay respuesta.';
			else {
				const visible = missing.slice(0, 3).join(', ');
				const rest = missing.length > 3 ? ` y ${missing.length - 3} más` : '';
				detail.textContent = `Falta completar: ${visible}${rest}.`;
			}
		}
		if (fill) fill.style.width = `${percent}%`;
		if (count) count.textContent = `${complete}/${checks.length} datos`;
		if (percentLabel) percentLabel.textContent = `${percent}%`;
		track?.setAttribute('aria-valuenow', String(percent));
	}

	function setupProfileReadiness() {
		injectProfileReadiness();
		const form = qs('#profileForm');
		form?.addEventListener('input', updateProfileReadiness);
		form?.addEventListener('change', updateProfileReadiness);
		[0, 450, 1200, 2600].forEach((delay) => setTimeout(updateProfileReadiness, delay));
	}

	function syncModeAwareActions() {
		const mode = currentMode();
		const prepareButton = qs('#prepareButton');
		const prepareState = qs('#prepareStatus')?.dataset.state || 'idle';
		if (prepareButton) {
			prepareButton.classList.toggle('ux-test-action', mode === 'test');
			if (prepareState === 'running') prepareButton.textContent = mode === 'real' ? 'Postulando…' : 'Probando formulario…';
			else prepareButton.textContent = mode === 'real' ? 'Postular automáticamente' : 'Probar formulario sin enviar';
		}
		const applicationCopy = qs('.application-section .application-heading p');
		if (applicationCopy) applicationCopy.textContent = mode === 'real'
			? 'Completa el formulario y puede enviar la postulación usando exclusivamente tu perfil y respuestas guardadas.'
			: 'Completa el formulario con tus datos locales y se detiene antes de cualquier envío final.';
		const applicationPill = qs('.application-section .safe-pill');
		if (applicationPill) applicationPill.textContent = mode === 'real' ? 'AUTO APPLY · REAL' : 'PRUEBA SEGURA';
		let prepareHint = qs('#uxPrepareHint');
		if (!prepareHint && prepareButton) {
			prepareHint = document.createElement('span');
			prepareHint.id = 'uxPrepareHint';
			prepareHint.className = 'ux-action-hint';
			prepareButton.after(prepareHint);
		}
		if (prepareHint) {
			prepareHint.className = `ux-action-hint ${mode === 'real' ? 'real' : 'safe'}`;
			prepareHint.textContent = mode === 'real' ? 'Modo real: esta acción puede enviar el formulario después de la confirmación.' : 'Modo prueba: no hará clic en la acción final de envío.';
		}

		const batchButton = qs('#batchButton');
		const batchState = qs('#batchStatus')?.dataset.state || 'idle';
		if (batchButton) {
			if (['searching', 'applying', 'running'].includes(batchState)) batchButton.textContent = mode === 'real' ? 'Ejecutando lote…' : 'Probando lote…';
			else batchButton.textContent = mode === 'real' ? 'Ejecutar mi lote' : 'Ejecutar lote en prueba';
		}
		let batchHint = qs('#uxBatchHint');
		if (!batchHint && batchButton) {
			batchHint = document.createElement('span');
			batchHint.id = 'uxBatchHint';
			batchHint.className = 'ux-action-hint';
			batchButton.after(batchHint);
		}
		if (batchHint) {
			batchHint.className = `ux-action-hint ${mode === 'real' ? 'real' : 'safe'}`;
			batchHint.textContent = mode === 'real' ? 'Puede enviar postulaciones elegibles hasta los límites configurados.' : 'Recorrerá el flujo de aplicación sin enviar postulaciones finales.';
		}
	}

	function setupModeAwareActions() {
		const prepareStatus = qs('#prepareStatus');
		const batchStatus = qs('#batchStatus');
		if (prepareStatus) new MutationObserver(syncModeAwareActions).observe(prepareStatus, { attributes: true, attributeFilter: ['data-state'] });
		if (batchStatus) new MutationObserver(syncModeAwareActions).observe(batchStatus, { attributes: true, attributeFilter: ['data-state'] });
		syncModeAwareActions();
	}

	function setupDashboardLoading() {
		document.body.classList.add('ux-dashboard-loading');
		const metric = qs('#totalMetric');
		if (!metric) return;
		const finish = () => {
			jobDataLoaded = true;
			document.body.classList.remove('ux-dashboard-loading');
			applyJobViewControls();
		};
		const observer = new MutationObserver(() => {
			observer.disconnect();
			finish();
		});
		observer.observe(metric, { childList: true, characterData: true, subtree: true });
		setTimeout(() => {
			observer.disconnect();
			finish();
		}, 3000);
	}

	injectRefinementStyles();
	injectMobileNavigation();
	setupNavigationTracking();
	enhanceJobTable();
	injectOperationalRail();
	setupJobViewControls();
	setupProfileReadiness();
	observeApplicationMode();
	setupModeAwareActions();
	setupRealModeConfirmations();
	observeStateElement('#searchStatus', 'Búsqueda completada', 'La búsqueda necesita atención');
	observeStateElement('#batchStatus', 'Lote finalizado', 'El lote necesita atención');
	observeStateElement('#prepareStatus', 'Intento de postulación finalizado', 'La postulación necesita atención');
	observeProfileSave();
	improveAccessibility();
	setupKeyboardNavigation();
	setupDashboardLoading();
	document.addEventListener('job-agent-automation-state', syncOperationalRail);
})();
