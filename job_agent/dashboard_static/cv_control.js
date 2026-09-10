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
					<p class="eyebrow">CURRÍCULUM · FUENTE PROFESIONAL</p>
					<h3>Mi CV</h3>
					<p>Sube PDF, DOCX o TXT. Se procesa localmente y actualiza los cargos y skills que usa el autopiloto.</p>
				</div>
				<span class="safe-pill">SOLO ESTE PC</span>
			</div>
			<div class="cv-upload-row">
				<input id="cvFileInput" type="file" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain">
				<button class="button secondary" id="cvUploadButton" type="button">Analizar mi CV</button>
			</div>
			<div id="cvStatus" class="cv-status">Aún no hay información del CV.</div>
			<div id="cvDetected" class="cv-detected"></div>`;
		form.insertBefore(card, firstField);
		card.querySelector('#cvUploadButton').addEventListener('click', uploadCv);
		loadCvStatus();
	}

	function renderStatus(status) {
		const statusEl = document.querySelector('#cvStatus');
		const detectedEl = document.querySelector('#cvDetected');
		if (!statusEl || !detectedEl) return;
		if (!status?.configured) {
			statusEl.textContent = 'Sube tu CV para construir automáticamente el perfil de búsqueda.';
			detectedEl.innerHTML = '';
			return;
		}
		statusEl.innerHTML = `<strong>${escapeCv(status.filename)}</strong> · ${Number(status.text_chars || 0).toLocaleString()} caracteres extraídos`;
		const roles = (status.detected_roles || []).map((item) => `<span class="skill-chip">${escapeCv(item)}</span>`).join('');
		const skills = (status.detected_skills || []).map((item) => `<span class="skill-chip">${escapeCv(item)}</span>`).join('');
		detectedEl.innerHTML = `
			<div><strong>Cargos de búsqueda</strong><div class="chip-list">${roles || '<span class="empty-chip">Conservando cargos actuales</span>'}</div></div>
			<div><strong>Skills verificadas en el CV</strong><div class="chip-list">${skills || '<span class="empty-chip">No se detectaron automáticamente</span>'}</div></div>`;
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

	async function uploadCv() {
		const input = document.querySelector('#cvFileInput');
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
		button.disabled = true;
		button.textContent = 'Analizando…';
		statusEl.textContent = 'Extrayendo información localmente…';
		try {
			const content_base64 = bytesToBase64(await file.arrayBuffer());
			const response = await fetch('/api/cv', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ filename: file.name, content_base64 }),
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
			renderStatus(payload.cv);
			if (typeof renderProfile === 'function') renderProfile(payload.profile);
			statusEl.innerHTML = `<strong>${escapeCv(file.name)}</strong> analizado. Revisa los cargos y skills debajo; puedes editarlos antes de guardar.`;
		} catch (error) {
			statusEl.textContent = `No se pudo analizar el CV: ${error.message}`;
		} finally {
			button.disabled = false;
			button.textContent = 'Analizar mi CV';
		}
	}

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
	else mount();
})();
