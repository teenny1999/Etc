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
  selectMode: false, picked: new Set(),
  hidden: new Set(),   // จุดที่ผู้ใช้ซ่อนบนแผนที่ (จำไว้ในเบราว์เซอร์นี้เท่านั้น)
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
function toast(msg, err = false, action = null) {
  const t = $('#toast');
  t.innerHTML = ic(err ? 'alert' : 'check') + `<span>${esc(msg)}</span>`
    + (action ? `<button class="toast-action">${ic('undo')}${esc(action.label)}</button>` : '');
  t.className = 'toast' + (err ? ' err' : '');
  t.hidden = true; void t.offsetWidth; t.hidden = false;  // เล่นแอนิเมชันใหม่ทุกครั้ง
  if (action) $('.toast-action', t).onclick = () => { t.hidden = true; action.fn(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, action ? 10000 : err ? 6000 : 3000);
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
  if (s.n_compared > 0) return 'ok';  // เขียว = มีค่าที่เทียบมาตรฐานได้จริงและผ่านทั้งหมด
  return 'nodata';
}
function siteLabel(s) {
  const f = $('#labelField').value;
  if (f === 'name') return s.name;
  if (f === 'both') return [s.code, s.name].filter(Boolean).join(' ');
  return s.code || s.name;
}
function parseGeom(g) { try { return g ? JSON.parse(g) : null; } catch { return null; } }

// หมุดที่ต้อง "ตกลงมา": ทุกหมุดตอนเปิดครั้งแรก (ไล่ทีละนิด รวมไม่เกิน 0.6 วิ) และหมุดที่เพิ่งสร้าง
const drop = { first: true, ids: new Set() };
function renderMap() {
  siteLayer.clearLayers();
  markers.clear();
  let n = 0;
  const list = filteredSites();
  const step = Math.min(40, 600 / Math.max(list.length, 1));
  for (const s of list) {
    if (state.hidden.has(s.id) && s.id !== state.selectedId) continue;
    if (state.mode === 'edit' && state.drawTarget === s.id) continue;   // กำลังแก้รูปร่าง: แสดงเฉพาะตัวที่แก้
    const st = siteStatus(s);
    const g = parseGeom(s.geometry);
    if (g) {
      const isLine = g.type === 'LineString';
      const color = st === 'exceed' ? '#ff5a45' : isLine ? '#ffd54a' : '#f6f3e8';
      const lyr = geomLayer(g, { color, weight: isLine ? 3 : 2, dashArray: st === 'exceed' || isLine ? null : '6 4',
        fillColor: st === 'exceed' ? '#ff5a45' : '#ffffff', fillOpacity: 0.12 });
      lyr.bindTooltip(`${esc(s.code || s.name)} · ${esc(measureGeom(g))}`, { sticky: true, className: 'measure-hover' });
      lyr.on('click', () => siteClick(s.id)).addTo(siteLayer);
      if (isLine) {   // เส้นวัดระยะ: ป้ายความยาวติดถาวรกลางเส้น เหมือน Google Earth
        const pts = g.coordinates.map(toLL);
        L.tooltip({ permanent: true, direction: 'center', className: 'gl measure-tip', interactive: false })
          .setLatLng(lineMid(pts)).setContent(fmtDist(pathLen(pts))).addTo(siteLayer);
      }
    }
    if (s.lat == null || s.lng == null) continue;
    const icon = L.divIcon({
      className: 'pin-wrap', iconSize: [22, 22], iconAnchor: [11, 11],
      html: (() => {
        const dropping = drop.first || drop.ids.has(s.id);
        const delay = drop.first ? ` style="animation-delay:${Math.round(n++ * step)}ms"` : '';
        return `<div class="pin ${st}${s.id === state.selectedId ? ' sel' : ''}${state.picked.has(s.id) ? ' picked' : ''}${dropping ? ' drop' : ''}"${delay}></div>`;
      })(),
    });
    const m = L.marker([s.lat, s.lng], { icon, title: [s.code, s.name].filter(Boolean).join(' — ') })
      .bindTooltip(esc(siteLabel(s)), { permanent: true, direction: 'right', className: 'gl', offset: [8, 0] })
      .on('click', () => siteClick(s.id))
      .addTo(siteLayer);
    markers.set(s.id, m);
  }
  if (list.length) drop.first = false;
  drop.ids.clear();
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

// ------------------------------------------------------------- การวัด ---
const R_EARTH = 6371008.8;
const toRad = (d) => (d * Math.PI) / 180;
function distM(a, b) {  // a, b = [lat, lng]
  const dLat = toRad(b[0] - a[0]), dLng = toRad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(h)));
}
const pathLen = (pts) => pts.reduce((s, p, i) => (i ? s + distM(pts[i - 1], p) : 0), 0);
function ringArea(pts) {  // พื้นที่บนทรงกลม (ตร.ม.) ของรูปปิดจาก [lat, lng]
  if (pts.length < 3) return 0;
  let s = 0;
  for (let i = 0; i < pts.length; i++) {
    const [la1, ln1] = pts[i], [la2, ln2] = pts[(i + 1) % pts.length];
    s += toRad(ln2 - ln1) * (2 + Math.sin(toRad(la1)) + Math.sin(toRad(la2)));
  }
  return Math.abs((s * R_EARTH * R_EARTH) / 2);
}
const fmtDist = (m) => (m < 1000 ? `${m < 10 ? m.toFixed(1) : Math.round(m).toLocaleString('th-TH')} ม.`
  : `${(m / 1000).toLocaleString('th-TH', { maximumFractionDigits: m < 10000 ? 2 : 1 })} กม.`);
function fmtArea(m2) {
  const main = m2 < 1e6 ? `${Math.round(m2).toLocaleString('th-TH')} ตร.ม.` : `${(m2 / 1e6).toLocaleString('th-TH', { maximumFractionDigits: 2 })} ตร.กม.`;
  const rai = m2 / 1600;  // 1 ไร่ = 1,600 ตร.ม.
  return `${main} (${rai.toLocaleString('th-TH', { maximumFractionDigits: rai < 10 ? 2 : 1 })} ไร่)`;
}
function destPoint([lat, lng], m, bearingDeg) {
  const d = m / R_EARTH, b = toRad(bearingDeg), p1 = toRad(lat), l1 = toRad(lng);
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [(p2 * 180) / Math.PI, (l2 * 180) / Math.PI];
}
// GeoJSON [lng, lat] <-> Leaflet [lat, lng]
const toLL = (c) => [c[1], c[0]];
const toXY = (p) => [+p[1].toFixed(7), +p[0].toFixed(7)];
function measureGeom(g) {
  if (!g) return '';
  if (g.type === 'LineString') return `ยาว ${fmtDist(pathLen(g.coordinates.map(toLL)))}`;
  if (g.type === 'Polygon') {
    const ring = g.coordinates[0].map(toLL).slice(0, -1);
    return `พื้นที่ ${fmtArea(ringArea(ring))} · เส้นรอบรูป ${fmtDist(pathLen([...ring, ring[0]]))}`;
  }
  if (g.type === 'Circle') return `รัศมี ${fmtDist(g.radius)} · พื้นที่ ${fmtArea(Math.PI * g.radius ** 2)}`;
  if (g.type === 'GeometryCollection') return g.geometries.map(measureGeom).filter(Boolean).join(' / ');
  return '';
}
function geomLayer(g, style) {
  if (g.type === 'Circle') return L.circle(toLL(g.center), { radius: g.radius, ...style });
  if (g.type === 'GeometryCollection') return L.featureGroup(g.geometries.map((x) => geomLayer(x, style)));
  return L.geoJSON(g, { style, pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4, ...style }) });
}
function geomBounds(g) {
  if (g.type === 'Circle') return L.latLng(toLL(g.center)).toBounds(g.radius * 2);
  if (g.type === 'GeometryCollection') {
    const b = L.latLngBounds([]);
    g.geometries.forEach((x) => b.extend(geomBounds(x)));
    return b;
  }
  return L.geoJSON(g).getBounds();
}
function lineMid(pts) {  // จุดกึ่งกลางตามความยาวเส้น (ไว้วางป้ายระยะ)
  const half = pathLen(pts) / 2;
  let acc = 0;
  for (let i = 1; i < pts.length; i++) {
    const d = distM(pts[i - 1], pts[i]);
    if (acc + d >= half) { const f = (half - acc) / (d || 1); return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f]; }
    acc += d;
  }
  return pts[0];
}

