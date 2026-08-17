/* ═══════════════════════════════════════════════════════════════════════
   month.js – Monatsansicht mit großem Raster und Malen-Modus
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.views = UP.views || {};

UP.views.monat = (function () {
  const U = UP.util, S = UP.store;
  const { el } = U;
  const CELL = 30;

  /* ── Werkzeugleiste ─────────────────────────────────────────────────── */
  function toolbar() {
    const m = S.ui.month;
    const nodes = [];

    nodes.push(el('div.tb-group', {},
      el('button.soft-btn.btn-sm', { onclick: () => step(-1), title: 'Vorheriger Monat' }, '‹'),
      el('select.tb-select', {
        onchange: e => S.set(s => { s.ui.month = Number(e.target.value); }),
        style: { minWidth: '132px', fontWeight: '600' },
      }, U.MONTHS.map((name, i) =>
        el('option', { value: i, selected: i === m }, `${name} ${S.year()}`))),
      el('button.soft-btn.btn-sm', { onclick: () => step(1), title: 'Nächster Monat' }, '›'),
      el('button.soft-btn.btn-sm', {
        onclick: () => S.set(s => {
          const now = new Date();
          if (s.years[now.getFullYear()]) s.ui.year = now.getFullYear();
          s.ui.month = now.getMonth();
        }),
      }, 'Heute')
    ));

    nodes.push(el('div.tb-sep'));

    nodes.push(el('div.tb-group', {},
      el('span.tb-label', { text: 'Malen mit' }),
      el('div.typepick', {}, S.TYPE_ORDER.map(key => {
        const t = S.TYPES[key];
        return el('button.typechip', {
          class: S.ui.quickType === key ? 'active' : '',
          title: `Im Raster ziehen trägt „${t.label}“ ein`,
          onclick: () => S.set(s => { s.ui.quickType = key; }),
        }, el('span.swatch', { style: { background: t.color } }), t.label);
      }))
    ));

    nodes.push(el('div.tb-spacer'));
    nodes.push(el('div.legend', {},
      el('span.legend-item', {}, 'Zeile ziehen legt einen Eintrag an · Klick auf einen Eintrag bearbeitet ihn')));
    return nodes;
  }

  function step(n) {
    S.set(s => {
      let m = s.ui.month + n;
      if (m < 0) { m = 11; if (s.years[s.ui.year - 1]) s.ui.year--; else m = 0; }
      else if (m > 11) { m = 0; if (s.years[s.ui.year + 1]) s.ui.year++; else m = 11; }
      s.ui.month = m;
    });
  }

  /* ── Aufbau ─────────────────────────────────────────────────────────── */
  function render(host) {
    const yd = S.currentYear();
    if (!yd.people.length) { host.appendChild(UP.app.emptyState()); return; }

    const cal = S.calendar();
    const m = U.clamp(S.ui.month, 0, 11);
    const days = cal.filter(d => d.month === m);
    const occ = S.occupancy();
    const term = (S.ui.search || '').trim().toLowerCase();
    const gridW = days.length * CELL;

    const root = el('div.mv-root');
    const scroll = el('div.mv-scroll');
    const grid = el('div.mv-grid');

    /* Kopf */
    const head = el('div.mv-head');
    head.appendChild(el('div.mv-headrow', {},
      el('div.mv-corner', {}, `${U.MONTHS[m]} ${S.year()}`),
      ...days.map(d => el('div.mv-cell', {
        class: cls(d), style: { width: CELL + 'px' },
        title: d.holiday ? `${U.fmtLong(d.iso)} · ${d.holiday.name}` : U.fmtLong(d.iso),
      }, String(d.dom)))
    ));
    head.appendChild(el('div.mv-headrow.dow', {},
      el('div.mv-corner', { style: { fontSize: '10px', fontWeight: '600' } }, `KW ${days[0].week}–${days[days.length - 1].week}`),
      ...days.map(d => el('div.mv-cell', { class: cls(d), style: { width: CELL + 'px' } }, U.DOW[d.dow]))
    ));
    grid.appendChild(head);

    function cls(d) {
      return [d.holiday ? 'hd' : d.weekend ? 'we' : '', d.iso === U.todayISO() ? 'today' : '']
        .filter(Boolean).join(' ');
    }

    /* Gruppen als Baum, Unterkategorien eingerückt */
    const body = el('div');

    const renderGroup = (dept, depth) => {
      const id = dept ? dept.id : '__none__';
      const max = dept ? dept.maxAbsent : S.settings.defaultMaxAbsent;
      const arr = occ.byDept[id] || [];
      const direct = S.peopleOf(dept ? dept.id : null, yd);
      const under = dept ? S.peopleUnder(dept.id, yd) : direct;
      const kids = dept ? S.childrenOf(dept.id, yd) : [];

      body.appendChild(el('div.mv-deptbar', { class: kids.length ? 'is-parent' : '' },
        el('div.mv-name', { style: { paddingLeft: (10 + depth * 14) + 'px' } },
          el('span.dot', { style: { background: dept ? dept.color : '#8d97ab' } }),
          el('span.pname', { class: kids.length ? 'is-parent' : '', text: dept ? dept.name : 'Ohne Abteilung' }),
          el('span', { style: { marginLeft: 'auto', fontSize: '10.5px', color: 'var(--faint)' } },
            `${under.length} · max ${max}`)),
        ...days.map(d => {
          const v = arr[d.i] || 0;
          const c = !d.workday ? '' : v > max ? 'd' : v === max ? 'w' : v > 0 ? 'has' : '';
          return el('div.mv-loadcell', {
            class: c, style: { width: CELL + 'px' },
            title: v ? `${dept ? dept.name : 'Ohne Abteilung'} · ${U.fmtLong(d.iso)}: ` +
              `${U.plural(v, 'Person', 'Personen')} abwesend (erlaubt: ${max})` : '',
            onclick: v ? () => UP.app.showDayDetail(d.i, id) : null,
          }, v ? String(v) : '');
        })
      ));

      for (const p of direct) body.appendChild(personRow(p, days, term, gridW, depth, dept));
      for (const k of kids) renderGroup(k, depth + 1);
    };

    S.childrenOf(null, yd).forEach(d => renderGroup(d, 0));
    if (S.peopleOf(null, yd).length) renderGroup(null, 0);

    grid.appendChild(body);
    scroll.appendChild(grid);
    root.appendChild(scroll);
    host.appendChild(root);
  }

  function personRow(p, days, term, gridW, depth = 0, dept = null) {
    const dim = term && !p.name.toLowerCase().includes(term);
    const q = S.quota(p.id);
    const alsoIn = (p.deptIds || []).filter(x => x !== (dept && dept.id))
      .map(x => S.deptById(x)?.name).filter(Boolean);

    const track = el('div.mv-track', { dataset: { person: p.id } });
    const marks = S.absencesOf(p.id);

    for (const d of days) {
      const cell = el('div.mv-day', {
        class: [d.holiday ? 'hd' : d.weekend ? 'we' : '', d.iso === U.todayISO() ? 'today' : ''].filter(Boolean).join(' '),
        style: { width: CELL + 'px' },
        dataset: { day: d.i },
      });
      const hits = marks.filter(x => x.start <= d.iso && x.end >= d.iso);
      if (hits.length) {
        const a = hits[hits.length - 1];   // der zuletzt begonnene Eintrag liegt oben
        const t = S.TYPES[a.type];
        const half = (a.halfStart && a.start === d.iso) ? 'half-b'
          : (a.halfEnd && a.end === d.iso) ? 'half-a' : '';
        cell.appendChild(el('div.mv-mark', {
          class: [a.status === 'beantragt' ? 'pending' : '', a.status === 'abgelehnt' ? 'rejected' : '', half].filter(Boolean).join(' '),
          style: {
            background: t.color,
            // mehrere Einträge am selben Tag: Ecke markieren
            boxShadow: hits.length > 1 ? 'inset -6px 6px 0 -3px rgba(255,255,255,.85)' : '',
          },
          dataset: { absence: a.id },
          title: p.name + '\n' + hits.map(x =>
            `${S.TYPES[x.type].label} · ${U.fmtRange(x.start, x.end)}${x.note ? ' · ' + x.note : ''}`).join('\n'),
        }, t.short));
      }
      track.appendChild(cell);
    }

    const row = el('div.mv-row', { class: dim ? 'dimmed' : '', style: dim ? { opacity: .3 } : null },
      el('div.mv-name', {
        title: `${p.name}${p.role ? ' · ' + p.role : ''} – Rest ${U.num(q.remaining)} Tage` +
          (alsoIn.length ? `\nAuch in: ${alsoIn.join(', ')}` : ''),
        onclick: () => UP.app.openPerson(p.id),
        style: { cursor: 'pointer', paddingLeft: (20 + depth * 14) + 'px' },
      },
        el('span.avatar.sm', { style: { background: p.color || U.colorOf(p.name) } }, U.initials(p.name)),
        el('span.pname', { text: p.name }),
        alsoIn.length ? el('span.multi-badge', { title: `Auch in: ${alsoIn.join(', ')}` }, `+${alsoIn.length}`) : null,
        el('span', { style: { marginLeft: 'auto', fontSize: '10.5px', fontWeight: '650', color: q.remaining < 0 ? 'var(--danger)' : 'var(--faint)' } }, U.num(q.remaining))),
      track);

    /* Klick auf Eintrag = bearbeiten, Ziehen auf leerer Fläche = anlegen */
    track.addEventListener('pointerdown', ev => {
      const mark = ev.target.closest('.mv-mark');
      if (mark) {
        ev.stopPropagation();
        UP.app.editAbsence(mark.dataset.absence);
        return;
      }
      if (!UP.app.requireUnlocked()) return;
      startPaint(ev, p, track, days);
    });

    return row;
  }

  /* ── Malen ──────────────────────────────────────────────────────────── */
  function startPaint(ev, p, track, days) {
    const rect = track.getBoundingClientRect();
    const idxAt = x => U.clamp(Math.floor((x - rect.left) / CELL), 0, days.length - 1);
    const a0 = idxAt(ev.clientX);
    const cells = Array.from(track.children);
    const color = S.TYPES[S.ui.quickType].color;
    let cur = a0, moved = false;

    paint(a0, a0);

    function paint(from, to) {
      cells.forEach((c, i) => {
        c.style.boxShadow = (i >= from && i <= to) ? `inset 0 0 0 2px ${color}` : '';
      });
    }

    function onMove(e) {
      const i = idxAt(e.clientX);
      if (i !== cur) { cur = i; moved = true; paint(Math.min(a0, i), Math.max(a0, i)); }
      e.preventDefault();
    }
    function done(cancelled) {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      window.removeEventListener('pointercancel', onCancel, true);
      window.removeEventListener('keydown', onKey, true);
      document.body.classList.remove('no-select');
      cells.forEach(c => c.style.boxShadow = '');
      if (cancelled) return;
      const from = Math.min(a0, cur), to = Math.max(a0, cur);
      const a = S.addAbsence({
        personId: p.id, type: S.ui.quickType,
        start: days[from].iso, end: days[to].iso,
      });
      UP.app.afterAbsenceChange(a, p, 'angelegt');
    }
    const onUp = () => done(false);
    const onCancel = () => done(true);
    const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); done(true); } };

    document.body.classList.add('no-select');
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
    window.addEventListener('pointercancel', onCancel, true);
    window.addEventListener('keydown', onKey, true);
  }

  return { toolbar, render };
})();
