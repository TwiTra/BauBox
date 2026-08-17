/* ═══════════════════════════════════════════════════════════════════════
   cloud.js – Google Drive als gemeinsamer Speicher

   Der Plan liegt als einzelne Datei „Urlaubsplaner.json“ im Google Drive des
   Nutzers. Jedes Gerät meldet sich mit dem eigenen Google-Konto an und liest
   und schreibt dieselbe Datei – ein Server dazwischen ist nicht nötig.

   Berechtigung: `drive.file`. Das ist der engste Umfang, den Google anbietet.
   Die Anwendung sieht ausschließlich Dateien, die sie selbst angelegt hat –
   der restliche Drive-Inhalt bleibt für sie unsichtbar.

   Gleichzeitige Änderungen: Drive vergibt für jede Datei eine fortlaufende
   Versionsnummer. Vor dem Schreiben wird geprüft, ob sie noch der erwarteten
   entspricht; andernfalls meldet der Transport einen Konflikt und die
   Zusammenführung in sync.js übernimmt.
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.cloud = (function () {
  const CFG = () => (window.UP_CONFIG || {});
  const CLIENT_KEY = 'urlaubsplaner.googleClientId';
  const FILE_KEY = 'urlaubsplaner.driveFileId';

  const SCOPE = 'https://www.googleapis.com/auth/drive.file';
  const GIS_SRC = 'https://accounts.google.com/gsi/client';

  // Basisadressen sind austauschbar, damit sich die Anbindung ohne
  // Google-Konto gegen einen Nachbau prüfen lässt.
  const apiBase = () => CFG().driveApiBase || 'https://www.googleapis.com/drive/v3';
  const uploadBase = () => CFG().driveUploadBase || 'https://www.googleapis.com/upload/drive/v3';
  const fileName = () => CFG().driveFileName || 'Urlaubsplaner.json';

  let token = null;
  let tokenExpiry = 0;
  let tokenClient = null;
  let fileId = null;
  let account = '';

  /* ── Einrichtung ────────────────────────────────────────────────────── */

  function clientIdValue() {
    if (CFG().googleClientId) return CFG().googleClientId;
    try { return localStorage.getItem(CLIENT_KEY) || ''; } catch (e) { return ''; }
  }

  function setClientId(id) {
    try { localStorage.setItem(CLIENT_KEY, (id || '').trim()); } catch (e) { /* egal */ }
  }

  const configured = () => !!clientIdValue();

  /**
   * Manche Umgebungen können Google grundsätzlich nicht erreichen. Das vorher
   * zu erkennen erspart die zehn Minuten Einrichtung, die dann ins Leere läuft.
   *
   * @returns {'sandbox'|'file'|null}
   */
  function blockedEnvironment() {
    // Direkt geöffnete Dateien haben keine Adresse, die Google zulässt.
    if (location.protocol !== 'http:' && location.protocol !== 'https:') return 'file';
    // Veröffentlichte Seiten auf claude.ai dürfen keine fremden Server rufen.
    if (window.claude || /(^|\.)claudeusercontent\.com$/.test(location.hostname)) return 'sandbox';
    return null;
  }

  function rememberFile(id) {
    fileId = id;
    try { id ? localStorage.setItem(FILE_KEY, id) : localStorage.removeItem(FILE_KEY); }
    catch (e) { /* egal */ }
  }

  function recallFile() {
    try { return localStorage.getItem(FILE_KEY) || null; } catch (e) { return null; }
  }

  /* ── Anmeldung ──────────────────────────────────────────────────────── */

  function loadGis() {
    if (window.google?.accounts?.oauth2) return Promise.resolve();
    if (CFG().fakeGis) return Promise.resolve();          // Prüfbetrieb
    const blocked = blockedEnvironment();
    if (blocked) {
      const err = new Error(blocked === 'sandbox'
        ? 'Diese Ansicht darf keine fremden Server aufrufen – Google Drive ist hier nicht möglich.'
        : 'Direkt geöffnete Dateien lässt Google nicht zu – der Planer muss über eine Adresse laufen.');
      err.blocked = blocked;
      return Promise.reject(err);
    }
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${GIS_SRC}"]`);
      if (existing) { existing.addEventListener('load', resolve); existing.addEventListener('error', reject); return; }
      const s = document.createElement('script');
      s.src = GIS_SRC; s.async = true; s.defer = true;
      s.onload = resolve;
      s.onerror = () => reject(new Error('Die Google-Anmeldung ist nicht erreichbar. Besteht eine Internetverbindung?'));
      document.head.appendChild(s);
    });
  }

  /**
   * Holt ein Zugriffstoken. `interactive: false` versucht es still im
   * Hintergrund – das klappt, solange die Freigabe schon erteilt wurde und
   * das Google-Konto im Browser angemeldet ist.
   */
  function requestToken({ interactive = false } = {}) {
    return new Promise((resolve, reject) => {
      if (!tokenClient) {
        tokenClient = google.accounts.oauth2.initTokenClient({
          client_id: clientIdValue(),
          scope: SCOPE,
          callback: () => {},
        });
      }
      tokenClient.callback = resp => {
        if (resp.error) {
          const err = new UP.sync.AuthError();
          err.detail = resp.error;
          return reject(err);
        }
        token = resp.access_token;
        // Etwas Sicherheitsabstand, damit kein Zugriff mitten im Ablauf scheitert.
        tokenExpiry = Date.now() + (Number(resp.expires_in || 3600) - 90) * 1000;
        resolve(token);
      };
      tokenClient.error_callback = err => {
        const e = new UP.sync.AuthError();
        e.detail = err?.type || 'popup_failed';
        reject(e);
      };
      try {
        tokenClient.requestAccessToken({ prompt: interactive ? 'consent' : '' });
      } catch (e) { reject(e); }
    });
  }

  async function ensureToken({ interactive = false } = {}) {
    if (token && Date.now() < tokenExpiry) return token;
    if (!clientIdValue()) throw new Error('Es ist noch keine Google-Kennung hinterlegt.');
    await loadGis();
    return requestToken({ interactive });
  }

  /** Vom Einrichtungsdialog aufgerufen: bewusst mit Anmeldefenster. */
  async function connectInteractive() {
    token = null; tokenExpiry = 0; tokenClient = null;
    await loadGis();
    await requestToken({ interactive: true });
    await findOrCreateFile();
    return { account, fileId };
  }

  function signOut() {
    try { if (token && window.google?.accounts?.oauth2) google.accounts.oauth2.revoke(token); }
    catch (e) { /* egal */ }
    token = null; tokenExpiry = 0; tokenClient = null;
    rememberFile(null);
  }

  /* ── Drive-Zugriffe ─────────────────────────────────────────────────── */

  async function call(url, opts = {}, { retryAuth = true } = {}) {
    const t = await ensureToken();
    const r = await fetch(url, {
      ...opts,
      headers: { Authorization: `Bearer ${t}`, ...(opts.headers || {}) },
    });
    if (r.status === 401 && retryAuth) {
      token = null; tokenExpiry = 0;
      return call(url, opts, { retryAuth: false });
    }
    if (r.status === 401 || r.status === 403) {
      const err = new UP.sync.AuthError();
      err.detail = await r.text().catch(() => '');
      throw err;
    }
    if (!r.ok) throw new Error(`Drive antwortet mit ${r.status}`);
    return r;
  }

  /** Sucht die Plandatei; legt sie beim ersten Mal an. */
  async function findOrCreateFile() {
    const known = fileId || recallFile();
    if (known) {
      try {
        await call(`${apiBase()}/files/${known}?fields=id,version,trashed`);
        rememberFile(known);
        return known;
      } catch (e) {
        if (e.name === 'AuthError') throw e;
        rememberFile(null);          // gelöscht oder unerreichbar – neu suchen
      }
    }

    const q = encodeURIComponent(`name='${fileName().replace(/'/g, "\\'")}' and trashed=false`);
    const r = await call(`${apiBase()}/files?q=${q}&spaces=drive&fields=files(id,name,version,modifiedTime)&pageSize=10`);
    const found = (await r.json()).files || [];
    if (found.length) { rememberFile(found[0].id); return found[0].id; }

    // Noch nichts da: leere Datei anlegen.
    const body = buildMultipart(
      { name: fileName(), mimeType: 'application/json', description: 'Urlaubsplaner – Plandaten' },
      JSON.stringify({ settings: {}, years: {} })
    );
    const created = await call(`${uploadBase()}/files?uploadType=multipart&fields=id,version`, {
      method: 'POST',
      headers: { 'Content-Type': `multipart/related; boundary=${body.boundary}` },
      body: body.text,
    });
    const info = await created.json();
    rememberFile(info.id);
    return info.id;
  }

  function buildMultipart(metadata, content) {
    const boundary = `up${Math.random().toString(36).slice(2)}`;
    const text =
      `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n` +
      `${JSON.stringify(metadata)}\r\n` +
      `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n` +
      `${content}\r\n--${boundary}--`;
    return { boundary, text };
  }

  async function currentVersion() {
    const r = await call(`${apiBase()}/files/${fileId}?fields=version,modifiedTime,name`);
    const d = await r.json();
    return { rev: Number(d.version), modifiedTime: d.modifiedTime, name: d.name };
  }

  /* ── Transport für sync.js ──────────────────────────────────────────── */

  const transport = {
    id: 'drive',
    label: 'Google Drive',
    pollInterval: 8000,          // sichtbarer Tab
    pollIntervalHidden: 45000,

    async connect() {
      if (!clientIdValue()) throw new Error('Es ist noch keine Google-Kennung hinterlegt.');
      await ensureToken();       // still; scheitert, wenn die Freigabe fehlt
      await findOrCreateFile();
    },

    async load() {
      if (!fileId) await findOrCreateFile();
      const meta = await currentVersion();
      const r = await call(`${apiBase()}/files/${fileId}?alt=media`);
      const text = await r.text();
      let doc;
      try {
        doc = text.trim() ? JSON.parse(text) : { settings: {}, years: {} };
      } catch (e) {
        throw new Error('Die Datei im Drive ist beschädigt und lässt sich nicht lesen.');
      }
      if (!doc || typeof doc !== 'object' || !('years' in doc)) doc = { settings: {}, years: {} };
      return { rev: meta.rev, doc };
    },

    /**
     * Drive kennt kein „nur schreiben, wenn unverändert“. Deshalb wird die
     * Versionsnummer unmittelbar vorher geprüft. Bleibt ein winziges Zeitfenster,
     * in dem zwei Geräte auf die Millisekunde genau schreiben; die nächste
     * Abfrage erkennt das und führt zusammen.
     */
    async save(doc, baseRev) {
      if (!fileId) await findOrCreateFile();
      if (baseRev != null) {
        const before = await currentVersion();
        if (before.rev !== baseRev) {
          const remote = await this.load();
          return { conflict: true, rev: remote.rev, doc: remote.doc };
        }
      }
      await call(`${uploadBase()}/files/${fileId}?uploadType=media&fields=id`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json; charset=UTF-8' },
        body: JSON.stringify(doc),
      });
      const after = await currentVersion();
      return { rev: after.rev };
    },

    /** Drive bietet kein Warten auf Änderungen – also in Abständen nachsehen. */
    async poll(since) {
      const visible = document.visibilityState === 'visible';
      const wait = CFG().drivePollInterval
        ?? (visible ? this.pollInterval : this.pollIntervalHidden);
      await new Promise(r => setTimeout(r, wait));
      if (!fileId) await findOrCreateFile();
      return (await currentVersion()).rev;
    },

    async info() {
      const meta = fileId ? await currentVersion() : { rev: 0, modifiedTime: null, name: fileName() };
      let bytes = 0;
      try {
        const r = await call(`${apiBase()}/files/${fileId}?fields=size,webViewLink,owners(emailAddress)`);
        const d = await r.json();
        bytes = Number(d.size || 0);
        account = d.owners?.[0]?.emailAddress || account;
        meta.link = d.webViewLink;
      } catch (e) { /* Größe ist nur schmückendes Beiwerk */ }

      return {
        rev: meta.rev,
        bytes,
        updatedAt: meta.modifiedTime,
        where: 'Datei im eigenen Google Drive',
        lines: [
          { icon: 'archive', title: 'Datei', value: meta.name },
          { icon: 'user', title: 'Google-Konto', value: account || 'angemeldet' },
          meta.link ? { icon: 'calendar', title: 'Im Drive öffnen', value: meta.link, href: meta.link } : null,
        ].filter(Boolean),
        note: 'Google Drive bewahrt ältere Fassungen der Datei nur begrenzt auf. ' +
              'Für ein dauerhaftes Archiv zusätzlich über das Menü eine Sicherung ablegen.',
      };
    },

    /** Drive führt für jede Datei eigene Revisionen. */
    async history() {
      if (!fileId) return [];
      const r = await call(`${apiBase()}/files/${fileId}/revisions?fields=revisions(id,modifiedTime,size,lastModifyingUser(displayName))&pageSize=100`);
      const list = (await r.json()).revisions || [];
      return list.slice().reverse().map(rev => ({
        rev: rev.id,
        createdAt: rev.modifiedTime,
        client: rev.lastModifyingUser?.displayName || '',
        bytes: Number(rev.size || 0),
      }));
    },

    async restore(revisionId) {
      const r = await call(`${apiBase()}/files/${fileId}/revisions/${revisionId}?alt=media`);
      const doc = JSON.parse(await r.text());
      const out = await this.save(doc, null);    // ohne Versionsprüfung überschreiben
      return { rev: out.rev, doc };
    },

    async logout() {
      signOut();
      UP.sync.useStorage('local');
    },
  };

  return {
    transport, configured, blockedEnvironment, clientIdValue, setClientId,
    connectInteractive, signOut,
    get account() { return account; },
    get fileName() { return fileName(); },
    get fileId() { return fileId || recallFile(); },
  };
})();
