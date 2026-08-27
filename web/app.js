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

const LAST_LOCATION = 'th-last-location';
const LAST_MODE = 'th-last-mode';        // 'all' | 'one'

const RANGES = [
  { h: 24, label: '24 h' },
  { h: 24 * 7, label: '7 zile' },
  { h: 24 * 30, label: '30 zile' },
  { h: 24 * 365, label: '1 an' },
];

const state = {
  location: null, hours: 24, points: [], thresholds: {},
  showHumidity: false, sub: null,
  // Compare mode: every location on one set of axes. `series` is
  // [{location, points, color}], one entry per sensor. Defaults on -- the
  // whole house at a glance is the more useful first screen, and picking a
  // single property from there is one tap. The last choice is remembered.
  compare: (() => {
    try { return (localStorage.getItem(LAST_MODE) || 'all') === 'all'; }
    catch { return true; }        // private mode
  })(),
  series: [],
  locations: [],          // sorted, stable -- drives colorFor()
};

const SERIES_COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)',
                       'var(--s4)', 'var(--s5)', 'var(--s6)'];
const KNOWN_LOCATIONS = 'th-locations';

/* One colour per property, everywhere it appears -- tile, chip, chart line,
   readout. The assignment is by position in the *sorted, complete* list of
   locations rather than by whatever order a response happens to arrive in,
   so a sensor going quiet does not silently re-colour the others.
   Deliberately not a hash of the name: with six colours and four properties
   a hash collides more often than not, and two properties sharing a colour
   defeats the point of having them. */
function colorFor(loc) {
  const i = state.locations.indexOf(loc);
  return i < 0 ? 'var(--muted)' : SERIES_COLORS[i % SERIES_COLORS.length];
}

/* The authoritative list includes locations with no current reading, which is
   what keeps the mapping stable. Cached so the colours survive a cold start
   offline, where /api/locations is unreachable but tiles still render. */
async function ensureLocations(seed) {
  if (!state.locations.length) {
    try { state.locations = JSON.parse(localStorage.getItem(KNOWN_LOCATIONS)) || []; }
    catch { /* private mode */ }
  }
  let fresh = null;
  try { fresh = (await api('/api/locations')).locations; } catch { /* offline */ }
  const merged = [...new Set([...(fresh || state.locations), ...(seed || [])])].sort();
  if (merged.join('\u0000') !== state.locations.join('\u0000')) {
    state.locations = merged;
    try { localStorage.setItem(KNOWN_LOCATIONS, JSON.stringify(merged)); } catch { /* ignore */ }
  }
}

const fmtTime = (iso, long) => new Date(iso).toLocaleString('ro-RO',
  long ? { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }
       : { hour: '2-digit', minute: '2-digit' });

/* ------------------------------------------------------------- readings -- */
/* A battery outline whose fill tracks the charge, so it reads at a glance
   without needing the number beside it. */
/* A sensor that died days ago used to read "acum 2867 min". Once age is
   measured against the sensor's own clock it can be arbitrarily large, so it
   needs a unit that stays readable at that range. */
