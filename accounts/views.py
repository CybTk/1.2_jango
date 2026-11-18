import csv
from datetime import date, timedelta
from math import radians, cos, sin, asin, sqrt, isfinite

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (PenghuniForm, GedungForm, KamarForm, SesiForm, SesiTambahForm, IzinForm,
                    ProfilForm, StyledPasswordChangeForm)

from .models import Presensi, SesiPresensi, PengajuanIzin, PenghuniKamar, User, Gedung, Kamar


# ---------------------------------------------------------------- helper
def calculate_distance(lat1, lon1, lat2, lon2):
    """Jarak dua titik koordinat dalam meter (Haversine)."""
    R = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    return R * 2 * asin(sqrt(a))


def is_admin(u):
    return u.is_superuser or u.role == 'superadmin'


def is_fasil(u):
    return u.role == 'fasil'


def is_staf(u):
    return is_admin(u) or is_fasil(u)


def is_penghuni(u):
    return u.role == 'penghuni' and not is_admin(u)


def rekap(qs):
    """Hitung jumlah per status -> {'hadir': 3, 'terlambat': 0, ...}"""
    hasil = {s: 0 for s, _ in Presensi.STATUS_CHOICES}
    for r in qs.order_by().values('status').annotate(n=Count('id')):
        hasil[r['status']] = r['n']
    return hasil


def okupansi_gedung():
    data = []
    for g in Gedung.objects.prefetch_related('kamar_list'):
        kamar = list(g.kamar_list.all())
        kapasitas = sum(k.kapasitas for k in kamar)
        terisi = PenghuniKamar.objects.filter(kamar__gedung=g, status='aktif').count()
        persen = round(terisi * 100 / kapasitas) if kapasitas else 0
        data.append({'gedung': g, 'jumlah_kamar': len(kamar), 'kapasitas': kapasitas,
                     'terisi': terisi, 'persen': min(persen, 100)})
    return data


def _tolak_non_staf(request):
    messages.error(request, "Akses ditolak.")
    return redirect('home')


# ---------------------------------------------------------------- dashboard
@login_required
def home(request):
    user = request.user
    today = timezone.localdate()
    now_time = timezone.localtime().time()

    if is_admin(user):
        return render(request, 'dashboard_superadmin.html', {
            'total_penghuni': User.objects.filter(role='penghuni').count(),
            'total_fasil': User.objects.filter(role='fasil').count(),
            'total_gedung': Gedung.objects.count(),
            'total_kamar': Kamar.objects.count(),
            'rekap_hari_ini': rekap(Presensi.objects.filter(tanggal=today)),
            'okupansi': okupansi_gedung(),
            'today': today,
        })

    if is_fasil(user):
        pending = (PengajuanIzin.objects.filter(status_persetujuan='pending')
                   .select_related('presensi__user', 'presensi__sesi').order_by('created_at'))
        terbaru = (Presensi.objects.filter(tanggal=today).select_related('user', 'sesi')
                   .order_by('-waktu_presensi')[:10])
        return render(request, 'dashboard_fasil.html', {
            'pending_izin': pending[:5],
            'total_pending': pending.count(),
            'presensi_hari_ini': terbaru,
            'rekap_hari_ini': rekap(Presensi.objects.filter(tanggal=today)),
            'total_penghuni': PenghuniKamar.objects.filter(status='aktif').count(),
            'today': today,
        })

    # penghuni
    penghuni_kamar = (PenghuniKamar.objects.filter(user=user, status='aktif')
                      .select_related('kamar__gedung').first())
    sesi_aktif = SesiPresensi.objects.filter(jam_mulai__lte=now_time, jam_selesai__gte=now_time).first()
    presensi_by_sesi = {p.sesi_id: p for p in Presensi.objects.filter(user=user, tanggal=today)}
    sesi_hari_ini = [
        {'sesi': s, 'presensi': presensi_by_sesi.get(s.id),
         'aktif': bool(sesi_aktif and sesi_aktif.id == s.id)}
        for s in SesiPresensi.objects.order_by('jam_mulai')
    ]
    bulan_ini = Presensi.objects.filter(user=user, tanggal__year=today.year, tanggal__month=today.month)
    return render(request, 'home.html', {
        'penghuni_kamar': penghuni_kamar,
        'sesi_aktif': sesi_aktif,
        'presensi_sesi_ini': presensi_by_sesi.get(sesi_aktif.id) if sesi_aktif else None,
        'sesi_hari_ini': sesi_hari_ini,
        'rekap': rekap(bulan_ini),
        'riwayat_terbaru': (Presensi.objects.filter(user=user).select_related('sesi')
                            .order_by('-tanggal', '-sesi__jam_mulai')[:5]),
        'izin_pending': PengajuanIzin.objects.filter(presensi__user=user, status_persetujuan='pending').count(),
        'today': today,
    })


