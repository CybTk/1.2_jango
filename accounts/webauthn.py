import json
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import WebAuthnCredential


CHALLENGE_TTL_SECONDS = 300
MAX_CREDENTIAL_BODY_BYTES = 65536


def _is_penghuni(user):
    return user.role == 'penghuni' and not user.is_superuser


def _context(request):
    parsed = urlsplit(request.build_absolute_uri('/'))
    rp_id = getattr(settings, 'WEBAUTHN_RP_ID', None) or parsed.hostname
    origin = getattr(settings, 'WEBAUTHN_ORIGIN', None) or f'{parsed.scheme}://{parsed.netloc}'
    if not rp_id or not parsed.netloc:
        raise ValueError('WebAuthn relying party is not configured.')
    return rp_id, origin


def _json_body(request):
    content_length = request.META.get('CONTENT_LENGTH')
    if content_length and int(content_length) > MAX_CREDENTIAL_BODY_BYTES:
        raise ValueError('Credential response is too large.')
    try:
        value = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Malformed JSON body.') from exc
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object.')
    return value


def _store_challenge(request, kind, options):
    request.session[f'webauthn_{kind}'] = {
        'challenge': bytes_to_base64url(options.challenge),
        'user_id': request.user.pk,
        'expires_at': int(time.time()) + CHALLENGE_TTL_SECONDS,
    }


def _take_challenge(request, kind):
    state = request.session.pop(f'webauthn_{kind}', None)
    if (
        not isinstance(state, dict)
        or state.get('user_id') != request.user.pk
        or state.get('expires_at', 0) <= int(time.time())
        or not state.get('challenge')
    ):
        raise ValueError('Challenge is missing or expired.')
    return base64url_to_bytes(state['challenge'])


def _error(message, status=400):
    return JsonResponse({'error': message}, status=status)


@login_required
@require_POST
def registration_options(request):
    if not _is_penghuni(request.user):
        return _error('Hanya penghuni yang dapat mendaftarkan passkey.', 403)
    try:
        body = _json_body(request)
        if body.get('consent') is not True:
            return _error('Persetujuan eksplisit diperlukan.', 400)
        rp_id, _ = _context(request)
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=getattr(settings, 'WEBAUTHN_RP_NAME', 'Presensi Asrama'),
            user_id=str(request.user.pk).encode('utf-8'),
            user_name=request.user.username,
            user_display_name=request.user.get_full_name() or request.user.username,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(item.credential_id),
                    transports=item.transports or None,
                )
                for item in request.user.passkeys.all()
            ],
        )
        _store_challenge(request, 'registration', options)
        return JsonResponse(json.loads(options_to_json(options)))
    except (ValueError, TypeError, WebAuthnException):
        return _error('Tidak dapat memulai pendaftaran passkey. Silakan coba lagi.')


@login_required
@require_POST
def register_credential(request):
    if not _is_penghuni(request.user):
        return _error('Hanya penghuni yang dapat mendaftarkan passkey.', 403)
    try:
        body = _json_body(request)
        challenge = _take_challenge(request, 'registration')
        rp_id, origin = _context(request)
        verified = verify_registration_response(
            credential=body,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
        transports = body.get('response', {}).get('transports', [])
        if not isinstance(transports, list):
            transports = []
        transports = [
            item for item in transports
            if item in {'usb', 'nfc', 'ble', 'internal', 'hybrid', 'smart-card'}
        ]
        WebAuthnCredential.objects.create(
            user=request.user,
            credential_id=bytes_to_base64url(verified.credential_id),
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=transports,
            consented_at=timezone.now(),
        )
    except IntegrityError:
        return _error('Passkey ini sudah terdaftar pada akun lain.')
    except (ValueError, TypeError, KeyError, WebAuthnException):
        return _error('Verifikasi pendaftaran gagal atau kedaluwarsa. Mulai pendaftaran lagi.')
    return JsonResponse({'ok': True})


@login_required
@require_POST
def authentication_options(request):
    if not _is_penghuni(request.user):
        return _error('Hanya penghuni yang dapat menggunakan passkey.', 403)
    credentials = list(request.user.passkeys.all())
    if not credentials:
        return _error('Belum ada passkey pada akun ini.', 400)
    try:
        rp_id, _ = _context(request)
        options = generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=[
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(item.credential_id),
                    transports=item.transports or None,
                )
                for item in credentials
            ],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        _store_challenge(request, 'authentication', options)
        return JsonResponse(json.loads(options_to_json(options)))
    except (ValueError, TypeError, WebAuthnException):
        return _error('Tidak dapat memulai verifikasi passkey. Silakan coba lagi.')


@login_required
@require_POST
def authenticate_credential(request):
    if not _is_penghuni(request.user):
        return _error('Hanya penghuni yang dapat menggunakan passkey.', 403)
    try:
        body = _json_body(request)
        challenge = _take_challenge(request, 'authentication')
        credential_id = body.get('id')
        if not isinstance(credential_id, str):
            raise ValueError('Credential identifier is missing.')
        credential = request.user.passkeys.get(credential_id=credential_id)
        rp_id, origin = _context(request)
        verified = verify_authentication_response(
            credential=body,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(credential.public_key),
            credential_current_sign_count=credential.sign_count,
            require_user_verification=True,
        )
        credential.sign_count = verified.new_sign_count
        credential.save(update_fields=['sign_count'])
    except WebAuthnCredential.DoesNotExist:
        return _error('Passkey tidak terdaftar pada akun ini.')
    except (ValueError, TypeError, KeyError, WebAuthnException):
        return _error('Verifikasi passkey gagal atau kedaluwarsa. Silakan coba lagi.')

    request.session['attendance_passkey'] = {
        'credential_id': credential.credential_id,
        'user_id': request.user.pk,
        'expires_at': int(time.time()) + CHALLENGE_TTL_SECONDS,
    }
    return JsonResponse({'ok': True})


def consume_attendance_passkey(request):
    state = request.session.pop('attendance_passkey', None)
    if (
        not isinstance(state, dict)
        or state.get('user_id') != request.user.pk
        or state.get('expires_at', 0) <= int(time.time())
    ):
        return False
    return request.user.passkeys.filter(credential_id=state.get('credential_id')).exists()


@login_required
@require_POST
def delete_credential(request, credential_id):
    if not _is_penghuni(request.user):
        messages.error(request, 'Hanya penghuni yang dapat mengelola passkey.')
        return redirect('home')
    credential = get_object_or_404(
        WebAuthnCredential, pk=credential_id, user=request.user
    )
    credential.delete()
    messages.success(request, 'Passkey berhasil dihapus dari akun.')
    return redirect('profil')
