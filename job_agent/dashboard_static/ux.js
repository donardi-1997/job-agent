(() => {
	const qs = (selector, root = document) => root.querySelector(selector);
	const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

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

	injectMobileNavigation();
	setupNavigationTracking();
	enhanceJobTable();
	observeApplicationMode();
	setupRealModeConfirmations();
	observeStateElement('#searchStatus', 'Búsqueda completada', 'La búsqueda necesita atención');
	observeStateElement('#batchStatus', 'Lote finalizado', 'El lote necesita atención');
	observeStateElement('#prepareStatus', 'Intento de postulación finalizado', 'La postulación necesita atención');
	observeProfileSave();
	improveAccessibility();
	setupKeyboardNavigation();
})();
