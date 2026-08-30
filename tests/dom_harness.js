/* Minimal DOM harness for testing extension/w4p.js against replayable
 * PokerBet fixtures. Supports the subset of selectors w4p.js uses:
 * tag, .class, .a.b, "ancestor descendant", comma lists. */
'use strict';

class El {
  constructor(tag, cls) {
    this.tagName = tag.toUpperCase();
    this._cls = new Set((cls || '').split(/\s+/).filter(Boolean));
    this.children = [];
    this.attrs = {};
    this._text = '';
    this.parent = null;
    this.offsetParent = {}; // non-null ⇒ visible (button detection)
  }
  classList = {
    contains: (c) => this._cls.has(c),
  };
  setAttribute(k, v) { this.attrs[k] = String(v); return this; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  dispatchEvent() { return true; } // command-click no-op for tests
  append(...kids) { kids.forEach(k => { k.parent = this; this.children.push(k); }); return this; }
  set textContent(v) { this._text = String(v); }
  get textContent() { return this._text || this.children.map(c => c.textContent).join(''); }
  get innerText() { return this.textContent; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const parts = sel.split(',').map(s => s.trim()).filter(Boolean);
    const out = [];
    parts.forEach(p => collect(this, parse(p), out));
    return out;
  }
}

// selector parser: [tag][.class]*[attr]* [ [tag][.class]*[attr]* ]* (descendant)
function parse(sel) {
  const tokens = sel.split(/\s+/).map(tok => {
    const m = /^([a-z0-9-]*)((?:\.[a-zA-Z0-9_-]+)*)((?:\[[a-zA-Z0-9_-]+(?:=[^\]"]+)?\])*)$/i.exec(tok);
    if (!m) throw new Error('unparseable selector token: ' + JSON.stringify(tok) + ' in ' + JSON.stringify(sel));
    const tag = (m[1] || '').toUpperCase();
    const classes = m[2] ? m[2].slice(1).split('.') : [];
    const attrs = [];
    (m[3] || '').replace(/\[([a-zA-Z0-9_-]+)(?:=([^\]]+))?\]/g, (_, name, val) => {
      attrs.push({ name, val: val ? val.replace(/^["']|["']$/g, '') : null });
      return '';
    });
    return { tag, classes, attrs };
  });
  return tokens;
}

function matches(el, tok) {
  if (tok.tag && el.tagName !== tok.tag) return false;
  if (!tok.classes.every(c => el._cls.has(c))) return false;
  return tok.attrs.every(a => {
    const v = el.getAttribute(a.name);
    return a.val === null ? v !== null : v === a.val;
  });
}

function collect(root, toks, out) {
  walk(root, toks, 0, out);
}

function walk(el, toks, i, out) {
  if (i >= toks.length) return;
  const tok = toks[i];
  const last = i === toks.length - 1;
  for (const child of el.children) {
    if (matches(child, tok)) {
      if (last) out.push(child);
      else walk(child, toks, i + 1, out);
    }
    walk(child, toks, i, out); // descendant: continue matching at this level too
  }
}

function make(tag, cls, text) {
  const e = new El(tag, cls);
  if (text !== undefined) e.textContent = text;
  return e;
}

module.exports = { El, make };
