// quilt-search-worker — semantic search across the Quilt canon
//
// Endpoints:
//   POST /api/search   body: { q, limit } -> [{ id, title, type, score, snippet }]
//   GET  /api/related/:id  -> [{ id, title, type, score }]
//   GET  /api/canon/stats  -> { total_chunks, total_papers, total_fables, total_stories }
//
// Vectorize index: CANON (768-dim bge-base)
// Workers AI: bge-base-en-v1.5 (free, multilingual, multilingual embeddings)
//
// Indexing: scripts/index_canon.py (run separately to populate the index)

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

async function embed(text, env) {
  // Workers AI: bge-base-en-v1.5 produces 768-dim vectors
  // Free, multilingual
  const result = await env.AI.run('@cf/baai/bge-base-en-v1.5', {
    text: text.slice(0, 2048),  // bge-base has 512 token limit, but we truncate
  });
  return result.data[0];
}

async function handleSearch(request, env) {
  const origin = request.headers.get('Origin');
  const body = await request.json();
  const q = (body.q || '').trim();
  if (!q) return jsonResponse({ error: 'missing q' }, origin, 400);
  const limit = Math.min(body.limit || 10, 50);

  const queryVector = await embed(q, env);
  const matches = await env.CANON.query(queryVector, {
    topK: limit,
    returnMetadata: 'all',
  });

  return jsonResponse({
    q,
    results: matches.matches.map(m => ({
      id: m.id,
      score: m.score,
      ...m.metadata,
    })),
  }, origin);
}

async function handleRelated(id, env) {
  const origin = request.headers.get('Origin');
  // Look up the id in Vectorize, then find similar
  const matches = await env.CANON.getByIds([id]);
  if (!matches.length) return jsonResponse({ error: 'not found' }, origin, 404);
  const vec = matches[0].values;
  const similar = await env.CANON.query(vec, {
    topK: 11,  // 1 self + 10 related
    returnMetadata: 'all',
  });
  return jsonResponse({
    id,
    related: similar.matches
      .filter(m => m.id !== id)
      .slice(0, 10)
      .map(m => ({ id: m.id, score: m.score, ...m.metadata })),
  }, origin);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin');

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (url.pathname === '/api/search' && request.method === 'POST') {
      try { return await handleSearch(request, env); }
      catch (e) { return jsonResponse({ error: e.message }, origin, 500); }
    }

    const m = url.pathname.match(/^\/api\/related\/([\w\-:]+)$/);
    if (m && request.method === 'GET') {
      try { return await handleRelated(m[1], env); }
      catch (e) { return jsonResponse({ error: e.message }, origin, 500); }
    }

    if (url.pathname === '/api/canon/stats' && request.method === 'GET') {
      // Vectorize doesn't have a count endpoint yet; return last indexed metadata
      // In production, this would be backed by D1
      return jsonResponse({
        note: 'stats backed by indexer script — see scripts/index_canon.py',
        dimensions: 768,
        model: '@cf/baai/bge-base-en-v1.5',
      }, origin);
    }

    if (url.pathname === '/health') {
      return jsonResponse({ ok: true, name: 'quilt-search-worker' }, origin);
    }

    return jsonResponse({ error: 'not found', path: url.pathname }, origin, 404);
  },
};
