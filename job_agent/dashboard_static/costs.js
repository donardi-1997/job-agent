(() => {
  const formatUsd = (value) => `$${Number(value || 0).toFixed(4)}`;
  const formatTokens = (value) => new Intl.NumberFormat('es-CO').format(Number(value || 0));

  function ensurePanel() {
    if (document.querySelector('#aiUsagePanel')) return;
    const metrics = document.querySelector('.metrics');
    if (!metrics) return;

    const panel = document.createElement('section');
    panel.id = 'aiUsagePanel';
    panel.className = 'ai-usage-panel';
    panel.innerHTML = `
      <div class="ai-usage-heading">
        <div>
          <p class="eyebrow">COSTO DE IA</p>
          <h2>Consumo real del agente</h2>
          <p>Tokens medidos por Browser Use. El valor en USD es una estimación calculada con la tabla de precios configurada localmente.</p>
        </div>
        <span class="safe-pill">LOCAL METERING</span>
      </div>
      <div class="ai-usage-grid">
        <article><span>Hoy</span><strong id="aiTodayCost">$0.0000</strong><small id="aiTodayTokens">0 tokens · 0 ejecuciones</small></article>
        <article><span>Este mes</span><strong id="aiMonthCost">$0.0000</strong><small id="aiMonthTokens">0 tokens · 0 ejecuciones</small></article>
        <article><span>Total</span><strong id="aiTotalCost">$0.0000</strong><small id="aiTotalTokens">0 tokens · 0 ejecuciones</small></article>
        <article><span>Memoria local</span><strong id="answerMemoryCount">0</strong><small id="answerMemoryUses">0 reutilizaciones registradas</small></article>
      </div>
      <div class="ai-recent" id="aiRecent"></div>
    `;
    metrics.insertAdjacentElement('afterend', panel);
  }

  function render(data) {
    ensurePanel();
    if (!document.querySelector('#aiUsagePanel')) return;
    const today = data.today || {};
    const month = data.month || {};
    const total = data.all_time || {};
    const memory = data.answer_memory || {};

    document.querySelector('#aiTodayCost').textContent = formatUsd(today.cost_usd);
    document.querySelector('#aiTodayTokens').textContent = `${formatTokens(today.tokens)} tokens · ${today.calls || 0} ejecuciones`;
    document.querySelector('#aiMonthCost').textContent = formatUsd(month.cost_usd);
    document.querySelector('#aiMonthTokens').textContent = `${formatTokens(month.tokens)} tokens · ${month.calls || 0} ejecuciones`;
    document.querySelector('#aiTotalCost').textContent = formatUsd(total.cost_usd);
    document.querySelector('#aiTotalTokens').textContent = `${formatTokens(total.tokens)} tokens · ${total.calls || 0} ejecuciones`;
    document.querySelector('#answerMemoryCount').textContent = memory.answers || 0;
    document.querySelector('#answerMemoryUses').textContent = `${memory.uses || 0} usos/aprendizajes registrados`;

    const recent = data.recent || [];
    const root = document.querySelector('#aiRecent');
    root.innerHTML = recent.length
      ? recent.slice(0, 6).map((item) => `
          <span class="ai-recent-item">
            <b>${item.operation === 'application' ? 'Postulación' : 'Búsqueda'}</b>
            ${formatTokens(item.total_tokens)} tokens · ${formatUsd(item.estimated_cost_usd)} · ${item.model}
          </span>
        `).join('')
      : '<span class="empty-chip">Aún no hay consumo de IA registrado.</span>';
  }

  async function refresh() {
    try {
      const response = await fetch('/api/ai/usage', { cache: 'no-store' });
      if (!response.ok) return;
      render(await response.json());
    } catch (error) {
      console.error('Unable to load AI usage', error);
    }
  }

  ensurePanel();
  refresh();
  window.setInterval(refresh, 5000);
})();
