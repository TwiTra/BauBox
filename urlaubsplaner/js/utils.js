/* ═══════════════════════════════════════════════════════════════════════
   utils.js – Datums-, DOM- und Formatierungshelfer
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

window.UP = window.UP || {};

UP.util = (function () {

  /* ── Datum ──────────────────────────────────────────────────────────── */
  const pad = n => String(n).padStart(2, '0');

  /** Date → "YYYY-MM-DD" (lokale Zeitzone, kein UTC-Versatz) */
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  /** "YYYY-MM-DD" → Date (lokal, 00:00 Uhr) */
  const parseISO = s => {
    const [y, m, d] = String(s).split('-').map(Number);
    return new Date(y, m - 1, d);
  };

  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const addISO = (s, n) => iso(addDays(parseISO(s), n));

  /** Ganze Tage zwischen zwei ISO-Daten (b − a) */
  const diffDays = (a, b) =>
    Math.round((parseISO(b) - parseISO(a)) / 86400000);

  const todayISO = () => iso(new Date());
  const isWeekend = d => d.getDay() === 0 || d.getDay() === 6;
  const daysInMonth = (y, m) => new Date(y, m + 1, 0).getDate();
  const daysInYear = y => (new Date(y, 1, 29).getMonth() === 1 ? 366 : 365);

  /** ISO-8601-Kalenderwoche */
  function isoWeek(d) {
    const t = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    t.setDate(t.getDate() + 3 - ((t.getDay() + 6) % 7));
    const week1 = new Date(t.getFullYear(), 0, 4);
    return 1 + Math.round(
      ((t - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7
    );
  }

  const MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
    'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  const MONTHS_SHORT = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
    'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
  const DOW = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
  const DOW_LONG = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];

  /** "2026-07-01" → "01.07.2026" */
  const fmt = s => { const d = parseISO(s); return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`; };
  /** "2026-07-01" → "01.07." */
  const fmtShort = s => { const d = parseISO(s); return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.`; };
  /** "2026-07-01" → "Mi, 01.07.2026" */
  const fmtLong = s => `${DOW[parseISO(s).getDay()]}, ${fmt(s)}`;

  /** Zeitraum kompakt: "01.–14.07.2026" bzw. "28.06.–03.07.2026" */
  function fmtRange(a, b) {
    if (a === b) return fmt(a);
    const da = parseISO(a), db = parseISO(b);
    if (da.getFullYear() === db.getFullYear()) {
      if (da.getMonth() === db.getMonth())
        return `${pad(da.getDate())}.–${pad(db.getDate())}.${pad(db.getMonth() + 1)}.${db.getFullYear()}`;
      return `${pad(da.getDate())}.${pad(da.getMonth() + 1)}. – ${fmt(b)}`;
    }
    return `${fmt(a)} – ${fmt(b)}`;
  }

  /** Deutsche Zahl mit optionaler halber Stelle: 10 / 10,5 */
  const num = n => (Number.isInteger(n) ? String(n) : String(n).replace('.', ','));

  const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many}`;

  /* ── Sonstiges ──────────────────────────────────────────────────────── */
  let idCounter = 0;
  const uid = (prefix = 'id') =>
    `${prefix}_${Date.now().toString(36)}${(idCounter++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  const esc = s => String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  /** Initialen: "Anna Müller" → "AM", "Jean-Luc de Vries" → "JV" */
  function initials(name) {
    const parts = String(name || '').trim().split(/[\s-]+/).filter(Boolean);
    if (!parts.length) return '??';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  /** Stabile Farbe aus einem String (für Avatare ohne eigene Farbe) */
  const AVATAR_COLORS = [
    '#4a6cf0', '#e0684a', '#1f9d76', '#b063d6', '#d69a1f', '#3f9bd1',
    '#d1518c', '#5f9e3c', '#8a6bd6', '#c4623c', '#2a9b9b', '#a8543f'
  ];
  function colorOf(str) {
    let h = 0;
    const s = String(str || '');
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
  }

  const DEPT_COLORS = [
    '#4a6cf0', '#1f9d76', '#d69a1f', '#b063d6', '#e0684a',
    '#3f9bd1', '#d1518c', '#5f9e3c', '#8a6bd6', '#c4623c'
  ];

  /** Textfarbe (schwarz/weiß) mit ausreichendem Kontrast zur Hintergrundfarbe */
  function readableOn(hex) {
    const c = String(hex).replace('#', '');
    const r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#1a1a1a' : '#ffffff';
  }

  function debounce(fn, ms) {
    let t;
    return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
  }

  /** Sortierung nach deutschem Alphabet (Umlaute korrekt) */
  const collator = new Intl.Collator('de', { sensitivity: 'base', numeric: true });
  const byName = (a, b) => collator.compare(a, b);

  /* ── DOM ────────────────────────────────────────────────────────────── */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /**
   * el('div.cls#id', { attrs }, children…)
   * Attribute: style (Objekt), dataset (Objekt), on* (Listener), sonst setAttribute.
   */
  function el(spec, props, ...children) {
    const m = /^([a-zA-Z0-9-]+)?(.*)$/.exec(spec);
    const node = document.createElement(m[1] || 'div');
    const rest = m[2] || '';
    const cls = rest.match(/\.[^.#]+/g);
    const id = rest.match(/#[^.#]+/);
    if (cls) node.className = cls.map(c => c.slice(1)).join(' ');
    if (id) node.id = id[0].slice(1);

    if (props) for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
      else if (k === 'dataset') Object.assign(node.dataset, v);
      else if (k === 'html') node.innerHTML = v;
      else if (k === 'text') node.textContent = v;
      else if (k === 'class') node.className += (node.className ? ' ' : '') + v;
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) node.setAttribute(k, '');
      else node.setAttribute(k, v);
    }

    for (const c of children.flat(3)) {
      if (c == null || c === false) continue;
      node.appendChild(typeof c === 'object' ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  const frag = (...children) => {
    const f = document.createDocumentFragment();
    for (const c of children.flat(3)) if (c != null && c !== false)
      f.appendChild(typeof c === 'object' ? c : document.createTextNode(String(c)));
    return f;
  };

  /** Inline-SVG-Icon aus dem Pfad-Katalog */
  const ICONS = {
    plus:      '<path d="M12 5v14M5 12h14"/>',
    check:     '<path d="M20 6L9 17l-5-5"/>',
    x:         '<path d="M18 6L6 18M6 6l12 12"/>',
    pencil:    '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    trash:     '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    users:     '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    user:      '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    calendar:  '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    alert:     '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    info:      '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    download:  '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>',
    upload:    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
    printer:   '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    settings:  '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.36.43.65.79.79H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    help:      '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>',
    copy:      '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    grip:      '<circle cx="9" cy="6" r="1.4"/><circle cx="9" cy="12" r="1.4"/><circle cx="9" cy="18" r="1.4"/><circle cx="15" cy="6" r="1.4"/><circle cx="15" cy="12" r="1.4"/><circle cx="15" cy="18" r="1.4"/>',
    chevron:   '<path d="M6 9l6 6 6-6"/>',
    archive:   '<rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9M10 13h4"/>',
    lock:      '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    unlock:    '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
    sun:       '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    star:      '<path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.9L12 17.8 5.8 21l1.2-6.9-5-4.9 6.9-1z"/>',
    bridge:    '<path d="M2 17h20M4 17V9M20 17V9M2 9c4 0 6-3 10-3s6 3 10 3"/><path d="M8 17v-4M16 17v-4M12 17v-6"/>',
    filter:    '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
    building:  '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
    chart:     '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>',
    clock:     '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  };

  function icon(name, size = 16, extra = '') {
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" ` +
      `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="${extra}">${ICONS[name] || ''}</svg>`;
  }

  function iconEl(name, size = 16) {
    const s = document.createElement('span');
    s.style.display = 'grid';
    s.style.placeItems = 'center';
    s.innerHTML = icon(name, size);
    return s;
  }

  /** Schaltfläche mit Icon und Beschriftung: btn('soft-btn btn-sm', 'download', 'CSV', {onclick}) */
  function btn(classes, iconName, label, props = {}) {
    const spec = 'button.' + String(classes).trim().split(/\s+/).join('.');
    const node = el(spec, props);
    if (iconName) node.appendChild(iconEl(iconName, props.iconSize || 14));
    if (label) node.appendChild(document.createTextNode(label));
    return node;
  }

  /* ── Datei-Download ─────────────────────────────────────────────────── */
  function download(filename, content, mime = 'application/octet-stream') {
    const blob = new Blob([content], { type: mime + ';charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 400);
  }

  /** CSV-Feld für Excel (Semikolon-getrennt, deutsche Konvention) */
  const csvCell = v => {
    const s = String(v ?? '');
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csvRows = rows => '﻿' + rows.map(r => r.map(csvCell).join(';')).join('\r\n');

  return {
    pad, iso, parseISO, addDays, addISO, diffDays, todayISO, isWeekend,
    daysInMonth, daysInYear, isoWeek,
    MONTHS, MONTHS_SHORT, DOW, DOW_LONG,
    fmt, fmtShort, fmtLong, fmtRange, num, plural,
    uid, clamp, esc, initials, colorOf, readableOn, debounce, byName,
    AVATAR_COLORS, DEPT_COLORS,
    $, $$, el, frag, icon, iconEl, btn, ICONS,
    download, csvCell, csvRows
  };
})();
