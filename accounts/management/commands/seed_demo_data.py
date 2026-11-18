from datetime import datetime, time, timedelta

from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import (
    Gedung,
    Kamar,
    PengajuanIzin,
    PenghuniKamar,
    Presensi,
    SesiPresensi,
    User,
)


NAMA_DEPAN = (
    "Aditya", "Aisyah", "Akbar", "Alya", "Andi", "Annisa", "Arif", "Aulia",
    "Bagas", "Citra", "Daffa", "Dewi", "Dimas", "Fajar", "Farah", "Fitri",
    "Gita", "Hana", "Ilham", "Intan", "Iqbal", "Nadia", "Naufal", "Putri",
)
NAMA_BELAKANG = (
    "Pratama", "Lestari", "Saputra", "Rahmawati", "Wijaya", "Putri",
    "Hidayat", "Permata", "Kurniawan", "Sari", "Maulana", "Ananda",
)
NAMA_GEDUNG = ("Demo Asrama A", "Demo Asrama B", "Demo Asrama C")
ALASAN_DEMO = "Data contoh untuk demonstrasi alur pengajuan izin."


def _bukti_pdf():
    stream = b"BT /F1 14 Tf 24 48 Td (BUKTI IZIN DATA DEMO) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return ContentFile(bytes(pdf))


