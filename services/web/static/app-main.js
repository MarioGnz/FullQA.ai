/* ─────────────────────────────────────────────────────────────
   app.js — FullQA.ai frontend  (Phase 2 rewrite)
   All UI logic: sessions list, events timeline, report tabs,
   toasts, activity log, lightbox, generating panel.
───────────────────────────────────────────────────────────── */
'use strict';

/* ── Constants ──────────────────────────────────────────────── */
const API   = '/api';
const TOAST_ICONS = { ok: '✅', error: '❌', warn: '⚠️', info: 'ℹ️' };
const LOG_ICONS   = { ok: '✅', error: '❌', warn: '⚠️', info: '💬' };
const GEN_STEPS   = [
  'Agrupando eventos…',
  'Preparando capturas de pantalla…',
  'Enviando datos a Claude AI…',
  'Procesando respuesta…',
  'Generando documentación final…'
];

/* ── Global state ───────────────────────────────────────────── */
let _allSessions    = [];
let _activeFilter   = 'all';
let _currentEvents  = [];
let _selectedId     = null;
let _pollTimer      = null;
let _genStepTimer   = null;
let _cachedReport   = {};   // sessionId → markdown string
let _cachedEvents   = {};   // sessionId → events array

/* ── Utility ────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('es-CO', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch { return iso; }
}

function fmtTime(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return iso; }
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(msg || `HTTP ${res.status}`);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

/* ── Toast ──────────────────────────────────────────────────── */
function toast(type, title, msg, duration = 5000) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `
    <span class="toast-icon">${TOAST_ICONS[type] ?? 'ℹ️'}</span>
    <div class="toast-body">
      <div class="toast-title">${esc(title)}</div>
      ${msg ? `<div class="toast-msg">${esc(msg)}</div>` : ''}
    </div>
    <button class="toast-close" aria-label="Cerrar">×</button>
  `;
  el.querySelector('.toast-close').onclick = () => removeToast(el);
  container.appendChild(el);
  setTimeout(() => removeToast(el), duration);
}

function removeToast(el) {
  if (!el.parentNode) return;
  el.classList.add('toast-out');
  setTimeout(() => el.remove(), 220);
}

/* ── Activity log ───────────────────────────────────────────── */
function logActivity(type, msg) {
  const list = document.getElementById('log-list');
  const li = document.createElement('li');
  li.className = `log-item log-${type}`;
  li.innerHTML = `
    <span class="log-icon">${LOG_ICONS[type] ?? '💬'}</span>
    <div class="log-body">
      <div class="log-msg">${esc(msg)}</div>
      <div class="log-ts">${new Date().toLocaleTimeString('es-CO')}</div>
    </div>
  `;
  list.prepend(li);
}

function showActivity(label) {
  const ind = document.getElementById('activity-indicator');
  const lbl = document.getElementById('activity-label');
  if (ind) { ind.classList.remove('hidden'); if (lbl) lbl.textContent = label || 'Procesando…'; }
}

function hideActivity() {
  const ind = document.getElementById('activity-indicator');
  if (ind) ind.classList.add('hidden');
}

/* ── Lightbox ───────────────────────────────────────────────── */
function openLightbox(src, caption) {
  const lb  = document.getElementById('lightbox');
  const img = document.getElementById('lightbox-img');
  const cap = document.getElementById('lightbox-caption');
  img.src = src;
  if (cap) cap.textContent = caption || '';
  lb.classList.add('open');
}

function closeLightbox() {
  const lb = document.getElementById('lightbox');
  lb.classList.remove('open');
  document.getElementById('lightbox-img').src = '';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeLightbox();
});

/* ── Health check ───────────────────────────────────────────── */
async function checkHealth() {
  const badge = document.getElementById('api-status');
  if (!badge) return;
  badge.className = 'badge badge-checking';
  badge.textContent = 'Conectando…';
  try {
    const data = await apiFetch('/health');
    badge.className = 'badge badge-ok';
    badge.textContent = '● API OK';
    logActivity('ok', `API conectada — ${data.status || 'ok'}`);
  } catch (err) {
    badge.className = 'badge badge-error';
    badge.textContent = '● Sin conexión';
    logActivity('error', `API no disponible: ${err.message}`);
  }
}

