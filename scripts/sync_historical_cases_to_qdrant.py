"""Sync MySQL work_order business IDs into Qdrant historical_case payloads.

Updates only payload metadata fields:
    knowledge_type, work_order_id, source_case_id

Vectors, point IDs, content and all other payload fields are untouched.
Document-header points (5, one per request type) have no matching work order and
are deliberately left unmodified.

Default is a read-only dry-run. Use --apply to write payloads.

Usage:
    python scripts/sync_historical_cases_to_qdrant.py [--apply] [--out <json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from scripts.historical_case_parser import parse_all_cases


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "assets" / "knowledge-source" / "03_历史工单案例"
CATEGORY = "历史工单案例（知识源顶层 03）"
QDRANT = "http://127.0.0.1:6333"
COLLECTION = "hotline_dispatch_v2"


def scroll_points(client: httpx.Client) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    offset = None
    while True:
        body: dict[str, Any] = {
            "filter": {"must": [{"key": "category", "match": {"value": CATEGORY}}]},
            "limit": 1000,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        response = client.post(f"{QDRANT}/collections/{COLLECTION}/points/scroll", json=body)
        response.raise_for_status()
        payload = response.json()
        points.extend(payload["result"]["points"])
        offset = payload["result"].get("next_page_offset")
        if offset is None:
            break
    return points


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()

    parsed, _ = parse_all_cases(SOURCE_DIR)
    body_sha_to_case: dict[str, str] = {item.body_sha256: item.source_case_id for item in parsed}
    print(f"parsed source cases={len(parsed)} body_sha unique={len(body_sha_to_case)}")

    from backend.db.session import SessionLocal
    from backend.domain.models import WorkOrder

    db = SessionLocal()
    try:
        id_by_source_case = {
            row.source_case_id: row.id
            for row in db.query(WorkOrder).filter(WorkOrder.source_case_id.isnot(None)).all()
        }
        print(f"mysql work_orders with source_case_id={len(id_by_source_case)}")
    finally:
        db.close()

    with httpx.Client(trust_env=False, timeout=180.0) as client:
        points = scroll_points(client)
        to_update: dict[str, dict[str, Any]] = {}
        unmatched: list[dict[str, Any]] = []
        for point in points:
            payload = dict(point.get("payload") or {})
            content = str(payload.get("content") or "")
            content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
            source_case_id = body_sha_to_case.get(content_sha)
            work_order_id = id_by_source_case.get(source_case_id) if source_case_id else None
            if source_case_id and work_order_id:
                to_update[str(point["id"])] = {
                    "knowledge_type": "historical_case",
                    "work_order_id": work_order_id,
                    "source_case_id": source_case_id,
                }
            else:
                unmatched.append({
                    "point_id": str(point["id"]),
                    "section": payload.get("section"),
                    "title": payload.get("title"),
                    "content_head": content[:80],
                })

        print(f"qdrant historical points={len(points)}")
        print(f"points to update={len(to_update)} unmatched={len(unmatched)}")
        per_title = Counter(
            next((u["title"] for u in unmatched if u["point_id"] == str(p["id"])), None)
            for p in points if str(p["id"]) in {u["point_id"] for u in unmatched}
        )
        print("unmatched per title:", dict(per_title))

        if args.apply and to_update:
            for point_id, metadata in to_update.items():
                response = client.post(
                    f"{QDRANT}/collections/{COLLECTION}/points/payload",
                    json={"payload": metadata, "points": [point_id]},
                )
                response.raise_for_status()
                result = response.json()
                if result.get("status") != "ok":
                    raise RuntimeError(f"qdrant set_payload failed for {point_id}: {result}")
            print(f"applied metadata to {len(to_update)} points")
        if args.apply and unmatched:
            for point in unmatched:
                response = client.post(
                    f"{QDRANT}/collections/{COLLECTION}/points/payload",
                    json={"payload": {"knowledge_type": "historical_case", "document_header": True},
                          "points": [point["point_id"]]},
                )
                response.raise_for_status()
            print(f"annotated {len(unmatched)} document-header points (no business ids)")

        report: dict[str, Any] = {
            "mode": "apply" if args.apply else "dry-run",
            "source_cases": len(parsed),
            "mysql_source_case_ids": len(id_by_source_case),
            "qdrant_historical_points": len(points),
            "points_updated": len(to_update),
            "points_unmatched": len(unmatched),
            "document_header_annotated": len(unmatched),
            "unmatched_detail": unmatched,
        }
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"report written: {out}")


if __name__ == "__main__":
    sys.exit(main())
