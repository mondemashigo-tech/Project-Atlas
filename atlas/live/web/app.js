/* Atlas Live frontend. Vanilla JS, no build step. Renders real data from the API
   and the SSE event spine. Never invents activity: idle is idle. */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (t, c, h) => { const n = document.createElement(t); if (c) n.className = c; if (h != null) n.innerHTML = h; return n; };
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));
const api = async (p, opt) => { const r = await fetch(p, opt); if (!r.ok) throw new Error(p + ' ' + r.status); return r.json(); };
const timeShort = ts => { try { return new Date(ts).toLocaleTimeString(); } catch { return ts || ''; } };

const State = {
  events: [], lastSeq: 0, byType: new Set(), agents: [], runner: { running: false },
  paused: false, filters: { agent: '', type: '', severity: '', q: '' },
};

/* ---------------- SSE ---------------- */
let es = null, agentRefresh = 0;
function connectSSE() {
  if (es) es.close();
  es = new EventSource('/api/events/stream?after_seq=' + State.lastSeq);
  es.onopen = () => setConn(true);
  es.onerror = () => setConn(false);        // EventSource auto-reconnects (Last-Event-ID)
  es.onmessage = ev => { try { onEvent(JSON.parse(ev.data)); } catch {} };
}
function setConn(on) {
  const c = $('#conn'); c.classList.toggle('on', on); c.classList.toggle('off', !on);
  $('#conn-label').textContent = on ? 'live' : 'reconnecting…';
}
function onEvent(e) {
  if (e.seq && e.seq <= State.lastSeq) return;
  if (e.seq) State.lastSeq = e.seq;
  State.events.push(e); if (State.events.length > 3000) State.events.shift();
  if (e.event_type) State.byType.add(e.event_type);
  const running = e.status === 'started' || (e.event_type === 'experiment_started');
  if (e.event_type === 'experiment_completed') $('#atlas-dot').classList.remove('live');
  else if (running) $('#atlas-dot').classList.add('live');
  if (currentView() === 'console' && !State.paused) appendConsoleRow(e);
  const now = Date.now();                    // throttle chamber refresh
  if (e.agent_id && now - agentRefresh > 400) { agentRefresh = now; refreshAgents(); }
}

/* ---------------- router ---------------- */
const currentView = () => (location.hash.replace('#', '') || 'chamber').split('/')[0];
function route() {
  const v = currentView();
  $$('.nav-link').forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + v));
  const views = { chamber, console: consoleView, experiments, registry, graveyard, knowledge, governance, brief };
  (views[v] || chamber)();
}
window.addEventListener('hashchange', route);