/* ── Sessions list ──────────────────────────────────────────── */
async function loadSessions() {
  const listEl = document.getElementById('session-list');
  if (!listEl) return;

  // Show skeleton on first load (empty list)
  if (_allSessions.length === 0) {
    listEl.innerHTML = `<div class="skeleton-list">
      <div class="skeleton-card"></div>
      <div class="skeleton-card"></div>
      <div class="skeleton-card"></div>
    </div>`;
  }

  try {
    const data = await apiFetch('/sessions');
    _allSessions = Array.isArray(data) ? data : (data.sessions ?? []);
    renderSessionList(_allSessions);
  } catch (err) {
    logActivity('error', `Error cargando sesiones: ${err.message}`);
    if (_allSessions.length === 0) {
      listEl.innerHTML = `<div class="timeline-empty">Error cargando sesiones.<br>${esc(err.message)}</div>`;
    }
  }
}

function renderSessionList(sessions) {
  const listEl = document.getElementById('session-list');
  const query  = (document.getElementById('search-input')?.value ?? '').toLowerCase();

  const filtered = sessions.filter(s => {
    if (!query) return true;
    return (s.id || '').toLowerCase().includes(query) ||
           (s.created_at || '').toLowerCase().includes(query) ||
           (s.status || '').toLowerCase().includes(query);
  });

  if (filtered.length === 0) {
    listEl.innerHTML = `<div class="timeline-empty">${query ? 'Sin resultados para "' + esc(query) + '"' : 'No hay sesiones registradas'}</div>`;
    return;
  }

  listEl.innerHTML = filtered.map(s => makeSessionCard(s)).join('');
  listEl.querySelectorAll('.session-card').forEach(card => {
    card.addEventListener('click', () => selectSession(card.dataset.id));
  });
}

function makeSessionCard(s) {
  const isGen = s.status === 'generating';
  const statusLabel = {
    captured:   'Capturado',
    generating: 'Generando…',
    done:       'Listo',
  }[s.status] ?? s.status;

  return `<div class="session-card${isGen ? ' generating-card' : ''}${s.id === _selectedId ? ' active' : ''}" data-id="${esc(s.id)}">
    <div class="s-id">${esc(s.id)}</div>
    <div class="s-date">${fmtDate(s.created_at)}</div>
    <div class="s-meta">${s.total_events ?? 0} eventos · ${s.total_screenshots ?? 0} capturas</div>
    <span class="s-status status-${esc(s.status ?? 'captured')}">${esc(statusLabel)}</span>
  </div>`;
}

/* ── Select session ─────────────────────────────────────────── */
async function selectSession(id) {
  _selectedId = id;

  // Highlight card
  document.querySelectorAll('.session-card').forEach(c => {
    c.classList.toggle('active', c.dataset.id === id);
  });

  const panel = document.getElementById('main-panel');
  panel.innerHTML = '<div class="timeline-empty">Cargando…</div>';

  try {
    const session = await apiFetch(`/sessions/${encodeURIComponent(id)}`);
    renderDetail(session);
    setupPolling(session);
  } catch (err) {
    panel.innerHTML = `<div class="error-banner"><span>❌</span> Error cargando sesión: ${esc(err.message)}</div>`;
  }
}

/* ── Render detail ──────────────────────────────────────────── */
function renderDetail(session) {
  const panel = document.getElementById('main-panel');
  const id    = session.id;

  panel.innerHTML = `
    <div class="detail-header fade-in">
      <div>
        <div class="detail-title">Sesión de QA</div>
        <div class="detail-subtitle">${esc(id)}</div>
      </div>
      <div class="detail-actions">
        <span class="s-status status-${esc(session.status ?? 'captured')}">${esc(session.status ?? '—')}</span>
      </div>
    </div>

    <div class="tabs">
      <div class="tab active" data-tab="overview">📋 Resumen</div>
      <div class="tab" data-tab="events">🖱 Eventos <span class="tab-badge" id="events-count">${session.total_events ?? 0}</span></div>
      <div class="tab" data-tab="report">📄 Reporte</div>
    </div>

    <div class="tab-pane active" id="pane-overview"></div>
    <div class="tab-pane" id="pane-events"></div>
    <div class="tab-pane" id="pane-report"></div>
  `;

  // Tab switching
  panel.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      panel.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      panel.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const name = tab.dataset.tab;
      panel.querySelector(`#pane-${name}`)?.classList.add('active');
      if (name === 'events')  loadEventsTab(id);
      if (name === 'report')  loadReportTab(id);
    });
  });

  renderOverviewPane(session);
}

