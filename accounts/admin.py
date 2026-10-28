from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Gedung, Kamar, PenghuniKamar, SesiPresensi, Presensi, PengajuanIzin

# Kustomisasi Tampilan User di Django Admin
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Informasi Asrama', {'fields': ('nim_nip', 'role')}),
    )
    list_display = ('username', 'email', 'nim_nip', 'role', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser')
    search_fields = ('username', 'nim_nip', 'first_name', 'last_name', 'email')

@admin.register(Gedung)
class GedungAdmin(admin.ModelAdmin):
    list_display = ('nama_gedung', 'latitude', 'longitude', 'radius_meter')

@admin.register(Kamar)
class KamarAdmin(admin.ModelAdmin):
    list_display = ('nomor_kamar', 'gedung', 'kapasitas')
    list_filter = ('gedung',)

@admin.register(PenghuniKamar)
class PenghuniKamarAdmin(admin.ModelAdmin):
    list_display = ('user', 'kamar', 'tanggal_masuk', 'tanggal_keluar', 'status')
    list_filter = ('status', 'kamar__gedung')
    search_fields = ('user__username', 'user__nim_nip')

@admin.register(SesiPresensi)
class SesiPresensiAdmin(admin.ModelAdmin):
    list_display = ('nama_sesi', 'jam_mulai', 'jam_selesai')

@admin.register(Presensi)
class PresensiAdmin(admin.ModelAdmin):
    list_display = ('user', 'sesi', 'tanggal', 'waktu_presensi', 'status', 'is_in_radius')
    list_filter = ('status', 'tanggal', 'sesi', 'is_in_radius')
    search_fields = ('user__username', 'user__nim_nip')

@admin.register(PengajuanIzin)
class PengajuanIzinAdmin(admin.ModelAdmin):
    list_display = ('presensi', 'status_persetujuan', 'fasil', 'created_at')
    list_filter = ('status_persetujuan', 'created_at')
    search_fields = ('presensi__user__username', 'alasan')