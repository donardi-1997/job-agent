(() => {
	let automationEnabled = true;
	let saving = false;

	const style = document.createElement('style');
	style.textContent = `
		.automation-master{display:flex;align-items:center;gap:10px;padding:8px 12px;border:1px solid var(--border,rgba(255,255,255,.12));border-radius:12px;background:var(--surface,#15171c)}
		.automation-master-copy{display:flex;flex-direction:column;line-height:1.15}.automation-master-copy strong{font-size:12px}.automation-master-copy span{font-size:10px;opacity:.68;margin-top:3px}
		.automation-switch{position:relative;width:42px;height:24px;display:inline-flex;flex:0 0 auto}.automation-switch input{position:absolute;opacity:0;pointer-events:none}.automation-slider{position:absolute;inset:0;border-radius:999px;background:#555;cursor:pointer;transition:.2s}.automation-slider:after{content:"";position:absolute;width:18px;height:18px;left:3px;top:3px;border-radius:50%;background:white;transition:.2s}.automation-switch input:checked+.automation-slider{background:#27a96b}.automation-switch input:checked+.automation-slider:after{transform:translateX(18px)}
		body.automation-paused #batchButton,body.automation-paused #prepareButton{opacity:.45;cursor:not-allowed}
		.automation-paused-note{font-size:11px;color:#d99a49;margin-top:5px}
		@media(max-width:760px){.automation-master{width:100%;justify-content:space-between}.topbar .actions{flex-wrap:wrap}}
	`;
	document.head.appendChild(style);

	function mount() {
		if (document.querySelector('#automationMaster')) return;
		const actions = document.querySelector('.topbar .actions');
		if (!actions) return;
		const root = document.createElement('div');
		root.id = 'automationMaster';
		root.className = 'automation-master';
		root.innerHTML = `
			<div class="automation-master-copy"><strong id="automationLabel">Automatización</strong><span id="automationStateText">Activa</span></div>
			<label class="automation-switch" title="Activar o pausar auto-postulaciones">
				<input id="automationToggle" type="checkbox" checked aria-label="Activar automatización">
				<span class="automation-slider"></span>
			</label>`;
		actions.prepend(root);
		root.querySelector('#automationToggle').addEventListener('change', onToggle);
	}

	function applyState(enabled) {
		automationEnabled = Boolean(enabled);
		document.body.classList.toggle('automation-paused', !automationEnabled);
		const toggle = document.querySelector('#automationToggle');
		const text = document.querySelector('#automationStateText');
		if (toggle) { toggle.checked = automationEnabled; toggle.disabled = saving; }
		if (text) text.textContent = automationEnabled ? 'Activa · auto-postulación permitida' : 'Pausada · solo búsqueda';
		const batchButton = document.querySelector('#batchButton');
		const prepareButton = document.querySelector('#prepareButton');
		if (!automationEnabled) {
			if (batchButton) batchButton.disabled = true;
			if (prepareButton) prepareButton.disabled = true;
		}
	}

	async function loadState() {
		mount();
		try {
			const response = await fetch('/api/automation', { cache: 'no-store' });
			if (!response.ok) return;
			const payload = await response.json();
			applyState(payload.enabled);
		} catch (error) {
			console.error('Unable to load automation state', error);
		}
	}

	async function onToggle(event) {
		if (saving) return;
		const requested = Boolean(event.target.checked);
		saving = true;
		applyState(requested);
		try {
			const response = await fetch('/api/automation', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled: requested }),
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			applyState(payload.enabled);
		} catch (error) {
			applyState(!requested);
			console.error('Unable to update automation state', error);
		} finally {
			saving = false;
			applyState(automationEnabled);
		}
	}

	mount();
	loadState();
	// Existing status renderers may update button.disabled; enforce the master pause visually and functionally.
	setInterval(() => { if (!automationEnabled) applyState(false); }, 750);
})();
