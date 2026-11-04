/* ฐานข้อมูลจุดเก็บตัวอย่าง — หน้าเว็บ (ไม่ต้อง build ใดๆ) */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem('fielddb.' + k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('fielddb.' + k, v); } catch { /* ignore */ } },
};

const state = {
  meta: { media: {}, parameters: [], units: {}, projects: [], provinces: [], categories: [] },
  sites: [], results: [], standards: [],
  selectedId: null, detail: null,
  mode: null, drawPts: [], drawTarget: null,
  resultSort: { key: 'sample_date', desc: true },
};

const FIELD_LABELS = {
  code: 'รหัสจุด', name: 'ชื่อ', category: 'ประเภทจุด', project: 'โครงการ', province: 'จังหวัด',
  address: 'ที่ตั้ง', description: 'รายละเอียด', lat: 'ละติจูด', lng: 'ลองจิจูด', geometry: 'รูปร่างพื้นที่',
  deleted: 'สถานะลบ', site_id: 'จุด', sample_code: 'รหัสตัวอย่าง', media: 'ประเภทตัวอย่าง',
  sample_date: 'วันที่เก็บ', depth: 'ความลึก', sampler: 'ผู้เก็บ', lab: 'ห้องปฏิบัติการ',
  report_no: 'เลขที่รายงาน', notes: 'หมายเหตุ', caption: 'คำบรรยาย', taken_at: 'วันที่ถ่าย',
  filename: 'ชื่อไฟล์', sample_id: 'ตัวอย่าง', parameter: 'พารามิเตอร์', min: 'ค่าต่ำสุด', max: 'ค่าสูงสุด',
  unit: 'หน่วย', reference: 'อ้างอิง',
};
const ACTION_LABELS = { create: 'เพิ่ม', update: 'แก้ไข', delete: 'ลบ', restore: 'ย้อนกลับ', import: 'นำเข้า' };
const ENTITY_LABELS = { site: 'จุด/พื้นที่', sample: 'ตัวอย่าง', photo: 'รูปถ่าย', standard: 'ค่ามาตรฐาน' };

const mediaLabel = (m) => state.meta.media[m] || m || '-';
const fmtDate = (d) => {
  if (!d) return '';
  const dt = new Date(d.length <= 10 ? d + 'T00:00:00' : d);
  if (isNaN(dt)) return d;
  return dt.toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' });
};
const fmtDateTime = (d) => {
  const dt = new Date(d);
  return isNaN(dt) ? d : dt.toLocaleString('th-TH', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' });
};
const fmtNum = (v) => (v === null || v === undefined || v === '') ? '' : String(v);

// ------------------------------------------------------------------ API ---
async function api(method, url, body, headers = {}) {
  const opt = { method, headers: { 'X-User': encodeURIComponent($('#userName').value.trim()), ...headers } };
  if (body !== undefined) {
    if (body instanceof Blob || body instanceof ArrayBuffer) opt.body = body;
    else { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  }
  const res = await fetch(url, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

let toastTimer;
function toast(msg, err = false) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (err ? ' err' : ''); t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, err ? 6000 : 3000);
}
async function guard(fn) {
  try { return await fn(); } catch (e) { console.error(e); toast(e.message, true); }
}
function needUser() {
  const u = $('#userName');
  if (u.value.trim()) return true;
  u.classList.add('need'); u.focus();
  toast('กรุณาใส่ชื่อผู้บันทึกก่อน (มุมขวาบน) เพื่อให้ประวัติการแก้ไขระบุได้ว่าใครแก้', true);
  return false;
}

// ------------------------------------------------------------------ MAP ---
const map = L.map('map', { zoomControl: true, worldCopyJump: true }).setView([13.8, 101.5], 8);
const esriImg = (o) => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  { maxZoom: 20, maxNativeZoom: 19, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics', ...o });
const esriLabels = () => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
  { maxZoom: 20, maxNativeZoom: 19 });
const esriRoads = () => L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}',
  { maxZoom: 20, maxNativeZoom: 19 });
const bases = {
  'ดาวเทียม + ชื่อสถานที่ + ถนน': L.layerGroup([esriImg(), esriRoads(), esriLabels()]),
  'ดาวเทียม + ชื่อสถานที่': L.layerGroup([esriImg(), esriLabels()]),
  'ดาวเทียมอย่างเดียว': esriImg(),
  'แผนที่ถนน (OpenStreetMap)': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    { maxZoom: 19, attribution: '© OpenStreetMap contributors' }),
};
const savedBase = store.get('base', 'ดาวเทียม + ชื่อสถานที่');
(bases[savedBase] || bases['ดาวเทียม + ชื่อสถานที่']).addTo(map);
L.control.layers(bases, null, { position: 'topright' }).addTo(map);
L.control.scale({ metric: true, imperial: false }).addTo(map);
map.on('baselayerchange', (e) => store.set('base', e.name));

const siteLayer = L.layerGroup().addTo(map);
const drawLayer = L.layerGroup().addTo(map);
const markers = new Map();

function siteStatus(s) {
  if (s.n_exceed > 0) return 'exceed';
  if (s.n_samples > 0) return 'ok';
  return 'nodata';
}
function siteLabel(s) {
  const f = $('#labelField').value;
  if (f === 'name') return s.name;
  if (f === 'both') return [s.code, s.name].filter(Boolean).join(' ');
  return s.code || s.name;
}
function parseGeom(g) { try { return g ? JSON.parse(g) : null; } catch { return null; } }

function renderMap() {
  siteLayer.clearLayers();
  markers.clear();
  for (const s of filteredSites()) {
    const st = siteStatus(s);
    const g = parseGeom(s.geometry);
    if (g) {
      L.geoJSON(g, {
        style: { color: st === 'exceed' ? '#ff5252' : '#ffeb3b', weight: 2.5, fillOpacity: 0.12 },
        pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4 }),
      }).on('click', () => selectSite(s.id)).addTo(siteLayer);
    }
    if (s.lat == null || s.lng == null) continue;
    const icon = L.divIcon({
      className: 'pin-wrap', iconSize: [22, 24], iconAnchor: [4, 24],
      html: `<div class="pin ${st}${s.id === state.selectedId ? ' sel' : ''}"></div>`,
    });
    const m = L.marker([s.lat, s.lng], { icon, title: [s.code, s.name].filter(Boolean).join(' — ') })
      .bindTooltip(esc(siteLabel(s)), { permanent: true, direction: 'right', className: 'gl', offset: [10, -14] })
      .on('click', () => selectSite(s.id))
      .addTo(siteLayer);
    markers.set(s.id, m);
  }
}

function fitAll() {
  const pts = filteredSites().filter((s) => s.lat != null).map((s) => [s.lat, s.lng]);
  if (pts.length === 1) map.setView(pts[0], 15);
  else if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 16 });
}

map.on('mousemove', (e) => {
  const { lat, lng } = e.latlng;
  const u = UTM.toUTM(lat, lng);
  $('#coordReadout').textContent =
    `${lat.toFixed(6)}, ${lng.toFixed(6)}   |   UTM ${u.zone}${u.south ? 'S' : 'N'}  E ${u.E.toFixed(0)}  N ${u.N.toFixed(0)}`;
});

