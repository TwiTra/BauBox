/* ═══════════════════════════════════════════════════════════════════════
   dnd.js – Drag & Drop auf Pointer-Basis (Maus, Stift, Touch)
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.dnd = (function () {
  const U = UP.util;
  let active = null;

  /* ── Mitlaufendes Rollen ────────────────────────────────────────────────
     Zieht man eine Karte an den Rand eines rollbaren Bereichs, rollt dieser
     von selbst weiter. Ohne das sind Abteilungen, die gerade nicht im Bild
     sind, per Drag & Drop nicht erreichbar. */
  const EDGE = 60;        // Randstreifen in Pixeln, der das Rollen auslöst
  const SPEED = 18;       // größte Schrittweite je Bild

  /** Nächstgelegener Vorfahre, der in der gefragten Richtung rollen kann. */
  function scrollableAncestor(node, axis) {
    for (let e = node; e && e !== document.body; e = e.parentElement) {
      const st = getComputedStyle(e);
      const ov = axis === 'y' ? st.overflowY : st.overflowX;
      const room = axis === 'y'
        ? e.scrollHeight - e.clientHeight
        : e.scrollWidth - e.clientWidth;
      if (/auto|scroll/.test(ov) && room > 4) return e;
    }
    return null;
  }

  function autoScroll() {
    let raf = 0, px = 0, py = 0, boxY = null, boxX = null;

    const step = () => {
      raf = 0;
      let moved = false;
      const nudge = (box, axis, amount) => {
        if (!box || !amount) return;
        const before = axis === 'y' ? box.scrollTop : box.scrollLeft;
        if (axis === 'y') box.scrollTop = before + amount;
        else box.scrollLeft = before + amount;
        if ((axis === 'y' ? box.scrollTop : box.scrollLeft) !== before) moved = true;
      };
      nudge(boxY, 'y', py);
      nudge(boxX, 'x', px);
      if (moved && (py || px)) raf = requestAnimationFrame(step);
    };

    /** Geschwindigkeit aus dem Abstand zum Rand; 0 = nicht rollen. */
    const rate = (pos, lo, hi) => {
      if (pos < lo + EDGE) return -Math.ceil(SPEED * Math.min(1, (lo + EDGE - pos) / EDGE));
      if (pos > hi - EDGE) return Math.ceil(SPEED * Math.min(1, (pos - (hi - EDGE)) / EDGE));
      return 0;
    };

    return {
      /** Bei jeder Zeigerbewegung aufrufen. `el` = Element unter dem Zeiger. */
      update(x, y, el) {
        boxY = scrollableAncestor(el || document.elementFromPoint(x, y), 'y');
        boxX = scrollableAncestor(el || document.elementFromPoint(x, y), 'x');
        py = px = 0;
        if (boxY) {
          const r = boxY.getBoundingClientRect();
          py = rate(y, Math.max(r.top, 0), Math.min(r.bottom, innerHeight));
        }
        if (boxX) {
          const r = boxX.getBoundingClientRect();
          px = rate(x, Math.max(r.left, 0), Math.min(r.right, innerWidth));
        }
        if ((py || px) && !raf) raf = requestAnimationFrame(step);
      },
      stop() { if (raf) cancelAnimationFrame(raf); raf = 0; py = px = 0; },
    };
  }

  /**
   * Startet einen Ziehvorgang mit frei schwebendem Stellvertreter-Element.
   *
   * @param {PointerEvent} ev
   * @param {Object}  o
   * @param {Function} o.makeProxy  () → HTMLElement, folgt dem Zeiger
   * @param {Function} [o.onStart]  (x,y) – wenn die Schwelle überschritten wurde
   * @param {Function} [o.onMove]   (x,y,elementUnderPointer)
   * @param {Function} [o.onEnd]    (x,y,elementUnderPointer,cancelled)
   * @param {number}  [o.threshold] Pixel bis der Zug beginnt (Standard 5)
   */
  function begin(ev, o) {
    if (active) return;
    if (ev.button != null && ev.button !== 0) return;

    const startX = ev.clientX, startY = ev.clientY;
    let started = false, proxy = null, offX = 0, offY = 0;
    const target = ev.currentTarget;
    const roll = autoScroll();

    const state = {
      move(e) {
        const x = e.clientX, y = e.clientY;
        if (!started) {
          if (Math.hypot(x - startX, y - startY) < (o.threshold ?? 5)) return;
          started = true;
          document.body.classList.add('dragging-active', 'no-select');
          proxy = o.makeProxy ? o.makeProxy() : null;
          if (proxy) {
            const r = (o.proxyRect || target.getBoundingClientRect.bind(target))();
            offX = startX - r.left; offY = startY - r.top;
            proxy.classList.add('drag-proxy');
            proxy.style.width = r.width + 'px';
            document.body.appendChild(proxy);
          }
          o.onStart?.(x, y);
        }
        if (proxy) {
          proxy.style.left = (x - offX) + 'px';
          proxy.style.top = (y - offY) + 'px';
        }
        const el = under(x, y);
        roll.update(x, y, el);
        o.onMove?.(x, y, el);
        e.preventDefault();
      },
      up(e) {
        finish(e.clientX, e.clientY, false);
      },
      cancel() { finish(startX, startY, true); },
    };

    function under(x, y) {
      if (proxy) proxy.style.display = 'none';
      const el = document.elementFromPoint(x, y);
      if (proxy) proxy.style.display = '';
      return el;
    }

    function finish(x, y, cancelled) {
      roll.stop();
      window.removeEventListener('pointermove', state.move, true);
      window.removeEventListener('pointerup', state.up, true);
      window.removeEventListener('pointercancel', state.cancel, true);
      window.removeEventListener('keydown', onKey, true);
      document.body.classList.remove('dragging-active', 'no-select');
      const el = started ? under(x, y) : null;
      proxy?.remove();
      active = null;
      o.onEnd?.(x, y, el, cancelled || !started);
    }

    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); state.cancel(); }
    }

    active = state;
    window.addEventListener('pointermove', state.move, true);
    window.addEventListener('pointerup', state.up, true);
    window.addEventListener('pointercancel', state.cancel, true);
    window.addEventListener('keydown', onKey, true);
  }

  /**
   * Waagerechtes Ziehen entlang eines Tagesrasters (Balken anlegen,
   * verschieben, an den Rändern verlängern).
   *
   * @param {PointerEvent} ev
   * @param {Object} o
   * @param {HTMLElement} o.track   Bezugselement für die Koordinaten
   * @param {number} o.dayW         Spaltenbreite in Pixeln
   * @param {number} o.maxIndex     letzter gültiger Tagesindex
   * @param {Function} o.onDrag     ({from,to,deltaDays,startIndex,currentIndex})
   * @param {Function} o.onDone     (info, cancelled)
   */
  function hDrag(ev, o) {
    /* Der Bezugspunkt wird bei jedem Schritt neu bestimmt: rollt der Bereich
       während des Ziehens, wäre ein einmal gemerkter Wert nicht mehr gültig. */
    const idxAt = clientX => U.clamp(
      Math.floor((clientX - o.track.getBoundingClientRect().left) / o.dayW), 0, o.maxIndex
    );
    const startIndex = idxAt(ev.clientX);
    let last = null, moved = false;

    function calc(x) {
      const cur = idxAt(x);
      const info = {
        startIndex, currentIndex: cur,
        from: Math.min(startIndex, cur), to: Math.max(startIndex, cur),
        deltaDays: cur - startIndex,
      };
      return info;
    }

    function onMove(e) {
      const info = calc(e.clientX);
      if (info.currentIndex !== startIndex) moved = true;
      if (!last || last.currentIndex !== info.currentIndex) {
        last = info;
        o.onDrag?.(info);
      }
      e.preventDefault();
    }
    function onUp(e) { stop(calc(e.clientX), false); }
    function onCancel() { stop(last || calc(ev.clientX), true); }
    function onKey(e) { if (e.key === 'Escape') { e.preventDefault(); onCancel(); } }

    function stop(info, cancelled) {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      window.removeEventListener('pointercancel', onCancel, true);
      window.removeEventListener('keydown', onKey, true);
      document.body.classList.remove('no-select');
      o.onDone?.({ ...info, moved }, cancelled);
    }

    document.body.classList.add('no-select');
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
    window.addEventListener('pointercancel', onCancel, true);
    window.addEventListener('keydown', onKey, true);

    o.onDrag?.(calc(ev.clientX));
  }

  const isDragging = () => !!active;

  return { begin, hDrag, isDragging };
})();
