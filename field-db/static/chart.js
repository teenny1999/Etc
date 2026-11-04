/* กราฟแนวโน้ม: ค่าพารามิเตอร์หนึ่งตัว ตามวันที่เก็บตัวอย่าง เปรียบเทียบหลายจุด (SVG ล้วน ไม่มีไลบรารี)
   ใช้ตัวแปรร่วมจาก app.js: state, $, $$, esc, fmtDate, mediaLabel, chip, toast, selectSite */
'use strict';

const TrendChart = (() => {
  // ชุดสีแยกจุด (ผ่านการตรวจตาบอดสีแล้วทั้งโหมดสว่าง/มืด) — ตัดสีแดงออกเพราะแดงสงวนไว้สำหรับ "เกินมาตรฐาน"
  const PALETTE = {
    light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6'],
    dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9'],
  };
  const MAX_SERIES = PALETTE.light.length;
  const darkQ = matchMedia('(prefers-color-scheme: dark)');
  const CH = { labels: store.get('chartLabels', '1') === '1', param: '', media: '', range: '', from: '', to: '', view: 'chart', siteIds: [], slots: new Map() };
  let hoverIdx = null;

  const key = (p) => (p || '').trim().toLowerCase();
  const colorOf = (id) => PALETTE[darkQ.matches ? 'dark' : 'light'][CH.slots.get(id) ?? 0];
  const siteOf = (id) => state.sites.find((s) => s.id === id);
  const siteName = (id) => { const s = siteOf(id); return s ? [s.code, s.name].filter(Boolean).join(' ') : `#${id}`; };
  const shortName = (id) => { const s = siteOf(id); return s ? (s.code || s.name) : `#${id}`; };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const ndLimit = (t) => { const m = /^<\s*([\d.,]+)/.exec((t || '').trim()); return m ? parseFloat(m[1].replace(/,/g, '')) : null; };
  const fmtN = (v) => (v == null ? '' : Math.abs(v) >= 1000 ? v.toLocaleString('th-TH', { maximumFractionDigits: 0 })
    : String(+v.toPrecision(4)));

  function addSite(id, quiet) {
    if (CH.siteIds.includes(id)) return true;
    if (CH.siteIds.length >= MAX_SERIES) {
      if (!quiet) toast(`เปรียบเทียบได้สูงสุด ${MAX_SERIES} จุดต่อกราฟ เพื่อให้แยกสีออก`, true);
      return false;
    }
    const used = new Set(CH.slots.values());
    let k = 0;
    while (used.has(k)) k++;
    CH.slots.set(id, k);          // สีผูกกับจุด ไม่ใช่ลำดับ — เอาจุดอื่นออก สีของจุดที่เหลือไม่เปลี่ยน
    CH.siteIds.push(id);
    return true;
  }
  function removeSite(id) {
    CH.siteIds = CH.siteIds.filter((x) => x !== id);
    CH.slots.delete(id);
  }

  // แถวผลวิเคราะห์ของพารามิเตอร์ที่เลือก ตามตัวกรองประเภท/ช่วงเวลา
  function rowsFor(param, { media = CH.media, sites = null } = {}) {
    const k = key(param);
    let from = '', to = '';
    if (CH.range === 'custom') { from = CH.from; to = CH.to; } else if (CH.range) {
      const d = new Date(); d.setMonth(d.getMonth() - +CH.range); from = d.toISOString().slice(0, 10);
    }
    return state.results.filter((r) => key(r.parameter) === k && r.sample_date
      && (!media || r.media === media) && (!from || r.sample_date >= from) && (!to || r.sample_date <= to)
      && (!sites || sites.includes(r.site_id)));
  }

  function autoPick() {
    const counts = new Map();
    for (const r of rowsFor(CH.param)) counts.set(r.site_id, (counts.get(r.site_id) || 0) + 1);
    // จุดที่มีค่าเกินมาตรฐานก่อน แล้วตามจำนวนครั้งที่เก็บ
    const exc = new Set(rowsFor(CH.param).filter((r) => r.exceed === 1).map((r) => r.site_id));
    const ids = [...counts.keys()].sort((a, b) => (exc.has(b) - exc.has(a)) || counts.get(b) - counts.get(a)).slice(0, 4);
    CH.siteIds = []; CH.slots.clear();
    ids.forEach((id) => addSite(id, true));
  }

  // ----------------------------------------------------------- controls ---
  function fillControls() {
    const byKey = new Map();
    for (const r of state.results) {
      const k = key(r.parameter);
      if (!byKey.has(k)) byKey.set(k, { name: r.parameter, n: 0 });
      byKey.get(k).n++;
    }
    const params = [...byKey.values()].sort((a, b) => a.name.localeCompare(b.name, 'th', { numeric: true }));
    $('#cParam').innerHTML = '<option value="">— เลือก —</option>' + params.map((p) =>
      `<option value="${esc(p.name)}" ${key(p.name) === key(CH.param) ? 'selected' : ''}>${esc(p.name)} (${p.n})</option>`).join('');
    const medias = [...new Set(rowsFor(CH.param, { media: '' }).map((r) => r.media))];
    if (CH.media && !medias.includes(CH.media)) CH.media = '';
    $('#cMedia').innerHTML = '<option value="">ทุกประเภท</option>' + medias.map((m) =>
      `<option value="${esc(m)}" ${m === CH.media ? 'selected' : ''}>${esc(mediaLabel(m))}</option>`).join('');
    $('#cRange').value = CH.range;
    $('#cFromBox').hidden = $('#cToBox').hidden = CH.range !== 'custom';

    $('#cSiteChips').innerHTML = CH.siteIds.map((id) => `<span class="site-chip">
      <i class="key" style="background:${colorOf(id)}"></i>${esc(shortName(id))}
      <button data-remove="${id}" aria-label="เอา ${esc(shortName(id))} ออกจากกราฟ">${ic('x')}</button></span>`).join('');
    const avail = [...new Set(rowsFor(CH.param).map((r) => r.site_id))].filter((id) => !CH.siteIds.includes(id) && siteOf(id));
    $('#cAddSite').innerHTML = `<option value="">${avail.length ? '+ เพิ่มจุด' : 'ไม่มีจุดอื่นที่มีข้อมูล'}</option>`
      + avail.map((id) => `<option value="${id}">${esc(siteName(id))}</option>`).join('');
    $('#cAddSite').disabled = !avail.length || CH.siteIds.length >= MAX_SERIES;
    $('#cAuto').hidden = !CH.param;
  }

  // ------------------------------------------------------------- scales ---
  function niceStep(x) {
    const e = Math.floor(Math.log10(x)), f = x / 10 ** e;
    return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * 10 ** e;
  }
  function niceTicks(a, b, n) {
    const step = niceStep((b - a) / n || 1);
    const out = [];
    for (let v = Math.floor(a / step) * step; v <= Math.ceil(b / step) * step + step / 2; v += step) out.push(+v.toPrecision(12));
    return { ticks: out, step };
  }
  function timeTicks(t0, t1, maxN) {
    const day = 864e5, span = (t1 - t0) / day, out = [];
    if (span <= 75) {
      const step = [1, 2, 5, 7, 14, 30].find((s) => span / s <= maxN) || 30;
      const d = new Date(t0); d.setHours(0, 0, 0, 0);
      for (let t = d.getTime(); t <= t1; t += step * day) if (t >= t0) out.push({ t, label: new Date(t).toLocaleDateString('th-TH', { day: 'numeric', month: 'short' }) });
      return out;
    }
    const months = span / 30.4;
    const step = [1, 2, 3, 6, 12, 24, 60].find((s) => months / s <= maxN) || 120;
    const d = new Date(t0); d.setDate(1); d.setHours(0, 0, 0, 0);
    d.setMonth(Math.ceil(d.getMonth() / step) * step);
    for (; d.getTime() <= t1; d.setMonth(d.getMonth() + step)) {
      if (d.getTime() >= t0) out.push({ t: d.getTime(), label: d.toLocaleDateString('th-TH', step >= 12 ? { year: 'numeric' } : { month: 'short', year: '2-digit' }) });
    }
    return out;
  }

  // -------------------------------------------------------------- data ---
  function buildSeries() {
    const rows = rowsFor(CH.param, { sites: CH.siteIds });
    const series = CH.siteIds.map((id) => ({ id, pts: [] }));
    const byId = new Map(series.map((s) => [s.id, s]));
    for (const r of rows) {
      const nd = r.value == null;
      const y = nd ? ndLimit(r.value_text) : r.value;
      byId.get(r.site_id).pts.push({
        t: new Date(r.sample_date + 'T00:00:00').getTime(), date: r.sample_date, y, nd, text: r.value_text,
        unit: r.unit, exceed: r.exceed, stdMin: r.std_min, stdMax: r.std_max, media: r.media, sampleId: r.sample_id,
      });
    }
    series.forEach((s) => s.pts.sort((a, b) => a.t - b.t));
    return { rows, series };
  }

  // ------------------------------------------------------------- render ---
  function render() {
    if (!$('#tab-chart').classList.contains('active')) return;
    if (CH.param && !CH.siteIds.length) autoPick();
    fillControls();
    const box = $('#chart');
    const { rows, series } = buildSeries();
    const plotted = series.flatMap((s) => s.pts.filter((p) => p.y != null));
    const units = [...new Set(rows.map((r) => r.unit).filter(Boolean))];
    const stdKeys = new Set(rows.map((r) => `${r.std_min ?? ''}|${r.std_max ?? ''}`));
    const std = stdKeys.size === 1 && rows.length ? { min: rows[0].std_min, max: rows[0].std_max } : null;

    $('#cTitle').textContent = CH.param ? `${CH.param}${units.length === 1 ? ` (${units[0]})` : ''}` : 'กราฟแนวโน้ม';
    const notes = [CH.param ? `${CH.media ? mediaLabel(CH.media) : 'ทุกประเภทตัวอย่าง'} · ค่าตามวันที่เก็บตัวอย่าง` : ''];
    if (units.length > 1) notes.push(`หน่วยไม่ตรงกัน (${units.join(', ')}) เทียบกันตรงๆ ไม่ได้`);
    if (stdKeys.size > 1) notes.push('ค่ามาตรฐานต่างกันตามประเภทตัวอย่าง เลือกประเภทเพื่อแสดงเส้นเกณฑ์');
    if (plotted.some((p) => p.nd)) notes.push('จุดกลวง = ต่ำกว่าค่าที่ตรวจวัดได้ (วางที่ค่าขีดจำกัด)');
    $('#cSub').textContent = notes.filter(Boolean).join(' · ');

    const legend = series.length >= 2 ? series.map((s) => `<span><i class="key" style="background:${colorOf(s.id)}"></i>${esc(siteName(s.id))}</span>`).join('') : '';
    $('#cLegend').innerHTML = legend;
    $('#cLegend').hidden = !legend;

    $('#chart').hidden = CH.view !== 'chart';
    $('#cPivotWrap').hidden = CH.view !== 'table';
    $$('.seg [data-view]').forEach((b) => b.classList.toggle('on', b.dataset.view === CH.view));
    renderSummary(series, std);
    renderPivot(series);

    if (!CH.param) { box.innerHTML = '<div class="chart-empty">เลือกพารามิเตอร์ด้านบนเพื่อดูค่าตามวันที่เก็บตัวอย่าง</div>'; return; }
    if (!plotted.length) {
      box.innerHTML = `<div class="chart-empty">${CH.siteIds.length ? 'ไม่มีค่าที่เป็นตัวเลขในช่วงเวลาและจุดที่เลือก' : 'ยังไม่ได้เลือกจุดที่จะเปรียบเทียบ'}</div>`;
      return;
    }
    drawSvg(box, series, plotted, std);
  }

  function drawSvg(box, series, plotted, std) {
    const W = Math.max(box.clientWidth, 280);
    const H = W < 560 ? 250 : 320;
    const direct = CH.labels && series.length <= 4 && W >= 560;   // จอแคบ: ใช้คำอธิบายสีด้านบนแทนป้ายปลายเส้น
    const m = { l: 54, r: direct ? 104 : 18, t: 16, b: 32 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;

    const ys = plotted.map((p) => p.y).concat([std?.min, std?.max].filter((v) => v != null));
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (hi === lo) { hi = hi === 0 ? 1 : hi * 1.2; lo = lo > 0 ? 0 : lo; }
    if (lo >= 0 && lo <= 0.35 * hi) lo = 0; else lo -= (hi - lo) * 0.1;
    hi += (hi - lo) * 0.08;
    const { ticks, step } = niceTicks(lo, hi, H < 300 ? 4 : 5);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const dec = Math.max(0, -Math.floor(Math.log10(step)));
    let t0 = Math.min(...plotted.map((p) => p.t)), t1 = Math.max(...plotted.map((p) => p.t));
    if (t1 - t0 < 864e5 * 20) { t0 -= 864e5 * 15; t1 += 864e5 * 15; }
    const pad = (t1 - t0) * 0.04; t0 -= pad; t1 += pad;
    const X = (t) => m.l + ((t - t0) / (t1 - t0)) * iw;
    const Y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;

    const surface = css('--panel'), exceedC = css('--exceed'), lowC = css('--low');
    let g = '';
    for (const v of ticks) {
      g += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>`;
      g += `<text class="tick" x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${v.toLocaleString('th-TH', { minimumFractionDigits: dec, maximumFractionDigits: dec })}</text>`;
    }
    g += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/>`;
    for (const tk of timeTicks(t0, t1, Math.max(3, Math.floor(iw / 80)))) {
      g += `<line class="tickmark" x1="${X(tk.t)}" x2="${X(tk.t)}" y1="${m.t + ih}" y2="${m.t + ih + 4}"/>`;
      g += `<text class="tick" x="${X(tk.t)}" y="${H - 9}" text-anchor="middle">${esc(tk.label)}</text>`;
    }
    // เกณฑ์มาตรฐาน: พื้นที่เกินเกณฑ์แรเงาจาง + เส้นประ + ป้ายบอกค่า
    if (std?.max != null && std.max <= y1) {
      g += `<rect x="${m.l}" y="${m.t}" width="${iw}" height="${Math.max(0, Y(std.max) - m.t)}" fill="${exceedC}" opacity=".07"/>`;
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(std.max)}" y2="${Y(std.max)}" stroke="${exceedC}" stroke-width="1.5" stroke-dasharray="5 4"/>`;
      if (CH.labels) g += `<text class="std-label" x="${m.l + 6}" y="${Y(std.max) - 6}">เกณฑ์สูงสุด ${fmtN(std.max)}</text>`;
    }
    if (std?.min != null && std.min >= y0) {
      g += `<rect x="${m.l}" y="${Y(std.min)}" width="${iw}" height="${Math.max(0, m.t + ih - Y(std.min))}" fill="${lowC}" opacity=".07"/>`;
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(std.min)}" y2="${Y(std.min)}" stroke="${lowC}" stroke-width="1.5" stroke-dasharray="5 4"/>`;
      if (CH.labels) g += `<text class="std-label" x="${m.l + 6}" y="${Y(std.min) + 15}">เกณฑ์ต่ำสุด ${fmtN(std.min)}</text>`;
    }
    // เส้นและจุดของแต่ละจุดเก็บตัวอย่าง
    const ends = [];
    for (const s of series) {
      const pts = s.pts.filter((p) => p.y != null);
      if (!pts.length) continue;
      const c = colorOf(s.id);
      if (pts.length > 1) g += `<path d="${pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.t).toFixed(1)},${Y(p.y).toFixed(1)}`).join('')}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      for (const p of pts) {
        if (p.exceed === 1) g += `<circle cx="${X(p.t)}" cy="${Y(p.y)}" r="8" fill="none" stroke="${exceedC}" stroke-width="1.75"/>`;
        g += `<circle cx="${X(p.t)}" cy="${Y(p.y)}" r="4.5" fill="${p.nd ? surface : c}" stroke="${p.nd ? c : surface}" stroke-width="2"/>`;
      }
      const last = pts[pts.length - 1];
      ends.push({ id: s.id, x: X(last.t), y: Y(last.y), text: `${shortName(s.id)}  ${last.text}` });
    }
    // ป้ายที่ปลายเส้น (≤4 จุด) — ถ้าชนกันให้ใช้คำอธิบายสีด้านบนแทน ไม่ดันป้ายจนหลุดจากเส้น
    if (direct) {
      const ys2 = ends.map((e) => e.y).sort((a, b) => a - b);
      const clash = ys2.some((v, i) => i && v - ys2[i - 1] < 15);
      if (!clash) for (const e of ends) {
        g += `<line x1="${W - m.r + 4}" x2="${W - m.r + 14}" y1="${e.y}" y2="${e.y}" stroke="${colorOf(e.id)}" stroke-width="2" stroke-linecap="round"/>`;
        g += `<text class="end-label" x="${W - m.r + 18}" y="${e.y + 4}">${esc(e.text)}</text>`;
      }
    }

    // ชั้นรับเมาส์/คีย์บอร์ด: เส้นแนวตั้งจับวันที่ใกล้สุด แล้วแสดงทุกจุดในวันนั้น
    const dates = [...new Set(plotted.map((p) => p.t))].sort((a, b) => a - b);
    box.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img"
        aria-label="กราฟ ${esc(CH.param)} ตามวันที่เก็บตัวอย่าง ${series.length} จุด">${g}
      <line class="crosshair" id="cCross" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/>
      <rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" tabindex="0"
        aria-label="เลื่อนดูค่าแต่ละวันด้วยปุ่มลูกศรซ้าย/ขวา"/></svg>
      <div class="chart-tip" id="cTip" hidden></div>`;
    const hit = $('.hit', box), cross = $('#cCross'), tip = $('#cTip');
    const show = (i) => {
      hoverIdx = Math.max(0, Math.min(dates.length - 1, i));
      const t = dates[hoverIdx], x = X(t);
      cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
      const rows = series.map((s) => ({ s, pts: s.pts.filter((p) => p.t === t) })).filter((r) => r.pts.length);
      tip.innerHTML = `<div class="tip-date">${esc(fmtDate(new Date(t).toISOString().slice(0, 10)))}</div>` + rows.map(({ s, pts }) =>
        `<div class="tip-row"><i class="key" style="background:${colorOf(s.id)}"></i>
          <b>${pts.map((p) => esc(p.text)).join(', ')}</b> <span class="muted">${esc(pts[0].unit || '')}</span>
          <span class="tip-name">${esc(shortName(s.id))}</span>
          ${pts.some((p) => p.exceed === 1) ? '<span class="verdict exceed">เกิน</span>' : ''}</div>`).join('');
      tip.hidden = false;
      const tw = tip.offsetWidth;
      tip.style.left = `${x + 14 + tw > W ? x - 14 - tw : x + 14}px`;
      tip.style.top = `${m.t + 4}px`;
    };
    const hide = () => { cross.setAttribute('visibility', 'hidden'); tip.hidden = true; };
    const nearest = (px) => {
      let best = 0, bd = Infinity;
      dates.forEach((t, i) => { const d = Math.abs(X(t) - px); if (d < bd) { bd = d; best = i; } });
      return best;
    };
    hit.addEventListener('pointermove', (e) => show(nearest(e.clientX - box.getBoundingClientRect().left)));
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('focus', () => show(hoverIdx ?? dates.length - 1));
    hit.addEventListener('blur', hide);
    hit.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); show((hoverIdx ?? 0) + (e.key === 'ArrowRight' ? 1 : -1)); }
    });
    hit.addEventListener('click', (e) => {   // คลิกที่วันหนึ่ง -> เปิดจุดแรกที่มีค่าในวันนั้น
      const t = dates[nearest(e.clientX - box.getBoundingClientRect().left)];
      const s = series.find((x) => x.pts.some((p) => p.t === t));
      if (s) selectSite(s.id, false);
    });
  }

  // ตาราง "เทียบกับครั้งก่อนๆ": ต่อจุด — ครั้งแรก, ครั้งก่อน, ล่าสุด, เปลี่ยนจากครั้งก่อน, สูงสุด, จำนวนครั้งที่เกิน
  function renderSummary(series) {
    const tbl = $('#cSummary');
    if (!CH.param || !series.length) { tbl.innerHTML = '<tbody><tr><td class="empty">เลือกพารามิเตอร์และจุดเพื่อดูการเปลี่ยนแปลงเทียบกับครั้งก่อน</td></tr></tbody>'; return; }
    const cell = (p) => p ? `<span class="${p.exceed === 1 ? 'exceed-v' : ''}">${esc(p.text)}</span><div class="when">${esc(fmtDate(p.date))}</div>` : '<span class="muted">–</span>';
    let multi = false;
    const body = series.map((s) => {
      // หลายค่าในวันเดียวกัน (เช่น หลายความลึก) ใช้ค่าที่สูงสุดของวันนั้น
      const perDay = [];
      for (const p of s.pts) {
        const last = perDay[perDay.length - 1];
        if (last && last.t === p.t) { multi = true; if ((p.y ?? -Infinity) > (last.y ?? -Infinity)) perDay[perDay.length - 1] = p; } else perDay.push(p);
      }
      const n = perDay.length, last = perDay[n - 1], prev = perDay[n - 2], first = perDay[0];
      const nums = s.pts.filter((p) => !p.nd && p.y != null);
      const max = nums.reduce((a, p) => (!a || p.y > a.y ? p : a), null);
      let change = '<span class="muted">–</span>';
      if (last && prev && !last.nd && !prev.nd && last.y != null && prev.y != null) {
        if (prev.y === 0) change = last.y === 0 ? 'เท่าเดิม' : '<span class="muted">–</span>';
        else {
          const pct = ((last.y - prev.y) / Math.abs(prev.y)) * 100;
          change = Math.abs(pct) < 0.5 ? 'เท่าเดิม' : `${pct > 0 ? '↑ เพิ่มขึ้น' : '↓ ลดลง'} ${Math.abs(pct) < 10 ? Math.abs(pct).toFixed(1) : Math.round(Math.abs(pct))}%`;
        }
      }
      const nEx = s.pts.filter((p) => p.exceed === 1).length;
      return `<tr data-site="${s.id}"><td><span class="series-name"><i class="key" style="background:${colorOf(s.id)}"></i>${esc(siteName(s.id))}</span></td>
        <td class="num">${n}</td><td class="num">${cell(first)}</td><td class="num">${prev ? cell(prev) : '<span class="muted">–</span>'}</td>
        <td class="num">${cell(last)}</td><td class="num change">${change}</td><td class="num">${cell(max)}</td>
        <td class="num">${nEx ? `<span class="exceed-v">${nEx}</span> / ${s.pts.length}` : `0 / ${s.pts.length}`}</td></tr>`;
    }).join('');
    tbl.innerHTML = `<thead><tr><th>จุด</th><th class="num">ครั้ง</th><th class="num">ครั้งแรก</th><th class="num">ครั้งก่อน</th>
      <th class="num">ล่าสุด</th><th class="num">เทียบครั้งก่อน</th><th class="num">สูงสุด</th><th class="num">เกินเกณฑ์</th></tr></thead><tbody>${body}</tbody>`
      + (multi ? `<caption>วันที่มีหลายค่า (เช่น หลายความลึก) ใช้ค่าที่สูงสุดของวันนั้น</caption>` : '');
  }

  // มุมมองตาราง: วันที่ × จุด (ทางเลือกแทนกราฟ อ่านค่าได้ครบโดยไม่ต้องชี้เมาส์)
  function renderPivot(series) {
    const dates = [...new Set(series.flatMap((s) => s.pts.map((p) => p.date)))].sort().reverse();
    if (!dates.length) { $('#cPivot').innerHTML = '<tbody><tr><td class="empty">ไม่มีข้อมูล</td></tr></tbody>'; return; }
    $('#cPivot').innerHTML = `<thead><tr><th>วันที่เก็บ</th>${series.map((s) => `<th class="num"><span class="series-name"><i class="key" style="background:${colorOf(s.id)}"></i>${esc(shortName(s.id))}</span></th>`).join('')}</tr></thead>
      <tbody>${dates.map((d) => `<tr><td>${esc(fmtDate(d))}</td>${series.map((s) => {
        const pts = s.pts.filter((p) => p.date === d);
        return `<td class="num">${pts.length ? pts.map((p) => `<span class="${p.exceed === 1 ? 'exceed-v' : ''}">${esc(p.text)}</span>`).join(', ') : ''}</td>`;
      }).join('')}</tr>`).join('')}</tbody>`;
  }

  // ------------------------------------------------------------- wiring ---
  $('#cParam').addEventListener('change', (e) => { CH.param = e.target.value; CH.media = ''; CH.siteIds = []; CH.slots.clear(); render(); });
  $('#cMedia').addEventListener('change', (e) => { CH.media = e.target.value; render(); });
  $('#cRange').addEventListener('change', (e) => { CH.range = e.target.value; render(); });
  $('#cFrom').addEventListener('change', (e) => { CH.from = e.target.value; render(); });
  $('#cTo').addEventListener('change', (e) => { CH.to = e.target.value; render(); });
  $('#cAddSite').addEventListener('change', (e) => { if (e.target.value) addSite(+e.target.value); render(); });
  $('#cLabels').checked = CH.labels;
  $('#cLabels').addEventListener('change', (e) => { CH.labels = e.target.checked; store.set('chartLabels', CH.labels ? '1' : '0'); render(); });
  $('#cAuto').addEventListener('click', () => { autoPick(); render(); });
  $('#cSiteChips').addEventListener('click', (e) => {
    const b = e.target.closest('[data-remove]');
    if (b) { removeSite(+b.dataset.remove); render(); }
  });
  $$('.seg [data-view]').forEach((b) => b.addEventListener('click', () => { CH.view = b.dataset.view; render(); }));
  $('#cSummary').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-site]'); if (tr) selectSite(+tr.dataset.site); });
  let raf = 0, lastW = 0;
  new ResizeObserver(() => {
    const w = $('#chart').clientWidth;
    if (!w || w === lastW) return;
    lastW = w; cancelAnimationFrame(raf); raf = requestAnimationFrame(render);
  }).observe($('#chart'));
  darkQ.addEventListener('change', render);

  return {
    render,
    /** เปิดแท็บกราฟพร้อมตั้งค่า เช่น open({ param: 'Pb', media: 'soil', siteIds: [3, 5] }) */
    open({ param, media = '', siteIds = [] } = {}) {
      if (param !== undefined) CH.param = param;
      CH.media = media;
      CH.siteIds = []; CH.slots.clear();
      const ok = siteIds.filter((id) => siteOf(id));
      ok.slice(0, MAX_SERIES).forEach((id) => addSite(id, true));
      if (ok.length > MAX_SERIES) toast(`แสดง ${MAX_SERIES} จุดแรกจาก ${ok.length} จุดที่เลือก (กราฟแยกสีได้สูงสุด ${MAX_SERIES} จุด)`, true);
      if (!CH.param) {   // ยังไม่ได้เลือกสาร: ใช้สารที่จุดเหล่านี้มีข้อมูลมากที่สุด
        const cnt = new Map();
        state.results.filter((r) => !ok.length || ok.includes(r.site_id)).forEach((r) => cnt.set(r.parameter, (cnt.get(r.parameter) || 0) + 1));
        CH.param = [...cnt.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || '';
      }
      $('.tabs button[data-tab="chart"]').click();
    },
    onData() {
      for (const id of [...CH.siteIds]) if (!siteOf(id)) removeSite(id);
      render();
    },
  };
})();