class Command(BaseCommand):
    help = "Tambahkan data demo asrama ke SQLite tanpa menghapus atau mengubah data lama."

    def add_arguments(self, parser):
        parser.add_argument(
            "--jumlah-penghuni",
            type=int,
            default=48,
            help="Jumlah akun demo penghuni (1-48, default: 48).",
        )
        parser.add_argument(
            "--password",
            default="DemoAsrama123!",
            help="Kata sandi awal akun demo yang baru dibuat.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        jumlah_penghuni = options["jumlah_penghuni"]
        if not 1 <= jumlah_penghuni <= 48:
            raise CommandError("Jumlah penghuni harus antara 1 dan 48.")
        password = options["password"]
        if len(password) < 8:
            raise CommandError("Kata sandi demo minimal 8 karakter.")

        jumlah_gedung_baru = 0
        gedung_list = []
        for index, nama in enumerate(NAMA_GEDUNG):
            gedung, dibuat = Gedung.objects.get_or_create(
                nama_gedung=nama,
                defaults={
                    "latitude": -0.914 + index * 0.001,
                    "longitude": 100.459 + index * 0.001,
                    "radius_meter": 100,
                },
            )
            gedung_list.append(gedung)
            jumlah_gedung_baru += int(dibuat)

        kamar_list = []
        jumlah_kamar_baru = 0
        for index in range(12):
            gedung = gedung_list[index // 4]
            kamar, dibuat = Kamar.objects.get_or_create(
                gedung=gedung,
                nomor_kamar=f"{gedung.nama_gedung[-1]}{index % 4 + 1:02d}",
                defaults={"kapasitas": 4},
            )
            kamar_list.append(kamar)
            jumlah_kamar_baru += int(dibuat)

        fasil, fasil_baru = User.objects.get_or_create(
            username="demo_fasil",
            defaults={
                "first_name": "Fasilitator",
                "last_name": "Demo",
                "email": "demo.fasil@example.test",
                "role": "fasil",
                "password": make_password(password),
            },
        )
        if fasil.role != "fasil":
            raise CommandError("Username demo_fasil sudah dipakai akun yang bukan fasilitator.")

        penghuni_list = []
        penempatan_baru = 0
        jumlah_akun_baru = int(fasil_baru)
        for index in range(jumlah_penghuni):
            username = f"demo_penghuni{index + 1:02d}"
            user, dibuat = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": NAMA_DEPAN[index % len(NAMA_DEPAN)],
                    "last_name": NAMA_BELAKANG[index % len(NAMA_BELAKANG)],
                    "email": f"{username}@example.test",
                    "nim_nip": f"DEMO2026{index + 1:04d}",
                    "role": "penghuni",
                    "password": make_password(password),
                },
            )
            if user.role != "penghuni":
                raise CommandError(f"Username {username} sudah dipakai akun yang bukan penghuni.")
            jumlah_akun_baru += int(dibuat)
            kamar = kamar_list[index // 4]
            if not user.riwayat_kamar.filter(status="aktif").exists():
                PenghuniKamar.objects.create(
                    user=user,
                    kamar=kamar,
                    tanggal_masuk=timezone.localdate() - timedelta(days=90),
                )
                penempatan_baru += 1
            penghuni_list.append((user, kamar))

        sesi_defaults = (
            ("subuh", time(4, 0), time(6, 0)),
            ("malam", time(18, 0), time(20, 30)),
        )
        sesi_list = []
        jumlah_sesi_baru = 0
        for nama_sesi, jam_mulai, jam_selesai in sesi_defaults:
            sesi, dibuat = SesiPresensi.objects.get_or_create(
                nama_sesi=nama_sesi,
                defaults={"jam_mulai": jam_mulai, "jam_selesai": jam_selesai},
            )
            sesi_list.append(sesi)
            jumlah_sesi_baru += int(dibuat)

        hari_ini = timezone.localdate()
        tanggal_awal = hari_ini - timedelta(days=29)
        penghuni_ids = [user.id for user, _ in penghuni_list]
        sesi_ids = [sesi.id for sesi in sesi_list]
        presensi_lama = {
            (presensi.user_id, presensi.sesi_id, presensi.tanggal): presensi
            for presensi in Presensi.objects.filter(
                user_id__in=penghuni_ids,
                sesi_id__in=sesi_ids,
                tanggal__range=(tanggal_awal, hari_ini),
            )
        }

        presensi_baru = []
        for user_index, (user, kamar) in enumerate(penghuni_list):
            gedung = kamar.gedung
            for hari_ke in range(30):
                tanggal = tanggal_awal + timedelta(days=hari_ke)
                for sesi_index, sesi in enumerate(sesi_list):
                    if (user.id, sesi.id, tanggal) in presensi_lama:
                        continue
                    hasil = (user_index * 23 + hari_ke * 17 + sesi_index * 41) % 100
                    status = "alpa" if hasil < 10 else "terlambat" if hasil < 20 else "hadir"
                    waktu = None
                    if status != "alpa":
                        durasi = (
                            datetime.combine(tanggal, sesi.jam_selesai)
                            - datetime.combine(tanggal, sesi.jam_mulai)
                        )
                        bagian = 2 if status == "terlambat" else 4
                        waktu_lokal = datetime.combine(tanggal, sesi.jam_mulai) + durasi / bagian
                        waktu = timezone.make_aware(waktu_lokal)
                    presensi_baru.append(
                        Presensi(
                            user=user,
                            sesi=sesi,
                            tanggal=tanggal,
                            status=status,
                            waktu_presensi=waktu,
                            latitude=gedung.latitude if waktu else None,
                            longitude=gedung.longitude if waktu else None,
                            is_in_radius=bool(waktu),
                        )
                    )

        if presensi_baru:
            Presensi.objects.bulk_create(presensi_baru, ignore_conflicts=True)

        jumlah_izin_demo_lama = PengajuanIzin.objects.filter(alasan=ALASAN_DEMO).count()
        sisa_izin_demo = max(12 - jumlah_izin_demo_lama, 0)
        kandidat_izin = list(
            Presensi.objects.filter(
                user_id__in=penghuni_ids,
                sesi_id__in=sesi_ids,
                tanggal__range=(tanggal_awal, hari_ini),
                status="alpa",
            )
            .exclude(pengajuan_izin__isnull=False)
            .select_related("user")
            .order_by("tanggal", "user_id", "sesi_id")[:sisa_izin_demo]
        )
        jumlah_izin_baru = 0
        for offset, presensi in enumerate(kandidat_izin):
            index = jumlah_izin_demo_lama + offset
            jenis = "sakit" if index % 2 else "izin"
            status_pengajuan = (
                "pending" if index < 4 else "disetujui" if index < 8 else "ditolak"
            )
            presensi.status = "alpa" if status_pengajuan == "ditolak" else jenis
            presensi.save(update_fields=["status"])
            PengajuanIzin.objects.create(
                presensi=presensi,
                fasil=None if status_pengajuan == "pending" else fasil,
                alasan=ALASAN_DEMO,
                file_bukti=_bukti_pdf(),
                status_persetujuan=status_pengajuan,
                catatan_fasil=(
                    None if status_pengajuan == "pending"
                    else "Data demo: pengajuan diproses untuk contoh."
                ),
            )
            jumlah_izin_baru += 1

        jumlah_presensi = Presensi.objects.filter(
            user_id__in=penghuni_ids,
            sesi_id__in=sesi_ids,
            tanggal__range=(tanggal_awal, hari_ini),
        ).count()
        self.stdout.write(self.style.SUCCESS("Data demo berhasil disiapkan (data lama tidak dihapus)."))
        self.stdout.write(
            f"Gedung baru: {jumlah_gedung_baru}; kamar baru: {jumlah_kamar_baru}; "
            f"sesi baru: {jumlah_sesi_baru}; akun baru: {jumlah_akun_baru}; "
            f"penempatan baru: {penempatan_baru}."
        )
        self.stdout.write(
            f"Penghuni demo: {len(penghuni_list)}; presensi demo: {jumlah_presensi}; "
            f"pengajuan izin contoh baru: {jumlah_izin_baru}."
        )
        self.stdout.write("Akun fasilitator demo: demo_fasil")
        self.stdout.write(f"Akun penghuni demo: demo_penghuni01 s.d. demo_penghuni{jumlah_penghuni:02d}")
        self.stdout.write(f"Kata sandi awal akun demo baru: {password}")