// ---------------------------------------- โหมดบนแผนที่: เพิ่ม/ย้าย/วาด/วงกลม/วัด/แก้รูปร่าง ---
const DRAW_LABEL = { polygon: 'พื้นที่', line: 'เส้น', circle: 'วงกลม' };
const PREVIEW = { color: '#00e5ff', weight: 2.5, dashArray: '6 4', interactive: false };
// state.mode: 'add-point' | 'move' | 'draw' (state.drawKind = polygon/line) | 'circle' | 'measure' | 'edit'
function setMode(mode, target = null, kind = null) {
  state.mode = mode; state.drawPts = []; state.drawTarget = target; state.drawKind = kind;
  state.hoverLL = null; state.circle = null; state.edit = null; state.measureClosed = false;
  drawLayer.clearLayers();
  $('.map-wrap').classList.toggle('crosshair', !!mode && mode !== 'edit');
  $('#btnAddPoint').classList.toggle('active', mode === 'add-point');
  $('#btnAddArea').classList.toggle('active', (mode === 'draw' || mode === 'circle') && !target);
  $('#btnRuler').classList.toggle('active', mode === 'measure');
  renderMap();   // ซ่อนรูปร่างเดิมระหว่างแก้ / แสดงกลับเมื่อเลิก
  renderModeBar();
}
function startDraw(kind, target = null) {
  if (!needUser()) return;
  if (kind === 'circle') setMode('circle', target);
  else setMode('draw', target, kind);
}
function currentMeasure() {
  const pts = state.drawPts.concat(state.hoverLL && state.mode !== 'edit' ? [state.hoverLL] : []);
  if (state.mode === 'draw' && state.drawKind === 'polygon') {
    return pts.length >= 3 ? `พื้นที่ ${fmtArea(ringArea(pts))} · เส้นรอบรูป ${fmtDist(pathLen([...pts, pts[0]]))}`
      : pts.length === 2 ? `ด้าน ${fmtDist(pathLen(pts))}` : '';
  }
  if (state.mode === 'draw') return pts.length >= 2 ? `ยาว ${fmtDist(pathLen(pts))}` : '';
  if (state.mode === 'measure') {
    if (!pts.length) return '';
    let t = `ระยะรวม ${fmtDist(pathLen(pts))}`;
    if (pts.length >= 2) t += ` · ช่วงล่าสุด ${fmtDist(distM(pts[pts.length - 2], pts[pts.length - 1]))}`;
    if (state.measureClosed && pts.length >= 3) t = `พื้นที่ ${fmtArea(ringArea(pts))} · เส้นรอบรูป ${fmtDist(pathLen([...pts, pts[0]]))}`;
    return t;
  }
  if (state.mode === 'circle' && state.circle) {
    const r = state.circle.r ?? (state.hoverLL ? distM(state.circle.c, state.hoverLL) : 0);
    return r ? `รัศมี ${fmtDist(r)} · พื้นที่ ${fmtArea(Math.PI * r * r)}` : '';
  }
  if (state.mode === 'edit' && state.edit) return measureGeom(editGeom());
  return '';
}
function renderModeBar() {
  const bar = $('#modeBar');
  const m = state.mode;
  if (!m) { bar.hidden = true; bar.innerHTML = ''; return; }
  const n = state.drawPts.length;
  const hint = {
    'add-point': 'คลิกบนแผนที่ตรงตำแหน่งที่ต้องการเพิ่มจุด',
    move: 'คลิกบนแผนที่ตรงตำแหน่งใหม่ของจุดนี้',
    draw: state.drawKind === 'line' ? `วาดเส้น: คลิกทีละจุด (${n} จุด) ดับเบิลคลิกหรือกด “เสร็จ” เมื่อครบ`
      : `วาดพื้นที่: คลิกทีละมุม (${n} มุม) ดับเบิลคลิกหรือกด “เสร็จ” เมื่อครบ`,
    circle: state.circle ? 'คลิกเพื่อกำหนดรัศมี หรือพิมพ์รัศมีแล้วกด Enter' : 'คลิกตรงจุดศูนย์กลางของวงกลม',
    measure: 'วัดระยะ: คลิกทีละจุดบนแผนที่ (ไม่บันทึก)',
    edit: 'ลากจุดเพื่อย้าย · คลิกจุดเล็กกลางเส้นเพื่อเพิ่มมุม · ดับเบิลคลิกจุดเพื่อลบ',
  }[m];
  const meas = currentMeasure();
  let btns = '';
  if (m === 'draw') btns = `<button class="btn small light" data-mb="finish" ${n < (state.drawKind === 'line' ? 2 : 3) ? 'disabled' : ''}>${ic('check')}เสร็จ</button>
    <button class="btn small on-glass" data-mb="undo" ${n ? '' : 'disabled'}>${ic('undo')}ลบจุดล่าสุด</button>`;
  if (m === 'circle' && state.circle) btns = `<label class="mb-radius">รัศมี <input id="mbRadius" inputmode="decimal" placeholder="ม." size="7"> ม.</label>
    <button class="btn small light" data-mb="finish">${ic('check')}เสร็จ</button>`;
  if (m === 'measure') btns = `<label class="mb-check"><input type="checkbox" data-mb="close" ${state.measureClosed ? 'checked' : ''}> ปิดรูป (วัดพื้นที่)</label>
    <button class="btn small on-glass" data-mb="undo" ${n ? '' : 'disabled'}>${ic('undo')}ลบจุดล่าสุด</button>
    <button class="btn small on-glass" data-mb="clear" ${n ? '' : 'disabled'}>ล้าง</button>
    <button class="btn small light" data-mb="save" ${n >= (state.measureClosed ? 3 : 2) ? '' : 'disabled'}>${ic('plus')}บันทึกเป็น${state.measureClosed ? 'พื้นที่' : 'เส้น'}</button>`;
  if (m === 'edit') btns = `<button class="btn small light" data-mb="save-edit">${ic('check')}บันทึกรูปร่าง</button>`;
  const keepRadius = $('#mbRadius') && document.activeElement === $('#mbRadius') ? $('#mbRadius').value : null;
  bar.innerHTML = `<div class="mb-text"><span>${esc(hint)}</span>${meas ? `<b class="mb-meas">${esc(meas)}</b>` : ''}</div>
    <div class="mb-btns">${btns}<button class="btn small on-glass" data-mb="cancel">${ic('x')}${m === 'measure' ? 'ปิด' : 'ยกเลิก'}</button></div>`;
  bar.hidden = false;
  if (keepRadius !== null) { const r = $('#mbRadius'); r.value = keepRadius; r.focus(); }
}
// อัปเดตเฉพาะตัวเลขระหว่างขยับเมาส์ (ไม่สร้างแถบใหม่ทั้งแถบ)
function updateMeasureText() {
  const el = $('#modeBar .mb-meas'), t = currentMeasure();
  if (el) el.textContent = t; else if (t) renderModeBar();
}
$('#modeBar').addEventListener('click', (e) => {
  const b = e.target.closest('[data-mb]');
  if (!b || b.disabled) return;
  const a = b.dataset.mb;
  if (a === 'cancel') setMode(null);
  else if (a === 'finish') state.mode === 'circle' ? finishCircle() : finishDraw();
  else if (a === 'undo') { state.drawPts.pop(); redrawPreview(); renderModeBar(); }
  else if (a === 'clear') { state.drawPts = []; redrawPreview(); renderModeBar(); }
  else if (a === 'save') saveMeasureAsSite();
  else if (a === 'save-edit') saveEdit();
});
$('#modeBar').addEventListener('change', (e) => {
  if (e.target.dataset.mb === 'close') { state.measureClosed = e.target.checked; redrawPreview(); renderModeBar(); }
});
$('#modeBar').addEventListener('keydown', (e) => {
  if (e.target.id === 'mbRadius' && e.key === 'Enter') { e.preventDefault(); finishCircle(); }
});
$('#modeBar').addEventListener('input', (e) => {
  if (e.target.id !== 'mbRadius' || !state.circle) return;
  const r = parseFloat(e.target.value.replace(/,/g, ''));
  state.circle.r = r > 0 ? r : null;
  redrawPreview(); updateMeasureText();
});

function redrawPreview() {
  drawLayer.clearLayers();
  // interactive:false — ไม่งั้นเส้น/จุดที่วาดอยู่จะกินคลิกของแผนที่ ทำให้คลิกต่อหรือดับเบิลคลิกจบไม่ได้
  if (state.mode === 'circle' && state.circle) {
    const r = state.circle.r ?? (state.hoverLL ? distM(state.circle.c, state.hoverLL) : 0);
    L.circleMarker(state.circle.c, { radius: 4, color: '#00e5ff', fillOpacity: 1, interactive: false }).addTo(drawLayer);
    if (r) {
      L.circle(state.circle.c, { ...PREVIEW, radius: r, fillOpacity: 0.12 }).addTo(drawLayer);
      const edge = destPoint(state.circle.c, r, 90);
      L.polyline([state.circle.c, edge], { ...PREVIEW, dashArray: null, weight: 1.5 }).addTo(drawLayer);
      L.tooltip({ permanent: true, direction: 'top', className: 'gl measure-tip', interactive: false })
        .setLatLng(lineMid([state.circle.c, edge])).setContent(fmtDist(r)).addTo(drawLayer);
    }
    return;
  }
  const pts = state.drawPts;
  if (!pts.length) return;
  const all = state.hoverLL ? pts.concat([state.hoverLL]) : pts;
  const closed = (state.mode === 'draw' && state.drawKind === 'polygon') || (state.mode === 'measure' && state.measureClosed);
  if (closed && all.length >= 3) L.polygon(all, { ...PREVIEW, fillOpacity: 0.15 }).addTo(drawLayer);
  else L.polyline(all, PREVIEW).addTo(drawLayer);
  pts.forEach((p) => L.circleMarker(p, { radius: 4, color: '#00e5ff', fillOpacity: 1, interactive: false }).addTo(drawLayer));
  if (state.mode === 'measure' || state.drawKind === 'line') {   // ป้ายระยะสะสมที่แต่ละจุด เหมือนไม้บรรทัดใน Google Earth
    let acc = 0;
    all.forEach((p, i) => {
      if (!i) return;
      acc += distM(all[i - 1], p);
      L.tooltip({ permanent: true, direction: 'right', offset: [8, 0], className: 'gl measure-tip', interactive: false })
        .setLatLng(p).setContent(fmtDist(acc)).addTo(drawLayer);
    });
  }
}
map.on('mousemove', (e) => {
  if (!['draw', 'measure', 'circle'].includes(state.mode)) return;
  if (state.mode === 'circle' && (!state.circle || state.circle.r != null)) return;
  if (state.mode !== 'circle' && !state.drawPts.length) return;
  state.hoverLL = [e.latlng.lat, e.latlng.lng];
  redrawPreview(); updateMeasureText();
});
map.on('mouseout', () => { if (state.hoverLL) { state.hoverLL = null; redrawPreview(); updateMeasureText(); } });
map.on('click', (e) => {
  const ll = [e.latlng.lat, e.latlng.lng];
  const [lat, lng] = ll;
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
  } else if (state.mode === 'draw' || state.mode === 'measure') {
    state.drawPts.push(ll);
    redrawPreview(); renderModeBar();
  } else if (state.mode === 'circle') {
    if (!state.circle) { state.circle = { c: ll, r: null }; state.hoverLL = null; renderModeBar(); setTimeout(() => $('#mbRadius')?.focus(), 0); }
    else { state.circle.r = state.circle.r ?? distM(state.circle.c, ll); finishCircle(); }
    redrawPreview();
  }
});
map.on('dblclick', (e) => {
  if (state.mode === 'draw') { L.DomEvent.stop(e); finishDraw(); }
});
map.doubleClickZoom.disable();
map.on('dblclick', (e) => { if (!['draw', 'measure', 'circle', 'edit'].includes(state.mode)) map.setZoomAround(e.latlng, map.getZoom() + 1); });