/* ---------------- Council Chamber ---------------- */
async function refreshAgents() {
  try { const r = await api('/api/agents'); State.agents = r.agents; State.runner = r.runner;
    if (currentView() === 'chamber') paintAgents(); } catch {}
}
function paintAgents() {
  const grid = $('#agent-grid'); if (!grid) return;
  grid.innerHTML = '';
  State.agents.forEach(a => {
    const active = a.state !== 'idle';
    const card = el('div', 'agent grp-' + a.group);
    card.innerHTML =
      `<div class="agent-top"><span class="agent-badge"></span>
        <span class="agent-name">${esc(a.name)}</span></div>
       <div class="agent-role">${esc(a.role)}</div>
       <div class="agent-state ${active ? 'state-active' : 'state-idle'}"><span class="dot"></span>${esc(a.state)}</div>
       <div class="agent-detail">${active ? esc(a.detail || '') : (a.last_activity ? 'last: ' + timeShort(a.last_activity) : 'no activity yet')}</div>`;
    card.onclick = () => openAgent(a.id);
    grid.appendChild(card);
  });
  const orb = $('#core-orb'); if (orb) orb.classList.toggle('idle', !State.runner.running);
  const cs = $('#core-status'); if (cs) cs.textContent = State.runner.running ? ('researching ' + (State.runner.current || '')) : 'idle';
}
async function chamber() {
  const v = $('#view'); v.innerHTML = '';
  v.appendChild(el('h1', 'page-title', 'Council Chamber'));
  v.appendChild(el('p', 'page-sub', 'The real council. State comes from live events — idle means idle.'));
  const core = el('div', 'chamber-core',
    `<div class="core-orb idle" id="core-orb"></div><strong>ATLAS</strong>
     <span class="muted" id="core-status">idle</span>
     <div class="run-panels">
       <div class="run-panel">
         <div class="run-label">Run an existing hypothesis</div>
         <div class="row">
           <select class="input" id="run-hyp" style="min-width:260px"><option value="">loading…</option></select>
           <button class="btn primary" id="run-btn">Run council</button></div>
       </div>
       <div class="run-panel">
         <div class="run-label">Test a new idea — describe it in plain English</div>
         <div class="row">
           <input class="input" id="idea-txt" style="flex:1;min-width:260px"
             placeholder="e.g. sweep the prior swing high then enter short on a bearish close back inside range">
           <button class="btn primary" id="idea-btn">Scout &amp; test</button></div>
       </div>
     </div>
     <span class="muted" id="run-msg" style="margin-top:8px;display:block"></span>`);
  v.appendChild(core);
  v.appendChild(el('div', 'agent-grid', '<div id="agent-grid"></div>'));
  v.querySelector('.agent-grid').id = 'agent-grid';
  await refreshAgents(); paintAgents();
  loadHypList();
  $('#run-btn').onclick = triggerRun;
  $('#idea-btn').onclick = triggerIdea;
}
async function loadHypList() {
  try {
    const r = await api('/api/hypotheses'); const sel = $('#run-hyp');
    const items = r.hypotheses || [];
    sel.innerHTML = items.length
      ? '<option value="">— pick a hypothesis —</option>' + items.map(h => `<option value="${esc(h.name)}">${esc(h.name)}</option>`).join('')
      : '<option value="">no hypothesis files found under hypotheses/</option>';
  } catch (e) { $('#run-hyp').innerHTML = '<option value="">could not load list</option>'; }
}
async function triggerRun() {
  const name = $('#run-hyp').value; const msg = $('#run-msg');
  if (!name) { msg.textContent = 'pick a hypothesis from the list'; return; }
  msg.textContent = 'starting…';
  try {
    const r = await api('/api/research/run', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hypothesis: name }) });
    msg.textContent = r.started ? 'running ' + r.hypothesis + ' — watch the console' : (r.reason || 'not started');
    location.hash = 'console';
  } catch (e) { msg.textContent = 'error: ' + e.message; }
}
async function triggerIdea() {
  const idea = $('#idea-txt').value.trim(); const msg = $('#run-msg');
  if (idea.length < 8) { msg.textContent = 'describe the idea in a bit more detail'; return; }
  msg.textContent = 'scouting your idea…';
  try {
    const r = await api('/api/research/idea', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ idea }) });
    if (r.started) { msg.textContent = 'scouting + testing your idea — watch the console'; location.hash = 'console'; }
    else { msg.textContent = r.reason || 'not started'; }
  } catch (e) { msg.textContent = 'error: ' + e.message; }
}

