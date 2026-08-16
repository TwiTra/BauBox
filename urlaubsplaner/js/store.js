/* ═══════════════════════════════════════════════════════════════════════
   store.js – Datenmodell, Speicherung, Undo/Redo und Auswertungen
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.store = (function () {
  const U = UP.util;
  const KEY = 'urlaubsplaner.v1';
  const MAX_UNDO = 60;

  /* ── Abwesenheitsarten ──────────────────────────────────────────────── */
  const TYPES = {
    urlaub:      { label: 'Urlaub',            short: 'U',  color: '#1f9d76', counts: true,  quota: true  },
    resturlaub:  { label: 'Resturlaub',        short: 'RU', color: '#2f7f9d', counts: true,  quota: true  },
    sonderurlaub:{ label: 'Sonderurlaub',      short: 'SU', color: '#8a6bd6', counts: true,  quota: false },
    gleitzeit:   { label: 'Überstunden',       short: 'ÜS', color: '#c98a1f', counts: true,  quota: false },
    krank:       { label: 'Krank',             short: 'K',  color: '#d4443b', counts: true,  quota: false },
    fortbildung: { label: 'Fortbildung',       short: 'FB', color: '#3f7fd1', counts: true,  quota: false },
    elternzeit:  { label: 'Elternzeit',        short: 'EZ', color: '#c9558f', counts: true,  quota: false },
    homeoffice:  { label: 'Homeoffice',        short: 'HO', color: '#6b7f8c', counts: false, quota: false },
  };
  const TYPE_ORDER = Object.keys(TYPES);

  const STATUS = {
    beantragt:  { label: 'Beantragt',  short: 'offen' },
    genehmigt:  { label: 'Genehmigt',  short: 'ok'    },
    abgelehnt:  { label: 'Abgelehnt',  short: 'abgel.'},
  };

  /* ── Standardzustand ────────────────────────────────────────────────── */
  const thisYear = new Date().getFullYear();

  function emptyYear() {
    return { locked: false, departments: [], people: [], absences: [], closures: [] };
  }

  function defaultState() {
    return {
      v: 1,
      settings: {
        region: 'DE-NW',
        theme: 'auto',
        defaultEntitlement: 30,
        defaultMaxAbsent: 2,
        defaultStatus: 'genehmigt',
        countHalfAsFull: true,
        showWeeks: true,
        showBridges: true,
      },
      ui: {
        year: thisYear,
        view: 'jahr',
        month: new Date().getMonth(),
        zoom: 2,
        quickType: 'urlaub',
        filterType: 'alle',
        search: '',
      },
      years: { [thisYear]: emptyYear() },
    };
  }

  let state = defaultState();
  const undoStack = [];
  const redoStack = [];
  const listeners = {};
  let cache = {};

  /* ── Pub/Sub ────────────────────────────────────────────────────────── */
  function on(evt, fn) { (listeners[evt] ||= []).push(fn); return () => off(evt, fn); }
  function off(evt, fn) { listeners[evt] = (listeners[evt] || []).filter(f => f !== fn); }
  function emit(evt, payload) { (listeners[evt] || []).forEach(f => f(payload)); }

  /* ── Speichern / Laden ──────────────────────────────────────────────── */
  const persist = U.debounce(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
    } catch (e) {
      console.warn('Speichern fehlgeschlagen', e);
      emit('storage-error', e);
    }
  }, 250);

  function load() {
    let raw = null;
    try { raw = localStorage.getItem(KEY); } catch (e) { /* Privatmodus */ }
    if (!raw) return false;
    try {
      const parsed = JSON.parse(raw);
      state = migrate(parsed);
      cache = {};
      return true;
    } catch (e) {
      console.error('Gespeicherte Daten unlesbar', e);
      return false;
    }
  }

  function migrate(data) {
    const base = defaultState();
    const s = {
      v: 1,
      settings: { ...base.settings, ...(data.settings || {}) },
      ui: { ...base.ui, ...(data.ui || {}) },
      years: {},
    };
    for (const [y, yd] of Object.entries(data.years || {})) {
      s.years[y] = {
        locked: !!yd.locked,
        departments: (yd.departments || []).map(d => ({
          id: d.id || U.uid('d'), name: d.name || 'Abteilung',
          color: d.color || U.DEPT_COLORS[0],
          maxAbsent: Number.isFinite(d.maxAbsent) ? d.maxAbsent : 2,
          collapsed: !!d.collapsed,
        })),
        people: (yd.people || []).map(p => ({
          id: p.id || U.uid('p'), name: p.name || 'Unbenannt',
          deptId: p.deptId ?? null, role: p.role || '',
          entitlement: Number.isFinite(p.entitlement) ? p.entitlement : base.settings.defaultEntitlement,
          carryover: Number.isFinite(p.carryover) ? p.carryover : 0,
          color: p.color || null,
        })),
        absences: (yd.absences || []).map(a => ({
          id: a.id || U.uid('a'), personId: a.personId,
          type: TYPES[a.type] ? a.type : 'urlaub',
          status: STATUS[a.status] ? a.status : 'genehmigt',
          start: a.start, end: a.end,
          halfStart: !!a.halfStart, halfEnd: !!a.halfEnd,
          note: a.note || '',
        })).filter(a => a.personId && a.start && a.end),
        closures: (yd.closures || []).map(c => ({
          id: c.id || U.uid('c'), name: c.name || 'Betriebsruhe',
          start: c.start, end: c.end,
        })).filter(c => c.start && c.end),
      };
    }
    if (!Object.keys(s.years).length) s.years[thisYear] = emptyYear();
    if (!s.years[s.ui.year]) s.ui.year = Number(Object.keys(s.years).sort().pop());
    return s;
  }

  /* ── Mutationen mit Undo ────────────────────────────────────────────── */
  const clone = o => JSON.parse(JSON.stringify(o));

  /**
   * Alle schreibenden Zugriffe laufen hierüber: Snapshot → Änderung → Speichern → Render.
   * @param {string} label  Beschreibung für die Rückgängig-Anzeige
   * @param {Function} fn   Erhält den Jahresdatensatz; false ⇒ Abbruch ohne Undo-Eintrag
   */
  function commit(label, fn) {
    const snapshot = { years: clone(state.years), label };
    const result = fn(currentYear(), state);
    if (result === false) return false;
    undoStack.push(snapshot);
    if (undoStack.length > MAX_UNDO) undoStack.shift();
    redoStack.length = 0;
    cache = {};
    persist();
    emit('change', { label });
    return true;
  }

  /** Änderung ohne Undo-Eintrag (Ansichtszustand, Einstellungen) */
  function set(fn, { silent = false } = {}) {
    fn(state);
    cache = {};
    persist();
    if (!silent) emit('change', {});
  }

  function undo() {
    if (!undoStack.length) return false;
    const snap = undoStack.pop();
    redoStack.push({ years: clone(state.years), label: snap.label });
    state.years = snap.years;
    cache = {};
    persist();
    emit('change', { undo: true, label: snap.label });
    return snap.label;
  }

  function redo() {
    if (!redoStack.length) return false;
    const snap = redoStack.pop();
    undoStack.push({ years: clone(state.years), label: snap.label });
    state.years = snap.years;
    cache = {};
    persist();
    emit('change', { redo: true, label: snap.label });
    return snap.label;
  }

  const canUndo = () => undoStack.length > 0;
  const canRedo = () => redoStack.length > 0;
  const lastUndoLabel = () => undoStack.length ? undoStack[undoStack.length - 1].label : '';

  /* ── Zugriff ────────────────────────────────────────────────────────── */
  const year = () => state.ui.year;
  const currentYear = () => state.years[state.ui.year] || (state.years[state.ui.year] = emptyYear());
  const yearData = y => state.years[y];
  const listYears = () => Object.keys(state.years).map(Number).sort((a, b) => a - b);
  const isLocked = () => !!currentYear().locked;

  function setYear(y) {
    if (!state.years[y]) return false;
    set(s => { s.ui.year = Number(y); });
    return true;
  }

  /**
   * Legt ein Jahr an. Struktur (Abteilungen + Personen) wird aus `copyFrom`
   * übernommen, Abwesenheiten nie – die werden jährlich neu geplant.
   * `carryRemaining`: Resturlaub des Quelljahres als Übertrag eintragen.
   */
  function createYear(y, { copyFrom = null, carryRemaining = false } = {}) {
    y = Number(y);
    if (state.years[y]) return false;
    const fresh = emptyYear();
    const src = copyFrom != null ? state.years[copyFrom] : null;
    if (src) {
      fresh.departments = clone(src.departments);
      fresh.people = clone(src.people).map(p => {
        const carry = carryRemaining ? Math.max(0, remainingIn(copyFrom, p.id)) : 0;
        return { ...p, carryover: Math.round(carry * 2) / 2 };
      });
    }
    const snapshot = { years: clone(state.years), label: `Jahr ${y} angelegt` };
    undoStack.push(snapshot);
    redoStack.length = 0;
    state.years[y] = fresh;
    state.ui.year = y;
    cache = {};
    persist();
    emit('change', { label: `Jahr ${y} angelegt` });
    return true;
  }

  function deleteYear(y) {
    if (Object.keys(state.years).length <= 1) return false;
    return commit(`Jahr ${y} gelöscht`, (_, s) => {
      delete s.years[y];
      if (s.ui.year == y) s.ui.year = Number(Object.keys(s.years).sort().pop());
    });
  }

  /* ── Kalender (gecacht) ─────────────────────────────────────────────── */
  function calendar(y = state.ui.year) {
    const k = `cal:${y}:${state.settings.region}`;
    return cache[k] ||= UP.holidays.calendar(Number(y), state.settings.region);
  }

  /** Index eines ISO-Datums im Jahreskalender, oder −1 */
  function dayIndex(isoStr, y = state.ui.year) {
    const d = UP.util.parseISO(isoStr);
    if (d.getFullYear() !== Number(y)) return -1;
    return UP.util.diffDays(`${y}-01-01`, isoStr);
  }

  /* ── Abteilungen ────────────────────────────────────────────────────── */
  function addDepartment(name, opts = {}) {
    const yd = currentYear();
    const dep = {
      id: U.uid('d'),
      name: name || `Abteilung ${yd.departments.length + 1}`,
      color: opts.color || U.DEPT_COLORS[yd.departments.length % U.DEPT_COLORS.length],
      maxAbsent: Number.isFinite(opts.maxAbsent) ? opts.maxAbsent : state.settings.defaultMaxAbsent,
      collapsed: false,
    };
    commit(`Abteilung „${dep.name}“ angelegt`, yd2 => { yd2.departments.push(dep); });
    return dep;
  }

  function updateDepartment(id, patch) {
    return commit('Abteilung geändert', yd => {
      const d = yd.departments.find(x => x.id === id);
      if (!d) return false;
      Object.assign(d, patch);
    });
  }

  /** Löscht die Abteilung; Personen wandern in „Ohne Abteilung“. */
  function deleteDepartment(id) {
    return commit('Abteilung gelöscht', yd => {
      const d = yd.departments.find(x => x.id === id);
      if (!d) return false;
      yd.departments = yd.departments.filter(x => x.id !== id);
      yd.people.forEach(p => { if (p.deptId === id) p.deptId = null; });
    });
  }

  function moveDepartment(id, toIndex) {
    return commit('Abteilung verschoben', yd => {
      const from = yd.departments.findIndex(x => x.id === id);
      if (from < 0) return false;
      const [d] = yd.departments.splice(from, 1);
      yd.departments.splice(U.clamp(toIndex, 0, yd.departments.length), 0, d);
    });
  }

  function toggleCollapse(id) {
    set(s => {
      const yd = s.years[s.ui.year];
      const d = yd.departments.find(x => x.id === id);
      if (d) d.collapsed = !d.collapsed;
    });
  }

  /* ── Personen ───────────────────────────────────────────────────────── */
  function addPerson(name, deptId, opts = {}) {
    const p = {
      id: U.uid('p'),
      name: name || 'Neue Person',
      deptId: deptId ?? null,
      role: opts.role || '',
      entitlement: Number.isFinite(opts.entitlement) ? opts.entitlement : state.settings.defaultEntitlement,
      carryover: Number.isFinite(opts.carryover) ? opts.carryover : 0,
      color: opts.color || null,
    };
    commit(`„${p.name}“ hinzugefügt`, yd => { yd.people.push(p); });
    return p;
  }

  function updatePerson(id, patch) {
    return commit('Person geändert', yd => {
      const p = yd.people.find(x => x.id === id);
      if (!p) return false;
      Object.assign(p, patch);
    });
  }

  function deletePerson(id) {
    return commit('Person gelöscht', yd => {
      const p = yd.people.find(x => x.id === id);
      if (!p) return false;
      yd.people = yd.people.filter(x => x.id !== id);
      yd.absences = yd.absences.filter(a => a.personId !== id);
    });
  }

  /**
   * Verschiebt eine Person in eine Abteilung – optional an eine bestimmte
   * Position innerhalb der Zielabteilung (Drag & Drop).
   */
  function movePerson(personId, deptId, beforePersonId = null) {
    return commit('Person verschoben', yd => {
      const idx = yd.people.findIndex(p => p.id === personId);
      if (idx < 0) return false;
      const [p] = yd.people.splice(idx, 1);
      p.deptId = deptId ?? null;
      let insertAt = yd.people.length;
      if (beforePersonId) {
        const bi = yd.people.findIndex(x => x.id === beforePersonId);
        if (bi >= 0) insertAt = bi;
      } else {
        // ans Ende der Zielabteilung
        let last = -1;
        yd.people.forEach((x, i) => { if ((x.deptId ?? null) === (deptId ?? null)) last = i; });
        insertAt = last + 1 || yd.people.length;
      }
      yd.people.splice(insertAt, 0, p);
    });
  }

  const peopleOf = (deptId, yd = currentYear()) =>
    yd.people.filter(p => (p.deptId ?? null) === (deptId ?? null));

  const personById = (id, yd = currentYear()) => yd.people.find(p => p.id === id);
  const deptById = (id, yd = currentYear()) => yd.departments.find(d => d.id === id) || null;

  /* ── Abwesenheiten ──────────────────────────────────────────────────── */
  function normalizeRange(a) {
    if (U.diffDays(a.start, a.end) < 0) { const t = a.start; a.start = a.end; a.end = t; }
    return a;
  }

  function addAbsence(data) {
    const a = normalizeRange({
      id: U.uid('a'),
      personId: data.personId,
      type: TYPES[data.type] ? data.type : 'urlaub',
      status: STATUS[data.status] ? data.status : state.settings.defaultStatus,
      start: data.start, end: data.end,
      halfStart: !!data.halfStart, halfEnd: !!data.halfEnd,
      note: data.note || '',
    });
    commit(`${TYPES[a.type].label} eingetragen`, yd => { yd.absences.push(a); });
    return a;
  }

  function updateAbsence(id, patch, label = 'Abwesenheit geändert') {
    return commit(label, yd => {
      const a = yd.absences.find(x => x.id === id);
      if (!a) return false;
      Object.assign(a, patch);
      normalizeRange(a);
    });
  }

  function deleteAbsence(id) {
    return commit('Abwesenheit gelöscht', yd => {
      const before = yd.absences.length;
      yd.absences = yd.absences.filter(a => a.id !== id);
      if (yd.absences.length === before) return false;
    });
  }

  function absencesOf(personId, yd = currentYear()) {
    return yd.absences.filter(a => a.personId === personId)
      .sort((a, b) => a.start.localeCompare(b.start));
  }

  /* ── Betriebsruhe ───────────────────────────────────────────────────── */
  function addClosure(name, start, end) {
    const c = { id: U.uid('c'), name: name || 'Betriebsruhe', start, end };
    if (U.diffDays(c.start, c.end) < 0) { const t = c.start; c.start = c.end; c.end = t; }
    commit(`Betriebsruhe „${c.name}“ angelegt`, yd => { yd.closures.push(c); });
    return c;
  }
  function deleteClosure(id) {
    return commit('Betriebsruhe gelöscht', yd => { yd.closures = yd.closures.filter(c => c.id !== id); });
  }

  /* ── Berechnungen ───────────────────────────────────────────────────── */

  /** Arbeitstage einer Abwesenheit (Wochenenden/Feiertage ausgenommen). */
  function workdaysOf(a, y = state.ui.year) {
    const cal = calendar(y);
    let s = dayIndex(a.start, y), e = dayIndex(a.end, y);
    // Zeiträume, die über den Jahreswechsel ragen, werden am Jahr beschnitten
    if (s < 0) s = U.parseISO(a.start) < new Date(Number(y), 0, 1) ? 0 : -1;
    if (e < 0) e = U.parseISO(a.end) > new Date(Number(y), 11, 31) ? cal.length - 1 : -1;
    if (s < 0 || e < 0 || e < s) return 0;
    let n = 0;
    for (let i = s; i <= e; i++) if (cal[i].workday) n++;
    if (n === 0) return 0;
    if (a.halfStart && cal[s].workday) n -= 0.5;
    if (a.halfEnd && e !== s && cal[e].workday) n -= 0.5;
    if (a.halfStart && a.halfEnd && e === s) n += 0.5;   // ein halber Tag bleibt ein halber
    return Math.max(0, n);
  }

  /** Urlaubskonto einer Person im aktuellen Jahr. */
  function quota(personId, y = state.ui.year) {
    const yd = state.years[y];
    if (!yd) return { entitlement: 0, carryover: 0, total: 0, approved: 0, pending: 0, planned: 0, remaining: 0, other: 0 };
    const p = yd.people.find(x => x.id === personId);
    if (!p) return { entitlement: 0, carryover: 0, total: 0, approved: 0, pending: 0, planned: 0, remaining: 0, other: 0 };
    let approved = 0, pending = 0, other = 0;
    for (const a of yd.absences) {
      if (a.personId !== personId || a.status === 'abgelehnt') continue;
      const d = workdaysOf(a, y);
      if (TYPES[a.type].quota) {
        if (a.status === 'genehmigt') approved += d; else pending += d;
      } else if (TYPES[a.type].counts) other += d;
    }
    const total = (p.entitlement || 0) + (p.carryover || 0);
    const planned = approved + pending;
    return {
      entitlement: p.entitlement || 0, carryover: p.carryover || 0, total,
      approved, pending, planned, other,
      remaining: Math.round((total - planned) * 2) / 2,
    };
  }

  const remainingIn = (y, personId) => quota(personId, y).remaining;

  /**
   * Belegung pro Abteilung: Array[deptId][tagIndex] = Anzahl abwesender Personen.
   * Nur Arten mit `counts: true` und nicht abgelehnte Einträge zählen.
   */
  function occupancy(y = state.ui.year) {
    const k = `occ:${y}:${state.settings.region}`;
    if (cache[k]) return cache[k];
    const yd = state.years[y];
    const cal = calendar(y);
    const n = cal.length;
    const byDept = {};
    const byPersonDay = {};       // personId → Set der belegten Tagesindizes
    const total = new Array(n).fill(0);

    const keys = yd.departments.map(d => d.id).concat(['__none__']);
    keys.forEach(id => byDept[id] = new Array(n).fill(0));

    for (const a of (yd?.absences || [])) {
      if (a.status === 'abgelehnt' || !TYPES[a.type].counts) continue;
      const p = yd.people.find(x => x.id === a.personId);
      if (!p) continue;
      const key = p.deptId ?? '__none__';
      if (!byDept[key]) byDept[key] = new Array(n).fill(0);
      let s = Math.max(0, dayIndex(a.start, y) < 0 ? 0 : dayIndex(a.start, y));
      let e = dayIndex(a.end, y);
      if (e < 0) e = U.parseISO(a.end) > new Date(Number(y), 11, 31) ? n - 1 : -1;
      if (e < 0) continue;
      const seen = (byPersonDay[a.personId] ||= new Set());
      for (let i = s; i <= e && i < n; i++) {
        if (!cal[i].workday) continue;      // an freien Tagen ist niemand „zusätzlich weg“
        if (seen.has(i)) continue;          // Doppelzählung bei Überlappung vermeiden
        seen.add(i);
        byDept[key][i]++;
        total[i]++;
      }
    }
    return cache[k] = { byDept, total, byPersonDay };
  }

  /** Personen einer Abteilung, die an Tagesindex `i` abwesend sind. */
  function absentOn(i, deptId, y = state.ui.year) {
    const yd = state.years[y];
    const cal = calendar(y);
    const day = cal[i];
    if (!day) return [];
    const out = [];
    const seen = new Set();
    for (const a of yd.absences) {
      if (a.status === 'abgelehnt' || !TYPES[a.type].counts) continue;
      if (a.start > day.iso || a.end < day.iso) continue;
      const p = yd.people.find(x => x.id === a.personId);
      if (!p) continue;
      if (deptId !== undefined && (p.deptId ?? '__none__') !== deptId) continue;
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      out.push({ person: p, absence: a });
    }
    return out;
  }

  /**
   * Überschneidungs-Analyse: zusammenhängende Zeiträume, in denen die
   * erlaubte Zahl gleichzeitig Abwesender überschritten wird.
   */
  function conflicts(y = state.ui.year) {
    const k = `cf:${y}:${state.settings.region}`;
    if (cache[k]) return cache[k];
    const yd = state.years[y];
    const cal = calendar(y);
    const occ = occupancy(y);
    const out = [];

    const groups = yd.departments.map(d => ({ id: d.id, name: d.name, color: d.color, max: d.maxAbsent, size: peopleOf(d.id, yd).length }));
    const orphan = peopleOf(null, yd);
    if (orphan.length) groups.push({ id: '__none__', name: 'Ohne Abteilung', color: '#8d97ab', max: state.settings.defaultMaxAbsent, size: orphan.length });

    for (const g of groups) {
      const arr = occ.byDept[g.id] || [];
      let run = null;
      for (let i = 0; i < cal.length; i++) {
        const over = cal[i].workday && arr[i] > g.max;
        if (over) {
          if (!run) run = { from: i, to: i, peak: arr[i], days: 1 };
          else { run.to = i; run.peak = Math.max(run.peak, arr[i]); run.days++; }
        } else if (run) { out.push(finish(g, run)); run = null; }
      }
      if (run) out.push(finish(g, run));
    }

    function finish(g, run) {
      const people = new Map();
      for (let i = run.from; i <= run.to; i++) {
        for (const { person, absence } of absentOn(i, g.id, y)) {
          if (!people.has(person.id)) people.set(person.id, { person, absence });
        }
      }
      return {
        deptId: g.id, deptName: g.name, deptColor: g.color, max: g.max, teamSize: g.size,
        from: cal[run.from].iso, to: cal[run.to].iso,
        fromIdx: run.from, toIdx: run.to,
        workdays: run.days, peak: run.peak,
        over: run.peak - g.max,
        people: [...people.values()],
      };
    }

    out.sort((a, b) => (b.over * 100 + b.workdays) - (a.over * 100 + a.workdays) || a.fromIdx - b.fromIdx);
    return cache[k] = out;
  }

  /** Menge der Tagesindizes, an denen ein Konflikt besteht (für die Balken-Markierung). */
  function conflictDaySet(y = state.ui.year) {
    const k = `cfd:${y}:${state.settings.region}`;
    if (cache[k]) return cache[k];
    const set = new Set();
    for (const c of conflicts(y)) {
      for (let i = c.fromIdx; i <= c.toIdx; i++) set.add(`${c.deptId}:${i}`);
    }
    return cache[k] = set;
  }

  /**
   * Prüft einen geplanten Zeitraum, bevor er gespeichert wird.
   * @returns {{days:Array, worst:number, max:number, over:boolean}}
   */
  function previewImpact(personId, start, end, { ignoreAbsenceId = null, y = state.ui.year } = {}) {
    const yd = state.years[y];
    const cal = calendar(y);
    const p = yd.people.find(x => x.id === personId);
    const dept = p ? (p.deptId ?? '__none__') : '__none__';
    const d = yd.departments.find(x => x.id === dept);
    const max = d ? d.maxAbsent : state.settings.defaultMaxAbsent;

    let s = dayIndex(start, y), e = dayIndex(end, y);
    if (s < 0) s = 0;
    if (e < 0) e = cal.length - 1;
    const days = [];
    let worst = 0;
    for (let i = s; i <= e && i < cal.length; i++) {
      if (!cal[i].workday) continue;
      const others = absentOn(i, dept, y)
        .filter(x => x.person.id !== personId && x.absence.id !== ignoreAbsenceId);
      const count = others.length + 1;
      worst = Math.max(worst, count);
      if (count > max) days.push({ i, iso: cal[i].iso, count, others: others.map(o => o.person) });
    }
    return { days, worst, max, over: days.length > 0, deptName: d ? d.name : 'Ohne Abteilung' };
  }

  /* ── Demodaten ──────────────────────────────────────────────────────── */
  function seedDemo() {
    const y = state.ui.year;
    const cal = calendar(y);
    const yd = currentYear();

    const snapshot = { years: clone(state.years), label: 'Demodaten geladen' };
    undoStack.push(snapshot);
    redoStack.length = 0;

    yd.departments = []; yd.people = []; yd.absences = []; yd.closures = [];

    const defs = [
      { name: 'Bauleitung',   max: 1, people: [['Miriam Kessler', 'Bauleiterin'], ['Tobias Reinhardt', 'Bauleiter'], ['Sven Lorenz', 'Polier']] },
      { name: 'Hochbau',      max: 3, people: [['Ahmet Yildiz', 'Maurer'], ['Piotr Nowak', 'Maurer'], ['Lukas Brandt', 'Betonbauer'], ['Dario Conti', 'Betonbauer'], ['Marek Wójcik', 'Facharbeiter'], ['Jonas Hesse', 'Azubi']] },
      { name: 'Tiefbau',      max: 2, people: [['Frank Osterloh', 'Baggerfahrer'], ['Kevin Sander', 'Rohrleger'], ['Igor Petrov', 'Rohrleger'], ['Nils Achterberg', 'Facharbeiter']] },
      { name: 'Werkstatt',    max: 1, people: [['Heiko Baumann', 'Mechaniker'], ['Ceyhan Demir', 'Schweißer']] },
      { name: 'Verwaltung',   max: 2, people: [['Sabine Vogt', 'Buchhaltung'], ['Nadja Wehrle', 'Lohnbuchhaltung'], ['Christoph Behr', 'Kalkulation'], ['Elif Karaca', 'Sekretariat']] },
    ];

    defs.forEach((d, di) => {
      const dep = {
        id: U.uid('d'), name: d.name,
        color: U.DEPT_COLORS[di % U.DEPT_COLORS.length],
        maxAbsent: d.max, collapsed: false,
      };
      yd.departments.push(dep);
      d.people.forEach(([name, role]) => {
        yd.people.push({
          id: U.uid('p'), name, deptId: dep.id, role,
          entitlement: role === 'Azubi' ? 28 : 30,
          carryover: [0, 0, 2, 3, 0, 5][Math.floor(Math.random() * 6)],
          color: null,
        });
      });
    });

    // Plausible Urlaubsverteilung: Schwerpunkte Sommer, Herbstferien, Weihnachten
    const spots = [
      [5, 20, 10], [6, 1, 14], [6, 15, 12], [6, 28, 10], [7, 3, 14], [7, 17, 10],
      [3, 7, 5], [4, 12, 4], [9, 6, 5], [9, 20, 7], [10, 3, 4], [11, 22, 8], [1, 12, 5], [2, 9, 4],
    ];
    const rand = (n) => Math.floor(Math.random() * n);
    yd.people.forEach((p, pi) => {
      const n = 2 + rand(2);
      const used = new Set();
      for (let k = 0; k < n; k++) {
        const sp = spots[(pi * 3 + k * 5 + rand(3)) % spots.length];
        if (used.has(sp)) continue;
        used.add(sp);
        const start = new Date(y, sp[0], Math.max(1, sp[1] + rand(5) - 2));
        if (start.getFullYear() !== y) continue;
        const end = U.addDays(start, sp[2] - 1);
        if (end.getFullYear() !== y) continue;
        yd.absences.push({
          id: U.uid('a'), personId: p.id, type: 'urlaub',
          status: rand(5) === 0 ? 'beantragt' : 'genehmigt',
          start: U.iso(start), end: U.iso(end),
          halfStart: false, halfEnd: false, note: '',
        });
      }
      if (rand(4) === 0) {
        const d0 = new Date(y, rand(11), 1 + rand(26));
        yd.absences.push({
          id: U.uid('a'), personId: p.id, type: rand(2) ? 'krank' : 'fortbildung',
          status: 'genehmigt', start: U.iso(d0), end: U.iso(U.addDays(d0, rand(4))),
          halfStart: false, halfEnd: false, note: '',
        });
      }
    });

    // Ein paar bewusst gesetzte Überschneidungen, damit die Prüfung im
    // Beispiel auch etwas zu zeigen hat.
    const overlapPlan = [
      ['Bauleitung', 0, 1, [7, 3], 9],   // zwei Bauleiter gleichzeitig im August
      ['Werkstatt',  0, 1, [9, 5], 7],   // beide Werkstattkräfte im Oktober
      ['Tiefbau',    0, 2, [6, 8], 12],  // drei von vier im Juli
    ];
    for (const [deptName, from, to, [mo, day], len] of overlapPlan) {
      const dep = yd.departments.find(d => d.name === deptName);
      if (!dep) continue;
      const members = yd.people.filter(p => p.deptId === dep.id);
      for (let k = from; k <= to && k < members.length; k++) {
        const start = new Date(y, mo, day + k);
        const end = U.addDays(start, len - 1);
        if (start.getFullYear() !== y || end.getFullYear() !== y) continue;
        const s = U.iso(start), e = U.iso(end);
        // zufällig erzeugte Einträge im selben Fenster entfernen, damit sich
        // die Balken einer Person nicht überlagern
        yd.absences = yd.absences.filter(a =>
          a.personId !== members[k].id || a.end < s || a.start > e);
        yd.absences.push({
          id: U.uid('a'), personId: members[k].id, type: 'urlaub', status: 'genehmigt',
          start: U.iso(start), end: U.iso(end), halfStart: false, halfEnd: false,
          note: '',
        });
      }
    }

    yd.closures.push({
      id: U.uid('c'), name: 'Betriebsruhe Weihnachten',
      start: `${y}-12-24`, end: `${y}-12-31`,
    });

    cache = {};
    persist();
    emit('change', { label: 'Demodaten geladen' });
  }

  function clearAll() {
    const snapshot = { years: clone(state.years), label: 'Alle Daten gelöscht' };
    undoStack.push(snapshot);
    redoStack.length = 0;
    state.years = { [state.ui.year]: emptyYear() };
    cache = {};
    persist();
    emit('change', { label: 'Alle Daten gelöscht' });
  }

  /* ── Abgleich mit dem Server ────────────────────────────────────────── */

  /** Der synchronisierte Teil des Zustands – ohne Ansichtszustand (`ui`). */
  function doc() {
    return clone({ settings: state.settings, years: state.years });
  }

  /**
   * Übernimmt einen Stand vom Server bzw. das Ergebnis einer Zusammenführung.
   * Die Ansicht (Jahr, Zoom, Suche) bleibt erhalten. Der Rückgängig-Verlauf
   * wird verworfen, weil er sich auf einen anderen Ausgangsstand bezöge.
   */
  function replaceDoc(next, { keepUndo = false } = {}) {
    const incoming = migrate({ settings: next.settings, years: next.years, ui: state.ui });
    state.settings = { ...state.settings, ...incoming.settings };
    state.years = incoming.years;
    if (!state.years[state.ui.year]) {
      const years = Object.keys(state.years);
      state.ui.year = years.length ? Number(years.sort().pop()) : thisYear;
      if (!state.years[state.ui.year]) state.years[state.ui.year] = emptyYear();
    }
    if (!keepUndo) { undoStack.length = 0; redoStack.length = 0; }
    cache = {};
    persist();
    emit('change', { remote: true });
  }

  /* ── Import / Export ────────────────────────────────────────────────── */
  function exportJSON() {
    return JSON.stringify({
      app: 'Urlaubsplaner', v: 1, exportedAt: new Date().toISOString(),
      settings: state.settings, years: state.years,
    }, null, 2);
  }

  function importJSON(text, { merge = false } = {}) {
    const data = JSON.parse(text);
    if (!data || typeof data !== 'object' || !data.years) throw new Error('Kein gültiger Urlaubsplaner-Export.');
    const snapshot = { years: clone(state.years), label: 'Daten importiert' };
    undoStack.push(snapshot);
    redoStack.length = 0;
    const incoming = migrate({ settings: data.settings, years: data.years, ui: state.ui });
    if (merge) {
      Object.assign(state.years, incoming.years);
    } else {
      state.years = incoming.years;
      state.settings = { ...state.settings, ...incoming.settings };
    }
    if (!state.years[state.ui.year]) state.ui.year = Number(Object.keys(state.years).sort().pop());
    cache = {};
    persist();
    emit('change', { label: 'Daten importiert' });
    return Object.keys(incoming.years).length;
  }

  return {
    TYPES, TYPE_ORDER, STATUS,
    get state() { return state; },
    get settings() { return state.settings; },
    get ui() { return state.ui; },
    on, off, emit, load, set, commit, undo, redo, canUndo, canRedo, lastUndoLabel,
    year, currentYear, yearData, listYears, setYear, createYear, deleteYear, isLocked,
    calendar, dayIndex,
    addDepartment, updateDepartment, deleteDepartment, moveDepartment, toggleCollapse,
    addPerson, updatePerson, deletePerson, movePerson, peopleOf, personById, deptById,
    addAbsence, updateAbsence, deleteAbsence, absencesOf,
    addClosure, deleteClosure,
    workdaysOf, quota, occupancy, absentOn, conflicts, conflictDaySet, previewImpact,
    seedDemo, clearAll, exportJSON, importJSON, emptyYear, doc, replaceDoc,
  };
})();
