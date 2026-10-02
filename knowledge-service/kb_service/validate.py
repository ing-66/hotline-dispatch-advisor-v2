from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .chunking import chunk_file
from .config import load_config


BAD = re.compile(r"[ꎬ�]|(?:锟斤拷)|(?:烫烫烫)")


def main():
    cfg = load_config()
    root = Path(cfg["source_root"])
    allowed = set(cfg.get("include_categories") or [])
    counts = Counter()
    problems = []
    total_chars = 0
    total_chunks = 0
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if allowed and rel.split("/", 1)[0] not in allowed:
            continue
        try:
            text = p.read_text(encoding="utf-8-sig")
            total_chars += len(text)
            chunks = chunk_file(p, root)
            total_chunks += len(chunks)
            counts[rel.split("/", 1)[0]] += 1
            if BAD.search(text):
                problems.append({"file": rel, "problem": "疑似乱码"})
            if not chunks:
                problems.append({"file": rel, "problem": "无有效分段"})
        except Exception as exc:
            problems.append({"file": rel, "problem": repr(exc)})
    report = {"files": sum(counts.values()), "characters": total_chars, "chunks": total_chunks,
              "categories": dict(counts), "problems": problems}
    out = Path(cfg["log_dir"]) / "source_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