function formatAge(min) {
  if (min == null || !isFinite(min)) return 'fără dată';
  if (min < 60) return `acum ${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `acum ${h} h`;
  return `acum ${Math.round(h / 24)} zile`;
}

function batteryIcon(pct) {
  const w = Math.max(1, Math.round((Math.max(0, Math.min(100, pct)) / 100) * 12));
  return `<svg viewBox="0 0 22 12" width="17" height="10" aria-hidden="true">
      <rect x="0.5" y="0.5" width="17" height="11" rx="2.5"
            fill="none" stroke="currentColor"/>
      <rect x="18.5" y="4" width="3" height="4" rx="1" fill="currentColor"/>
      <rect x="2.5" y="2.5" width="${w}" height="7" rx="1" fill="currentColor"/>
    </svg>`;
}

function tempClass(t) {
  // Only the thresholds that actually raise an alert get a colour. An
  // arbitrary "warm above 24" band made a normal summer indoor reading look
  // like a problem, which trains you to ignore the colour entirely.
  const th = state.thresholds;
  if (t == null) return '';
  if (t <= (th.cold_c ?? 8)) return 'c-cold';
  if (t >= (th.hot_c ?? 30)) return 'c-hot';
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
  await ensureLocations(rows.map((r) => r.location));
  $('cards').innerHTML = rows.length ? rows.map((r) => {
    const t = r.temperature;
    const heating = (r.status || '').toLowerCase() === 'on';
    const lowBatt = r.battery != null && r.battery <= (state.thresholds.battery_pct ?? 15);

    const bits = [];
    if (r.humidity != null) bits.push(`${r.humidity.toFixed(0)}% umiditate`);
    if (r.setpoint != null) bits.push(`prag ${r.setpoint.toFixed(1)}°`);
    bits.push(formatAge(r.age_minutes));

    // Several badges can apply at once -- a silent sensor with a flat battery
    // is the most likely combination, and is exactly when both matter.
    const badges = [];
    if (lowBatt) {
      badges.push(`<span class="badge batt" title="Baterie ${r.battery.toFixed(0)}%">`
        + batteryIcon(r.battery) + `${r.battery.toFixed(0)}%</span>`);
    }
    // "deconectat" and "tace" are different faults: the first is the cloud
    // telling us the device is gone, the second is our own silence timer.
    if (r.offline) badges.push('<span class="badge stale">deconectat</span>');
    else if (r.stale) badges.push('<span class="badge stale">tace</span>');
    else if (heating) badges.push('<span class="badge heat">încălzire</span>');

    // The rail carries which property this is; the number keeps its own
    // colour, which says how hot it is. Two different questions, two channels.
    return `<div class="tile${(r.stale || r.offline) ? ' stale' : ''}"
        style="--loc-color:${colorFor(r.location)}">
        <div class="tile-head">
          <div class="loc">${esc(r.location)}</div>
          ${badges.length ? `<div class="badges">${badges.join('')}</div>` : ''}
        </div>
        <p class="t ${tempClass(t)}">${t == null ? '—' : t.toFixed(1)}<small>°C</small></p>
        <div class="meta">${esc(bits.join(' · '))}</div>
      </div>`;
  }).join('') : '<p class="empty">Nicio măsurătoare încă.</p>';

  if (!state.location && rows.length) {
    // Your own last choice wins, then the server's default, then whatever
    // comes first -- so each person settles on their own view after one tap.
    const known = (l) => l && rows.some((r) => r.location === l);
    let saved = null;
    try { saved = localStorage.getItem(LAST_LOCATION); } catch { /* private mode */ }
    state.location = known(saved) ? saved
      : known(data.default_location) ? data.default_location
      : rows[0].location;
  }
  renderChips(rows.map((r) => r.location));
}

function renderChips(locs) {
  const uniq = [...new Set(locs)];
  // "toate" is a mode, not a place, so it sits first and is styled as the
  // odd one out. Humidity is hidden while comparing: four humidity lines on a
  // second scale is not a comparison, it is a mess.
  // The swatches preview what the mode does: one dot per property, in the
  // colours they will appear in, overlapped so they read as a set rather than
  // as four separate controls.
  // Falls back to arrival order only until ensureLocations() has run; on the
  // single-location path chips can render before the list is known.
  const known = state.locations.length > 0;
  const swatch = (known ? state.locations : uniq).slice(0, 5)
    .map((l, i) => `<i style="background:${known ? colorFor(l)
                       : SERIES_COLORS[i % SERIES_COLORS.length]}"></i>`).join('');
  $('loc-chips').innerHTML =
    `<button class="chip mode${state.compare ? ' on' : ''}" data-all="1"
       ><span class="dots">${swatch}</span>toate</button>`
    + uniq.map((l) =>
      `<button class="chip${!state.compare && l === state.location ? ' on' : ''}" data-loc="${esc(l)}"
         style="--loc-color:${colorFor(l)}"><i class="dot"></i>${esc(l)}</button>`
    ).join('')
    + (state.compare ? ''
       : `<button class="chip${state.showHumidity ? ' on' : ''}" data-hum="1">umiditate</button>`);
  $('range-chips').innerHTML = RANGES.map((r) =>
    `<button class="chip${r.h === state.hours ? ' on' : ''}" data-h="${r.h}">${r.label}</button>`
  ).join('');

  $('loc-chips').querySelectorAll('[data-loc]').forEach((b) =>
    b.addEventListener('click', () => {
      state.compare = false;
      state.location = b.dataset.loc;
      try {
        localStorage.setItem(LAST_LOCATION, state.location);
        localStorage.setItem(LAST_MODE, 'one');
      } catch { /* ignore */ }
      loadHistory();
    }));
  $('loc-chips').querySelectorAll('[data-all]').forEach((b) =>
    b.addEventListener('click', () => {
      state.compare = true;
      try { localStorage.setItem(LAST_MODE, 'all'); } catch { /* ignore */ }
      loadHistory();
    }));
  $('loc-chips').querySelectorAll('[data-hum]').forEach((b) =>
    b.addEventListener('click', () => { state.showHumidity = !state.showHumidity; drawChart(); renderChips(locs); }));
  $('range-chips').querySelectorAll('[data-h]').forEach((b) =>
    b.addEventListener('click', () => { state.hours = Number(b.dataset.h); loadHistory(); }));
}