# ---------------------------------------------------------------- riwayat (penghuni & staf)
@login_required
def riwayat(request):
    staf = is_staf(request.user)
    qs = Presensi.objects.select_related('user', 'sesi').order_by('-tanggal', '-sesi__jam_mulai')
    if not staf:
        qs = qs.filter(user=request.user)

    f = {k: request.GET.get(k, '').strip() for k in ('q', 'tanggal', 'sesi', 'status', 'gedung')}
    if f['tanggal']:
        qs = qs.filter(tanggal=f['tanggal'])
    if f['sesi']:
        qs = qs.filter(sesi__nama_sesi=f['sesi'])
    if f['status']:
        qs = qs.filter(status=f['status'])
    if staf:
        if f['q']:
            qs = qs.filter(Q(user__username__icontains=f['q']) | Q(user__first_name__icontains=f['q'])
                           | Q(user__last_name__icontains=f['q']) | Q(user__nim_nip__icontains=f['q']))
        if f['gedung']:
            qs = qs.filter(user__riwayat_kamar__status='aktif',
                           user__riwayat_kamar__kamar__gedung_id=f['gedung'])

    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'riwayat.html', {
        'page_obj': Paginator(qs, 20).get_page(request.GET.get('page')),
        'f': f, 'staf': staf, 'rekap': rekap(qs), 'querystring': query.urlencode(),
        'gedung_list': Gedung.objects.all(), 'status_choices': Presensi.STATUS_CHOICES,
    })


# ---------------------------------------------------------------- izin
@login_required
def izin_saya(request):
    if not is_penghuni(request.user):
        return _tolak_non_staf(request)
    form = IzinForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        sesi_qs = SesiPresensi.objects.all()
        if d['sesi'] != 'semua':
            sesi_qs = sesi_qs.filter(nama_sesi=d['sesi'])
        dibuat = dilewati = 0
        berkas = d['file_bukti']
        with transaction.atomic():
            tgl = d['tanggal_mulai']
            while tgl <= d['tanggal_selesai']:
                for sesi in sesi_qs:
                    presensi, baru = Presensi.objects.get_or_create(
                        user=request.user, sesi=sesi, tanggal=tgl, defaults={'status': d['jenis']})
                    if not baru:
                        presensi = Presensi.objects.select_for_update().get(pk=presensi.pk)
                        sudah_diajukan = PengajuanIzin.objects.filter(presensi=presensi).exists()
                        if presensi.status != 'alpa' or sudah_diajukan:
                            dilewati += 1
                            continue
                        presensi.status = d['jenis']
                        presensi.save(update_fields=['status'])
                    berkas.seek(0)
                    PengajuanIzin.objects.create(presensi=presensi, alasan=d['alasan'],
                                                 file_bukti=berkas, status_persetujuan='pending')
                    dibuat += 1
                tgl += timedelta(days=1)
        if dibuat:
            messages.success(request, f"{dibuat} pengajuan terkirim. Menunggu persetujuan Fasil.")
        if dilewati:
            messages.warning(request, f"{dilewati} sesi dilewati karena sudah ada presensi/pengajuan.")
        return redirect('izin_saya')
    daftar = (PengajuanIzin.objects.filter(presensi__user=request.user)
              .select_related('presensi__sesi').order_by('-presensi__tanggal', '-created_at'))
    return render(request, 'izin_saya.html', {'daftar': daftar, 'form': form})


