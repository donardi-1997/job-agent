(() => {
	const MAX_CV_BYTES = 8 * 1024 * 1024;

	function escapeCv(value) {
		return String(value ?? '')
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;')
			.replaceAll("'", '&#039;');
	}

	function bytesToBase64(buffer) {
		const bytes = new Uint8Array(buffer);
		let binary = '';
		const chunkSize = 0x8000;
		for (let offset = 0; offset < bytes.length; offset += chunkSize) {
			binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
		}
		return btoa(binary);
	}

	function mount() {
		const form = document.querySelector('#profileForm');
		if (!form || document.querySelector('#cvProfileCard')) return;
		const firstField = form.querySelector('label');
		const card = document.createElement('section');
		card.id = 'cvProfileCard';
		card.className = 'cv-profile-card wide';
		card.innerHTML = `
			<div class="section-heading">
				<div>
					<p class="eyebrow">CURRÍCULUM · VARIANTES POR VACANTE</p>
					<h3>Mis CV</h3>
					<p>Guarda varias versiones. SearchJob elegirá automáticamente la más cercana a cada vacante y la adjuntará cuando el formulario lo solicite.</p>
				</div>
				<span class="safe-pill">SOLO ESTE PC</span>
			</div>
			<div class="cv-upload-row">
				<input id="cvVariantName" type="text" maxlength="80" value="Principal" placeholder="Ej. Backend / Python">
				<input id="cvFileInput" type="file" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain">
				<label class="inline-check"><input id="cvActivate" type="checkbox" checked> Usar como CV principal</label>
				<button class="button secondary" id="cvUploadButton" type="button">Analizar y guardar</button>
			</div>
			<div id="cvStatus" class="cv-status">Aún no hay información del CV.</div>
			<div id="cvDetected" class="cv-detected"></div>
			<div id="cvVariants" class="cv-detected"></div>`;
		form.insertBefore(card, firstField);
		card.querySelector('#cvUploadButton').addEventListener('click', uploadCv);
		card.querySelector('#cvVariants').addEventListener('click', async (event) => {
			const button = event.target.closest('[data-cv-activate]');
			if (!button) return;
			await activateVariant(button.dataset.cvActivate);
		});
		loadCvStatus();
	}

	function chips(items) {
		return (items || []).map((item) => `<span class="skill-chip">${escapeCv(item)}</span>`).join('');
	}

	function renderStatus(status) {
		const statusEl = document.querySelector('#cvStatus');
		const detectedEl = document.querySelector('#cvDetected');
		const variantsEl = document.querySelector('#cvVariants');
		if (!statusEl || !detectedEl || !variantsEl) return;
		if (!status?.configured) {
			statusEl.textContent = 'Sube tu primer CV. Recomendación: Principal, Backend / Python, AWS / Cloud y Full Stack / AI.';
			detectedEl.innerHTML = '';
			variantsEl.innerHTML = '';
			return;
		}
		statusEl.innerHTML = `CV principal: <strong>${escapeCv(status.filename)}</strong> · ${Number(status.text_chars || 0).toLocaleString()} caracteres extraídos`;
		detectedEl.innerHTML = `
			<div><strong>Cargos del CV principal</strong><div class="chip-list">${chips(status.detected_roles) || '<span class="empty-chip">Conservando cargos actuales</span>'}</div></div>
			<div><strong>Skills verificadas</strong><div class="chip-list">${chips(status.detected_skills) || '<span class="empty-chip">No se detectaron automáticamente</span>'}</div></div>`;

		const variants = status.variants || [];
		variantsEl.innerHTML = variants.length ? `
			<div><strong>Versiones disponibles</strong></div>
			<div class="cv-variant-list">
				${variants.map((variant) => `
					<div class="cv-variant-item">
						<div>
							<strong>${escapeCv(variant.label)}</strong>
							<span class="muted"> · ${escapeCv(variant.filename)}</span>
							${variant.is_default ? '<span class="safe-pill">PRINCIPAL</span>' : ''}
							<div class="chip-list">${chips(variant.detected_roles)}</div>
						</div>
						${variant.is_default ? '' : `<button type="button" class="button secondary" data-cv-activate="${escapeCv(variant.variant_key)}">Usar como principal</button>`}
					</div>`).join('')}
			</div>` : '';
	}

	async function loadCvStatus() {
		try {
			const response = await fetch('/api/cv');
			if (!response.ok) return;
			renderStatus(await response.json());
		} catch (error) {
			console.error('Unable to load CV status', error);
		}
	}

	async function activateVariant(variantKey) {
		const statusEl = document.querySelector('#cvStatus');
		try {
			const response = await fetch('/api/cv/select', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ variant_key: variantKey }),
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			renderStatus(payload.cv);
			if (typeof renderProfile === 'function') renderProfile(payload.profile);
		} catch (error) {
			statusEl.textContent = `No se pudo activar el CV: ${error.message}`;
		}
	}

	async function uploadCv() {
		const input = document.querySelector('#cvFileInput');
		const labelInput = document.querySelector('#cvVariantName');
		const activateInput = document.querySelector('#cvActivate');
		const button = document.querySelector('#cvUploadButton');
		const statusEl = document.querySelector('#cvStatus');
		const file = input?.files?.[0];
		if (!file) {
			statusEl.textContent = 'Selecciona primero un archivo PDF, DOCX o TXT.';
			return;
		}
		if (file.size > MAX_CV_BYTES) {
			statusEl.textContent = 'El archivo supera el límite de 8 MB.';
			return;
		}
		const variantName = String(labelInput?.value || '').trim() || 'Principal';
		button.disabled = true;
		button.textContent = 'Analizando…';
		statusEl.textContent = 'Extrayendo información localmente…';
		try {
			const content_base64 = bytesToBase64(await file.arrayBuffer());
			const response = await fetch('/api/cv', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					filename: file.name,
					content_base64,
					variant_name: variantName,
					activate: Boolean(activateInput?.checked),
				}),
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			renderStatus(payload.cv);
			if (typeof renderProfile === 'function') renderProfile(payload.profile);
			statusEl.innerHTML = `<strong>${escapeCv(variantName)}</strong> guardado. SearchJob ya puede seleccionarlo automáticamente por vacante.`;
			input.value = '';
		} catch (error) {
			statusEl.textContent = `No se pudo analizar el CV: ${error.message}`;
		} finally {
			button.disabled = false;
			button.textContent = 'Analizar y guardar';
		}
	}

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