/* ---------------------------------------------------------------- chart -- */
async function loadHistory() {
  // Compare mode is driven by the location *list*, not by a chosen location,
  // so it is reached before the guard below -- which would otherwise blank the
  // default view on a first run, before any location has been picked.
  if (state.compare) { await loadCompare(); return; }

  // loadNow picks a default location on first run. Fetching history without
  // one returns every location interleaved by timestamp, which drawn as a
  // single path looks like a fault in the sensor rather than in the chart.
  if (!state.location) await loadNow();
  if (!state.location) { state.points = []; drawChart(); return; }

  renderChips([state.location]);
  try {
    const d = await api(`/api/history?location=${encodeURIComponent(state.location)}`
                      + `&hours=${state.hours}`);
    state.points = (d.points || []).filter((p) => p.temperature != null);
  } catch (ex) {
    state.points = [];
    if (ex instanceof ApiError && ex.status === 401) { showGate(''); return; }
  }
  await loadNow();          // refreshes the tiles and the location chips
  drawChart();
}

/* One request per location rather than one unfiltered request for all of
   them. /api/history downsamples to a fixed number of points *after*
   filtering, so asking for everything at once would spend that budget on
   whichever locations happen to interleave first and thin the rest
   unevenly. Per-location keeps every series sampled the same way. */
async function loadCompare() {
  await ensureLocations();
  const results = await Promise.all(state.locations.map(async (l) => {
    try {
      const d = await api(`/api/history?location=${encodeURIComponent(l)}`
                        + `&hours=${state.hours}`);
      return { location: l, points: (d.points || []).filter((p) => p.temperature != null) };
    } catch {
      return { location: l, points: [] };   // one dead sensor must not blank the chart
    }
  }));
  state.series = results
    .filter((r) => r.points.length)
    .map((r) => ({ ...r, color: colorFor(r.location) }));
  await loadNow();
  drawChart();
}

/* The viewBox is measured from the element rather than fixed, and the SVG no
   longer stretches: with preserveAspectRatio="none" and a 720-wide box, a
   360px portrait screen squashed everything horizontally by 2x -- including
   the axis text, which is why the labels were hard to read. */
function chartGeometry(svg) {
  const w = Math.max(280, Math.round(svg.clientWidth || 720));
  const h = Math.round(Math.min(300, Math.max(200, w * 0.52)));
  return {
    W: w,
    H: h,
    // Room for the widest y label, and for x labels that must not collide.
    PAD: { l: 34, r: 10, t: 10, b: 26 },
    ticks: w < 380 ? 2 : w < 560 ? 3 : 5,
    gridY: h < 240 ? 3 : 4,
  };
}

function drawChart() {
  if (state.compare) return drawCompareChart();
  const svg = $('chart');
  const { W, H, PAD, ticks, gridY } = chartGeometry(svg);
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);
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

  const grid = [], labels = [];
  for (let i = 0; i <= gridY; i++) {
    const v = y0 + (i / gridY) * (y1 - y0), y = Y(v);
    grid.push(`<line class="grid" x1="${PAD.l}" y1="${y.toFixed(1)}" x2="${W - PAD.r}" y2="${y.toFixed(1)}"/>`);
    labels.push(`<text class="axis" x="4" y="${(y + 4).toFixed(1)}">${v.toFixed(1)}</text>`);
  }
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

  // Same colour this property has on its tile, its chip and the combined
  // chart -- switching between the two views should not recolour the line.
  const locColor = colorFor(state.location);
  svg.innerHTML = bands + grid.join('') + hum
    + `<path class="serie" stroke="${locColor}" d="${path}"/>`
    + labels.join('')
    + `<line id="cursor" class="cursor" x1="0" y1="${PAD.t}" x2="0" y2="${H - PAD.b}" style="display:none"/>`;

  // The swatch carries the property, the label carries the metric: the line
  // is still "temperatură", it is just this property's temperature.
  $('legend').innerHTML =
    `<span><i style="background:${locColor}"></i>temperatură</span>`
    + (bands ? `<span><i class="band" style="background:var(--heat);opacity:.5"></i>încălzire pornită</span>` : '')
    + (hum ? `<span><i style="background:var(--hum)"></i>umiditate</span>` : '');

  attachCursor(svg, pts, xs, X, PAD, H);
}