// ดับเบิลคลิกจะนับเป็นคลิกเดี่ยวสองครั้งด้วย จึงตัดจุดซ้ำที่อยู่ติดกันออก
const dedupe = (pts) => pts.filter((p, i, a) => i === 0 || p[0] !== a[i - 1][0] || p[1] !== a[i - 1][1]);
function geomFromPts(pts, kind) {
  if (kind === 'line') return { type: 'LineString', coordinates: pts.map(toXY) };
  const ring = pts.map(toXY);
  ring.push(ring[0]);
  return { type: 'Polygon', coordinates: [ring] };
}
function saveGeometry(geometry, anchor, nameHint) {
  const target = state.drawTarget;
  setMode(null);
  if (target) {
    guard(async () => {
      await api('PUT', `/api/sites/${target}`, { geometry: JSON.stringify(geometry) });
      toast(`บันทึกรูปร่างแล้ว · ${measureGeom(geometry)}`);
      await reloadAll(); await selectSite(target, false);
    });
  } else {
    openSiteForm({ lat: anchor[0], lng: anchor[1], geometry: JSON.stringify(geometry), name: nameHint || '' });
  }
}
function finishDraw() {
  const kind = state.drawKind;
  const pts = dedupe(state.drawPts);
  if (pts.length < (kind === 'line' ? 2 : 3)) { toast(kind === 'line' ? 'เส้นต้องมีอย่างน้อย 2 จุด' : 'พื้นที่ต้องมีอย่างน้อย 3 มุม', true); return; }
  const anchor = kind === 'line' ? lineMid(pts) : [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
  saveGeometry(geomFromPts(pts, kind), anchor);
}
function finishCircle() {
  const c = state.circle;
  if (!c || !(c.r > 0)) { toast('ยังไม่ได้กำหนดรัศมี', true); return; }
  const r = Math.round(c.r * 10) / 10;
  saveGeometry({ type: 'Circle', center: toXY(c.c), radius: r }, c.c, `รัศมี ${fmtDist(r)}`);
}
function saveMeasureAsSite() {
  if (!needUser()) return;
  const pts = dedupe(state.drawPts);
  const kind = state.measureClosed ? 'polygon' : 'line';
  const g = geomFromPts(pts, kind);
  saveGeometry(g, kind === 'line' ? lineMid(pts) : pts[0], kind === 'line' ? `เส้นวัดระยะ ${fmtDist(pathLen(pts))}` : '');
}
$('#btnRuler').onclick = () => setMode(state.mode === 'measure' ? null : 'measure');
$('#drawMenu').addEventListener('click', (e) => {
  const b = e.target.closest('[data-draw]');
  if (!b) return;
  $('#drawMenu').open = false;
  startDraw(b.dataset.draw);
});

// --- แก้รูปร่างเดิม: ลากจุดยอด, คลิกจุดกลางเส้นเพื่อเพิ่มมุม, ดับเบิลคลิกจุดยอดเพื่อลบ, วงกลมลากศูนย์กลาง/รัศมี
function editableOf(g) {  // แปลงเป็นโครงสร้างที่แก้ได้ (เฉพาะรูปร่างแรกที่แก้ได้ของ GeometryCollection)
  if (g.type === 'GeometryCollection') {
    const i = g.geometries.findIndex((x) => ['LineString', 'Polygon', 'Circle'].includes(x.type));
    return i < 0 ? null : { ...editableOf(g.geometries[i]), parent: g, index: i };
  }
  if (g.type === 'LineString') return { kind: 'line', pts: g.coordinates.map(toLL) };
  if (g.type === 'Polygon') return { kind: 'polygon', pts: g.coordinates[0].map(toLL).slice(0, -1), holes: g.coordinates.slice(1) };
  if (g.type === 'Circle') return { kind: 'circle', c: toLL(g.center), r: g.radius };
  return null;
}
function editGeom() {
  const ed = state.edit;
  let g;
  if (ed.kind === 'circle') g = { type: 'Circle', center: toXY(ed.c), radius: Math.round(ed.r * 10) / 10 };
  else {
    g = geomFromPts(ed.pts, ed.kind);
    if (ed.holes && ed.holes.length) g.coordinates.push(...ed.holes);
  }
  if (ed.parent) { const p = JSON.parse(JSON.stringify(ed.parent)); p.geometries[ed.index] = g; return p; }
  return g;
}
function startEdit(site) {
  const g = parseGeom(site.geometry);
  const ed = g && editableOf(g);
  if (!ed) { toast('จุดนี้ยังไม่มีรูปร่างให้แก้ไข', true); return; }
  if (!needUser()) return;
  setMode('edit', site.id);
  state.edit = ed;
  focusOn(geomBounds(g), 18);
  drawEditHandles();
  renderModeBar();
}
const vtxIcon = (cls) => L.divIcon({ className: 'vtx-wrap', html: `<div class="vtx ${cls}"></div>`, iconSize: [16, 16], iconAnchor: [8, 8] });
function drawEditHandles() {
  drawLayer.clearLayers();
  const ed = state.edit;
  const shapeStyle = { ...PREVIEW, dashArray: null, interactive: false };
  let shape;
  if (ed.kind === 'circle') shape = L.circle(ed.c, { ...shapeStyle, radius: ed.r, fillOpacity: 0.12 });
  else shape = ed.kind === 'polygon' ? L.polygon(ed.pts, { ...shapeStyle, fillOpacity: 0.12 }) : L.polyline(ed.pts, shapeStyle);
  shape.addTo(drawLayer);
  const refresh = () => {
    if (ed.kind === 'circle') { shape.setLatLng(ed.c); shape.setRadius(ed.r); } else shape.setLatLngs(ed.pts);
    updateMeasureText();
  };
  if (ed.kind === 'circle') {
    const center = L.marker(ed.c, { draggable: true, icon: vtxIcon('center'), title: 'ลากเพื่อย้ายจุดศูนย์กลาง' }).addTo(drawLayer);
    const edge = L.marker(destPoint(ed.c, ed.r, 90), { draggable: true, icon: vtxIcon(''), title: 'ลากเพื่อปรับรัศมี' }).addTo(drawLayer);
    center.on('drag', (e) => { ed.c = [e.latlng.lat, e.latlng.lng]; edge.setLatLng(destPoint(ed.c, ed.r, 90)); refresh(); });
    edge.on('drag', (e) => { ed.r = Math.max(1, distM(ed.c, [e.latlng.lat, e.latlng.lng])); refresh(); });
    return;
  }
  const closed = ed.kind === 'polygon', min = closed ? 3 : 2;
  ed.pts.forEach((p, i) => {
    const mk = L.marker(p, { draggable: true, icon: vtxIcon(''), title: 'ลากเพื่อย้าย · ดับเบิลคลิกเพื่อลบจุดนี้' }).addTo(drawLayer);
    mk.on('drag', (e) => { ed.pts[i] = [e.latlng.lat, e.latlng.lng]; refresh(); });
    mk.on('dragend', drawEditHandles);   // จัดตำแหน่งจุดกลางเส้นใหม่
    mk.on('dblclick', (e) => {
      L.DomEvent.stop(e);
      if (ed.pts.length <= min) { toast(closed ? 'พื้นที่ต้องมีอย่างน้อย 3 มุม' : 'เส้นต้องมีอย่างน้อย 2 จุด', true); return; }
      ed.pts.splice(i, 1); drawEditHandles(); updateMeasureText();
    });
  });
  const segs = closed ? ed.pts.length : ed.pts.length - 1;
  for (let i = 0; i < segs; i++) {
    const a = ed.pts[i], b = ed.pts[(i + 1) % ed.pts.length];
    const mid = L.marker([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], { icon: vtxIcon('mid'), title: 'คลิกเพื่อเพิ่มมุมตรงนี้' }).addTo(drawLayer);
    mid.on('click', (e) => { L.DomEvent.stop(e); ed.pts.splice(i + 1, 0, [e.latlng.lat, e.latlng.lng]); drawEditHandles(); updateMeasureText(); });
  }
}
function saveEdit() {
  const site = state.sites.find((x) => x.id === state.drawTarget);
  const g = editGeom();
  const extra = state.edit.kind === 'circle' && !state.edit.parent ? { lat: state.edit.c[0], lng: state.edit.c[1] } : {};
  const id = state.drawTarget;
  setMode(null);
  guard(async () => {
    await api('PUT', `/api/sites/${id}`, { geometry: JSON.stringify(g), ...extra });
    toast(`บันทึกรูปร่าง ${site ? site.code || site.name : ''} แล้ว · ${measureGeom(g)}`);
    await reloadAll(); await selectSite(id, false);
  });
}
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (!$('#lightbox').hidden) { $('#lightbox').hidden = true; return; }
  if (!$('#modal').hidden) { closeModal(); return; }
  if (state.mode) { setMode(null); return; }
  if (state.selectMode) setSelectMode(false);
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
  for (const id of [...state.picked]) if (!state.sites.some((x) => x.id === id)) state.picked.delete(id);
  updateBulkBar();
  if ($('#tab-history').classList.contains('active')) renderHistoryTab();
  if (typeof TrendChart !== 'undefined') TrendChart.onData();
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

const chip = (m) => `<span class="chip m-${esc(m || 'other')}">${esc(mediaLabel(m))}</span>`;

function renderSites() {
  const list = filteredSites();
  $('#cntSites').textContent = state.sites.length || '';
  $('#siteCount').textContent = list.length === state.sites.length ? `${list.length} จุด`
    : `แสดง ${list.length} จาก ${state.sites.length} จุด`;
  const ul = $('#siteList');
  ul.classList.toggle('selecting', state.selectMode);
  ul.innerHTML = list.length ? list.map((s, i) => {
    const st = siteStatus(s);
    const sub = [
      s.project && `<span>${esc(s.project)}</span>`,
      s.category && `<span>${esc(s.category)}</span>`,
      `<span>${s.n_samples ? `${s.n_samples} ตัวอย่าง · ล่าสุด ${esc(fmtDate(s.last_date))}` : 'ยังไม่มีตัวอย่าง'}</span>`,
      s.n_photos ? `<span title="รูปถ่าย">${ic('image')}${s.n_photos}</span>` : '',
    ].filter(Boolean).join('');
    const exc = s.n_exceed ? `<div class="ex">เกินมาตรฐาน ${s.n_exceed} ค่า · ${esc(s.exceed_params.join(', '))}</div>` : '';
    const chips = s.media.length ? `<div class="chips">${s.media.map(chip).join('')}</div>` : '';
    const delay = ul.classList.contains('first') ? ` style="animation-delay:${Math.min(i * 30, 450)}ms"` : '';
    const pick = state.selectMode ? `<input type="checkbox" class="pick" tabindex="-1" aria-label="เลือก ${esc(s.code || s.name)}" ${state.picked.has(s.id) ? 'checked' : ''}>` : '';
    const hid = state.hidden.has(s.id);
    return `<li data-id="${s.id}" class="${s.id === state.selectedId ? 'sel' : ''}${state.picked.has(s.id) ? ' picked' : ''}${hid ? ' is-hidden' : ''}"${delay}>
      <button class="eye icon-btn" data-eye="${s.id}" title="${hid ? 'แสดงบนแผนที่' : 'ซ่อนบนแผนที่'}" aria-label="${hid ? 'แสดง' : 'ซ่อน'} ${esc(s.code || s.name)} บนแผนที่" aria-pressed="${hid}">${ic(hid ? 'eyeoff' : 'eye')}</button>
      ${pick}<span class="dot ${st}" title="${{ exceed: 'เกินมาตรฐาน', ok: 'ผ่านเกณฑ์', nodata: 'ยังไม่มีผลที่เทียบเกณฑ์ได้' }[st]}"></span>
      <div style="min-width:0"><div class="t">${s.code ? `<span class="code">${esc(s.code)}</span>` : ''}<span class="name">${esc(s.name)}</span>${s.geometry ? ic(shapeIcon(parseGeom(s.geometry))) : ''}</div>
      <div class="s">${sub}</div>${exc}${chips}</div></li>`;
  }).join('') : `<li class="empty">${state.sites.length ? 'ไม่มีจุดที่ตรงกับคำค้นหรือตัวกรอง'
    : 'ยังไม่มีข้อมูล<br>กด “เพิ่มจุดบนแผนที่” หรือนำเข้าไฟล์ KML/KMZ จาก Google Earth'}</li>`;
  if (list.length) setTimeout(() => ul.classList.remove('first'), 800);
  renderMap();
  updateBulkBar();
}

// ------------------------------------------------- เลือกหลายจุด (แก้/ลบ/กราฟ พร้อมกัน) ---
function siteClick(id) {
  if (state.selectMode) togglePick(id); else selectSite(id);
}
function togglePick(id) {
  if (state.picked.has(id)) state.picked.delete(id); else state.picked.add(id);
  renderSites();
}
function setSelectMode(on) {
  state.selectMode = on;
  if (!on) state.picked.clear();
  $('#btnSelect').classList.toggle('active', on);
  renderSites();
}
// ---- ซ่อน/แสดงทีละจุดบนแผนที่ (ค่าการแสดงผลของผู้ใช้แต่ละคน เก็บในเบราว์เซอร์ ไม่แก้ฐานข้อมูล)
const shapeIcon = (g) => (!g ? 'area' : g.type === 'LineString' ? 'line' : g.type === 'Circle' ? 'circle' : 'area');
try { JSON.parse(store.get('hidden', '[]')).forEach((id) => state.hidden.add(id)); } catch { /* ignore */ }
function saveHidden() { store.set('hidden', JSON.stringify([...state.hidden])); }
function toggleHidden(ids, force) {
  const hide = force ?? !ids.every((id) => state.hidden.has(id));
  ids.forEach((id) => (hide ? state.hidden.add(id) : state.hidden.delete(id)));
  saveHidden(); renderSites();
}
$('#showAll').onclick = () => { state.hidden.clear(); saveHidden(); renderSites(); };
$('#bulkHide').onclick = () => toggleHidden([...state.picked], true);
$('#bulkShow').onclick = () => toggleHidden([...state.picked], false);

function updateBulkBar() {
  const n = state.picked.size, shown = filteredSites();
  $('#bulkBar').hidden = !state.selectMode;
  $('#bulkCount').textContent = n;
  const notPicked = shown.filter((s) => !state.picked.has(s.id)).length;
  $('#bulkAll').textContent = notPicked ? `เลือกทั้งหมดที่แสดง (${shown.length})` : '';
  $('#bulkAll').hidden = !notPicked;
  $('#bulkClear').hidden = !n;
  ['#bulkChart', '#bulkEdit', '#bulkDelete', '#bulkHide', '#bulkShow'].forEach((b) => { $(b).disabled = !n; });
  const nh = state.sites.filter((x) => state.hidden.has(x.id)).length;
  $('#showAll').hidden = !nh;
  $('#showAll').textContent = `ซ่อนอยู่ ${nh} จุด · แสดงทั้งหมด`;
}
$('#btnSelect').onclick = () => setSelectMode(!state.selectMode);
$('#bulkDone').onclick = () => setSelectMode(false);
$('#bulkAll').onclick = () => { filteredSites().forEach((s) => state.picked.add(s.id)); renderSites(); };
$('#bulkClear').onclick = () => { state.picked.clear(); renderSites(); };
$('#bulkChart').onclick = () => TrendChart.open({ param: '', siteIds: [...state.picked] });

async function restoreBatch(batch) {
  await guard(async () => {
    const r = await api('POST', `/api/history/batch/${batch}/restore`);
    toast(`ย้อนกลับแล้ว ${r.restored} รายการ`);
    await reloadAll();
    if (state.selectedId && !state.sites.find((x) => x.id === state.selectedId)) closeDetail();
    else if (state.selectedId) await selectSite(state.selectedId, false);
  });
}
const pickedSites = () => state.sites.filter((x) => state.picked.has(x.id));
function pickedPreview(list) {
  const names = list.slice(0, 12).map((x) => `<span class="chip">${esc(x.code || x.name)}</span>`).join(' ');
  return `<div class="chips" style="margin-bottom:14px">${names}${list.length > 12 ? ` <span class="muted small">และอีก ${list.length - 12} จุด</span>` : ''}</div>`;
}
$('#bulkDelete').onclick = () => {
  const list = pickedSites();
  if (!list.length || !needUser()) return;
  if (!confirm(`ลบ ${list.length} จุดที่เลือก?\n(ตัวอย่างและผลวิเคราะห์ของจุดเหล่านี้จะถูกซ่อนไปด้วย กดย้อนกลับได้จากประวัติ)`)) return;
  guard(async () => {
    const r = await api('POST', '/api/sites/bulk', { ids: list.map((x) => x.id), action: 'delete' });
    state.picked.clear();
    if (state.selectedId && list.some((x) => x.id === state.selectedId)) closeDetail();
    await reloadAll();
    toast(`ลบแล้ว ${r.count} จุด`, false, { label: 'ย้อนกลับ', fn: () => restoreBatch(r.batch) });
  });
};
const BULK_FIELDS = [
  ['project', 'โครงการ / เรื่อง', 'dlProjects'], ['category', 'ประเภทจุด', 'dlCategories'],
  ['province', 'จังหวัด', 'dlProvinces'], ['address', 'ที่ตั้ง (ต./อ./จ.)', ''], ['description', 'รายละเอียด / หมายเหตุ', ''],
];
$('#bulkEdit').onclick = () => {
  const list = pickedSites();
  if (!list.length || !needUser()) return;
  const current = (k) => {
    const vals = [...new Set(list.map((x) => x[k] || ''))];
    return vals.length === 1 ? (vals[0] ? `ปัจจุบัน: ${vals[0]}` : 'ปัจจุบัน: (ว่าง)') : `ปัจจุบันมี ${vals.length} ค่าต่างกัน`;
  };
  openModal(`<h2>แก้ไขพร้อมกัน ${list.length} จุด</h2>
    ${pickedPreview(list)}
    <form id="bulkForm">
      <p class="note" style="margin-bottom:12px">ติ๊กเฉพาะช่องที่ต้องการเปลี่ยน ช่องที่ไม่ติ๊กจะคงค่าเดิมของแต่ละจุด
        (ติ๊กแล้วเว้นว่าง = ล้างค่าช่องนั้น) · รหัส ชื่อ และพิกัดแก้ได้ทีละจุดเท่านั้น</p>
      <div class="bulk-fields">${BULK_FIELDS.map(([k, label, dl]) => `
        <label class="bulk-on"><input type="checkbox" data-on="${k}"> ${label}</label>
        ${k === 'description' ? `<textarea name="${k}" rows="2" placeholder="${esc(current(k))}"></textarea>`
          : `<input name="${k}" ${dl ? `list="${dl}"` : ''} placeholder="${esc(current(k))}">`}`).join('')}
      </div>
      <div class="form-actions">
        <button type="button" class="btn" id="bulkCancel">ยกเลิก</button>
        <button class="btn primary" id="bulkSave" disabled>${ic('check')}บันทึก ${list.length} จุด</button>
      </div>
    </form>`);
  const form = $('#bulkForm');
  const sync = () => { $('#bulkSave').disabled = !$$('[data-on]:checked', form).length; };
  form.addEventListener('input', (e) => {
    if (e.target.name) { $(`[data-on="${e.target.name}"]`, form).checked = true; }
    sync();
  });
  $('#bulkCancel').onclick = closeModal;
  form.onsubmit = (e) => {
    e.preventDefault();
    const fields = {};
    $$('[data-on]:checked', form).forEach((c) => { fields[c.dataset.on] = form.elements[c.dataset.on].value; });
    guard(async () => {
      const r = await api('POST', '/api/sites/bulk', { ids: list.map((x) => x.id), action: 'update', fields });
      closeModal();
      await reloadAll();
      if (state.selectedId && state.picked.has(state.selectedId)) await selectSite(state.selectedId, false);
      toast(`แก้ไขแล้ว ${r.count} จุด`, false, { label: 'ย้อนกลับ', fn: () => restoreBatch(r.batch) });
    });
  };
};
$('#siteList').addEventListener('click', (e) => {
  const eye = e.target.closest('[data-eye]');
  if (eye) { e.stopPropagation(); toggleHidden([+eye.dataset.eye]); return; }
  const li = e.target.closest('li[data-id]');
  if (li) siteClick(+li.dataset.id);
});
['#siteSearch', '#fProject', '#fMedia', '#fStatus', '#fSort'].forEach((s) =>
  $(s).addEventListener(s === '#siteSearch' ? 'input' : 'change', renderSites));
$('#siteSearch').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const m = e.target.value.trim().match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
  if (m) {
    const lat = +m[1], lng = +m[2];
    map.setView([lat, lng], 16);
    L.popup().setLatLng([lat, lng]).setContent(`${lat}, ${lng}<br><button class="btn small" id="popAdd" style="margin-top:6px">${ic('pin')}เพิ่มจุดที่นี่</button>`).openOn(map);
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
    if (g) focusOn(geomBounds(g), 17);
    else if (d.lat != null) focusOn(L.latLng(d.lat, d.lng).toBounds(400), Math.max(map.getZoom(), 15));
  }
}
// จัดให้สิ่งที่ดูอยู่ไปอยู่ในส่วนแผนที่ที่มองเห็นได้ ไม่จมใต้แผงรายละเอียดด้านขวา
function focusOn(bounds, maxZoom) {
  const right = !$('#detail').hidden && innerWidth > 860 ? $('#detail').offsetWidth + 40 : 40;
  map.fitBounds(bounds, { paddingTopLeft: [60, 80], paddingBottomRight: [right, 60], maxZoom });
}
function closeDetail() {
  $('#detail').hidden = true; state.selectedId = null; state.detail = null; renderSites();
  $('.map-wrap').classList.remove('has-detail');
}

