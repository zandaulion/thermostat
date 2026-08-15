/* Termometru — readings, charts and alerts. No chart library: the whole
   thing is one SVG path per series, which keeps the app self-contained and
   the payload a few kB rather than a few hundred. */
'use strict';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const api = (path, body, method) =>
  fetch(path, {
    method: method || (body ? 'POST' : 'GET'),
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  }).then(async (r) => {
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new ApiError(r.status, data.detail || `Cererea a eșuat (${r.status})`);
    return data;
  });

const RANGES = [
  { h: 24, label: '24 h' },
  { h: 24 * 7, label: '7 zile' },
  { h: 24 * 30, label: '30 zile' },
  { h: 24 * 365, label: '1 an' },
];

const state = {
  location: null, hours: 24, points: [], thresholds: {},
  showHumidity: false, sub: null,
};

const fmtTime = (iso, long) => new Date(iso).toLocaleString('ro-RO',
  long ? { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }
       : { hour: '2-digit', minute: '2-digit' });

/* ------------------------------------------------------------- readings -- */
function tempClass(t) {
  const th = state.thresholds;
  if (t == null) return '';
  if (t <= (th.cold_c ?? 8)) return 'c-cold';
  if (t >= (th.hot_c ?? 30)) return 'c-hot';
  if (t >= 24) return 'c-warm';
  return 'c-ok';
}

async function loadNow() {
  let data;
  try {
    data = await api('/api/now');
  } catch (ex) {
    if (ex instanceof ApiError && ex.status === 401) { showGate(''); return; }
    $('now-err').textContent = ex.message; $('now-err').hidden = false;
    return;
  }
  $('now-err').hidden = true;
  state.thresholds = data.thresholds || {};

  const rows = data.readings || [];
  $('cards').innerHTML = rows.length ? rows.map((r) => {
    const t = r.temperature;
    const heating = (r.status || '').toLowerCase() === 'on';
    const bits = [];
    if (r.humidity != null) bits.push(`${r.humidity.toFixed(0)}% umiditate`);
    if (r.setpoint != null) bits.push(`prag ${r.setpoint.toFixed(1)}°`);
    bits.push(r.age_minutes < 60 ? `acum ${r.age_minutes} min`
                                 : `acum ${Math.round(r.age_minutes / 60)} h`);
    return `<div class="tile${r.stale ? ' stale' : ''}">
        ${r.stale ? '<span class="badge stale">tace</span>'
                  : heating ? '<span class="badge heat">încălzire</span>' : ''}
        <div class="loc">${esc(r.location)}</div>
        <p class="t ${tempClass(t)}">${t == null ? '—' : t.toFixed(1)}<small>°C</small></p>
        <div class="meta">${esc(bits.join(' · '))}</div>
      </div>`;
  }).join('') : '<p class="empty">Nicio măsurătoare încă.</p>';

  if (!state.location && rows.length) state.location = rows[0].location;
  renderChips(rows.map((r) => r.location));
}

function renderChips(locs) {
  const uniq = [...new Set(locs)];
  $('loc-chips').innerHTML = uniq.map((l) =>
    `<button class="chip${l === state.location ? ' on' : ''}" data-loc="${esc(l)}">${esc(l)}</button>`
  ).join('') + `<button class="chip${state.showHumidity ? ' on' : ''}" data-hum="1">umiditate</button>`;
  $('range-chips').innerHTML = RANGES.map((r) =>
    `<button class="chip${r.h === state.hours ? ' on' : ''}" data-h="${r.h}">${r.label}</button>`
  ).join('');

  $('loc-chips').querySelectorAll('[data-loc]').forEach((b) =>
    b.addEventListener('click', () => { state.location = b.dataset.loc; loadHistory(); }));
  $('loc-chips').querySelectorAll('[data-hum]').forEach((b) =>
    b.addEventListener('click', () => { state.showHumidity = !state.showHumidity; drawChart(); renderChips(locs); }));
  $('range-chips').querySelectorAll('[data-h]').forEach((b) =>
    b.addEventListener('click', () => { state.hours = Number(b.dataset.h); loadHistory(); }));
}

/* ---------------------------------------------------------------- chart -- */
async function loadHistory() {
  renderChips(state.location ? [state.location] : []);
  try {
    const d = await api(`/api/history?location=${encodeURIComponent(state.location || '')}`
                      + `&hours=${state.hours}`);
    state.points = (d.points || []).filter((p) => p.temperature != null);
  } catch (ex) {
    state.points = [];
    if (ex instanceof ApiError && ex.status === 401) { showGate(''); return; }
  }
  await loadNow();          // keeps the location chips in step
  drawChart();
}

const W = 720, H = 300, PAD = { l: 38, r: 12, t: 12, b: 24 };