/* Every location on one temperature axis.
   Heat bands and the humidity line are deliberately absent: both belong to a
   single sensor, and drawing four of either would say less than one does.
   The axis is shared, which is the whole point -- the comparison is only
   honest if the lines are measured against the same scale. */
function drawCompareChart() {
  const svg = $('chart');
  const { W, H, PAD, ticks, gridY } = chartGeometry(svg);
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);

  const series = state.series.filter((s) => s.points.length);
  if (!series.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle"
      class="axis">Nicio măsurătoare în acest interval</text>`;
    $('legend').innerHTML = '';
    return;
  }

  const all = series.flatMap((s) => s.points);
  const xsAll = all.map((p) => new Date(p.ts).getTime());
  const tsAll = all.map((p) => p.temperature);
  const x0 = Math.min(...xsAll), x1 = Math.max(...xsAll);
  let y0 = Math.min(...tsAll), y1 = Math.max(...tsAll);
  const padY = Math.max(0.5, (y1 - y0) * 0.12);
  y0 -= padY; y1 += padY;

  const X = (v) => PAD.l + ((v - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const Y = (v) => H - PAD.b - ((v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);

  const grid = [], labels = [];
  for (let i = 0; i <= gridY; i++) {
    const v = y0 + (i / gridY) * (y1 - y0), y = Y(v);
    grid.push(`<line class="grid" x1="${PAD.l}" y1="${y.toFixed(1)}" x2="${W - PAD.r}" y2="${y.toFixed(1)}"/>`);
    labels.push(`<text class="axis" x="4" y="${(y + 4).toFixed(1)}">${v.toFixed(1)}</text>`);
  }
  for (let i = 0; i <= ticks; i++) {
    const t = x0 + (i / ticks) * (x1 - x0);
    const anchor = i === 0 ? 'start' : i === ticks ? 'end' : 'middle';
    labels.push(`<text class="axis" x="${X(t).toFixed(1)}" y="${H - 6}"
      text-anchor="${anchor}">${esc(fmtTime(new Date(t).toISOString(), state.hours > 48))}</text>`);
  }

  const paths = series.map((s) => {
    const d = s.points.map((p, i) =>
      `${i ? 'L' : 'M'}${X(new Date(p.ts).getTime()).toFixed(1)},${Y(p.temperature).toFixed(1)}`
    ).join('');
    return `<path class="serie" stroke="${s.color}" d="${d}"/>`;
  }).join('');

  svg.innerHTML = grid.join('') + paths + labels.join('')
    + `<line id="cursor" class="cursor" x1="0" y1="${PAD.t}" x2="0" y2="${H - PAD.b}" style="display:none"/>`;

  $('legend').innerHTML = series.map((s) =>
    `<span><i style="background:${s.color}"></i>${esc(s.location)}</span>`).join('');

  attachCompareCursor(svg, series, X, PAD, H);
}

/* Reads every series at the dragged moment, so the readout answers "which is
   warmer right now" rather than making you eyeball two lines. */
function attachCompareCursor(svg, series, X, PAD, H) {
  const cursor = svg.querySelector('#cursor');
  const readout = $('readout');
  const prepared = series.map((s) => ({
    ...s, xs: s.points.map((p) => new Date(p.ts).getTime()),
  }));
  const at = (evt) => {
    const r = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const cx = ((evt.touches ? evt.touches[0].clientX : evt.clientX) - r.left)
               / r.width * vb.width;
    let stamp = null;
    const reads = prepared.map((s) => {
      let best = 0, bd = Infinity;
      for (let i = 0; i < s.xs.length; i++) {
        const d = Math.abs(X(s.xs[i]) - cx);
        if (d < bd) { bd = d; best = i; }
      }
      if (stamp === null || bd < stamp.d) stamp = { d: bd, x: X(s.xs[best]), ts: s.points[best].ts };
      return { location: s.location, color: s.color, p: s.points[best] };
    });
    cursor.setAttribute('x1', stamp.x);
    cursor.setAttribute('x2', stamp.x);
    cursor.style.display = '';
    readout.hidden = false;
    // Warmest first: the ordering is the comparison.
    reads.sort((a, b) => b.p.temperature - a.p.temperature);
    readout.innerHTML = `${esc(fmtTime(stamp.ts, true))}<br>`
      + reads.map((r) =>
          `<span style="color:${r.color}">&#9632;</span> ${esc(r.location)} `
          + `<b>${r.p.temperature.toFixed(1)}°</b>`).join('<br>');
  };
  const hide = () => { cursor.style.display = 'none'; readout.hidden = true; };
  svg.onpointermove = at;
  svg.onpointerdown = at;
  svg.onpointerleave = hide;
  svg.onpointerup = hide;
}