function stdText(r) {
  if (r.std_min == null && r.std_max == null) return '';
  if (r.std_min != null && r.std_max != null) return `${r.std_min}–${r.std_max}`;
  return r.std_max != null ? `≤ ${r.std_max}` : `≥ ${r.std_min}`;
}
// คำตัดสินสั้นๆ: "เกิน 2.4×" บอกว่าเกินมากแค่ไหน ไม่ใช่แค่เกินหรือไม่
function verdict(r) {
  if (r.exceed === 1) {
    const x = r.std_max ? r.value / r.std_max : null;
    return `<span class="verdict exceed">เกิน${x && x >= 1.05 ? ` ${x >= 10 ? Math.round(x) : x.toFixed(1)}×` : ''}</span>`;
  }
  if (r.exceed === -1) return '<span class="verdict low">ต่ำกว่าเกณฑ์</span>';
  if (r.exceed === 0) return '<span class="verdict ok">ผ่าน</span>';
  return '<span class="verdict muted">–</span>';
}
// เกจเทียบค่ากับมาตรฐาน: ขีดดำ = ค่ามาตรฐาน, แถบ = ค่าที่วัดได้ (สเกล 0 ถึง 1.5 เท่าของเกณฑ์)
function gauge(r) {
  if (r.value == null || (r.std_min == null && r.std_max == null)) return '';
  const top = (r.std_max ?? r.std_min) * 1.5 || 1;
  const pct = (v) => Math.max(0, Math.min(100, (v / top) * 100));
  const cls = r.exceed === 1 ? 'exceed' : r.exceed === -1 ? 'low' : 'ok';
  const ticks = [r.std_min, r.std_max].filter((v) => v != null && v > 0)
    .map((v) => `<i class="tick" style="left:${pct(v).toFixed(1)}%"></i>`).join('');
  const over = r.value > top ? '<i class="over"></i>' : '';
  return `<span class="gauge ${cls}" title="ค่า ${esc(r.value_text)} เทียบเกณฑ์ ${esc(stdText(r))}"><i class="fill" style="width:${pct(r.value).toFixed(1)}%"></i>${ticks}${over}</span>`;
}
const compareCell = (r) => `<span class="cmp">${gauge(r)}${verdict(r)}</span>`;