/* ---------------- Live Console ---------------- */
function consoleView() {
  const v = $('#view'); v.innerHTML = '';
  v.appendChild(el('h1', 'page-title', 'Live Console'));
  v.appendChild(el('p', 'page-sub', 'Structured system events — operational status, actions, decisions. Not private reasoning.'));
  const agents = ['', ...State.agents.map(a => a.name)];
  const types = ['', ...[...State.byType].sort()];
  const tools = el('div', 'console-tools');
  tools.innerHTML =
    `<select class="input" id="f-agent">${agents.map(a => `<option value="${esc(a)}">${a || 'all agents'}</option>`).join('')}</select>
     <select class="input" id="f-type">${types.map(t => `<option value="${esc(t)}">${t || 'all types'}</option>`).join('')}</select>
     <select class="input" id="f-sev"><option value="">all</option><option>info</option><option>warning</option><option>error</option></select>
     <input class="input" id="f-q" placeholder="search…" style="flex:1;min-width:120px">
     <button class="btn" id="f-pause">${State.paused ? 'Resume' : 'Pause'}</button>`;
  v.appendChild(tools);
  const con = el('div', 'console', '<div id="con-list"></div>');
  v.appendChild(con);
  ['f-agent', 'f-type', 'f-sev', 'f-q'].forEach(id => $('#' + id).oninput = e => {
    State.filters = { agent: $('#f-agent').value, type: $('#f-type').value, severity: $('#f-sev').value, q: $('#f-q').value.toLowerCase() };
    paintConsole();
  });
  $('#f-pause').onclick = () => { State.paused = !State.paused; $('#f-pause').textContent = State.paused ? 'Resume' : 'Pause'; if (!State.paused) paintConsole(); };
  paintConsole();
}
function matchFilter(e) {
  const f = State.filters;
  if (f.agent && e.agent_name !== f.agent) return false;
  if (f.type && e.event_type !== f.type) return false;
  if (f.severity && e.severity !== f.severity) return false;
  if (f.q && !((e.summary || '') + (e.title || '') + (e.event_type || '')).toLowerCase().includes(f.q)) return false;
  return true;
}
function rowHtml(e) {
  const refs = (e.evidence_refs || []).filter(r => /^(EXP|HYP)-/.test(r))
    .map(r => `<a href="#experiments/${esc(r)}" onclick="openRef('${esc(r)}')">${esc(r)}</a>`).join(' ');
  return `<div class="ev sev-${esc(e.severity)}" title="${esc(e.title)}">
    <span class="ev-time">${timeShort(e.timestamp_utc)}</span>
    <span class="ev-agent">${esc(e.agent_name || '')}</span>
    <span class="ev-type">${esc(e.event_type)}</span>
    <span class="ev-sum">${esc(e.summary || e.title || '')}</span>
    <span class="ev-refs">${refs}</span></div>`;
}
function paintConsole() {
  const list = $('#con-list'); if (!list) return;
  const rows = State.events.filter(matchFilter).slice(-400).reverse();
  list.innerHTML = rows.length ? rows.map(rowHtml).join('')
    : '<div class="empty">No events match. Trigger a run from the Council Chamber to see live activity.</div>';
}
function appendConsoleRow(e) {
  const list = $('#con-list'); if (!list || !matchFilter(e)) return;
  list.insertAdjacentHTML('afterbegin', rowHtml(e));
}
window.openRef = id => { location.hash = 'experiments'; setTimeout(() => openExperiment(id), 30); };