/* Drag anywhere on the chart to read the value at that moment. */
function attachCursor(svg, pts, xs, X, PAD, H) {
  const cursor = svg.querySelector('#cursor');
  const readout = $('readout');
  const at = (evt) => {
    const r = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const cx = ((evt.touches ? evt.touches[0].clientX : evt.clientX) - r.left)
               / r.width * vb.width;
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

let resizeTimer = null;
const onResize = () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state.points.length) drawChart(); }, 150);
};
window.addEventListener('resize', onResize);
window.addEventListener('orientationchange', onResize);

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
/* Session-scoped: while the app is still in a browser the offer returns
   each launch, since notifications and the offline shell both want it on
   the home screen. The dismissal only clears it for now. */
const DISMISSED = 'th-install-dismissed';
function refreshInstallBar() {
  const bar = $('install');
  if (standalone() || sessionStorage.getItem(DISMISSED)) { bar.hidden = true; return; }
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
  try { sessionStorage.setItem(DISMISSED, '1'); } catch { /* private mode */ }
  $('install').hidden = true;
});

/* ---------------------------------------------------------- gate / boot -- */
/* Android WebView reports "; wv)"; the big chat apps ship their own browser.
   Either way the cookie jar is separate from Chrome's, so registering inside
   one strands the credential where the installed PWA can never read it. */
function inAppBrowser() {
  const ua = navigator.userAgent || '';
  return /\bwv\b/.test(ua)
    || /(FBAN|FBAV|Instagram|Line\/|WhatsApp|Snapchat|Messenger)/i.test(ua);
}

const isAndroid = () => /Android/i.test(navigator.userAgent || '');

async function copyText(text, btn) {
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text); ok = true;
    }
  } catch { ok = false; }
  if (!ok) {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta);
    ta.select(); ta.setSelectionRange(0, text.length);
    try { ok = document.execCommand('copy'); } catch { ok = false; }
    document.body.removeChild(ta);
  }
  if (btn) {
    const was = btn.textContent;
    btn.textContent = ok ? 'Copiat' : 'Selectează manual';
    setTimeout(() => { btn.textContent = was; }, 1800);
  }
}

function setupInApp(code) {
  const box = $('gate-inapp');
  box.hidden = !inAppBrowser();
  if (box.hidden) return;

  const url = `${location.origin}/i/${encodeURIComponent(code || '')}`;
  const chrome = $('open-chrome');
  if (isAndroid() && code) {
    // Navigating to intent:// hands the URL to Chrome. Android-only; there is
    // no equivalent on iOS, where the instructions below are the whole answer.
    chrome.href = 'intent://' + url.replace(/^https?:\/\//, '')
      + '#Intent;scheme=https;package=com.android.chrome;'
      + 'S.browser_fallback_url=' + encodeURIComponent(url) + ';end';
    chrome.hidden = false;
  }
  $('inapp-note').textContent = isAndroid()
    ? 'În Chrome: instalează aplicația din meniul ⋮, deschide-o de pe ecranul '
      + 'principal, apoi introdu codul. Poți activa de mai multe ori în prima '
      + 'oră, deci o atingere aici nu se pierde.'
    : `Deschide ${location.host} în Safari, adaugă pagina pe ecranul `
      + 'principal, deschide-o de acolo, apoi introdu codul.';
  $('copy-code').onclick = () => copyText(code || $('invite-code').value, $('copy-code'));
}

function showGate(prefill) {
  $('gate').hidden = false; $('app').hidden = true;
  setupInApp(prefill);
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
    try {
      // updateViaCache:'none' keeps the browser's http cache out of the worker's
      // own update check, and update() asks on every load, so a deployed fix
      // cannot sit behind a stale worker. controllerchange then reloads once
      // when the new worker takes over.
      const reg = await navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' });
      reg.update().catch(() => {});
      let reloading = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (reloading) return;
        reloading = true;
        location.reload();
      });
    } catch { /* the app still works without one */ }
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
