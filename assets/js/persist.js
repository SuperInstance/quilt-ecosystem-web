/* Quilt Persist — Save/load playground state.
 *
 * Two paths:
 *   1. Local: localStorage (default, works offline)
 *   2. Cloud: POST to /api/state (Cloudflare Worker → KV, 30-day TTL)
 *
 * The same JSONL format works for both. Export as saddle-bridge
 * (hash-chained) for offline continuation on a local instance.
 */
(function (global) {
  'use strict';

  const STORAGE_KEY = 'quilt:state:v1';
  const HISTORY_KEY = 'quilt:history:v1';

  // ── Local storage ───────────────────────────────────────────────────
  function saveLocal(sub) {
    const jsonl = sub.toJSONL();
    const id = 'local-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const entry = {
      id, name: 'Untitled',
      jsonl, t: sub.t, cells: sub.cellCount(), links: sub.linkCount(),
      savedAt: new Date().toISOString(),
    };
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    history.unshift(entry);
    if (history.length > 50) history.length = 50;
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    localStorage.setItem(STORAGE_KEY + ':' + id, JSON.stringify(entry));
    return entry;
  }

  function loadLocal(id) {
    const raw = localStorage.getItem(STORAGE_KEY + ':' + id);
    if (!raw) return null;
    return JSON.parse(raw);
  }

  function listLocal() {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  }

  // ── Cloud (Cloudflare Worker → KV) ─────────────────────────────────
  async function saveCloud(sub, name) {
    const res = await fetch('/api/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name || 'Untitled',
        jsonl: sub.toJSONL(),
        t: sub.t, cells: sub.cellCount(), links: sub.linkCount(),
      }),
    });
    if (!res.ok) throw new Error('Cloud save failed: ' + res.status);
    return res.json();  // { id, url }
  }

  async function loadCloud(id) {
    const res = await fetch('/api/state/' + id);
    if (!res.ok) throw new Error('Cloud load failed: ' + res.status);
    return res.json();
  }

  // ── Export as saddle-bridge JSONL (for offline continuation) ──────
  // Adds a hash chain so the local instance can verify integrity.
  async function exportSaddleBridge(sub) {
    // djb2 hash
    function hash(s) {
      let h = 5381;
      for (let i = 0; i < s.length; i++) h = ((h << 5) + h) ^ s.charCodeAt(i);
      return (h >>> 0).toString(16).padStart(8, '0');
    }
    const lines = [];
    let prev = '00000000';
    lines.push(JSON.stringify({ meta: 'quilt-saddle-bridge', version: 1, prev }));
    for (const ev of sub.events) {
      const payload = JSON.stringify(ev);
      const h = hash(prev + payload);
      lines.push(JSON.stringify({ event: ev, hash: h, prev }));
      prev = h;
    }
    return lines.join('\n') + '\n';
  }

  // ── Import saddle-bridge JSONL ────────────────────────────────────
  function importSaddleBridge(text) {
    const sub = new Substrate();
    const lines = text.split('\n').filter(l => l.trim());
    for (const line of lines) {
      const obj = JSON.parse(line);
      if (obj.event) {
        sub.events.push(obj.event);
        if (obj.event.op === 'BIND') {
          if (!sub.cells.has(obj.event.id)) sub.cells.set(obj.event.id, new Cell(obj.event.id));
          sub.cells.get(obj.event.id).value = obj.event.value;
        } else if (obj.event.op === 'TICK') {
          sub.t = obj.event.t;
        }
      }
    }
    return sub;
  }

  // ── Export ─────────────────────────────────────────────────────────
  global.QuiltPersist = {
    saveLocal, loadLocal, listLocal,
    saveCloud, loadCloud,
    exportSaddleBridge, importSaddleBridge,
  };
})(typeof window !== 'undefined' ? window : globalThis);