// ค่าครั้งก่อนของพารามิเตอร์เดียวกัน (ตัวอย่างประเภทเดียวกัน ที่เก็บก่อนหน้า) เพื่อเทียบกับอดีตได้ทันที
function prevHint(sample, r) {
  const k = r.parameter.trim().toLowerCase();
  const older = state.detail.samples.filter((x) => x.media === sample.media && x.id !== sample.id
    && (x.sample_date || '') < (sample.sample_date || ''));
  for (const o of older) {  // samples เรียงจากใหม่ไปเก่าแล้ว ตัวแรกที่เจอคือครั้งก่อนหน้า
    const p = o.results.find((x) => x.parameter.trim().toLowerCase() === k);
    if (!p) continue;
    let arrow = '';
    if (r.value != null && p.value != null && p.value !== r.value) arrow = r.value > p.value ? '↑ ' : '↓ ';
    return `<div class="prev" title="ครั้งก่อน ${esc(fmtDate(o.sample_date))}">${arrow}ครั้งก่อน ${esc(p.value_text)}</div>`;
  }
  return '';
}

function renderDetail() {
  const d = state.detail;
  const el = $('#detail');
  const entering = el.hidden;
  el.hidden = false;
  $('.map-wrap').classList.add('has-detail');
  el.classList.toggle('enter', entering);
  const u = d.lat != null ? UTM.toUTM(d.lat, d.lng) : null;
  const site = state.sites.find((x) => x.id === d.id) || { n_exceed: 0, n_samples: d.samples.length, exceed_params: [] };
  const st = siteStatus(site);
  const strip = {
    exceed: `${ic('alert')}<div><b>เกินมาตรฐาน ${site.n_exceed} ค่า</b> — ${esc(site.exceed_params.join(', '))}</div>`,
    ok: `${ic('check')}<div><b>ผลวิเคราะห์ทั้งหมดอยู่ในเกณฑ์</b> จาก ${d.samples.length} ครั้งที่เก็บ</div>`,
    nodata: d.samples.some((x) => x.results.length)
      ? `${ic('flask')}<div>มีผลวิเคราะห์ แต่ยังไม่มีค่ามาตรฐานให้เทียบ เพิ่มได้ในแท็บ “ค่ามาตรฐาน”</div>`
      : `${ic('flask')}<div>ยังไม่มีผลวิเคราะห์ เพิ่มตัวอย่างแรกได้ที่ด้านล่าง</div>`,
  }[st];
  const geo = parseGeom(d.geometry);
  const hidden = state.hidden.has(d.id);
  const kv = [
    ['โครงการ', d.project], ['จังหวัด', d.province], ['ที่ตั้ง', d.address],
    ['พิกัด', d.lat != null ? `${d.lat.toFixed(6)}, ${d.lng.toFixed(6)}` : 'ไม่ระบุ', true],
    ['UTM', u ? `${u.zone}${u.south ? 'S' : 'N'}  E ${u.E.toFixed(0)}  N ${u.N.toFixed(0)}` : '', true],
    ['ขนาด', geo ? measureGeom(geo) : ''],
    ['รายละเอียด', d.description], ['แก้ไขล่าสุด', fmtDateTime(d.updated_at)],
  ].filter(([, v]) => v);
  const gmaps = d.lat != null ? `https://www.google.com/maps?q=${d.lat},${d.lng}` : null;

  const samples = d.samples.map((s) => {
    const rows = s.results.map((r) => `<tr class="${r.exceed === 1 ? 'exceed' : ''}">
      <td><button class="param-link" data-act="chart" data-param="${esc(r.parameter)}" data-media="${esc(s.media || '')}"
        title="ดูกราฟ ${esc(r.parameter)} ตามวันที่เก็บ">${esc(r.parameter)}${ic('chart')}</button></td>
      <td class="num val">${esc(r.value_text)}${prevHint(s, r)}</td><td class="muted">${esc(r.unit)}</td>
      <td class="num std-text">${esc(stdText(r))}</td><td>${compareCell(r)}</td></tr>`).join('');
    const meta = [s.sample_code && `รหัส ${s.sample_code}`, s.depth && `ลึก ${s.depth}`, s.sampler && `ผู้เก็บ ${s.sampler}`,
      s.lab && `แล็บ ${s.lab}`, s.report_no && `รายงาน ${s.report_no}`].filter(Boolean).join(' · ');
    return `<div class="sample-card">
      <header><div><div class="when">${chip(s.media)}<span class="date">${esc(fmtDate(s.sample_date) || 'ไม่ระบุวันที่')}</span></div>
        ${meta ? `<div class="meta">${esc(meta)}</div>` : ''}</div>
        <div style="display:flex;gap:2px;flex:none">
          <label class="icon-btn" title="เพิ่มรูปของตัวอย่างครั้งนี้" aria-label="เพิ่มรูปของตัวอย่างครั้งนี้">${ic('image')}<input type="file" accept="image/*" multiple hidden data-act="upload" data-sample="${s.id}"></label>
          <button class="icon-btn" data-act="hist-sample" data-id="${s.id}" title="ประวัติการแก้ไขของตัวอย่างนี้" aria-label="ประวัติการแก้ไข">${ic('history')}</button>
          <button class="btn small" data-act="edit-sample" data-id="${s.id}">${ic('edit')}แก้ไข</button></div></header>
      ${s.notes ? `<div class="notes">${esc(s.notes)}</div>` : ''}
      ${(() => {
        const ph = d.photos.filter((p) => p.sample_id === s.id);
        return ph.length ? `<div class="sample-photos">${ph.slice(0, 6).map((p) => `<img data-act="photo" data-idx="${d.photos.indexOf(p)}"
          src="/api/photos/${p.id}/thumb" alt="${esc(p.caption || p.filename)}" loading="lazy">`).join('')}${ph.length > 6 ? `<span class="muted small">+${ph.length - 6}</span>` : ''}</div>` : '';
      })()}
      ${rows ? `<table class="data"><thead><tr><th>พารามิเตอร์</th><th style="text-align:right">ค่า</th><th>หน่วย</th><th style="text-align:right">เกณฑ์</th><th>เทียบเกณฑ์</th></tr></thead><tbody>${rows}</tbody></table>`
        : '<div class="empty-res">ยังไม่มีผลวิเคราะห์</div>'}
    </div>`;
  }).join('');

  const fig = (p) => `<figure data-act="photo" data-idx="${d.photos.indexOf(p)}">
      <img loading="lazy" src="/api/photos/${p.id}/thumb" alt="${esc(p.caption || p.filename)}">
      <figcaption>${esc(p.caption || p.filename || '')}</figcaption></figure>`;
  // จัดกลุ่มรูปตามวันที่ถ่าย (ใหม่ไปเก่า) จะได้แยกออกว่ารูปไหนมาจากการลงพื้นที่ครั้งไหน
  const groups = new Map();
  for (const p of d.photos) {
    const k = (p.taken_at || '').slice(0, 10);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(p);
  }
  const keys = [...groups.keys()].sort((a, b) => (!a) - (!b) || b.localeCompare(a));
  const photos = keys.map((k) => {
    const list = groups.get(k);
    const linked = [...new Set(list.map((p) => p.sample_id).filter(Boolean))]
      .map((id) => d.samples.find((x) => x.id === id)).filter(Boolean);
    return `<div class="photo-day"><div class="photo-day-h"><b>${k ? esc(fmtDate(k)) : 'ไม่ระบุวันที่'}</b>
        <span class="muted">${list.length} รูป</span>${linked.map((x) => chip(x.media)).join('')}</div>
      <div class="photos">${list.map(fig).join('')}</div></div>`;
  }).join('');

  el.innerHTML = `
    <div class="detail-head">
      <button class="icon-btn close" data-act="close" aria-label="ปิด">${ic('x')}</button>
      <div class="kicker">${d.code ? `<span class="mono">${esc(d.code)}</span>` : ''}${d.category ? `<span>${esc(d.category)}</span>` : ''}</div>
      <h2>${esc(d.name)}</h2>
      <div class="detail-actions">
        <button class="btn small" data-act="edit">${ic('edit')}แก้ไขข้อมูล</button>
        <button class="btn small" data-act="move">${ic('move')}ย้ายหมุด</button>
        <details class="menu shape-menu">
          <summary class="btn small">${ic(shapeIcon(geo))}รูปร่าง${ic('chevron')}</summary>
          <div class="menu-items left">
            ${geo ? `<button data-act="shape-edit"><b>แก้ไขรูปร่างเดิม</b><span>ลากจุด เพิ่ม/ลบมุม ปรับรัศมี</span></button>` : ''}
            <button data-act="shape" data-kind="polygon"><b>${geo ? 'วาดใหม่เป็น' : 'วาด'}พื้นที่</b><span>รูปหลายเหลี่ยม</span></button>
            <button data-act="shape" data-kind="line"><b>${geo ? 'วาดใหม่เป็น' : 'วาด'}เส้น</b><span>แนว / เส้นวัดระยะ</span></button>
            <button data-act="shape" data-kind="circle"><b>${geo ? 'วาดใหม่เป็น' : 'วาด'}วงกลม</b><span>กำหนดรัศมีรอบจุด</span></button>
            ${geo ? `<button data-act="shape-clear"><b>ลบรูปร่าง</b><span>เหลือแค่หมุด</span></button>` : ''}
          </div>
        </details>
        <button class="btn small" data-act="toggle-hide" title="${hidden ? 'แสดงจุดนี้บนแผนที่' : 'ซ่อนจุดนี้บนแผนที่'}">${ic(hidden ? 'eye' : 'eyeoff')}${hidden ? 'แสดงบนแผนที่' : 'ซ่อน'}</button>
        ${gmaps ? `<a class="btn small" href="${gmaps}" target="_blank" rel="noopener">นำทาง${ic('external')}</a>` : ''}
        <button class="btn small danger" data-act="delete" style="margin-left:auto">${ic('trash')}ลบ</button>
      </div>
    </div>
    <div class="detail-body">
      <div class="status-strip ${st}">${strip}</div>
      <dl class="kv">${kv.map(([k, v, mono]) => `<dt>${esc(k)}</dt><dd class="${mono ? 'mono' : ''}">${esc(v)}</dd>`).join('')}</dl>

      <div class="sec-h"><span>ตัวอย่างและผลวิเคราะห์<span class="n">${d.samples.length}</span></span>
        <button class="btn small primary" data-act="add-sample">${ic('plus')}เพิ่มตัวอย่าง</button></div>
      ${samples || '<div class="empty-box">ยังไม่มีการเก็บตัวอย่างที่จุดนี้</div>'}

      <div class="sec-h"><span>รูปถ่าย<span class="n">${d.photos.length}</span></span>
        <label class="btn small">${ic('upload')}เพิ่มรูป<input type="file" accept="image/*" multiple hidden data-act="upload"></label></div>
      ${photos || '<div class="empty-box">ยังไม่มีรูป · ถ่ายจากมือถือแล้วอัปโหลดเข้าจุดนี้ได้เลย</div>'}

      <div class="sec-h"><span>ประวัติการแก้ไข</span>
        <button class="btn small" data-act="history">${ic('history')}แสดงประวัติ</button></div>
      <div id="detailHistory" class="timeline"></div>
    </div>`;
}

