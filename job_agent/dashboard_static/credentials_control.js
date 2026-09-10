(() => {
  const escapeHtml = (value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  function ensureStyles() {
    if (document.querySelector('#credentialStyles')) return;
    const style = document.createElement('style');
    style.id = 'credentialStyles';
    style.textContent = `
      .credential-card{grid-column:1/-1;margin:4px 0 2px;padding:16px;border:1px solid rgba(139,165,255,.16);border-radius:14px;background:rgba(8,13,27,.42)}
      .credential-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:13px}.credential-head h3{margin:2px 0 4px;font-size:15px}.credential-head p{margin:0;color:#78859d;font-size:10px;line-height:1.55;max-width:720px}.credential-state{font-size:9px;color:#93a0b8;white-space:nowrap}
      .credential-grid{display:grid;grid-template-columns:1fr 1fr auto;gap:10px;align-items:end}.credential-grid label{display:flex;flex-direction:column;gap:6px;color:#8e9ab1;font-size:10px}.credential-grid input{width:100%}.credential-actions{display:flex;gap:7px}.credential-message{display:block;margin-top:9px;color:#75829b;font-size:9px;line-height:1.5}.credential-message.ok{color:#8dbfa2}.credential-message.error{color:#e59a9a}
      @media(max-width:760px){.credential-grid{grid-template-columns:1fr}.credential-actions{width:100%}.credential-actions button{flex:1}.credential-head{flex-direction:column}}
    `;
    document.head.appendChild(style);
  }

  function mount() {
    ensureStyles();
    if (document.querySelector('#computrabajoCredentials')) return;
    const form = document.querySelector('#profileForm');
    if (!form) return;

    const firstWide = form.querySelector('.wide');
    const card = document.createElement('section');
    card.id = 'computrabajoCredentials';
    card.className = 'credential-card';
    card.innerHTML = `
      <div class="credential-head">
        <div>
          <p class="eyebrow">COMPUTRABAJO · ACCESO LOCAL</p>
          <h3>Credenciales para completar postulaciones</h3>
          <p>Se usan únicamente si Computrabajo solicita inicio de sesión. La contraseña no se muestra después de guardarla ni se incluye en el prompt de IA.</p>
        </div>
        <span class="credential-state" id="credentialState">Consultando…</span>
      </div>
      <div class="credential-grid">
        <label>Usuario o correo<input id="computrabajoUsername" autocomplete="username" placeholder="Tu usuario o correo"></label>
        <label>Contraseña<input id="computrabajoPassword" type="password" autocomplete="current-password" placeholder="••••••••"></label>
        <div class="credential-actions">
          <button class="button primary" id="saveCredentials" type="button">Guardar acceso</button>
          <button class="button secondary" id="clearCredentials" type="button">Borrar</button>
        </div>
      </div>
      <span class="credential-message" id="credentialMessage">La sesión persistente del navegador sigue siendo la primera opción; estas credenciales son respaldo para el login nativo.</span>
    `;
    if (firstWide) form.insertBefore(card, firstWide);
    else form.prepend(card);

    document.querySelector('#saveCredentials').addEventListener('click', save);
    document.querySelector('#clearCredentials').addEventListener('click', clear);
    refresh();
  }

  async function refresh() {
    try {
      const response = await fetch('/api/computrabajo/credentials', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const username = document.querySelector('#computrabajoUsername');
      if (username && !username.value) username.value = data.username || '';
      document.querySelector('#credentialState').textContent = data.configured ? `Configurado · ${data.protection}` : 'No configurado';
      document.querySelector('#clearCredentials').disabled = !data.configured;
    } catch (error) {
      document.querySelector('#credentialState').textContent = 'No disponible';
    }
  }

  async function save() {
    const username = document.querySelector('#computrabajoUsername').value.trim();
    const passwordInput = document.querySelector('#computrabajoPassword');
    const password = passwordInput.value;
    const message = document.querySelector('#credentialMessage');
    const button = document.querySelector('#saveCredentials');
    button.disabled = true;
    message.className = 'credential-message';
    message.textContent = 'Protegiendo y guardando localmente…';
    try {
      const response = await fetch('/api/computrabajo/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      passwordInput.value = '';
      message.className = 'credential-message ok';
      message.textContent = `Acceso guardado. La contraseña está protegida con ${escapeHtml(data.protection || 'protección local')}.`;
      await refresh();
    } catch (error) {
      message.className = 'credential-message error';
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  async function clear() {
    const message = document.querySelector('#credentialMessage');
    try {
      const response = await fetch('/api/computrabajo/credentials/clear', { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      document.querySelector('#computrabajoPassword').value = '';
      document.querySelector('#computrabajoUsername').value = '';
      message.className = 'credential-message ok';
      message.textContent = 'Credenciales eliminadas del almacenamiento local.';
      await refresh();
    } catch (error) {
      message.className = 'credential-message error';
      message.textContent = error.message;
    }
  }

  mount();
})();
