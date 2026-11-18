from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from accounts.models import PenghuniKamar, Presensi, SesiPresensi


class Command(BaseCommand):
    help = "Buat catatan alpa untuk penghuni aktif setelah sesi presensi selesai."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tanggal",
            type=date.fromisoformat,
            help="Tanggal yang diproses dalam format YYYY-MM-DD (default: hari ini).",
        )

    def handle(self, *args, **options):
        target_date = options["tanggal"] or timezone.localdate()
        today = timezone.localdate()
        if target_date > today:
            raise CommandError("Tanggal alpa tidak boleh di masa depan.")

        if target_date == today:
            now_time = timezone.localtime().time()
            sessions = SesiPresensi.objects.filter(jam_selesai__lte=now_time)
        else:
            sessions = SesiPresensi.objects.all()
        sessions = list(sessions.order_by("jam_mulai"))
        if not sessions:
            self.stdout.write("Belum ada sesi yang selesai untuk diproses.")
            return

        user_ids = list(
            PenghuniKamar.objects.filter(tanggal_masuk__lte=target_date)
            .filter(Q(tanggal_keluar__isnull=True) | Q(tanggal_keluar__gte=target_date))
            .values_list("user_id", flat=True)
            .distinct()
        )
        if not user_ids:
            self.stdout.write("Tidak ada penghuni yang menempati kamar pada tanggal tersebut.")
            return

        session_ids = [session.id for session in sessions]
        existing = set(
            Presensi.objects.filter(
                tanggal=target_date,
                user_id__in=user_ids,
                sesi_id__in=session_ids,
            ).values_list("user_id", "sesi_id")
        )
        missing = [
            Presensi(user_id=user_id, sesi_id=session_id, tanggal=target_date, status="alpa")
            for user_id in user_ids
            for session_id in session_ids
            if (user_id, session_id) not in existing
        ]
        if missing:
            Presensi.objects.bulk_create(missing, ignore_conflicts=True)

        self.stdout.write(
            f"Selesai memeriksa {len(user_ids) * len(session_ids)} kombinasi penghuni dan sesi "
            f"untuk {target_date}; {len(missing)} catatan alpa ditambahkan."
        )
