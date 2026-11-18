from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .models import PengajuanIzin, Presensi
from .views import is_staf


def notifikasi(request):
    """Daftar notifikasi untuk ikon lonceng (dihitung dari data yang ada, tanpa tabel baru)."""
    u = request.user
    if not u.is_authenticated:
        return {}
    items = []
    if is_staf(u):
        n = PengajuanIzin.objects.filter(status_persetujuan='pending').count()
        if n:
            items.append({'teks': f'{n} pengajuan izin menunggu persetujuan', 'url': reverse('izin_list'), 'tone': 'pending'})
    else:
        batas = timezone.now() - timedelta(days=14)
        diproses = (PengajuanIzin.objects.filter(presensi__user=u, created_at__gte=batas)
                    .exclude(status_persetujuan='pending').select_related('presensi__sesi').order_by('-created_at')[:5])
        for i in diproses:
            items.append({'teks': f'Izin {i.presensi.tanggal:%d %b} ({i.presensi.sesi.get_nama_sesi_display()}) {i.get_status_persetujuan_display().lower()}',
                          'url': reverse('izin_detail', args=[i.id]), 'tone': i.status_persetujuan})
        alpa = (Presensi.objects.filter(user=u, status='alpa', tanggal__gte=timezone.localdate() - timedelta(days=7))
                .select_related('sesi').order_by('-tanggal')[:3])
        for p in alpa:
            items.append({'teks': f'Anda tercatat alpa: {p.tanggal:%d %b}, {p.sesi.get_nama_sesi_display()}',
                          'url': reverse('riwayat'), 'tone': 'ditolak'})
    return {'notif_items': items}
