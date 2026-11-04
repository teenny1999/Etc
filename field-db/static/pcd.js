/* นำเข้า "ตาราง คพ." (รายงานผลตรวจวิเคราะห์ใน Word .docx): อ่านไฟล์ -> ดูตัวอย่าง/ปรับ -> บันทึกทั้งชุด
   ใช้ตัวแปรร่วมจาก app.js: $, $$, esc, api, toast, guard, needUser, openModal, closeModal, chip, mediaLabel,
   fmtDate, reloadAll, fitAll, restoreBatch, state */
'use strict';

const PcdImport = (() => {
  let pv = null;   // ผลจาก /api/import/pcd/preview (แก้ไขตามที่ผู้ใช้ปรับในหน้าต่าง)

  const readB64 = (f) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] || '');
    r.onerror = () => reject(new Error('อ่านไฟล์ไม่ได้: ' + f.name));
    r.readAsDataURL(f);
  });
  const stdText = (st) => (st.min != null && st.max != null ? `${st.min}–${st.max}` : st.max != null ? `≤ ${st.max}` : st.min != null ? `≥ ${st.min}` : '');

  async function open(files) {
    if (!files.length || !needUser()) return;
    await guard(async () => {
      toast(`กำลังอ่าน ${files.length} ไฟล์…`);
      const payload = { files: await Promise.all(files.map(async (f) => ({ name: f.name, data: await readB64(f) }))) };
      pv = await api('POST', '/api/import/pcd/preview', payload);
      $('#toast').hidden = true;
      render(files.map((f) => f.name));
    });
  }

  function siteOptions(s) {
    const same = pv.sites.filter((x) => (x.code || '').toUpperCase() === s.code.toUpperCase());
    const others = pv.sites.filter((x) => !same.includes(x))
      .sort((a, b) => (a.code || a.name).localeCompare(b.code || b.name, 'th', { numeric: true }));
    const opt = (x) => `<option value="${x.id}" ${x.id === s.site_id ? 'selected' : ''}>${esc([x.code, x.name].filter(Boolean).join(' — '))}${x.lat == null ? ' (ไม่มีพิกัด)' : ''}</option>`;
    return `<option value="" ${s.site_id ? '' : 'selected'}>+ สร้างจุดใหม่ ${esc(s.code)}</option>`
      + (same.length ? `<optgroup label="รหัสตรงกัน">${same.map(opt).join('')}</optgroup>` : '')
      + (others.length ? `<optgroup label="จุดอื่นในฐานข้อมูล">${others.map(opt).join('')}</optgroup>` : '');
  }

  function render(names) {
    const S = pv.samples;
    if (!S.length) {
      openModal(`<h2>นำเข้าตาราง คพ.</h2>
        <div class="empty-box">ไม่พบตารางผลตรวจวิเคราะห์ในไฟล์ที่เลือก</div>
        ${pv.warnings.length ? `<ul class="pcd-warn">${pv.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
        <div class="form-actions"><button class="btn" id="pcdClose">ปิด</button></div>`);
      $('#pcdClose').onclick = closeModal;
      return;
    }
    const projects = [...new Set(S.map((s) => s.project).filter(Boolean))];
    const nRes = S.reduce((a, s) => a + s.results.length, 0);
    const status = (s) => (s.existing_sample_id ? '<span class="badge low">มีอยู่แล้ว</span>'
      : s.site_id ? '<span class="muted small">เพิ่มเข้าจุดเดิม</span>' : '<span class="muted small">จุดใหม่ · ยังไม่มีพิกัด</span>');
    const rows = S.map((s, i) => {
      const siteCell = s.dup ? `<span class="muted small">ตามจุด ${esc(s.code)}</span>`
        : `<select data-site="${i}">${siteOptions(s)}</select>`;
      return `<tr class="${s.dup ? 'dup' : ''}" data-i="${i}">
        <td><input type="checkbox" data-inc="${i}" ${s.include ? 'checked' : ''} aria-label="นำเข้า ${esc(s.sample_code)}"></td>
        <td class="code">${esc(s.sample_code)}</td><td>${chip(s.media)}</td>
        <td><input type="date" data-date="${i}" value="${esc(s.date || '')}" title="${esc(s.date_text || '')}"></td>
        <td>${siteCell}</td>
        <td class="loc" title="${esc([s.location, s.section].filter(Boolean).join(' · '))}">${esc(s.location || '')}</td>
        <td class="num" title="${esc(s.results.map((r) => r.parameter).join(', '))}">${s.results.length}</td>
        <td class="st">${status(s)}</td></tr>`;
    }).join('');
    const stdRows = pv.standards.map((st, i) => `<tr>
        <td><input type="checkbox" data-std="${i}" ${st.include ? 'checked' : ''}></td>
        <td>${chip(st.media)}</td><td>${esc(st.parameter)}</td><td class="num">${esc(stdText(st))}</td><td>${esc(st.unit || '')}</td>
        <td class="ref" title="${esc(st.reference)}">${esc(st.reference)}</td>
        <td>${st.existing ? `<span class="badge low" title="ค่าเดิมในระบบ">มีแล้ว: ${esc(stdText(st.existing))}</span>`
          : st.primary ? '' : '<span class="muted small">ทางเลือก (มาตรฐานอื่นของสารเดียวกัน)</span>'}</td></tr>`).join('');
    openModal(`<h2>นำเข้าตาราง คพ.</h2>
      <p class="note">${esc(names.join(', '))} — พบ ${S.length} ตัวอย่าง · ${nRes.toLocaleString('th-TH')} ค่า · ค่ามาตรฐาน ${pv.standards.length} รายการ
        ${pv.skipped_tables ? ` · ข้าม ${pv.skipped_tables} ตารางที่ไม่ใช่ตารางผล` : ''}</p>
      ${pv.warnings.length ? `<ul class="pcd-warn">${pv.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
      <div class="photo-bulk">
        <label>โครงการ (สำหรับจุดใหม่)<input id="pcdProject" list="dlProjects" value="${esc(projects[0] || '')}"></label>
        <label>ตั้งวันที่เก็บทุกตัวอย่าง<input type="date" id="pcdAllDate"></label>
      </div>
      <div class="row gap" style="margin-bottom:6px">
        <button class="link-btn" id="pcdAll">เลือกทั้งหมด</button><button class="link-btn" id="pcdNone">ไม่เลือกเลย</button>
        <span class="muted small">วันที่ตั้งต้นใช้วันแรกของช่วงที่ระบุในรายงาน · จุดที่สร้างใหม่ยังไม่มีพิกัด เลือกจุดเดิม (เช่นที่นำเข้าจาก KMZ) ได้</span>
      </div>
      <div class="table-wrap pcd-table"><table class="data">
        <thead><tr><th></th><th>รหัส</th><th>ประเภท</th><th>วันที่เก็บ</th><th>จุดในฐานข้อมูล</th><th>รายละเอียดจุดในรายงาน</th><th class="num">ค่า</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      ${pv.standards.length ? `<details class="pcd-std"><summary>ค่ามาตรฐานจากตาราง <span id="pcdStdCount"></span></summary>
        <p class="note">ติ๊กเฉพาะค่าที่ต้องการบันทึกลงแท็บ "ค่ามาตรฐาน" (ค่าที่ติ๊กและมีอยู่แล้วจะถูกแทนที่ · ประเภทตัวอย่างดูจากชื่อมาตรฐาน)</p>
        <div class="table-wrap pcd-table"><table class="data"><thead><tr><th></th><th>ประเภท</th><th>พารามิเตอร์</th><th class="num">เกณฑ์</th><th>หน่วย</th><th>อ้างอิง</th><th></th></tr></thead>
        <tbody>${stdRows}</tbody></table></div></details>` : ''}
      <div class="form-actions"><button class="btn" id="pcdCancel">ยกเลิก</button>
        <button class="btn primary" id="pcdSave"></button></div>`);
    $('.modal-box').classList.add('wide');
    const box = $('#modalBody');
    const count = () => {
      const n = S.filter((s) => s.include).length, m = pv.standards.filter((s) => s.include).length;
      $('#pcdSave').innerHTML = `${ic('upload')}นำเข้า ${n} ตัวอย่าง${m ? ` + ค่ามาตรฐาน ${m}` : ''}`;
      $('#pcdSave').disabled = !n && !m;
      if ($('#pcdStdCount')) $('#pcdStdCount').textContent = `(${pv.standards.length} รายการ · เลือกไว้ ${m})`;
    };
    count();
    box.onchange = (e) => {   // onchange (ไม่ใช่ addEventListener) เพราะ #modalBody ใช้ซ้ำทุกหน้าต่าง
      const t = e.target;
      if (t.dataset.inc) S[+t.dataset.inc].include = t.checked;
      if (t.dataset.std) pv.standards[+t.dataset.std].include = t.checked;
      if (t.dataset.date) S[+t.dataset.date].date = t.value || null;
      if (t.dataset.site) {   // จุดของตัวอย่างหลัก -> ตัวอย่างซ้ำ (Dup) ใช้จุดเดียวกัน
        const s = S[+t.dataset.site];
        s.site_id = +t.value || null;
        S.filter((x) => x.dup && x.code === s.code && x.media === s.media).forEach((x) => { x.site_id = s.site_id; });
        // เลือกจุดใหม่แล้ว สถานะ "มีอยู่แล้ว" เดิมไม่ใช้ต่อ (ตรวจซ้ำอีกครั้งตอนบันทึกไม่ได้ จึงแจ้งให้เห็นชัด)
        S.forEach((x, j) => { if (x.code === s.code && x.media === s.media) { x.existing_sample_id = null; $(`tr[data-i="${j}"] td.st`, box).innerHTML = status(x); } });
      }
      count();
    };
    $('#pcdAllDate').addEventListener('change', (e) => {
      S.forEach((s) => { s.date = e.target.value || s.date; });
      $$('[data-date]', box).forEach((inp) => { inp.value = S[+inp.dataset.date].date || ''; });
    });
    $('#pcdAll').onclick = () => { S.forEach((s) => { s.include = true; }); $$('[data-inc]', box).forEach((c) => { c.checked = true; }); count(); };
    $('#pcdNone').onclick = () => { S.forEach((s) => { s.include = false; }); $$('[data-inc]', box).forEach((c) => { c.checked = false; }); count(); };
    $('#pcdCancel').onclick = closeModal;
    $('#pcdSave').onclick = () => {
      const missing = S.filter((s) => s.include && !s.date);
      if (missing.length) { toast(`ยังไม่มีวันที่เก็บ ${missing.length} ตัวอย่าง`, true); return; }
      const project = $('#pcdProject').value.trim() || null;
      guard(async () => {
        const r = await api('POST', '/api/import/pcd/commit', { project, samples: S, standards: pv.standards });
        closeModal();
        await reloadAll();
        fitAll();
        toast(`นำเข้า ${r.samples} ตัวอย่าง (${r.results.toLocaleString('th-TH')} ค่า)${r.skipped ? ` · ข้าม ${r.skipped} ที่มีอยู่แล้ว` : ''}${r.new_sites ? ` · จุดใหม่ ${r.new_sites} จุดยังไม่มีพิกัด: เปิดจุดแล้วกด "ย้ายหมุด"` : ''}${r.standards ? ` · ค่ามาตรฐาน ${r.standards}` : ''}`,
          false, { label: 'ย้อนกลับ', fn: () => restoreBatch(r.batch) });
      });
    };
  }

  return { open };
})();

$('#btnImportPcd').onclick = () => { if (needUser()) $('#filePcd').click(); };
$('#filePcd').onchange = (e) => { const files = [...e.target.files]; e.target.value = ''; PcdImport.open(files); };
