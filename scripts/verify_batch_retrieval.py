from __future__ import annotations

import re
import time
from pathlib import Path

import httpx


CATEGORIES = [
    "机构职责（知识源顶层 01）",
    "权责清单（知识源顶层 02）",
    "历史工单案例（知识源顶层 03）",
    "国家法律法规（知识源顶层 04）",
    "广州地方性法规（知识源顶层 05）",
    "广州政府规章（知识源顶层 06）",
    "广州行政规范性文件（知识源顶层 07）",
]
QUERY = "白云区江高镇出租屋内疑似无证牙科诊所，器械消毒条件差，请核查"


def config_value(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    if not match:
        raise RuntimeError(f"missing config: {key}")
    return match.group(1).strip().strip("'\"")


def ids(records: list[dict]) -> list[str]:
    return [str(item.get("metadata", {}).get("chunk_id")) for item in records]


def main() -> None:
    config = (Path(__file__).parents[1] / "knowledge-service" / "config" / "config.yaml").read_text(encoding="utf-8")
    key = config_value(config, "api_key")
    collection = config_value(config, "collection")
    headers = {"Authorization": f"Bearer {key}"}
    setting = {"top_k": 12, "score_threshold": 0.0}
    with httpx.Client(base_url="http://127.0.0.1:8088", headers=headers, timeout=180) as client:
        started = time.perf_counter()
        legacy = {}
        for category in CATEGORIES:
            response = client.post("/retrieval", json={
                "knowledge_id": collection, "query": QUERY,
                "retrieval_setting": setting, "metadata_condition": {"category": category},
            })
            response.raise_for_status()
            legacy[category] = response.json()["records"]
        legacy_seconds = time.perf_counter() - started

        started = time.perf_counter()
        response = client.post("/retrieval/batch", json={
            "knowledge_id": collection, "query": QUERY,
            "categories": CATEGORIES, "retrieval_setting": setting,
        })
        response.raise_for_status()
        batch = response.json()["records_by_category"]
        batch_seconds = time.perf_counter() - started

    mismatches = [category for category in CATEGORIES if ids(legacy[category]) != ids(batch[category])]
    print(f"legacy={legacy_seconds:.2f}s batch={batch_seconds:.2f}s mismatches={len(mismatches)}")
    if mismatches:
        for category in mismatches:
            print(f"MISMATCH {category}: legacy={ids(legacy[category])} batch={ids(batch[category])}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