// ---------------------------------------------- map modes (add / draw / move) ---
function setMode(mode, target = null) {
  state.mode = mode; state.drawPts = []; state.drawTarget = target;
  drawLayer.clearLayers();
  const bar = $('#modeBar');
  $('.map-wrap').classList.toggle('crosshair', !!mode);
  $('#btnAddPoint').classList.toggle('active', mode === 'add-point');
  $('#btnAddArea').classList.toggle('active', mode === 'draw' && !target);
  if (!mode) { bar.hidden = true; return; }
  bar.hidden = false;
  const drawing = mode === 'draw';
  $('#modeFinish').hidden = !drawing;
  $('#modeUndo').hidden = !drawing;
  updateModeText();
}
function updateModeText() {
  const t = {
    'add-point': 'คลิกบนแผนที่ตรงตำแหน่งที่ต้องการเพิ่มจุด',
    move: 'คลิกบนแผนที่ตรงตำแหน่งใหม่ของจุดนี้',
    draw: `คลิกบนแผนที่ทีละมุมเพื่อวาดพื้นที่ (${state.drawPts.length} มุม) — ดับเบิลคลิกหรือกด “เสร็จ” เมื่อครบ`,
  }[state.mode];
  $('#modeText').textContent = t || '';
}
function redrawPreview() {
  drawLayer.clearLayers();
  if (!state.drawPts.length) return;
  // interactive:false — ไม่งั้นเส้น/จุดที่วาดอยู่จะกินคลิกของแผนที่ ทำให้คลิกต่อในพื้นที่หรือดับเบิลคลิกจบไม่ได้
  const style = { color: '#00e5ff', weight: 2.5, dashArray: '6 4', interactive: false };
  if (state.drawPts.length >= 3) L.polygon(state.drawPts, { ...style, fillOpacity: 0.15 }).addTo(drawLayer);
  else L.polyline(state.drawPts, style).addTo(drawLayer);
  state.drawPts.forEach((p) => L.circleMarker(p, { radius: 4, color: '#00e5ff', fillOpacity: 1, interactive: false }).addTo(drawLayer));
}
map.on('click', (e) => {
  const { lat, lng } = e.latlng;
  if (state.mode === 'add-point') {
    setMode(null);
    openSiteForm({ lat, lng });
  } else if (state.mode === 'move') {
    const id = state.drawTarget;
    setMode(null);
    guard(async () => {
      await api('PUT', `/api/sites/${id}`, { lat, lng });
      toast('ย้ายตำแหน่งแล้ว');
      await reloadAll(); await selectSite(id, false);
    });
  } else if (state.mode === 'draw') {
    state.drawPts.push([lat, lng]);
    redrawPreview(); updateModeText();
  }
});
map.on('dblclick', (e) => {
  if (state.mode === 'draw') { L.DomEvent.stop(e); finishDraw(); }
});
map.doubleClickZoom.disable();
map.on('dblclick', (e) => { if (state.mode !== 'draw') map.setZoomAround(e.latlng, map.getZoom() + 1); });

function finishDraw() {
  // ดับเบิลคลิกจะนับเป็นคลิกเดี่ยวสองครั้งด้วย จึงตัดจุดซ้ำที่อยู่ติดกันออก
  const pts = state.drawPts.filter((p, i, a) => i === 0 || p[0] !== a[i - 1][0] || p[1] !== a[i - 1][1]);
  if (pts.length < 3) { toast('พื้นที่ต้องมีอย่างน้อย 3 มุม', true); return; }
  const ring = pts.map(([la, ln]) => [ln, la]);
  ring.push(ring[0]);
  const geometry = JSON.stringify({ type: 'Polygon', coordinates: [ring] });
  const lat = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const lng = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const target = state.drawTarget;
  setMode(null);
  if (target) {
    guard(async () => {
      await api('PUT', `/api/sites/${target}`, { geometry });
      toast('บันทึกรูปร่างพื้นที่แล้ว');
      await reloadAll(); await selectSite(target, false);
    });
  } else {
    openSiteForm({ lat, lng, geometry });
  }
}
$('#modeFinish').onclick = finishDraw;
$('#modeUndo').onclick = () => { state.drawPts.pop(); redrawPreview(); updateModeText(); };
$('#modeCancel').onclick = () => setMode(null);
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (!$('#lightbox').hidden) { $('#lightbox').hidden = true; return; }
  if (!$('#modal').hidden) { closeModal(); return; }
  if (state.mode) setMode(null);
});

// ---------------------------------------------------------- loading data ---
async function reloadAll() {
  const [meta, sites, results, standards] = await Promise.all([
    api('GET', '/api/meta'), api('GET', '/api/sites'), api('GET', '/api/results'), api('GET', '/api/standards'),
  ]);
  Object.assign(state, { meta, sites, results, standards });
  fillSelects();
  renderSites();
  renderResults();
  renderStandards();
  if ($('#tab-history').classList.contains('active')) renderHistoryTab();
}

function fillOptions(sel, values, labelFn = (v) => v) {
  const cur = sel.value;
  const first = sel.options[0].outerHTML;
  sel.innerHTML = first + values.map((v) => `<option value="${esc(v)}">${esc(labelFn(v))}</option>`).join('');
  sel.value = values.includes(cur) ? cur : '';
}
function fillDatalist(id, values) {
  $('#' + id).innerHTML = values.map((v) => `<option value="${esc(v)}">`).join('');
}
function fillSelects() {
  const m = state.meta;
  const mediaKeys = Object.keys(m.media);
  fillOptions($('#fProject'), m.projects);
  fillOptions($('#rProject'), m.projects);
  fillOptions($('#fMedia'), mediaKeys, mediaLabel);
  fillOptions($('#rMedia'), mediaKeys, mediaLabel);
  const params = [...new Set(state.results.map((r) => r.parameter))].sort((a, b) => a.localeCompare(b, 'th'));
  fillOptions($('#rParam'), params);
  fillDatalist('dlParams', m.parameters);
  fillDatalist('dlProjects', m.projects);
  fillDatalist('dlProvinces', m.provinces);
  fillDatalist('dlCategories', m.categories);
  fillDatalist('dlSamplers', m.samplers || []);
  fillDatalist('dlLabs', m.labs || []);
}

// ------------------------------------------------------------- site list ---
function filteredSites() {
  const q = $('#siteSearch').value.trim().toLowerCase();
  const proj = $('#fProject').value, media = $('#fMedia').value, status = $('#fStatus').value;
  let paramHits = null;
  if (q) {
    paramHits = new Set(state.results.filter((r) => r.parameter.toLowerCase().includes(q)).map((r) => r.site_id));
  }
  const list = state.sites.filter((s) => {
    if (proj && s.project !== proj) return false;
    if (media && !s.media.includes(media)) return false;
    if (status && siteStatus(s) !== status) return false;
    if (q) {
      const hay = [s.code, s.name, s.project, s.province, s.category, s.address, s.description]
        .filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(q) && !paramHits.has(s.id)) return false;
    }
    return true;
  });
  const sort = $('#fSort').value;
  const cmpText = (a, b) => (a || '').localeCompare(b || '', 'th', { numeric: true });
  const sorters = {
    code: (a, b) => cmpText(a.code || a.name, b.code || b.name),
    date: (a, b) => cmpText(b.last_date, a.last_date),
    project: (a, b) => cmpText(a.project, b.project) || cmpText(a.code || a.name, b.code || b.name),
    exceed: (a, b) => b.n_exceed - a.n_exceed || cmpText(a.code, b.code),
    updated: (a, b) => cmpText(b.updated_at, a.updated_at),
  };
  return list.sort(sorters[sort] || sorters.code);
}

