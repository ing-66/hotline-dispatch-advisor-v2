"""Verify the real Knowledge API + Qdrant retrieval chain.

Usage:
    $env:KS_BASE_URL = "http://127.0.0.1:8088"
    $env:KS_API_KEY  = "<local knowledge service api key>"
    python scripts/verify_knowledge_service.py [--out baseline.json]

The script performs:
  1. GET /health and checks Qdrant/collection status.
  2. Real /retrieval calls for the four knowledge groups
     (department duties / authority lists / regulations / historical cases).
  3. Optional JSON snapshot of top hits for before/after comparisons.

No business data is modified. The API key is only read from the environment.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import httpx
import yaml


COLLECTION = os.environ.get("KS_COLLECTION", "hotline_dispatch_v2")
BASE_URL = os.environ.get("KS_BASE_URL", "http://127.0.0.1:8088").rstrip("/")

# Category values stored in Qdrant payloads and understood by the Knowledge API.
KNOWLEDGE_GROUPS: dict[str, list[str]] = {
    "department_duties": ["机构职责（知识源顶层 01）"],
    "responsibilities": ["权责清单（知识源顶层 02）"],
    "historical_cases": ["历史工单案例（知识源顶层 03）"],
    "regulations": [
        "国家法律法规（知识源顶层 04）",
        "广州地方性法规（知识源顶层 05）",
        "广州政府规章（知识源顶层 06）",
        "广州行政规范性文件（知识源顶层 07）",
    ],
}

QUERIES = [
    "市民反映住宅小区物业服务企业长期不履行管理责任，多次反映仍未处理公共区域环境卫生问题，希望主管部门督促整改。",
    "市民投诉夜市餐饮店占道经营、食客喧哗噪声扰民，同时油烟直排污染空气，请有关部门尽快处理。",
    "咨询住宅专项维修资金如何使用申请，电梯故障维修能否列支，由哪个部门审批。",
    "反映某快递公司泄露客户个人信息和身份证号码，希望监管部门查处。",
    "反映工厂夜间施工噪声扰民，希望生态环境部门现场检测并责令整改。",
]


def load_api_key() -> str:
    """Read the API key from KS_API_KEY; config.yaml fallback for local runs."""
    value = os.environ.get("KS_API_KEY")
    if value:
        return value
    candidate = os.environ.get("HOTLINE_KB_CONFIG")
    if candidate and os.path.exists(candidate):
        with open(candidate, encoding="utf-8") as fh:
            return str((yaml.safe_load(fh) or {}).get("api_key", ""))
    raise SystemExit("KS_API_KEY is required (or set HOTLINE_KB_CONFIG)")


def fetch_health(client: httpx.Client) -> dict[str, Any]:
    response = client.get("/health")
    response.raise_for_status()
    payload = response.json()
    assert payload.get("collection") == COLLECTION, "collection mismatch"
    assert payload.get("qdrant", {}).get("ok"), "qdrant not ok"
    return payload


def fetch_retrieval(client: httpx.Client, query: str, category: str, top_k: int = 3) -> list[dict[str, Any]]:
    body = {
        "knowledge_id": COLLECTION,
        "query": query,
        "retrieval_setting": {"top_k": top_k, "score_threshold": 0.0},
        "metadata_condition": {"category": category},
    }
    response = client.post("/retrieval", json=body)
    response.raise_for_status()
    records = [dict(r) for r in (response.json().get("records") or [])]
    leaked = [r for r in records if (r.get("metadata") or {}).get("document_header") is True]
    if leaked:
        raise SystemExit("document_header point leaked into retrieval results")
    return records


def top_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for record in records:
        metadata = record.get("metadata") or {}
        content = str(record.get("content") or "")
        output.append({
            "chunk_id": str(metadata.get("chunk_id") or ""),
            "title": str(record.get("title") or ""),
            "score": record.get("score"),
            "content_len": len(content),
            "content_head": content[:120],
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="optional JSON file with full before/after snapshot")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    api_key = load_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    results: dict[str, Any] = {"base_url": BASE_URL, "collection": COLLECTION,
                               "queries": [], "groups": {}, "health": None}

    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=60.0) as client:
        health = fetch_health(client)
        results["health"] = health
        print(f"health status={health.get('status')} qdrant_points={health.get('qdrant', {}).get('points')} "
              f"fts_rows={health.get('fts', {}).get('rows')}")

        for query in QUERIES:
            query_result = {"query": query, "categories": {}}
            for group, categories in KNOWLEDGE_GROUPS.items():
                group_total = 0
                for category in categories:
                    records = fetch_retrieval(client, query, category, top_k=args.top_k)
                    query_result["categories"].setdefault(group, {})[category] = {
                        "count": len(records),
                        "top": top_summary(records),
                    }
                    group_total += len(records)
                    print(f"[{'OK' if records else 'EMPTY'}] {group} | {category} | hits={len(records)} | {query[:24]}...")
                if group_total == 0:
                    raise SystemExit(f"no results for group {group} on query: {query[:40]}")
            results["queries"].append(query_result)

    # Group coverage assertion: every group has at least one non-empty category.
    assert all(any(v.get("count", 0) for v in cat_values.values())
               for q in results["queries"]
               for cat_values in [q["categories"][g] for g in KNOWLEDGE_GROUPS])

    print("ALL FOUR KNOWLEDGE GROUPS RETURNED REAL RESULTS: PASS")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print(f"snapshot written: {args.out}")


if __name__ == "__main__":
    main()
