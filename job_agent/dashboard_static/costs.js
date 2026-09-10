(() => {
  let usdCopRate = 4000;
  const formatCop = (value) => new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(Number(value || 0) * usdCopRate);
  const formatUsd = (value) => `US$${Number(value || 0).toFixed(4)}`;
  const formatTokens = (value) => new Intl.NumberFormat('es-CO').format(Number(value || 0));

  function ensureStyles() {
    if (document.querySelector('#aiUsageStyles')) return;
    const style = document.createElement('style');
    style.id = 'aiUsageStyles';
    style.textContent = `
      .ai-usage-panel{margin:0 0 22px;padding:18px;border:1px solid rgba(139,165,255,.15);border-radius:16px;background:linear-gradient(135deg,rgba(139,165,255,.055),rgba(104,211,145,.025))}
      .ai-usage-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.ai-usage-heading h2{margin:3px 0 5px;font-size:17px}.ai-usage-heading p:last-child{margin:0;color:#7f8ba4;font-size:11px;line-height:1.55;max-width:760px}
      .ai-usage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:15px}.ai-usage-grid article{padding:13px;border:1px solid rgba(255,255,255,.065);border-radius:11px;background:rgba(5,10,22,.4)}.ai-usage-grid article>span{display:block;color:#7d89a3;font-size:10px}.ai-usage-grid strong{display:block;margin:5px 0 3px;color:#e7edf8;font-size:19px}.ai-usage-grid small{display:block;color:#6f7c95;font-size:9px;line-height:1.4}.ai-usage-grid .coverage{margin-top:3px;color:#8dbfa2}
      .ai-recent{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}.ai-recent-item{padding:6px 8px;border-radius:8px;background:rgba(255,255,255,.035);color:#79869f;font-size:9px}.ai-recent-item b{color:#aab6cf;margin-right:4px}.ai-rate{margin-top:8px;color:#68758d;font-size:9px}
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
      <div class="ai-usage-heading"><div><p class="eyebrow">COSTO DE IA · APRENDIZAJE LOCAL</p><h2>Consumo del agente en pesos colombianos</h2><p>Cada respuesta confirmada alimenta memoria local. La meta es aumentar cobertura determinística y reducir progresivamente las decisiones que necesitan IA.</p><div class="ai-rate" id="aiRate">Tasa USD/COP: cargando…</div></div><span class="safe-pill">COP</span></div>
      <div class="ai-usage-grid">
        <article><span>Hoy</span><strong id="aiTodayCost">$0</strong><small id="aiTodayTokens">0 tokens · 0 ejecuciones</small><small id="aiTodayUsd">US$0.0000</small></article>
        <article><span>Este mes</span><strong id="aiMonthCost">$0</strong><small id="aiMonthTokens">0 tokens · 0 ejecuciones</small><small id="aiMonthUsd">US$0.0000</small></article>
        <article><span>Total</span><strong id="aiTotalCost">$0</strong><small id="aiTotalTokens">0 tokens · 0 ejecuciones</small><small id="aiTotalUsd">US$0.0000</small></article>
        <article><span>Memoria determinística</span><strong id="answerMemoryCount">0</strong><small id="answerMemoryUses">0 aprendizajes registrados</small><small class="coverage" id="answerMemoryCoverage">0% cobertura de preguntas conocidas</small></article>
      </div><div class="ai-recent" id="aiRecent"></div>`;
    metrics.insertAdjacentElement('afterend', panel);
  }

  function render(data) {
    ensurePanel();
    const today = data.today || {}, month = data.month || {}, total = data.all_time || {}, memory = data.answer_memory || {};
    document.querySelector('#aiTodayCost').textContent = formatCop(today.cost_usd);
    document.querySelector('#aiTodayUsd').textContent = formatUsd(today.cost_usd);
    document.querySelector('#aiTodayTokens').textContent = `${formatTokens(today.tokens)} tokens · ${today.calls || 0} ejecuciones`;
    document.querySelector('#aiMonthCost').textContent = formatCop(month.cost_usd);
    document.querySelector('#aiMonthUsd').textContent = formatUsd(month.cost_usd);
    document.querySelector('#aiMonthTokens').textContent = `${formatTokens(month.tokens)} tokens · ${month.calls || 0} ejecuciones`;
    document.querySelector('#aiTotalCost').textContent = formatCop(total.cost_usd);
    document.querySelector('#aiTotalUsd').textContent = formatUsd(total.cost_usd);
    document.querySelector('#aiTotalTokens').textContent = `${formatTokens(total.tokens)} tokens · ${total.calls || 0} ejecuciones`;
    document.querySelector('#answerMemoryCount').textContent = memory.answers || 0;
    document.querySelector('#answerMemoryUses').textContent = `${memory.learned_questions || 0}/${memory.encountered_questions || 0} preguntas aprendidas · ${memory.submitted_applications || 0} postulaciones exitosas`;
    document.querySelector('#answerMemoryCoverage').textContent = `${Number(memory.answer_coverage_pct || 0).toFixed(1)}% cobertura determinística`;
    const recent = data.recent || [];
    document.querySelector('#aiRecent').innerHTML = recent.length ? recent.slice(0, 6).map((item) => `<span class="ai-recent-item"><b>${item.operation === 'application' ? 'Postulación' : 'Búsqueda'}</b>${formatTokens(item.total_tokens)} tokens · ${formatCop(item.estimated_cost_usd)} · ${item.model}</span>`).join('') : '<span class="empty-chip">Aún no hay consumo de IA registrado.</span>';
  }

  async function refresh() {
    try {
      const [usageResponse, currencyResponse] = await Promise.all([fetch('/api/ai/usage', { cache: 'no-store' }), fetch('/api/currency', { cache: 'no-store' })]);
      if (currencyResponse.ok) {
        const currency = await currencyResponse.json();
        usdCopRate = Number(currency.usd_cop_rate || 4000);
        const rate = document.querySelector('#aiRate');
        if (rate) rate.textContent = `Tasa usada: US$1 = ${new Intl.NumberFormat('es-CO').format(usdCopRate)} COP · configurable con JOB_AGENT_USD_COP_RATE`;
      }
      if (usageResponse.ok) render(await usageResponse.json());
    } catch (error) { console.error('Unable to load AI usage', error); }
  }

  ensurePanel(); refresh(); window.setInterval(refresh, 5000);
})();