@login_required
def izin_list(request):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    status = request.GET.get('status', 'pending')
    qs = (PengajuanIzin.objects.select_related('presensi__user', 'presensi__sesi', 'fasil')
          .order_by('-created_at'))
    if status in ('pending', 'disetujui', 'ditolak'):
        qs = qs.filter(status_persetujuan=status)
    else:
        status = 'semua'
    counts = {s: PengajuanIzin.objects.filter(status_persetujuan=s).count()
              for s in ('pending', 'disetujui', 'ditolak')}
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'izin_list.html', {
        'page_obj': Paginator(qs, 15).get_page(request.GET.get('page')),
        'status': status, 'counts': counts, 'querystring': query.urlencode(),
    })


@login_required
@require_POST
def verifikasi_izin(request, izin_id, aksi):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    if aksi not in ('setuju', 'tolak'):
        messages.error(request, "Aksi tidak dikenal.")
        return redirect('izin_list')

    with transaction.atomic():
        izin = get_object_or_404(
            PengajuanIzin.objects.select_for_update().select_related('presensi__user'),
            id=izin_id,
        )
        if izin.status_persetujuan != 'pending':
            messages.warning(request, "Pengajuan ini sudah diproses dan tidak dapat diubah lagi.")
            return redirect('izin_list')

        presensi = Presensi.objects.select_for_update().get(pk=izin.presensi_id)
        if aksi == 'setuju':
            izin.status_persetujuan = 'disetujui'
            if presensi.status not in ('izin', 'sakit'):
                presensi.status = 'izin'
            messages.success(request, f"Izin {presensi.user.username} disetujui.")
        else:
            izin.status_persetujuan = 'ditolak'
            presensi.status = 'alpa'
            messages.warning(request, f"Izin {presensi.user.username} ditolak.")

        izin.catatan_fasil = request.POST.get('catatan_fasil', '').strip() or None
        izin.fasil = request.user
        presensi.save(update_fields=['status'])
        izin.save(update_fields=['status_persetujuan', 'catatan_fasil', 'fasil'])
    return redirect('izin_list')


# ---------------------------------------------------------------- kelola data
@login_required
def penghuni_list(request):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    q = request.GET.get('q', '').strip()
    gedung_sel = request.GET.get('gedung', '').strip()
    qs = (PenghuniKamar.objects.filter(status='aktif').select_related('user', 'kamar__gedung')
          .order_by('kamar__gedung__nama_gedung', 'kamar__nomor_kamar', 'user__first_name'))
    if q:
        qs = qs.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q)
                       | Q(user__last_name__icontains=q) | Q(user__nim_nip__icontains=q))
    if gedung_sel:
        qs = qs.filter(kamar__gedung_id=gedung_sel)
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'penghuni_list.html', {
        'page_obj': Paginator(qs, 20).get_page(request.GET.get('page')),
        'q': q, 'gedung_sel': gedung_sel, 'gedung_list': Gedung.objects.all(),
        'total': qs.count(), 'querystring': query.urlencode(),
    })


@login_required
def gedung_list(request):
    if not is_admin(request.user):
        return _tolak_non_staf(request)
    kamar = (Kamar.objects.select_related('gedung')
             .annotate(terisi=Count('penghuni_list', filter=Q(penghuni_list__status='aktif')))
             .order_by('gedung__nama_gedung', 'nomor_kamar'))
    return render(request, 'gedung_list.html', {'okupansi': okupansi_gedung(), 'kamar_list': kamar})


