(() => {
  const formatUsd = (value) => `$${Number(value || 0).toFixed(4)}`;
  const formatTokens = (value) => new Intl.NumberFormat('es-CO').format(Number(value || 0));

  function ensureStyles() {
    if (document.querySelector('#aiUsageStyles')) return;
    const style = document.createElement('style');
    style.id = 'aiUsageStyles';
    style.textContent = `
      .ai-usage-panel{margin:0 0 22px;padding:18px;border:1px solid rgba(139,165,255,.15);border-radius:16px;background:linear-gradient(135deg,rgba(139,165,255,.055),rgba(104,211,145,.025))}
      .ai-usage-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.ai-usage-heading h2{margin:3px 0 5px;font-size:17px}.ai-usage-heading p:last-child{margin:0;color:#7f8ba4;font-size:11px;line-height:1.55;max-width:760px}
      .ai-usage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:15px}.ai-usage-grid article{padding:13px;border:1px solid rgba(255,255,255,.065);border-radius:11px;background:rgba(5,10,22,.4)}.ai-usage-grid article>span{display:block;color:#7d89a3;font-size:10px}.ai-usage-grid strong{display:block;margin:5px 0 3px;color:#e7edf8;font-size:19px}.ai-usage-grid small{color:#6f7c95;font-size:9px;line-height:1.4}
      .ai-recent{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}.ai-recent-item{padding:6px 8px;border-radius:8px;background:rgba(255,255,255,.035);color:#79869f;font-size:9px}.ai-recent-item b{color:#aab6cf;margin-right:4px}
      @media(max-width:900px){.ai-usage-grid{grid-template-columns:1fr 1fr}}@media(max-width:560px){.ai-usage-heading{flex-direction:column}.ai-usage-grid{grid-template-columns:1fr 1fr}.ai-usage-grid strong{font-size:16px}}
    `;
    document.head.appendChild(style);
  }

  function ensurePanel() {
    ensureStyles();
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
        <article><span>Memoria local</span><strong id="answerMemoryCount">0</strong><small id="answerMemoryUses">0 usos/aprendizajes registrados</small></article>
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
