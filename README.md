# quilt-ecosystem-web — The Quilt Web Ecosystem

> *The substrate is the boat. The web is the dock. The cowboy
> rides the boat to the dock. The dock is where people come
> aboard.*

This repo is the **public face of the Quilt collection** — the
24-repo, 200+ canon-piece, 5-opcode polyformalism. It contains
the static site, the Cloudflare Workers, and the indexing
infrastructure for the ecosystem at `quilt.superinstance.dev`.

## The pages

| Path | What it is | Stack |
|---|---|---|
| `/` | Landing page | Static HTML |
| `/academy/` | 7 interactive lessons | Static + JS substrate |
| `/repl/` | Browser REPL with time-travel | Static + JS substrate |
| `/playground/` | Visual cell editor (drag-drop) | Static + SVG + JS |
| `/apps/{kv,bus,config,sixth,plugins}/` | 5 worked applications | Static + JS |
| `/boundaries/` | Laminar Boundaries explorer | Static + filter |
| `/vms/` | The 5 VMs (C/Rust/TS/Haskell/WASM) | Static |
| `/canon/` | Semantic search over 200+ pieces | Static + Vectorize |
| `/self-host/` | 3-step self-host guide | Static |

## The architecture

```
                    Cloudflare Edge
                   ┌──────────────────┐
                   │   Pages (static) │
                   │   + Workers      │
                   └────────┬─────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
   ┌────▼─────┐      ┌──────▼──────┐      ┌─────▼──────┐
   │   KV     │      │  Vectorize  │      │ Workers AI │
   │ (state)  │      │  (canon)    │      │ (Llama 3.1 │
   └──────────┘      └─────────────┘      │ + bge-base)│
                                         └────────────┘
        ┌──────────────────┐         ┌─────────────┐
        │       D1         │         │     R2      │
        │ (gallery, comm.) │         │ (canon exp) │
        └──────────────────┘         └─────────────┘
```

## The Cloudflare Workers

- **quilt-state-worker** — save/load playground state. KV-backed. 30-day TTL.
- **quilt-search-worker** — semantic canon search. Vectorize + Workers AI.
- **quilt-llm-worker** — LLM proxy with rate-limiting (separate repo).

## Save / load

Every page has three save options:

1. **Save local** — localStorage. Works offline. Forever (until the user clears).
2. **Save to cloud** — POST to `quilt-state-worker` → KV. Returns a share URL with the state ID.
3. **Export JSONL** — saddle-bridge format with hash chain. Drop into a local instance to replay.

The state is yours. The cowboy's maxim extends: the watch is
whoever is holding it.

## Local development

```bash
# Serve the static site
python3 -m http.server 8080

# In another terminal, run the workers
cd workers/state
npm install
npx wrangler dev
# Runs on http://localhost:8787

cd ../search
npm install
npx wrangler dev
# Runs on http://localhost:8788

# Index the canon (one-time)
CF_ACCOUNT_ID=... CF_API_TOKEN=... VECTORIZE_ID=... \
  python3 scripts/index_canon.py
```

## Deploy

```bash
# Static site → Cloudflare Pages
npx wrangler pages deploy . --project-name=quilt

# Workers
cd workers/state && npx wrangler deploy
cd workers/search && npx wrangler deploy

# Custom domain
npx wrangler pages domains add quilt.superinstance.dev
```

## The 5 apps

| App | Lines | What it does |
|---|---|---|
| kv | ~30 | Key-value store. BIND=set, VIEW=get. |
| bus | ~50 | Pub/sub. LINK=subscribe, BIND=publish. |
| config | ~70 | Versioned config with rollback. |
| sixth | ~50 | Derive a 6th opcode, prover accepts/rejects. |
| plugins | ~50 | Self-evolving plugin registry. |

Each is also implemented in C99 in
[quilt-substrate-meta/apps](https://github.com/SuperInstance/quilt-substrate-meta/tree/main/apps).
The web version uses the JS substrate; the C99 version uses
the C substrate. The same journal format works for both.

## The principle

The 5 opcodes appear in the web pages too:

- **BIND** — every cell in the playground has a BIND
- **LINK** — every arrow in the playground has a LINK
- **EFFECT** — every save, every load, every search is an EFFECT
- **VIEW** — every page render is a VIEW of the state
- **TICK** — every time-travel slider is a TICK through the journal

The web is not separate from the substrate. The web **is** the
substrate, opened to the public.

## Related repos

- [quilt-substrate-meta](https://github.com/SuperInstance/quilt-substrate-meta) — the C99 self-evolving substrate
- [quilt-foundation](https://github.com/SuperInstance/quilt-foundation) — the 5 opcodes, math
- [quilt-llm-worker](https://github.com/SuperInstance/quilt-llm-worker) — the LLM proxy Worker
- [quilt-ecosystem-demo](https://github.com/SuperInstance/quilt-ecosystem-demo) — the 12-inch tablet demo
- [AI-Writings](https://github.com/SuperInstance/AI-Writings) — the canon (178 papers, 92 fables, 53 stories)

## License

MIT.

---

> *The cowboy's maxim: the substrate is the boat, the boat has
> a waterline, the waterline is the boundary, the boundary is
> the chart, the chart is the cowboy, the cowboy rides the boat
> through the chart, the chart grows, the boat grows, the
> cowboy grows.*
