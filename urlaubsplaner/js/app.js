/* ═══════════════════════════════════════════════════════════════════════
   app.js – Steuerung, Dialoge, Import/Export, Tastaturbedienung
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.app = (function () {
  const U = UP.util, S = UP.store;
  const { el, $, $$ } = U;

  const VIEWS = {
    jahr:      { label: 'Jahr',              mod: () => UP.views.jahr },
    monat:     { label: 'Monat',             mod: () => UP.views.monat },
    konflikte: { label: 'Überschneidungen',  mod: () => UP.views.konflikte },
    team:      { label: 'Team',              mod: () => UP.views.team },
    statistik: { label: 'Statistik',         mod: () => UP.views.statistik },
  };

  let host, toolbarEl, hovercardEl;

  /* ═══ Start ═════════════════════════════════════════════════════════ */
  function init() {
    host = $('#viewHost');
    toolbarEl = $('#toolbar');
    hovercardEl = $('#hovercard');

    S.load();
    applyTheme();
    wireTopbar();
    wireKeyboard();

    S.on('change', () => render());
    S.on('storage-error', () =>
      toast('danger', 'Speichern nicht möglich – der Browser-Speicher ist voll oder gesperrt.'));

    render();

    // Abgleich mit dem Server, falls einer läuft. Ohne Server bleibt alles
    // wie bisher rein im Browser.
    $('#syncChip').onclick = openSyncPanel;
    UP.sync.onStatus(updateSyncChip);
    UP.sync.init().catch(err => console.warn('Abgleich nicht möglich', err));
  }

  /* ═══ Abgleich-Anzeige ══════════════════════════════════════════════ */
  const SYNC_LABEL = {
    off:          { text: '', cls: '', hint: '' },
    connecting:   { text: 'Verbinden…', cls: 'is-saving', hint: 'Die Verbindung zum Speicherort wird aufgebaut.' },
    saving:       { text: 'Speichert…', cls: 'is-saving', hint: 'Die Änderung wird gerade gespeichert.' },
    synced:       { text: 'Gespeichert', cls: 'is-synced', hint: 'Alle Änderungen sind gesichert.' },
    offline:      { text: 'Offline', cls: 'is-offline', hint: 'Der Speicherort ist nicht erreichbar. Die Änderungen liegen im Browser und werden nachgetragen, sobald die Verbindung wieder steht.' },
    unauthorized: { text: 'Anmelden', cls: 'is-error', hint: 'Die Anmeldung ist abgelaufen oder fehlt.' },
    error:        { text: 'Fehler', cls: 'is-error', hint: 'Der Abgleich wurde mehrfach unterbrochen.' },
  };

  function updateSyncChip(st) {
    const chip = $('#syncChip');
    if (!chip) return;
    if (st.mode === 'local') { chip.hidden = true; return; }
    const info = SYNC_LABEL[st.status] || SYNC_LABEL.connecting;
    chip.hidden = false;
    chip.className = 'sync-chip ' + info.cls;
    chip.querySelector('.sync-text').textContent = info.text;
    chip.title = `${st.label}\n${info.hint}` +
      (st.rev != null ? `\nFassung ${st.rev}` : '') + '\nKlick zeigt Details';
    chip.onclick = st.status === 'unauthorized' ? reconnect : openSyncPanel;
  }

  /** „Anmelden“ in der Statusanzeige – je nach Speicherort verschieden. */
  async function reconnect() {
    if (UP.sync.mode === 'server') { location.href = '/login'; return; }
    if (UP.sync.mode === 'drive') {
      try {
        await UP.cloud.connectInteractive();
        toast('ok', 'Wieder mit Google Drive verbunden.');
        UP.sync.pullNow();
      } catch (e) {
        toast('danger', `Anmeldung fehlgeschlagen: ${e.detail || e.message}`);
      }
    }
  }

  /* ═══ Dialog: Speicherort wählen ════════════════════════════════════ */
  function openStorageDialog() {
    const current = UP.sync.mode;
    const pref = UP.sync.readPref();
    const serverAvailable = current === 'server';

    const option = (kind, icon, title, desc, extra) => {
      const active = current === kind || (kind === 'local' && current === 'local');
      return el('div.mrow', {
        style: {
          cursor: 'pointer', alignItems: 'flex-start', padding: '13px',
          borderColor: active ? 'var(--primary)' : null,
          background: active ? 'var(--primary-soft)' : null,
        },
        onclick: () => choose(kind),
      },
        el('span', {
          html: U.icon(icon, 18),
          style: { color: active ? 'var(--primary)' : 'var(--faint)', marginTop: '2px' },
        }),
        el('div.mrow-main', {},
          el('div.mrow-title', {}, title,
            active ? el('span.tag.info', { style: { marginLeft: '8px' } }, 'aktiv') : null),
          el('div.mrow-sub', { style: { lineHeight: '1.5' } }, desc),
          extra || null));
    };

    async function choose(kind) {
      if (kind === current) return;
      if (kind === 'drive') { m.close(); return openDriveSetup(); }
      if (kind === 'server' && !serverAvailable) {
        return toast('warn', 'Es läuft gerade kein eigener Server. Starte ihn mit „python server.py“ und öffne die Adresse, die dabei angezeigt wird.');
      }
      const ok = await confirmBox({
        title: 'Speicherort wechseln?',
        text: 'Der Planer lädt danach neu und arbeitet mit dem Stand des neuen Speicherorts. ' +
              'Sichere vorher über das Menü, wenn du unsicher bist.',
        okLabel: 'Wechseln',
      });
      if (ok) UP.sync.useStorage(kind);
    }

    const m = modal({
      title: 'Speicherort',
      sub: `derzeit: ${UP.sync.label}`,
      body: el('div', {},
        el('div.mlist', {},
          option('local', 'user', 'Nur dieser Browser',
            'Der Plan bleibt auf diesem Gerät. Keine Einrichtung nötig, funktioniert ohne Internet. ' +
            'Andere Geräte sehen ihn nicht.'),
          option('server', 'building', 'Eigener Server auf dem PC',
            'Der Plan liegt in einer Datenbank auf deinem Rechner und ist über einen Link erreichbar, ' +
            'solange der Rechner läuft. Start mit „python server.py --tunnel“.',
            serverAvailable ? null : el('div.small', {
              style: { color: 'var(--warn)', marginTop: '5px' },
            }, 'Zurzeit nicht erreichbar – der Server läuft nicht oder du hast die Seite anders geöffnet.')),
          option('drive', 'archive', 'Google Drive',
            'Der Plan liegt als eine Datei in deinem eigenen Google Drive. Alle Geräte greifen darauf zu, ' +
            'der PC muss dafür nicht laufen.',
            UP.cloud.configured()
              ? null
              : el('div.small', { style: { color: 'var(--muted)', marginTop: '5px' } },
                'Einmalige Einrichtung nötig – der Planer führt dich durch.'))),

        el('div.note-box', { style: { marginTop: '16px' } },
          el('span.ico', { html: U.icon('info', 15) }),
          el('div', {}, el('b', {}, 'Ein Wechsel löscht nichts. '),
            'Der Plan bleibt an beiden Orten liegen. Ist der neue Speicherort noch leer, wird der ' +
            'aktuelle Plan dorthin übertragen; hat er schon Daten, werden beide zusammengeführt.'))),
      footer: [
        el('div.spacer'),
        el('button.primary-btn', { text: 'Schließen', onclick: () => m.close() }),
      ],
    });
  }

  /* ═══ Dialog: Google Drive einrichten ═══════════════════════════════ */
  function openDriveSetup() {
    const idInput = el('input', {
      type: 'text', value: UP.cloud.clientIdValue(),
      placeholder: '1234567890-abc….apps.googleusercontent.com',
      spellcheck: 'false',
    });
    const statusBox = el('div');

    const step = (n, title, body) => el('div.mrow', { style: { alignItems: 'flex-start' } },
      el('div', {
        style: {
          width: '24px', height: '24px', borderRadius: '7px', flex: '0 0 auto',
          display: 'grid', placeItems: 'center', background: 'var(--primary-soft)',
          color: 'var(--primary)', fontWeight: '800', fontSize: '11.5px', marginTop: '1px',
        },
      }, n),
      el('div.mrow-main', {},
        el('div.mrow-title', {}, title),
        el('div.mrow-sub', { style: { lineHeight: '1.55' } }, body)));

    const m = modal({
      title: 'Google Drive einrichten',
      sub: 'einmalig, danach auf jedem Gerät nur noch anmelden',
      size: 'wide',
      body: el('div', {},
        el('div.note-box', {},
          el('span.ico', { html: U.icon('info', 15) }),
          el('div', {}, 'Damit der Planer auf dein Drive zugreifen darf, braucht er eine ' +
            'Zugangskennung, die du dir in der Google Cloud Console selbst ausstellst. ' +
            'Das ist kostenlos und dauert etwa zehn Minuten. Die ausführliche Anleitung mit ' +
            'allen Klickwegen steht in der Datei ',
            el('span.mono', {}, 'CLOUD-EINRICHTEN.md'), '.')),

        el('div.sec-title', { style: { marginTop: '18px' } }, 'Kurzfassung'),
        el('div.mlist', {},
          step('1', 'Projekt anlegen',
            el('span', {}, 'Auf ', el('span.mono', {}, 'console.cloud.google.com'),
              ' anmelden und oben ein neues Projekt anlegen, z. B. „Urlaubsplaner“.')),
          step('2', 'Drive-API einschalten',
            'Unter „APIs & Dienste“ → „Bibliothek“ nach „Google Drive API“ suchen und aktivieren.'),
          step('3', 'Zustimmungsseite ausfüllen',
            'Unter „APIs & Dienste“ → „OAuth-Zustimmungsbildschirm“ den Typ „Extern“ wählen, ' +
            'Namen und deine E-Mail eintragen und dich selbst als Testnutzer hinzufügen.'),
          step('4', 'Kennung erzeugen',
            el('span', {}, 'Unter „Anmeldedaten“ → „Anmeldedaten erstellen“ → „OAuth-Client-ID“, ' +
              'Typ „Webanwendung“. Bei „Autorisierte JavaScript-Quellen“ die Adresse eintragen, ' +
              'unter der du den Planer öffnest – aktuell: ',
              el('span.mono', { style: { color: 'var(--primary)' } }, location.origin), '.')),
          step('5', 'Kennung hier einsetzen',
            'Die erzeugte Client-ID unten einfügen und auf „Verbinden“ klicken.')),

        el('div.field', { style: { marginTop: '18px' } },
          el('label', {}, 'Client-ID'), idInput,
          el('div.hint', {}, 'Diese Angabe ist nicht geheim. Sie lässt sich auch dauerhaft in ' +
            'js/config.js eintragen, dann entfällt der Schritt auf jedem weiteren Gerät.')),
        statusBox),
      footer: [
        el('div.spacer'),
        el('button.soft-btn', { text: 'Abbrechen', onclick: () => m.close() }),
        U.btn('primary-btn', 'check', 'Verbinden', {
          onclick: async e => {
            const btn = e.currentTarget;
            const id = idInput.value.trim();
            if (!/\.apps\.googleusercontent\.com$/.test(id)) {
              statusBox.replaceChildren(el('div.note-box.warn', { style: { marginTop: '12px' } },
                el('span.ico', { html: U.icon('alert', 15) }),
                el('div', {}, 'Das sieht nicht nach einer Client-ID aus. Sie endet auf ' +
                  '„.apps.googleusercontent.com“.')));
              return;
            }
            UP.cloud.setClientId(id);
            btn.disabled = true;
            statusBox.replaceChildren(el('div.note-box', { style: { marginTop: '12px' } },
              el('span.ico', { html: U.icon('clock', 15) }),
              el('div', {}, 'Google fragt gleich nach deiner Zustimmung …')));
            try {
              await UP.cloud.connectInteractive();
              statusBox.replaceChildren(el('div.note-box.ok', { style: { marginTop: '12px' } },
                el('span.ico', { html: U.icon('check', 15) }),
                el('div', {}, 'Verbunden. Der Planer lädt jetzt neu und arbeitet ab sofort mit Drive.')));
              setTimeout(() => UP.sync.useStorage('drive'), 900);
            } catch (err) {
              btn.disabled = false;
              statusBox.replaceChildren(el('div.note-box.danger', { style: { marginTop: '12px' } },
                el('span.ico', { html: U.icon('alert', 15) }),
                el('div', {},
                  el('div', { style: { fontWeight: '700', marginBottom: '3px' } }, 'Verbindung fehlgeschlagen'),
                  el('div', {}, driveErrorHint(err)))));
            }
          },
        }),
      ],
    });
  }

  function driveErrorHint(err) {
    const d = String(err.detail || err.message || '');
    if (/popup/i.test(d)) return 'Das Anmeldefenster wurde blockiert. Erlaube Pop-ups für diese Seite und versuche es erneut.';
    if (/redirect_uri|origin/i.test(d)) return `Google akzeptiert die Adresse ${location.origin} noch nicht. Trage sie in der Cloud Console unter „Autorisierte JavaScript-Quellen“ ein.`;
    if (/access_denied/i.test(d)) return 'Die Freigabe wurde abgelehnt – oder dein Konto steht noch nicht als Testnutzer auf dem Zustimmungsbildschirm.';
    if (/invalid_client/i.test(d)) return 'Die Client-ID ist unbekannt. Stimmt sie genau mit der aus der Cloud Console überein?';
    return d || 'Unbekannter Fehler.';
  }

  /* ═══ Dialog: Speicherort und Fassungen ═════════════════════════════ */
  async function openSyncPanel() {
    if (UP.sync.mode === 'local') return openStorageDialog();

    const body = el('div', {}, el('div.small.muted', {}, 'Daten werden geladen…'));
    const m = modal({
      title: 'Speicherort und Fassungen',
      sub: UP.sync.label,
      size: 'wide', body,
      footer: [
        U.btn('soft-btn', 'settings', 'Speicherort wechseln', {
          onclick: () => { m.close(); openStorageDialog(); },
        }),
        el('div.spacer'),
        U.btn('soft-btn', 'download', 'Sicherung laden', { onclick: exportBackup }),
        el('button.primary-btn', { text: 'Schließen', onclick: () => m.close() }),
      ],
    });

    let info, versions;
    try {
      [info, versions] = await Promise.all([UP.sync.info(), UP.sync.history()]);
    } catch (e) {
      body.replaceChildren(el('div.note-box.danger', {},
        el('span.ico', { html: U.icon('alert', 15) }),
        el('div', {},
          el('div', { style: { fontWeight: '700', marginBottom: '3px' } }, 'Der Speicherort antwortet nicht'),
          el('div', {}, e.name === 'AuthError'
            ? 'Die Anmeldung ist abgelaufen. Über die Statusanzeige oben rechts neu anmelden.'
            : e.message))));
      return;
    }

    const st = SYNC_LABEL[UP.sync.status] || SYNC_LABEL.connecting;
    const since = UP.sync.lastSyncedAt
      ? new Date(UP.sync.lastSyncedAt).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : '–';

    body.replaceChildren(
      el(`div.note-box${UP.sync.status === 'synced' ? '.ok' : UP.sync.status === 'offline' ? '.warn' : ''}`, {},
        el('span.ico', { html: U.icon(UP.sync.status === 'synced' ? 'check' : 'info', 16) }),
        el('div', {},
          el('div', { style: { fontWeight: '700', marginBottom: '2px' } }, st.text || 'Verbunden'),
          el('div', {}, st.hint))),

      el('div.grid-4', { style: { marginTop: '14px' } },
        kpiMini('Fassung', String(info.rev ?? '–'), UP.sync.label),
        kpiMini('Größe', info.bytes ? `${Math.max(1, Math.round(info.bytes / 1024))} kB` : '–', 'Plandaten'),
        kpiMini('Zuletzt', since, 'abgeglichen'),
        kpiMini('Gerät', UP.sync.clientId.split('-')[0], 'dieser Browser')),

      el('div.sec-title', { style: { marginTop: '20px' } }, info.where || 'Speicherort'),
      el('div.mlist', {}, (info.lines || []).map(line => el('div.mrow', {},
        el('span', { html: U.icon(line.icon || 'archive', 16), style: { color: 'var(--faint)' } }),
        el('div.mrow-main', {},
          el('div.mrow-title', {}, line.title),
          line.href
            ? el('a.mrow-sub', { href: line.href, target: '_blank', rel: 'noopener' }, 'im Browser öffnen')
            : el('div.mrow-sub.mono', {}, line.value))))),

      info.note
        ? el('div.small.muted', { style: { marginTop: '10px', lineHeight: '1.5' } }, info.note)
        : null,

      el('div.sec-title', { style: { marginTop: '20px' } }, 'Frühere Fassungen'),
      el('div.small.muted', { style: { marginBottom: '9px' } },
        'Das Wiederherstellen legt selbst eine neue Fassung an – der aktuelle Stand geht dabei nicht verloren.'),
      versions.length
        ? el('div.mlist', {}, versions.slice(0, 25).map(v => el('div.mrow', {},
          el('span.tag', {}, typeof v.rev === 'number' ? `#${v.rev}` : 'Fassung'),
          el('div.mrow-main', {},
            el('div.mrow-title', {}, new Date(v.createdAt).toLocaleString('de-DE')),
            el('div.mrow-sub', {}, [
              v.client || 'unbekanntes Gerät',
              v.bytes ? `${Math.max(1, Math.round(v.bytes / 1024))} kB` : null,
            ].filter(Boolean).join(' · '))),
          String(v.rev) === String(info.rev)
            ? el('span.tag.ok', {}, 'aktuell')
            : U.btn('soft-btn btn-sm', null, 'Wiederherstellen', {
              onclick: async () => {
                if (!await confirmBox({
                  title: 'Fassung wiederherstellen?',
                  text: `Der Plan wird auf den Stand von ${new Date(v.createdAt).toLocaleString('de-DE')} ` +
                        'zurückgesetzt. Der aktuelle Stand bleibt als Fassung erhalten und lässt sich ' +
                        'genauso wieder zurückholen.',
                  okLabel: 'Wiederherstellen',
                })) return;
                try {
                  await UP.sync.restore(v.rev);
                  m.close();
                  toast('ok', 'Fassung wiederhergestellt.');
                } catch (e) { toast('danger', `Fehlgeschlagen: ${e.message}`); }
              },
            }))))
        : el('div.small.muted', {}, 'Noch keine früheren Fassungen vorhanden.'));
  }

  /* ═══ Rendern ═══════════════════════════════════════════════════════ */
  function render() {
    const view = VIEWS[S.ui.view] ? S.ui.view : 'jahr';

    // Kopfleiste aktualisieren
    $('#yearLabel').textContent = S.year();
    $('#yearPill').classList.toggle('archived', S.isLocked());
    $('#yearPill').title = S.isLocked()
      ? `${S.year()} ist schreibgeschützt – im Jahres-Menü entsperren`
      : 'Jahr wechseln oder anlegen';
    $$('#viewTabs .viewtab').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    $('#btnUndo').disabled = !S.canUndo();
    $('#btnRedo').disabled = !S.canRedo();
    $('#btnUndo').title = S.canUndo() ? `Rückgängig: ${S.lastUndoLabel()} (Strg+Z)` : 'Nichts rückgängig zu machen';
    $('#search').value = S.ui.search || '';

    const cf = S.currentYear().people.length ? S.conflicts().length : 0;
    const badge = $('#conflictBadge');
    badge.textContent = cf;
    badge.hidden = cf === 0;

    // Werkzeugleiste
    toolbarEl.replaceChildren();
    const mod = VIEWS[view].mod();
    if (mod.toolbar) {
      const nodes = mod.toolbar();
      (Array.isArray(nodes) ? nodes : [nodes]).forEach(n => n && toolbarEl.appendChild(n));
    }
    if (S.isLocked()) {
      toolbarEl.appendChild(el('div.tb-sep'));
      toolbarEl.appendChild(el('span.tag.warn', {
        title: 'Archiviertes Jahr – Änderungen sind gesperrt',
      }, 'Schreibgeschützt'));
    }

    // Ansicht
    host.replaceChildren();
    mod.render(host);
  }

  /* ═══ Kopfleiste ════════════════════════════════════════════════════ */
  function wireTopbar() {
    $('#viewTabs').addEventListener('click', e => {
      const b = e.target.closest('.viewtab');
      if (b) S.set(s => { s.ui.view = b.dataset.view; });
    });

    $('#yearPrev').onclick = () => stepYear(-1);
    $('#yearNext').onclick = () => stepYear(1);
    $('#yearPill').onclick = e => openYearMenu(e.currentTarget);

    $('#btnAdd').onclick = () => editAbsence(null);
    $('#btnUndo').onclick = doUndo;
    $('#btnRedo').onclick = doRedo;
    $('#btnTheme').onclick = cycleTheme;
    $('#btnMenu').onclick = e => openMainMenu(e.currentTarget);

    $('#search').addEventListener('input', U.debounce(e => {
      S.set(s => { s.ui.search = e.target.value; });
    }, 180));
  }

  function stepYear(n) {
    const years = S.listYears();
    const i = years.indexOf(S.year());
    const target = S.year() + n;
    if (S.setYear(target)) { UP.views.jahr.resetScroll(); return; }
    const next = years[i + n];
    if (next != null) { S.setYear(next); UP.views.jahr.resetScroll(); return; }
    askCreateYear(target);
  }

  /* ═══ Design ════════════════════════════════════════════════════════ */
  function applyTheme() {
    const t = S.settings.theme;
    if (t === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', t);
  }

  function cycleTheme() {
    const order = ['auto', 'light', 'dark'];
    const next = order[(order.indexOf(S.settings.theme) + 1) % 3];
    S.set(s => { s.settings.theme = next; }, { silent: true });
    applyTheme();
    toast('info', `Design: ${{ auto: 'Systemeinstellung', light: 'Hell', dark: 'Dunkel' }[next]}`);
  }

  /* ═══ Tastatur ══════════════════════════════════════════════════════ */
  function wireKeyboard() {
    window.addEventListener('keydown', e => {
      const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault(); e.shiftKey ? doRedo() : doUndo(); return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); doRedo(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault(); exportBackup(); return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        e.preventDefault(); stepYear(e.key === 'ArrowLeft' ? -1 : 1); return;
      }
      if (inField) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      switch (e.key) {
        case 'n': case 'N': e.preventDefault(); editAbsence(null); break;
        case 't': case 'T':
          e.preventDefault();
          if (S.ui.view === 'jahr') UP.views.jahr.scrollToToday(true);
          else S.set(s => { s.ui.month = new Date().getMonth(); });
          break;
        case '/': e.preventDefault(); $('#search').focus(); break;
        case '?': e.preventDefault(); showHelp(); break;
        case '+': case '=':
          if (S.ui.view === 'jahr') S.set(s => { s.ui.zoom = U.clamp(s.ui.zoom + 1, 0, UP.views.jahr.ZOOMS.length - 1); });
          break;
        case '-':
          if (S.ui.view === 'jahr') S.set(s => { s.ui.zoom = U.clamp(s.ui.zoom - 1, 0, UP.views.jahr.ZOOMS.length - 1); });
          break;
        case 'ArrowLeft':
          if (S.ui.view === 'monat') { e.preventDefault(); S.set(s => { s.ui.month = Math.max(0, s.ui.month - 1); }); }
          break;
        case 'ArrowRight':
          if (S.ui.view === 'monat') { e.preventDefault(); S.set(s => { s.ui.month = Math.min(11, s.ui.month + 1); }); }
          break;
        case '1': case '2': case '3': case '4': case '5':
          e.preventDefault();
          S.set(s => { s.ui.view = Object.keys(VIEWS)[Number(e.key) - 1]; });
          break;
      }
    });
  }

  function doUndo() {
    const label = S.undo();
    if (label) toast('info', `Rückgängig: ${label}`);
    else toast('info', 'Nichts rückgängig zu machen.');
  }
  function doRedo() {
    const label = S.redo();
    if (label) toast('info', `Wiederhergestellt: ${label}`);
  }

  /* ═══ Bausteine ═════════════════════════════════════════════════════ */
  function requireUnlocked() {
    if (!S.isLocked()) return true;
    toast('warn', `${S.year()} ist schreibgeschützt.`, {
      action: { label: 'Entsperren', fn: () => { S.set(s => { s.years[s.ui.year].locked = false; }); toast('ok', 'Jahr entsperrt.'); } },
    });
    return false;
  }

  function emptyState() {
    const yd = S.currentYear();
    const hasDepts = yd.departments.length > 0;
    return el('div.empty-state', {},
      el('div.es-icon', { html: U.icon(hasDepts ? 'user' : 'building', 28) }),
      el('h3', {}, hasDepts ? 'Noch keine Personen im Team' : `Urlaubsjahr ${S.year()} ist noch leer`),
      el('p', {}, hasDepts
        ? 'Lege Personen an und ordne sie den Abteilungen zu. Anschließend kannst du Urlaub direkt im Kalender aufziehen.'
        : 'Lege zuerst Abteilungen und Personen an – oder starte mit einem Beispielteam, um alle Funktionen auszuprobieren.'),
      el('div.row.gap-8.mt-8', {},
        U.btn('primary-btn', 'plus', hasDepts ? 'Person anlegen' : 'Abteilung anlegen', {
          onclick: () => hasDepts ? editPerson(null) : editDepartment(null),
        }),
        hasDepts ? null : U.btn('soft-btn', 'star', 'Beispieldaten laden', {
          onclick: async () => {
            if (await confirmBox({
              title: 'Beispieldaten laden?',
              text: 'Damit werden 5 Abteilungen mit 19 Personen und beispielhaften Urlaubseinträgen für ' +
                    `${S.year()} angelegt. Vorhandene Daten dieses Jahres werden dabei ersetzt.`,
              okLabel: 'Beispieldaten laden',
            })) { S.seedDemo(); toast('ok', 'Beispieldaten geladen – alles lässt sich frei ändern.'); }
          },
        }),
        S.listYears().length > 1 ? U.btn('soft-btn', 'copy', 'Team aus anderem Jahr übernehmen', {
          onclick: () => openYearMenu($('#yearPill')),
        }) : null));
  }

  /* ═══ Toast ═════════════════════════════════════════════════════════ */
  function toast(kind, text, opts = {}) {
    const icons = { ok: 'check', warn: 'alert', danger: 'alert', info: 'info' };
    const node = el(`div.toast.${kind}`, {},
      el('span.t-icon', { html: U.icon(icons[kind] || 'info', 13) }),
      el('span', { text }),
      opts.action ? el('button.t-action', {
        text: opts.action.label,
        onclick: () => { close(); opts.action.fn(); },
      }) : null);
    $('#toastHost').appendChild(node);
    const timer = setTimeout(close, opts.duration || (opts.action ? 6500 : 3600));
    function close() {
      clearTimeout(timer);
      node.classList.add('out');
      setTimeout(() => node.remove(), 200);
    }
    return close;
  }

  /* ═══ Hovercard ═════════════════════════════════════════════════════ */
  function showHovercard(anchor, content) {
    hovercardEl.replaceChildren(content);
    hovercardEl.hidden = false;
    const r = anchor.getBoundingClientRect();
    const c = hovercardEl.getBoundingClientRect();
    let left = U.clamp(r.left, 8, window.innerWidth - c.width - 8);
    let top = r.bottom + 8;
    if (top + c.height > window.innerHeight - 8) top = Math.max(8, r.top - c.height - 8);
    hovercardEl.style.left = left + 'px';
    hovercardEl.style.top = top + 'px';
  }
  const hideHovercard = () => { hovercardEl.hidden = true; };

  /* ═══ Modal ═════════════════════════════════════════════════════════ */
  function modal({ title, sub, body, footer, size = '', onClose, onMount }) {
    hideHovercard();
    const overlay = el('div.modal-host');
    const box = el(`div.modal${size ? '.' + size : ''}`, { role: 'dialog', 'aria-modal': 'true' });
    document.body.classList.add('modal-open');

    box.appendChild(el('div.modal-head', {},
      el('h2', {}, title),
      sub ? el('span.sub', { text: sub }) : null,
      el('button.modal-close', { html: U.icon('x', 17), title: 'Schließen (Esc)', onclick: close })));

    const bodyEl = el('div.modal-body', {});
    if (body) bodyEl.appendChild(body);
    box.appendChild(bodyEl);
    if (footer) box.appendChild(el('div.modal-foot', {}, footer));

    overlay.appendChild(box);
    overlay.addEventListener('pointerdown', e => { if (e.target === overlay) close(); });
    document.body.appendChild(overlay);

    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    }
    overlay.addEventListener('keydown', onKey);
    window.addEventListener('keydown', onKey, true);

    function close() {
      window.removeEventListener('keydown', onKey, true);
      overlay.remove();
      if (!document.querySelector('.modal-host')) document.body.classList.remove('modal-open');
      onClose?.();
    }

    setTimeout(() => {
      const first = box.querySelector('input:not([type=hidden]), select, textarea, button.primary-btn');
      first?.focus();
      onMount?.(box, close);
    }, 20);

    return { close, box, bodyEl };
  }

  function confirmBox({ title, text, okLabel = 'OK', danger = false }) {
    return new Promise(resolve => {
      let done = false;
      const m = modal({
        title, size: 'narrow',
        body: el('div', { style: { fontSize: '13.5px', lineHeight: '1.55', color: 'var(--ink-2)' } }, text),
        footer: [
          el('div.spacer'),
          el('button.soft-btn', { text: 'Abbrechen', onclick: () => { done = true; m.close(); resolve(false); } }),
          el(`button.${danger ? 'danger-btn' : 'primary-btn'}`, {
            text: okLabel, onclick: () => { done = true; m.close(); resolve(true); },
          }),
        ],
        onClose: () => { if (!done) resolve(false); },
      });
    });
  }

  /* ═══ Popover ═══════════════════════════════════════════════════════ */
  function popover(anchor, items) {
    const host = el('div.popover-host');
    const pop = el('div.popover');

    for (const it of items) {
      if (it === '-') { pop.appendChild(el('div.menu-sep')); continue; }
      if (it.head) { pop.appendChild(el('div.menu-head', { text: it.head })); continue; }
      if (it.node) { pop.appendChild(it.node); continue; }
      pop.appendChild(el('button.menu-item', {
        class: [it.active ? 'active' : '', it.danger ? 'danger' : ''].filter(Boolean).join(' '),
        onclick: () => { close(); it.fn?.(); },
        title: it.title || '',
      },
        it.icon ? el('span.mi-icon', { html: U.icon(it.icon, 15) }) : el('span.mi-icon'),
        el('span', { text: it.label }),
        it.right ? el('span.mi-right', { text: it.right }) : null));
    }

    host.appendChild(pop);
    host.addEventListener('pointerdown', e => { if (e.target === host) close(); });
    document.body.appendChild(host);

    const r = anchor.getBoundingClientRect();
    const p = pop.getBoundingClientRect();
    pop.style.left = U.clamp(r.left, 8, window.innerWidth - p.width - 8) + 'px';
    pop.style.top = (r.bottom + 6 + p.height > window.innerHeight - 8
      ? Math.max(8, r.top - p.height - 6) : r.bottom + 6) + 'px';

    function onKey(e) { if (e.key === 'Escape') { e.preventDefault(); close(); } }
    window.addEventListener('keydown', onKey, true);
    function close() { window.removeEventListener('keydown', onKey, true); host.remove(); }
    return close;
  }

  /* ═══ Menü: Jahr ════════════════════════════════════════════════════ */
  function openYearMenu(anchor) {
    const years = S.listYears();
    const items = [{ head: 'Gespeicherte Jahre' }];
    for (const y of years) {
      const yd = S.yearData(y);
      items.push({
        label: String(y),
        icon: yd.locked ? 'lock' : 'calendar',
        active: y === S.year(),
        right: `${yd.people.length} P · ${yd.absences.length} E`,
        fn: () => { S.setYear(y); UP.views.jahr.resetScroll(); },
      });
    }
    items.push('-');
    items.push({ label: 'Neues Jahr anlegen …', icon: 'plus', fn: () => askCreateYear(Math.max(...years) + 1) });
    items.push({
      label: S.isLocked() ? 'Jahr entsperren' : 'Jahr schreibgeschützt archivieren',
      icon: S.isLocked() ? 'unlock' : 'archive',
      fn: () => {
        S.set(s => { s.years[s.ui.year].locked = !s.years[s.ui.year].locked; });
        toast('ok', S.isLocked() ? `${S.year()} ist jetzt schreibgeschützt.` : `${S.year()} kann wieder bearbeitet werden.`);
      },
    });
    if (years.length > 1) items.push({
      label: `${S.year()} löschen …`, icon: 'trash', danger: true,
      fn: async () => {
        if (await confirmBox({
          title: `Jahr ${S.year()} löschen?`, danger: true, okLabel: 'Endgültig löschen',
          text: `Alle Abteilungen, Personen und ${S.currentYear().absences.length} Einträge dieses Jahres gehen verloren. ` +
                'Andere Jahre bleiben erhalten.',
        })) { const y = S.year(); S.deleteYear(y); toast('ok', `Jahr ${y} gelöscht.`); }
      },
    });
    popover(anchor, items);
  }

  function askCreateYear(suggested) {
    const years = S.listYears();
    const src = years.length ? Math.max(...years.filter(y => y <= suggested).concat(Math.min(...years))) : null;

    const yearInput = el('input', { type: 'number', value: suggested, min: 1990, max: 2100 });
    const copySel = el('select', {},
      el('option', { value: '' }, 'Leer beginnen'),
      ...years.map(y => el('option', { value: y, selected: y === src }, `Team aus ${y} übernehmen`)));
    const carry = el('input', { type: 'checkbox', checked: true });

    const m = modal({
      title: 'Neues Urlaubsjahr anlegen',
      sub: 'Jedes Jahr wird eigenständig gespeichert',
      size: 'narrow',
      body: el('div', {},
        el('div.field', {}, el('label', {}, 'Jahr'), yearInput),
        el('div.field', {}, el('label', {}, 'Struktur übernehmen'), copySel,
          el('div.hint', {}, 'Abteilungen und Personen werden kopiert – Urlaubseinträge nicht, die planst du neu.')),
        el('div.field', {}, el('label.check', {}, carry, 'Resturlaub als Übertrag eintragen'),
          el('div.hint', {}, 'Offene Tage des Quelljahres werden je Person als Übertrag gutgeschrieben.')),
      ),
      footer: [
        el('div.spacer'),
        el('button.soft-btn', { text: 'Abbrechen', onclick: () => m.close() }),
        el('button.primary-btn', {
          text: 'Anlegen',
          onclick: () => {
            const y = Number(yearInput.value);
            if (!Number.isInteger(y) || y < 1990 || y > 2100) return toast('warn', 'Bitte ein Jahr zwischen 1990 und 2100 angeben.');
            if (S.yearData(y)) { m.close(); S.setYear(y); return toast('info', `Jahr ${y} gibt es schon – es ist jetzt geöffnet.`); }
            const from = copySel.value ? Number(copySel.value) : null;
            S.createYear(y, { copyFrom: from, carryRemaining: from != null && carry.checked });
            UP.views.jahr.resetScroll();
            m.close();
            toast('ok', `Jahr ${y} angelegt${from ? ` – Team aus ${from} übernommen` : ''}.`);
          },
        }),
      ],
    });
  }

  /* ═══ Menü: Hauptmenü ═══════════════════════════════════════════════ */
  function openMainMenu(anchor) {
    const synced = UP.sync.mode !== 'local';
    popover(anchor, [
      { head: 'Speicherort' },
      {
        label: synced ? 'Speicherort & Fassungen …' : 'Speicherort wählen …',
        icon: synced ? 'archive' : 'settings',
        right: synced ? UP.sync.label : 'nur dieser Browser',
        fn: synced ? openSyncPanel : openStorageDialog,
      },
      ...(synced ? [{
        label: 'Jetzt abgleichen', icon: 'copy',
        fn: () => { UP.sync.pullNow(); UP.sync.push(); toast('info', 'Abgleich angestoßen.'); },
      }, {
        label: UP.sync.mode === 'drive' ? 'Google-Verbindung trennen' : 'Abmelden',
        icon: 'x', danger: true,
        fn: async () => {
          if (await confirmBox({
            title: UP.sync.mode === 'drive' ? 'Verbindung zu Google Drive trennen?' : 'Abmelden?',
            text: UP.sync.mode === 'drive'
              ? 'Die Datei bleibt in deinem Drive liegen. Dieser Browser arbeitet danach wieder nur ' +
                'lokal weiter; erneut verbinden geht jederzeit über „Speicherort“.'
              : 'Dieses Gerät meldet sich vom Server ab. Der Plan bleibt dort gespeichert.',
            okLabel: UP.sync.mode === 'drive' ? 'Trennen' : 'Abmelden', danger: true,
          })) UP.sync.logout();
        },
      }] : []),
      '-',
      { head: 'Verwalten' },
      { label: 'Abteilungen …', icon: 'building', fn: openDepartments },
      { label: 'Personen …', icon: 'users', fn: openPeople },
      { label: 'Betriebsruhe / Sperrzeiten …', icon: 'lock', fn: openClosures },
      { label: 'Einstellungen …', icon: 'settings', fn: openSettings },
      '-',
      { head: 'Daten' },
      { label: 'Sicherung speichern (JSON)', icon: 'download', right: 'Strg+S', fn: exportBackup },
      { label: 'Sicherung einlesen …', icon: 'upload', fn: importBackup },
      { label: 'Urlaubskonten als CSV', icon: 'download', fn: () => UP.views.statistik.exportQuota() },
      { label: 'Einträge als CSV', icon: 'download', fn: () => UP.views.statistik.exportAbsences() },
      { label: 'Kalenderdatei (ICS)', icon: 'calendar', fn: exportICS },
      { label: 'Drucken / als PDF sichern', icon: 'printer', fn: () => window.print() },
      '-',
      { label: 'Beispieldaten laden …', icon: 'star', fn: askSeed },
      { label: `Jahr ${S.year()} leeren …`, icon: 'trash', danger: true, fn: askClear },
      '-',
      { label: 'Hilfe & Tastenkürzel', icon: 'help', right: '?', fn: showHelp },
    ]);
  }

  async function askSeed() {
    if (!requireUnlocked()) return;
    if (await confirmBox({
      title: 'Beispieldaten laden?',
      text: `Ersetzt alle Abteilungen, Personen und Einträge in ${S.year()} durch ein Beispielteam. ` +
            'Andere Jahre bleiben unberührt, und der Schritt lässt sich rückgängig machen.',
      okLabel: 'Laden', danger: true,
    })) { S.seedDemo(); toast('ok', 'Beispieldaten geladen.'); }
  }

  async function askClear() {
    if (!requireUnlocked()) return;
    if (await confirmBox({
      title: `Jahr ${S.year()} leeren?`,
      text: 'Alle Abteilungen, Personen und Einträge dieses Jahres werden entfernt. Andere Jahre bleiben erhalten.',
      okLabel: 'Leeren', danger: true,
    })) { S.clearAll(); toast('ok', 'Jahr geleert.', { action: { label: 'Rückgängig', fn: doUndo } }); }
  }

  /* ═══ Dialog: Abwesenheit ═══════════════════════════════════════════ */
  function editAbsence(id, prefill = {}) {
    const yd = S.currentYear();
    if (!yd.people.length) {
      toast('warn', 'Lege zuerst eine Person an.');
      return editPerson(null);
    }
    const existing = id ? yd.absences.find(a => a.id === id) : null;
    if (id && !existing) return;
    if (!requireUnlocked()) return;

    const y = S.year();
    const data = {
      personId: existing?.personId || prefill.personId || yd.people[0].id,
      type: existing?.type || prefill.type || S.ui.quickType,
      status: existing?.status || prefill.status || S.settings.defaultStatus,
      start: existing?.start || prefill.start || U.todayISO(),
      end: existing?.end || prefill.end || prefill.start || U.todayISO(),
      halfStart: existing?.halfStart || false,
      halfEnd: existing?.halfEnd || false,
      note: existing?.note || '',
    };
    if (U.parseISO(data.start).getFullYear() !== y) data.start = `${y}-01-01`;
    if (U.parseISO(data.end).getFullYear() !== y) data.end = data.start;

    /* Felder */
    const personSel = el('select', { onchange: e => { data.personId = e.target.value; refresh(); } });
    const groups = yd.departments.map(d => ({ d, people: S.peopleOf(d.id, yd) }))
      .concat(S.peopleOf(null, yd).length ? [{ d: null, people: S.peopleOf(null, yd) }] : []);
    for (const g of groups) {
      if (!g.people.length) continue;
      const og = el('optgroup', { label: g.d ? g.d.name : 'Ohne Abteilung' });
      g.people.forEach(p => og.appendChild(el('option', { value: p.id, selected: p.id === data.personId }, p.name)));
      personSel.appendChild(og);
    }

    const typeChips = el('div.chipgrid', {}, S.TYPE_ORDER.map(key => {
      const t = S.TYPES[key];
      return el('button.chipopt', {
        class: data.type === key ? 'active' : '',
        style: data.type === key ? { color: t.color } : null,
        dataset: { type: key },
        onclick: () => {
          data.type = key;
          $$('.chipopt', typeChips).forEach(c => {
            const on = c.dataset.type === key;
            c.classList.toggle('active', on);
            c.style.color = on ? S.TYPES[key].color : '';
          });
          refresh();
        },
      }, el('span.swatch', { style: { background: t.color } }), t.label);
    }));

    const statusSeg = el('div.seg', {}, Object.entries(S.STATUS).map(([k, v]) =>
      el('button', {
        class: data.status === k ? 'active' : '',
        dataset: { status: k },
        onclick: () => {
          data.status = k;
          $$('button', statusSeg).forEach(b => b.classList.toggle('active', b.dataset.status === k));
          refresh();
        },
      }, v.label)));

    const startInp = el('input', {
      type: 'date', value: data.start, min: `${y}-01-01`, max: `${y}-12-31`,
      onchange: e => {
        data.start = e.target.value || data.start;
        if (data.end < data.start) { data.end = data.start; endInp.value = data.end; }
        refresh();
      },
    });
    const endInp = el('input', {
      type: 'date', value: data.end, min: `${y}-01-01`, max: `${y}-12-31`,
      onchange: e => {
        data.end = e.target.value || data.end;
        if (data.end < data.start) { data.start = data.end; startInp.value = data.start; }
        refresh();
      },
    });

    const halfStartCb = el('input', { type: 'checkbox', checked: data.halfStart, onchange: e => { data.halfStart = e.target.checked; refresh(); } });
    const halfEndCb = el('input', { type: 'checkbox', checked: data.halfEnd, onchange: e => { data.halfEnd = e.target.checked; refresh(); } });
    const noteInp = el('textarea', { placeholder: 'Notiz (optional) – z. B. Vertretung, Reiseziel, Rückrufnummer', oninput: e => { data.note = e.target.value; } });
    noteInp.value = data.note;

    const info = el('div');

    function refresh() {
      const days = S.workdaysOf({ ...data });
      const q = S.quota(data.personId);
      const p = S.personById(data.personId);
      const t = S.TYPES[data.type];
      const impact = S.previewImpact(data.personId, data.start, data.end, { ignoreAbsenceId: id });

      const restAfter = t.quota
        ? q.remaining + (existing && S.TYPES[existing.type].quota && existing.status !== 'abgelehnt' ? S.workdaysOf(existing) : 0)
          - (data.status === 'abgelehnt' ? 0 : days)
        : q.remaining;

      const parts = [
        el('div.grid-3', { style: { marginBottom: '12px' } },
          el('div.kpi', { style: { padding: '10px 12px' } },
            el('div.k-label', {}, 'Arbeitstage'),
            el('div.k-value', { style: { fontSize: '21px' } }, U.num(days))),
          el('div.kpi', { style: { padding: '10px 12px' } },
            el('div.k-label', {}, 'Kalendertage'),
            el('div.k-value', { style: { fontSize: '21px' } }, String(U.diffDays(data.start, data.end) + 1))),
          el('div.kpi', {
            class: t.quota && restAfter < 0 ? 'is-danger' : '',
            style: { padding: '10px 12px' },
          },
            el('div.k-label', {}, t.quota ? 'Rest danach' : 'Urlaubskonto'),
            el('div.k-value', { style: { fontSize: '21px' } }, t.quota ? U.num(Math.round(restAfter * 2) / 2) : '±0'))),

        impact.over
          ? el('div.note-box.danger', {},
            el('span.ico', { html: U.icon('alert', 16) }),
            el('div', {},
              el('div', { style: { fontWeight: '700', marginBottom: '3px' } },
                `Überschneidung in „${impact.deptName}“`),
              el('div', {}, `An ${U.plural(impact.days.length, 'Arbeitstag', 'Arbeitstagen')} wären bis zu ` +
                `${impact.worst} Personen gleichzeitig abwesend – erlaubt sind ${impact.max}.`),
              el('div', { style: { marginTop: '5px' } },
                'Betroffen: ' + [...new Set(impact.days.flatMap(d => d.others.map(o => o.name)))].join(', ')),
              el('div', { style: { marginTop: '5px', opacity: .85 } },
                `Zuerst betroffen: ${U.fmt(impact.days[0].iso)}`)))
          : el('div.note-box.ok', {},
            el('span.ico', { html: U.icon('check', 16) }),
            el('div', {}, `Passt: In „${impact.deptName}“ bleibt die Grenze von ${impact.max} gleichzeitig ` +
              'Abwesenden eingehalten.')),

        t.quota && restAfter < 0
          ? el('div.note-box.warn', { style: { marginTop: '10px' } },
            el('span.ico', { html: U.icon('alert', 16) }),
            el('div', {}, `${p.name} überzieht damit das Urlaubskonto um ${U.num(Math.abs(restAfter))} Tage.`))
          : null,
      ];
      info.replaceChildren(...parts.filter(Boolean));
    }

    const m = modal({
      title: existing ? 'Abwesenheit bearbeiten' : 'Abwesenheit eintragen',
      sub: `Jahr ${y}`,
      body: el('div', {},
        el('div.field', {}, el('label', {}, 'Person'), personSel),
        el('div.field', {}, el('div.field-label', {}, 'Art'), typeChips),
        el('div.field-row', {},
          el('div.field', {}, el('label', {}, 'Von'), startInp,
            el('label.check', { style: { marginTop: '6px' } }, halfStartCb, 'nur halber Tag')),
          el('div.field', {}, el('label', {}, 'Bis'), endInp,
            el('label.check', { style: { marginTop: '6px' } }, halfEndCb, 'nur halber Tag'))),
        el('div.field', {}, el('div.field-label', {}, 'Status'), statusSeg),
        info,
        el('div.field', { style: { marginTop: '14px' } }, el('label', {}, 'Notiz'), noteInp)),
      footer: [
        existing ? U.btn('soft-btn', 'trash', 'Löschen', {
          onclick: async () => {
            const p = S.personById(existing.personId);
            if (await confirmBox({
              title: 'Eintrag löschen?', danger: true, okLabel: 'Löschen',
              text: `${S.TYPES[existing.type].label} von ${p?.name} (${U.fmtRange(existing.start, existing.end)}) wird entfernt.`,
            })) {
              S.deleteAbsence(existing.id); m.close();
              toast('ok', 'Eintrag gelöscht.', { action: { label: 'Rückgängig', fn: doUndo } });
            }
          },
        }) : null,
        el('div.spacer'),
        el('button.soft-btn', { text: 'Abbrechen', onclick: () => m.close() }),
        el('button.primary-btn', {
          text: existing ? 'Speichern' : 'Eintragen',
          onclick: () => {
            const payload = { ...data };
            if (existing) S.updateAbsence(existing.id, payload);
            else S.addAbsence(payload);
            m.close();
            afterAbsenceChange(payload, S.personById(payload.personId), existing ? 'gespeichert' : 'eingetragen');
          },
        }),
      ],
    });

    refresh();
  }

  /** Rückmeldung nach jeder Änderung an einem Eintrag – inklusive Konfliktwarnung. */
  function afterAbsenceChange(a, p, verb) {
    const days = S.workdaysOf(a);
    const impact = S.previewImpact(a.personId, a.start, a.end, { ignoreAbsenceId: a.id });
    const base = `${p ? p.name : 'Eintrag'}: ${S.TYPES[a.type].label} ${U.fmtRange(a.start, a.end)} · ${U.plural(days, 'Arbeitstag', 'Arbeitstage')} ${verb}`;
    if (impact.over) {
      toast('warn', `${base} – Achtung: ${impact.worst} gleichzeitig abwesend, erlaubt sind ${impact.max}.`, {
        action: { label: 'Rückgängig', fn: doUndo }, duration: 8000,
      });
    } else {
      toast('ok', base, { action: { label: 'Rückgängig', fn: doUndo } });
    }
  }

  /* ═══ Dialog: Person ════════════════════════════════════════════════ */
  function editPerson(id, presetDept = null) {
    if (!requireUnlocked()) return;
    const yd = S.currentYear();
    const p = id ? S.personById(id) : null;
    if (id && !p) return;

    const nameInp = el('input', { type: 'text', value: p?.name || '', placeholder: 'Vor- und Nachname' });
    const roleInp = el('input', { type: 'text', value: p?.role || '', placeholder: 'z. B. Polier, Buchhaltung' });
    const deptSel = el('select', {},
      el('option', { value: '' }, 'Ohne Abteilung'),
      ...yd.departments.map(d => el('option', {
        value: d.id, selected: d.id === (p ? p.deptId : presetDept),
      }, d.name)));
    const entInp = el('input', { type: 'number', min: 0, max: 200, step: 0.5, value: p?.entitlement ?? S.settings.defaultEntitlement });
    const carryInp = el('input', { type: 'number', min: -50, max: 100, step: 0.5, value: p?.carryover ?? 0 });

    let color = p?.color || null;
    const colorRow = el('div.colorpick', {},
      el('button', {
        class: color ? '' : 'active',
        style: { background: U.colorOf(nameInp.value || 'x'), border: '2px dashed var(--border-strong)' },
        title: 'Automatisch aus dem Namen', onclick: () => pick(null),
      }),
      ...U.AVATAR_COLORS.map(c => el('button', {
        class: color === c ? 'active' : '', style: { background: c }, title: c,
        onclick: () => pick(c),
      })));
    function pick(c) {
      color = c;
      $$('button', colorRow).forEach((b, i) => b.classList.toggle('active', i === 0 ? c === null : U.AVATAR_COLORS[i - 1] === c));
    }

    const m = modal({
      title: p ? 'Person bearbeiten' : 'Person anlegen',
      sub: `Jahr ${S.year()}`,
      body: el('div', {},
        el('div.field', {}, el('label', {}, 'Name'), nameInp),
        el('div.field-row', {},
          el('div.field', {}, el('label', {}, 'Rolle / Funktion'), roleInp),
          el('div.field', {}, el('label', {}, 'Abteilung'), deptSel)),
        el('div.field-row', {},
          el('div.field', {}, el('label', {}, 'Urlaubsanspruch (Tage)'), entInp),
          el('div.field', {}, el('label', {}, 'Übertrag aus Vorjahr'), carryInp)),
        el('div.field', {}, el('div.field-label', {}, 'Farbe'), colorRow,
          el('div.hint', {}, 'Wird für das Kürzel in den Listen verwendet.')),
        p ? el('div.note-box', { style: { marginTop: '4px' } },
          el('span.ico', { html: U.icon('info', 15) }),
          el('div', {}, `Diese Angaben gelten für ${S.year()}. Andere Jahre werden dadurch nicht verändert.`)) : null),
      footer: [
        p ? U.btn('soft-btn', 'trash', 'Löschen', {
          onclick: async () => {
            const n = S.absencesOf(p.id).length;
            if (await confirmBox({
              title: `${p.name} löschen?`, danger: true, okLabel: 'Löschen',
              text: `Die Person und ${U.plural(n, 'Eintrag', 'Einträge')} aus ${S.year()} werden entfernt.`,
            })) { S.deletePerson(p.id); m.close(); toast('ok', 'Person gelöscht.', { action: { label: 'Rückgängig', fn: doUndo } }); }
          },
        }) : null,
        el('div.spacer'),
        el('button.soft-btn', { text: 'Abbrechen', onclick: () => m.close() }),
        el('button.primary-btn', {
          text: p ? 'Speichern' : 'Anlegen',
          onclick: () => {
            const name = nameInp.value.trim();
            if (!name) { nameInp.focus(); return toast('warn', 'Bitte einen Namen angeben.'); }
            const patch = {
              name, role: roleInp.value.trim(),
              deptId: deptSel.value || null,
              entitlement: Number(entInp.value) || 0,
              carryover: Number(carryInp.value) || 0,
              color,
            };
            if (p) { S.updatePerson(p.id, patch); toast('ok', `${name} gespeichert.`); }
            else { S.addPerson(name, patch.deptId, patch); toast('ok', `${name} hinzugefügt.`); }
            m.close();
          },
        }),
      ],
    });
  }

  /* ═══ Ansicht: Person im Detail ═════════════════════════════════════ */
  function openPerson(id) {
    const p = S.personById(id);
    if (!p) return;
    const q = S.quota(id);
    const d = S.deptById(p.deptId);
    const list = S.absencesOf(id);
    const cfIds = new Set(S.conflicts().flatMap(c => c.people.map(x => x.absence.id)));

    const body = el('div', {},
      el('div.row.gap-14', { style: { marginBottom: '16px' } },
        el('span.avatar.lg', { style: { background: p.color || U.colorOf(p.name) } }, U.initials(p.name)),
        el('div', {},
          el('div', { style: { fontSize: '17px', fontWeight: '700' } }, p.name),
          el('div.small.muted', {}, [p.role, d ? d.name : 'Ohne Abteilung'].filter(Boolean).join(' · '))),
        el('div', { style: { marginLeft: 'auto', display: 'flex', gap: '6px' } },
          U.btn('soft-btn btn-sm', 'pencil', 'Bearbeiten', { onclick: () => { m.close(); editPerson(id); } }))),

      el('div.grid-4', { style: { marginBottom: '16px' } },
        kpiMini('Anspruch', U.num(q.entitlement), 'Tage'),
        kpiMini('Übertrag', U.num(q.carryover), 'aus Vorjahr'),
        kpiMini('Verplant', U.num(q.planned), `${U.num(q.approved)} genehmigt`),
        kpiMini('Rest', U.num(q.remaining), q.remaining < 0 ? 'überzogen' : 'offen',
          q.remaining < 0 ? 'is-danger' : q.remaining <= 3 ? 'is-warn' : 'is-ok')),

      el('div.sec-title', {}, `Einträge ${S.year()}`),
      list.length ? el('div.mlist', {}, list.map(a => {
        const t = S.TYPES[a.type];
        return el('div.mrow', {},
          el('span', { style: { width: '4px', alignSelf: 'stretch', borderRadius: '3px', background: t.color, flex: '0 0 auto' } }),
          el('div.mrow-main', {},
            el('div.mrow-title', {}, U.fmtRange(a.start, a.end),
              cfIds.has(a.id) ? el('span.tag.danger', { style: { marginLeft: '7px' } }, 'Überschneidung') : null),
            el('div.mrow-sub', {},
              `${t.label} · ${U.plural(S.workdaysOf(a), 'Arbeitstag', 'Arbeitstage')} · ${S.STATUS[a.status].label}` +
              (a.note ? ` · ${a.note}` : ''))),
          el('div.mrow-actions', {},
            el('button.iconbtn', { html: U.icon('pencil', 14), title: 'Bearbeiten', onclick: () => { m.close(); editAbsence(a.id); } }),
            el('button.iconbtn.danger', {
              html: U.icon('trash', 14), title: 'Löschen',
              onclick: () => { if (!requireUnlocked()) return; S.deleteAbsence(a.id); m.close(); openPerson(id); toast('ok', 'Eintrag gelöscht.', { action: { label: 'Rückgängig', fn: doUndo } }); },
            })));
      })) : el('div.small.muted', { style: { padding: '10px 0' } }, 'Für dieses Jahr ist noch nichts eingetragen.'));

    const m = modal({
      title: 'Person', sub: `Jahr ${S.year()}`, size: 'wide', body,
      footer: [
        el('div.spacer'),
        el('button.soft-btn', { text: 'Schließen', onclick: () => m.close() }),
        U.btn('primary-btn', 'plus', 'Abwesenheit', { onclick: () => { m.close(); editAbsence(null, { personId: id }); } }),
      ],
    });
  }

  function kpiMini(label, value, note, cls = '') {
    return el(`div.kpi${cls ? '.' + cls : ''}`, { style: { padding: '10px 12px' } },
      el('div.k-label', {}, label),
      el('div.k-value', { style: { fontSize: '21px' } }, value),
      el('div.k-note', {}, note));
  }

  /* ═══ Dialog: Abteilung ═════════════════════════════════════════════ */
  function editDepartment(id) {
    if (!requireUnlocked()) return;
    const yd = S.currentYear();
    const d = id ? S.deptById(id) : null;
    if (id && !d) return;

    const nameInp = el('input', { type: 'text', value: d?.name || '', placeholder: 'z. B. Hochbau, Verwaltung' });
    const maxInp = el('input', {
      type: 'number', min: 0, max: 99, step: 1,
      value: d?.maxAbsent ?? S.settings.defaultMaxAbsent,
    });

    let color = d?.color || U.DEPT_COLORS[yd.departments.length % U.DEPT_COLORS.length];
    const colorRow = el('div.colorpick', {}, U.DEPT_COLORS.map(c =>
      el('button', {
        class: color === c ? 'active' : '', style: { background: c },
        onclick: () => { color = c; $$('button', colorRow).forEach((b, i) => b.classList.toggle('active', U.DEPT_COLORS[i] === c)); },
      })));

    const size = d ? S.peopleOf(d.id, yd).length : 0;

    const m = modal({
      title: d ? 'Abteilung bearbeiten' : 'Abteilung anlegen',
      sub: `Jahr ${S.year()}`, size: 'narrow',
      body: el('div', {},
        el('div.field', {}, el('label', {}, 'Name'), nameInp),
        el('div.field', {}, el('label', {}, 'Höchstens gleichzeitig abwesend'), maxInp,
          el('div.hint', {}, 'Wird diese Zahl an einem Arbeitstag überschritten, meldet der Planer eine Überschneidung. ' +
            (size ? `Die Abteilung hat aktuell ${U.plural(size, 'Person', 'Personen')}.` : ''))),
        el('div.field', {}, el('div.field-label', {}, 'Farbe'), colorRow)),
      footer: [
        d ? U.btn('soft-btn', 'trash', 'Löschen', {
          onclick: async () => {
            if (await confirmBox({
              title: `„${d.name}“ löschen?`, danger: true, okLabel: 'Löschen',
              text: size
                ? `Die ${U.plural(size, 'Person', 'Personen')} dieser Abteilung bleiben erhalten und stehen danach unter „Ohne Abteilung“.`
                : 'Die Abteilung wird entfernt.',
            })) { S.deleteDepartment(d.id); m.close(); toast('ok', 'Abteilung gelöscht.', { action: { label: 'Rückgängig', fn: doUndo } }); }
          },
        }) : null,
        el('div.spacer'),
        el('button.soft-btn', { text: 'Abbrechen', onclick: () => m.close() }),
        el('button.primary-btn', {
          text: d ? 'Speichern' : 'Anlegen',
          onclick: () => {
            const name = nameInp.value.trim();
            if (!name) { nameInp.focus(); return toast('warn', 'Bitte einen Namen angeben.'); }
            const patch = { name, color, maxAbsent: U.clamp(Number(maxInp.value) || 0, 0, 99) };
            if (d) { S.updateDepartment(d.id, patch); toast('ok', 'Abteilung gespeichert.'); }
            else { S.addDepartment(name, patch); toast('ok', `Abteilung „${name}“ angelegt.`); }
            m.close();
          },
        }),
      ],
    });
  }

  /* ═══ Übersicht: Abteilungen ════════════════════════════════════════ */
  function openDepartments() {
    const yd = S.currentYear();
    const rows = yd.departments.map(d => {
      const n = S.peopleOf(d.id, yd).length;
      const cf = S.conflicts().filter(c => c.deptId === d.id).length;
      return el('div.mrow', {},
        el('span.dot', { style: { background: d.color, width: '11px', height: '11px' } }),
        el('div.mrow-main', {},
          el('div.mrow-title', {}, d.name),
          el('div.mrow-sub', {}, `${U.plural(n, 'Person', 'Personen')} · höchstens ${d.maxAbsent} gleichzeitig abwesend` +
            (cf ? ` · ${cf} Überschneidung${cf > 1 ? 'en' : ''}` : ''))),
        cf ? el('span.tag.danger', {}, String(cf)) : null,
        el('div.mrow-actions', {},
          el('button.iconbtn', { html: U.icon('pencil', 14), title: 'Bearbeiten', onclick: () => { m.close(); editDepartment(d.id); } })));
    });
    const orphan = S.peopleOf(null, yd).length;

    const m = modal({
      title: 'Abteilungen', sub: `Jahr ${S.year()}`,
      body: el('div', {},
        rows.length ? el('div.mlist', {}, rows) : el('div.small.muted', {}, 'Noch keine Abteilungen angelegt.'),
        orphan ? el('div.note-box.warn', { style: { marginTop: '12px' } },
          el('span.ico', { html: U.icon('info', 15) }),
          el('div', {}, `${U.plural(orphan, 'Person ist', 'Personen sind')} keiner Abteilung zugeordnet. ` +
            'In der Team-Ansicht lassen sie sich per Drag & Drop einsortieren.')) : null,
        el('div.note-box', { style: { marginTop: '12px' } },
          el('span.ico', { html: U.icon('info', 15) }),
          el('div', {}, 'Der Grenzwert je Abteilung steuert die Überschneidungs-Prüfung: ' +
            'Sind an einem Arbeitstag mehr Personen abwesend als erlaubt, erscheint der Zeitraum unter „Überschneidungen“.'))),
      footer: [
        el('div.spacer'),
        el('button.soft-btn', { text: 'Schließen', onclick: () => m.close() }),
        U.btn('primary-btn', 'plus', 'Abteilung', { onclick: () => { m.close(); editDepartment(null); } }),
      ],
    });
  }

  /* ═══ Übersicht: Personen ═══════════════════════════════════════════ */
  function openPeople() {
    const yd = S.currentYear();
    const sorted = yd.people.slice().sort((a, b) => U.byName(a.name, b.name));
    const rows = sorted.map(p => {
      const d = S.deptById(p.deptId);
      const q = S.quota(p.id);
      return el('div.mrow', {},
        el('span.avatar.sm', { style: { background: p.color || U.colorOf(p.name) } }, U.initials(p.name)),
        el('div.mrow-main', {},
          el('div.mrow-title', {}, p.name),
          el('div.mrow-sub', {}, [p.role, d ? d.name : 'Ohne Abteilung',
            `Rest ${U.num(q.remaining)} von ${U.num(q.total)}`].filter(Boolean).join(' · '))),
        el('div.mrow-actions', {},
          el('button.iconbtn', { html: U.icon('calendar', 14), title: 'Details', onclick: () => { m.close(); openPerson(p.id); } }),
          el('button.iconbtn', { html: U.icon('pencil', 14), title: 'Bearbeiten', onclick: () => { m.close(); editPerson(p.id); } })));
    });

    const m = modal({
      title: 'Personen', sub: `${sorted.length} im Jahr ${S.year()}`, size: 'wide',
      body: rows.length ? el('div.mlist', {}, rows) : el('div.small.muted', {}, 'Noch niemand angelegt.'),
      footer: [
        el('div.spacer'),
        el('button.soft-btn', { text: 'Schließen', onclick: () => m.close() }),
        U.btn('primary-btn', 'plus', 'Person', { onclick: () => { m.close(); editPerson(null); } }),
      ],
    });
  }

  /* ═══ Betriebsruhe ══════════════════════════════════════════════════ */
  function openClosures() {
    const yd = S.currentYear();
    const y = S.year();
    const nameInp = el('input', { type: 'text', placeholder: 'z. B. Betriebsruhe Weihnachten' });
    const fromInp = el('input', { type: 'date', min: `${y}-01-01`, max: `${y}-12-31`, value: `${y}-12-24` });
    const toInp = el('input', { type: 'date', min: `${y}-01-01`, max: `${y}-12-31`, value: `${y}-12-31` });

    const listEl = el('div.mlist');
    function fill() {
      listEl.replaceChildren(...(yd.closures.length ? yd.closures
        .slice().sort((a, b) => a.start.localeCompare(b.start)).map(c =>
          el('div.mrow', {},
            el('div.mrow-main', {},
              el('div.mrow-title', {}, c.name),
              el('div.mrow-sub', {}, U.fmtRange(c.start, c.end))),
            el('div.mrow-actions', {},
              el('button.iconbtn.danger', {
                html: U.icon('trash', 14), title: 'Entfernen',
                onclick: () => { S.deleteClosure(c.id); fill(); },
              }))))
        : [el('div.small.muted', {}, 'Noch keine Sperrzeiten eingetragen.')]));
    }
    fill();

    const m = modal({
      title: 'Betriebsruhe & Sperrzeiten', sub: `Jahr ${y}`,
      body: el('div', {},
        listEl,
        el('div.sec-title', { style: { marginTop: '18px' } }, 'Neu anlegen'),
        el('div.field', {}, el('label', {}, 'Bezeichnung'), nameInp),
        el('div.field-row', {},
          el('div.field', {}, el('label', {}, 'Von'), fromInp),
          el('div.field', {}, el('label', {}, 'Bis'), toInp)),
        U.btn('soft-btn', 'plus', 'Sperrzeit hinzufügen', {
          onclick: () => {
            if (!requireUnlocked()) return;
            if (!fromInp.value || !toInp.value) return toast('warn', 'Bitte Zeitraum angeben.');
            S.addClosure(nameInp.value.trim() || 'Betriebsruhe', fromInp.value, toInp.value);
            nameInp.value = '';
            fill();
            toast('ok', 'Sperrzeit angelegt.');
          },
        }),
        el('div.note-box', { style: { marginTop: '14px' } },
          el('span.ico', { html: U.icon('info', 15) }),
          el('div', {}, 'Sperrzeiten werden in der Jahresansicht als farbiger Streifen hinterlegt – ' +
            'als Hinweis für die Planung. Urlaubstage werden dadurch nicht automatisch abgezogen.'))),
      footer: [el('div.spacer'), el('button.primary-btn', { text: 'Fertig', onclick: () => m.close() })],
    });
  }

  /* ═══ Einstellungen ═════════════════════════════════════════════════ */
  function openSettings() {
    const regionSel = el('select', {}, UP.holidays.REGION_GROUPS.map(g =>
      el('optgroup', { label: g.label }, g.keys.map(k =>
        el('option', { value: k, selected: S.settings.region === k }, UP.holidays.REGIONS[k])))));
    const entInp = el('input', { type: 'number', min: 0, max: 200, step: 0.5, value: S.settings.defaultEntitlement });
    const maxInp = el('input', { type: 'number', min: 0, max: 99, value: S.settings.defaultMaxAbsent });
    const statusSel = el('select', {}, Object.entries(S.STATUS).map(([k, v]) =>
      el('option', { value: k, selected: S.settings.defaultStatus === k }, v.label)));
    const themeSel = el('select', {},
      el('option', { value: 'auto', selected: S.settings.theme === 'auto' }, 'Wie das System'),
      el('option', { value: 'light', selected: S.settings.theme === 'light' }, 'Hell'),
      el('option', { value: 'dark', selected: S.settings.theme === 'dark' }, 'Dunkel'));

    const m = modal({
      title: 'Einstellungen', size: 'narrow',
      body: el('div', {},
        el('div.field', {}, el('label', {}, 'Feiertagsregion'), regionSel,
          el('div.hint', {}, 'Bestimmt, welche Tage als Feiertag gelten und damit nicht als Urlaubstag zählen.')),
        el('div.field', {}, el('label', {}, 'Design'), themeSel),
        el('div.sec-title', { style: { marginTop: '18px' } }, 'Vorgaben für neue Einträge'),
        el('div.field-row', {},
          el('div.field', {}, el('label', {}, 'Urlaubsanspruch'), entInp),
          el('div.field', {}, el('label', {}, 'Max. gleichzeitig'), maxInp)),
        el('div.field', {}, el('label', {}, 'Status neuer Einträge'), statusSel,
          el('div.hint', {}, 'Bei „Beantragt“ erscheinen neue Einträge gestreift und lassen sich später genehmigen.')),
        el('div.note-box', { style: { marginTop: '16px' } },
          el('span.ico', { html: U.icon('info', 15) }),
          UP.sync.mode === 'server'
            ? el('div', {}, 'Diese Vorgaben gelten für alle Geräte, die auf denselben Server zugreifen.')
            : el('div', {}, 'Alle Daten bleiben in diesem Browser gespeichert (localStorage) – nichts wird hochgeladen. ' +
              'Für den Wechsel auf einen anderen Rechner nutze „Sicherung speichern“ im Menü.'))),
      footer: [
        el('div.spacer'),
        el('button.soft-btn', { text: 'Abbrechen', onclick: () => m.close() }),
        el('button.primary-btn', {
          text: 'Speichern',
          onclick: () => {
            S.set(s => {
              s.settings.region = regionSel.value;
              s.settings.theme = themeSel.value;
              s.settings.defaultEntitlement = Number(entInp.value) || 0;
              s.settings.defaultMaxAbsent = U.clamp(Number(maxInp.value) || 0, 0, 99);
              s.settings.defaultStatus = statusSel.value;
            }, { silent: true });
            applyTheme();
            m.close();
            render();
            toast('ok', 'Einstellungen gespeichert.');
          },
        }),
      ],
    });
  }

  /* ═══ Tages-Detail ══════════════════════════════════════════════════ */
  function showDayDetail(dayIndex, deptId) {
    const cal = S.calendar();
    const day = cal[dayIndex];
    if (!day) return;
    const rows = S.absentOn(dayIndex, deptId);
    const dept = deptId === '__none__' ? null : S.deptById(deptId);
    const max = dept ? dept.maxAbsent : S.settings.defaultMaxAbsent;

    const m = modal({
      title: U.fmtLong(day.iso),
      sub: (dept ? dept.name : 'Ohne Abteilung') + (day.holiday ? ` · ${day.holiday.name}` : ''),
      size: 'narrow',
      body: el('div', {},
        el(`div.note-box${rows.length > max ? '.danger' : rows.length === max ? '.warn' : '.ok'}`, {},
          el('span.ico', { html: U.icon(rows.length > max ? 'alert' : 'info', 15) }),
          el('div', {}, `${U.plural(rows.length, 'Person', 'Personen')} abwesend – erlaubt sind ${max}.`)),
        el('div.mlist', { style: { marginTop: '14px' } }, rows.map(({ person, absence }) =>
          el('div.mrow', {},
            el('span.avatar.sm', { style: { background: person.color || U.colorOf(person.name) } }, U.initials(person.name)),
            el('div.mrow-main', {},
              el('div.mrow-title', {}, person.name),
              el('div.mrow-sub', {}, `${S.TYPES[absence.type].label} · ${U.fmtRange(absence.start, absence.end)}`)),
            el('button.iconbtn', {
              html: U.icon('pencil', 14), title: 'Eintrag bearbeiten',
              onclick: () => { m.close(); editAbsence(absence.id); },
            })))),
      ),
      footer: [el('div.spacer'), el('button.primary-btn', { text: 'Schließen', onclick: () => m.close() })],
    });
  }

  /* ═══ Import / Export ═══════════════════════════════════════════════ */
  function exportBackup() {
    const stamp = new Date().toISOString().slice(0, 10);
    U.download(`Urlaubsplaner_Sicherung_${stamp}.json`, S.exportJSON(), 'application/json');
    toast('ok', `Sicherung gespeichert – ${U.plural(S.listYears().length, 'Jahr', 'Jahre')} enthalten.`);
  }

  function importBackup() {
    const input = el('input', { type: 'file', accept: '.json,application/json', style: { display: 'none' } });
    document.body.appendChild(input);
    input.onchange = async () => {
      const file = input.files?.[0];
      input.remove();
      if (!file) return;
      const text = await file.text();
      let mode = null;
      const m = modal({
        title: 'Sicherung einlesen', size: 'narrow',
        body: el('div', {},
          el('div', { style: { fontSize: '13.5px', marginBottom: '12px' } }, `Datei: ${file.name}`),
          el('div.note-box.warn', {},
            el('span.ico', { html: U.icon('alert', 15) }),
            el('div', {}, 'Beim Ersetzen gehen die aktuell gespeicherten Jahre verloren. ' +
              'Beim Zusammenführen bleiben vorhandene Jahre erhalten – gleichnamige Jahre werden überschrieben.'))),
        footer: [
          el('div.spacer'),
          el('button.soft-btn', { text: 'Abbrechen', onclick: () => m.close() }),
          el('button.soft-btn', { text: 'Zusammenführen', onclick: () => { mode = 'merge'; m.close(); run(); } }),
          el('button.primary-btn', { text: 'Ersetzen', onclick: () => { mode = 'replace'; m.close(); run(); } }),
        ],
      });
      function run() {
        try {
          const n = S.importJSON(text, { merge: mode === 'merge' });
          applyTheme();
          UP.views.jahr.resetScroll();
          toast('ok', `${U.plural(n, 'Jahr', 'Jahre')} eingelesen.`, { action: { label: 'Rückgängig', fn: doUndo } });
        } catch (err) {
          toast('danger', `Import fehlgeschlagen: ${err.message}`);
        }
      }
    };
    input.click();
  }

  function exportICS() {
    const yd = S.currentYear();
    const stamp = new Date().toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
    const lines = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Urlaubsplaner//DE', 'CALSCALE:GREGORIAN',
      'METHOD:PUBLISH', `X-WR-CALNAME:Abwesenheiten ${S.year()}`,
    ];
    const enc = s => String(s).replace(/([,;\\])/g, '\\$1').replace(/\n/g, '\\n');

    for (const a of yd.absences) {
      if (a.status === 'abgelehnt') continue;
      const p = S.personById(a.personId);
      if (!p) continue;
      const d = S.deptById(p.deptId);
      lines.push('BEGIN:VEVENT',
        `UID:${a.id}@urlaubsplaner`,
        `DTSTAMP:${stamp}`,
        `DTSTART;VALUE=DATE:${a.start.replace(/-/g, '')}`,
        `DTEND;VALUE=DATE:${U.addISO(a.end, 1).replace(/-/g, '')}`,
        `SUMMARY:${enc(`${p.name} – ${S.TYPES[a.type].label}`)}`,
        `DESCRIPTION:${enc([d ? `Abteilung: ${d.name}` : '', `Status: ${S.STATUS[a.status].label}`,
          `Arbeitstage: ${U.num(S.workdaysOf(a))}`, a.note].filter(Boolean).join('\n'))}`,
        'TRANSP:TRANSPARENT',
        a.status === 'beantragt' ? 'STATUS:TENTATIVE' : 'STATUS:CONFIRMED',
        'END:VEVENT');
    }
    lines.push('END:VCALENDAR');

    // iCalendar erlaubt höchstens 75 Oktette je Zeile; längere werden mit
    // einem führenden Leerzeichen umgebrochen.
    const fold = line => {
      const bytes = new TextEncoder().encode(line);
      if (bytes.length <= 75) return line;
      const out = [];
      let cur = '', curLen = 0, limit = 75;
      for (const ch of line) {
        const n = new TextEncoder().encode(ch).length;
        if (curLen + n > limit) { out.push(cur); cur = ' '; curLen = 1; limit = 74; }
        cur += ch; curLen += n;
      }
      out.push(cur);
      return out.join('\r\n');
    };
    U.download(`Abwesenheiten_${S.year()}.ics`, lines.map(fold).join('\r\n'), 'text/calendar');
    toast('ok', 'Kalenderdatei erstellt – lässt sich in Outlook oder Google Kalender einlesen.');
  }

  /* ═══ Hilfe ═════════════════════════════════════════════════════════ */
  function showHelp() {
    const k = s => el('span.kbd', {}, s);
    const row = (keys, text) => el('div.mrow', {},
      el('div', { style: { display: 'flex', gap: '4px', flex: '0 0 132px' } }, keys),
      el('div', { style: { fontSize: '13px' } }, text));

    const m = modal({
      title: 'Hilfe & Tastenkürzel', size: 'wide',
      body: el('div', {},
        el('div.sec-title', {}, 'So planst du'),
        el('div.mlist', {},
          tip('1', 'Abteilungen anlegen', 'Im Menü unter „Abteilungen“ oder in der Team-Ansicht. Jede Abteilung bekommt einen Grenzwert: wie viele Personen dort höchstens gleichzeitig fehlen dürfen.'),
          tip('2', 'Personen zuordnen', 'In der Team-Ansicht lassen sich Personenkarten per Drag & Drop zwischen Abteilungen ziehen. In der Jahresansicht funktioniert das ebenfalls: Namen links anfassen und auf eine andere Abteilung ziehen.'),
          tip('3', 'Urlaub eintragen', 'In der Jahres- oder Monatsansicht einfach in der Zeile der Person über den gewünschten Zeitraum ziehen. Balken lassen sich verschieben, an den Rändern verlängern und per Klick bearbeiten.'),
          tip('4', 'Überschneidungen prüfen', 'Die Zahl im Reiter „Überschneidungen“ zeigt, an wie vielen Zeiträumen zu viele Leute gleichzeitig weg wären. Schon beim Eintragen warnt der Planer, bevor gespeichert wird.'),
          tip('5', 'Jahre archivieren', 'Über die Jahreszahl oben links lassen sich Jahre wechseln und neue anlegen – wahlweise mit dem Team des Vorjahres und dem Resturlaub als Übertrag. Alte Jahre bleiben dauerhaft einsehbar.')),

        el('div.sec-title', { style: { marginTop: '20px' } }, 'Tastenkürzel'),
        el('div.mlist', {},
          row([k('N')], 'Neue Abwesenheit'),
          row([k('T')], 'Zum heutigen Tag springen'),
          row([k('1'), '–', k('5')], 'Ansicht wechseln'),
          row([k('+'), k('−')], 'Zeitachse zoomen'),
          row([k('←'), k('→')], 'Monat blättern (Monatsansicht)'),
          row([k('Strg'), k('←'), k('→')], 'Jahr wechseln'),
          row([k('/')], 'Personensuche'),
          row([k('Strg'), k('Z')], 'Rückgängig'),
          row([k('Strg'), k('S')], 'Sicherung speichern'),
          row([k('Esc')], 'Dialog schließen · laufendes Ziehen abbrechen'),
          row([k('?')], 'Diese Hilfe')),

        storageNote()),
      footer: [el('div.spacer'), el('button.primary-btn', { text: 'Verstanden', onclick: () => m.close() })],
    });

    function storageNote() {
      const texts = {
        server: 'In der Datenbank auf dem Rechner, der den Planer bereitstellt. Jede Änderung wird dort ' +
          'sofort gespeichert; andere Geräte übernehmen sie innerhalb weniger Sekunden. Fällt die ' +
          'Verbindung aus, wird im Browser weitergearbeitet und alles nachgetragen, sobald der Server ' +
          'wieder erreichbar ist.',
        drive: 'Als eine Datei in deinem eigenen Google Drive. Alle Geräte arbeiten auf derselben Datei; ' +
          'Änderungen werden sofort hochgeladen und von den anderen Geräten in Sekunden übernommen. ' +
          'Ohne Verbindung wird im Browser weitergearbeitet und später nachgetragen.',
        local: 'Ausschließlich in diesem Browser auf diesem Gerät. Es gibt keinen Server und keine Anmeldung. ' +
          'Lege regelmäßig eine Sicherung an (Menü → „Sicherung speichern“), besonders bevor du den ' +
          'Browser-Verlauf löschst.',
      };
      return el('div.note-box', { style: { marginTop: '18px' } },
        el('span.ico', { html: U.icon('info', 15) }),
        el('div', {}, el('b', {}, 'Wo liegen die Daten? '),
          texts[UP.sync.mode] || texts.local,
          ' Wechseln lässt sich das jederzeit über das Menü unter „Speicherort“.'));
    }

    function tip(n, title, text) {
      return el('div.mrow', {},
        el('div', {
          style: {
            width: '26px', height: '26px', borderRadius: '8px', flex: '0 0 auto',
            display: 'grid', placeItems: 'center', background: 'var(--primary-soft)',
            color: 'var(--primary)', fontWeight: '800', fontSize: '12px',
          }
        }, n),
        el('div.mrow-main', {},
          el('div.mrow-title', {}, title),
          el('div.mrow-sub', { style: { lineHeight: '1.5' } }, text)));
    }
  }

  /* ═══ Öffentlich ════════════════════════════════════════════════════ */
  return {
    init, render, toast, showHovercard, hideHovercard, emptyState, requireUnlocked,
    editAbsence, editPerson, editDepartment, openPerson, openPeople, openDepartments,
    openSettings, openClosures, openYearMenu, showDayDetail, showHelp,
    openSyncPanel, openStorageDialog, openDriveSetup,
    afterAbsenceChange, doUndo, doRedo, confirmBox, modal, popover,
    exportBackup, importBackup, exportICS,
  };
})();

document.addEventListener('DOMContentLoaded', UP.app.init);
