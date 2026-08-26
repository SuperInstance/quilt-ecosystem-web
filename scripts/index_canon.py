#!/usr/bin/env python3
"""
index_canon.py — Index the Quilt canon into Cloudflare Vectorize.

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
  python3 index_canon.py [--dry-run] [--limit=10]
"""
import os
import sys
import json
import re
import argparse
import requests
from pathlib import Path

# Config
CANON_DIR = Path("/workspace/ai-writings-new/seed-canon")
API_BASE = "https://api.cloudflare.com/client/v4"
VECTORIZE_INDEX = "quilt-canon"
EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"
EMBED_URL = f"/accounts/{os.environ.get('CF_ACCOUNT_ID', 'ACCOUNT_ID')}/ai/run/{EMBED_MODEL}"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def split_into_chunks(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping chunks. Tries to break on paragraph boundaries."""
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # Try to break on a paragraph or sentence boundary
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
    if 'papers' in parts:
        ctype = 'paper'
    elif 'fables' in parts:
        ctype = 'fable'
    elif 'stories' in parts:
        ctype = 'story'
    elif rel.name == 'COLLECTION.md':
        ctype = 'collection'
    else:
        ctype = 'other'
    return ctype


def embed(text, account_id, token):
    """Embed a single chunk via Workers AI REST API."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{EMBED_MODEL}"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"text": text[:2048]},  # truncate for safety
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data["result"]["data"][0]


def index_chunk(chunk_id, text, metadata, account_id, token, vectorize_id):
    """Embed a chunk and insert into Vectorize."""
    vec = embed(text, account_id, token)
    url = f"{API_BASE}/accounts/{account_id}/vectorize/indexes/{vectorize_id}/insert"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=[{
            "id": chunk_id,
            "values": vec,
            "metadata": {
                "title": metadata["title"][:200],
                "type": metadata["type"],
                "path": metadata["path"][:200],
                "snippet": text[:200].replace("\n", " "),
            },
        }],
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would be indexed without calling API")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of files (for testing)")
    parser.add_argument("--vectorize-id", default=os.environ.get("VECTORIZE_ID", ""), help="Vectorize index ID")
    args = parser.parse_args()

    account_id = os.environ.get("CF_ACCOUNT_ID")
    token = os.environ.get("CF_API_TOKEN")
    if not args.dry_run and (not account_id or not token):
        print("ERROR: set CF_ACCOUNT_ID and CF_API_TOKEN, or use --dry-run", file=sys.stderr)
        sys.exit(1)
    if not args.dry_run and not args.vectorize_id:
        print("ERROR: set VECTORIZE_ID or pass --vectorize-id", file=sys.stderr)
        sys.exit(1)

    # Find all .md files
    files = []
    for sub in ['papers', 'fables', 'stories']:
        for f in sorted((CANON_DIR / sub).glob("*.md")):
            files.append(f)
    for f in sorted(CANON_DIR.glob("*.md")):
        if f.name not in {'COLLECTION.md'} and f not in files:
            files.append(f)

    if args.limit:
        files = files[:args.limit]

    print(f"Found {len(files)} files. Chunking and embedding...")

    total_chunks = 0
    total_ok = 0
    total_err = 0
    for f in files:
        text = f.read_text(errors='replace')
        # Extract title from first H1 or filename
        m = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        title = m.group(1).strip() if m else f.stem
        ctype = extract_title_and_type(f)
        chunks = split_into_chunks(text)
        total_chunks += len(chunks)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{f.stem}::{i:03d}"
            metadata = {
                "title": title,
                "type": ctype,
                "path": str(f.relative_to(CANON_DIR.parent)),
            }
            if args.dry_run:
                if i == 0:
                    print(f"  {f.relative_to(CANON_DIR)} → {len(chunks)} chunks (title: {title[:60]})")
            else:
                try:
                    index_chunk(chunk_id, chunk, metadata, account_id, token, args.vectorize_id)
                    total_ok += 1
                    if total_ok % 50 == 0:
                        print(f"  Indexed {total_ok}/{total_chunks} chunks...")
                except Exception as e:
                    total_err += 1
                    print(f"  ERROR on {chunk_id}: {e}", file=sys.stderr)
                    if total_err > 5:
                        print("Too many errors, aborting", file=sys.stderr)
                        sys.exit(1)

    print(f"\n=== Summary ===")
    print(f"Files: {len(files)}")
    print(f"Chunks: {total_chunks}")
    if not args.dry_run:
        print(f"Indexed: {total_ok}")
        print(f"Errors: {total_err}")


if __name__ == "__main__":
    main()