/* ── Overview pane ──────────────────────────────────────────── */
function renderOverviewPane(session) {
  const pane = document.getElementById('pane-overview');
  if (!pane) return;

  pane.innerHTML = `
    <div class="meta-grid fade-in">
      <div class="meta-card">
        <div class="label">Eventos</div>
        <div class="value">${session.total_events ?? 0}</div>
      </div>
      <div class="meta-card">
        <div class="label">Capturas</div>
        <div class="value">${session.total_screenshots ?? 0}</div>
      </div>
      <div class="meta-card">
        <div class="label">Inicio</div>
        <div class="value small">${fmtDate(session.created_at)}</div>
      </div>
      <div class="meta-card">
        <div class="label">Estado</div>
        <div class="value small">${esc(session.status ?? '—')}</div>
      </div>
    </div>
    <div id="overview-action"></div>
  `;

  renderOverviewAction(session);
}

function renderOverviewAction(session) {
  const el = document.getElementById('overview-action');
  if (!el) return;

  if (session.status === 'generating') {
    el.innerHTML = buildGeneratingPanel();
    startGenStepCycle();
    return;
  }

  if (session.status === 'done') {
    el.innerHTML = `
      <div class="btn-row">
        <button class="btn btn-success" id="btn-view-report">📄 Ver Reporte</button>
      </div>
    `;
    document.getElementById('btn-view-report')?.addEventListener('click', () => {
      document.querySelector('.tab[data-tab="report"]')?.click();
    });
    return;
  }

  if ((session.status ?? '').startsWith('error')) {
    el.innerHTML = `
      <div class="error-banner">
        <span>❌</span>
        <div><strong>Error en generación:</strong><br>${esc(session.status)}</div>
      </div>
      <div class="btn-row" style="margin-top:14px">
        <button class="btn btn-primary" id="btn-generate">✨ Reintentar Generación</button>
      </div>
    `;
    document.getElementById('btn-generate')?.addEventListener('click', () => generateDocs(session.id));
    return;
  }

  // Default — captured, ready to generate
  el.innerHTML = `
    <div class="btn-row">
      <button class="btn btn-primary" id="btn-generate">✨ Generar Documentación con AI</button>
    </div>
    <p class="muted" style="font-size:12px">Claude AI analizará los eventos capturados y generará casos de prueba, plan de pruebas y ticket Jira.</p>
  `;
  document.getElementById('btn-generate')?.addEventListener('click', () => generateDocs(session.id));
}

function buildGeneratingPanel() {
  return `
    <div class="generating-panel fade-in">
      <div class="generating-animation">
        <div class="gen-bar"></div><div class="gen-bar"></div><div class="gen-bar"></div>
        <div class="gen-bar"></div><div class="gen-bar"></div>
      </div>
      <div class="generating-title">Generando documentación…</div>
      <div class="generating-step" id="gen-step">${GEN_STEPS[0]}</div>
      <div class="progress-bar-wrap"><div class="progress-bar"></div></div>
    </div>
  `;
}

function startGenStepCycle() {
  clearInterval(_genStepTimer);
  let i = 0;
  _genStepTimer = setInterval(() => {
    i = (i + 1) % GEN_STEPS.length;
    const el = document.getElementById('gen-step');
    if (el) el.textContent = GEN_STEPS[i];
    else clearInterval(_genStepTimer);
  }, 4000);
}

