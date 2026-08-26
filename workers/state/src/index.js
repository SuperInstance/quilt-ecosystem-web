// quilt-state-worker — save/load playground state in Cloudflare KV
//
// Endpoints:
//   POST /api/state     body: { name, jsonl, t, cells, links } -> { id, url }
//   GET  /api/state/:id -> { name, jsonl, t, cells, links, savedAt }
//
// KV namespace: STATE (id from wrangler.toml)
// TTL: 30 days
//
// Rate limit: 100 saves / IP / day (in-memory; replace with a real limit)

const TTL = 60 * 60 * 24 * 30;  // 30 days
const MAX_SIZE = 1024 * 1024;   // 1 MB per save

const rateLimit = new Map();  // ip -> { count, resetAt }

function checkRate(ip) {
  const now = Date.now();
  const entry = rateLimit.get(ip) || { count: 0, resetAt: now + 86400000 };
  if (now > entry.resetAt) { entry.count = 0; entry.resetAt = now + 86400000; }
  entry.count++;
  rateLimit.set(ip, entry);
  return entry.count <= 100;
}

function genId() {
  // 8-char base36, time-prefixed for natural ordering
  return Date.now().toString(36).slice(-4) + Math.random().toString(36).slice(2, 8);
}

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function jsonResponse(obj, origin, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(origin),
    },
  });
}

async function handlePost(request, env, ctx) {
  const origin = request.headers.get('Origin');
  const ip = request.headers.get('CF-Connecting-IP') || '0.0.0.0';
  if (!checkRate(ip)) {
    return jsonResponse({ error: 'rate limit exceeded (100/day)' }, origin, 429);
  }
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return jsonResponse({ error: 'invalid json' }, origin, 400);
  }
  if (!body.jsonl || typeof body.jsonl !== 'string') {
    return jsonResponse({ error: 'missing jsonl' }, origin, 400);
  }
  if (body.jsonl.length > MAX_SIZE) {
    return jsonResponse({ error: `jsonl too large (max ${MAX_SIZE} bytes)` }, origin, 413);
  }
  const id = genId();
  const entry = {
    id,
    name: (body.name || 'Untitled').slice(0, 100),
    jsonl: body.jsonl,
    t: body.t || 0,
    cells: body.cells || 0,
    links: body.links || 0,
    savedAt: new Date().toISOString(),
  };
  await env.STATE.put(`state:${id}`, JSON.stringify(entry), {
    expirationTtl: TTL,
  });
  return jsonResponse({
    id,
    url: `/api/state/${id}`,
    savedAt: entry.savedAt,
    expiresIn: TTL,
  }, origin);
}

async function handleGet(id, env, origin) {
  if (!/^[a-z0-9]{8,16}$/.test(id)) {
    return jsonResponse({ error: 'invalid id' }, origin, 400);
  }
  const raw = await env.STATE.get(`state:${id}`);
  if (!raw) {
    return jsonResponse({ error: 'not found' }, origin, 404);
  }
  const entry = JSON.parse(raw);
  return jsonResponse(entry, origin);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (url.pathname === '/api/state' && request.method === 'POST') {
      return handlePost(request, env, ctx);
    }

    const m = url.pathname.match(/^\/api\/state\/([a-z0-9]{8,16})$/);
    if (m && request.method === 'GET') {
      return handleGet(m[1], env, origin);
    }

    if (url.pathname === '/health') {
      return jsonResponse({ ok: true, name: 'quilt-state-worker' }, origin);
    }

    return jsonResponse({ error: 'not found', path: url.pathname }, origin, 404);
  },
};