$('#detail').addEventListener('click', (e) => {
  const t = e.target.closest('[data-act]');
  if (!t) return;
  const d = state.detail;
  const act = t.dataset.act;
  if (act === 'close') closeDetail();
  else if (act === 'edit') openSiteForm(d);
  else if (act === 'move') { if (needUser()) setMode('move', d.id); }
  else if (act === 'shape') { $('#detail .shape-menu').open = false; startDraw(t.dataset.kind, d.id); }
  else if (act === 'shape-edit') { $('#detail .shape-menu').open = false; startEdit(d); }
  else if (act === 'shape-clear') {
    $('#detail .shape-menu').open = false;
    if (!needUser() || !confirm('ลบรูปร่าง (พื้นที่/เส้น/วงกลม) ของจุดนี้? หมุดยังอยู่ และย้อนกลับได้จากประวัติ')) return;
    guard(async () => { await api('PUT', `/api/sites/${d.id}`, { geometry: null }); toast('ลบรูปร่างแล้ว'); await reloadAll(); await selectSite(d.id, false); });
  } else if (act === 'toggle-hide') { toggleHidden([d.id]); renderDetail(); }
  else if (act === 'delete') {
    if (!needUser()) return;
    if (!confirm(`ลบ "${d.name}" ?\n(ข้อมูลยังเก็บอยู่ในประวัติ กู้คืนได้จากแท็บ "ประวัติ")`)) return;
    guard(async () => { await api('DELETE', `/api/sites/${d.id}`); toast('ลบแล้ว'); closeDetail(); await reloadAll(); });
  } else if (act === 'add-sample') openSampleForm({ site_id: d.id });
  else if (act === 'edit-sample') openSampleForm(d.samples.find((s) => s.id === +t.dataset.id));
  else if (act === 'hist-sample') loadDetailHistory({ entity: 'sample', entity_id: t.dataset.id });
  else if (act === 'history') loadDetailHistory({ site_id: d.id });
  else if (act === 'photo') openLightbox(+t.dataset.idx);
  else if (act === 'chart') TrendChart.open({ param: t.dataset.param, media: t.dataset.media, siteIds: [d.id] });
});
$('#detail').addEventListener('change', (e) => {
  if (e.target.dataset.act === 'upload') {
    const files = [...e.target.files];
    const sid = +e.target.dataset.sample || null;
    e.target.value = '';
    openPhotoDialog(files, sid);
  }
});

