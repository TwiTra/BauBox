/* ═══════════════════════════════════════════════════════════════════════
   dnd.js – Drag & Drop auf Pointer-Basis (Maus, Stift, Touch)
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

UP.dnd = (function () {
  const U = UP.util;
  let active = null;

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
        o.onMove?.(x, y, under(x, y));
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
    const rect = o.track.getBoundingClientRect();
    const idxAt = clientX => U.clamp(
      Math.floor((clientX - rect.left + o.track.scrollLeft * 0) / o.dayW), 0, o.maxIndex
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
