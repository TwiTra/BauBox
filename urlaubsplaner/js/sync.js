/* ═══════════════════════════════════════════════════════════════════════
   sync.js – Abgleich mit dem Server auf dem eigenen Rechner

   Ohne laufenden Server verhält sich der Planer wie bisher: Alles bleibt im
   Browser (localStorage). Ist ein Server erreichbar, gilt dessen Stand als
   maßgeblich; Änderungen werden automatisch gespeichert und andere Geräte
   holen sie innerhalb weniger Sekunden ab.

   Bei gleichzeitigen Änderungen wird zusammengeführt: Grundlage ist der
   zuletzt gemeinsam bestätigte Stand. Was hier geändert wurde, bleibt; was
   dort geändert wurde, kommt dazu. Nur wenn beide Seiten denselben Eintrag
   angefasst haben, gewinnt das Gerät, an dem gerade gearbeitet wird.
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.sync = (function () {
  const U = UP.util, S = UP.store;

  const SYNC_KEY = 'urlaubsplaner.sync';
  const CLIENT_KEY = 'urlaubsplaner.client';
  const PUSH_DELAY = 700;          // ms nach der letzten Änderung
  const POLL_WAIT = 25;            // Sekunden, die der Server offen hält
  const MAX_RETRY = 4;

  let mode = 'local';              // 'local' | 'server'
  let status = 'off';              // off | connecting | synced | saving | offline | unauthorized | error
  let detail = '';
  let serverRev = null;
  let lastSynced = null;           // Stand, auf den sich Client und Server zuletzt geeinigt haben
  let lastSyncedAt = null;
  let pushTimer = null;
  let polling = false;
  let stopped = false;
  let backoff = 1000;
  let clientId = '';

  /* Hochladen und Herunterladen dürfen sich nicht überlappen: beide lesen und
     schreiben denselben Stand. Alles läuft deshalb nacheinander über diese
     Warteschlange. */
  let queue = Promise.resolve();
  function enqueue(fn) {
    const run = () => fn().catch(e => { console.warn('Abgleich:', e.message || e); });
    queue = queue.then(run, run);
    return queue;
  }

  const listeners = [];
  const onStatus = fn => { listeners.push(fn); return () => listeners.splice(listeners.indexOf(fn), 1); };
  const emit = () => listeners.forEach(f => f({ mode, status, detail, rev: serverRev, at: lastSyncedAt }));

  function setStatus(next, text = '') {
    if (status === next && detail === text) return;
    status = next; detail = text;
    emit();
  }

  const ser = o => JSON.stringify(o);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  /* ══ Zusammenführen ═══════════════════════════════════════════════════ */

  /**
   * Drei-Wege-Zusammenführung.
   * @param {Object} base   letzter gemeinsam bestätigter Stand
   * @param {Object} mine   lokaler Stand
   * @param {Object} theirs Stand auf dem Server
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

      if (inB && !inM) continue;                       // hier gelöscht → bleibt gelöscht
      if (inB && !inT && ser(m[y]) === ser(b[y])) continue;  // dort gelöscht, hier unverändert
      if (!inM && inT) { out[y] = t[y]; continue; }    // dort neu angelegt
      if (inM && !inT) { out[y] = m[y]; continue; }    // hier neu angelegt
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
   * Listen von Objekten mit `id`. Reihenfolge richtet sich nach dem lokalen
   * Stand – das ist die zuletzt per Drag & Drop gewählte Sortierung; Einträge,
   * die es nur auf dem Server gibt, werden hinten angehängt.
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

  /* ══ Netzwerk ═════════════════════════════════════════════════════════ */

  async function api(method, path, body, opts = {}) {
    const init = {
      method,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      ...opts,
    };
    if (body) init.body = JSON.stringify(body);
    return fetch(path, init);
  }

  function loadMeta() {
    try {
      const raw = localStorage.getItem(SYNC_KEY);
      if (!raw) return;
      const meta = JSON.parse(raw);
      serverRev = meta.rev ?? null;
      lastSynced = meta.lastSynced ?? null;
      lastSyncedAt = meta.at ?? null;
    } catch (e) { /* unbrauchbar – wird beim ersten Abgleich neu aufgebaut */ }
  }

  function saveMeta() {
    try {
      localStorage.setItem(SYNC_KEY, JSON.stringify({
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
    loadMeta();

    // Direkt geöffnete Dateien haben keinen Server, den man fragen könnte.
    if (location.protocol !== 'http:' && location.protocol !== 'https:') {
      mode = 'local'; setStatus('off'); return false;
    }

    let ping;
    try {
      const r = await api('GET', '/api/ping', null, { cache: 'no-store' });
      if (!r.ok) throw new Error('kein Server');
      ping = await r.json();
    } catch (e) {
      mode = 'local';
      setStatus('off');
      return false;                       // reiner Browser-Betrieb wie bisher
    }
    if (!ping.sync) { mode = 'local'; setStatus('off'); return false; }

    mode = 'server';
    if (ping.authRequired && !ping.auth) { setStatus('unauthorized'); return true; }

    setStatus('connecting');
    S.on('change', payload => { if (!payload || !payload.remote) schedulePush(); });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') { flush(); pullNow(); }
      else flush(true);
    });
    window.addEventListener('online', () => { backoff = 1000; pullNow(); flush(); });
    window.addEventListener('pagehide', () => flush(true));

    await enqueue(firstSync);
    startPolling();
    return true;
  }

  /** Erster Abgleich nach dem Laden: Serverstand holen und zusammenführen. */
  async function firstSync() {
    try {
      const r = await api('GET', '/api/state', null, { cache: 'no-store' });
      if (r.status === 401) return setStatus('unauthorized');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const server = await r.json();
      const local = S.doc();
      const localEmpty = !Object.keys(local.years || {}).some(y => hasContent(local.years[y]));
      const serverEmpty = !Object.keys(server.doc.years || {}).some(y => hasContent(server.doc.years[y]));

      serverRev = server.rev;

      if (serverEmpty && !localEmpty) {
        // Erster Start mit Server: den vorhandenen Browser-Plan hochladen.
        lastSynced = server.doc;
        saveMeta();
        await doPush(true);
        UP.app?.toast('ok', 'Plan auf den Server übertragen – ab jetzt von überall erreichbar.');
        return;
      }

      if (localEmpty || !lastSynced) {
        apply(server.doc);
        lastSynced = server.doc;
      } else {
        const merged = mergeDoc(lastSynced, local, server.doc);
        apply(merged);
        lastSynced = server.doc;
        if (ser(merged) !== ser(server.doc)) { saveMeta(); return doPush(true); }
      }
      lastSyncedAt = Date.now();
      saveMeta();
      setStatus('synced');
    } catch (e) {
      setStatus('offline', e.message);
    }
  }

  const hasContent = y => y && ((y.people || []).length || (y.departments || []).length || (y.absences || []).length);

  /** Übernimmt einen Stand, sofern er sich vom aktuellen unterscheidet. */
  function apply(next) {
    if (ser(S.doc()) === ser(next)) return false;
    S.replaceDoc(next);
    return true;
  }

  /* ══ Hochladen ════════════════════════════════════════════════════════ */

  function schedulePush(delay = PUSH_DELAY) {
    if (mode !== 'server' || stopped) return;
    if (status !== 'offline' && status !== 'unauthorized') setStatus('saving');
    clearTimeout(pushTimer);
    pushTimer = setTimeout(() => { pushTimer = null; enqueue(() => doPush()); }, delay);
  }

  /** Wartende Änderung sofort losschicken (Tab wird ausgeblendet/geschlossen). */
  function flush(keepalive = false) {
    if (mode !== 'server' || !pushTimer) return;
    clearTimeout(pushTimer); pushTimer = null;
    enqueue(() => doPush(false, keepalive));
  }

  async function doPush(force = false, keepalive = false, attempt = 0) {
    if (mode !== 'server' || stopped) return;

    const doc = S.doc();
    if (!force && lastSynced && ser(doc) === ser(lastSynced)) {
      setStatus('synced');
      return;
    }

    try {
      const r = await api('PUT', '/api/state',
        { baseRev: serverRev, doc, client: clientId },
        keepalive ? { keepalive: true } : {});

      if (r.status === 401) { setStatus('unauthorized'); return; }

      if (r.status === 409) {
        // Ein anderes Gerät war schneller: zusammenführen und erneut senden.
        const server = await r.json();
        const merged = mergeDoc(lastSynced, doc, server.doc);
        serverRev = server.rev;
        lastSynced = server.doc;
        const changed = apply(merged);
        saveMeta();
        if (attempt >= MAX_RETRY) {
          setStatus('error', 'Abgleich mehrfach unterbrochen');
          return;
        }
        if (changed) UP.app?.toast('info', 'Änderungen von einem anderen Gerät übernommen.');
        return doPush(true, false, attempt + 1);
      }

      if (!r.ok) throw new Error(`HTTP ${r.status}`);

      const out = await r.json();
      serverRev = out.rev;
      lastSynced = doc;
      lastSyncedAt = Date.now();
      saveMeta();
      backoff = 1000;
      setStatus('synced');
    } catch (e) {
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
    if (mode !== 'server') return;
    const r = await api('GET', '/api/state', null, { cache: 'no-store' });
    if (r.status === 401) { setStatus('unauthorized'); return; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const server = await r.json();
    if (server.rev === serverRev) return;

    const local = S.doc();
    const localClean = lastSynced && ser(local) === ser(lastSynced);

    serverRev = server.rev;
    if (localClean) {
      const changed = apply(server.doc);
      lastSynced = server.doc;
      lastSyncedAt = Date.now();
      saveMeta();
      setStatus('synced');
      if (changed) UP.app?.toast('info', 'Der Plan wurde auf einem anderen Gerät geändert.', { duration: 2600 });
    } else {
      const merged = mergeDoc(lastSynced, local, server.doc);
      lastSynced = server.doc;
      apply(merged);
      saveMeta();
      UP.app?.toast('info', 'Änderungen von einem anderen Gerät zusammengeführt.');
      schedulePush(120);
    }
  }

  function pullNow() {
    return enqueue(async () => {
      try { await doPull(); } catch (e) { setStatus('offline'); }
    });
  }

  /** Wartende Abfrage: der Server antwortet, sobald sich etwas ändert. */
  async function startPolling() {
    if (polling) return;
    polling = true;
    while (!stopped && mode === 'server') {
      if (status === 'unauthorized') { await sleep(5000); continue; }
      try {
        const r = await api('GET', `/api/rev?since=${serverRev ?? -1}&wait=${POLL_WAIT}`,
          null, { cache: 'no-store' });
        if (r.status === 401) { setStatus('unauthorized'); await sleep(4000); continue; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const { rev } = await r.json();
        backoff = 1000;
        if (status === 'offline') {
          // Verbindung ist zurück: erst Wartendes hochladen, dann abholen.
          setStatus('synced');
          await enqueue(() => doPush());
        }
        if (rev !== serverRev) await enqueue(doPull);
      } catch (e) {
        setStatus('offline');
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 30000);
      }
    }
    polling = false;
  }

  /* ══ Fassungen ════════════════════════════════════════════════════════ */

  async function history() {
    const r = await api('GET', '/api/history');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return (await r.json()).entries;
  }

  function restore(rev) {
    let result;
    return enqueue(async () => {
      const r = await api('POST', '/api/restore', { rev });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const out = await r.json();
      serverRev = out.rev;
      lastSynced = out.doc;
      apply(out.doc);
      lastSyncedAt = Date.now();
      saveMeta();
      setStatus('synced');
      result = out.rev;
    }).then(() => result);
  }

  async function info() {
    const r = await api('GET', '/api/info');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function logout() {
    await api('POST', '/api/logout');
    location.href = '/login';
  }

  /* ══ Öffentlich ═══════════════════════════════════════════════════════ */

  return {
    init, onStatus, history, restore, info, logout,
    pullNow, flush,
    push: () => enqueue(() => doPush(true)),
    get mode() { return mode; },
    get status() { return status; },
    get rev() { return serverRev; },
    get lastSyncedAt() { return lastSyncedAt; },
    get clientId() { return clientId; },
    // für Tests einsehbar
    _merge: mergeDoc,
  };
})();