function drawChart() {
  const svg = $('chart');
  const pts = state.points;
  if (!pts.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle"
      class="axis">Nicio măsurătoare în acest interval</text>`;
    $('legend').innerHTML = '';
    return;
  }

  const xs = pts.map((p) => new Date(p.ts).getTime());
  const ts = pts.map((p) => p.temperature);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ts), y1 = Math.max(...ts);
  const padY = Math.max(0.5, (y1 - y0) * 0.12);
  y0 -= padY; y1 += padY;

  const X = (v) => PAD.l + ((v - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const Y = (v) => H - PAD.b - ((v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);

  // Shade the stretches where the heating was on, so the shape of the
  // temperature curve can be read against the thing causing it.
  let bands = '', start = null;
  pts.forEach((p, i) => {
    const on = (p.status || '').toLowerCase() === 'on';
    if (on && start === null) start = xs[i];
    if ((!on || i === pts.length - 1) && start !== null) {
      const a = X(start), b = X(xs[i]);
      if (b - a >= 0.6) bands += `<rect class="heatband" x="${a.toFixed(1)}" y="${PAD.t}"
        width="${(b - a).toFixed(1)}" height="${H - PAD.t - PAD.b}"/>`;
      start = null;
    }
  });

  const gridY = 4, grid = [], labels = [];
  for (let i = 0; i <= gridY; i++) {
    const v = y0 + (i / gridY) * (y1 - y0), y = Y(v);
    grid.push(`<line class="grid" x1="${PAD.l}" y1="${y.toFixed(1)}" x2="${W - PAD.r}" y2="${y.toFixed(1)}"/>`);
    labels.push(`<text class="axis" x="4" y="${(y + 4).toFixed(1)}">${v.toFixed(1)}</text>`);
  }
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const t = x0 + (i / ticks) * (x1 - x0);
    const anchor = i === 0 ? 'start' : i === ticks ? 'end' : 'middle';
    labels.push(`<text class="axis" x="${X(t).toFixed(1)}" y="${H - 6}"
      text-anchor="${anchor}">${esc(fmtTime(new Date(t).toISOString(), state.hours > 48))}</text>`);
  }

  const path = pts.map((p, i) =>
    `${i ? 'L' : 'M'}${X(xs[i]).toFixed(1)},${Y(p.temperature).toFixed(1)}`).join('');

  let hum = '';
  if (state.showHumidity) {
    const hv = pts.map((p) => p.humidity).filter((v) => v != null);
    if (hv.length) {
      const h0 = Math.min(...hv) - 2, h1 = Math.max(...hv) + 2;
      const HY = (v) => H - PAD.b - ((v - h0) / (h1 - h0 || 1)) * (H - PAD.t - PAD.b);
      let d = '', started = false;
      pts.forEach((p, i) => {
        if (p.humidity == null) { started = false; return; }
        d += `${started ? 'L' : 'M'}${X(xs[i]).toFixed(1)},${HY(p.humidity).toFixed(1)}`;
        started = true;
      });
      hum = `<path class="humline" d="${d}"/>`;
    }
  }

  svg.innerHTML = bands + grid.join('') + hum
    + `<path class="serie" stroke="var(--accent)" d="${path}"/>`
    + labels.join('')
    + `<line id="cursor" class="cursor" x1="0" y1="${PAD.t}" x2="0" y2="${H - PAD.b}" style="display:none"/>`;

  $('legend').innerHTML =
    `<span><i style="background:var(--accent)"></i>temperatură</span>`
    + (bands ? `<span><i style="background:var(--heat);opacity:.5"></i>încălzire pornită</span>` : '')
    + (hum ? `<span><i style="background:var(--hum)"></i>umiditate</span>` : '');

  attachCursor(svg, pts, xs, X);
}

/* Drag anywhere on the chart to read the value at that moment. */
function attachCursor(svg, pts, xs, X) {
  const cursor = svg.querySelector('#cursor');
  const readout = $('readout');
  const at = (evt) => {
    const r = svg.getBoundingClientRect();
    const cx = ((evt.touches ? evt.touches[0].clientX : evt.clientX) - r.left) / r.width * W;
    let best = 0, bd = Infinity;
    for (let i = 0; i < pts.length; i++) {
      const d = Math.abs(X(xs[i]) - cx);
      if (d < bd) { bd = d; best = i; }
    }
    const p = pts[best];
    cursor.setAttribute('x1', X(xs[best]));
    cursor.setAttribute('x2', X(xs[best]));
    cursor.style.display = '';
    readout.hidden = false;
    readout.innerHTML = `${esc(fmtTime(p.ts, true))}<br>`
      + `<b>${p.temperature.toFixed(1)}°C</b>`
      + (p.humidity != null ? ` · ${p.humidity.toFixed(0)}%` : '')
      + ((p.status || '').toLowerCase() === 'on' ? ' · încălzire' : '');
  };
  const hide = () => { cursor.style.display = 'none'; readout.hidden = true; };
  svg.onpointermove = at;
  svg.onpointerdown = at;
  svg.onpointerleave = hide;
  svg.ontouchmove = (e) => { at(e); };
  svg.ontouchend = hide;
}

/* --------------------------------------------------------------- push --- */
const b64ToBytes = (b64) => {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};
const standalone = () =>
  window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent || '');

async function getSubscription() {
  if (state.sub) return state.sub;
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    throw new Error('Acest browser nu acceptă notificări push.');
  }
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      throw new Error('Notificările sunt blocate. Permite-le pentru acest site.');
    }
    const { publicKey } = await api('/api/vapid');
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: b64ToBytes(publicKey),
    });
  }
  state.sub = sub.toJSON();
  await api('/api/push/subscribe', { subscription: state.sub });
  return state.sub;
}

$('btn-notify').addEventListener('click', async () => {
  const b = $('btn-notify');
  b.disabled = true; b.textContent = 'Se activează…';
  try {
    await getSubscription();
    b.textContent = 'Notificări active ✓';
  } catch (ex) {
    alert(ex.message);
    b.textContent = 'Activează notificările';
    if (isIOS() && !standalone()) {
      alert('Pe iPhone, adaugă întâi aplicația pe ecranul principal și '
          + 'deschide-o de acolo.');
    }
  } finally { b.disabled = false; }
});

$('btn-test').addEventListener('click', async () => {
  try {
    const sub = await getSubscription();
    const r = await api('/api/push/test', { subscription: sub });
    if (!r.delivered) throw new Error(`Serviciul de notificări a refuzat (${r.status}).`);
  } catch (ex) { alert(ex.message); }
});

/* ------------------------------------------------------------- install -- */
let installPrompt = null;
const DISMISSED = 'th-install-dismissed';
function refreshInstallBar() {
  const bar = $('install');
  if (standalone() || localStorage.getItem(DISMISSED)) { bar.hidden = true; return; }
  if (installPrompt) { $('btn-install').hidden = false; bar.hidden = false; }
  else if (isIOS()) {
    $('btn-install').hidden = true;
    $('install-title').textContent = 'Adaugă pe ecranul principal';
    $('install-note').textContent =
      'Apasă Distribuie, apoi „Adaugă la ecranul principal”. Pe iPhone '
      + 'alertele funcționează doar din aplicația instalată.';
    bar.hidden = false;
  } else bar.hidden = true;
}
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault(); installPrompt = e; refreshInstallBar();
});
window.addEventListener('appinstalled', () => { installPrompt = null; $('install').hidden = true; });
$('btn-install').addEventListener('click', async () => {
  if (!installPrompt) return;
  const p = installPrompt; installPrompt = null; $('install').hidden = true;
  p.prompt();
  const { outcome } = await p.userChoice;
  if (outcome !== 'accepted') { installPrompt = p; refreshInstallBar(); }
});
$('btn-install-dismiss').addEventListener('click', () => {
  try { localStorage.setItem(DISMISSED, '1'); } catch { /* private mode */ }
  $('install').hidden = true;
});

/* ---------------------------------------------------------- gate / boot -- */
function showGate(prefill) {
  $('gate').hidden = false; $('app').hidden = true;
  if (prefill) {
    $('invite-code').value = prefill;
    $('gate-title').textContent = 'Activează acest dispozitiv';
    $('gate-lead').textContent =
      'Această invitație înregistrează dispozitivul pe care o citești acum.';
  }
}
function showApp() { $('gate').hidden = true; $('app').hidden = false; refreshInstallBar(); }

$('form-code').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('gate-err'); err.hidden = true;
  const btn = $('btn-activate'); btn.disabled = true; btn.textContent = 'Se activează…';
  try {
    await api('/api/invites/redeem', { code: $('invite-code').value });
    history.replaceState({}, '', '/');
    showApp(); await start();
  } catch (ex) {
    err.textContent = ex.message; err.hidden = false;
    btn.disabled = false; btn.textContent = 'Activează';
  }
});

let started = false;
async function start() {
  if (started) return;
  started = true;
  if ('serviceWorker' in navigator) {
    try { await navigator.serviceWorker.register('/sw.js'); } catch { /* ignore */ }
    try {
      const reg = await navigator.serviceWorker.ready;
      const existing = await reg.pushManager.getSubscription();
      if (existing) {
        state.sub = existing.toJSON();
        $('btn-notify').textContent = 'Notificări active ✓';
      }
    } catch { /* not subscribed yet */ }
  }
  await loadHistory();
  api('/api/health').then((h) => {
    $('foot').textContent = h.readings
      ? `${h.readings.toLocaleString('ro-RO')} măsurători · citire la `
        + `${Math.round(h.poll_seconds / 60)} min`
      : '';
  }).catch(() => {});
  // Readings only change every POLL_SECONDS; refreshing faster is noise.
  setInterval(loadNow, 120000);
}

async function boot() {
  const invite = location.pathname.match(/^\/i\/(.+)$/);
  if (invite) { showGate(decodeURIComponent(invite[1])); return; }
  try {
    await api('/api/me');
    showApp();
    await start();
  } catch (ex) {
    showGate('');
    if (!(ex instanceof ApiError && ex.status === 401)) {
      $('gate-err').textContent = ex.message; $('gate-err').hidden = false;
    }
  }
}
boot();
