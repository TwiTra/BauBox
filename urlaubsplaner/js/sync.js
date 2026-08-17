/* ═══════════════════════════════════════════════════════════════════════
   sync.js – Abgleich des Plans über verschiedene Speicherorte

   Der Planer kennt drei Speicherorte:

     lokal   nur dieser Browser (localStorage) – Voreinstellung, keine Einrichtung
     server  ein laufender server.py auf dem eigenen Rechner
     drive   eine Datei im eigenen Google Drive (siehe cloud.js)

   Die Abgleichlogik ist für alle gleich und steckt hier; der Weg zum Speicher
   steckt in austauschbaren „Transporten“. Bei gleichzeitigen Änderungen wird
   zusammengeführt: Grundlage ist der zuletzt gemeinsam bestätigte Stand. Was
   hier geändert wurde, bleibt; was dort geändert wurde, kommt dazu. Nur wenn
   beide Seiten denselben Eintrag angefasst haben, gewinnt das Gerät, an dem
   gerade gearbeitet wird.
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.sync = (function () {
  const U = UP.util, S = UP.store;

  const SYNC_KEY = 'urlaubsplaner.sync';
  const CLIENT_KEY = 'urlaubsplaner.client';
  const STORAGE_KEY = 'urlaubsplaner.storage';
  const PUSH_DELAY = 700;
  const MAX_RETRY = 4;

  let transport = null;            // null = rein lokal
  let status = 'off';              // off | connecting | synced | saving | offline | unauthorized | error
  let detail = '';
  let serverRev = null;
  let lastSynced = null;
  let lastSyncedAt = null;
  let pushTimer = null;
  let polling = false;
  let stopped = false;
  let backoff = 1000;
  let clientId = '';

  const listeners = [];
  const onStatus = fn => { listeners.push(fn); return () => listeners.splice(listeners.indexOf(fn), 1); };
  const emit = () => listeners.forEach(f => f(snapshot()));
  const snapshot = () => ({
    mode: transport ? transport.id : 'local',
    label: transport ? transport.label : 'Nur dieser Browser',
    status, detail, rev: serverRev, at: lastSyncedAt,
  });

  function setStatus(next, text = '') {
    if (status === next && detail === text) return;
    status = next; detail = text;
    emit();
  }

  const ser = o => JSON.stringify(o);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  /* Hochladen und Herunterladen dürfen sich nicht überlappen: beide lesen und
     schreiben denselben Stand. Alles läuft deshalb nacheinander. */
  let queue = Promise.resolve();
  function enqueue(fn) {
    const run = () => fn().catch(e => { console.warn('Abgleich:', e.message || e); });
    queue = queue.then(run, run);
    return queue;
  }

  /* ══ Zusammenführen ═══════════════════════════════════════════════════ */

  /**
   * Drei-Wege-Zusammenführung.
   * @param {Object} base   letzter gemeinsam bestätigter Stand
   * @param {Object} mine   lokaler Stand
   * @param {Object} theirs Stand am Speicherort
   */
  function mergeDoc(base, mine, theirs) {
    base = base || { settings: {}, years: {} };
    return {
      settings: mergeFlat(base.settings || {}, mine.settings || {}, theirs.settings || {}),
      years: mergeYears(base.years || {}, mine.years || {}, theirs.years || {}),
    };
  }

  /** Einfache Schlüssel/Wert-Paare: lokale Änderung schlägt die entfernte. */
  function mergeFlat(b, m, t) {
    const out = { ...t };
    for (const k of new Set([...Object.keys(b), ...Object.keys(m), ...Object.keys(t)])) {
      const changedHere = ser(m[k]) !== ser(b[k]);
      if (!changedHere) continue;
      if (k in m) out[k] = m[k]; else delete out[k];
    }
    return out;
  }

  function mergeYears(b, m, t) {
    const out = {};
    for (const y of new Set([...Object.keys(b), ...Object.keys(m), ...Object.keys(t)])) {
      const inB = y in b, inM = y in m, inT = y in t;

      if (inB && !inM) continue;                             // hier gelöscht
      if (inB && !inT && ser(m[y]) === ser(b[y])) continue;   // dort gelöscht, hier unverändert
      if (!inM && inT) { out[y] = t[y]; continue; }            // dort neu angelegt
      if (inM && !inT) { out[y] = m[y]; continue; }            // hier neu angelegt
      out[y] = mergeYear(inB ? b[y] : null, m[y], t[y]);
    }
    return out;
  }

  function mergeYear(b, m, t) {
    b = b || { departments: [], people: [], absences: [], closures: [] };
    return {
      locked: ser(m.locked) !== ser(b.locked) ? m.locked : t.locked,
      departments: mergeById(b.departments, m.departments, t.departments),
      people: mergeById(b.people, m.people, t.people),
      absences: mergeById(b.absences, m.absences, t.absences),
      closures: mergeById(b.closures, m.closures, t.closures),
    };
  }

  /**
   * Listen von Objekten mit `id`. Die Reihenfolge richtet sich nach dem lokalen
   * Stand – das ist die zuletzt per Drag & Drop gewählte Sortierung; Einträge,
   * die es nur am Speicherort gibt, werden hinten angehängt.
   */
  function mergeById(b = [], m = [], t = []) {
    const map = arr => new Map((arr || []).map(x => [x.id, x]));
    const B = map(b), M = map(m), T = map(t);
    const out = [];
    const taken = new Set();

    const decide = id => {
      const inB = B.has(id), inM = M.has(id), inT = T.has(id);
      if (inB && !inM) return null;                                   // hier gelöscht
      if (!inM && inT) return T.get(id);                              // dort neu
      if (inM && !inT) {
        if (!inB) return M.get(id);                                   // hier neu
        return ser(M.get(id)) !== ser(B.get(id)) ? M.get(id) : null;  // dort gelöscht
      }
      if (!inM) return null;
      if (inB && ser(M.get(id)) === ser(B.get(id))) return T.get(id);  // hier unverändert
      return M.get(id);                                                // hier geändert
    };

    for (const item of (m || [])) {
      const keep = decide(item.id);
      taken.add(item.id);
      if (keep) out.push(keep);
    }
    for (const item of (t || [])) {
      if (taken.has(item.id)) continue;
      taken.add(item.id);
      const keep = decide(item.id);
      if (keep) out.push(keep);
    }
    return out;
  }

  /* ══ Transport: eigener Server (server.py) ════════════════════════════ */

  const serverTransport = {
    id: 'server',
    label: 'Eigener Server',
    pollWait: 25,

    async available() {
      if (location.protocol !== 'http:' && location.protocol !== 'https:') return false;
      try {
        const r = await fetch('/api/ping', { credentials: 'same-origin', cache: 'no-store' });
        if (!r.ok) return false;
        const ping = await r.json();
        if (!ping.sync) return false;
        this.authRequired = ping.authRequired;
        this.authed = ping.auth;
        return true;
      } catch (e) { return false; }
    },

    needsLogin() { return this.authRequired && !this.authed; },
    loginUrl: '/login',

    async load() {
      const r = await fetch('/api/state', { credentials: 'same-origin', cache: 'no-store' });
      if (r.status === 401) throw new AuthError();
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const out = await r.json();
      return { rev: out.rev, doc: out.doc };
    },

    async save(doc, baseRev, { keepalive = false } = {}) {
      const r = await fetch('/api/state', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ baseRev, doc, client: clientId }),
        ...(keepalive ? { keepalive: true } : {}),
      });
      if (r.status === 401) throw new AuthError();
      if (r.status === 409) {
        const out = await r.json();
        return { conflict: true, rev: out.rev, doc: out.doc };
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return { rev: (await r.json()).rev };
    },

    /** Der Server hält die Anfrage offen, bis sich etwas ändert. */
    async poll(since) {
      const r = await fetch(`/api/rev?since=${since ?? -1}&wait=${this.pollWait}`,
        { credentials: 'same-origin', cache: 'no-store' });
      if (r.status === 401) throw new AuthError();
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return (await r.json()).rev;
    },

    async info() {
      const r = await fetch('/api/info', { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      return {
        ...d,
        where: 'Datenbank auf dem eigenen Rechner',
        lines: [
          { icon: 'archive', title: 'Datenbank', value: d.database },
          { icon: 'copy', title: `Tägliche Sicherungen (${d.backups.length || 'noch keine'})`, value: d.backupDir },
        ],
        exportUrl: '/api/export',
      };
    },

    async history() {
      const r = await fetch('/api/history', { credentials: 'same-origin' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return (await r.json()).entries;
    },

    async restore(rev) {
      const r = await fetch('/api/restore', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rev }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const out = await r.json();
      return { rev: out.rev, doc: out.doc };
    },

    async logout() {
      await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' });
      location.href = '/login';
    },
  };

  class AuthError extends Error {
    constructor() { super('Anmeldung erforderlich'); this.name = 'AuthError'; }
  }

  /* ══ Speicherort wählen ═══════════════════════════════════════════════ */

  const readPref = () => { try { return localStorage.getItem(STORAGE_KEY) || 'auto'; } catch (e) { return 'auto'; } };
  const writePref = v => { try { localStorage.setItem(STORAGE_KEY, v); } catch (e) { /* egal */ } };

  /** Wechselt den Speicherort und lädt die Seite neu. */
  async function useStorage(kind) {
    writePref(kind);
    // Der zuletzt bestätigte Stand gilt nur für den alten Speicherort.
    try { localStorage.removeItem(SYNC_KEY); } catch (e) { /* egal */ }
    location.reload();
  }

  function loadMeta() {
    try {
      const raw = localStorage.getItem(SYNC_KEY);
      if (!raw) return;
      const meta = JSON.parse(raw);
      if (meta.transport && transport && meta.transport !== transport.id) return;
      serverRev = meta.rev ?? null;
      lastSynced = meta.lastSynced ?? null;
      lastSyncedAt = meta.at ?? null;
    } catch (e) { /* unbrauchbar – wird beim ersten Abgleich neu aufgebaut */ }
  }

  function saveMeta() {
    try {
      localStorage.setItem(SYNC_KEY, JSON.stringify({
        transport: transport ? transport.id : null,
        rev: serverRev, lastSynced, at: lastSyncedAt,
      }));
    } catch (e) { /* Speicher voll: der nächste Abgleich gleicht das aus */ }
  }

  function getClientId() {
    try {
      let id = localStorage.getItem(CLIENT_KEY);
      if (!id) {
        id = `${deviceName()}-${Math.random().toString(36).slice(2, 6)}`;
        localStorage.setItem(CLIENT_KEY, id);
      }
      return id;
    } catch (e) { return 'gerät'; }
  }

  function deviceName() {
    const ua = navigator.userAgent;
    if (/iPhone|iPod/.test(ua)) return 'iPhone';
    if (/iPad/.test(ua)) return 'iPad';
    if (/Android/.test(ua)) return 'Android';
    if (/Macintosh/.test(ua)) return 'Mac';
    if (/Windows/.test(ua)) return 'Windows';
    if (/Linux/.test(ua)) return 'Linux';
    return 'Browser';
  }

  /* ══ Start ════════════════════════════════════════════════════════════ */

  async function init() {
    clientId = getClientId();
    const pref = readPref();

    if (pref === 'local') { transport = null; setStatus('off'); emit(); return false; }

    // Google Drive nur, wenn ausdrücklich gewählt und eingerichtet.
    if (pref === 'drive' && UP.cloud?.configured()) {
      transport = UP.cloud.transport;
      loadMeta();
      setStatus('connecting');
      emit();
      try {
        await transport.connect();
      } catch (e) {
        setStatus(e.name === 'AuthError' ? 'unauthorized' : 'offline', e.message);
        wire();
        startPolling();
        return true;
      }
    } else if (pref === 'auto' || pref === 'server') {
      if (await serverTransport.available()) {
        transport = serverTransport;
        if (serverTransport.needsLogin()) { setStatus('unauthorized'); emit(); return true; }
        setStatus('connecting');
      }
    }

    if (!transport) { setStatus('off'); emit(); return false; }

    loadMeta();
    wire();
    await enqueue(firstSync);
    startPolling();
    return true;
  }

  function wire() {
    S.on('change', payload => { if (!payload || !payload.remote) schedulePush(); });

    /* Beim Wegschalten oder Schließen des Tabs wird nicht auf den Zeitgeber
       gewartet, sondern sofort gespeichert. Browser lösen „hidden“ aus, bevor
       die Seite abgebaut wird – in dieser Phase bleibt genug Zeit für den
       vollständigen, konfliktsicheren Ablauf. */
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') { flush(); pullNow(); }
      else leaving();
    });
    window.addEventListener('pagehide', leaving);
    window.addEventListener('online', () => { backoff = 1000; pullNow(); flush(); });

    /* Letzte Rückversicherung: Ist beim Schließen wirklich noch etwas offen –
       etwa weil die Verbindung steht oder der Upload nicht mehr durchkam –
       fragt der Browser nach. Verloren ist dabei nichts: Der Stand liegt im
       Browser-Speicher und geht beim nächsten Öffnen automatisch hinaus. */
    window.addEventListener('beforeunload', e => {
      S.flushPersist();
      if (!saveNow()) return;
      e.preventDefault();
      e.returnValue = '';
    });
  }

  /** Gibt es Änderungen, die der Speicherort noch nicht hat? */
  const hasUnsaved = () => !!transport && (!lastSynced || ser(S.doc()) !== ser(lastSynced));

  /** Seite wird verlassen: Browser-Speicher sofort schreiben und hochladen. */
  function leaving() {
    S.flushPersist();
    saveNow();
  }

  /**
   * Schickt Wartendes unverzüglich los – anders als `flush()` auch dann, wenn
   * gerade kein Zeitgeber läuft.
   * @returns {boolean} true, wenn tatsächlich etwas offen war
   */
  function saveNow(keepalive = true) {
    if (!transport || stopped) return false;
    clearTimeout(pushTimer); pushTimer = null;
    if (!hasUnsaved()) return false;
    enqueue(() => doPush(true, keepalive));
    return true;
  }

  /** Erster Abgleich nach dem Laden: Stand holen und zusammenführen. */
  async function firstSync() {
    try {
      const remote = await transport.load();
      const local = S.doc();
      const localEmpty = !Object.keys(local.years || {}).some(y => hasContent(local.years[y]));
      const remoteEmpty = !remote.doc || !Object.keys(remote.doc.years || {})
        .some(y => hasContent(remote.doc.years[y]));

      serverRev = remote.rev;

      if (remoteEmpty && !localEmpty) {
        // Erstes Mal an diesem Speicherort: den vorhandenen Plan hochladen.
        lastSynced = remote.doc || { settings: {}, years: {} };
        saveMeta();
        await doPush(true);
        UP.app?.toast('ok', `Plan nach „${transport.label}“ übertragen.`);
        return;
      }

      if (localEmpty || !lastSynced) {
        apply(remote.doc);
        lastSynced = remote.doc;
      } else {
        const merged = mergeDoc(lastSynced, local, remote.doc);
        apply(merged);
        lastSynced = remote.doc;
        if (ser(merged) !== ser(remote.doc)) { saveMeta(); return doPush(true); }
      }
      lastSyncedAt = Date.now();
      saveMeta();
      setStatus('synced');
    } catch (e) {
      setStatus(e.name === 'AuthError' ? 'unauthorized' : 'offline', e.message);
    }
  }

  const hasContent = y => y && ((y.people || []).length || (y.departments || []).length || (y.absences || []).length);

  /** Übernimmt einen Stand, sofern er sich vom aktuellen unterscheidet. */
  function apply(next) {
    if (!next || ser(S.doc()) === ser(next)) return false;
    S.replaceDoc(next);
    return true;
  }

  /* ══ Hochladen ════════════════════════════════════════════════════════ */

  function schedulePush(delay = PUSH_DELAY) {
    if (!transport || stopped) return;
    if (status !== 'offline' && status !== 'unauthorized') setStatus('saving');
    clearTimeout(pushTimer);
    pushTimer = setTimeout(() => { pushTimer = null; enqueue(() => doPush()); }, delay);
  }

  /** Wartende Änderung sofort losschicken (Tab wird ausgeblendet/geschlossen). */
  function flush(keepalive = false) {
    if (!transport || !pushTimer) return;
    clearTimeout(pushTimer); pushTimer = null;
    enqueue(() => doPush(false, keepalive));
  }

  async function doPush(force = false, keepalive = false, attempt = 0) {
    if (!transport || stopped) return;

    const doc = S.doc();
    if (!force && lastSynced && ser(doc) === ser(lastSynced)) { setStatus('synced'); return; }

    try {
      const out = await transport.save(doc, serverRev, { keepalive });

      if (out.conflict) {
        // Ein anderes Gerät war schneller: zusammenführen und erneut senden.
        const merged = mergeDoc(lastSynced, doc, out.doc);
        serverRev = out.rev;
        lastSynced = out.doc;
        const changed = apply(merged);
        saveMeta();
        if (attempt >= MAX_RETRY) { setStatus('error', 'Abgleich mehrfach unterbrochen'); return; }
        if (changed) UP.app?.toast('info', 'Änderungen von einem anderen Gerät übernommen.');
        return doPush(true, false, attempt + 1);
      }

      serverRev = out.rev;
      lastSynced = doc;
      lastSyncedAt = Date.now();
      saveMeta();
      backoff = 1000;
      setStatus('synced');
    } catch (e) {
      if (e.name === 'AuthError') { setStatus('unauthorized', e.message); return; }
      // Kein Datenverlust: der Stand liegt weiterhin im Browser.
      setStatus('offline');
      if (!stopped) {
        clearTimeout(pushTimer);
        pushTimer = setTimeout(() => { pushTimer = null; enqueue(() => doPush()); }, backoff);
        backoff = Math.min(backoff * 2, 30000);
      }
    }
  }

  /* ══ Herunterladen ════════════════════════════════════════════════════ */

  async function doPull() {
    if (!transport) return;
    const remote = await transport.load();
    if (remote.rev === serverRev) return;

    const local = S.doc();
    const localClean = lastSynced && ser(local) === ser(lastSynced);

    serverRev = remote.rev;
    if (localClean) {
      const changed = apply(remote.doc);
      lastSynced = remote.doc;
      lastSyncedAt = Date.now();
      saveMeta();
      setStatus('synced');
      if (changed) UP.app?.toast('info', 'Der Plan wurde auf einem anderen Gerät geändert.', { duration: 2600 });
    } else {
      const merged = mergeDoc(lastSynced, local, remote.doc);
      lastSynced = remote.doc;
      apply(merged);
      saveMeta();
      UP.app?.toast('info', 'Änderungen von einem anderen Gerät zusammengeführt.');
      schedulePush(120);
    }
  }

  function pullNow() {
    return enqueue(async () => {
      try { await doPull(); }
      catch (e) { setStatus(e.name === 'AuthError' ? 'unauthorized' : 'offline'); }
    });
  }

  /**
   * Fragt den Speicherort nach Änderungen. Der eigene Server hält die Anfrage
   * offen, bis etwas passiert; Google Drive wird in Abständen gefragt.
   */
  async function startPolling() {
    if (polling) return;
    polling = true;
    while (!stopped && transport) {
      if (status === 'unauthorized') { await sleep(5000); continue; }
      try {
        const rev = await transport.poll(serverRev);
        backoff = 1000;
        if (status === 'offline') { setStatus('synced'); await enqueue(() => doPush()); }
        if (rev !== serverRev) await enqueue(doPull);
      } catch (e) {
        if (e.name === 'AuthError') { setStatus('unauthorized'); await sleep(4000); continue; }
        setStatus('offline');
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 30000);
      }
    }
    polling = false;
  }

  /* ══ Fassungen ════════════════════════════════════════════════════════ */

  const history = () => (transport?.history ? transport.history() : Promise.resolve([]));
  const info = () => (transport?.info ? transport.info() : Promise.resolve(null));

  function restore(rev) {
    let result;
    return enqueue(async () => {
      const out = await transport.restore(rev);
      serverRev = out.rev;
      lastSynced = out.doc;
      apply(out.doc);
      lastSyncedAt = Date.now();
      saveMeta();
      setStatus('synced');
      result = out.rev;
    }).then(() => result);
  }

  async function logout() {
    if (transport?.logout) return transport.logout();
  }

  /* ══ Öffentlich ═══════════════════════════════════════════════════════ */

  return {
    init, onStatus, history, restore, info, logout,
    pullNow, flush, saveNow, hasUnsaved, useStorage, readPref,
    push: () => enqueue(() => doPush(true)),
    AuthError,
    get transport() { return transport; },
    get mode() { return transport ? transport.id : 'local'; },
    get label() { return transport ? transport.label : 'Nur dieser Browser'; },
    get status() { return status; },
    get rev() { return serverRev; },
    get lastSyncedAt() { return lastSyncedAt; },
    get clientId() { return clientId; },
    _merge: mergeDoc,
  };
})();
