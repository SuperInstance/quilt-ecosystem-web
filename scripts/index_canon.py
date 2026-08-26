#!/usr/bin/env python3
"""
index_canon.py — Index the Quilt canon into Cloudflare Vectorize.
Stdlib-only (no requests) for sandbox compatibility.

Reads:
  - /workspace/ai-writings-new/seed-canon/papers/*.md
  - /workspace/ai-writings-new/seed-canon/fables/*.md
  - /workspace/ai-writings-new/seed-canon/stories/*.md
  - /workspace/ai-writings-new/seed-canon/COLLECTION.md

Chunks each file into 1000-char pieces (with 200-char overlap).
Embeds each chunk via Workers AI (bge-base, 768-dim).
Uploads to Vectorize via the Cloudflare API.

Usage:
  export CF_API_TOKEN=...
  export CF_ACCOUNT_ID=...
  python3 index_canon.py [--dry-run] [--limit=N] [--batch-size=100]
"""
import os
import sys
import json
import re
import urllib.request
import urllib.parse
import argparse
from pathlib import Path

# Config
CANON_DIR = Path("/workspace/ai-writings-new/seed-canon")
API_BASE = "https://api.cloudflare.com/client/v4"
VECTORIZE_INDEX = "quilt-canon"
EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
BATCH_SIZE = 100  # Vectorize accepts up to 100 vectors per insert


def api_request(method, path, body=None, token=None, content_type="application/json"):
    """Make a CF API request using stdlib."""
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if body is not None:
        if content_type == "application/x-ndjson":
            data = body.encode() if isinstance(body, str) else body
        else:
            data = json.dumps(body).encode()
        headers["Content-Type"] = content_type
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except Exception:
            return {"success": False, "errors": [{"message": body}]}


def split_into_chunks(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping chunks. Tries to break on paragraph boundaries."""
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            for sep in ['\n\n', '\n', '. ', ' ']:
                idx = text.rfind(sep, start + size // 2, end)
                if idx > start:
                    end = idx + len(sep)
                    break
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if len(c) > 50]


def extract_title_and_type(path):
    """Extract title from the first H1, type from path."""
    rel = path.relative_to(CANON_DIR)
    parts = rel.parts
    if "papers" in parts:
        ctype = "paper"
    elif "fables" in parts:
        ctype = "fable"
    elif "stories" in parts:
        ctype = "story"
    elif rel.name == "COLLECTION.md":
        ctype = "collection"
    else:
        ctype = "other"
    return ctype


def embed(text, account_id, token):
    """Embed a single chunk via Workers AI REST API."""
    r = api_request(
        "POST",
        f"/accounts/{account_id}/ai/run/{EMBED_MODEL}",
        body={"text": text[:2048]},
        token=token,
    )
    if not r.get("success"):
        raise RuntimeError(f"embed failed: {r.get('errors')}")
    return r["result"]["data"][0]


def index_batch(vectors, account_id, token):
    """Insert a batch of vectors into Vectorize (NDJSON)."""
    if not vectors:
        return
    ndjson = "\n".join(json.dumps(v) for v in vectors)
    r = api_request(
        "POST",
        f"/accounts/{account_id}/vectorize/indexes/{VECTORIZE_INDEX}/insert",
        body=ndjson,
        token=token,
        content_type="application/x-ndjson",
    )
    if not r.get("success"):
        raise RuntimeError(f"insert failed: {r.get('errors')}")
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    account_id = os.environ.get("CF_ACCOUNT_ID")
    token = os.environ.get("CF_API_TOKEN")
    if not args.dry_run and (not account_id or not token):
        print("ERROR: set CF_ACCOUNT_ID and CF_API_TOKEN, or use --dry-run", file=sys.stderr)
        sys.exit(1)

    # Find all .md files
    files = []
    for sub in ["papers", "fables", "stories"]:
        for f in sorted((CANON_DIR / sub).glob("*.md")):
            files.append(f)
    for f in sorted(CANON_DIR.glob("*.md")):
        if f.name not in {"COLLECTION.md"} and f not in files:
            files.append(f)
    if args.limit:
        files = files[:args.limit]

    print(f"Found {len(files)} files. Chunking and embedding...")

    total_chunks = 0
    total_ok = 0
    total_err = 0
    pending_batch = []

    for f in files:
        text = f.read_text(errors="replace")
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = m.group(1).strip() if m else f.stem
        ctype = extract_title_and_type(f)
        chunks = split_into_chunks(text)
        total_chunks += len(chunks)

        for i, chunk in enumerate(chunks):
            chunk_id = f"{f.stem}::{i:03d}"
            metadata = {
                "title": title[:200],
                "type": ctype,
                "path": str(f.relative_to(CANON_DIR.parent))[:200],
                "snippet": chunk[:200].replace("\n", " "),
            }
            if args.dry_run:
                if i == 0:
                    print(f"  {f.relative_to(CANON_DIR)} -> {len(chunks)} chunks (title: {title[:60]})")
            else:
                try:
                    vec = embed(chunk, account_id, token)
                    pending_batch.append({
                        "id": chunk_id,
                        "values": vec,
                        "metadata": metadata,
                    })
                    if len(pending_batch) >= args.batch_size:
                        index_batch(pending_batch, account_id, token)
                        total_ok += len(pending_batch)
                        print(f"  Indexed {total_ok}/{total_chunks} chunks...")
                        pending_batch = []
                except Exception as e:
                    total_err += 1
                    print(f"  ERROR on {chunk_id}: {e}", file=sys.stderr)
                    if total_err > 5:
                        print("Too many errors, aborting", file=sys.stderr)
                        sys.exit(1)

    # Flush final batch
    if pending_batch and not args.dry_run:
        try:
            index_batch(pending_batch, account_id, token)
            total_ok += len(pending_batch)
        except Exception as e:
            print(f"Final batch error: {e}", file=sys.stderr)

    print(f"\n=== Summary ===")
    print(f"Files: {len(files)}")
    print(f"Chunks: {total_chunks}")
    if not args.dry_run:
        print(f"Indexed: {total_ok}")
        print(f"Errors: {total_err}")


if __name__ == "__main__":
    main()