function renderSites() {
  const list = filteredSites();
  $('#cntSites').textContent = state.sites.length;
  $('#siteList').innerHTML = list.length ? list.map((s) => {
    const st = siteStatus(s);
    const sub = [
      s.project, s.category,
      s.n_samples ? `${s.n_samples} ตัวอย่าง · ล่าสุด ${fmtDate(s.last_date)}` : 'ยังไม่มีตัวอย่าง',
      s.n_photos ? `📷 ${s.n_photos}` : '',
    ].filter(Boolean).join(' · ');
    const exc = s.n_exceed ? `<div class="s" style="color:var(--red)">เกินมาตรฐาน: ${esc(s.exceed_params.join(', '))}</div>` : '';
    const media = s.media.map((m) => `<span class="badge media">${esc(mediaLabel(m))}</span>`).join(' ');
    return `<li data-id="${s.id}" class="${s.id === state.selectedId ? 'sel' : ''}">
      <span class="dot ${st}"></span>
      <div><div class="t">${esc(s.code ? s.code + ' — ' : '')}${esc(s.name)} ${s.geometry ? '⬠' : ''}</div>
      <div class="s">${esc(sub)}</div>${exc}<div>${media}</div></div></li>`;
  }).join('') : '<li class="muted">ไม่พบข้อมูล — เพิ่มจุดใหม่ หรือ นำเข้าไฟล์ KML/KMZ จาก Google Earth</li>';
  renderMap();
}
$('#siteList').addEventListener('click', (e) => {
  const li = e.target.closest('li[data-id]');
  if (li) selectSite(+li.dataset.id);
});
['#siteSearch', '#fProject', '#fMedia', '#fStatus', '#fSort'].forEach((s) =>
  $(s).addEventListener(s === '#siteSearch' ? 'input' : 'change', renderSites));
$('#siteSearch').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const m = e.target.value.trim().match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
  if (m) {
    const lat = +m[1], lng = +m[2];
    map.setView([lat, lng], 16);
    L.popup().setLatLng([lat, lng]).setContent(`${lat}, ${lng}<br><button class="btn small" id="popAdd">📍 เพิ่มจุดที่นี่</button>`).openOn(map);
    setTimeout(() => { const b = $('#popAdd'); if (b) b.onclick = () => { map.closePopup(); openSiteForm({ lat, lng }); }; });
    e.target.value = ''; renderSites();
  } else {
    const first = filteredSites()[0];
    if (first) selectSite(first.id);
  }
});
$('#labelField').addEventListener('change', () => { store.set('labelField', $('#labelField').value); renderMap(); });
$('#labelField').value = store.get('labelField', 'code');
$('#showLabels').addEventListener('change', () => $('#map').classList.toggle('hide-labels', !$('#showLabels').checked));
$('#btnFit').onclick = fitAll;
$('#btnAddPoint').onclick = () => setMode(state.mode === 'add-point' ? null : 'add-point');
$('#btnAddArea').onclick = () => setMode(state.mode === 'draw' ? null : 'draw');
$('#btnAddManual').onclick = () => openSiteForm({});

// ------------------------------------------------------------ site detail ---
async function selectSite(id, fly = true) {
  state.selectedId = id;
  renderSites();
  const d = await guard(() => api('GET', `/api/sites/${id}`));
  if (!d) return;
  state.detail = d;
  renderDetail();
  if (fly) {
    const g = parseGeom(d.geometry);
    if (g) map.fitBounds(L.geoJSON(g).getBounds(), { padding: [60, 60], maxZoom: 17 });
    else if (d.lat != null) map.setView([d.lat, d.lng], Math.max(map.getZoom(), 15));
  }
}
function closeDetail() {
  $('#detail').hidden = true; state.selectedId = null; state.detail = null; renderSites();
}

function resultStatusBadge(r) {
  if (r.exceed === 1) return '<span class="badge exceed">เกิน</span>';
  if (r.exceed === -1) return '<span class="badge low">ต่ำกว่าเกณฑ์</span>';
  if (r.exceed === 0) return '<span class="badge ok">ผ่าน</span>';
  return '';
}
function stdText(r) {
  if (r.std_min == null && r.std_max == null) return '';
  if (r.std_min != null && r.std_max != null) return `${r.std_min}–${r.std_max}`;
  return r.std_max != null ? `≤ ${r.std_max}` : `≥ ${r.std_min}`;
}