# ---------------------------------------------------------------- aksi penghuni (logika lama, belum diubah)
@login_required
@require_POST
def do_presensi(request):
    if not is_penghuni(request.user):
        return _tolak_non_staf(request)
    user = request.user
    try:
        lat = float(request.POST.get('latitude', ''))
        lng = float(request.POST.get('longitude', ''))
    except (TypeError, ValueError):
        messages.error(request, "Lokasi tidak valid. Aktifkan GPS lalu coba lagi.")
        return redirect('home')

    if not (isfinite(lat) and isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        messages.error(request, "Lokasi tidak valid. Aktifkan GPS lalu coba lagi.")
        return redirect('home')

    now = timezone.localtime()
    today = now.date()
    now_time = now.time()

    sesi = SesiPresensi.objects.filter(jam_mulai__lte=now_time, jam_selesai__gte=now_time).first()
    if not sesi:
        messages.error(request, "Di luar jam presensi Subuh (04.00-06.00) atau Malam (18.00-20.30).")
        return redirect('home')

    # Cek alokasi kamar & gedung
    penghuni = PenghuniKamar.objects.filter(user=user, status='aktif').select_related('kamar__gedung').first()
    if not penghuni:
        messages.error(request, "Kamu belum terdaftar di kamar/gedung asrama manapun.")
        return redirect('home')

    gedung = penghuni.kamar.gedung
    jarak = calculate_distance(lat, lng, float(gedung.latitude), float(gedung.longitude))
    is_in_radius = jarak <= gedung.radius_meter

    if not is_in_radius:
        messages.error(request, f"Kamu berada di luar radius asrama ({int(jarak)}m dari gedung).")
        return redirect('home')

    _, created = Presensi.objects.get_or_create(
        user=user, sesi=sesi, tanggal=today,
        defaults={
            'waktu_presensi': now,
            'status': 'hadir',
            'latitude': lat,
            'longitude': lng,
            'is_in_radius': True
        }
    )

    if not created:
        messages.warning(request, "Kamu sudah melakukan presensi pada sesi ini.")
    else:
        messages.success(request, f"Presensi {sesi.get_nama_sesi_display()} berhasil tercatat!")

    return redirect('home')




# ================================================================ TAHAP 2: fitur tambahan
def _aman(request, nxt, default):
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return default


def _crud(request, form_class, instance, judul, sub, kembali, pesan, dua_kolom=True):
    form = form_class(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, pesan)
        return redirect(kembali)
    return render(request, 'form_page.html', {'form': form, 'judul': judul, 'sub': sub,
                                              'batal_url': reverse(kembali), 'dua_kolom': dua_kolom})


# ---- penghuni
@login_required
def penghuni_tambah(request):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    form = PenghuniForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        u = form.save()
        messages.success(request, f"Penghuni {u.get_full_name() or u.username} berhasil ditambahkan.")
        return redirect('penghuni_detail', user_id=u.id)
    return render(request, 'form_page.html', {'form': form, 'judul': 'Tambah Penghuni',
                  'sub': 'Buat akun penghuni dan tempatkan ke kamar', 'batal_url': reverse('penghuni_list'), 'dua_kolom': True})


@login_required
def penghuni_ubah(request, user_id):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    u = get_object_or_404(User, id=user_id, role='penghuni')
    form = PenghuniForm(request.POST or None, instance=u)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Data penghuni diperbarui.")
        return redirect('penghuni_detail', user_id=u.id)
    return render(request, 'form_page.html', {'form': form, 'judul': f"Ubah Data: {u.get_full_name() or u.username}",
                  'sub': 'Perbarui data akun atau pindahkan kamar', 'batal_url': reverse('penghuni_detail', args=[u.id]), 'dua_kolom': True})


@login_required
def penghuni_detail(request, user_id):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    u = get_object_or_404(User, id=user_id, role='penghuni')
    presensi = Presensi.objects.filter(user=u)
    today = timezone.localdate()
    return render(request, 'penghuni_detail.html', {
        'penghuni': u,
        'aktif': u.riwayat_kamar.filter(status='aktif').select_related('kamar__gedung').first(),
        'riwayat_kamar': u.riwayat_kamar.select_related('kamar__gedung').order_by('-tanggal_masuk'),
        'rekap': rekap(presensi),
        'rekap_bulan': rekap(presensi.filter(tanggal__year=today.year, tanggal__month=today.month)),
        'terbaru': presensi.select_related('sesi').order_by('-tanggal', '-sesi__jam_mulai')[:15],
    })


@login_required
@require_POST
def penghuni_keluar(request, user_id):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    u = get_object_or_404(User, id=user_id, role='penghuni')
    n = u.riwayat_kamar.filter(status='aktif').update(status='non_aktif', tanggal_keluar=timezone.localdate())
    messages.success(request, f"{u.get_full_name() or u.username} dikeluarkan dari kamar." if n else "Penghuni tidak punya penempatan aktif.")
    return redirect('penghuni_list')


# ---- gedung, kamar, sesi (admin)
def _admin_only(request):
    return None if is_admin(request.user) else _tolak_non_staf(request)


@login_required
def gedung_tambah(request):
    return _admin_only(request) or _crud(request, GedungForm, None, 'Tambah Gedung', 'Titik koordinat dipakai untuk validasi lokasi presensi', 'gedung_list', 'Gedung ditambahkan.')


@login_required
def gedung_ubah(request, pk):
    return _admin_only(request) or _crud(request, GedungForm, get_object_or_404(Gedung, pk=pk), 'Ubah Gedung', 'Perbarui data gedung', 'gedung_list', 'Gedung diperbarui.')


@login_required
def kamar_tambah(request):
    return _admin_only(request) or _crud(request, KamarForm, None, 'Tambah Kamar', 'Tentukan gedung dan kapasitas kamar', 'gedung_list', 'Kamar ditambahkan.')


@login_required
def kamar_ubah(request, pk):
    return _admin_only(request) or _crud(request, KamarForm, get_object_or_404(Kamar, pk=pk), 'Ubah Kamar', 'Perbarui data kamar', 'gedung_list', 'Kamar diperbarui.')


@login_required
def sesi_list(request):
    if not is_admin(request.user):
        return _tolak_non_staf(request)
    sesi_list = SesiPresensi.objects.order_by('jam_mulai')
    return render(request, 'sesi_list.html', {
        'sesi_list': sesi_list,
        'sesi_bisa_ditambah': sesi_list.count() < len(SesiPresensi.NAMA_SESI_CHOICES),
    })


@login_required
def sesi_tambah(request):
    if not is_admin(request.user):
        return _tolak_non_staf(request)
    return _crud(
        request,
        SesiTambahForm,
        None,
        'Tambah Sesi Presensi',
        'Tambahkan sesi Subuh atau Malam yang belum tersedia',
        'sesi_list',
        'Sesi presensi ditambahkan.',
    )


@login_required
def sesi_ubah(request, pk):
    return _admin_only(request) or _crud(request, SesiForm, get_object_or_404(SesiPresensi, pk=pk), 'Ubah Jam Sesi', 'Jam ini menentukan kapan penghuni dapat melakukan presensi', 'sesi_list', 'Jam sesi diperbarui.')


# ---- izin: detail & batal
@login_required
def izin_detail(request, izin_id):
    izin = get_object_or_404(PengajuanIzin.objects.select_related('presensi__user', 'presensi__sesi', 'fasil'), id=izin_id)
    staf = is_staf(request.user)
    if not staf and (not is_penghuni(request.user) or izin.presensi.user_id != request.user.id):
        return _tolak_non_staf(request)
    nama = izin.file_bukti.name.lower()
    return render(request, 'izin_detail.html', {
        'izin': izin, 'staf': staf,
        'is_pdf': nama.endswith('.pdf'), 'is_img': nama.endswith(('.jpg', '.jpeg', '.png')),
    })


@login_required
@require_POST
def izin_batal(request, izin_id):
    if not is_penghuni(request.user):
        return _tolak_non_staf(request)
    with transaction.atomic():
        izin = get_object_or_404(
            PengajuanIzin.objects.select_for_update(),
            id=izin_id,
            presensi__user=request.user,
            status_persetujuan='pending',
        )
        presensi = Presensi.objects.select_for_update().get(pk=izin.presensi_id)
        izin.delete()
        if presensi.waktu_presensi is None:
            presensi.delete()
    messages.success(request, "Pengajuan izin dibatalkan.")
    return redirect('izin_saya')


# ---- koreksi presensi manual
@login_required
@require_POST
def presensi_koreksi(request, presensi_id):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    p = get_object_or_404(Presensi, id=presensi_id)
    status = request.POST.get('status')
    if status in dict(Presensi.STATUS_CHOICES):
        p.status = status
        p.save()
        messages.success(request, f"Status presensi {p.user.get_full_name() or p.user.username} diubah menjadi {p.get_status_display()}.")
    else:
        messages.error(request, "Status tidak valid.")
    return redirect(_aman(request, request.POST.get('next'), 'riwayat'))


# ---- laporan
def _data_laporan(request):
    today = timezone.localdate()
    bulan = request.GET.get('bulan') or today.strftime('%Y-%m')
    try:
        y, m = map(int, bulan.split('-'))
        date(y, m, 1)
    except (ValueError, TypeError):
        y, m = today.year, today.month
        bulan = today.strftime('%Y-%m')
    gedung = request.GET.get('gedung', '').strip()
    qs = Presensi.objects.filter(tanggal__year=y, tanggal__month=m)
    if gedung:
        qs = qs.filter(user__riwayat_kamar__status='aktif', user__riwayat_kamar__kamar__gedung_id=gedung)
    baris = {}
    for r in (qs.order_by().values('user_id', 'user__first_name', 'user__last_name', 'user__username', 'user__nim_nip', 'status')
              .annotate(n=Count('id'))):
        nama = f"{r['user__first_name']} {r['user__last_name']}".strip() or r['user__username']
        b = baris.setdefault(r['user_id'], {'id': r['user_id'], 'nama': nama, 'nim': r['user__nim_nip'] or '',
                                            'hadir': 0, 'terlambat': 0, 'izin': 0, 'sakit': 0, 'alpa': 0, 'total': 0})
        b[r['status']] += r['n']
        b['total'] += r['n']
    daftar = sorted(baris.values(), key=lambda b: b['nama'].lower())
    for b in daftar:
        b['persen'] = round((b['hadir'] + b['terlambat']) * 100 / b['total']) if b['total'] else 0
    tren = []
    for t in (qs.order_by().values('tanggal').annotate(total=Count('id'), ok=Count('id', filter=Q(status__in=['hadir', 'terlambat'])))
              .order_by('tanggal')):
        tren.append({'tanggal': t['tanggal'], 'total': t['total'], 'ok': t['ok'],
                     'persen': round(t['ok'] * 100 / t['total']) if t['total'] else 0})
    return bulan, y, m, gedung, daftar, tren, rekap(qs)


@login_required
def laporan(request):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    bulan, y, m, gedung, daftar, tren, ringkasan = _data_laporan(request)
    return render(request, 'laporan.html', {
        'bulan': bulan, 'periode': date(y, m, 1), 'gedung_sel': gedung, 'gedung_list': Gedung.objects.all(),
        'daftar': daftar, 'tren': tren, 'rekap': ringkasan,
        'querystring': request.GET.urlencode(),
    })


@login_required
def laporan_csv(request):
    if not is_staf(request.user):
        return _tolak_non_staf(request)
    bulan, _, _, _, daftar, _, _ = _data_laporan(request)
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="laporan-presensi-{bulan}.csv"'
    resp.write('\ufeff')  # agar Excel membaca UTF-8
    w = csv.writer(resp)
    w.writerow(['NIM', 'Nama', 'Hadir', 'Terlambat', 'Izin', 'Sakit', 'Alpa', 'Total', '% Kehadiran'])
    for b in daftar:
        w.writerow([b['nim'], b['nama'], b['hadir'], b['terlambat'], b['izin'], b['sakit'], b['alpa'], b['total'], b['persen']])
    return resp


# ---- profil & kata sandi
@login_required
def profil(request):
    form = ProfilForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "Profil diperbarui.")
        return redirect('profil')
    kamar = PenghuniKamar.objects.filter(user=request.user, status='aktif').select_related('kamar__gedung').first()
    return render(request, 'profil.html', {'form': form, 'penghuni_kamar': kamar})


class GantiPassword(SuccessMessageMixin, PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = 'form_page.html'
    success_url = reverse_lazy('profil')
    success_message = "Kata sandi berhasil diubah."
    extra_context = {'judul': 'Ganti Kata Sandi', 'sub': 'Gunakan kata sandi yang kuat dan unik',
                     'batal_url': reverse_lazy('profil')}
