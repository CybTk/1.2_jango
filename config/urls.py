"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from accounts import views as accounts_views
from accounts import webauthn as webauthn_views
from accounts.forms import StyledPasswordResetForm, StyledSetPasswordForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    path('', accounts_views.home, name='home'),
    path('presensi/', accounts_views.do_presensi, name='do_presensi'),
    path('ajukan-izin/', accounts_views.izin_saya, name='ajukan_izin'),
    path('verifikasi-izin/<int:izin_id>/<str:aksi>/', accounts_views.verifikasi_izin, name='verifikasi_izin'),

    # Halaman baru (frontend)
    path('riwayat/', accounts_views.riwayat, name='riwayat'),
    path('izin/', accounts_views.izin_saya, name='izin_saya'),
    path('kelola/izin/', accounts_views.izin_list, name='izin_list'),
    path('kelola/penghuni/', accounts_views.penghuni_list, name='penghuni_list'),
    path('kelola/gedung/', accounts_views.gedung_list, name='gedung_list'),

    # Tahap 2
    path('profil/', accounts_views.profil, name='profil'),
    path('profil/password/', accounts_views.GantiPassword.as_view(), name='ganti_password'),
    path('profil/passkey/opsi-daftar/', webauthn_views.registration_options, name='passkey_registration_options'),
    path('profil/passkey/daftar/', webauthn_views.register_credential, name='passkey_register'),
    path('profil/passkey/<int:credential_id>/hapus/', webauthn_views.delete_credential, name='passkey_delete'),
    path('presensi/passkey/opsi/', webauthn_views.authentication_options, name='passkey_authentication_options'),
    path('presensi/passkey/verifikasi/', webauthn_views.authenticate_credential, name='passkey_authenticate'),
    path('izin/<int:izin_id>/', accounts_views.izin_detail, name='izin_detail'),
    path('izin/<int:izin_id>/batal/', accounts_views.izin_batal, name='izin_batal'),
    path('kelola/penghuni/tambah/', accounts_views.penghuni_tambah, name='penghuni_tambah'),
    path('kelola/penghuni/<int:user_id>/', accounts_views.penghuni_detail, name='penghuni_detail'),
    path('kelola/penghuni/<int:user_id>/ubah/', accounts_views.penghuni_ubah, name='penghuni_ubah'),
    path('kelola/penghuni/<int:user_id>/keluar/', accounts_views.penghuni_keluar, name='penghuni_keluar'),
    path('kelola/gedung/tambah/', accounts_views.gedung_tambah, name='gedung_tambah'),
    path('kelola/gedung/<int:pk>/ubah/', accounts_views.gedung_ubah, name='gedung_ubah'),
    path('kelola/kamar/tambah/', accounts_views.kamar_tambah, name='kamar_tambah'),
    path('kelola/kamar/<int:pk>/ubah/', accounts_views.kamar_ubah, name='kamar_ubah'),
    path('kelola/sesi/', accounts_views.sesi_list, name='sesi_list'),
    path('kelola/sesi/tambah/', accounts_views.sesi_tambah, name='sesi_tambah'),
    path('kelola/sesi/<int:pk>/ubah/', accounts_views.sesi_ubah, name='sesi_ubah'),
    path('kelola/presensi/<int:presensi_id>/koreksi/', accounts_views.presensi_koreksi, name='presensi_koreksi'),
    path('kelola/laporan/', accounts_views.laporan, name='laporan'),
    path('kelola/laporan/csv/', accounts_views.laporan_csv, name='laporan_csv'),

    # Lupa kata sandi
    path('lupa-password/', auth_views.PasswordResetView.as_view(
        template_name='auth_page.html', form_class=StyledPasswordResetForm,
        email_template_name='registration/password_reset_email.txt',
        subject_template_name='registration/password_reset_subject.txt',
        extra_context={'judul': 'Lupa kata sandi', 'keterangan': 'Masukkan email akun Anda. Kami kirim tautan untuk mengatur ulang.', 'tombol': 'Kirim tautan'}),
        name='password_reset'),
    path('lupa-password/terkirim/', auth_views.PasswordResetDoneView.as_view(
        template_name='auth_page.html',
        extra_context={'judul': 'Cek email Anda', 'keterangan': 'Jika email terdaftar, tautan pengaturan ulang sudah dikirim.'}),
        name='password_reset_done'),
    path('lupa-password/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='auth_page.html', form_class=StyledSetPasswordForm,
        extra_context={'judul': 'Atur kata sandi baru', 'keterangan': 'Buat kata sandi baru untuk akun Anda.', 'tombol': 'Simpan kata sandi'}),
        name='password_reset_confirm'),
    path('lupa-password/selesai/', auth_views.PasswordResetCompleteView.as_view(
        template_name='auth_page.html',
        extra_context={'judul': 'Kata sandi diperbarui', 'keterangan': 'Silakan masuk dengan kata sandi baru Anda.'}),
        name='password_reset_complete'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)