function renderDetail() {
  const d = state.detail;
  const el = $('#detail');
  el.hidden = false;
  const u = d.lat != null ? UTM.toUTM(d.lat, d.lng) : null;
  const kv = [
    ['ประเภทจุด', d.category], ['โครงการ', d.project], ['จังหวัด', d.province], ['ที่ตั้ง', d.address],
    ['พิกัด', d.lat != null ? `${d.lat.toFixed(6)}, ${d.lng.toFixed(6)}` : 'ไม่ระบุ'],
    ['UTM', u ? `โซน ${u.zone}${u.south ? 'S' : 'N'}  E ${u.E.toFixed(0)}  N ${u.N.toFixed(0)}` : ''],
    ['รายละเอียด', d.description], ['แก้ไขล่าสุด', fmtDateTime(d.updated_at)],
  ].filter(([, v]) => v);
  const gmaps = d.lat != null ? `https://www.google.com/maps?q=${d.lat},${d.lng}` : null;

  const samples = d.samples.map((s) => {
    const rows = s.results.map((r) => `<tr class="${r.exceed === 1 ? 'exceed' : ''}">
      <td>${esc(r.parameter)}</td><td class="num val">${esc(r.value_text)}</td><td>${esc(r.unit)}</td>
      <td class="num muted">${esc(stdText(r))}</td><td>${resultStatusBadge(r)}</td></tr>`).join('');
    const meta = [s.sample_code && `รหัส ${s.sample_code}`, s.depth && `ลึก ${s.depth}`, s.sampler && `ผู้เก็บ ${s.sampler}`,
      s.lab && `แล็บ ${s.lab}`, s.report_no && `รายงาน ${s.report_no}`].filter(Boolean).join(' · ');
    return `<div class="sample-card">
      <header><div><span class="badge media">${esc(mediaLabel(s.media))}</span> <b>${esc(fmtDate(s.sample_date) || 'ไม่ระบุวันที่')}</b>
        <div class="meta">${esc(meta)}</div></div>
        <div class="row gap"><button class="btn small" data-act="edit-sample" data-id="${s.id}">แก้ไข</button>
        <button class="btn small" data-act="hist-sample" data-id="${s.id}" title="ประวัติการแก้ไขของตัวอย่างนี้">🕘</button></div></header>
      ${s.notes ? `<div class="meta">${esc(s.notes)}</div>` : ''}
      ${rows ? `<table class="data"><thead><tr><th>พารามิเตอร์</th><th>ค่า</th><th>หน่วย</th><th>มาตรฐาน</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
        : '<div class="meta">ยังไม่มีผลวิเคราะห์</div>'}
    </div>`;
  }).join('');

  const photos = d.photos.map((p, i) => `<figure data-act="photo" data-idx="${i}">
      <img loading="lazy" src="/api/photos/${p.id}/thumb" alt="${esc(p.caption || p.filename)}">
      <figcaption>${esc(p.caption || fmtDate(p.taken_at) || p.filename || '')}</figcaption></figure>`).join('');

  el.innerHTML = `
    <button class="close" data-act="close" aria-label="ปิด">✕</button>
    <h2>${esc(d.code ? d.code + ' — ' : '')}${esc(d.name)}</h2>
    <div class="row gap" style="margin:8px 0">
      <button class="btn small" data-act="edit">✎ แก้ไขข้อมูล</button>
      <button class="btn small" data-act="move">✥ ย้ายหมุด</button>
      <button class="btn small" data-act="draw">⬠ ${d.geometry ? 'วาดพื้นที่ใหม่' : 'วาดขอบเขตพื้นที่'}</button>
      ${gmaps ? `<a class="btn small" href="${gmaps}" target="_blank" rel="noopener">นำทาง ↗</a>` : ''}
      <button class="btn small danger" data-act="delete">🗑 ลบ</button>
    </div>
    <dl class="kv">${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>

    <h3>รูปถ่าย (${d.photos.length})
      <label class="btn small primary">+ เพิ่มรูป<input type="file" accept="image/*" multiple hidden data-act="upload"></label></h3>
    ${photos ? `<div class="photos">${photos}</div>` : '<div class="muted small">ยังไม่มีรูป</div>'}

    <h3>ตัวอย่าง / ผลวิเคราะห์ (${d.samples.length})
      <button class="btn small primary" data-act="add-sample">+ เพิ่มตัวอย่าง</button></h3>
    ${samples || '<div class="muted small">ยังไม่มีการเก็บตัวอย่าง</div>'}

    <h3>ประวัติการแก้ไข <button class="btn small" data-act="history">แสดง</button></h3>
    <div id="detailHistory"></div>`;
}

$('#detail').addEventListener('click', (e) => {
  const t = e.target.closest('[data-act]');
  if (!t) return;
  const d = state.detail;
  const act = t.dataset.act;
  if (act === 'close') closeDetail();
  else if (act === 'edit') openSiteForm(d);
  else if (act === 'move') { if (needUser()) setMode('move', d.id); }
  else if (act === 'draw') { if (needUser()) setMode('draw', d.id); }
  else if (act === 'delete') {
    if (!needUser()) return;
    if (!confirm(`ลบ "${d.name}" ?\n(ข้อมูลยังเก็บอยู่ในประวัติ กู้คืนได้จากแท็บ "ประวัติ")`)) return;
    guard(async () => { await api('DELETE', `/api/sites/${d.id}`); toast('ลบแล้ว'); closeDetail(); await reloadAll(); });
  } else if (act === 'add-sample') openSampleForm({ site_id: d.id });
  else if (act === 'edit-sample') openSampleForm(d.samples.find((s) => s.id === +t.dataset.id));
  else if (act === 'hist-sample') loadDetailHistory({ entity: 'sample', entity_id: t.dataset.id });
  else if (act === 'history') loadDetailHistory({ site_id: d.id });
  else if (act === 'photo') openLightbox(+t.dataset.idx);
});
$('#detail').addEventListener('change', (e) => {
  if (e.target.dataset.act === 'upload') uploadPhotos([...e.target.files]);
});

async function loadDetailHistory(params) {
  const box = $('#detailHistory');
  box.innerHTML = '<div class="muted small">กำลังโหลด…</div>';
  const list = await guard(() => api('GET', '/api/history?' + new URLSearchParams(params)));
  if (!list) return;
  box.innerHTML = list.length ? list.map(renderHistoryEntry).join('') : '<div class="muted small">ไม่มีประวัติ</div>';
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ---------------------------------------------------------------- photos ---
function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('เปิดไฟล์รูปไม่ได้: ' + file.name)); };
    img.src = url;
  });
}
function scaled(img, max, quality) {
  const r = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
  const c = document.createElement('canvas');
  c.width = Math.round(img.naturalWidth * r); c.height = Math.round(img.naturalHeight * r);
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL('image/jpeg', quality);
}
async function uploadPhotos(files) {
  if (!files.length || !needUser()) return;
  const d = state.detail;
  await guard(async () => {
    let n = 0;
    for (const f of files) {
      toast(`กำลังอัปโหลดรูป ${++n}/${files.length}…`);
      const img = await loadImage(f);
      const taken = f.lastModified ? new Date(f.lastModified) : null;
      await api('POST', '/api/photos', {
        site_id: d.id, filename: f.name,
        taken_at: taken ? taken.toISOString().slice(0, 10) : null,
        data: scaled(img, 2000, 0.85), thumb: scaled(img, 360, 0.75),
      });
    }
    toast(`เพิ่มรูปแล้ว ${files.length} รูป`);
    await reloadAll(); await selectSite(d.id, false);
  });
}

function openLightbox(idx) {
  const photos = state.detail.photos;
  const p = photos[idx];
  if (!p) return;
  const lb = $('#lightbox');
  const sampleOpts = state.detail.samples.map((s) =>
    `<option value="${s.id}" ${s.id === p.sample_id ? 'selected' : ''}>${esc(mediaLabel(s.media))} ${esc(fmtDate(s.sample_date))} ${esc(s.sample_code || '')}</option>`).join('');
  lb.innerHTML = `
    ${idx > 0 ? '<button class="nav" style="left:10px" data-go="-1">‹</button>' : ''}
    ${idx < photos.length - 1 ? '<button class="nav" style="right:10px" data-go="1">›</button>' : ''}
    <img src="/api/photos/${p.id}" alt="">
    <div class="bar">
      <input id="lbCaption" value="${esc(p.caption || '')}" placeholder="คำบรรยายรูป" style="width:260px">
      <input id="lbDate" type="date" value="${esc((p.taken_at || '').slice(0, 10))}">
      <select id="lbSample"><option value="">— ไม่ผูกกับตัวอย่าง —</option>${sampleOpts}</select>
      <button class="btn" id="lbSave">บันทึก</button>
      <a class="btn" href="/api/photos/${p.id}" download="${esc(p.filename || 'photo.jpg')}">⬇</a>
      <button class="btn danger" id="lbDel">ลบรูป</button>
      <button class="btn" id="lbClose">ปิด ✕</button>
    </div>
    <div class="small" style="opacity:.7;margin-top:4px">${idx + 1} / ${photos.length} · ${esc(p.filename || '')}</div>`;
  lb.hidden = false;
  lb.onclick = (e) => {
    if (e.target === lb || e.target.id === 'lbClose') lb.hidden = true;
    const go = e.target.dataset.go;
    if (go) openLightbox(idx + +go);
  };
  $('#lbSave').onclick = () => {
    if (!needUser()) return;
    guard(async () => {
      await api('PUT', `/api/photos/${p.id}`, { caption: $('#lbCaption').value, taken_at: $('#lbDate').value, sample_id: +$('#lbSample').value || null });
      toast('บันทึกแล้ว'); lb.hidden = true; await selectSite(state.detail.id, false);
    });
  };
  $('#lbDel').onclick = () => {
    if (!needUser() || !confirm('ลบรูปนี้? (กู้คืนได้จากประวัติ)')) return;
    guard(async () => {
      await api('DELETE', `/api/photos/${p.id}`);
      toast('ลบรูปแล้ว'); lb.hidden = true; await reloadAll(); await selectSite(state.detail.id, false);
    });
  };
}

// ----------------------------------------------------------------- modal ---
function openModal(html) {
  $('#modalBody').innerHTML = html;
  $('#modal').hidden = false;
  const first = $('#modalBody input:not([type=hidden]), #modalBody select');
  if (first) first.focus();
}
function closeModal() { $('#modal').hidden = true; $('#modalBody').innerHTML = ''; }
$('#modalClose').onclick = closeModal;
$('#modal').addEventListener('mousedown', (e) => { if (e.target.id === 'modal') closeModal(); });

function formData(form) {
  const o = {};
  for (const el of form.elements) if (el.name) o[el.name] = el.value;
  return o;
}

// -------------------------------------------------------------- site form ---
function openSiteForm(s) {
  const isNew = !s.id;
  const u = s.lat != null ? UTM.toUTM(+s.lat, +s.lng) : { zone: 47 };
  const f = (name, label, attrs = '') => `<label>${label}<input name="${name}" value="${esc(s[name] ?? '')}" ${attrs}></label>`;
  openModal(`
    <h2>${isNew ? 'เพิ่มจุด / พื้นที่ใหม่' : 'แก้ไขข้อมูลจุด'}</h2>
    <form id="siteForm">
      <div class="form-grid">
        ${f('code', 'รหัสจุด', 'placeholder="เช่น SW-01"')}
        ${f('name', 'ชื่อจุด / พื้นที่ *', 'required')}
        ${f('category', 'ประเภทจุด', 'list="dlCategories" placeholder="เช่น จุดเก็บน้ำผิวดิน, บ่อสังเกตการณ์"')}
        ${f('project', 'โครงการ / เรื่อง', 'list="dlProjects"')}
        ${f('province', 'จังหวัด', 'list="dlProvinces"')}
        ${f('address', 'ที่ตั้ง (ต./อ./จ.)')}
        <div class="full coord-box">
          <div class="form-grid">
            ${f('lat', 'ละติจูด (Lat)', 'inputmode="decimal" placeholder="13.xxxxxx"')}
            ${f('lng', 'ลองจิจูด (Long)', 'inputmode="decimal" placeholder="101.xxxxxx"')}
          </div>
          <div class="form-grid" style="margin-top:6px">
            <label>UTM โซน<select id="uZone">${[46, 47, 48].map((z) => `<option ${z === u.zone ? 'selected' : ''}>${z}</option>`).join('')}</select></label>
            <label>UTM E (Easting)<input id="uE" inputmode="decimal" value="${u.E ? u.E.toFixed(0) : ''}"></label>
            <label>UTM N (Northing)<input id="uN" inputmode="decimal" value="${u.N ? u.N.toFixed(0) : ''}"></label>
          </div>
          <div class="muted small" style="margin-top:4px">กรอกแบบใดแบบหนึ่ง ระบบจะแปลงให้อีกแบบอัตโนมัติ (WGS84)
            ${s.geometry ? ' · จุดนี้มีรูปร่างพื้นที่ (polygon) อยู่แล้ว' : ''}</div>
        </div>
        <label class="full">รายละเอียด / หมายเหตุ<textarea name="description" rows="3">${esc(s.description || '')}</textarea></label>
      </div>
      <input type="hidden" name="geometry" value="${esc(s.geometry || '')}">
      <div class="form-actions">
        <button type="button" class="btn" id="cancelSite">ยกเลิก</button>
        <button class="btn primary">${isNew ? 'บันทึกจุดใหม่' : 'บันทึกการแก้ไข'}</button>
      </div>
    </form>`);
  const form = $('#siteForm');
  const latEl = form.elements.lat, lngEl = form.elements.lng;
  const syncUTM = () => {
    const la = parseFloat(latEl.value), ln = parseFloat(lngEl.value);
    if (isNaN(la) || isNaN(ln)) return;
    const z = UTM.zoneOf(ln);
    const r = UTM.toUTM(la, ln, z);
    $('#uZone').value = String(z); $('#uE').value = r.E.toFixed(0); $('#uN').value = r.N.toFixed(0);
  };
  const syncLL = () => {
    const E = parseFloat($('#uE').value), N = parseFloat($('#uN').value);
    if (isNaN(E) || isNaN(N)) return;
    const r = UTM.fromUTM(+$('#uZone').value, E, N, false);
    latEl.value = r.lat.toFixed(6); lngEl.value = r.lng.toFixed(6);
  };
  if (s.lat != null) { latEl.value = (+s.lat).toFixed(6); lngEl.value = (+s.lng).toFixed(6); }
  latEl.addEventListener('input', syncUTM); lngEl.addEventListener('input', syncUTM);
  ['#uE', '#uN', '#uZone'].forEach((x) => $(x).addEventListener('input', syncLL));
  $('#cancelSite').onclick = closeModal;
  form.onsubmit = (e) => {
    e.preventDefault();
    if (!needUser()) return;
    const data = formData(form);
    guard(async () => {
      const r = isNew ? await api('POST', '/api/sites', data) : await api('PUT', `/api/sites/${s.id}`, data);
      closeModal();
      toast(isNew ? 'เพิ่มจุดแล้ว' : 'บันทึกแล้ว');
      await reloadAll();
      await selectSite(r.id, isNew);
    });
  };
}

// ------------------------------------------------------------ sample form ---
function resultRow(r = {}) {
  return `<tr>
    <td><input name="parameter" list="dlParams" value="${esc(r.parameter || '')}" placeholder="เช่น Pb, Cd, pH"></td>
    <td><input name="value_text" value="${esc(r.value_text ?? '')}" placeholder="เช่น 0.05, <0.01, ND"></td>
    <td><input name="unit" value="${esc(r.unit || '')}" placeholder="mg/kg"></td>
    <td><input name="method" value="${esc(r.method || '')}"></td>
    <td><button type="button" class="btn small danger" data-del-row title="ลบแถว">✕</button></td></tr>`;
}
function openSampleForm(s) {
  const isNew = !s.id;
  const site = state.sites.find((x) => x.id === s.site_id) || state.detail;
  const mediaOpts = Object.entries(state.meta.media).map(([k, v]) =>
    `<option value="${k}" ${k === s.media ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const f = (name, label, attrs = '') => `<label>${label}<input name="${name}" value="${esc(s[name] ?? '')}" ${attrs}></label>`;
  const results = (s.results && s.results.length ? s.results : [{}, {}, {}]).map(resultRow).join('');
  openModal(`
    <h2>${isNew ? 'เพิ่มตัวอย่าง' : 'แก้ไขตัวอย่าง'} — ${esc(site ? (site.code || site.name) : '')}</h2>
    <form id="sampleForm">
      <div class="form-grid">
        <label>ประเภทตัวอย่าง *<select name="media" required><option value="">— เลือก —</option>${mediaOpts}</select></label>
        <label>วันที่เก็บ<input name="sample_date" type="date" value="${esc(s.sample_date || new Date().toISOString().slice(0, 10))}"></label>
        ${f('sample_code', 'รหัสตัวอย่าง')}
        ${f('depth', 'ความลึก', 'placeholder="เช่น 0-15 cm, 12 m"')}
        ${f('sampler', 'ผู้เก็บตัวอย่าง', 'list="dlSamplers"')}
        ${f('lab', 'ห้องปฏิบัติการ', 'list="dlLabs"')}
        ${f('report_no', 'เลขที่รายงานผล')}
        <label class="full">หมายเหตุ<textarea name="notes" rows="2">${esc(s.notes || '')}</textarea></label>
      </div>
      <h3 style="margin:14px 0 6px">ผลวิเคราะห์</h3>
      <div class="table-wrap"><table class="data results-grid">
        <thead><tr><th>พารามิเตอร์ / สาร</th><th>ค่าที่วัดได้</th><th>หน่วย</th><th>วิธีวิเคราะห์</th><th></th></tr></thead>
        <tbody id="resRows">${results}</tbody></table></div>
      <div class="row gap" style="margin-top:6px">
        <button type="button" class="btn small" id="addRow">+ เพิ่มแถว</button>
        <button type="button" class="btn small" id="fillStd" title="เติมรายการพารามิเตอร์ที่มีค่ามาตรฐานของประเภทตัวอย่างนี้">เติมพารามิเตอร์จากค่ามาตรฐาน</button>
        <button type="button" class="btn small" id="pasteBtn">📋 วางจาก Excel</button>
      </div>
      <div id="pasteBox" hidden style="margin-top:6px">
        <textarea id="pasteText" rows="4" placeholder="คัดลอกคอลัมน์จาก Excel มาวาง: พารามิเตอร์ [Tab] ค่า [Tab] หน่วย (ทีละบรรทัด)"></textarea>
        <button type="button" class="btn small" id="pasteApply">เพิ่มจากข้อความที่วาง</button>
      </div>
      <div class="form-actions">
        ${isNew ? '' : '<button type="button" class="btn danger" id="delSample" style="margin-right:auto">🗑 ลบตัวอย่างนี้</button>'}
        <button type="button" class="btn" id="cancelSample">ยกเลิก</button>
        <button class="btn primary">บันทึก</button>
      </div>
    </form>`);
  const form = $('#sampleForm');
  const tbody = $('#resRows');
  const addRows = (rows) => {
    // ใช้แถวว่างที่มีอยู่ก่อน แล้วค่อยต่อท้าย
    const empties = $$('tr', tbody).filter((tr) => !$('[name=parameter]', tr).value && !$('[name=value_text]', tr).value);
    for (const r of rows) {
      const tr = empties.shift();
      if (tr) tr.outerHTML = resultRow(r); else tbody.insertAdjacentHTML('beforeend', resultRow(r));
    }
  };
  tbody.addEventListener('click', (e) => { if (e.target.closest('[data-del-row]')) e.target.closest('tr').remove(); });
  tbody.addEventListener('change', (e) => {
    if (e.target.name !== 'parameter') return;
    const unit = $('[name=unit]', e.target.closest('tr'));
    if (!unit.value) {
      const p = e.target.value.trim().toLowerCase();
      const media = form.elements.media.value;
      const std = state.standards.find((x) => x.parameter.toLowerCase() === p && (x.media || '') === media)
        || state.standards.find((x) => x.parameter.toLowerCase() === p && !x.media);
      unit.value = (std && std.unit) || state.meta.units[p] || '';
    }
  });
  $('#addRow').onclick = () => tbody.insertAdjacentHTML('beforeend', resultRow());
  $('#fillStd').onclick = () => {
    const media = form.elements.media.value;
    if (!media) { toast('เลือกประเภทตัวอย่างก่อน', true); return; }
    const have = new Set($$('[name=parameter]', tbody).map((i) => i.value.trim().toLowerCase()));
    const rows = state.standards.filter((x) => (x.media === media || !x.media) && !have.has(x.parameter.toLowerCase()))
      .map((x) => ({ parameter: x.parameter, unit: x.unit }));
    if (!rows.length) toast('ไม่มีค่ามาตรฐานเพิ่มเติมสำหรับประเภทนี้ (เพิ่มได้ในแท็บ "ค่ามาตรฐาน")', true);
    addRows(rows);
  };
  $('#pasteBtn').onclick = () => { $('#pasteBox').hidden = !$('#pasteBox').hidden; $('#pasteText').focus(); };
  $('#pasteApply').onclick = () => {
    const rows = $('#pasteText').value.split(/\r?\n/).map((l) => l.split(/\t|;|,(?=\s*\S)/).map((x) => x.trim()))
      .filter((c) => c[0]).map((c) => ({ parameter: c[0], value_text: c[1] || '', unit: c[2] || '' }));
    addRows(rows);
    $('#pasteText').value = ''; $('#pasteBox').hidden = true;
  };
  $('#cancelSample').onclick = closeModal;
  if (!isNew) {
    $('#delSample').onclick = () => {
      if (!needUser() || !confirm('ลบตัวอย่างนี้พร้อมผลวิเคราะห์? (กู้คืนได้จากประวัติ)')) return;
      guard(async () => {
        await api('DELETE', `/api/samples/${s.id}`);
        closeModal(); toast('ลบแล้ว'); await reloadAll(); await selectSite(s.site_id, false);
      });
    };
  }
  form.onsubmit = (e) => {
    e.preventDefault();
    if (!needUser()) return;
    const data = {};
    for (const k of ['media', 'sample_date', 'sample_code', 'depth', 'sampler', 'lab', 'report_no', 'notes']) data[k] = form.elements[k].value;
    data.site_id = s.site_id;
    data.results = $$('tr', tbody).map((tr) => ({
      parameter: $('[name=parameter]', tr).value, value_text: $('[name=value_text]', tr).value,
      unit: $('[name=unit]', tr).value, method: $('[name=method]', tr).value,
    })).filter((r) => r.parameter.trim());
    guard(async () => {
      if (isNew) await api('POST', '/api/samples', data);
      else await api('PUT', `/api/samples/${s.id}`, data);
      closeModal(); toast('บันทึกแล้ว');
      await reloadAll(); await selectSite(s.site_id, false);
    });
  };
}

// ---------------------------------------------------------- results tab ---
const RESULT_COLS = [
  { key: 'site_code', label: 'รหัสจุด' }, { key: 'site_name', label: 'ชื่อจุด' }, { key: 'project', label: 'โครงการ' },
  { key: 'sample_date', label: 'วันที่เก็บ', fmt: fmtDate }, { key: 'media', label: 'ประเภท', fmt: mediaLabel },
  { key: 'sample_code', label: 'รหัสตัวอย่าง' }, { key: 'depth', label: 'ความลึก' }, { key: 'parameter', label: 'พารามิเตอร์' },
  { key: 'value', label: 'ค่า', num: true, show: (r) => r.value_text }, { key: 'unit', label: 'หน่วย' },
  { key: 'std', label: 'มาตรฐาน', show: stdText, sortVal: (r) => r.std_max ?? r.std_min },
  { key: 'exceed', label: 'สถานะ', html: resultStatusBadge }, { key: 'sampler', label: 'ผู้เก็บ' }, { key: 'lab', label: 'แล็บ' },
];
function filteredResults() {
  const q = $('#rSearch').value.trim().toLowerCase();
  const media = $('#rMedia').value, param = $('#rParam').value, proj = $('#rProject').value;
  const from = $('#rFrom').value, to = $('#rTo').value, onlyEx = $('#rExceed').checked;
  const rows = state.results.filter((r) => {
    if (media && r.media !== media) return false;
    if (param && r.parameter !== param) return false;
    if (proj && r.project !== proj) return false;
    if (from && (!r.sample_date || r.sample_date < from)) return false;
    if (to && (!r.sample_date || r.sample_date > to)) return false;
    if (onlyEx && !r.exceed) return false;
    if (q) {
      const hay = [r.site_code, r.site_name, r.project, r.province, r.parameter, r.sample_code, r.sampler, r.lab, r.value_text, mediaLabel(r.media)]
        .filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const { key, desc } = state.resultSort;
  const col = RESULT_COLS.find((c) => c.key === key);
  const val = (r) => (col && col.sortVal ? col.sortVal(r) : r[key]);
  rows.sort((a, b) => {
    const va = val(a), vb = val(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    const c = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb), 'th', { numeric: true });
    return desc ? -c : c;
  });
  return rows;
}
function renderResults() {
  const rows = filteredResults();
  $('#cntResults').textContent = state.results.length;
  const LIMIT = 3000;
  $('#rCount').textContent = `${rows.length} รายการ` + (rows.length > LIMIT ? ` (แสดง ${LIMIT} แถวแรก — ใช้ตัวกรองเพื่อจำกัดผล หรือส่งออก CSV)` : '');
  const { key, desc } = state.resultSort;
  const head = RESULT_COLS.map((c) => `<th data-key="${c.key}" class="${c.key === key ? 'sorted' + (desc ? ' desc' : '') : ''}">${c.label}</th>`).join('');
  const body = rows.slice(0, LIMIT).map((r) => `<tr data-site="${r.site_id}" class="${r.exceed === 1 ? 'exceed' : ''}">` + RESULT_COLS.map((c) => {
    if (c.html) return `<td>${c.html(r)}</td>`;
    const v = c.show ? c.show(r) : c.fmt ? c.fmt(r[c.key]) : r[c.key];
    return `<td class="${c.num ? 'num val' : ''}" title="${esc(v)}">${esc(v)}</td>`;
  }).join('') + '</tr>').join('');
  $('#resultsTable').innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body ||
    `<tr><td colspan="${RESULT_COLS.length}" class="muted">ไม่มีข้อมูล</td></tr>`}</tbody>`;
}
$('#resultsTable').addEventListener('click', (e) => {
  const th = e.target.closest('th[data-key]');
  if (th) {
    const k = th.dataset.key;
    state.resultSort = { key: k, desc: state.resultSort.key === k ? !state.resultSort.desc : false };
    renderResults(); return;
  }
  const tr = e.target.closest('tr[data-site]');
  if (tr) selectSite(+tr.dataset.site);
});
['#rSearch', '#rMedia', '#rParam', '#rProject', '#rFrom', '#rTo', '#rExceed'].forEach((s) =>
  $(s).addEventListener(s === '#rSearch' ? 'input' : 'change', renderResults));
$('#rExport').onclick = () => {
  const cols = ['site_code', 'site_name', 'project', 'province', 'sample_code', 'sample_date', 'media', 'depth', 'parameter',
    'value_text', 'unit', 'std_min', 'std_max', 'exceed', 'sampler', 'lab'];
  const q = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const lines = [cols.join(',')].concat(filteredResults().map((r) => cols.map((c) => q(c === 'media' ? mediaLabel(r.media) : r[c])).join(',')));
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `results-filtered-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

// ---------------------------------------------------------- history tab ---
function displayValue(field, v) {
  if (v === null || v === undefined || v === '') return '(ว่าง)';
  if (field === 'media') return mediaLabel(v);
  if (field === 'geometry') return '[รูปร่างพื้นที่]';
  if (field === 'deleted') return v ? 'ถูกลบ' : 'ปกติ';
  if (field === 'site_id') { const s = state.sites.find((x) => x.id === v); return s ? (s.code || s.name) : `#${v}`; }
  return String(v);
}
function diffRows(before, after) {
  const rows = [];
  const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  keys.delete('id'); keys.delete('results');
  for (const k of keys) {
    const a = before ? before[k] : undefined, b = after ? after[k] : undefined;
    if ((a ?? '') === (b ?? '')) continue;
    if (!before && (b === null || b === '' || (k === 'deleted' && !b))) continue;
    rows.push(`<tr><td class="muted">${esc(FIELD_LABELS[k] || k)}</td><td>${before ? `<span class="old">${esc(displayValue(k, a))}</span> → ` : ''}
      <span class="new">${esc(displayValue(k, b))}</span></td></tr>`);
  }
  if ((before && before.results) || (after && after.results)) {
    const fmt = (r) => [r.value_text, r.unit].filter(Boolean).join(' ') || '(ว่าง)';
    const mapOf = (arr) => new Map((arr || []).map((r) => [r.parameter, r]));
    const A = mapOf(before && before.results), B = mapOf(after && after.results);
    for (const p of new Set([...A.keys(), ...B.keys()])) {
      const a = A.get(p), b = B.get(p);
      if (a && b && fmt(a) === fmt(b) && (a.method || '') === (b.method || '')) continue;
      rows.push(`<tr><td class="muted">ผล: ${esc(p)}</td><td>${a ? `<span class="old">${esc(fmt(a))}</span>` : ''}${a && b ? ' → ' : ''}${b ? `<span class="new">${esc(fmt(b))}</span>` : (a ? ' (ลบออก)' : '')}</td></tr>`);
    }
  }
  return rows.join('');
}
function renderHistoryEntry(h) {
  const label = h.summary || `#${h.entity_id}`;
  const site = h.site_id && state.sites.find((s) => s.id === h.site_id);
  const siteLink = site && h.entity !== 'site' ? ` · <span class="link" data-site="${site.id}">${esc(site.code || site.name)}</span>` : '';
  const ownLink = h.entity === 'site' && site ? `<span class="link" data-site="${site.id}">${esc(label)}</span>` : esc(label);
  const diff = diffRows(h.before, h.after);
  return `<div class="hist ${h.action}">
    <div class="h"><b>${ACTION_LABELS[h.action] || h.action}${ENTITY_LABELS[h.entity] || h.entity}</b> ${ownLink}${siteLink}
      <span class="who">· ${esc(h.user || '')} · ${esc(fmtDateTime(h.at))}</span>
      ${h.before ? `<button class="btn small" data-restore="${h.id}" title="คืนข้อมูลเป็นสถานะก่อนการเปลี่ยนแปลงนี้">↶ ย้อนกลับ</button>` : ''}</div>
    ${diff ? `<table>${diff}</table>` : ''}</div>`;
}
async function renderHistoryTab() {
  const params = { limit: 500 };
  if ($('#hEntity').value) params.entity = $('#hEntity').value;
  const list = await guard(() => api('GET', '/api/history?' + new URLSearchParams(params)));
  if (!list) return;
  $('#historyList').innerHTML = list.length ? list.map(renderHistoryEntry).join('') : '<div class="muted">ยังไม่มีประวัติ</div>';
}
$('#hEntity').addEventListener('change', renderHistoryTab);
$('#hReload').onclick = renderHistoryTab;
document.addEventListener('click', (e) => {
  const r = e.target.closest('[data-restore]');
  if (r) {
    if (!needUser() || !confirm('ย้อนข้อมูลกลับเป็นสถานะก่อนการเปลี่ยนแปลงนี้?')) return;
    guard(async () => {
      await api('POST', `/api/history/${r.dataset.restore}/restore`);
      toast('ย้อนกลับแล้ว');
      await reloadAll();
      if (state.selectedId) {
        const still = state.sites.find((s) => s.id === state.selectedId);
        if (still) await selectSite(state.selectedId, false); else closeDetail();
      }
      if ($('#tab-history').classList.contains('active')) renderHistoryTab();
    });
    return;
  }
  const l = e.target.closest('.hist [data-site]');
  if (l) selectSite(+l.dataset.site);
});

// -------------------------------------------------------- standards tab ---
function renderStandards() {
  const mediaOpts = (sel) => `<option value="">(ทุกประเภท)</option>` + Object.entries(state.meta.media)
    .map(([k, v]) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const row = (s) => `<tr data-id="${s.id || ''}">
    <td><select name="media">${mediaOpts(s.media || '')}</select></td>
    <td><input name="parameter" value="${esc(s.parameter || '')}" list="dlParams"></td>
    <td><input name="min" value="${esc(fmtNum(s.min))}" inputmode="decimal"></td>
    <td><input name="max" value="${esc(fmtNum(s.max))}" inputmode="decimal"></td>
    <td><input name="unit" value="${esc(s.unit || '')}"></td>
    <td><input name="reference" value="${esc(s.reference || '')}"></td>
    <td style="white-space:nowrap"><button class="btn small" data-std-save>บันทึก</button>
      ${s.id ? '<button class="btn small danger" data-std-del>✕</button>' : ''}</td></tr>`;
  $('#stdTable').innerHTML = `<thead><tr><th>ประเภทตัวอย่าง</th><th>พารามิเตอร์</th><th>ต่ำสุด</th><th>สูงสุด</th><th>หน่วย</th><th>อ้างอิงประกาศ</th><th></th></tr></thead>
    <tbody>${state.standards.map(row).join('')}</tbody>`;
  $('#stdAdd').onclick = () => { $('#stdTable tbody').insertAdjacentHTML('beforeend', row({})); $('#stdTable tbody tr:last-child [name=parameter]').focus(); };
}
$('#stdTable').addEventListener('click', (e) => {
  const tr = e.target.closest('tr[data-id]');
  if (!tr) return;
  const id = tr.dataset.id;
  if (e.target.closest('[data-std-save]')) {
    if (!needUser()) return;
    const data = {};
    $$('[name]', tr).forEach((i) => { data[i.name] = i.value; });
    guard(async () => {
      if (id) await api('PUT', `/api/standards/${id}`, data); else await api('POST', '/api/standards', data);
      toast('บันทึกค่ามาตรฐานแล้ว'); await reloadAll();
    });
  } else if (e.target.closest('[data-std-del]')) {
    if (!needUser() || !confirm('ลบค่ามาตรฐานนี้?')) return;
    guard(async () => { await api('DELETE', `/api/standards/${id}`); await reloadAll(); });
  }
});

// ------------------------------------------------------------------ tabs ---
$$('.tabs button').forEach((b) => b.addEventListener('click', () => {
  $$('.tabs button').forEach((x) => x.classList.toggle('active', x === b));
  $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + b.dataset.tab));
  $('#sidebar').classList.toggle('wide', ['results', 'history', 'standards'].includes(b.dataset.tab));
  store.set('tab', b.dataset.tab);
  if (b.dataset.tab === 'history') renderHistoryTab();
  setTimeout(() => map.invalidateSize(), 250);
}));

// ---------------------------------------------------------------- import ---
$('#btnImportKml').onclick = () => { if (needUser()) $('#fileKml').click(); };
$('#btnImportCsv').onclick = () => {
  if (!needUser()) return;
  openModal(`<h2>นำเข้าผลวิเคราะห์จาก CSV</h2>
    <p>บันทึกไฟล์จาก Excel เป็น <b>CSV UTF-8</b> โดยมีหัวคอลัมน์ (แถวแรก) ตามนี้ — 1 แถว = 1 พารามิเตอร์:</p>
    <pre style="overflow:auto;background:var(--hover);padding:8px;border-radius:6px">site_code,site_name,lat,lng,project,sample_code,sample_date,media,depth,sampler,lab,parameter,value,unit
SW-01,คลองท้ายโรงงาน,13.7301,101.5231,โครงการ A,SW-01-1,2026-05-27,surface_water,,สมชาย,แล็บ X,Pb,0.012,mg/L
SW-01,คลองท้ายโรงงาน,13.7301,101.5231,โครงการ A,SW-01-1,2026-05-27,surface_water,,สมชาย,แล็บ X,pH,7.2,</pre>
    <ul class="small">
      <li>ถ้ารหัสจุด (site_code) มีในฐานข้อมูลแล้ว จะเพิ่มตัวอย่างเข้าจุดเดิม — ถ้ายังไม่มีต้องใส่ lat,lng เพื่อสร้างจุดใหม่</li>
      <li>แถวที่ site / sample_code / sample_date / media / depth ตรงกันจะรวมเป็นตัวอย่างเดียวกัน</li>
      <li>media ใช้ได้: ${Object.entries(state.meta.media).map(([k, v]) => `<code>${k}</code> (${esc(v)})`).join(', ')} — หรือพิมพ์ชื่อไทยก็ได้</li>
      <li>ค่าที่ต่ำกว่าขีดจำกัดการตรวจวัด ใส่เป็น <code>&lt;0.01</code> หรือ <code>ND</code> ได้</li>
    </ul>
    <div class="form-actions"><button class="btn" id="csvCancel">ยกเลิก</button><button class="btn primary" id="csvPick">เลือกไฟล์ CSV…</button></div>`);
  $('#csvCancel').onclick = closeModal;
  $('#csvPick').onclick = () => { closeModal(); $('#fileCsv').click(); };
};
async function uploadFile(input, url, describe) {
  const f = input.files[0];
  input.value = '';
  if (!f) return;
  await guard(async () => {
    toast('กำลังนำเข้า…');
    const r = await api('POST', url, await f.arrayBuffer(), { 'X-Filename': encodeURIComponent(f.name), 'Content-Type': 'application/octet-stream' });
    await reloadAll();
    fitAll();
    toast(describe(r));
  });
}
$('#fileKml').onchange = (e) => uploadFile(e.target, '/api/import/kml',
  (r) => `พบ ${r.found} รายการ · เพิ่มใหม่ ${r.added} · ข้าม (ซ้ำของเดิม) ${r.skipped}`);
$('#fileCsv').onchange = (e) => uploadFile(e.target, '/api/import/csv',
  (r) => `นำเข้า ${r.rows} แถว → ${r.samples} ตัวอย่าง, ${r.results} ผลวิเคราะห์, จุดใหม่ ${r.new_sites}`);

// ------------------------------------------------------------------ boot ---
$('#userName').value = store.get('user', '');
$('#userName').addEventListener('input', (e) => { store.set('user', e.target.value.trim()); e.target.classList.remove('need'); });
document.addEventListener('click', (e) => {  // ปิดเมนูส่งออกเมื่อคลิกที่อื่น
  const m = $('.menu');
  if (m.open && !m.contains(e.target)) m.open = false;
});
(async () => {
  await guard(reloadAll);
  if (state.sites.length) fitAll();
  const tab = store.get('tab', 'sites');
  const b = $(`.tabs button[data-tab="${tab}"]`);
  if (b && tab !== 'sites') b.click();
})();