function stopGenStepCycle() {
  clearInterval(_genStepTimer);
  _genStepTimer = null;
}

/* ── Generate docs ──────────────────────────────────────────── */
async function generateDocs(sessionId) {
  const btn = document.getElementById('btn-generate');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Iniciando…'; }

  showActivity('Generando documentación…');
  logActivity('info', `Iniciando generación para sesión ${sessionId}`);

  try {
    await apiFetch(`/sessions/${encodeURIComponent(sessionId)}/generate`, { method: 'POST' });
    logActivity('info', 'Generación iniciada, monitoreando progreso…');
    // Reload to show generating panel
    const session = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}`);
    renderDetail(session);
    setupPolling(session);
  } catch (err) {
    hideActivity();
    toast('error', 'Error al iniciar generación', err.message);
    logActivity('error', `Generación fallida: ${err.message}`);
    if (btn) { btn.disabled = false; btn.textContent = '✨ Generar Documentación con AI'; }
  }
}

/* ── Polling ────────────────────────────────────────────────── */
function setupPolling(session) {
  clearInterval(_pollTimer);
  if (session.status === 'generating') {
    _pollTimer = setInterval(() => pollSession(session.id), 3000);
  }
}

async function pollSession(id) {
  try {
    const session = await apiFetch(`/sessions/${encodeURIComponent(id)}`);
    // Update card in sidebar
    const idx = _allSessions.findIndex(s => s.id === id);
    if (idx >= 0) { _allSessions[idx] = session; renderSessionList(_allSessions); }

    if (session.status === 'done') {
      clearInterval(_pollTimer);
      stopGenStepCycle();
      hideActivity();
      toast('ok', '¡Documentación lista!', 'El reporte fue generado exitosamente.');
      logActivity('ok', `Documentación generada para sesión ${id}`);
      renderDetail(session);
      // Auto-open report tab
      setTimeout(() => document.querySelector('.tab[data-tab="report"]')?.click(), 300);
    } else if ((session.status ?? '').startsWith('error')) {
      clearInterval(_pollTimer);
      stopGenStepCycle();
      hideActivity();
      toast('error', 'Error en generación', session.status);
      logActivity('error', `Error generando sesión ${id}: ${session.status}`);
      renderDetail(session);
    }
  } catch (err) {
    // ignore poll errors silently
  }
}

/* ── Events tab ─────────────────────────────────────────────── */
async function loadEventsTab(sessionId) {
  const pane = document.getElementById('pane-events');
  if (!pane) return;

  // Use cache if available
  if (_cachedEvents[sessionId]) {
    _currentEvents = _cachedEvents[sessionId];
    renderEventsPane(pane, sessionId);
    return;
  }

  pane.innerHTML = '<div class="timeline-empty">Cargando eventos…</div>';
  try {
    const data = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}/events`);
    _currentEvents = Array.isArray(data) ? data : (data.events ?? []);
    _cachedEvents[sessionId] = _currentEvents;

    // Update tab badge
    const badge = document.getElementById('events-count');
    if (badge) badge.textContent = _currentEvents.length;

    renderEventsPane(pane, sessionId);
  } catch (err) {
    pane.innerHTML = `<div class="error-banner"><span>❌</span> Error cargando eventos: ${esc(err.message)}</div>`;
  }
}

function renderEventsPane(pane, sessionId) {
  const counts = {
    all:    _currentEvents.length,
    click:  _currentEvents.filter(e => e.type === 'click').length,
    key:    _currentEvents.filter(e => e.type === 'key').length,
    scroll: _currentEvents.filter(e => e.type === 'scroll').length,
  };

  pane.innerHTML = `
    <div class="timeline-filters fade-in">
      ${['all','click','key','scroll'].map(f => `
        <button class="filter-pill${_activeFilter === f ? ' active' : ''}" data-filter="${f}">
          ${{ all:'Todos', click:'Click', key:'Teclado', scroll:'Scroll' }[f]}
          <span style="opacity:.7;margin-left:4px">${counts[f]}</span>
        </button>`).join('')}
      <input class="timeline-search" id="timeline-search" placeholder="🔍 Buscar eventos…" type="search">
    </div>
    <div class="timeline" id="timeline-list"></div>
  `;

  pane.querySelectorAll('.filter-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      _activeFilter = btn.dataset.filter;
      pane.querySelectorAll('.filter-pill').forEach(b => b.classList.toggle('active', b.dataset.filter === _activeFilter));
      applyEventsFilter(sessionId);
    });
  });

  document.getElementById('timeline-search')?.addEventListener('input', e => {
    applyEventsFilter(sessionId, e.target.value);
  });

  applyEventsFilter(sessionId);
}