/* ---------------- Experiments ---------------- */
async function experiments() {
  const v = $('#view'); v.innerHTML = '';
  v.appendChild(el('h1', 'page-title', 'Experiments'));
  let ov, list;
  try { ov = await api('/api/overview'); } catch {}
  try { list = (await api('/api/experiments?limit=100')).experiments; } catch { list = []; }
  if (ov) v.appendChild(funnel(ov));
  if (!list.length) { v.appendChild(el('div', 'empty', 'No experiments yet.')); return; }
  const t = el('div', 'scroll-x');
  t.innerHTML = `<table><thead><tr><th>ID</th><th>verdict</th><th>trades</th><th>PF</th><th>window</th><th>when</th></tr></thead><tbody>${
    list.map(e => `<tr class="click" onclick="openExperiment('${esc(e.id)}')">
      <td class="mono">${esc(e.id)}</td><td><span class="pill ${esc(e.verdict)}">${esc(e.verdict)}</span></td>
      <td>${e.trades ?? '—'}</td><td>${e.profit_factor ?? '—'}</td><td>${esc(e.window)}</td>
      <td class="muted">${timeShort(e.created_at)}</td></tr>`).join('')}</tbody></table>`;
  v.appendChild(t);
}
function funnel(ov) {
  const c = ov.counts || {};
  const cand = (ov.decision_tally && 0) || 0;
  const stages = [
    ['Generated', c.hypotheses ?? 0, false],
    ['Tested', c.experiments ?? 0, false],
    ['Buried', ov.graveyard_count ?? 0, false],
    ['Candidates', c.strategies ?? 0, false],
    ['Walk-forward', '—', true],
    ['Live', 0, false],
  ];
  const wrap = el('div', 'funnel');
  stages.forEach(([label, n, planned]) => {
    const s = el('div', 'fstage' + (planned ? ' planned' : ''));
    s.innerHTML = `<div class="n">${n}</div><div class="muted">${label}</div>`;
    wrap.appendChild(s);
  });
  return wrap;
}
window.openExperiment = async id => {
  const d = await api('/api/experiments/' + id).catch(() => null);
  if (!d) return;
  const e = d.experiment, m = e.metrics || {};
  const ladder = (d.decisions || []).map(x =>
    `<tr><td>${esc(x.phase)}</td><td>${esc(x.agent)}</td><td>${esc(x.decision)}</td><td class="muted">${esc((x.evidence || '').slice(0, 120))}</td></tr>`).join('');
  const tl = (d.events || []).map(x =>
    `<div class="ev"><span class="ev-time">${timeShort(x.timestamp_utc)}</span><span class="ev-agent">${esc(x.agent_name || '')}</span><span class="ev-type">${esc(x.event_type)}</span><span class="ev-sum">${esc(x.summary || '')}</span><span></span></div>`).join('');
  const mc = e.monte_carlo ? `<pre class="mono">${esc(JSON.stringify(e.monte_carlo, null, 1)).slice(0, 900)}</pre>` : '<div class="muted">Monte-Carlo data unavailable for this record.</div>';
  drawer(`<button class="close-x" onclick="closeDrawer()">×</button>
    <h2 class="page-title">${esc(e.id)} <span class="pill ${esc(e.verdict)}">${esc(e.verdict)}</span></h2>
    <p class="muted mono">${esc(e.hypothesis_id)} · ${esc(e.window)} · engine ${esc(e.engine_version)}</p>
    <div class="cards grid" style="margin:10px 0">
      <div class="card"><h3>trades</h3><div class="stat">${m.trades ?? '—'}</div></div>
      <div class="card"><h3>profit factor</h3><div class="stat">${m.profit_factor ?? '—'}</div></div>
      <div class="card"><h3>expectancy R</h3><div class="stat">${m.expectancy_r ?? '—'}</div></div></div>
    <h3 class="page-sub">Decision ladder</h3>
    <div class="scroll-x"><table><thead><tr><th>phase</th><th>agent</th><th>decision</th><th>evidence</th></tr></thead><tbody>${ladder || '<tr><td colspan=4 class=muted>none</td></tr>'}</tbody></table></div>
    <h3 class="page-sub" style="margin-top:16px">Monte Carlo</h3>${mc}
    <h3 class="page-sub" style="margin-top:16px">Event timeline</h3><div class="console">${tl || '<div class=empty>no events</div>'}</div>
    <p class="muted" style="margin-top:14px">Equity-curve rendering is unavailable — raw per-bar equity is not stored on the experiment record.</p>`);
};

