from datetime import date, datetime, time
import tempfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Gedung,
    Kamar,
    PengajuanIzin,
    PenghuniKamar,
    Presensi,
    SesiPresensi,
    User,
)


class SesiManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="superadmin", password="rahasia", role="superadmin"
        )
        self.client.force_login(self.admin)
        self.sesi_subuh = SesiPresensi.objects.create(
            nama_sesi="subuh",
            jam_mulai=time(4, 0),
            jam_selesai=time(6, 0),
        )

    def test_admin_can_add_missing_session_from_sessions_page(self):
        response = self.client.get(reverse("sesi_list"))
        self.assertContains(response, "Tambah sesi")

        response = self.client.post(
            reverse("sesi_tambah"),
            {"nama_sesi": "malam", "jam_mulai": "18:00", "jam_selesai": "20:30"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subuh")
        self.assertContains(response, "Malam")
        self.assertEqual(SesiPresensi.objects.count(), 2)

    def test_admin_cannot_add_duplicate_session_or_invalid_time_range(self):
        response = self.client.post(
            reverse("sesi_tambah"),
            {"nama_sesi": "subuh", "jam_mulai": "04:00", "jam_selesai": "06:00"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sesi ini sudah tersedia")
        self.assertEqual(SesiPresensi.objects.count(), 1)

        response = self.client.post(
            reverse("sesi_tambah"),
            {"nama_sesi": "malam", "jam_mulai": "20:30", "jam_selesai": "18:00"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jam selesai harus setelah jam mulai")
        self.assertEqual(SesiPresensi.objects.count(), 1)

    def test_fasilitator_cannot_add_session(self):
        fasil = User.objects.create_user(
            username="fasil", password="rahasia", role="fasil"
        )
        self.client.force_login(fasil)
        self.assertRedirects(self.client.get(reverse("sesi_tambah")), reverse("home"))
        self.assertRedirects(self.client.post(reverse("sesi_tambah")), reverse("home"))
        self.assertEqual(SesiPresensi.objects.count(), 1)


class PresensiViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="penghuni", password="rahasia")
        self.client.force_login(self.user)

    def test_invalid_location_is_rejected(self):
        for latitude, longitude in (
            ("", "100"),
            ("abc", "100"),
            ("NaN", "100"),
            ("91", "100"),
            ("0", "181"),
        ):
            with self.subTest(latitude=latitude, longitude=longitude):
                response = self.client.post(
                    reverse("do_presensi"),
                    {"latitude": latitude, "longitude": longitude},
                )
                self.assertRedirects(response, reverse("home"))

        self.assertEqual(Presensi.objects.count(), 0)

    def test_valid_location_records_attendance_once(self):
        gedung = Gedung.objects.create(
            nama_gedung="Asrama",
            latitude=-0.914,
            longitude=100.459,
            radius_meter=100,
        )
        kamar = Kamar.objects.create(gedung=gedung, nomor_kamar="1", kapasitas=2)
        PenghuniKamar.objects.create(
            user=self.user,
            kamar=kamar,
            tanggal_masuk=date(2026, 1, 1),
        )
        sesi = SesiPresensi.objects.create(
            nama_sesi="malam",
            jam_mulai=time(18, 0),
            jam_selesai=time(20, 30),
        )
        now = datetime(2026, 1, 2, 19, 0, tzinfo=ZoneInfo("Asia/Jakarta"))

        with patch("accounts.views.timezone.localtime", return_value=now):
            for _ in range(2):
                response = self.client.post(
                    reverse("do_presensi"),
                    {"latitude": "-0.914", "longitude": "100.459"},
                )
                self.assertRedirects(response, reverse("home"))

        presensi = Presensi.objects.get(user=self.user, sesi=sesi, tanggal=now.date())
        self.assertEqual(Presensi.objects.count(), 1)
        self.assertEqual(presensi.status, "hadir")
        self.assertTrue(presensi.is_in_radius)


class GenerateAlpaCommandTests(TestCase):
    def test_generates_missing_absences_idempotently_after_sessions_end(self):
        today = date(2026, 1, 2)
        penghuni = User.objects.create_user(username="penghuni", password="rahasia")
        penghuni_lain = User.objects.create_user(username="penghuni2", password="rahasia")
        gedung = Gedung.objects.create(
            nama_gedung="Asrama",
            latitude=-0.914,
            longitude=100.459,
            radius_meter=100,
        )
        kamar = Kamar.objects.create(gedung=gedung, nomor_kamar="1", kapasitas=2)
        PenghuniKamar.objects.create(user=penghuni, kamar=kamar, tanggal_masuk=date(2026, 1, 1))
        PenghuniKamar.objects.create(user=penghuni_lain, kamar=kamar, tanggal_masuk=date(2026, 1, 1))
        subuh = SesiPresensi.objects.create(
            nama_sesi="subuh",
            jam_mulai=time(4, 0),
            jam_selesai=time(6, 0),
        )
        malam = SesiPresensi.objects.create(
            nama_sesi="malam",
            jam_mulai=time(18, 0),
            jam_selesai=time(20, 30),
        )
        existing = Presensi.objects.create(
            user=penghuni,
            sesi=subuh,
            tanggal=today,
            status="sakit",
        )
        now = datetime(2026, 1, 2, 7, 0, tzinfo=ZoneInfo("Asia/Jakarta"))

        with patch(
            "accounts.management.commands.generate_alpa.timezone.localdate",
            return_value=today,
        ), patch(
            "accounts.management.commands.generate_alpa.timezone.localtime",
            return_value=now,
        ):
            call_command("generate_alpa")
            call_command("generate_alpa")

        self.assertEqual(Presensi.objects.count(), 2)
        existing.refresh_from_db()
        self.assertEqual(existing.status, "sakit")
        self.assertTrue(
            Presensi.objects.filter(user=penghuni_lain, sesi=subuh, tanggal=today, status="alpa").exists()
        )
        self.assertFalse(Presensi.objects.filter(sesi=malam, tanggal=today).exists())


class IzinWorkflowTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_dir.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        self.penghuni = User.objects.create_user(username="penghuni", password="rahasia")
        self.fasil = User.objects.create_user(
            username="fasil", password="rahasia", role="fasil"
        )
        self.sesi = SesiPresensi.objects.create(
            nama_sesi="subuh",
            jam_mulai=time(4, 0),
            jam_selesai=time(6, 0),
        )
        self.client.force_login(self.penghuni)

    def create_pengajuan(self, status="sakit"):
        presensi = Presensi.objects.create(
            user=self.penghuni,
            sesi=self.sesi,
            tanggal=timezone.localdate(),
            status=status,
        )
        return PengajuanIzin.objects.create(
            presensi=presensi,
            alasan="Ada keperluan",
            file_bukti=SimpleUploadedFile("bukti.jpg", b"bukti"),
        )

    def test_resident_submission_and_fasil_approval_work_through_templates(self):
        response = self.client.post(
            reverse("izin_saya"),
            {
                "jenis": "sakit",
                "sesi": "subuh",
                "tanggal_mulai": timezone.localdate().isoformat(),
                "tanggal_selesai": timezone.localdate().isoformat(),
                "alasan": "Sedang sakit",
                "file_bukti": SimpleUploadedFile("bukti.jpg", b"bukti"),
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Riwayat Pengajuan")
        izin = PengajuanIzin.objects.get()
        self.assertEqual(izin.status_persetujuan, "pending")
        self.assertEqual(izin.presensi.status, "sakit")

        self.client.force_login(self.fasil)
        response = self.client.get(reverse("izin_list"))
        self.assertContains(response, "Setujui")
        self.assertContains(response, reverse("verifikasi_izin", args=[izin.id, "setuju"]))

        response = self.client.post(
            reverse("verifikasi_izin", args=[izin.id, "setuju"]),
            {"catatan_fasil": "Semoga lekas pulih"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Disetujui")
        izin.refresh_from_db()
        self.assertEqual(izin.status_persetujuan, "disetujui")
        self.assertEqual(izin.presensi.status, "sakit")
        self.assertEqual(izin.fasil, self.fasil)
        self.assertEqual(izin.catatan_fasil, "Semoga lekas pulih")

    def test_resident_can_request_approval_for_generated_alpa(self):
        today = timezone.localdate()
        Presensi.objects.create(
            user=self.penghuni,
            sesi=self.sesi,
            tanggal=today,
            status="alpa",
        )

        response = self.client.post(
            reverse("izin_saya"),
            {
                "jenis": "izin",
                "sesi": "subuh",
                "tanggal_mulai": today.isoformat(),
                "tanggal_selesai": today.isoformat(),
                "alasan": "Ada keperluan mendadak",
                "file_bukti": SimpleUploadedFile("bukti.jpg", b"bukti"),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        izin = PengajuanIzin.objects.get()
        self.assertEqual(izin.status_persetujuan, "pending")
        self.assertEqual(izin.presensi.status, "izin")

    def test_rejection_and_finalized_requests_cannot_be_changed(self):
        izin = self.create_pengajuan()
        self.client.force_login(self.fasil)

        response = self.client.post(
            reverse("verifikasi_izin", args=[izin.id, "tolak"]),
            {"catatan_fasil": "Bukti belum memadai"},
        )
        self.assertRedirects(response, reverse("izin_list"))
        izin.refresh_from_db()
        self.assertEqual(izin.status_persetujuan, "ditolak")
        self.assertEqual(izin.presensi.status, "alpa")
        self.assertEqual(izin.fasil, self.fasil)

        response = self.client.post(
            reverse("verifikasi_izin", args=[izin.id, "setuju"]),
            {"catatan_fasil": "Perubahan setelah diproses"},
        )
        self.assertRedirects(response, reverse("izin_list"))
        izin.refresh_from_db()
        self.assertEqual(izin.status_persetujuan, "ditolak")
        self.assertEqual(izin.presensi.status, "alpa")
        self.assertEqual(izin.catatan_fasil, "Bukti belum memadai")

    def test_approval_is_post_only_and_invalid_action_does_not_change_request(self):
        izin = self.create_pengajuan()
        self.client.force_login(self.fasil)

        response = self.client.get(reverse("verifikasi_izin", args=[izin.id, "setuju"]))
        self.assertEqual(response.status_code, 405)
        response = self.client.post(reverse("verifikasi_izin", args=[izin.id, "lainnya"]))
        self.assertRedirects(response, reverse("izin_list"))

        izin.refresh_from_db()
        self.assertEqual(izin.status_persetujuan, "pending")
        self.assertEqual(izin.presensi.status, "sakit")
        self.assertIsNone(izin.fasil)

    def test_resident_can_only_view_or_cancel_own_pending_request(self):
        own_izin = self.create_pengajuan()
        other_user = User.objects.create_user(username="penghuni-lain", password="rahasia")
        other_presensi = Presensi.objects.create(
            user=other_user,
            sesi=self.sesi,
            tanggal=timezone.localdate(),
            status="izin",
        )
        other_izin = PengajuanIzin.objects.create(
            presensi=other_presensi,
            alasan="Keperluan lain",
            file_bukti=SimpleUploadedFile("bukti-lain.jpg", b"bukti"),
        )

        self.assertEqual(
            self.client.get(reverse("izin_detail", args=[other_izin.id])).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(reverse("izin_batal", args=[other_izin.id])).status_code,
            404,
        )

        response = self.client.post(reverse("izin_batal", args=[own_izin.id]))
        self.assertRedirects(response, reverse("izin_saya"))
        self.assertFalse(PengajuanIzin.objects.filter(pk=own_izin.pk).exists())
        self.assertFalse(Presensi.objects.filter(pk=own_izin.presensi_id).exists())
        self.assertTrue(PengajuanIzin.objects.filter(pk=other_izin.pk).exists())

    def test_staff_cannot_submit_resident_requests_and_resident_cannot_approve(self):
        self.client.force_login(self.fasil)
        self.assertRedirects(self.client.get(reverse("izin_saya")), reverse("home"))
        self.assertRedirects(self.client.post(reverse("izin_saya")), reverse("home"))
        self.assertRedirects(
            self.client.post(
                reverse("do_presensi"),
                {"latitude": "-0.914", "longitude": "100.459"},
            ),
            reverse("home"),
        )

        izin = self.create_pengajuan()
        self.client.force_login(self.penghuni)
        response = self.client.post(
            reverse("verifikasi_izin", args=[izin.id, "setuju"]),
        )
        self.assertRedirects(response, reverse("home"))
        izin.refresh_from_db()
        self.assertEqual(izin.status_persetujuan, "pending")
        self.assertEqual(izin.presensi.status, "sakit")


class RoleAccessTests(TestCase):
    def setUp(self):
        self.penghuni = User.objects.create_user(username="penghuni", password="rahasia")
        self.fasil = User.objects.create_user(
            username="fasil", password="rahasia", role="fasil"
        )
        self.superadmin = User.objects.create_user(
            username="superadmin", password="rahasia", role="superadmin"
        )
        self.gedung = Gedung.objects.create(
            nama_gedung="Asrama",
            latitude=-0.914,
            longitude=100.459,
            radius_meter=100,
        )
        self.kamar = Kamar.objects.create(
            gedung=self.gedung,
            nomor_kamar="1",
            kapasitas=2,
        )
        self.sesi = SesiPresensi.objects.create(
            nama_sesi="subuh",
            jam_mulai=time(4, 0),
            jam_selesai=time(6, 0),
        )
        self.presensi = Presensi.objects.create(
            user=self.penghuni,
            sesi=self.sesi,
            tanggal=timezone.localdate(),
            status="alpa",
        )

    def assert_allowed_for(self, user, route_names):
        self.client.force_login(user)
        for route_name in route_names:
            with self.subTest(role=user.role, route=route_name):
                self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)

    def assert_denied_for(self, user, route_names):
        self.client.force_login(user)
        for route_name in route_names:
            with self.subTest(role=user.role, route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertRedirects(response, reverse("home"))

    def test_resident_access_is_limited_to_resident_pages(self):
        self.assert_allowed_for(self.penghuni, ("home", "riwayat", "izin_saya"))
        self.assert_denied_for(
            self.penghuni,
            (
                "izin_list",
                "penghuni_list",
                "penghuni_tambah",
                "gedung_list",
                "gedung_tambah",
                "sesi_list",
                "laporan",
                "laporan_csv",
            ),
        )
        self.client.force_login(self.penghuni)
        response = self.client.post(
            reverse("presensi_koreksi", args=[self.presensi.id]),
            {"status": "hadir"},
        )
        self.assertRedirects(response, reverse("home"))
        self.presensi.refresh_from_db()
        self.assertEqual(self.presensi.status, "alpa")

    def test_fasil_can_manage_residents_but_not_system_configuration(self):
        self.assert_allowed_for(
            self.fasil,
            (
                "home",
                "riwayat",
                "izin_list",
                "penghuni_list",
                "penghuni_tambah",
                "laporan",
                "laporan_csv",
            ),
        )
        self.assert_denied_for(
            self.fasil,
            ("izin_saya", "gedung_list", "gedung_tambah", "sesi_list"),
        )
        self.client.force_login(self.fasil)
        self.assertEqual(
            self.client.get(reverse("penghuni_detail", args=[self.penghuni.id])).status_code,
            200,
        )
        self.assertRedirects(
            self.client.get(reverse("sesi_ubah", args=[self.sesi.id])),
            reverse("home"),
        )

    def test_superadmin_has_staff_and_configuration_access(self):
        self.assert_allowed_for(
            self.superadmin,
            (
                "home",
                "riwayat",
                "izin_list",
                "penghuni_list",
                "gedung_list",
                "gedung_tambah",
                "sesi_list",
                "laporan",
                "laporan_csv",
            ),
        )
        self.client.force_login(self.superadmin)
        self.assertEqual(
            self.client.get(reverse("penghuni_detail", args=[self.penghuni.id])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("sesi_ubah", args=[self.sesi.id])).status_code,
            200,
        )
        dashboard = self.client.get(reverse("home"))
        self.assertNotContains(dashboard, reverse("admin:index"))

    def test_django_admin_link_and_route_require_django_staff_permission(self):
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

        django_superuser = User.objects.create_superuser(
            username="django-admin",
            email="admin@example.com",
            password="rahasia",
        )
        self.client.force_login(django_superuser)
        dashboard = self.client.get(reverse("home"))
        self.assertContains(dashboard, reverse("admin:index"))
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)


class SeedDemoDataCommandTests(TestCase):
    def test_seed_command_is_repeatable_and_keeps_existing_records(self):
        existing_user = User.objects.create_user(
            username="existing-user", password="rahasia", role="penghuni"
        )
        with tempfile.TemporaryDirectory() as media_dir:
            with override_settings(MEDIA_ROOT=media_dir):
                call_command(
                    "seed_demo_data",
                    jumlah_penghuni=8,
                    password="Demo12345!",
                    verbosity=0,
                )
                counts_after_first_run = (
                    User.objects.count(),
                    Gedung.objects.count(),
                    Kamar.objects.count(),
                    PenghuniKamar.objects.count(),
                    SesiPresensi.objects.count(),
                    Presensi.objects.count(),
                    PengajuanIzin.objects.count(),
                )
                call_command(
                    "seed_demo_data",
                    jumlah_penghuni=8,
                    password="Demo12345!",
                    verbosity=0,
                )
                counts_after_second_run = (
                    User.objects.count(),
                    Gedung.objects.count(),
                    Kamar.objects.count(),
                    PenghuniKamar.objects.count(),
                    SesiPresensi.objects.count(),
                    Presensi.objects.count(),
                    PengajuanIzin.objects.count(),
                )

        self.assertEqual(counts_after_first_run, counts_after_second_run)
        self.assertEqual(counts_after_first_run[0], 10)
        self.assertEqual(counts_after_first_run[1], 3)
        self.assertEqual(counts_after_first_run[2], 12)
        self.assertEqual(counts_after_first_run[3], 8)
        self.assertEqual(counts_after_first_run[4], 2)
        self.assertEqual(counts_after_first_run[5], 8 * 30 * 2)
        self.assertGreater(counts_after_first_run[6], 0)
        self.assertFalse(existing_user.riwayat_kamar.exists())
