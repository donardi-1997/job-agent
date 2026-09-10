(() => {
	let mounted = false;
	let previousFetch = null;

	function stateNode() {
		return document.querySelector('#scoreRefreshState');
	}

	function setState(message, isError = false) {
		const node = stateNode();
		if (!node) return;
		node.textContent = message;
		node.dataset.state = isError ? 'error' : 'ok';
	}

	async function reloadVisibleScores() {
		if (typeof window.loadDashboard === 'function') {
			await window.loadDashboard();
		}
		if (typeof window.refreshApplicationsList === 'function') {
			await window.refreshApplicationsList();
		}
	}

	async function manualRescore() {
		const button = document.querySelector('#rescoreJobsButton');
		if (!button) return;
		button.disabled = true;
		button.textContent = 'Recalculando…';
		setState('Actualizando todos los scores localmente…');
		try {
			const response = await previousFetch('/api/jobs/rescore', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: '{}',
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			setState(`${payload.rescored_jobs || 0} vacantes recalculadas · sin IA`);
			await reloadVisibleScores();
		} catch (error) {
			setState(`No se pudieron actualizar los scores: ${error.message}`, true);
		} finally {
			button.disabled = false;
			button.textContent = 'Actualizar scores';
		}
	}

	function mountControl() {
		if (mounted || document.querySelector('#rescoreJobsButton')) return;
		const panel = document.querySelector('#jobs .panel-header');
		if (!panel) return;
		const filters = panel.querySelector('.filters');
		if (!filters) return;

		const control = document.createElement('div');
		control.className = 'score-refresh-control';
		control.innerHTML = `
			<button class="button secondary" id="rescoreJobsButton" type="button">Actualizar scores</button>
			<span class="empty-chip" id="scoreRefreshState">Se actualizan al guardar Mi perfil</span>`;
		filters.prepend(control);
		control.querySelector('#rescoreJobsButton').addEventListener('click', manualRescore);
		mounted = true;
	}

	function installProfileSaveWatcher() {
		if (previousFetch) return;
		previousFetch = window.fetch.bind(window);
		const profileWritePaths = new Set([
			'/api/profile',
			'/api/profile/summary',
			'/api/profile/min-salary',
		]);

		window.fetch = async (input, init) => {
			const response = await previousFetch(input, init);
			const url = typeof input === 'string' ? input : (input?.url || '');
			const path = (() => {
				try { return new URL(url, window.location.origin).pathname; }
				catch (_) { return url; }
			})();
			const method = String(init?.method || 'GET').toUpperCase();
			if (response.ok && method === 'POST' && profileWritePaths.has(path)) {
				response.clone().json().then(async (payload) => {
					const count = Number(payload.rescored_jobs || 0);
					setState(`${count} vacantes recalculadas automáticamente · sin IA`);
					await reloadVisibleScores();
				}).catch(() => {});
			}
			return response;
		};
	}

	function mount() {
		installProfileSaveWatcher();
		mountControl();
	}

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
