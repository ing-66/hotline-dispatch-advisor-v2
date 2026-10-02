from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .engine import Engine


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--category")
    args = ap.parse_args()
    rows = Engine(load_config()).search(args.query, args.top_k, category=args.category)
    output = []
    for row in rows:
        p = row["payload"]
        output.append({"score": row["score"], "title": p["title"], "category": p["category"],
                       "source_path": p["source_path"], "section": p["section"], "content": p["content"][:500]})
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