/* ---------------- simple record tables ---------------- */
async function simpleTable(title, sub, path, key, cols) {
  const v = $('#view'); v.innerHTML = '';
  v.appendChild(el('h1', 'page-title', title));
  if (sub) v.appendChild(el('p', 'page-sub', sub));
  let rows; try { rows = (await api(path))[key]; } catch { rows = []; }
  if (!rows || !rows.length) { v.appendChild(el('div', 'empty', 'Nothing recorded yet.')); return; }
  const t = el('div', 'scroll-x');
  t.innerHTML = `<table><thead><tr>${cols.map(c => `<th>${c[0]}</th>`).join('')}</tr></thead><tbody>${
    rows.map(r => `<tr>${cols.map(c => `<td>${esc(typeof c[1] === 'function' ? c[1](r) : r[c[1]])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  v.appendChild(t);
}
const graveyard = () => simpleTable('Graveyard', 'Buried hypotheses and why. Failure is data.', '/api/graveyard', 'graveyard',
  [['hypothesis', 'hypothesis_id'], ['title', 'title'], ['reason', 'reason'], ['when', 'at']]);
const registry = () => simpleTable('Registry', 'Candidates. Promotion to capital is human-gated — never automatic.', '/api/registry', 'registry',
  [['strategy', 'strategy_id'], ['status', 'status'], ['version', 'version'], ['experiments', r => (r.experiment_ids || []).join(', ')]]);
const knowledge = () => simpleTable('Knowledge', 'Ingested notes, tagged.', '/api/knowledge', 'knowledge',
  [['title', 'title'], ['tags', r => (r.topic_tags || []).join(', ')], ['summary', r => (r.summary || '').slice(0, 120)]]);
async function governance() {
  const v = $('#view'); v.innerHTML = '';
  v.appendChild(el('h1', 'page-title', 'Governance'));
  v.appendChild(el('p', 'page-sub', 'Out-of-sample look budget & multiple-testing discipline — the p-hacking guard.'));
  let g; try { g = await api('/api/governance'); } catch { g = {}; }
  const looks = g.oos_looks || {};
  const rows = Object.entries(looks).map(([s, n]) => `<tr><td class="mono">${esc(s)}</td><td>${n}</td></tr>`).join('');
  v.appendChild(el('div', 'card', `<h3>graveyard total</h3><div class="stat">${g.graveyard_count ?? 0}</div>`));
  const t = el('div', 'scroll-x'); t.style.marginTop = '14px';
  t.innerHTML = `<table><thead><tr><th>snapshot</th><th>OOS looks</th></tr></thead><tbody>${rows || '<tr><td colspan=2 class=muted>no snapshots yet</td></tr>'}</tbody></table>`;
  v.appendChild(t);
}

/* ---------------- Morning brief ---------------- */
async function brief() {
  const v = $('#view'); v.innerHTML = '';
  v.appendChild(el('h1', 'page-title', 'Morning Brief'));
  let b; try { b = await api('/api/reports/morning-brief'); } catch { b = null; }
  if (!b) { v.appendChild(el('div', 'empty', 'Unavailable.')); return; }
  if (b.no_activity) { v.appendChild(el('div', 'empty', esc(b.text))); return; }
  v.appendChild(el('div', 'card', `<h3>last ${b.window_hours}h</h3><div class="stat">${esc(b.headline)}</div>`));
  const p = el('p'); p.style.margin = '14px 0'; p.textContent = b.text; v.appendChild(p);
  const grid = el('div', 'cards grid');
  [['completed', b.generated], ['rejected', b.rejected], ['advanced', b.advanced],
   ['warnings', b.warnings], ['errors', b.errors], ['awaiting review', b.candidates_awaiting_review]]
    .forEach(([k, n]) => grid.appendChild(el('div', 'card', `<h3>${k}</h3><div class="stat">${n ?? 0}</div>`)));
  v.appendChild(grid);
  const say = el('button', 'btn', '🔊 Read it to me'); say.style.marginTop = '14px';
  say.onclick = () => speak(b.text); v.appendChild(say);
}

/* ---------------- agent drawer ---------------- */
async function openAgent(id) {
  const d = await api('/api/agents/' + id).catch(() => null); if (!d) return;
  const acts = (d.activity || []).slice(0, 20).map(e =>
    `<div class="ev"><span class="ev-time">${timeShort(e.timestamp_utc)}</span><span class="ev-type">${esc(e.event_type)}</span><span class="ev-sum">${esc(e.summary || e.title || '')}</span></div>`).join('');
  drawer(`<button class="close-x" onclick="closeDrawer()">×</button>
    <h2 class="page-title">${esc(d.name)}</h2>
    <p class="page-sub">${esc(d.role)}</p>
    <div class="agent-state ${d.state !== 'idle' ? 'state-active' : 'state-idle'}"><span class="dot"></span>${esc(d.state)}</div>
    <h3 class="page-sub" style="margin-top:16px">Recent activity</h3>
    <div class="console">${acts || '<div class=empty>No recorded activity yet.</div>'}</div>
    <form onsubmit="askAgent(event,'${esc(id)}')" style="margin-top:14px" class="row">
      <input class="input" id="agent-q" placeholder="Ask ${esc(d.name)} about its work…" style="flex:1">
      <button class="btn primary">Ask</button></form>
    <div id="agent-a" class="msg atlas" style="display:none;margin-top:10px"></div>`);
}
window.askAgent = async (ev, id) => {
  ev.preventDefault(); const q = $('#agent-q').value.trim(); if (!q) return;
  const box = $('#agent-a'); box.style.display = 'block'; box.textContent = '…';
  try { const r = await api('/api/agents/' + id + '/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: q }) });
    box.innerHTML = esc(r.answer) + citesHtml(r.citations); } catch (e) { box.textContent = 'error: ' + e.message; }
};
function drawer(html) { $('#drawer-inner').innerHTML = html; $('#drawer').hidden = false; }
window.closeDrawer = () => { $('#drawer').hidden = true; };
$('#drawer').addEventListener('click', e => { if (e.target.id === 'drawer') closeDrawer(); });

/* ---------------- chat ---------------- */
function citesHtml(cites) {
  if (!cites || !cites.length) return '';
  return `<div class="cites">${cites.map(c => /^(EXP|HYP)-/.test(c)
    ? `<a href="#" onclick="openRef('${esc(c)}');return false">${esc(c)}</a>` : `<span class="badge">${esc(c)}</span>`).join('')}</div>`;
}
function addMsg(kind, text, cites, tag) {
  const m = el('div', 'msg ' + kind, (tag ? `<div class="tag">${esc(tag)}</div>` : '') + esc(text) + citesHtml(cites));
  $('#chat-body').appendChild(m); $('#chat-body').scrollTop = 1e9; return m;
}
$('#chat-form').addEventListener('submit', async e => {
  e.preventDefault(); const inp = $('#chat-input'); const q = inp.value.trim(); if (!q) return;
  addMsg('user', q); inp.value = '';
  const thinking = addMsg('atlas', '…');
  try {
    const r = await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: q, transcript_source: 'text' }) });
    thinking.remove();
    const tag = r.grounded ? (r.llm_used ? 'grounded · phrased' : 'grounded · records') : 'no recorded evidence';
    addMsg('atlas', r.answer, r.citations, tag);
    if ($('#tts-toggle').checked) speak(r.answer);
  } catch (e) { thinking.textContent = 'error: ' + e.message; }
});
$('#chat-toggle').onclick = () => $('#chat-dock').classList.toggle('collapsed');

/* ---------------- voice (read-only) ---------------- */
function speak(text) {
  if (!('speechSynthesis' in window)) return;
  speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.rate = 1.02; speechSynthesis.speak(u);
}
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  const rec = new SR(); rec.lang = 'en-ZA'; rec.interimResults = true;
  let listening = false;
  $('#mic-btn').onclick = () => { if (listening) { rec.stop(); return; } try { rec.start(); } catch {} };
  rec.onstart = () => { listening = true; $('#mic-btn').classList.add('listening'); $('#mic-state').textContent = 'listening…'; };
  rec.onend = () => { listening = false; $('#mic-btn').classList.remove('listening'); $('#mic-state').textContent = 'review, then Send'; };
  rec.onerror = e => { $('#mic-state').textContent = 'mic: ' + e.error; };
  rec.onresult = e => { $('#chat-input').value = [...e.results].map(r => r[0].transcript).join(''); };
} else {
  $('#mic-btn').disabled = true; $('#mic-btn').title = 'no speech recognition in this browser';
}

/* ---------------- boot ---------------- */
(async function boot() {
  try { const h = await api('/api/system/health'); if (h.status === 'ok') $('#atlas-dot').title = 'connected'; } catch {}
  await refreshAgents();
  connectSSE();
  route();
})();