function applyEventsFilter(sessionId, query = '') {
  const tl = document.getElementById('timeline-list');
  if (!tl) return;

  const q = query.toLowerCase();
  let events = _currentEvents;
  if (_activeFilter !== 'all') events = events.filter(e => e.type === _activeFilter);
  if (q) events = events.filter(e =>
    (e.text || '').toLowerCase().includes(q) ||
    (e.type || '').toLowerCase().includes(q) ||
    (e.button || '').toLowerCase().includes(q)
  );

  if (events.length === 0) {
    tl.innerHTML = '<div class="timeline-empty">Sin eventos que coincidan con el filtro.</div>';
    return;
  }

  tl.innerHTML = events.map(e => buildTimelineItem(e, sessionId)).join('');
  tl.querySelectorAll('.screenshot-thumb').forEach(thumb => {
    const src = thumb.dataset.src;
    const cap = thumb.dataset.caption;
    thumb.addEventListener('click', () => openLightbox(src, cap));
  });
}

function buildTimelineItem(ev, sessionId) {
  const typeClass = { click: 'event-click', key: 'event-key', scroll: 'event-scroll' }[ev.type] || 'event-click';
  const typeLabel = { click: 'Click', key: 'Teclado', scroll: 'Scroll' }[ev.type] || ev.type;
  const typeIcon  = { click: 'C', key: 'K', scroll: 'S' }[ev.type] || '?';

  let detail = '';
  if (ev.type === 'click') {
    detail = `<span class="event-coord">(${ev.x ?? 0}, ${ev.y ?? 0})</span>${ev.button ? ` · botón ${esc(ev.button)}` : ''}`;
  } else if (ev.type === 'key') {
    detail = ev.text ? `Tecla: <code style="background:var(--surface-2);padding:1px 5px;border-radius:4px">${esc(ev.text)}</code>` : '';
  } else if (ev.type === 'scroll') {
    detail = `<span class="event-coord">(${ev.x ?? 0}, ${ev.y ?? 0})</span>`;
  }

  const screenshot = ev.screenshot
    ? `<div class="screenshot-thumb" data-src="/api/sessions/${encodeURIComponent(sessionId)}/screenshots/${encodeURIComponent(ev.screenshot)}" data-caption="${esc(ev.screenshot)}">
         <img src="/api/sessions/${encodeURIComponent(sessionId)}/screenshots/${encodeURIComponent(ev.screenshot)}" loading="lazy" alt="${esc(ev.screenshot)}">
         <div class="thumb-overlay">🔍</div>
       </div>`
    : '';

  return `
    <div class="timeline-item" data-type="${esc(ev.type)}">
      <div class="timeline-line">
        <div class="event-icon ${typeClass}">${typeIcon}</div>
      </div>
      <div class="timeline-content">
        <div class="event-header">
          <span class="event-type ${ev.type ?? ''}">${typeLabel}</span>
          <span class="event-ts">${fmtTime(ev.ts)}</span>
        </div>
        <div class="event-detail">${detail}</div>
        ${screenshot}
      </div>
    </div>
  `;
}

