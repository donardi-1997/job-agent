(() => {
  function ensureStyles() {
    if (document.querySelector('#contactTrackingStyles')) return;
    const style = document.createElement('style');
    style.id = 'contactTrackingStyles';
    style.textContent = `
      .contact-panel{margin-top:18px;padding:16px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.025)}
      .contact-panel h3{margin:0 0 5px}.contact-panel>p{margin:0 0 13px;color:#7f8ba4;font-size:11px;line-height:1.5}
      .contact-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.contact-grid label{display:flex;flex-direction:column;gap:5px;color:#8591a8;font-size:10px}.contact-grid input,.contact-grid select,.contact-grid textarea{width:100%;box-sizing:border-box}.contact-grid .wide{grid-column:1/-1}.contact-grid textarea{min-height:72px;resize:vertical}.contact-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:11px}.contact-message{color:#7f8ba4;font-size:10px}
      .contact-stats{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.contact-stat{padding:7px 9px;border-radius:9px;background:rgba(255,255,255,.04);font-size:10px;color:#8190a8}.contact-stat strong{color:#dce5f5;margin-right:3px}
      @media(max-width:560px){.contact-grid{grid-template-columns:1fr}.contact-grid .wide{grid-column:auto}.contact-actions{align-items:stretch;flex-direction:column}.contact-actions button{width:100%}}
    `;
    document.head.appendChild(style);
  }

  async function api(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }

  function ensurePanel() {
    ensureStyles();
    if (document.querySelector('#contactPanel')) return;
    const application = document.querySelector('.application-section');
    if (!application) return;
    const panel = document.createElement('section');
    panel.id = 'contactPanel';
    panel.className = 'contact-panel';
    panel.innerHTML = `
      <h3>Seguimiento del proceso</h3>
      <p>Cuando ya te hayas postulado, registra si la empresa se comunicó contigo. Estos datos alimentan tus estadísticas reales de búsqueda.</p>
      <div class="contact-grid">
        <label>Estado<select id="contactStatus"><option value="pending">Pendiente</option><option value="contacted">Sí, me contactaron</option><option value="no_contact">No me contactaron</option></select></label>
        <label>Canal<input id="contactChannel" placeholder="WhatsApp, llamada, email..."></label>
        <label>Fecha de contacto<input id="contactDate" type="date"></label>
        <label class="wide">Nota<textarea id="contactNote" placeholder="Ej. llamada inicial, entrevista técnica, mensaje del reclutador..."></textarea></label>
      </div>
      <div class="contact-actions"><span class="contact-message" id="contactMessage">Disponible para vacantes postuladas.</span><button class="button secondary" type="button" id="saveContactButton">Guardar seguimiento</button></div>
      <div class="contact-stats" id="contactStats"></div>
    `;
    application.appendChild(panel);
    panel.querySelector('#saveContactButton').addEventListener('click', saveContact);
  }

  async function loadStats() {
    const root = document.querySelector('#contactStats');
    if (!root) return;
    try {
      const stats = await api('/api/contact/stats');
      root.innerHTML = `
        <span class="contact-stat"><strong>${stats.contacted || 0}</strong> contactos</span>
        <span class="contact-stat"><strong>${stats.pending || 0}</strong> pendientes</span>
        <span class="contact-stat"><strong>${stats.no_contact || 0}</strong> sin contacto</span>
        <span class="contact-stat"><strong>${Number(stats.contact_rate_pct || 0).toFixed(1)}%</strong> tasa de contacto</span>`;
    } catch (error) {
      root.textContent = '';
    }
  }

  async function loadContact(jobId) {
    ensurePanel();
    if (!jobId || !document.querySelector('#contactPanel')) return;
    try {
      const item = await api(`/api/jobs/${jobId}/contact`);
      document.querySelector('#contactStatus').value = item.status || 'pending';
      document.querySelector('#contactChannel').value = item.channel || '';
      document.querySelector('#contactDate').value = (item.contacted_at || '').slice(0, 10);
      document.querySelector('#contactNote').value = item.note || '';
      document.querySelector('#contactMessage').textContent = item.updated_at ? 'Seguimiento guardado.' : 'Disponible para vacantes postuladas.';
    } catch (error) {
      document.querySelector('#contactMessage').textContent = error.message;
    }
    loadStats();
  }

  async function saveContact() {
    if (!activeJobId) return;
    const button = document.querySelector('#saveContactButton');
    const message = document.querySelector('#contactMessage');
    button.disabled = true;
    message.textContent = 'Guardando…';
    try {
      const status = document.querySelector('#contactStatus').value;
      await api(`/api/jobs/${activeJobId}/contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status,
          channel: document.querySelector('#contactChannel').value.trim(),
          contacted_at: status === 'contacted' ? document.querySelector('#contactDate').value : '',
          note: document.querySelector('#contactNote').value.trim(),
        }),
      });
      message.textContent = 'Seguimiento guardado. Las estadísticas fueron actualizadas.';
      await loadStats();
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  const originalOpenJob = window.openJob || (typeof openJob === 'function' ? openJob : null);
  if (originalOpenJob) {
    window.openJob = async function(jobId) {
      const result = await originalOpenJob(jobId);
      await loadContact(jobId);
      return result;
    };
  }

  ensurePanel();
  loadStats();
  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('[data-review-job]');
    if (button) window.setTimeout(() => loadContact(Number(button.dataset.reviewJob)), 80);
  });
})();
