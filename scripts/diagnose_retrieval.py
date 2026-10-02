import os
import re

import httpx

from backend.db.session import SessionLocal
from backend.domain.models import WorkOrder


CATS = [
    "机构职责（知识源顶层 01）",
    "权责清单（知识源顶层 02）",
    "历史工单案例（知识源顶层 03）",
    "国家法律法规（知识源顶层 04）",
    "广州地方性法规（知识源顶层 05）",
    "广州政府规章（知识源顶层 06）",
    "广州行政规范性文件（知识源顶层 07）",
]

db = SessionLocal()
query = db.query(WorkOrder).filter(WorkOrder.id == "b5a7fa7f-3f0d-45b4-9953-ccd27b1fd91e").one().content
db.close()
print("query_len", len(query))

config_path = r"D:\热线派单系统V2\knowledge-service\config\config.yaml"
raw = open(config_path, encoding="utf-8").read()
key = re.search(r"(?m)^api_key:\s*(.+?)\s*$", raw).group(1)

for cat in CATS:
    body = {
        "knowledge_id": "hotline_dispatch_v2",
        "query": query,
        "retrieval_setting": {"top_k": 3, "score_threshold": 0.0},
        "metadata_condition": {"category": cat},
    }
    response = httpx.post(
        "http://127.0.0.1:8088/retrieval",
        json=body,
        headers={"Authorization": f"Bearer {key}"},
        timeout=180,
        trust_env=False,
    )
    records = response.json().get("records") or []
    print("CAT", cat, "hits", len(records))
    for record in records[:3]:
        metadata = record.get("metadata") or {}
        print(
            " -",
            str(record.get("title"))[:60],
            round(float(record.get("score", 0)), 3),
            "doc",
            metadata.get("document_id"),
            "header",
            metadata.get("document_header"),
        )
