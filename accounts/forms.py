import os
from datetime import timedelta

from django import forms
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import User, Gedung, Kamar, SesiPresensi, PenghuniKamar


class StyledMixin:
    """Beri class CSS 'input' ke semua widget agar sesuai desain."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, (forms.CheckboxInput, forms.RadioSelect)):
                f.widget.attrs['class'] = 'input'


DATE = lambda: forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
TIME = lambda: forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')


# ------------------------------------------------------------ penghuni
class PenghuniForm(StyledMixin, forms.Form):
    first_name = forms.CharField(label='Nama depan', max_length=150)
    last_name = forms.CharField(label='Nama belakang', max_length=150, required=False)
    nim_nip = forms.CharField(label='NIM', max_length=30)
    username = forms.CharField(label='Username', max_length=150)
    email = forms.EmailField(label='Email', required=False, help_text='Dipakai untuk fitur lupa kata sandi.')
    password = forms.CharField(label='Kata sandi', required=False, widget=forms.PasswordInput(render_value=False))
    kamar = forms.ModelChoiceField(label='Kamar', required=False, queryset=Kamar.objects.none())
    tanggal_masuk = forms.DateField(label='Tanggal masuk', required=False, widget=DATE())

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        self.fields['kamar'].queryset = Kamar.objects.select_related('gedung').order_by('gedung__nama_gedung', 'nomor_kamar')
        self.aktif = instance.riwayat_kamar.filter(status='aktif').first() if instance else None
        if instance is None:
            self.fields['password'].required = True
            self.initial.setdefault('tanggal_masuk', timezone.localdate())
        else:
            self.fields['password'].help_text = 'Kosongkan jika tidak ingin mengubah kata sandi.'
            self.initial.update({
                'first_name': instance.first_name, 'last_name': instance.last_name,
                'nim_nip': instance.nim_nip, 'username': instance.username, 'email': instance.email,
                'kamar': self.aktif.kamar_id if self.aktif else None,
                'tanggal_masuk': self.aktif.tanggal_masuk if self.aktif else timezone.localdate(),
            })

    def _unik(self, field, value):
        qs = User.objects.filter(**{field: value})
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        return not qs.exists()

    def clean_username(self):
        v = self.cleaned_data['username'].strip()
        if not self._unik('username', v):
            raise ValidationError('Username sudah dipakai.')
        return v

    def clean_nim_nip(self):
        v = self.cleaned_data['nim_nip'].strip()
        if not self._unik('nim_nip', v):
            raise ValidationError('NIM sudah terdaftar.')
        return v

    def clean(self):
        data = super().clean()
        kamar = data.get('kamar')
        if kamar and not (self.aktif and self.aktif.kamar_id == kamar.id):
            if kamar.penghuni_list.filter(status='aktif').count() >= kamar.kapasitas:
                self.add_error('kamar', f'Kamar {kamar.nomor_kamar} sudah penuh (kapasitas {kamar.kapasitas}).')
        return data

    def save(self):
        d = self.cleaned_data
        u = self.instance or User(role='penghuni')
        u.username, u.first_name, u.last_name = d['username'], d['first_name'], d['last_name']
        u.email, u.nim_nip = d['email'], d['nim_nip']
        if d['password']:
            u.set_password(d['password'])
        u.save()
        kamar = d.get('kamar')
        if kamar and not (self.aktif and self.aktif.kamar_id == kamar.id):
            if self.aktif:
                self.aktif.status, self.aktif.tanggal_keluar = 'non_aktif', timezone.localdate()
                self.aktif.save()
            PenghuniKamar.objects.create(user=u, kamar=kamar, status='aktif',
                                         tanggal_masuk=d.get('tanggal_masuk') or timezone.localdate())
        return u


# ------------------------------------------------------------ gedung, kamar, sesi
class GedungForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Gedung
        fields = ['nama_gedung', 'latitude', 'longitude', 'radius_meter']
        labels = {'nama_gedung': 'Nama gedung', 'latitude': 'Latitude', 'longitude': 'Longitude',
                  'radius_meter': 'Radius presensi (meter)'}
        help_texts = {'latitude': 'Contoh: -0.9140', 'longitude': 'Contoh: 100.4590',
                      'radius_meter': 'Jarak maksimum dari titik gedung agar presensi sah.'}


class KamarForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Kamar
        fields = ['gedung', 'nomor_kamar', 'kapasitas']
        labels = {'gedung': 'Gedung', 'nomor_kamar': 'Nomor kamar', 'kapasitas': 'Kapasitas (orang)'}

    def clean_kapasitas(self):
        k = self.cleaned_data['kapasitas']
        if k < 1:
            raise ValidationError('Kapasitas minimal 1.')
        if self.instance.pk:
            terisi = self.instance.penghuni_list.filter(status='aktif').count()
            if k < terisi:
                raise ValidationError(f'Saat ini sudah ada {terisi} penghuni aktif di kamar ini.')
        return k


class SesiForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = SesiPresensi
        fields = ['jam_mulai', 'jam_selesai']
        labels = {'jam_mulai': 'Jam mulai', 'jam_selesai': 'Jam selesai'}
        widgets = {'jam_mulai': TIME(), 'jam_selesai': TIME()}

    def clean(self):
        d = super().clean()
        if d.get('jam_mulai') and d.get('jam_selesai') and d['jam_selesai'] <= d['jam_mulai']:
            self.add_error('jam_selesai', 'Jam selesai harus setelah jam mulai.')
        return d


# ------------------------------------------------------------ izin
class IzinForm(StyledMixin, forms.Form):
    jenis = forms.ChoiceField(label='Jenis', choices=[('izin', 'Izin'), ('sakit', 'Sakit')])
    sesi = forms.ChoiceField(label='Sesi', choices=[('semua', 'Subuh & Malam'), ('subuh', 'Subuh saja'), ('malam', 'Malam saja')])
    tanggal_mulai = forms.DateField(label='Tanggal mulai', widget=DATE())
    tanggal_selesai = forms.DateField(label='Tanggal selesai', widget=DATE())
    alasan = forms.CharField(label='Alasan', widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Jelaskan alasan Anda'}))
    file_bukti = forms.FileField(label='Bukti pendukung (JPG / PDF)', help_text='Maksimal 5 MB.',
                                 widget=forms.ClearableFileInput(attrs={'accept': '.jpg,.jpeg,.pdf'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hari_ini = timezone.localdate()
        self.initial.setdefault('tanggal_mulai', hari_ini)
        self.initial.setdefault('tanggal_selesai', hari_ini)

    def clean_file_bukti(self):
        f = self.cleaned_data['file_bukti']
        if os.path.splitext(f.name)[1].lower() not in ('.jpg', '.jpeg', '.pdf'):
            raise ValidationError('Format berkas harus JPG atau PDF.')
        if f.size > 5 * 1024 * 1024:
            raise ValidationError('Ukuran berkas maksimal 5 MB.')
        return f

    def clean(self):
        d = super().clean()
        m, s = d.get('tanggal_mulai'), d.get('tanggal_selesai')
        if m and s:
            if m < timezone.localdate():
                self.add_error('tanggal_mulai', 'Tanggal mulai tidak boleh sebelum hari ini.')
            if s < m:
                self.add_error('tanggal_selesai', 'Tanggal selesai harus sama atau setelah tanggal mulai.')
            elif s - m > timedelta(days=13):
                self.add_error('tanggal_selesai', 'Maksimal 14 hari per pengajuan.')
        return d


# ------------------------------------------------------------ akun
class ProfilForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {'first_name': 'Nama depan', 'last_name': 'Nama belakang', 'email': 'Email'}


class StyledPasswordChangeForm(StyledMixin, PasswordChangeForm):
    pass


class StyledPasswordResetForm(StyledMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(StyledMixin, SetPasswordForm):
    pass
