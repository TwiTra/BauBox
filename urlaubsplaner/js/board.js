/* ═══════════════════════════════════════════════════════════════════════
   board.js – Team-Ansicht: Abteilungen als Spalten, Personen per Drag & Drop
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.views = UP.views || {};

UP.views.team = (function () {
  const U = UP.util, S = UP.store;
  const { el } = U;

  /* ── Werkzeugleiste ─────────────────────────────────────────────────── */
  function toolbar() {
    return [
      el('div.tb-group', {},
        U.btn('primary-btn btn-sm', 'plus', 'Abteilung', { onclick: () => UP.app.editDepartment(null) }),
        U.btn('soft-btn btn-sm', 'user', 'Person', { onclick: () => UP.app.editPerson(null) })),
      el('div.tb-sep'),
      el('div.tb-group', {},
        el('span.tb-label', { text: 'Sortieren' }),
        el('div.seg', {},
          el('button', { class: 'active', onclick: () => sortPeople('name') }, 'A–Z'),
          el('button', { onclick: () => sortPeople('rest') }, 'Resturlaub'))),
      el('div.tb-spacer'),
      el('span.small.muted', { text: 'Personenkarten lassen sich zwischen den Spalten ziehen' }),
    ];
  }

  function sortPeople(mode) {
    if (!UP.app.requireUnlocked()) return;
    S.commit('Personen sortiert', yd => {
      const rank = new Map(yd.departments.map((d, i) => [d.id, i]));
      yd.people.sort((a, b) => {
        const da = rank.has(a.deptId) ? rank.get(a.deptId) : 999;
        const db = rank.has(b.deptId) ? rank.get(b.deptId) : 999;
        if (da !== db) return da - db;
        if (mode === 'rest') return S.quota(b.id).remaining - S.quota(a.id).remaining;
        return U.byName(a.name, b.name);
      });
    });
  }

  /* ── Aufbau ─────────────────────────────────────────────────────────── */
  function render(host) {
    const yd = S.currentYear();
    if (!yd.departments.length && !yd.people.length) { host.appendChild(UP.app.emptyState()); return; }

    const board = el('div.board');
    const cols = el('div.board-cols');

    yd.departments.forEach((d, i) => cols.appendChild(column(d, i)));
    const orphans = S.peopleOf(null, yd);
    cols.appendChild(column(null, -1, orphans.length === 0));

    cols.appendChild(el('div', { style: { flex: '0 0 240px' } },
      U.btn('soft-btn', 'plus', 'Abteilung hinzufügen', {
        style: { width: '100%', height: '44px', borderStyle: 'dashed' },
        onclick: () => UP.app.editDepartment(null),
      })));

    board.appendChild(cols);
    host.appendChild(board);
  }

  function column(dept, index, faded = false) {
    const yd = S.currentYear();
    const id = dept ? dept.id : '__none__';
    const people = S.peopleOf(dept ? dept.id : null, yd);
    const color = dept ? dept.color : '#8d97ab';
    const max = dept ? dept.maxAbsent : S.settings.defaultMaxAbsent;

    const totalRest = people.reduce((n, p) => n + S.quota(p.id).remaining, 0);
    const conflictCount = S.conflicts().filter(c => c.deptId === id).length;

    const list = el('div.bcol-list', { dataset: { dept: id } });
    people.forEach(p => list.appendChild(personCard(p)));
    if (!people.length) list.appendChild(el('div.small.muted', {
      style: { padding: '14px 8px', textAlign: 'center', border: '1px dashed var(--border)', borderRadius: '10px' },
      text: 'Karten hierher ziehen',
    }));

    const head = el('div.bcol-head', {},
      el('span.cbar', { style: { background: color } }),
      el('span.cname', { text: dept ? dept.name : 'Ohne Abteilung' }),
      el('span.ccount', { text: String(people.length) }),
      dept ? el('button.iconbtn', {
        html: U.icon('pencil', 14), title: 'Abteilung bearbeiten',
        onclick: e => { e.stopPropagation(); UP.app.editDepartment(dept.id); },
      }) : null);

    const col = el('div.bcol', {
      class: [dept ? '' : 'unassigned', faded ? '' : ''].filter(Boolean).join(' '),
      dataset: { dept: id },
      style: faded ? { opacity: .6 } : null,
    },
      head,
      el('div.bcol-sub', {},
        el('span.tag', { class: conflictCount ? 'danger' : '' },
          `max ${max} gleichzeitig`),
        conflictCount ? el('span.tag.danger', {}, `${conflictCount} Überschneidung${conflictCount > 1 ? 'en' : ''}`) : null,
        people.length ? el('span.small.muted', { text: `${U.num(Math.round(totalRest * 2) / 2)} Resttage gesamt` }) : null),
      list,
      el('div.bcol-foot', {},
        U.btn('soft-btn btn-sm', 'plus', 'Person hinzufügen', {
          style: { width: '100%' },
          onclick: () => UP.app.editPerson(null, dept ? dept.id : null),
        })));

    /* Spalte per Kopfzeile umsortieren */
    if (dept) head.addEventListener('pointerdown', ev => {
      if (ev.target.closest('.iconbtn')) return;
      startColumnDrag(ev, dept, col, index);
    });

    return col;
  }

  function personCard(p) {
    const q = S.quota(p.id);
    const abs = S.absencesOf(p.id);
    const restCls = q.remaining < 0 ? 'danger' : q.remaining <= 3 ? 'warn' : '';

    const card = el('div.pcard', { dataset: { person: p.id } },
      el('span.avatar', { style: { background: p.color || U.colorOf(p.name) } }, U.initials(p.name)),
      el('div.pcard-main', {},
        el('div.pcard-name', { text: p.name }),
        el('div.pcard-sub', {},
          p.role ? el('span', { text: p.role }) : null,
          p.role && abs.length ? el('span', { text: '·' }) : null,
          abs.length ? el('span', { text: `${abs.length} Einträge` }) : el('span', { text: 'noch nichts geplant' }))),
      el('div.pcard-quota', { title: `Anspruch ${U.num(q.entitlement)} + Übertrag ${U.num(q.carryover)}\nVerplant ${U.num(q.planned)}` },
        el('b', { style: restCls === 'danger' ? { color: 'var(--danger)' } : restCls === 'warn' ? { color: 'var(--warn)' } : null },
          U.num(q.remaining)),
        'Rest'),
      el('button.miniedit', {
        html: U.icon('pencil', 13), title: 'Person bearbeiten',
        onclick: e => { e.stopPropagation(); UP.app.editPerson(p.id); },
      }));

    card.addEventListener('pointerdown', ev => {
      if (ev.target.closest('.miniedit')) return;
      startCardDrag(ev, p, card);
    });
    card.addEventListener('click', ev => {
      if (ev.defaultPrevented || ev.target.closest('.miniedit')) return;
      UP.app.openPerson(p.id);
    });

    return card;
  }

  /* ── Ziehen: Personenkarte ──────────────────────────────────────────── */
  function startCardDrag(ev, p, card) {
    let dropLine = null, targetList = null, beforeId = null, dragged = false;

    const clearLine = () => { dropLine?.remove(); dropLine = null; };

    UP.dnd.begin(ev, {
      threshold: 6,
      makeProxy: () => {
        const clone = card.cloneNode(true);
        clone.classList.remove('dragging');
        clone.style.background = 'var(--surface)';
        return clone;
      },
      onStart: () => { dragged = true; card.classList.add('dragging'); },
      onMove: (x, y, target) => {
        const list = target?.closest?.('.bcol-list');
        if (list !== targetList) {
          targetList?.closest('.bcol')?.classList.remove('drop-target');
          targetList = list;
          targetList?.closest('.bcol')?.classList.add('drop-target');
          clearLine();
        }
        if (!targetList) { clearLine(); beforeId = null; return; }

        const cards = Array.from(targetList.querySelectorAll('.pcard')).filter(c => c !== card);
        beforeId = null;
        let anchor = null;
        for (const c of cards) {
          const r = c.getBoundingClientRect();
          if (y < r.top + r.height / 2) { beforeId = c.dataset.person; anchor = c; break; }
        }
        if (!dropLine) dropLine = el('div.drop-line');
        if (anchor) targetList.insertBefore(dropLine, anchor);
        else targetList.appendChild(dropLine);
      },
      onEnd: (x, y, target, cancelled) => {
        card.classList.remove('dragging');
        targetList?.closest('.bcol')?.classList.remove('drop-target');
        clearLine();
        if (cancelled || !dragged || !targetList) return;
        if (!UP.app.requireUnlocked()) return;
        const raw = targetList.dataset.dept;
        const deptId = raw === '__none__' ? null : raw;
        const sameSpot = (p.deptId ?? null) === deptId && !beforeId;
        S.movePerson(p.id, deptId, beforeId);
        if (!sameSpot) {
          const d = S.deptById(deptId);
          UP.app.toast('ok', `${p.name} → ${d ? d.name : 'Ohne Abteilung'}`, {
            action: { label: 'Rückgängig', fn: () => UP.app.doUndo() },
          });
        }
      },
    });
  }

  /* ── Ziehen: Spalte umsortieren ─────────────────────────────────────── */
  function startColumnDrag(ev, dept, col, index) {
    let dragged = false, targetIndex = index;

    UP.dnd.begin(ev, {
      threshold: 8,
      proxyRect: () => col.getBoundingClientRect(),
      makeProxy: () => {
        const c = el('div.bcol', { style: { width: '288px', background: 'var(--surface)' } },
          el('div.bcol-head', {},
            el('span.cbar', { style: { background: dept.color } }),
            el('span.cname', { text: dept.name })));
        return c;
      },
      onStart: () => { dragged = true; col.style.opacity = '.4'; },
      onMove: (x, y, target) => {
        const other = target?.closest?.('.bcol');
        UP.util.$$('.bcol').forEach(c => c.classList.remove('drop-target'));
        if (!other || other === col || other.dataset.dept === '__none__') return;
        other.classList.add('drop-target');
        const all = UP.util.$$('.bcol');
        targetIndex = all.indexOf(other);
      },
      onEnd: (x, y, target, cancelled) => {
        col.style.opacity = '';
        UP.util.$$('.bcol').forEach(c => c.classList.remove('drop-target'));
        if (cancelled || !dragged) return;
        if (targetIndex === index) return;
        if (!UP.app.requireUnlocked()) return;
        S.moveDepartment(dept.id, targetIndex);
      },
    });
  }

  return { toolbar, render };
})();
