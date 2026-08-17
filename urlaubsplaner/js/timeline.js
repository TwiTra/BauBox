/* ═══════════════════════════════════════════════════════════════════════
   timeline.js – Jahresansicht: alle Personen, alle Tage, Überschneidungen
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.views = UP.views || {};

UP.views.jahr = (function () {
  const U = UP.util, S = UP.store;
  const { el, frag } = U;

  const ZOOMS = [3, 5, 8, 12, 18, 26];
  const ROW_H = 34;     // muss zu --row-h in css/app.css passen
  const PAD = 4;        // Luft ober- und unterhalb der Balken
  // Die Scrollposition wird als Tagesindex gemerkt, damit beim Zoomen
  // derselbe Zeitraum sichtbar bleibt.
  let scrollPos = { day: null, top: 0 };
  let selectedBar = null;

  const dayW = () => ZOOMS[U.clamp(S.ui.zoom, 0, ZOOMS.length - 1)];

  /* ── Werkzeugleiste ─────────────────────────────────────────────────── */
  function toolbar() {
    const nodes = [];

    nodes.push(el('div.tb-group', {},
      el('span.tb-label', { text: 'Eintragen' }),
      el('div.typepick', {}, S.TYPE_ORDER.map(key => {
        const t = S.TYPES[key];
        return el('button.typechip', {
          class: S.ui.quickType === key ? 'active' : '',
          title: `${t.label} – beim Aufziehen im Kalender wird dieser Typ verwendet`,
          onclick: () => { S.set(s => { s.ui.quickType = key; }); },
        },
          el('span.swatch', { style: { background: t.color } }),
          t.label);
      }))
    ));

    nodes.push(el('div.tb-spacer'));

    nodes.push(el('div.tb-group', {},
      el('span.tb-label', { text: 'Zoom' }),
      el('input.zoom-slider', {
        type: 'range', min: 0, max: ZOOMS.length - 1, step: 1, value: S.ui.zoom,
        title: 'Zeitachse zoomen (+ / −)',
        oninput: e => { S.set(s => { s.ui.zoom = Number(e.target.value); }); },
      })
    ));

    nodes.push(el('div.tb-sep'));

    nodes.push(el('div.tb-group', {},
      el('button.soft-btn.btn-sm', {
        onclick: () => scrollToToday(true),
        title: 'Zum heutigen Tag springen (T)',
      }, 'Heute'),
      el('button.soft-btn.btn-sm', {
        class: S.settings.showWeeks ? 'on' : '',
        onclick: () => S.set(s => { s.settings.showWeeks = !s.settings.showWeeks; }),
        title: 'Kalenderwochen ein-/ausblenden',
      }, 'KW'),
      el('button.soft-btn.btn-sm', {
        onclick: () => setAllCollapsed(true), title: 'Alle Abteilungen zuklappen',
      }, 'Alle zu'),
      el('button.soft-btn.btn-sm', {
        onclick: () => setAllCollapsed(false), title: 'Alle Abteilungen aufklappen',
      }, 'Alle auf')
    ));

    nodes.push(el('div.tb-sep'));
    nodes.push(legend());
    return nodes;
  }

  /** Kompakt: die Farben der Arten stehen bereits auf den Schnelleintrag-Chips. */
  function legend() {
    return el('div.legend', {},
      el('span.legend-item', { title: 'Gestreifte Balken sind beantragt, aber noch nicht genehmigt' },
        el('span.swatch.hatch', { style: { background: S.TYPES.urlaub.color } }), 'beantragt'),
      el('span.legend-item', { title: 'Balken mit rotem Rahmen liegen in einem Zeitraum mit Überschneidung' },
        el('span.swatch', { style: { background: 'transparent', boxShadow: 'inset 0 0 0 2px var(--danger)' } }), 'Überschneidung'),
      el('span.legend-item', { title: 'Gesetzliche Feiertage der eingestellten Region' },
        el('span.swatch', { style: { background: 'var(--holiday)', boxShadow: 'inset 0 0 0 1px var(--holiday-line)' } }), 'Feiertag'),
      el('span.legend-item', { title: 'Eingetragene Betriebsruhe' },
        el('span.swatch', { style: { background: 'var(--closure)' } }), 'Betriebsruhe'));
  }

  function setAllCollapsed(v) {
    S.set(s => { s.years[s.ui.year].departments.forEach(d => d.collapsed = v); });
  }

  /* ── Aufbau ─────────────────────────────────────────────────────────── */
  function render(host) {
    const yd = S.currentYear();
    const cal = S.calendar();
    const w = dayW();
    const totalW = cal.length * w;
    const occ = S.occupancy();
    const cfDays = S.conflictDaySet();
    const term = (S.ui.search || '').trim().toLowerCase();

    if (!yd.people.length) { host.appendChild(UP.app.emptyState()); return; }

    const root = el('div.tl-root');
    const scroll = el('div.tl-scroll');
    const grid = el('div.tl-grid');

    /* Kopf */
    const head = el('div.tl-head');
    head.appendChild(monthRow(cal, w, totalW));
    if (S.settings.showWeeks && w >= 5) head.appendChild(weekRow(cal, w, totalW));
    if (w >= 11) head.appendChild(dayRow(cal, w, totalW));
    grid.appendChild(head);

    const headH = 26 + (S.settings.showWeeks && w >= 5 ? 22 : 0) + (w >= 11 ? 22 : 0);
    root.style.setProperty('--tl-head-h', headH + 'px');

    /* Körper */
    const body = el('div.tl-body', { style: { position: 'relative' } });
    body.appendChild(backgroundLayer(cal, w, totalW, yd));

    // Abteilungen als Baum: erst die Sammelzeile, dann die direkt zugeordneten
    // Personen, dann die Unterkategorien eine Stufe eingerückt.
    for (const node of S.deptTree(yd)) {
      body.appendChild(deptBlock(node, cal, w, totalW, occ, cfDays, term));
    }
    const orphans = S.peopleOf(null, yd);
    if (orphans.length) {
      body.appendChild(deptBlock({ dept: null, depth: 0, children: [] },
        cal, w, totalW, occ, cfDays, term));
    }

    grid.appendChild(body);
    scroll.appendChild(grid);
    root.appendChild(scroll);
    host.appendChild(root);

    /* Scrollposition wiederherstellen bzw. auf heute setzen */
    requestAnimationFrame(() => {
      if (scrollPos.day == null) scrollToToday(false);
      else { scroll.scrollLeft = scrollPos.day * w; scroll.scrollTop = scrollPos.top; }
      scroll.addEventListener('scroll', () => {
        scrollPos = { day: scroll.scrollLeft / dayW(), top: scroll.scrollTop };
      }, { passive: true });
    });
  }

  function scrollToToday(smooth) {
    const scroll = U.$('.tl-scroll');
    if (!scroll) return;
    const cal = S.calendar();
    let idx = S.dayIndex(U.todayISO());
    if (idx < 0) idx = Math.round(cal.length * 0.45);
    const x = Math.max(0, idx * dayW() - scroll.clientWidth * 0.35);
    scroll.scrollTo({ left: x, behavior: smooth ? 'smooth' : 'auto' });
    scrollPos.day = x / dayW();
  }

  /* ── Kopfzeilen ─────────────────────────────────────────────────────── */
  function monthRow(cal, w, totalW) {
    const lane = el('div.tl-lane', { style: { width: totalW + 'px', height: '26px' } });
    let i = 0;
    while (i < cal.length) {
      const m = cal[i].month;
      let n = 0;
      while (i + n < cal.length && cal[i + n].month === m) n++;
      const width = n * w;
      const label = width > 74 ? U.MONTHS[m] : width > 34 ? U.MONTHS_SHORT[m] : U.MONTHS_SHORT[m][0];
      lane.appendChild(el('div.tl-month', {
        style: { left: i * w + 'px', width: width + 'px' },
        title: `${U.MONTHS[m]} ${cal[i].date.getFullYear()}`,
      }, el('span', {}, label)));
      i += n;
    }
    return el('div.tl-headrow.months', {}, el('div.tl-corner', {}, 'Team'), lane);
  }

  function weekRow(cal, w, totalW) {
    const lane = el('div.tl-lane', { style: { width: totalW + 'px', height: '22px' } });
    let i = 0;
    while (i < cal.length) {
      const wk = cal[i].week;
      let n = 0;
      while (i + n < cal.length && cal[i + n].week === wk) n++;
      const width = n * w;
      lane.appendChild(el('div.tl-week', {
        style: { left: i * w + 'px', width: width + 'px' },
        title: `Kalenderwoche ${wk}`,
      }, width >= 20 ? String(wk) : ''));
      i += n;
    }
    return el('div.tl-headrow', { style: { height: '22px' } },
      el('div.tl-corner', { style: { fontSize: '10px' } }, 'KW'), lane);
  }

  function dayRow(cal, w, totalW) {
    const lane = el('div.tl-lane', { style: { width: totalW + 'px', height: '22px' } });
    for (const d of cal) {
      lane.appendChild(el('div.tl-daynum', {
        class: d.holiday ? 'hd' : d.weekend ? 'we' : '',
        style: { left: d.i * w + 'px', width: w + 'px' },
        title: d.holiday ? `${U.fmtLong(d.iso)} · ${d.holiday.name}` : U.fmtLong(d.iso),
      }, w >= 17 ? String(d.dom) : (d.dom % 5 === 0 || d.dom === 1 ? String(d.dom) : '')));
    }
    return el('div.tl-headrow', { style: { height: '22px' } },
      el('div.tl-corner', { style: { fontSize: '10px' } }, 'Tag'), lane);
  }

  /* ── Hintergrund: Wochenenden, Feiertage, Betriebsruhe, Heute ───────── */
  function backgroundLayer(cal, w, totalW, yd) {
    const layer = el('div.tl-bg', {
      style: { left: 'var(--name-w)', width: totalW + 'px' },
    });

    // Betriebsruhe zuerst (liegt unter den anderen Markierungen)
    for (const c of yd.closures || []) {
      const s = S.dayIndex(c.start), e = S.dayIndex(c.end);
      if (s < 0 && e < 0) continue;
      const a = Math.max(0, s), b = e < 0 ? cal.length - 1 : e;
      layer.appendChild(el('span.cl', {
        style: { left: a * w + 'px', width: (b - a + 1) * w + 'px' },
      }));
    }

    // Wochenenden und Feiertage zusammengefasst rendern
    let i = 0;
    while (i < cal.length) {
      const d = cal[i];
      if (d.holiday) {
        layer.appendChild(el('span.hd', { style: { left: i * w + 'px', width: w + 'px' } }));
        i++; continue;
      }
      if (d.weekend) {
        let n = 0;
        while (i + n < cal.length && cal[i + n].weekend && !cal[i + n].holiday) n++;
        layer.appendChild(el('span.we', { style: { left: i * w + 'px', width: n * w + 'px' } }));
        i += n; continue;
      }
      i++;
    }

    // Monatsgrenzen
    for (let k = 1; k < 12; k++) {
      const idx = U.diffDays(cal[0].iso, `${cal[0].date.getFullYear()}-${U.pad(k + 1)}-01`);
      layer.appendChild(el('span.mo', { style: { left: idx * w + 'px', width: '0px' } }));
    }

    // Heute
    const ti = S.dayIndex(U.todayISO());
    if (ti >= 0) layer.appendChild(el('div.tl-today', {
      style: { left: (ti * w + w / 2) + 'px' }, title: 'Heute',
    }));

    return layer;
  }

  /* ── Abteilungsblock (rekursiv über die Unterkategorien) ────────────── */
  function deptBlock(node, cal, w, totalW, occ, cfDays, term) {
    const d = node.dept;
    const yd = S.currentYear();
    const id = d ? d.id : '__none__';
    const depth = node.depth || 0;
    const color = d ? d.color : '#8d97ab';
    const max = d ? d.maxAbsent : S.settings.defaultMaxAbsent;

    const direct = S.peopleOf(d ? d.id : null, yd);
    const under = d ? S.peopleUnder(d.id, yd) : direct;
    const hasKids = (node.children || []).length > 0;

    const block = el('div.tl-dept', {
      class: d && d.collapsed ? 'collapsed' : '',
      dataset: { dept: id, depth },
    });

    /* Kopfzeile mit Belegungsbalken */
    const name = el('div.tl-deptname', {
      style: { paddingLeft: (8 + depth * 15) + 'px' },
      title: d
        ? `${d.name}${hasKids ? ' (mit Unterkategorien)' : ''} – höchstens ${max} gleichzeitig abwesend` +
          (hasKids ? `\nZählt alle ${under.length} Personen der Unterkategorien, jede nur einmal.` : '')
        : 'Personen ohne Abteilung',
    },
      el('button.caret', {
        html: U.icon('chevron', 14),
        title: 'Auf-/Zuklappen',
        onclick: e => { e.stopPropagation(); if (d) S.toggleCollapse(d.id); },
      }),
      el('span.dot', { style: { background: color } }),
      el('span.dname', { class: hasKids ? 'is-parent' : '', text: d ? d.name : 'Ohne Abteilung' }),
      el('span.cnt', { text: `${under.length} · max ${max}` })
    );
    if (d) name.addEventListener('dblclick', () => UP.app.editDepartment(d.id));

    const load = el('div.tl-load', { style: { width: totalW + 'px', position: 'relative' } });
    renderLoad(load, occ.byDept[id] || [], cal, w, max, id);

    block.appendChild(el('div.tl-deptbar', {
      class: hasKids ? 'is-parent' : '',
      style: { top: 'var(--tl-head-h)' },
    }, name, load));

    /* Direkt zugeordnete Personen, danach die Unterkategorien */
    const rows = el('div.tl-rows');
    // Konflikte der Abteilung selbst und ihrer übergeordneten Ebenen zählen
    const cfKeys = d ? [d.id, ...S.ancestorIds(d.id, yd)] : ['__none__'];
    for (const p of direct) {
      rows.appendChild(personRow(p, d, cal, w, totalW, cfDays, term, depth, cfKeys));
    }
    for (const child of (node.children || [])) {
      rows.appendChild(deptBlock(child, cal, w, totalW, occ, cfDays, term));
    }
    block.appendChild(rows);

    return block;
  }

  /** Belegungsbalken: gleiche Werte werden zu einem Element zusammengefasst. */
  function renderLoad(host, arr, cal, w, max, deptId) {
    const H = 21;
    const scale = Math.max(max + 1, 3);
    let i = 0;
    while (i < cal.length) {
      const v = arr[i] || 0;
      let n = 1;
      while (i + n < cal.length && (arr[i + n] || 0) === v) n++;
      if (v > 0) {
        const h = Math.max(3, Math.round(Math.min(1, v / scale) * H));
        const cls = v > max ? 'd' : v === max ? 'w' : '';
        host.appendChild(el('i', {
          class: cls,
          style: { left: i * w + 'px', width: Math.max(1, n * w - 0.5) + 'px', height: h + 'px' },
          dataset: { from: i, to: i + n - 1, dept: deptId, count: v },
          title: `${U.plural(v, 'Person', 'Personen')} abwesend · ${U.fmtRange(cal[i].iso, cal[i + n - 1].iso)}`,
        }));
      }
      i += n;
    }
  }

  /* ── Personenzeile ──────────────────────────────────────────────────── */
  function personRow(p, dept, cal, w, totalW, cfDays, term, depth = 0, cfKeys = null) {
    const q = S.quota(p.id);
    const dim = term && !p.name.toLowerCase().includes(term) && !(p.role || '').toLowerCase().includes(term);
    const yd = S.currentYear();
    const alsoIn = (p.deptIds || []).filter(x => x !== (dept && dept.id))
      .map(x => S.deptById(x, yd)?.name).filter(Boolean);

    const quotaCls = q.remaining < 0 ? 'over' : q.remaining <= 3 ? 'low' : '';
    const nameCell = el('div.tl-name', {
      dataset: { person: p.id },
      style: { paddingLeft: (22 + depth * 15) + 'px' },
      title: `${p.name}${p.role ? ' · ' + p.role : ''}\nRest: ${U.num(q.remaining)} von ${U.num(q.total)} Tagen` +
        (alsoIn.length ? `\nAuch in: ${alsoIn.join(', ')}` : '') +
        '\nZum Verschieben ziehen · mit Strg zusätzlich zuordnen · Klick öffnet die Details',
    },
      el('span.grip', { html: U.icon('grip', 13) }),
      el('span.avatar.sm', {
        style: { background: p.color || U.colorOf(p.name) },
      }, U.initials(p.name)),
      el('span.pname', { text: p.name }),
      alsoIn.length
        ? el('span.multi-badge', { title: `Auch in: ${alsoIn.join(', ')}` }, `+${alsoIn.length}`)
        : null,
      el('span.pquota', { class: quotaCls, text: U.num(q.remaining) })
    );

    const track = el('div.tl-track', {
      style: { width: totalW + 'px' },
      dataset: { person: p.id },
    });

    const deptKeys = cfKeys || [dept ? dept.id : '__none__'];
    const list = S.absencesOf(p.id);
    const { lane, count } = assignLanes(list);

    // Bei überlappenden Einträgen wächst die Zeile mit, statt die Balken
    // auf unlesbare Streifen zusammenzuquetschen.
    const rowH = count === 1 ? ROW_H : Math.max(ROW_H, count * 15 + PAD * 2);
    const laneH = (rowH - PAD * 2) / count;

    for (const a of list) {
      const bar = makeBar(a, p, cal, w, cfDays, deptKeys, lane.get(a.id) || 0, count, laneH);
      if (bar) track.appendChild(bar);
    }

    const row = el('div.tl-row', {
      class: dim ? 'dimmed' : '',
      dataset: { person: p.id, dept: dept ? dept.id : '__none__' },
      style: count > 1 ? { height: rowH + 'px' } : null,
    }, nameCell, track);

    /* Person per Ziehen in eine andere Abteilung bewegen */
    nameCell.addEventListener('pointerdown', ev => {
      if (ev.target.closest('.caret')) return;
      startPersonDrag(ev, p, row, dept ? dept.id : null);
    });
    nameCell.addEventListener('click', ev => {
      if (ev.defaultPrevented) return;
      UP.app.openPerson(p.id);
    });

    /* Neue Abwesenheit aufziehen */
    track.addEventListener('pointerdown', ev => {
      if (ev.target !== track) return;
      if (!UP.app.requireUnlocked()) return;
      startCreate(ev, p, track, cal, w);
    });

    return row;
  }

  /**
   * Überlappende Einträge derselben Person (z. B. krank im Urlaub) bekommen
   * eigene Spuren, damit keiner unter einem anderen verschwindet.
   */
  function assignLanes(list) {
    const lane = new Map();
    const laneEnd = [];
    for (const a of list) {
      let i = laneEnd.findIndex(end => end < a.start);
      if (i < 0) { i = laneEnd.length; laneEnd.push(''); }
      laneEnd[i] = a.end;
      lane.set(a.id, i);
    }
    return { lane, count: Math.max(1, Math.min(laneEnd.length, 3)) };
  }

  /* ── Balken ─────────────────────────────────────────────────────────── */
  function makeBar(a, p, cal, w, cfDays, deptKeys, laneIdx = 0, laneCount = 1, laneH = ROW_H - PAD * 2) {
    let s = S.dayIndex(a.start), e = S.dayIndex(a.end);
    if (s < 0) s = U.parseISO(a.start) < cal[0].date ? 0 : -1;
    if (e < 0) e = U.parseISO(a.end) > cal[cal.length - 1].date ? cal.length - 1 : -1;
    if (s < 0 || e < 0 || e < s) return null;

    const t = S.TYPES[a.type];
    let left = s * w, width = (e - s + 1) * w;
    if (a.halfStart) { left += w / 2; width -= w / 2; }
    if (a.halfEnd) { width -= w / 2; }
    width = Math.max(3, width - 1);

    // Ein Balken gilt als betroffen, wenn die Abteilung der Zeile oder eine
    // ihrer übergeordneten Ebenen in diesem Zeitraum überbelegt ist.
    let conflicted = false;
    outer: for (let i = s; i <= e; i++) {
      for (const key of deptKeys) if (cfDays.has(`${key}:${i}`)) { conflicted = true; break outer; }
    }

    const days = S.workdaysOf(a);
    const single = laneCount === 1;
    const label = width > 44 ? (width > 78 && single ? `${t.label} · ${U.num(days)}` : t.short) : '';

    const h = Math.max(6, laneH - (single ? 1 : 2));
    const top = PAD + laneIdx * laneH;

    const bar = el('div.bar', {
      class: [
        a.status === 'beantragt' ? 'pending' : '',
        a.status === 'abgelehnt' ? 'rejected' : '',
        conflicted ? 'conflict' : '',
        selectedBar === a.id ? 'selected' : '',
      ].filter(Boolean).join(' '),
      style: {
        left: left + 'px', width: width + 'px', background: t.color,
        top: top + 'px', height: h + 'px', fontSize: single ? '' : '9px',
      },
      dataset: { absence: a.id, person: p.id },
    },
      el('span.bar-label', { text: label }),
      el('span.handle.l'), el('span.handle.r')
    );

    bar.addEventListener('pointerenter', () => showBarCard(bar, a, p, days, conflicted));
    bar.addEventListener('pointerleave', () => UP.app.hideHovercard());
    bar.addEventListener('pointerdown', ev => {
      ev.stopPropagation();
      UP.app.hideHovercard();
      const mode = ev.target.classList.contains('handle')
        ? (ev.target.classList.contains('l') ? 'start' : 'end') : 'move';
      startBarDrag(ev, a, p, bar, cal, w, mode);
    });

    return bar;
  }

  function showBarCard(bar, a, p, days, conflicted) {
    const t = S.TYPES[a.type];
    UP.app.showHovercard(bar, U.frag(
      el('div.hc-title', {},
        el('span.dot', { style: { background: t.color } }), p.name),
      el('div.hc-line', { html: `<b>${U.esc(t.label)}</b> · ${U.esc(S.STATUS[a.status].label)}` }),
      el('div.hc-line', { html: `${U.esc(U.fmtRange(a.start, a.end))} · <b>${U.num(days)}</b> Arbeitstage` }),
      a.note ? el('div.hc-line', { text: a.note }) : null,
      conflicted ? el('div.hc-line', { style: { color: 'var(--danger)', fontWeight: '600' }, text: '⚠ Überschneidung – Kapazität überschritten' }) : null,
      el('div.hc-line', { style: { marginTop: '4px', opacity: .75 }, text: 'Ziehen = verschieben · Ränder = verlängern · Klick = bearbeiten' })
    ));
  }

  /* ── Interaktion: Balken anlegen ────────────────────────────────────── */
  function startCreate(ev, p, track, cal, w) {
    const ghost = el('div.bar-ghost', { style: { background: S.TYPES[S.ui.quickType].color, opacity: .75 } });
    track.appendChild(ghost);

    UP.dnd.hDrag(ev, {
      track, dayW: w, maxIndex: cal.length - 1,
      onDrag: info => {
        ghost.style.left = info.from * w + 'px';
        ghost.style.width = ((info.to - info.from + 1) * w - 1) + 'px';
        let n = 0;
        for (let i = info.from; i <= info.to; i++) if (cal[i].workday) n++;
        ghost.textContent = (info.to - info.from) * w > 60
          ? `${U.fmtShort(cal[info.from].iso)}–${U.fmtShort(cal[info.to].iso)} · ${n} AT` : String(n || '');
      },
      onDone: (info, cancelled) => {
        ghost.remove();
        if (cancelled) return;
        const a = S.addAbsence({
          personId: p.id, type: S.ui.quickType,
          start: cal[info.from].iso, end: cal[info.to].iso,
        });
        UP.app.afterAbsenceChange(a, p, 'angelegt');
      },
    });
  }

  /* ── Interaktion: Balken verschieben / verlängern ───────────────────── */
  function startBarDrag(ev, a, p, bar, cal, w, mode) {
    const s0 = Math.max(0, S.dayIndex(a.start));
    const e0 = Math.min(cal.length - 1, S.dayIndex(a.end) < 0 ? cal.length - 1 : S.dayIndex(a.end));
    const len = e0 - s0;
    const track = bar.parentElement;
    let next = null;

    bar.classList.add('dragging');

    UP.dnd.hDrag(ev, {
      track, dayW: w, maxIndex: cal.length - 1,
      onDrag: info => {
        let s = s0, e = e0;
        if (mode === 'move') {
          s = U.clamp(s0 + info.deltaDays, 0, cal.length - 1 - len);
          e = s + len;
        } else if (mode === 'start') {
          s = U.clamp(info.currentIndex, 0, e0);
          e = e0;
        } else {
          s = s0;
          e = U.clamp(info.currentIndex, s0, cal.length - 1);
        }
        next = { start: cal[s].iso, end: cal[e].iso };
        bar.style.left = s * w + 'px';
        bar.style.width = Math.max(3, (e - s + 1) * w - 1) + 'px';
        let n = 0;
        for (let i = s; i <= e; i++) if (cal[i].workday) n++;
        bar.querySelector('.bar-label').textContent =
          (e - s + 1) * w > 60 ? `${U.fmtShort(cal[s].iso)}–${U.fmtShort(cal[e].iso)} · ${n}` : String(n || '');
      },
      onDone: (info, cancelled) => {
        bar.classList.remove('dragging');
        const unchanged = cancelled || !next || !info.moved
          || (next.start === a.start && next.end === a.end)
          || !UP.app.requireUnlocked();

        // Ohne echte Verschiebung war es ein Klick: Vorschau verwerfen und bearbeiten.
        if (unchanged) {
          const isClick = !cancelled && !info.moved;
          if (isClick) selectedBar = a.id;
          UP.app.render();
          if (isClick) UP.app.editAbsence(a.id);
          return;
        }
        S.updateAbsence(a.id, next, mode === 'move' ? 'Abwesenheit verschoben' : 'Zeitraum geändert');
        UP.app.afterAbsenceChange({ ...a, ...next }, p, mode === 'move' ? 'verschoben' : 'angepasst');
      },
    });
  }

  /* ── Interaktion: Person in andere Abteilung ziehen ─────────────────── */
  /**
   * Ziehen verschiebt die Person aus der Abteilung dieser Zeile in die
   * Zielabteilung. Wird dabei Strg (bzw. Alt) gehalten, bleibt die bisherige
   * Zuordnung bestehen und die Person gehört danach zu beiden.
   */
  function startPersonDrag(ev, p, row, fromDeptId) {
    let lastTarget = null;
    let dragged = false;
    let copy = ev.ctrlKey || ev.metaKey || ev.altKey;
    const proxy = { node: null };

    const trackKeys = e => {
      const now = e.ctrlKey || e.metaKey || e.altKey;
      if (now === copy) return;
      copy = now;
      if (proxy.node) proxy.node.classList.toggle('is-copy', copy);
    };
    window.addEventListener('keydown', trackKeys, true);
    window.addEventListener('keyup', trackKeys, true);

    UP.dnd.begin(ev, {
      threshold: 6,
      proxyRect: () => row.querySelector('.tl-name').getBoundingClientRect(),
      makeProxy: () => {
        proxy.node = el('div.pcard', {
          class: copy ? 'is-copy' : '',
          style: { background: 'var(--surface)', width: '230px' },
        },
          el('span.avatar.sm', { style: { background: p.color || U.colorOf(p.name) } }, U.initials(p.name)),
          el('div.pcard-main', {}, el('div.pcard-name', { text: p.name })));
        return proxy.node;
      },
      onStart: () => { dragged = true; row.classList.add('dragging'); },
      onMove: (x, y, target) => {
        const block = target?.closest?.('.tl-dept');
        if (block === lastTarget) return;
        lastTarget?.classList.remove('drop-target');
        lastTarget = block;
        lastTarget?.classList.add('drop-target');
      },
      onEnd: (x, y, target, cancelled) => {
        window.removeEventListener('keydown', trackKeys, true);
        window.removeEventListener('keyup', trackKeys, true);
        row.classList.remove('dragging');
        lastTarget?.classList.remove('drop-target');
        if (cancelled || !dragged) return;
        const block = target?.closest?.('.tl-dept');
        if (!block) return;
        const raw = block.dataset.dept;
        const toId = raw === '__none__' ? null : raw;
        if (toId === fromDeptId) return;
        if (!UP.app.requireUnlocked()) return;

        const d = S.deptById(toId);
        if (copy && toId) {
          if ((p.deptIds || []).includes(toId)) return;
          S.assignPerson(p.id, toId, `${p.name} zusätzlich zugeordnet`);
          UP.app.toast('ok', `${p.name} jetzt auch in „${d.name}“`, {
            action: { label: 'Rückgängig', fn: () => UP.app.doUndo() },
          });
        } else {
          S.movePerson(p.id, fromDeptId, toId);
          UP.app.toast('ok', `${p.name} → ${d ? d.name : 'Ohne Abteilung'}`, {
            action: { label: 'Rückgängig', fn: () => UP.app.doUndo() },
          });
        }
      },
    });
  }

  /* ── Öffentliche Hilfen ─────────────────────────────────────────────── */
  function revealDate(isoStr) {
    const scroll = U.$('.tl-scroll');
    if (!scroll) return;
    const idx = S.dayIndex(isoStr);
    if (idx < 0) return;
    scroll.scrollTo({ left: Math.max(0, idx * dayW() - scroll.clientWidth * 0.3), behavior: 'smooth' });
  }

  function selectAbsence(id) { selectedBar = id; }
  function resetScroll() { scrollPos = { day: null, top: 0 }; }

  return { toolbar, render, revealDate, selectAbsence, resetScroll, scrollToToday, ZOOMS };
})();
