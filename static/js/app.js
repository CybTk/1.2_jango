document.addEventListener('DOMContentLoaded', () => {
  // Sidebar (mobile)
  const sb = document.getElementById('sidebar');
  document.querySelector('.burger')?.addEventListener('click', () => sb.classList.toggle('open'));
  document.querySelector('.main')?.addEventListener('click', () => sb?.classList.remove('open'));

  // Dialog generik: <button data-dialog="id" data-url="..." data-title="...">
  document.querySelectorAll('[data-dialog]').forEach(btn => btn.addEventListener('click', () => {
    const dlg = document.getElementById(btn.dataset.dialog);
    if (btn.dataset.url) dlg.querySelector('form').action = btn.dataset.url;
    if (btn.dataset.title) dlg.querySelector('[data-role="title"]').textContent = btn.dataset.title;
    if (btn.dataset.who) dlg.querySelector('[data-role="who"]').textContent = btn.dataset.who;
    const v = dlg.querySelector('[data-role="value"]'); if (v && btn.dataset.value) v.value = btn.dataset.value;
    dlg.showModal();
  }));
  document.querySelectorAll('dialog').forEach(d => {
    d.addEventListener('click', e => { if (e.target === d) d.close(); });
    d.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => d.close()));
  });

  const csrfToken = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
  const decodeBase64Url = value => {
    const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(base64 + '='.repeat((4 - base64.length % 4) % 4));
    return Uint8Array.from(binary, char => char.charCodeAt(0));
  };
  const preparePublicKeyOptions = options => {
    const result = { ...options, challenge: decodeBase64Url(options.challenge) };
    if (options.user) result.user = { ...options.user, id: decodeBase64Url(options.user.id) };
    ['allowCredentials', 'excludeCredentials'].forEach(key => {
      if (options[key]) result[key] = options[key].map(item => ({ ...item, id: decodeBase64Url(item.id) }));
    });
    return result;
  };
  const encodeBase64Url = value => {
    const bytes = new Uint8Array(value);
    let binary = '';
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  };
  const serializeCredential = credential => {
    if (typeof credential.toJSON === 'function') return credential.toJSON();
    const response = { clientDataJSON: encodeBase64Url(credential.response.clientDataJSON) };
    if (credential.response.attestationObject) {
      response.attestationObject = encodeBase64Url(credential.response.attestationObject);
      response.transports = credential.response.getTransports?.() || [];
    } else {
      response.authenticatorData = encodeBase64Url(credential.response.authenticatorData);
      response.signature = encodeBase64Url(credential.response.signature);
      response.userHandle = credential.response.userHandle
        ? encodeBase64Url(credential.response.userHandle) : null;
    }
    return {
      id: credential.id,
      rawId: encodeBase64Url(credential.rawId),
      type: credential.type,
      response,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(),
    };
  };
  const postWebAuthnJSON = async (url, body) => {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Permintaan biometrik gagal.');
    return data;
  };

  // Presensi tetap memakai lokasi; passkey hanya menambahkan verifikasi opsional.
  const fp = document.getElementById('formPresensi');
  if (fp) {
    const manualButton = fp.querySelector('button[type="submit"]');
    const passkeyButton = fp.querySelector('[data-passkey-attendance]');
    const geoStatus = document.getElementById('geoStatus');
    const passkeyStatus = document.getElementById('passkeyStatus');
    const submitWithLocation = () => {
      if (!navigator.geolocation) {
        geoStatus.textContent = 'Browser tidak mendukung layanan lokasi.';
        manualButton.disabled = false;
        if (passkeyButton) passkeyButton.disabled = false;
        return;
      }
      manualButton.disabled = true;
      if (passkeyButton) passkeyButton.disabled = true;
      geoStatus.textContent = 'Mengambil lokasi...';
      navigator.geolocation.getCurrentPosition(pos => {
        fp.elements.latitude.value = pos.coords.latitude;
        fp.elements.longitude.value = pos.coords.longitude;
        fp.dataset.ready = '1';
        fp.requestSubmit();
      }, () => {
        manualButton.disabled = false;
        if (passkeyButton) passkeyButton.disabled = false;
        geoStatus.textContent = 'Izin lokasi diperlukan. Aktifkan GPS lalu coba lagi.';
      }, { enableHighAccuracy: true, timeout: 15000 });
    };

    fp.addEventListener('submit', e => {
      if (fp.dataset.ready === '1') return;
      e.preventDefault();
      fp.elements.verification_method.value = 'manual';
      submitWithLocation();
    });

    if (passkeyButton) {
      let options;
      const loadAuthenticationOptions = async () => {
        passkeyButton.disabled = true;
        try {
          options = await postWebAuthnJSON(fp.dataset.passkeyOptions, {});
          passkeyButton.disabled = false;
          passkeyStatus.textContent = 'Biometrik perangkat siap digunakan.';
        } catch (error) {
          passkeyStatus.textContent = `${error.message} Anda tetap dapat presensi tanpa biometrik.`;
        }
      };
      if (!window.isSecureContext || !window.PublicKeyCredential || !navigator.credentials) {
        passkeyButton.disabled = true;
        passkeyStatus.textContent = window.isSecureContext
          ? 'Browser ini tidak mendukung passkey. Anda tetap dapat presensi tanpa biometrik.'
          : 'Passkey memerlukan HTTPS atau localhost. Anda tetap dapat presensi tanpa biometrik.';
      } else {
        loadAuthenticationOptions();
      }
      passkeyButton.addEventListener('click', async () => {
        if (!options) return;
        passkeyButton.disabled = true;
        try {
          const assertionPromise = navigator.credentials.get({
            publicKey: preparePublicKeyOptions(options),
          });
          const assertion = await assertionPromise;
          if (!assertion) throw new Error('Verifikasi dibatalkan.');
          await postWebAuthnJSON(fp.dataset.passkeyVerify, serializeCredential(assertion));
          fp.elements.verification_method.value = 'passkey';
          passkeyStatus.textContent = 'Terverifikasi. Mengambil lokasi...';
          submitWithLocation();
        } catch (error) {
          passkeyStatus.textContent = `${error.message} Anda dapat mencoba lagi atau memakai presensi biasa.`;
          await loadAuthenticationOptions();
        }
      });
    }
  }

  // Pendaftaran passkey memerlukan persetujuan eksplisit dan menggunakan perangkat lokal.
  const registerButton = document.querySelector('[data-passkey-register]');
  if (registerButton) {
    const consent = document.querySelector('[data-passkey-consent]');
    const status = document.getElementById('passkeyRegistrationStatus');
    let options;
    const loadRegistrationOptions = async () => {
      options = null;
      registerButton.disabled = true;
      try {
        options = await postWebAuthnJSON(registerButton.dataset.optionsUrl, { consent: true });
        registerButton.disabled = false;
        status.textContent = 'Siap mendaftarkan passkey pada perangkat ini.';
      } catch (error) {
        status.textContent = error.message;
      }
    };
    consent.addEventListener('change', () => {
      if (consent.checked && window.isSecureContext && window.PublicKeyCredential && navigator.credentials) {
        loadRegistrationOptions();
      } else {
        options = null;
        registerButton.disabled = true;
        if (consent.checked) {
          status.textContent = window.isSecureContext
            ? 'Browser ini tidak mendukung passkey.'
            : 'Passkey memerlukan HTTPS atau localhost.';
        }
        else status.textContent = '';
      }
    });
    registerButton.addEventListener('click', async () => {
      if (!options) return;
      registerButton.disabled = true;
      try {
        const creationPromise = navigator.credentials.create({
          publicKey: preparePublicKeyOptions(options),
        });
        const credential = await creationPromise;
        if (!credential) throw new Error('Pendaftaran dibatalkan.');
        await postWebAuthnJSON(registerButton.dataset.verifyUrl, serializeCredential(credential));
        status.textContent = 'Passkey berhasil didaftarkan.';
        window.location.reload();
      } catch (error) {
        status.textContent = `${error.message} Pastikan perangkat Anda telah mengaktifkan biometrik.`;
        if (consent.checked) await loadRegistrationOptions();
      }
    });
  }

  // Nama file bukti
  document.querySelectorAll('input[type=file][data-hint]').forEach(inp => inp.addEventListener('change', () => {
    const el = document.getElementById(inp.dataset.hint), f = inp.files[0];
    if (el && f) el.textContent = `${f.name} (${(f.size/1024).toFixed(0)} KB)`;
  }));

  // Pesan hilang otomatis
  setTimeout(() => document.querySelectorAll('.alert').forEach(a => a.style.display = 'none'), 6000);
});