/* ── Report tab ─────────────────────────────────────────────── */
async function loadReportTab(sessionId) {
  const pane = document.getElementById('pane-report');
  if (!pane) return;

  if (_cachedReport[sessionId]) {
    renderReportPane(pane, _cachedReport[sessionId]);
    return;
  }

  pane.innerHTML = '<div class="timeline-empty">Cargando reporte…</div>';
  try {
    const md = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}/report`);
    _cachedReport[sessionId] = md;
    renderReportPane(pane, md);
  } catch (err) {
    if (err.message.includes('404') || err.message.includes('not found')) {
      pane.innerHTML = `<div class="timeline-empty">El reporte aún no ha sido generado.<br>Usa el botón "Generar Documentación" en la pestaña Resumen.</div>`;
    } else {
      pane.innerHTML = `<div class="error-banner"><span>❌</span> Error cargando reporte: ${esc(err.message)}</div>`;
    }
  }
}

function renderReportPane(pane, md) {
  const sections = parseReportSections(md);

  const SECTION_DEFS = [
    { key: 'all',   label: '🔖 Todo' },
    { key: 'cases', label: '✅ Casos de Prueba' },
    { key: 'plan',  label: '📋 Plan de Prueba' },
    { key: 'jira',  label: '🎫 Jira Ticket' },
  ];

  const tabs = SECTION_DEFS.filter(d => d.key === 'all' || sections.some(s => matchSection(s.title, d.key)));

  pane.innerHTML = `
    <div class="btn-row fade-in">
      <button class="btn btn-secondary" id="btn-toggle-raw">🔤 Ver Markdown</button>
      <button class="btn btn-secondary" id="btn-copy-md">📋 Copiar</button>
      <a class="btn btn-secondary" id="btn-download-md" download="report.md">⬇ Descargar</a>
    </div>
    <div class="report-section-tabs fade-in" id="rsec-tabs">
      ${tabs.map((d, i) => `<button class="rsec-tab${i === 0 ? ' active' : ''}" data-key="${d.key}">${d.label}</button>`).join('')}
    </div>
    <div class="report-rendered fade-in" id="report-rendered"></div>
    <div class="report-raw-wrap" id="report-raw">
      <textarea readonly>${esc(md)}</textarea>
      <div class="copy-row">
        <button class="btn btn-secondary" id="btn-copy-raw">📋 Copiar texto</button>
      </div>
    </div>
  `;

  // Section tab switching
  let activeKey = 'all';
  function showSection(key) {
    activeKey = key;
    pane.querySelectorAll('.rsec-tab').forEach(t => t.classList.toggle('active', t.dataset.key === key));
    const rendered = document.getElementById('report-rendered');
    const content = key === 'all' ? md : (sections.find(s => matchSection(s.title, key))?.content ?? '*Sección no encontrada*');
    rendered.innerHTML = renderMarkdown(content);
  }
  showSection('all');

  pane.querySelectorAll('.rsec-tab').forEach(tab => {
    tab.addEventListener('click', () => showSection(tab.dataset.key));
  });

  // Toggle raw
  let rawVisible = false;
  document.getElementById('btn-toggle-raw')?.addEventListener('click', function() {
    rawVisible = !rawVisible;
    document.getElementById('report-raw')?.classList.toggle('visible', rawVisible);
    this.textContent = rawVisible ? '👁 Ver Renderizado' : '🔤 Ver Markdown';
  });

  // Copy
  document.getElementById('btn-copy-md')?.addEventListener('click', function() {
    navigator.clipboard.writeText(md).then(() => {
      this.classList.add('btn-flash');
      setTimeout(() => this.classList.remove('btn-flash'), 400);
      toast('ok', 'Copiado', 'Markdown copiado al portapapeles');
    });
  });
  document.getElementById('btn-copy-raw')?.addEventListener('click', function() {
    navigator.clipboard.writeText(md).then(() => {
      this.classList.add('btn-flash');
      setTimeout(() => this.classList.remove('btn-flash'), 400);
    });
  });

  // Download
  const dlLink = document.getElementById('btn-download-md');
  if (dlLink) {
    const blob = new Blob([md], { type: 'text/markdown' });
    dlLink.href = URL.createObjectURL(blob);
  }
}

function matchSection(title, key) {
  const t = (title || '').toLowerCase();
  if (key === 'cases') return t.includes('caso') || t.includes('test case');
  if (key === 'plan')  return t.includes('plan');
  if (key === 'jira')  return t.includes('jira');
  return false;
}

function parseReportSections(md) {
  const lines = md.split('\n');
  const sections = [];
  let current = null;

  for (const line of lines) {
    if (line.startsWith('## ')) {
      if (current) sections.push(current);
      current = { title: line.slice(3).trim(), content: line + '\n' };
    } else if (current) {
      current.content += line + '\n';
    }
  }
  if (current) sections.push(current);
  return sections;
}

/* ── Markdown renderer ──────────────────────────────────────── */
function renderMarkdown(md) {
  if (!md) return '';
  let html = esc(md);

  // Headings
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm,  '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm,   '<h1>$1</h1>');

  // Bold / italic
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g,     '<em>$1</em>');

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Hr
  html = html.replace(/^---$/gm, '<hr>');

  // Tables
  html = html.replace(/((?:^\|.+\|\n)+)/gm, match => {
    const rows = match.trim().split('\n');
    if (rows.length < 2) return match;
    const headers = rows[0].split('|').filter((_, i, a) => i > 0 && i < a.length - 1);
    const isHeader = row => /^[\s|:-]+$/.test(row);
    const dataRows = rows.filter((r, i) => i !== 0 && !isHeader(r));
    const head = `<tr>${headers.map(h => `<th>${h.trim()}</th>`).join('')}</tr>`;
    const body = dataRows.map(row => {
      const cells = row.split('|').filter((_, i, a) => i > 0 && i < a.length - 1);
      return `<tr>${cells.map(c => `<td>${c.trim()}</td>`).join('')}</tr>`;
    }).join('');
    return `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
  });

  // Lists
  html = html.replace(/^(\s*- .+\n?)+/gm, match => {
    const items = match.trim().split('\n').map(l => `<li>${l.replace(/^\s*- /, '').trim()}</li>`).join('');
    return `<ul>${items}</ul>`;
  });
  html = html.replace(/^(\s*\d+\. .+\n?)+/gm, match => {
    const items = match.trim().split('\n').map(l => `<li>${l.replace(/^\s*\d+\. /, '').trim()}</li>`).join('');
    return `<ol>${items}</ol>`;
  });

  // Paragraphs (double newline → <p>)
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = '<p>' + html + '</p>';

  // Fix headings inside <p>
  html = html.replace(/<p>(<h[1-6]>)/g, '$1').replace(/(<\/h[1-6]>)<\/p>/g, '$1');
  html = html.replace(/<p>(<ul>)/g, '$1').replace(/(<\/ul>)<\/p>/g, '$1');
  html = html.replace(/<p>(<ol>)/g, '$1').replace(/(<\/ol>)<\/p>/g, '$1');
  html = html.replace(/<p>(<table>)/g, '$1').replace(/(<\/table>)<\/p>/g, '$1');
  html = html.replace(/<p>(<hr>)<\/p>/g, '$1');
  html = html.replace(/<p>\s*<\/p>/g, '');

  // Single newline → <br> inside paragraphs
  html = html.replace(/\n/g, '<br>');

  return html;
}

/* ── Search ─────────────────────────────────────────────────── */
document.getElementById('search-input')?.addEventListener('input', () => {
  renderSessionList(_allSessions);
});

/* ── Activity log toggle ────────────────────────────────────── */
document.getElementById('btn-log-toggle')?.addEventListener('click', function() {
  const log = document.querySelector('.activity-log');
  const open = log?.classList.toggle('open');
  this.classList.toggle('active', !!open);
});

document.getElementById('btn-log-clear')?.addEventListener('click', () => {
  document.getElementById('log-list').innerHTML = '';
});

/* ── Lightbox close button ──────────────────────────────────── */
document.getElementById('lightbox-close')?.addEventListener('click', closeLightbox);
document.getElementById('lightbox')?.addEventListener('click', e => {
  if (e.target === e.currentTarget) closeLightbox();
});

/* ── Auto refresh ───────────────────────────────────────────── */
setInterval(loadSessions, 15_000);

/* ── Init ───────────────────────────────────────────────────── */
(async function init() {
  await checkHealth();
  await loadSessions();
})();
