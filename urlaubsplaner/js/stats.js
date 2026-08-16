/* ═══════════════════════════════════════════════════════════════════════
   stats.js – Auswertungen, Urlaubskonten, Brückentage, Feiertage
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.views = UP.views || {};

UP.views.statistik = (function () {
  const U = UP.util, S = UP.store;
  const { el } = U;

  let sortKey = 'name', sortDir = 1;

  /* ── Werkzeugleiste ─────────────────────────────────────────────────── */
  function toolbar() {
    return [
      el('div.tb-group', {},
        el('span.tb-label', { text: `Auswertung ${S.year()}` })),
      el('div.tb-spacer'),
      U.btn('soft-btn btn-sm', 'download', 'Urlaubskonten (CSV)', { onclick: exportQuota }),
      U.btn('soft-btn btn-sm', 'download', 'Alle Einträge (CSV)', { onclick: exportAbsences }),
      U.btn('soft-btn btn-sm', 'printer', 'Drucken', { onclick: () => window.print() }),
    ];
  }

  /* ── Aufbau ─────────────────────────────────────────────────────────── */
  function render(host) {
    const yd = S.currentYear();
    if (!yd.people.length) { host.appendChild(UP.app.emptyState()); return; }

    const wrap = el('div.wrap');
    wrap.appendChild(kpis());
    wrap.appendChild(el('div.grid-2', {}, monthChart(), deptChart()));
    wrap.appendChild(quotaTable());
    wrap.appendChild(el('div.grid-2', {}, bridgeCard(), holidayCard()));
    host.appendChild(el('div.pad-view', {}, wrap));
  }

  /* ── Kennzahlen ─────────────────────────────────────────────────────── */
  function kpis() {
    const yd = S.currentYear();
    const qs = yd.people.map(p => S.quota(p.id));
    const planned = qs.reduce((n, q) => n + q.planned, 0);
    const rest = qs.reduce((n, q) => n + q.remaining, 0);
    const pending = yd.absences.filter(a => a.status === 'beantragt').length;
    const overdrawn = qs.filter(q => q.remaining < 0).length;
    const unplanned = qs.filter(q => q.planned === 0).length;

    return el('div.grid-4', { style: { marginBottom: '16px' } },
      el('div.kpi', {},
        el('div.k-label', { text: 'Team' }),
        el('div.k-value', { text: String(yd.people.length) }),
        el('div.k-note', { text: `in ${U.plural(yd.departments.length, 'Abteilung', 'Abteilungen')}` })),
      el('div.kpi', {},
        el('div.k-label', { text: 'Verplante Urlaubstage' }),
        el('div.k-value', { text: U.num(Math.round(planned * 2) / 2) }),
        el('div.k-note', { text: `${U.num(Math.round(rest * 2) / 2)} Tage noch offen` })),
      el('div.kpi', { class: pending ? 'is-warn' : '' },
        el('div.k-label', { text: 'Offene Anträge' }),
        el('div.k-value', { text: String(pending) }),
        el('div.k-note', { text: pending ? 'warten auf Genehmigung' : 'alles entschieden' })),
      el('div.kpi', { class: overdrawn ? 'is-danger' : unplanned ? 'is-warn' : 'is-ok' },
        el('div.k-label', { text: 'Auffälligkeiten' }),
        el('div.k-value', { text: String(overdrawn + unplanned) }),
        el('div.k-note', {
          text: overdrawn ? `${overdrawn}× Konto überzogen`
            : unplanned ? `${unplanned}× noch nichts geplant` : 'keine'
        })));
  }

  /* ── Verteilung über das Jahr ───────────────────────────────────────── */
  function monthChart() {
    const yd = S.currentYear();
    const cal = S.calendar();
    const perMonth = new Array(12).fill(0);

    for (const a of yd.absences) {
      if (a.status === 'abgelehnt' || !S.TYPES[a.type].quota) continue;
      let s = S.dayIndex(a.start), e = S.dayIndex(a.end);
      if (s < 0) s = 0;
      if (e < 0) e = cal.length - 1;
      for (let i = s; i <= e && i < cal.length; i++) if (cal[i].workday) perMonth[cal[i].month]++;
    }
    const max = Math.max(1, ...perMonth);

    return el('div.card', {},
      el('div.card-head', {},
        el('h3', {}, 'Urlaubstage je Monat'),
        el('span.sub', {}, 'nur quotenwirksame Arten')),
      el('div.card-body', {},
        el('div.colchart', {}, perMonth.map((v, i) =>
          el('div.colchart-col', {},
            el('div.colchart-val', { text: v ? String(v) : '' }),
            el('div.colchart-bar', {
              style: {
                height: `${Math.max(2, (v / max) * 100)}%`,
                background: v === max ? 'linear-gradient(180deg, var(--warn), color-mix(in srgb, var(--warn) 60%, transparent))' : null,
              },
              title: `${U.MONTHS[i]}: ${U.plural(v, 'Urlaubstag', 'Urlaubstage')}`,
              onclick: () => S.set(s => { s.ui.view = 'monat'; s.ui.month = i; }),
            }),
            el('div.colchart-lbl', { text: U.MONTHS_SHORT[i] }))))));
  }

  /* ── Belastung je Abteilung ─────────────────────────────────────────── */
  function deptChart() {
    const yd = S.currentYear();
    const rows = [];
    const groups = yd.departments.slice();

    for (const d of groups) {
      const people = S.peopleOf(d.id, yd);
      if (!people.length) continue;
      const qs = people.map(p => S.quota(p.id));
      const planned = qs.reduce((n, q) => n + q.planned, 0);
      const total = qs.reduce((n, q) => n + q.total, 0);
      rows.push({ name: d.name, color: d.color, planned, total, pct: total ? planned / total : 0, n: people.length });
    }
    rows.sort((a, b) => b.pct - a.pct);

    return el('div.card', {},
      el('div.card-head', {},
        el('h3', {}, 'Planungsstand je Abteilung'),
        el('span.sub', {}, 'verplant von verfügbar')),
      el('div.card-body', {},
        rows.length ? el('div.barlist', {}, rows.map(r =>
          el('div.barlist-row', {},
            el('div.barlist-label', { title: `${r.name} · ${U.plural(r.n, 'Person', 'Personen')}` },
              el('span.dot', { style: { background: r.color } }),
              el('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis' }, text: r.name })),
            el('div.barlist-track', {},
              el('div.barlist-fill', {
                style: { width: `${Math.min(100, r.pct * 100)}%`, background: r.color },
                title: `${U.num(Math.round(r.planned * 2) / 2)} von ${U.num(r.total)} Tagen`,
              })),
            el('div.barlist-value', { text: `${Math.round(r.pct * 100)} %` }))))
          : el('div.small.muted', { text: 'Noch keine Abteilungen mit Personen.' })));
  }

  /* ── Urlaubskonten ──────────────────────────────────────────────────── */
  function quotaTable() {
    const yd = S.currentYear();
    const rows = yd.people.map(p => {
      const q = S.quota(p.id);
      const d = S.deptById(p.deptId);
      return { p, q, dept: d ? d.name : 'Ohne Abteilung', deptColor: d ? d.color : '#8d97ab' };
    });

    const cmp = {
      name: (a, b) => U.byName(a.p.name, b.p.name),
      dept: (a, b) => U.byName(a.dept, b.dept) || U.byName(a.p.name, b.p.name),
      total: (a, b) => a.q.total - b.q.total,
      planned: (a, b) => a.q.planned - b.q.planned,
      rest: (a, b) => a.q.remaining - b.q.remaining,
    }[sortKey] || (() => 0);
    rows.sort((a, b) => cmp(a, b) * sortDir);

    const th = (key, label, num) => el(num ? 'th.num' : 'th', {
      style: { cursor: 'pointer', userSelect: 'none' },
      onclick: () => { if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = 1; } UP.app.render(); },
      title: 'Sortieren',
    }, label + (sortKey === key ? (sortDir > 0 ? ' ↑' : ' ↓') : ''));

    return el('div.card', { style: { marginTop: '16px' } },
      el('div.card-head', {},
        el('h3', {}, 'Urlaubskonten'),
        el('span.sub', {}, 'Anspruch, Übertrag aus dem Vorjahr, verplante und offene Tage')),
      el('div.card-body', { style: { overflowX: 'auto' } },
        el('table.data', {},
          el('thead', {}, el('tr', {},
            th('name', 'Person'), th('dept', 'Abteilung'),
            th('total', 'Verfügbar', true), th('planned', 'Verplant', true),
            th('rest', 'Rest', true),
            el('th', { style: { width: '160px' } }, 'Fortschritt'),
            el('th.num', {}, 'Sonstige'))),
          el('tbody', {}, rows.map(({ p, q, dept, deptColor }) => {
            const pct = q.total ? U.clamp(q.planned / q.total, 0, 1) : 0;
            const appPct = q.total ? U.clamp(q.approved / q.total, 0, 1) : 0;
            return el('tr', { style: { cursor: 'pointer' }, onclick: () => UP.app.openPerson(p.id) },
              el('td', {}, el('span.rowname', {},
                el('span.avatar.sm', { style: { background: p.color || U.colorOf(p.name) } }, U.initials(p.name)),
                el('span', {}, p.name))),
              el('td', {}, el('span.rowname', {}, el('span.dot', { style: { background: deptColor } }), dept)),
              el('td.num', {}, U.num(q.total)),
              el('td.num', {}, U.num(q.planned)),
              el('td.num', { style: q.remaining < 0 ? { color: 'var(--danger)', fontWeight: '700' } : q.remaining <= 3 ? { color: 'var(--warn)', fontWeight: '650' } : null },
                U.num(q.remaining)),
              el('td', {}, el('div.barlist-track', { title: `genehmigt ${U.num(q.approved)} · beantragt ${U.num(q.pending)}` },
                el('div.barlist-fill', { style: { width: `${appPct * 100}%`, background: 'var(--ok)' } }),
                el('div.barlist-fill', {
                  style: {
                    width: `${(pct - appPct) * 100}%`, background: 'var(--ok)', opacity: .42,
                    backgroundImage: 'repeating-linear-gradient(135deg, rgba(255,255,255,.5) 0 4px, transparent 4px 8px)',
                  }
                }),
                q.remaining < 0 ? el('div.over') : null)),
              el('td.num', { style: { color: 'var(--muted)' } }, q.other ? U.num(q.other) : '–'));
          })))));
  }

  /* ── Brückentage ────────────────────────────────────────────────────── */
  function bridgeCard() {
    const cal = S.calendar();
    const list = UP.holidays.bridges(cal).slice(0, 10);

    return el('div.card', { style: { marginTop: '16px' } },
      el('div.card-head', {},
        el('h3', {}, 'Brückentage'),
        el('span.sub', {}, 'wenige Urlaubstage, viel freie Zeit')),
      el('div.card-body', {},
        list.length ? el('div.mlist', {}, list.map(b =>
          el('div.mrow', {},
            el('div', {
              style: {
                width: '44px', height: '40px', borderRadius: '10px', flex: '0 0 auto',
                display: 'grid', placeItems: 'center', background: 'var(--primary-soft)',
                color: 'var(--primary)', fontWeight: '800', fontSize: '13px',
              }
            }, `${b.cost}→${b.free}`),
            el('div.mrow-main', {},
              el('div.mrow-title', { text: b.cost === 1 ? U.fmtLong(b.from) : U.fmtRange(b.from, b.to) }),
              el('div.mrow-sub', {
                text: `${U.plural(b.cost, 'Urlaubstag', 'Urlaubstage')} ergibt ${b.free} freie Tage ` +
                      `(${U.fmtShort(b.freeFrom)}–${U.fmtShort(b.freeTo)}) · Anlass: ${b.cause}`
              })),
            U.btn('soft-btn btn-sm', null, 'Eintragen', {
              title: 'Für eine Person als Urlaub eintragen',
              onclick: () => UP.app.editAbsence(null, { start: b.from, end: b.to }),
            }))))
          : el('div.small.muted', { text: 'In diesem Jahr ergeben sich keine lohnenden Brückentage.' })));
  }

  /* ── Feiertage ──────────────────────────────────────────────────────── */
  function holidayCard() {
    const cal = S.calendar();
    const hs = cal.filter(d => d.holiday);
    const region = UP.holidays.REGIONS[S.settings.region] || S.settings.region;

    return el('div.card', { style: { marginTop: '16px' } },
      el('div.card-head', {},
        el('h3', {}, 'Feiertage'),
        el('span.sub', {}, region),
        U.btn('soft-btn btn-sm', 'settings', 'Region', {
          style: { marginLeft: 'auto' }, onclick: () => UP.app.openSettings(),
        })),
      el('div.card-body', {},
        hs.length ? el('table.data', {},
          el('tbody', {}, hs.map(d => el('tr', {},
            el('td', { style: { width: '104px', whiteSpace: 'nowrap' } }, U.fmt(d.iso)),
            el('td', { style: { width: '38px', color: 'var(--muted)' } }, U.DOW[d.dow]),
            el('td', {}, d.holiday.name),
            el('td', { style: { textAlign: 'right' } },
              d.weekend ? el('span.tag', {}, 'am Wochenende') : el('span.tag.ok', {}, 'frei'))))))
          : el('div.small.muted', { text: 'Für die gewählte Region sind keine Feiertage hinterlegt.' })));
  }

  /* ── Export ─────────────────────────────────────────────────────────── */
  async function exportQuota() {
    const yd = S.currentYear();
    const rows = [['Person', 'Abteilung', 'Rolle', 'Anspruch', 'Übertrag', 'Verfügbar', 'Genehmigt', 'Beantragt', 'Rest', 'Sonstige Abwesenheit']];
    for (const p of yd.people) {
      const q = S.quota(p.id);
      const d = S.deptById(p.deptId);
      rows.push([p.name, d ? d.name : '', p.role || '', U.num(q.entitlement), U.num(q.carryover),
        U.num(q.total), U.num(q.approved), U.num(q.pending), U.num(q.remaining), U.num(q.other)]);
    }
    if (await U.download(`Urlaubskonten_${S.year()}.csv`, U.csvRows(rows), 'text/csv'))
      UP.app.toast('ok', 'Urlaubskonten als CSV gespeichert.');
  }

  async function exportAbsences() {
    const yd = S.currentYear();
    const rows = [['Person', 'Abteilung', 'Art', 'Status', 'Von', 'Bis', 'Arbeitstage', 'Halber erster Tag', 'Halber letzter Tag', 'Notiz']];
    const sorted = yd.absences.slice().sort((a, b) => a.start.localeCompare(b.start));
    for (const a of sorted) {
      const p = S.personById(a.personId);
      if (!p) continue;
      const d = S.deptById(p.deptId);
      rows.push([p.name, d ? d.name : '', S.TYPES[a.type].label, S.STATUS[a.status].label,
        U.fmt(a.start), U.fmt(a.end), U.num(S.workdaysOf(a)),
        a.halfStart ? 'ja' : '', a.halfEnd ? 'ja' : '', a.note || '']);
    }
    if (await U.download(`Abwesenheiten_${S.year()}.csv`, U.csvRows(rows), 'text/csv'))
      UP.app.toast('ok', `${sorted.length} Einträge als CSV gespeichert.`);
  }

  return { toolbar, render, exportQuota, exportAbsences };
})();
