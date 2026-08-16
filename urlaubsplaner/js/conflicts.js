/* ═══════════════════════════════════════════════════════════════════════
   conflicts.js – Überschneidungen: wo sind zu viele Leute gleichzeitig weg?
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.views = UP.views || {};

UP.views.konflikte = (function () {
  const U = UP.util, S = UP.store;
  const { el } = U;

  /* ── Werkzeugleiste ─────────────────────────────────────────────────── */
  function toolbar() {
    return [
      el('div.tb-group', {},
        el('span.tb-label', { text: 'Prüft' }),
        el('span.small.muted', { text: 'Arbeitstage gegen die erlaubte Zahl gleichzeitig Abwesender je Abteilung' })),
      el('div.tb-spacer'),
      U.btn('soft-btn btn-sm', 'settings', 'Grenzwerte anpassen', { onclick: () => UP.app.openDepartments() }),
      U.btn('soft-btn btn-sm', 'printer', 'Drucken', { onclick: () => window.print() }),
    ];
  }

  /* ── Aufbau ─────────────────────────────────────────────────────────── */
  function render(host) {
    const yd = S.currentYear();
    if (!yd.people.length) { host.appendChild(UP.app.emptyState()); return; }

    const list = S.conflicts();
    const wrap = el('div.wrap');
    const page = el('div.pad-view', {}, wrap);

    wrap.appendChild(kpis(list));
    wrap.appendChild(heatmap());
    wrap.appendChild(conflictList(list));
    wrap.appendChild(tightDays());

    host.appendChild(page);
  }

  /* ── Kennzahlen ─────────────────────────────────────────────────────── */
  function kpis(list) {
    const yd = S.currentYear();
    const days = list.reduce((n, c) => n + c.workdays, 0);
    const depts = new Set(list.map(c => c.deptId)).size;
    const peak = list.reduce((m, c) => Math.max(m, c.over), 0);

    const occ = S.occupancy();
    const cal = S.calendar();
    let busiest = { i: -1, v: 0 };
    for (const d of cal) if (d.workday && occ.total[d.i] > busiest.v) busiest = { i: d.i, v: occ.total[d.i] };

    return el('div.grid-4', { style: { marginBottom: '16px' } },
      el('div.kpi', { class: list.length ? 'is-danger' : 'is-ok' },
        el('div.k-label', { text: 'Überschneidungen' }),
        el('div.k-value', { text: String(list.length) }),
        el('div.k-note', { text: list.length ? `an ${U.plural(days, 'Arbeitstag', 'Arbeitstagen')}` : 'Alles im Rahmen' })),
      el('div.kpi', { class: depts ? 'is-warn' : '' },
        el('div.k-label', { text: 'Betroffene Abteilungen' }),
        el('div.k-value', { text: `${depts}` }),
        el('div.k-note', { text: `von ${yd.departments.length + (S.peopleOf(null, yd).length ? 1 : 0)}` })),
      el('div.kpi', {},
        el('div.k-label', { text: 'Stärkste Überschreitung' }),
        el('div.k-value', { text: peak ? `+${peak}` : '–' }),
        el('div.k-note', { text: peak ? 'Person(en) über der Grenze' : 'keine Überschreitung' })),
      el('div.kpi', {},
        el('div.k-label', { text: 'Spitzentag gesamt' }),
        el('div.k-value', { text: String(busiest.v) }),
        el('div.k-note', { text: busiest.i >= 0 ? U.fmt(cal[busiest.i].iso) : '–' }))
    );
  }

  /* ── Wochen-Heatmap ─────────────────────────────────────────────────── */
  function heatmap() {
    const yd = S.currentYear();
    const cal = S.calendar();
    const occ = S.occupancy();

    const weeks = [];
    const seen = new Set();
    for (const d of cal) {
      const key = `${d.week}`;
      if (!seen.has(key)) { seen.add(key); weeks.push({ week: d.week, days: [] }); }
      weeks[weeks.length - 1].days.push(d);
    }
    // Randwochen aus dem Vor-/Folgejahr zusammenfassen
    const merged = [];
    for (const w of weeks) {
      const prev = merged[merged.length - 1];
      if (prev && prev.week === w.week) { prev.days.push(...w.days); continue; }
      merged.push(w);
    }

    const groups = yd.departments.map(d => ({ id: d.id, name: d.name, color: d.color, max: d.maxAbsent }));
    if (S.peopleOf(null, yd).length)
      groups.push({ id: '__none__', name: 'Ohne Abteilung', color: '#8d97ab', max: S.settings.defaultMaxAbsent });

    const rows = groups.map(g => {
      const arr = occ.byDept[g.id] || [];
      const cells = merged.map(w => {
        let v = 0, peakDay = null;
        for (const d of w.days) {
          if (!d.workday) continue;
          if ((arr[d.i] || 0) > v) { v = arr[d.i]; peakDay = d; }
        }
        const lvl = v === 0 ? '' : v > g.max ? 'l4' : v === g.max ? 'l3' : (v / g.max) <= 0.5 ? 'l1' : 'l2';
        return el('div.heat-cell', {
          class: lvl,
          title: `${g.name} · KW ${w.week} (${U.fmtShort(w.days[0].iso)}–${U.fmtShort(w.days[w.days.length - 1].iso)})\n` +
                 `Spitze: ${v} von max. ${g.max} gleichzeitig abwesend`,
          onclick: () => peakDay ? UP.app.showDayDetail(peakDay.i, g.id) : null,
        }, v ? String(v) : '');
      });
      return el('div.heat-row', {},
        el('div.barlist-label', {},
          el('span.dot', { style: { background: g.color } }),
          el('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis' }, text: g.name }),
          el('span.small.muted', { style: { marginLeft: 'auto' }, text: `≤${g.max}` })),
        el('div.heat-cells', {}, cells));
    });

    return el('div.card', {},
      el('div.card-head', {},
        el('h2', {}, 'Auslastung nach Kalenderwoche'),
        el('span.sub', {}, 'Höchstzahl gleichzeitig Abwesender je Woche'),
        el('div.heat-scale', { style: { marginLeft: 'auto' } },
          el('span.small', { text: 'wenig' }),
          el('i', { style: { background: 'var(--surface-3)' } }),
          el('i.heat-cell.l1', { style: { width: '18px', height: '12px' } }),
          el('i.heat-cell.l2', { style: { width: '18px', height: '12px' } }),
          el('i.heat-cell.l3', { style: { width: '18px', height: '12px' } }),
          el('i.heat-cell.l4', { style: { width: '18px', height: '12px' } }),
          el('span.small', { text: 'über Grenze' }))),
      el('div.card-body', {},
        el('div.heat', {}, rows),
        el('div.heat-row', { style: { marginTop: '6px' } },
          el('div'),
          el('div.heat-cells', {}, merged.map(w =>
            el('div', { style: { fontSize: '9px', textAlign: 'center', color: 'var(--faint)', fontVariantNumeric: 'tabular-nums' } },
              w.week % 2 === 1 ? String(w.week) : ''))))));
  }

  /* ── Konfliktliste ──────────────────────────────────────────────────── */
  function conflictList(list) {
    if (!list.length) {
      return el('div.card', {},
        el('div.card-body', {},
          el('div.note-box.ok', {},
            el('span.ico', { html: U.icon('check', 17) }),
            el('div', {},
              el('div', { style: { fontWeight: '700', marginBottom: '2px' } }, 'Keine Überschneidungen'),
              el('div', {}, `In ${S.year()} bleibt in jeder Abteilung an jedem Arbeitstag die erlaubte Zahl gleichzeitig Abwesender eingehalten.`)))));
    }

    const items = list.map(c => el('div.cf-item', {
      onclick: () => jumpTo(c),
      title: 'Klick öffnet die Jahresansicht an diesem Zeitraum',
    },
      el('div.cf-sev', { class: c.over === 1 ? 'warn' : '' }, `+${c.over}`),
      el('div.cf-main', {},
        el('div.cf-title', {},
          el('span.dot', { style: { background: c.deptColor } }),
          el('span', { text: c.deptName }),
          el('span.tag', { class: c.over > 1 ? 'danger' : 'warn' },
            `${c.peak} gleichzeitig · erlaubt ${c.max}`)),
        el('div.cf-meta', {
          text: `${U.fmtRange(c.from, c.to)} · ${U.plural(c.workdays, 'Arbeitstag', 'Arbeitstage')} betroffen · ` +
                `${c.people.length} von ${c.teamSize} Personen abwesend`
        }),
        el('div.cf-people', {}, c.people.map(({ person, absence }) =>
          el('span.cf-chip', {
            title: `${S.TYPES[absence.type].label} · ${U.fmtRange(absence.start, absence.end)}`,
            onclick: e => { e.stopPropagation(); UP.app.openPerson(person.id); },
          },
            el('span.avatar.sm', { style: { background: person.color || U.colorOf(person.name), width: '17px', height: '17px', fontSize: '8px' } }, U.initials(person.name)),
            person.name,
            el('span', { style: { color: 'var(--faint)', fontWeight: '500' } }, U.fmtShort(absence.start) + '–' + U.fmtShort(absence.end))))))
    ));

    return el('div.card', { style: { marginTop: '16px' } },
      el('div.card-head', {},
        el('h2', {}, 'Überschneidungen im Detail'),
        el('span.sub', {}, `${list.length} Zeiträume, nach Schwere sortiert`),
        U.btn('soft-btn btn-sm', 'download', 'CSV', { style: { marginLeft: 'auto' }, onclick: exportConflicts })),
      ...items);
  }

  function jumpTo(c) {
    S.set(s => { s.ui.view = 'jahr'; s.ui.month = U.parseISO(c.from).getMonth(); });
    setTimeout(() => UP.views.jahr.revealDate(c.from), 60);
  }

  /* ── Engpasstage (genau an der Grenze) ──────────────────────────────── */
  function tightDays() {
    const yd = S.currentYear();
    const cal = S.calendar();
    const occ = S.occupancy();
    const rows = [];

    const groups = yd.departments.map(d => ({ id: d.id, name: d.name, color: d.color, max: d.maxAbsent }));
    for (const g of groups) {
      const arr = occ.byDept[g.id] || [];
      let run = null;
      for (const d of cal) {
        const at = d.workday && (arr[d.i] || 0) === g.max && g.max > 0;
        if (at) { if (!run) run = { from: d, to: d, n: 1 }; else { run.to = d; run.n++; } }
        else if (run) { rows.push({ g, ...run }); run = null; }
      }
      if (run) rows.push({ g, ...run });
    }
    if (!rows.length) return el('div');

    rows.sort((a, b) => b.n - a.n || a.from.i - b.from.i);
    const top = rows.slice(0, 12);

    return el('div.card', { style: { marginTop: '16px' } },
      el('div.card-head', {},
        el('h2', {}, 'Engpasstage'),
        el('span.sub', {}, 'Genau an der Grenze – hier passt kein weiterer Urlaub mehr rein')),
      el('div.card-body', {},
        el('table.data', {},
          el('thead', {}, el('tr', {},
            el('th', {}, 'Abteilung'),
            el('th', {}, 'Zeitraum'),
            el('th.num', {}, 'Arbeitstage'),
            el('th.num', {}, 'Abwesend'),
            el('th', {}))),
          el('tbody', {}, top.map(r => el('tr', {},
            el('td', {}, el('span.rowname', {}, el('span.dot', { style: { background: r.g.color } }), r.g.name)),
            el('td', {}, U.fmtRange(r.from.iso, r.to.iso)),
            el('td.num', {}, String(r.n)),
            el('td.num', {}, `${r.g.max} / ${r.g.max}`),
            el('td', { style: { textAlign: 'right' } },
              el('button.soft-btn.btn-sm', {
                onclick: () => jumpTo({ from: r.from.iso }),
              }, 'Anzeigen')))))),
        rows.length > top.length
          ? el('div.small.muted.mt-8', { text: `… und ${rows.length - top.length} weitere Zeiträume` })
          : null));
  }

  /* ── Export ─────────────────────────────────────────────────────────── */
  async function exportConflicts() {
    const list = S.conflicts();
    const rows = [['Abteilung', 'Von', 'Bis', 'Arbeitstage', 'Gleichzeitig abwesend', 'Erlaubt', 'Überschreitung', 'Betroffene Personen']];
    for (const c of list) {
      rows.push([c.deptName, U.fmt(c.from), U.fmt(c.to), c.workdays, c.peak, c.max, c.over,
        c.people.map(p => p.person.name).join(', ')]);
    }
    if (await U.download(`Ueberschneidungen_${S.year()}.csv`, U.csvRows(rows), 'text/csv'))
      UP.app.toast('ok', 'CSV-Datei wurde erstellt.');
  }

  return { toolbar, render };
})();
