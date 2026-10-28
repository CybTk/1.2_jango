from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. Custom User Model
class User(AbstractUser):
    ROLE_CHOICES = (
        ('superadmin', 'Superadmin'),
        ('fasil', 'Fasilitator'),
        ('penghuni', 'Penghuni'),
    )
    nim_nip = models.CharField(max_length=30, unique=True, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='penghuni')

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


# 2. Model Gedung
class Gedung(models.Model):
    nama_gedung = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_meter = models.IntegerField(default=50, help_text="Radius toleransi dalam meter")

    def __str__(self):
        return self.nama_gedung


# 3. Model Kamar
class Kamar(models.Model):
    gedung = models.ForeignKey(Gedung, on_delete=models.CASCADE, related_name='kamar_list')
    nomor_kamar = models.CharField(max_length=10)
    kapasitas = models.PositiveIntegerField(default=2)

    def __str__(self):
        return f"{self.gedung.nama_gedung} - Kamar {self.nomor_kamar}"


# 4. Model Penghuni Kamar
class PenghuniKamar(models.Model):
    STATUS_CHOICES = (
        ('aktif', 'Aktif'),
        ('non_aktif', 'Non Aktif'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='riwayat_kamar')
    kamar = models.ForeignKey(Kamar, on_delete=models.CASCADE, related_name='penghuni_list')
    tanggal_masuk = models.DateField()
    tanggal_keluar = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='aktif')

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.kamar}"


# 5. Model Sesi Presensi
class SesiPresensi(models.Model):
    NAMA_SESI_CHOICES = (
        ('subuh', 'Subuh'),
        ('malam', 'Malam'),
    )
    nama_sesi = models.CharField(max_length=10, choices=NAMA_SESI_CHOICES)
    jam_mulai = models.TimeField()
    jam_selesai = models.TimeField()

    def __str__(self):
        return f"Sesi {self.get_nama_sesi_display()} ({self.jam_mulai} - {self.jam_selesai})"


# 6. Model Presensi
class Presensi(models.Model):
    STATUS_CHOICES = (
        ('hadir', 'Hadir'),
        ('terlambat', 'Terlambat'),
        ('izin', 'Izin'),
        ('sakit', 'Sakit'),
        ('alpa', 'Alpa'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='presensi_list')
    sesi = models.ForeignKey(SesiPresensi, on_delete=models.CASCADE)
    tanggal = models.DateField()
    waktu_presensi = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='alpa')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_in_radius = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'sesi', 'tanggal')

    def __str__(self):
        return f"{self.user.username} - {self.tanggal} ({self.sesi.nama_sesi}): {self.status}"


# 7. Model Pengajuan Izin
class PengajuanIzin(models.Model):
    STATUS_PERSETUJUAN = (
        ('pending', 'Pending'),
        ('disetujui', 'Disetujui'),
        ('ditolak', 'Ditolak'),
    )
    presensi = models.OneToOneField(Presensi, on_delete=models.CASCADE, related_name='pengajuan_izin')
    fasil = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='izin_diproses')
    alasan = models.TextField()
    file_bukti = models.FileField(upload_to='bukti_izin/')
    status_persetujuan = models.CharField(max_length=20, choices=STATUS_PERSETUJUAN, default='pending')
    catatan_fasil = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Izin {self.presensi.user.username} - {self.status_persetujuan}"