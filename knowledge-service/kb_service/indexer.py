from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from .chunking import chunk_file
from .config import load_config
from .engine import Engine


MANIFEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
 source_path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
 chunk_count INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category")
    ap.add_argument("--sample-per-category", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    root = Path(cfg["source_root"])
    manifest = sqlite3.connect(cfg["manifest_db"])
    manifest.executescript(MANIFEST_SCHEMA)
    engine = Engine(cfg)
    files = sorted(root.rglob("*.md"))
    allowed = set(cfg.get("include_categories") or [])
    if allowed:
        files = [p for p in files if p.relative_to(root).parts[0] in allowed]
    if args.category:
        files = [p for p in files if p.relative_to(root).parts[0] == args.category]
    if args.sample_per_category:
        by_category = {}
        for p in files:
            category = p.relative_to(root).parts[0]
            if p.stat().st_size >= 300:
                current = by_category.get(category)
                if current is None or p.stat().st_size < current.stat().st_size:
                    by_category[category] = p
        files = [by_category[k] for k in sorted(by_category)]
    if args.limit:
        files = files[:args.limit]
    batch_size = int(cfg.get("index_batch_size", 8))
    summary = {"files_seen": len(files), "indexed": 0, "skipped": 0, "failed": 0, "chunks": 0, "errors": []}
    report = Path(cfg["log_dir"]) / "last_index_report.json"
    progress = Path(cfg["log_dir"]) / "index_progress.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    def save_progress(current_file: str = ""):
        state = dict(summary)
        state["current_file"] = current_file
        progress.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    save_progress()
    for path in files:
        rel = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        previous = manifest.execute("SELECT sha256,status FROM files WHERE source_path=?", (rel,)).fetchone()
        if previous == (sha, "indexed"):
            summary["skipped"] += 1
            save_progress(rel)
            continue
        try:
            chunks = chunk_file(path, root)
            if not chunks:
                raise ValueError("empty chunk set")
            payloads = [c.payload() for c in chunks]
            for i in range(0, len(payloads), batch_size):
                engine.upsert(payloads[i:i + batch_size])
            with manifest:
                manifest.execute("INSERT OR REPLACE INTO files(source_path,sha256,bytes,chunk_count,status,error) VALUES (?,?,?,?,?,NULL)",
                                 (rel, sha, len(raw), len(chunks), "indexed"))
            summary["indexed"] += 1
            summary["chunks"] += len(chunks)
        except Exception as exc:
            with manifest:
                manifest.execute("INSERT OR REPLACE INTO files(source_path,sha256,bytes,chunk_count,status,error) VALUES (?,?,?,?,?,?)",
                                 (rel, sha, len(raw), 0, "failed", repr(exc)))
            summary["failed"] += 1
            summary["errors"].append({"file": rel, "error": repr(exc)})
        save_progress(rel)
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    save_progress("COMPLETED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
