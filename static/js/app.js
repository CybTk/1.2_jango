document.addEventListener('DOMContentLoaded', () => {
  // Sidebar (mobile)
  const sb = document.getElementById('sidebar');
  document.querySelector('.burger')?.addEventListener('click', () => sb.classList.toggle('open'));
  document.querySelector('.main')?.addEventListener('click', () => sb?.classList.remove('open'));

  // Dialog generik: <button data-dialog="id" data-url="..." data-title="...">
  document.querySelectorAll('[data-dialog]').forEach(btn => btn.addEventListener('click', () => {
    const dlg = document.getElementById(btn.dataset.dialog);
    if (btn.dataset.url) dlg.querySelector('form').action = btn.dataset.url;
    if (btn.dataset.title) dlg.querySelector('[data-role="title"]').textContent = btn.dataset.title;
    if (btn.dataset.who) dlg.querySelector('[data-role="who"]').textContent = btn.dataset.who;
    const v = dlg.querySelector('[data-role="value"]'); if (v && btn.dataset.value) v.value = btn.dataset.value;
    dlg.showModal();
  }));
  document.querySelectorAll('dialog').forEach(d => {
    d.addEventListener('click', e => { if (e.target === d) d.close(); });
    d.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => d.close()));
  });

  // Presensi: ambil koordinat GPS sebelum form dikirim
  const fp = document.getElementById('formPresensi');
  if (fp) fp.addEventListener('submit', e => {
    if (fp.dataset.ready === '1') return;
    e.preventDefault();
    const btn = fp.querySelector('button'), info = document.getElementById('geoStatus'), label = btn.textContent;
    if (!navigator.geolocation) { info.textContent = 'Browser tidak mendukung layanan lokasi.'; return; }
    btn.disabled = true; btn.textContent = 'Mengambil lokasi…';
    navigator.geolocation.getCurrentPosition(pos => {
      fp.elements.latitude.value = pos.coords.latitude;
      fp.elements.longitude.value = pos.coords.longitude;
      fp.dataset.ready = '1'; fp.submit();
    }, () => {
      btn.disabled = false; btn.textContent = label;
      info.textContent = 'Izin lokasi diperlukan. Aktifkan GPS lalu coba lagi.';
    }, { enableHighAccuracy: true, timeout: 15000 });
  });

  // Nama file bukti
  document.querySelectorAll('input[type=file][data-hint]').forEach(inp => inp.addEventListener('change', () => {
    const el = document.getElementById(inp.dataset.hint), f = inp.files[0];
    if (el && f) el.textContent = `${f.name} (${(f.size/1024).toFixed(0)} KB)`;
  }));

  // Pesan hilang otomatis
  setTimeout(() => document.querySelectorAll('.alert').forEach(a => a.style.display = 'none'), 6000);
});