async function loadDetailHistory(params) {
  const box = $('#detailHistory');
  box.innerHTML = '<div class="muted small">กำลังโหลด…</div>';
  const list = await guard(() => api('GET', '/api/history?' + new URLSearchParams(params)));
  if (!list) return;
  box.innerHTML = list.length ? renderHistoryList(list) : '<div class="muted small">ไม่มีประวัติ</div>';
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
// อ่านวันที่ถ่ายจากข้อมูล EXIF ของกล้อง/มือถือ (DateTimeOriginal) — คืนค่า 'YYYY-MM-DD' หรือ null
async function exifDate(file) {
  try {
    if (!/jpe?g$/i.test(file.type) && !/\.jpe?g$/i.test(file.name)) return null;
    const v = new DataView(await file.slice(0, 256 * 1024).arrayBuffer());
    if (v.getUint16(0) !== 0xFFD8) return null;
    let o = 2;
    while (o + 4 < v.byteLength) {
      const marker = v.getUint16(o), len = v.getUint16(o + 2);
      if (marker === 0xFFE1 && v.getUint32(o + 4) === 0x45786966) {   // "Exif"
        const t = o + 10, le = v.getUint16(t) === 0x4949;
        const u16 = (x) => v.getUint16(t + x, le), u32 = (x) => v.getUint32(t + x, le);
        const ascii = (x, n) => { let r = ''; for (let i = 0; i < n - 1; i++) r += String.fromCharCode(v.getUint8(t + x + i)); return r; };
        const scan = (ifd) => {
          const out = {};
          const n = u16(ifd);
          for (let i = 0; i < n; i++) {
            const e = ifd + 2 + i * 12, tag = u16(e);
            if (tag === 0x8769) out.exif = u32(e + 8);
            if (tag === 0x9003 || tag === 0x0132) out[tag] = ascii(u32(e + 8), u32(e + 4));
          }
          return out;
        };
        const ifd0 = scan(u32(4));
        const sub = ifd0.exif ? scan(ifd0.exif) : {};
        const raw = sub[0x9003] || ifd0[0x0132];
        const m = raw && /^(\d{4}):(\d{2}):(\d{2})/.exec(raw);
        return m && m[1] !== '0000' ? `${m[1]}-${m[2]}-${m[3]}` : null;
      }
      if ((marker & 0xFF00) !== 0xFF00) return null;
      o += 2 + len;
    }
  } catch { /* รูปที่ไม่มี EXIF หรืออ่านไม่ได้ */ }
  return null;
}
const localDate = (ms) => { const d = new Date(ms); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };

async function openPhotoDialog(files, presetSampleId = null) {
  if (!files.length || !needUser()) return;
  const d = state.detail;
  const preset = d.samples.find((x) => x.id === presetSampleId);
  const items = await Promise.all(files.map(async (f) => {
    const ex = await exifDate(f);
    const date = preset?.sample_date || ex || (f.lastModified ? localDate(f.lastModified) : '');
    return { f, url: URL.createObjectURL(f), date, src: preset ? 'sample' : ex ? 'exif' : 'file' };
  }));
  const sampleFor = (date) => d.samples.find((x) => x.sample_date === date && (!preset || x.media === preset.media))?.id
    ?? d.samples.find((x) => x.sample_date === date)?.id ?? (date === preset?.sample_date ? preset.id : '');
  const sampleOpts = (sel) => '<option value="">— ไม่ผูกกับตัวอย่าง —</option>' + d.samples.map((x) =>
    `<option value="${x.id}" ${x.id === +sel ? 'selected' : ''}>${esc(mediaLabel(x.media))} · ${esc(fmtDate(x.sample_date))}${x.sample_code ? ' · ' + esc(x.sample_code) : ''}</option>`).join('');
  const srcText = { exif: 'จากข้อมูลกล้อง', file: 'จากวันที่ไฟล์ · ตรวจวันที่', sample: 'ตามวันที่เก็บตัวอย่าง' };
  openModal(`<h2>เพิ่มรูป ${items.length} รูป — ${esc(d.code || d.name)}</h2>
    <div class="photo-bulk">
      <label>ใช้วันที่นี้กับทุกรูป<input type="date" id="pdAllDate"></label>
      <label>ผูกทุกรูปกับตัวอย่าง<select id="pdAllSample">${sampleOpts('')}</select></label>
    </div>
    <div class="photo-rows">${items.map((it, i) => `<div class="photo-row" data-i="${i}">
      <img src="${it.url}" alt="">
      <div class="photo-fields">
        <div class="muted small photo-name">${esc(it.f.name)}</div>
        <label>วันที่ถ่าย<input type="date" name="date" value="${esc(it.date)}" required>
          <span class="src ${it.src}">${srcText[it.src]}</span></label>
        <label>ตัวอย่างครั้งที่ถ่าย<select name="sample">${sampleOpts(sampleFor(it.date))}</select></label>
        <label class="wide">คำบรรยาย<input name="caption" placeholder="เช่น สภาพจุดเก็บ, สีน้ำ, กองกาก"></label>
      </div></div>`).join('')}</div>
    <div class="form-actions"><button class="btn" id="pdCancel">ยกเลิก</button>
      <button class="btn primary" id="pdSave">${ic('upload')}อัปโหลด ${items.length} รูป</button></div>`);
  const rows = $$('.photo-row');
  const cleanup = () => items.forEach((it) => URL.revokeObjectURL(it.url));
  // เปลี่ยนวันที่ -> เลือกตัวอย่างวันเดียวกันให้อัตโนมัติ (ถ้ายังไม่ได้เลือกเอง)
  rows.forEach((r) => {
    const sel = $('[name=sample]', r);
    $('[name=date]', r).addEventListener('change', (e) => {
      $('.src', r).hidden = true;
      if (!sel.dataset.touched) sel.value = sampleFor(e.target.value);
    });
    sel.addEventListener('change', () => { sel.dataset.touched = 1; });
  });
  $('#pdAllDate').addEventListener('change', (e) => rows.forEach((r) => {
    const inp = $('[name=date]', r); inp.value = e.target.value; inp.dispatchEvent(new Event('change'));
  }));
  $('#pdAllSample').addEventListener('change', (e) => rows.forEach((r) => {
    const sel = $('[name=sample]', r); sel.value = e.target.value; sel.dataset.touched = 1;
    const smp = d.samples.find((x) => x.id === +e.target.value);
    if (smp?.sample_date) { $('[name=date]', r).value = smp.sample_date; $('.src', r).hidden = true; }
  }));
  $('#pdCancel').onclick = () => { cleanup(); closeModal(); };
  $('#pdSave').onclick = () => {
    const missing = rows.filter((r) => !$('[name=date]', r).value);
    if (missing.length) { toast(`ยังไม่ได้ใส่วันที่ ${missing.length} รูป`, true); $('[name=date]', missing[0]).focus(); return; }
    const meta = rows.map((r) => ({ date: $('[name=date]', r).value, sample: +$('[name=sample]', r).value || null, caption: $('[name=caption]', r).value }));
    closeModal();
    guard(async () => {
      for (let i = 0; i < items.length; i++) {
        toast(`กำลังอัปโหลดรูป ${i + 1}/${items.length}…`);
        const img = await loadImage(items[i].f);
        await api('POST', '/api/photos', {
          site_id: d.id, filename: items[i].f.name, taken_at: meta[i].date, sample_id: meta[i].sample, caption: meta[i].caption,
          data: scaled(img, 2000, 0.85), thumb: scaled(img, 360, 0.75),
        });
      }
      cleanup();
      toast(`เพิ่มรูปแล้ว ${items.length} รูป`);
      await reloadAll(); await selectSite(d.id, false);
    });
  };
}

function openLightbox(idx) {
  const photos = state.detail.photos;
  const p = photos[idx];
  if (!p) return;
  const lb = $('#lightbox');
  const sampleOpts = state.detail.samples.map((s) =>
    `<option value="${s.id}" ${s.id === p.sample_id ? 'selected' : ''}>${esc(mediaLabel(s.media))} ${esc(fmtDate(s.sample_date))} ${esc(s.sample_code || '')}</option>`).join('');
  lb.innerHTML = `
    ${idx > 0 ? `<button class="nav" style="left:14px" data-go="-1" aria-label="รูปก่อนหน้า">${ic('left')}</button>` : ''}
    ${idx < photos.length - 1 ? `<button class="nav" style="right:14px" data-go="1" aria-label="รูปถัดไป">${ic('right')}</button>` : ''}
    <img src="/api/photos/${p.id}" alt="">
    <div class="bar">
      <input id="lbCaption" value="${esc(p.caption || '')}" placeholder="คำบรรยายรูป" style="width:260px">
      <input id="lbDate" type="date" value="${esc((p.taken_at || '').slice(0, 10))}">
      <select id="lbSample"><option value="">— ไม่ผูกกับตัวอย่าง —</option>${sampleOpts}</select>
      <button class="btn light" id="lbSave">${ic('check')}บันทึก</button>
      <a class="btn" href="/api/photos/${p.id}" download="${esc(p.filename || 'photo.jpg')}">⬇</a>
      <button class="btn on-glass" id="lbDel">${ic('trash')}ลบรูป</button>
      <button class="btn on-glass" id="lbClose">${ic('x')}ปิด</button>
    </div>
    <div class="info">${idx + 1} / ${photos.length} · ${esc(p.filename || '')}</div>`;
  lb.hidden = false;
  lb.onclick = (e) => {
    if (e.target === lb || e.target.closest('#lbClose')) lb.hidden = true;
    const go = e.target.closest('[data-go]')?.dataset.go;
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
          <div class="cap">กรอกแบบใดแบบหนึ่ง ระบบจะแปลงให้อีกแบบอัตโนมัติ (WGS84)
            ${s.geometry ? ' · จุดนี้มีรูปร่างพื้นที่ (polygon) อยู่แล้ว' : ''}</div>
        </div>
        <label class="full">รายละเอียด / หมายเหตุ<textarea name="description" rows="3">${esc(s.description || '')}</textarea></label>
      </div>
      <input type="hidden" name="geometry" value="${esc(s.geometry || '')}">
      <div class="form-actions">
        <button type="button" class="btn" id="cancelSite">ยกเลิก</button>
        <button class="btn primary">${ic('check')}${isNew ? 'บันทึกจุดใหม่' : 'บันทึกการแก้ไข'}</button>
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
      toast(isNew ? `เพิ่มจุด ${data.code || data.name} แล้ว` : 'บันทึกการแก้ไขแล้ว');
      if (isNew) drop.ids.add(r.id);
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
    <td><button type="button" class="icon-btn" data-del-row title="ลบแถว" aria-label="ลบแถว">${ic('x')}</button></td></tr>`;
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
      <div class="tool-row">
        <button type="button" class="btn small" id="addRow">${ic('plus')}เพิ่มแถว</button>
        <button type="button" class="btn small" id="fillStd" title="เติมรายการพารามิเตอร์ที่มีค่ามาตรฐานของประเภทตัวอย่างนี้">เติมพารามิเตอร์จากค่ามาตรฐาน</button>
        <button type="button" class="btn small" id="pasteBtn">${ic('clipboard')}วางจาก Excel</button>
      </div>
      <div id="pasteBox" hidden style="margin-top:6px">
        <textarea id="pasteText" rows="4" placeholder="คัดลอกคอลัมน์จาก Excel มาวาง: พารามิเตอร์ [Tab] ค่า [Tab] หน่วย (ทีละบรรทัด)"></textarea>
        <button type="button" class="btn small" id="pasteApply">เพิ่มจากข้อความที่วาง</button>
      </div>
      <div class="form-actions">
        ${isNew ? '' : `<button type="button" class="btn danger" id="delSample" style="margin-right:auto">${ic('trash')}ลบตัวอย่างนี้</button>`}
        <button type="button" class="btn" id="cancelSample">ยกเลิก</button>
        <button class="btn primary">${ic('check')}${isNew ? 'บันทึกตัวอย่าง' : 'บันทึกการแก้ไข'}</button>
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
  { key: 'site_code', label: 'รหัสจุด', code: true }, { key: 'site_name', label: 'ชื่อจุด', clip: 1 },
  { key: 'sample_date', label: 'วันที่เก็บ', fmt: fmtDate }, { key: 'media', label: 'ประเภท', html: (r) => chip(r.media) },
  { key: 'parameter', label: 'พารามิเตอร์' },
  { key: 'value', label: 'ค่า', num: true, show: (r) => r.value_text }, { key: 'unit', label: 'หน่วย' },
  { key: 'std', label: 'เกณฑ์', num: true, show: stdText, sortVal: (r) => r.std_max ?? r.std_min },
  { key: 'ratio', label: 'เทียบเกณฑ์', html: compareCell,
    sortVal: (r) => (r.value == null ? null : r.std_max ? r.value / r.std_max : r.std_min ? r.std_min / Math.max(r.value, 1e-9) : null) },
  { key: 'sample_code', label: 'รหัสตัวอย่าง', code: true }, { key: 'depth', label: 'ความลึก' },
  { key: 'project', label: 'โครงการ', clip: 2 }, { key: 'sampler', label: 'ผู้เก็บ' }, { key: 'lab', label: 'แล็บ' },
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
  $('#cntResults').textContent = state.results.length || '';
  const LIMIT = 3000;
  $('#rCount').textContent = `${rows.length.toLocaleString('th-TH')} รายการ` + (rows.length > LIMIT ? ` · แสดง ${LIMIT} แถวแรก` : '');
  const { key, desc } = state.resultSort;
  const head = RESULT_COLS.map((c) => `<th data-key="${c.key}" class="${c.key === key ? 'sorted' + (desc ? ' desc' : '') : ''}">${c.label}</th>`).join('');
  const body = rows.slice(0, LIMIT).map((r) => `<tr data-site="${r.site_id}" class="${r.exceed === 1 ? 'exceed' : ''}">` + RESULT_COLS.map((c) => {
    if (c.html) return `<td>${c.html(r)}</td>`;
    const v = c.show ? c.show(r) : c.fmt ? c.fmt(r[c.key]) : r[c.key];
    return `<td class="${c.num ? 'num' + (c.key === 'value' ? ' val' : ' std-text') : c.code ? 'code' : c.clip ? 'clip' + c.clip : ''}" title="${esc(v)}">${esc(v)}</td>`;
  }).join('') + '</tr>').join('');
  $('#resultsTable').innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body ||
    `<tr><td colspan="${RESULT_COLS.length}" class="empty">${state.results.length ? 'ไม่มีผลที่ตรงกับตัวกรอง' : 'ยังไม่มีผลวิเคราะห์ เปิดจุดบนแผนที่แล้วกด “เพิ่มตัวอย่าง”'}</td></tr>`}</tbody>`;
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
    <div class="h"><span class="act">${ACTION_LABELS[h.action] || h.action}${ENTITY_LABELS[h.entity] || h.entity}</span> ${ownLink}${siteLink}
      ${h.before ? `<button class="btn small" data-restore="${h.id}" title="คืนข้อมูลเป็นสถานะก่อนการเปลี่ยนแปลงนี้">${ic('undo')}ย้อนกลับ</button>` : ''}</div>
    <div class="who">${esc(h.user || '')} · ${esc(fmtDateTime(h.at))}</div>
    ${diff ? `<table>${diff}</table>` : ''}</div>`;
}
async function renderHistoryTab() {
  const params = { limit: 500 };
  if ($('#hEntity').value) params.entity = $('#hEntity').value;
  const list = await guard(() => api('GET', '/api/history?' + new URLSearchParams(params)));
  if (!list) return;
  $('#historyList').innerHTML = list.length ? renderHistoryList(list) : '<div class="empty-box">ยังไม่มีประวัติ</div>';
}
// รายการที่ทำพร้อมกัน (แก้/ลบหลายจุด, นำเข้าไฟล์) รวมเป็นก้อนเดียว ย้อนกลับได้ทั้งชุด
function renderHistoryList(list) {
  const out = [];
  for (let i = 0; i < list.length;) {
    let j = i + 1;
    while (list[i].batch && j < list.length && list[j].batch === list[i].batch) j++;
    out.push(j - i > 1 ? renderHistoryGroup(list.slice(i, j)) : renderHistoryEntry(list[i]));
    i = j;
  }
  return out.join('');
}
function renderHistoryGroup(items) {
  const h = items[0];
  const verbs = { delete: 'ลบ', import: 'นำเข้า', restore: 'ย้อนกลับ', create: 'เพิ่ม', update: 'แก้ไข' };
  const counts = {};
  items.forEach((x) => { counts[x.action] = (counts[x.action] || 0) + 1; });
  const action = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  const ents = {};
  items.forEach((x) => { ents[x.entity] = (ents[x.entity] || 0) + 1; });
  const words = { site: 'จุด', sample: 'ตัวอย่าง', photo: 'รูป', standard: 'ค่ามาตรฐาน' };
  const what = Object.entries(ents).map(([e, n]) => `${n} ${words[e] || 'รายการ'}`).join(', ');
  return `<div class="hist ${action} hist-group">
    <div class="h"><span class="act">${verbs[action] || action}พร้อมกัน</span> ${esc(what)}
      <button class="btn small" data-restore-batch="${esc(h.batch)}" title="คืนทุกรายการในชุดนี้เป็นสถานะก่อนการเปลี่ยนแปลง">${ic('undo')}ย้อนกลับทั้งชุด</button></div>
    <div class="who">${esc(h.user || '')} · ${esc(fmtDateTime(h.at))}</div>
    <details><summary>ดูทีละรายการ</summary><div class="timeline nested">${items.map(renderHistoryEntry).join('')}</div></details>
  </div>`;
}
$('#hEntity').addEventListener('change', renderHistoryTab);
$('#hReload').onclick = renderHistoryTab;
document.addEventListener('click', (e) => {
  const rb = e.target.closest('[data-restore-batch]');
  if (rb) {
    if (!needUser() || !confirm('ย้อนทุกรายการในชุดนี้กลับเป็นสถานะก่อนการเปลี่ยนแปลง?')) return;
    restoreBatch(rb.dataset.restoreBatch).then(() => {
      if ($('#tab-history').classList.contains('active')) renderHistoryTab();
    });
    return;
  }
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
      ${s.id ? `<button class="icon-btn" data-std-del title="ลบ" aria-label="ลบค่ามาตรฐาน">${ic('trash')}</button>` : ''}</td></tr>`;
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
function moveSlider(instant = false) {
  const b = $('.tabs button.active'), sl = $('.tab-slider');
  if (!b) return;
  sl.classList.toggle('instant', instant);
  sl.style.width = b.offsetWidth - 16 + 'px';
  sl.style.transform = `translateX(${b.offsetLeft + 8}px)`;
}
window.addEventListener('resize', () => moveSlider(true));
if (document.fonts) document.fonts.ready.then(() => moveSlider(true));
$$('.tabs button').forEach((b) => b.addEventListener('click', () => {
  $$('.tabs button').forEach((x) => x.classList.toggle('active', x === b));
  moveSlider();
  $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + b.dataset.tab));
  $('#sidebar').classList.toggle('wide', ['results', 'chart', 'history', 'standards'].includes(b.dataset.tab));
  store.set('tab', b.dataset.tab);
  if (b.dataset.tab === 'history') renderHistoryTab();
  if (b.dataset.tab === 'chart') requestAnimationFrame(() => TrendChart.render());
  setTimeout(() => map.invalidateSize(), 250);
}));

// ---------------------------------------------------------------- import ---
$('#btnImportKml').onclick = () => { if (needUser()) $('#fileKml').click(); };
$('#btnImportCsv').onclick = () => {
  if (!needUser()) return;
  openModal(`<h2>นำเข้าผลวิเคราะห์จาก CSV</h2>
    <p>บันทึกไฟล์จาก Excel เป็น <b>CSV UTF-8</b> โดยมีหัวคอลัมน์ (แถวแรก) ตามนี้ — 1 แถว = 1 พารามิเตอร์:</p>
    <pre>site_code,site_name,lat,lng,project,sample_code,sample_date,media,depth,sampler,lab,parameter,value,unit
SW-01,คลองท้ายโรงงาน,13.7301,101.5231,โครงการ A,SW-01-1,2026-05-27,surface_water,,สมชาย,แล็บ X,Pb,0.012,mg/L
SW-01,คลองท้ายโรงงาน,13.7301,101.5231,โครงการ A,SW-01-1,2026-05-27,surface_water,,สมชาย,แล็บ X,pH,7.2,</pre>
    <ul class="small">
      <li>ถ้ารหัสจุด (site_code) มีในฐานข้อมูลแล้ว จะเพิ่มตัวอย่างเข้าจุดเดิม — ถ้ายังไม่มีต้องใส่ lat,lng เพื่อสร้างจุดใหม่</li>
      <li>แถวที่ site / sample_code / sample_date / media / depth ตรงกันจะรวมเป็นตัวอย่างเดียวกัน</li>
      <li>media ใช้ได้: ${Object.entries(state.meta.media).map(([k, v]) => `<code>${k}</code> (${esc(v)})`).join(', ')} — หรือพิมพ์ชื่อไทยก็ได้</li>
      <li>ค่าที่ต่ำกว่าขีดจำกัดการตรวจวัด ใส่เป็น <code>&lt;0.01</code> หรือ <code>ND</code> ได้</li>
    </ul>
    <div class="form-actions"><button class="btn" id="csvCancel">ยกเลิก</button><button class="btn primary" id="csvPick">${ic('upload')}เลือกไฟล์ CSV</button></div>`);
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
document.addEventListener('click', (e) => {  // ปิดเมนูเมื่อคลิกที่อื่น หรือเลือกรายการแล้ว
  $$('.menu').forEach((m) => {
    if (m.open && (!m.contains(e.target) || e.target.closest('.menu-items'))) m.open = false;
  });
});
$$('.menu').forEach((m) => m.addEventListener('toggle', () => {
  if (m.open) $$('.menu').forEach((o) => { if (o !== m) o.open = false; });
}));
hydrateIcons();
moveSlider(true);
(async () => {
  await guard(reloadAll);
  if (state.sites.length) fitAll();
  const tab = store.get('tab', 'sites');
  const b = $(`.tabs button[data-tab="${tab}"]`);
  if (b && tab !== 'sites') b.click();
})();
