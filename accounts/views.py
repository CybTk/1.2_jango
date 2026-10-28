from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Presensi, SesiPresensi, PengajuanIzin, PenghuniKamar, User, Gedung, Kamar
from math import radians, cos, sin, asin, sqrt

# Fungsi bantu hitung jarak dua titik koordinat (Haversine Formula)
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Radius bumi dalam meter
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2)**2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2)**2
    c = 2 * asin(sqrt(a))
    return R * c

@login_required
def home(request):
    user = request.user
    today = timezone.localdate()
    now_time = timezone.localtime().time()

    # 1. Dashboard Superadmin
    if user.role == 'superadmin' or user.is_superuser:
        total_penghuni = User.objects.filter(role='penghuni').count()
        total_fasil = User.objects.filter(role='fasil').count()
        total_gedung = Gedung.objects.count()
        total_kamar = Kamar.objects.count()
        
        context = {
            'total_penghuni': total_penghuni,
            'total_fasil': total_fasil,
            'total_gedung': total_gedung,
            'total_kamar': total_kamar,
        }
        return render(request, 'dashboard_superadmin.html', context)

    # 2. Dashboard Fasilitator
    elif user.role == 'fasil':
        pending_izin = PengajuanIzin.objects.filter(status_persetujuan='pending')
        presensi_hari_ini = Presensi.objects.filter(tanggal=today).select_related('user', 'sesi')
        
        context = {
            'pending_izin': pending_izin,
            'presensi_hari_ini': presensi_hari_ini,
            'today': today,
        }
        return render(request, 'dashboard_fasil.html', context)

    # 3. Dashboard Penghuni (Mahasiswa)
    else:
        penghuni_kamar = PenghuniKamar.objects.filter(user=user, status='aktif').first()
        riwayat_presensi = Presensi.objects.filter(user=user).order_by('-tanggal', '-sesi__jam_mulai')
        
        # Cek sesi aktif saat ini
        sesi_aktif = SesiPresensi.objects.filter(jam_mulai__lte=now_time, jam_selesai__gte=now_time).first()
        presensi_sesi_ini = None
        if sesi_aktif:
            presensi_sesi_ini = Presensi.objects.filter(user=user, sesi=sesi_aktif, tanggal=today).first()

        context = {
            'penghuni_kamar': penghuni_kamar,
            'riwayat_presensi': riwayat_presensi,
            'sesi_aktif': sesi_aktif,
            'presensi_sesi_ini': presensi_sesi_ini,
            'today': today,
        }
        return render(request, 'home.html', context)


@login_required
def do_presensi(request):
    if request.method == 'POST':
        user = request.user
        lat = float(request.POST.get('latitude', 0))
        lng = float(request.POST.get('longitude', 0))
        
        now = timezone.localtime()
        today = now.date()
        now_time = now.time()

        sesi = SesiPresensi.objects.filter(jam_mulai__lte=now_time, jam_selesai__gte=now_time).first()
        if not sesi:
            messages.error(request, "Di luar jam presensi Subuh (04.00-06.00) atau Malam (18.00-20.30).")
            return redirect('home')

        # Cek alokasi kamar & gedung
        penghuni = PenghuniKamar.objects.filter(user=user, status='aktif').first()
        if not penghuni:
            messages.error(request, "Kamu belum terdaftar di kamar/gedung asrama manapun.")
            return redirect('home')

        gedung = penghuni.kamar.gedung
        jarak = calculate_distance(lat, lng, float(gedung.latitude), float(gedung.longitude))
        is_in_radius = jarak <= gedung.radius_meter

        if not is_in_radius:
            messages.error(request, f"Kamu berada di luar radius asrama ({int(jarak)}m dari gedung).")
            return redirect('home')

        presensi, created = Presensi.objects.get_or_create(
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


@login_required
def ajukan_izin(request):
    if request.method == 'POST':
        user = request.user
        sesi_id = request.POST.get('sesi_id')
        alasan = request.POST.get('alasan')
        file_bukti = request.FILES.get('file_bukti')
        today = timezone.localdate()

        sesi = get_object_or_404(SesiPresensi, id=sesi_id)
        
        # Buat record presensi status 'izin'
        presensi, _ = Presensi.objects.get_or_create(
            user=user, sesi=sesi, tanggal=today,
            defaults={'status': 'izin'}
        )

        PengajuanIzin.objects.create(
            presensi=presensi,
            alasan=alasan,
            file_bukti=file_bukti,
            status_persetujuan='pending'
        )
        messages.success(request, "Pengajuan izin berhasil dikirim! Menunggu persetujuan Fasil.")

    return redirect('home')


@login_required
def verifikasi_izin(request, izin_id, aksi):
    if request.user.role != 'fasil' and not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "Akses ditolak.")
        return redirect('home')

    izin = get_object_or_404(PengajuanIzin, id=izin_id)
    if aksi == 'setuju':
        izin.status_persetujuan = 'disetujui'
        izin.presensi.status = 'izin'
        messages.success(request, f"Izin {izin.presensi.user.username} disetujui.")
    elif aksi == 'tolak':
        izin.status_persetujuan = 'ditolak'
        izin.presensi.status = 'alpa'
        messages.warning(request, f"Izin {izin.presensi.user.username} ditolak.")
    
    izin.fasil = request.user
    izin.presensi.save()
    izin.save()
    return redirect('home')