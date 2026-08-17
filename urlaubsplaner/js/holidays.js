/* ═══════════════════════════════════════════════════════════════════════
   holidays.js – Gesetzliche Feiertage (DE/AT/CH) und Brückentage
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.holidays = (function () {
  const U = UP.util;

  /* ── Regionen ───────────────────────────────────────────────────────── */
  const REGIONS = {
    'DE-BW': 'Baden-Württemberg',      'DE-BY': 'Bayern',
    'DE-BE': 'Berlin',                 'DE-BB': 'Brandenburg',
    'DE-HB': 'Bremen',                 'DE-HH': 'Hamburg',
    'DE-HE': 'Hessen',                 'DE-MV': 'Mecklenburg-Vorpommern',
    'DE-NI': 'Niedersachsen',          'DE-NW': 'Nordrhein-Westfalen',
    'DE-RP': 'Rheinland-Pfalz',        'DE-SL': 'Saarland',
    'DE-SN': 'Sachsen',                'DE-ST': 'Sachsen-Anhalt',
    'DE-SH': 'Schleswig-Holstein',     'DE-TH': 'Thüringen',
    'AT':    'Österreich',             'CH':    'Schweiz (Bundesfeiertage)',
    'NONE':  'Keine Feiertage'
  };

  const REGION_GROUPS = [
    { label: 'Deutschland', keys: Object.keys(REGIONS).filter(k => k.startsWith('DE-')) },
    { label: 'Weitere',     keys: ['AT', 'CH', 'NONE'] }
  ];

  /* ── Ostersonntag (Meeus/Jones/Butcher, gregorianisch) ──────────────── */
  function easterSunday(year) {
    const a = year % 19;
    const b = Math.floor(year / 100), c = year % 100;
    const d = Math.floor(b / 4), e = b % 4;
    const f = Math.floor((b + 8) / 25);
    const g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4), k = c % 4;
    const l = (32 + 2 * e + 2 * i - h - k) % 7;
    const m = Math.floor((a + 11 * h + 22 * l) / 451);
    const n = h + l - 7 * m + 114;
    return new Date(year, Math.floor(n / 31) - 1, (n % 31) + 1);
  }

  /** Buß- und Bettag: letzter Mittwoch vor dem 23. November */
  function bussUndBettag(year) {
    const d = new Date(year, 10, 22);
    while (d.getDay() !== 3) d.setDate(d.getDate() - 1);
    return d;
  }

  const DE_ALL = ['DE-BW', 'DE-BY', 'DE-BE', 'DE-BB', 'DE-HB', 'DE-HH', 'DE-HE', 'DE-MV',
    'DE-NI', 'DE-NW', 'DE-RP', 'DE-SL', 'DE-SN', 'DE-ST', 'DE-SH', 'DE-TH'];

  /**
   * Alle Feiertage eines Jahres für eine Region.
   * @returns {Object} Map "YYYY-MM-DD" → { name, region }
   */
  function forYear(year, region) {
    const map = {};
    if (region === 'NONE') return map;

    const E = easterSunday(year);
    const rel = n => U.iso(U.addDays(E, n));
    const fix = (m, d) => `${year}-${U.pad(m)}-${U.pad(d)}`;
    const add = (dateStr, name, regions) => {
      if (regions && !regions.includes(region)) return;
      map[dateStr] = { name, date: dateStr };
    };

    if (region.startsWith('DE-')) {
      add(fix(1, 1),   'Neujahr');
      add(fix(1, 6),   'Heilige Drei Könige', ['DE-BW', 'DE-BY', 'DE-ST']);
      add(fix(3, 8),   'Internationaler Frauentag', ['DE-BE', 'DE-MV']);
      add(rel(-2),     'Karfreitag');
      add(rel(0),      'Ostersonntag', ['DE-BB']);
      add(rel(1),      'Ostermontag');
      add(fix(5, 1),   'Tag der Arbeit');
      add(rel(39),     'Christi Himmelfahrt');
      add(rel(49),     'Pfingstsonntag', ['DE-BB']);
      add(rel(50),     'Pfingstmontag');
      add(rel(60),     'Fronleichnam', ['DE-BW', 'DE-BY', 'DE-HE', 'DE-NW', 'DE-RP', 'DE-SL']);
      add(fix(8, 15),  'Mariä Himmelfahrt', ['DE-SL']);
      add(fix(9, 20),  'Weltkindertag', ['DE-TH']);
      add(fix(10, 3),  'Tag der Deutschen Einheit');
      add(fix(10, 31), 'Reformationstag',
        ['DE-BB', 'DE-HB', 'DE-HH', 'DE-MV', 'DE-NI', 'DE-SH', 'DE-SN', 'DE-ST', 'DE-TH']);
      add(fix(11, 1),  'Allerheiligen', ['DE-BW', 'DE-BY', 'DE-NW', 'DE-RP', 'DE-SL']);
      add(U.iso(bussUndBettag(year)), 'Buß- und Bettag', ['DE-SN']);
      add(fix(12, 25), '1. Weihnachtstag');
      add(fix(12, 26), '2. Weihnachtstag');
      // Einmaliger Feiertag: 75 Jahre Kriegsende (nur Berlin, 2020)
      if (year === 2020 && region === 'DE-BE') add(fix(5, 8), 'Tag der Befreiung');
    } else if (region === 'AT') {
      add(fix(1, 1),   'Neujahr');
      add(fix(1, 6),   'Heilige Drei Könige');
      add(rel(1),      'Ostermontag');
      add(fix(5, 1),   'Staatsfeiertag');
      add(rel(39),     'Christi Himmelfahrt');
      add(rel(50),     'Pfingstmontag');
      add(rel(60),     'Fronleichnam');
      add(fix(8, 15),  'Mariä Himmelfahrt');
      add(fix(10, 26), 'Nationalfeiertag');
      add(fix(11, 1),  'Allerheiligen');
      add(fix(12, 8),  'Mariä Empfängnis');
      add(fix(12, 25), 'Christtag');
      add(fix(12, 26), 'Stefanitag');
    } else if (region === 'CH') {
      add(fix(1, 1),   'Neujahr');
      add(rel(-2),     'Karfreitag');
      add(rel(1),      'Ostermontag');
      add(fix(5, 1),   'Tag der Arbeit');
      add(rel(39),     'Auffahrt');
      add(rel(50),     'Pfingstmontag');
      add(fix(8, 1),   'Bundesfeier');
      add(fix(12, 25), 'Weihnachten');
      add(fix(12, 26), 'Stephanstag');
    }
    return map;
  }

  /* ── Jahreskalender ─────────────────────────────────────────────────── */
  /**
   * Tages-Array für ein ganzes Jahr – Grundlage aller Ansichten.
   * @returns {Array} [{ i, iso, date, dow, month, dom, week, weekend, holiday, workday }]
   */
  function calendar(year, region) {
    const hol = forYear(year, region);
    const days = [];
    const d = new Date(year, 0, 1);
    let i = 0;
    while (d.getFullYear() === year) {
      const key = U.iso(d);
      const weekend = d.getDay() === 0 || d.getDay() === 6;
      const holiday = hol[key] || null;
      days.push({
        i, iso: key, date: new Date(d),
        dow: d.getDay(), month: d.getMonth(), dom: d.getDate(),
        week: U.isoWeek(d),
        weekend, holiday,
        workday: !weekend && !holiday
      });
      d.setDate(d.getDate() + 1);
      i++;
    }
    return days;
  }

  /* ── Brückentage ────────────────────────────────────────────────────── */
  /**
   * Findet Arbeitstage, die zwischen freien Tagen liegen.
   * @returns {Array} [{ days:[iso], cost, free, ratio, from, to, label }]
   */
  function bridges(days) {
    const out = [];
    let run = null;

    const freeRunBefore = idx => {
      let n = 0;
      for (let j = idx - 1; j >= 0 && !days[j].workday; j--) n++;
      return n;
    };
    const freeRunAfter = idx => {
      let n = 0;
      for (let j = idx + 1; j < days.length && !days[j].workday; j++) n++;
      return n;
    };

    for (let i = 0; i < days.length; i++) {
      if (days[i].workday) {
        if (!run) run = { start: i, end: i }; else run.end = i;
      } else if (run) {
        pushRun(run); run = null;
      }
    }
    if (run) pushRun(run);

    function pushRun(r) {
      const cost = r.end - r.start + 1;
      if (cost > 4) return;                       // längere Blöcke sind keine Brücken
      const before = freeRunBefore(r.start);
      const after = freeRunAfter(r.end);
      if (before === 0 || after === 0) return;     // muss beidseitig eingebettet sein
      const free = before + cost + after;
      const ratio = free / cost;
      if (ratio < 2.2) return;                     // lohnt sich sonst nicht
      const list = days.slice(r.start, r.end + 1);
      // Anlass benennen (der angrenzende Feiertag)
      let cause = null;
      for (let j = r.start - 1; j >= r.start - before; j--) if (days[j]?.holiday) { cause = days[j].holiday.name; break; }
      if (!cause) for (let j = r.end + 1; j <= r.end + after; j++) if (days[j]?.holiday) { cause = days[j].holiday.name; break; }
      if (!cause) return;                          // reine Wochenend-Lücke ignorieren
      out.push({
        days: list.map(x => x.iso),
        from: list[0].iso, to: list[list.length - 1].iso,
        cost, free, ratio, cause,
        freeFrom: days[r.start - before].iso,
        freeTo: days[Math.min(days.length - 1, r.end + after)].iso
      });
    }

    return out.sort((a, b) => b.ratio - a.ratio || U.diffDays(b.from, a.from));
  }

  return { REGIONS, REGION_GROUPS, forYear, calendar, bridges, easterSunday };
})();
