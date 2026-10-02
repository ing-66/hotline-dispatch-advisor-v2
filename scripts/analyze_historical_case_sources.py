"""Read-only analysis of historical case sources vs Qdrant historical_case points.

Purpose: establish an exact, evidence-based mapping before importing anything.
No MySQL or Qdrant writes are performed.

Usage:
    python scripts/analyze_historical_case_sources.py [--out <json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_DIR = PROJECT_ROOT / "assets" / "knowledge-source" / "03_历史工单案例"
CATEGORY = "历史工单案例（知识源顶层 03）"
QDRANT = "http://127.0.0.1:6333"
FILE_PATTERN = re.compile(r"^(\d{5})_(.+)__([0-9a-f]{10})\.md$")


def parse_source_file(path: Path) -> dict[str, Any] | None:
    match = FILE_PATTERN.match(path.name)
    if not match:
        return None
    content = path.read_text(encoding="utf-8")
    marker = "\n## "
    index = content.find(marker)
    if index < 0:
        return None
    body = content[index + 1 :].rstrip()
    return {
        "path": str(path),
        "request_type": path.parent.name.replace("__拆分", ""),
        "seq": int(match.group(1)),
        "title": match.group(2),
        "name_hash": match.group(3),
        "content": content,
        "body": body,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def scroll_historical_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    offset = None
    with httpx.Client(trust_env=False, timeout=120.0) as client:
        while True:
            body: dict[str, Any] = {
                "filter": {"must": [{"key": "category", "match": {"value": CATEGORY}}]},
                "limit": 1000,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            response = client.post(
                f"{QDRANT}/collections/hotline_dispatch_v2/points/scroll", json=body
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload["result"]["points"]
            points.extend(batch)
            offset = payload["result"].get("next_page_offset")
            if offset is None:
                break
    return points


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="JSON summary output path")
    args = parser.parse_args()

    files = [parse_source_file(p) for p in sorted(HISTORICAL_DIR.rglob("*.md"))]
    parsed = [f for f in files if f is not None]
    unparsed = [f for f in files if f is None]

    points = scroll_historical_points()
    point_rows = []
    for point in points:
        payload = dict(point.get("payload") or {})
        content = str(payload.get("content") or "")
        point_rows.append({
            "point_id": str(point["id"]),
            "document_id": payload.get("document_id"),
            "version_id": payload.get("version_id"),
            "ordinal": payload.get("ordinal"),
            "title": payload.get("title"),
            "section": payload.get("section"),
            "sha256": payload.get("sha256"),
            "content": content,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })

    file_by_body_sha: dict[str, list[dict[str, Any]]] = {}
    for item in parsed:
        file_by_body_sha.setdefault(item["body_sha256"], []).append(item)

    matched = []
    unmatched_points = []
    content_dup_points: dict[str, list[dict[str, Any]]] = {}
    for row in point_rows:
        content_dup_points.setdefault(row["content_sha256"], []).append(row)
        candidates = file_by_body_sha.get(row["content_sha256"], [])
        if len(candidates) == 1:
            matched.append({"point": row, "file": candidates[0]})
        else:
            unmatched_points.append(row)

    print(f"source files total={len(files)} parsed={len(parsed)} unparsed={len(unparsed)}")
    print(f"qdrant historical points={len(point_rows)}")
    print(f"points exactly matched to one source file={len(matched)}")
    print(f"points unmatched/ambiguous={len(unmatched_points)}")

    per_title = Counter(row["title"] for row in point_rows)
    per_type_files = Counter(item["request_type"] for item in parsed)
    print("qdrant per title:", dict(per_title))
    print("source per type:", dict(per_type_files))

    duplicate_content_points = {k: v for k, v in content_dup_points.items() if len(v) > 1}
    print(f"duplicate point content sha count={len(duplicate_content_points)}")

    matched_ids = {row["point"]["point_id"] for row in matched}
    unmatched_summary = []
    for row in unmatched_points:
        unmatched_summary.append({
            "point_id": row["point_id"],
            "document_id": row["document_id"],
            "ordinal": row["ordinal"],
            "title": row["title"],
            "section": row["section"],
            "content_sha256": row["content_sha256"],
            "content_head": row["content"][:120],
            "candidates": [f["path"] for f in file_by_body_sha.get(row["content_sha256"], [])][:3],
        })

    report: dict[str, Any] = {
        "category": CATEGORY,
        "source_dir": str(HISTORICAL_DIR),
        "source_files_total": len(files),
        "source_files_parsed": len(parsed),
        "source_unparsed": [str(p) for p in unparsed],
        "qdrant_points_total": len(point_rows),
        "matched_points": len(matched),
        "unmatched_points": len(unmatched_points),
        "per_title_points": dict(per_title),
        "per_type_source_files": dict(per_type_files),
        "duplicate_point_content_groups": len(duplicate_content_points),
        "unmatched_detail": unmatched_summary,
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report written: {out}")
    print("READ-ONLY ANALYSIS COMPLETE (no writes to MySQL/Qdrant)")


if __name__ == "__main__":
    sys.exit(main())
