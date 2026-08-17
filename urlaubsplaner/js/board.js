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
      const first = p => Math.min(...((p.deptIds || []).map(x => rank.get(x) ?? 999).concat(999)));
      yd.people.sort((a, b) => {
        const da = first(a), db = first(b);
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

    /* Abteilungen mit Unterkategorien werden zu einem Block zusammengefasst:
       Überschrift mit der Gesamtzahl, darunter die Unterspalten nebeneinander.
       Abteilungen ohne Unterkategorien stehen wie bisher nebeneinander in einer
       gemeinsamen Reihe – sonst bekäme jede eine eigene Zeile und das Brett
       würde unnötig hoch. */
    let reihe = null;
    const reiheAbschliessen = () => { if (reihe) { board.appendChild(reihe); reihe = null; } };

    for (const node of S.deptTree(yd)) {
      if (node.children && node.children.length) {
        reiheAbschliessen();
        board.appendChild(groupBlock(node, yd));
      } else {
        if (!reihe) reihe = el('div.board-cols', { style: { marginBottom: '14px' } });
        reihe.appendChild(column(node.dept, yd.departments.findIndex(x => x.id === node.dept.id)));
      }
    }
    reiheAbschliessen();

    const orphans = S.peopleOf(null, yd);
    const rest = el('div.board-cols', { style: { marginTop: '14px' } },
      column(null, -1, orphans.length === 0),
      el('div', { style: { flex: '0 0 240px' } },
        U.btn('soft-btn', 'plus', 'Abteilung hinzufügen', {
          style: { width: '100%', height: '44px', borderStyle: 'dashed' },
          onclick: () => UP.app.editDepartment(null),
        })));
    board.appendChild(rest);
    host.appendChild(board);
  }

  /** Eine Abteilung samt ihrer Unterkategorien. */
  function groupBlock(node, yd, depth = 0) {
    const d = node.dept;
    const kids = node.children || [];
    const index = yd.departments.findIndex(x => x.id === d.id);

    if (!kids.length) {
      return el('div.board-cols', { style: { marginBottom: '14px' } }, column(d, index));
    }

    const under = S.peopleUnder(d.id, yd);
    const cf = S.conflicts().filter(c => c.deptId === d.id).length;
    const direct = S.peopleOf(d.id, yd);

    const head = el('div.bgroup-head', {},
      el('span.cbar', { style: { background: d.color } }),
      el('span.bgroup-name', { text: d.name }),
      el('span.tag', { title: 'Personen insgesamt, jede nur einmal gezählt' },
        `${under.length} gesamt`),
      el('span.tag', { class: cf ? 'danger' : '' }, `max ${d.maxAbsent} gleichzeitig`),
      cf ? el('span.tag.danger', {}, `${cf} Überschneidung${cf > 1 ? 'en' : ''}`) : null,
      el('div', { style: { marginLeft: 'auto', display: 'flex', gap: '6px' } },
        U.btn('soft-btn btn-sm', 'plus', 'Unterkategorie', {
          onclick: () => UP.app.editDepartment(null, d.id),
        }),
        el('button.iconbtn', {
          html: U.icon('pencil', 14), title: 'Abteilung bearbeiten',
          onclick: () => UP.app.editDepartment(d.id),
        })));

    const cols = el('div.board-cols');
    // direkt der übergeordneten Abteilung zugeordnete Personen zuerst
    if (direct.length) cols.appendChild(column(d, index, false, true));
    kids.forEach(k => {
      const sub = groupBlock(k, yd, depth + 1);
      // eine Ebene tiefer ohne eigenen Rahmen einhängen
      if (sub.classList.contains('board-cols')) {
        while (sub.firstChild) cols.appendChild(sub.firstChild);
      } else {
        cols.appendChild(sub);
      }
    });

    return el('div.bgroup', { dataset: { dept: d.id } }, head, cols);
  }

  function column(dept, index, faded = false, directOnly = false) {
    const yd = S.currentYear();
    const id = dept ? dept.id : '__none__';
    const people = S.peopleOf(dept ? dept.id : null, yd);
    const color = dept ? dept.color : '#8d97ab';
    const max = dept ? dept.maxAbsent : S.settings.defaultMaxAbsent;

    const totalRest = people.reduce((n, p) => n + S.quota(p.id).remaining, 0);
    const conflictCount = S.conflicts().filter(c => c.deptId === id).length;

    const list = el('div.bcol-list', { dataset: { dept: id } });
    people.forEach(p => list.appendChild(personCard(p, dept ? dept.id : null)));
    if (!people.length) list.appendChild(el('div.small.muted', {
      style: { padding: '14px 8px', textAlign: 'center', border: '1px dashed var(--border)', borderRadius: '10px' },
      text: 'Karten hierher ziehen',
    }));

    const head = el('div.bcol-head', {},
      el('span.cbar', { style: { background: color } }),
      el('span.cname', {
        text: directOnly ? `${dept.name} (direkt)` : dept ? dept.name : 'Ohne Abteilung',
        title: directOnly ? 'Personen, die dieser Abteilung direkt zugeordnet sind – nicht über eine Unterkategorie' : '',
      }),
      el('span.ccount', { text: String(people.length) }),
      dept && !directOnly ? el('button.iconbtn', {
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

  function personCard(p, inDeptId) {
    const q = S.quota(p.id);
    const abs = S.absencesOf(p.id);
    const restCls = q.remaining < 0 ? 'danger' : q.remaining <= 3 ? 'warn' : '';
    const alsoIn = (p.deptIds || []).filter(x => x !== inDeptId)
      .map(x => S.deptById(x)?.name).filter(Boolean);

    const card = el('div.pcard', { dataset: { person: p.id, from: inDeptId || '' } },
      el('span.avatar', { style: { background: p.color || U.colorOf(p.name) } }, U.initials(p.name)),
      el('div.pcard-main', {},
        el('div.pcard-name', {},
          p.name,
          alsoIn.length
            ? el('span.multi-badge', { title: `Auch in: ${alsoIn.join(', ')}` }, `+${alsoIn.length}`)
            : null),
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
      startCardDrag(ev, p, card, inDeptId);
    });
    card.addEventListener('click', ev => {
      if (ev.defaultPrevented || ev.target.closest('.miniedit')) return;
      UP.app.openPerson(p.id);
    });

    return card;
  }

  /* ── Ziehen: Personenkarte ──────────────────────────────────────────── */
  /**
   * Ziehen verschiebt die Person aus dieser Spalte in die Zielspalte. Mit
   * gedrückter Strg-Taste (bzw. Alt) bleibt die bisherige Zuordnung bestehen –
   * die Person gehört danach zu beiden Abteilungen.
   */
  function startCardDrag(ev, p, card, fromDeptId) {
    let dropLine = null, targetList = null, beforeId = null, dragged = false;
    let copy = ev.ctrlKey || ev.metaKey || ev.altKey;
    let proxyNode = null;

    const clearLine = () => { dropLine?.remove(); dropLine = null; };
    const trackKeys = e => {
      const now = e.ctrlKey || e.metaKey || e.altKey;
      if (now === copy) return;
      copy = now;
      proxyNode?.classList.toggle('is-copy', copy);
    };
    window.addEventListener('keydown', trackKeys, true);
    window.addEventListener('keyup', trackKeys, true);

    UP.dnd.begin(ev, {
      threshold: 6,
      makeProxy: () => {
        const clone = card.cloneNode(true);
        clone.classList.remove('dragging');
        clone.classList.toggle('is-copy', copy);
        clone.style.background = 'var(--surface)';
        proxyNode = clone;
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
        window.removeEventListener('keydown', trackKeys, true);
        window.removeEventListener('keyup', trackKeys, true);
        card.classList.remove('dragging');
        targetList?.closest('.bcol')?.classList.remove('drop-target');
        clearLine();
        if (cancelled || !dragged || !targetList) return;
        if (!UP.app.requireUnlocked()) return;
        const raw = targetList.dataset.dept;
        const toId = raw === '__none__' ? null : raw;
        const d = S.deptById(toId);

        if (copy && toId) {
          if ((p.deptIds || []).includes(toId)) return;
          S.assignPerson(p.id, toId, `${p.name} zusätzlich zugeordnet`);
          UP.app.toast('ok', `${p.name} jetzt auch in „${d.name}“`, {
            action: { label: 'Rückgängig', fn: () => UP.app.doUndo() },
          });
          return;
        }

        const sameSpot = toId === fromDeptId && !beforeId;
        S.movePerson(p.id, fromDeptId, toId, beforeId);
        if (!sameSpot) {
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
