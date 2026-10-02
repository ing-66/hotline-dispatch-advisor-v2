from __future__ import annotations

import re
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import load_config
from .engine import Engine

cfg = load_config()
engine = Engine(cfg)
app = FastAPI(title="热线派单外部知识库", version="1.0.0")


def content_with_department_heading(payload: dict) -> str:
    """Restore the nearest department heading lost by small institution-duty chunks."""
    content = payload["content"]
    if payload.get("category") != "01_机构职责":
        return content
    try:
        source = Path(cfg["source_root"]) / payload["source_path"]
        source_text = source.read_text(encoding="utf-8")
        start = max(0, int(payload.get("start") or 0))
        headings = re.findall(r"^##\s+(.+?)\s*$", source_text[:start], flags=re.MULTILINE)
        if headings:
            heading = headings[-1].strip()
            if heading and heading not in content:
                return f"【所属部门（原文标题）】\n{heading}\n\n{content}"
    except (OSError, TypeError, ValueError):
        pass
    return content


class RetrievalSetting(BaseModel):
    top_k: int = Field(default=8, ge=1, le=50)
    score_threshold: float | None = 0.0


class RetrievalRequest(BaseModel):
    knowledge_id: str
    query: str = Field(min_length=1)
    retrieval_setting: RetrievalSetting = RetrievalSetting()
    metadata_condition: dict | None = None


class BatchRetrievalRequest(BaseModel):
    knowledge_id: str
    query: str = Field(min_length=1)
    categories: list[str] = Field(min_length=1, max_length=20)
    retrieval_setting: RetrievalSetting = RetrievalSetting()


def authorize(value: str | None) -> None:
    expected = f"Bearer {cfg['api_key']}"
    if not value or value != expected:
        raise HTTPException(status_code=401, detail="invalid API key")


@app.get("/health")
def health():
    # MySQL 为可选组件：未启用或异常均不影响主检索服务 status，
    # 保证 status.ps1 的既有契约不回退；启用时在 mysql 子字段给出可诊断信息。
    mysql_state = {"enabled": False, "detail": "mysql.enabled=false（未启用，现有链路不受影响）"}
    try:
        from .db.health import check_mysql, format_check

        mysql_state = check_mysql(cfg)
        mysql_state["summary"] = format_check(mysql_state)
    except Exception as exc:  # noqa: BLE001 —— health 永不因附属组件崩溃
        mysql_state = {"enabled": True, "ok": False, "error": str(exc)}
    qdrant_state = {"ok": False, "collection": cfg["collection"]}
    try:
        info = engine.qdrant.get_collection(cfg["collection"])
        qdrant_state.update(ok=True, points=int(info.points_count or 0))
    except Exception as exc:  # noqa: BLE001
        qdrant_state["error"] = type(exc).__name__

    lexical_state = {"ok": False}
    try:
        lexical_path = Path(cfg["lexical_db"])
        with sqlite3.connect(f"file:{lexical_path.as_posix()}?mode=ro", uri=True) as db:
            lexical_state.update(ok=True, rows=int(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]))
    except Exception as exc:  # noqa: BLE001
        lexical_state["error"] = type(exc).__name__

    asset_root = Path(os.environ.get("KB_ASSET_ROOT", Path(cfg["project_root"]) / "data" / "kb-assets"))
    storage_state = {"ok": asset_root.is_dir(), "writable": os.access(asset_root, os.W_OK) if asset_root.exists() else False}
    mysql_ok = True if mysql_state.get("enabled") is False else bool(mysql_state.get("ok"))
    dependencies_ok = qdrant_state["ok"] and lexical_state["ok"] and storage_state["ok"] and mysql_ok
    return {"status": "ok" if dependencies_ok else "degraded", "collection": cfg["collection"],
            "mysql": mysql_state, "qdrant": qdrant_state, "fts": lexical_state, "file_storage": storage_state}


@app.post("/retrieval")
def retrieval(req: RetrievalRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    category = None
    if req.metadata_condition:
        category = req.metadata_condition.get("category")
    threshold = req.retrieval_setting.score_threshold or 0.0
    rows = engine.search(req.query, req.retrieval_setting.top_k, threshold, category)
    return {"records": rows_to_records(rows)}


def rows_to_records(rows: list[dict]) -> list[dict]:
    records = []
    for index, row in enumerate(rows, start=1):
        p = row["payload"]
        evidence_id = f"E{index}"
        source_title = p["title"]
        evidence_content = content_with_department_heading(p)
        records.append({
            "content": (
                f"【证据ID：{evidence_id}】\n"
                f"【文件名：{source_title}】\n"
                "【以下为知识库原文，引用时必须逐字复制】\n"
                f"{evidence_content}"
            ),
            "score": row["score"],
            "title": f"[{evidence_id}] {source_title}",
            "metadata": {
                **{k: p.get(k) for k in (
                    "chunk_id", "document_id", "category", "source_path", "section",
                    "start", "end", "sha256", "knowledge_type", "work_order_id", "source_case_id",
                    "document_header",
                )},
                "evidence_id": evidence_id,
                "source_title": source_title,
            }
        })
    return records


@app.post("/retrieval/batch")
def retrieval_batch(req: BatchRetrievalRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    threshold = req.retrieval_setting.score_threshold or 0.0
    grouped = engine.search_many(req.query, req.retrieval_setting.top_k, req.categories, threshold)
    return {"records_by_category": {
        category: rows_to_records(grouped.get(category, [])) for category in req.categories
    }}
