from __future__ import annotations

from pathlib import Path
from uuid import UUID
import math
import re

from qdrant_client import QdrantClient, models as qm

from .filter_policy import RETRIEVAL_EXCLUSIONS
from .models import Models
from .store import LexicalStore


def point_uuid(hex_id: str) -> str:
    return str(UUID(hex=hex_id[:32]))


class Engine:
    def __init__(self, cfg: dict):
        Path(cfg["qdrant_path"]).mkdir(parents=True, exist_ok=True)
        self.cfg = cfg
        self.models = Models(cfg)
        self.lexical = LexicalStore(cfg["lexical_db"])
        qdrant_url = cfg.get("qdrant_url")
        self.qdrant = (
            QdrantClient(url=qdrant_url, timeout=120)
            if qdrant_url
            else QdrantClient(path=cfg["qdrant_path"])
        )
        self.collection = cfg["collection"]

    def ensure_collection(self, dimension: int) -> None:
        names = {c.name for c in self.qdrant.get_collections().collections}
        if self.collection not in names:
            self.qdrant.create_collection(self.collection, vectors_config=qm.VectorParams(size=dimension, distance=qm.Distance.COSINE))

    def upsert(self, payloads: list[dict]) -> None:
        vectors = self.models.embed([p["content"] for p in payloads])
        self.ensure_collection(len(vectors[0]))
        points = [qm.PointStruct(id=point_uuid(str(p.get("point_id") or p["chunk_id"])), vector=v.tolist(), payload=p) for p, v in zip(payloads, vectors)]
        self.qdrant.upsert(self.collection, points=points, wait=True)
        # Staged versions stay out of FTS entirely. This prevents a failed
        # version from crowding the currently published version out of Top-K.
        visible = [p for p in payloads if p.get("active") is not False]
        if visible:
            self.lexical.upsert(visible)

    def delete_document(self, document_id: int | str, version_id: int | str | None = None) -> None:
        conditions = [qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))]
        if version_id is not None:
            conditions.append(qm.FieldCondition(key="version_id", match=qm.MatchValue(value=version_id)))
        names = {c.name for c in self.qdrant.get_collections().collections}
        if self.collection in names:
            self.qdrant.delete(
                self.collection,
                points_selector=qm.FilterSelector(filter=qm.Filter(must=conditions)),
                wait=True,
            )
        self.lexical.delete_document(document_id, version_id)

    def activate_document_version(self, document_id: int | str, version_id: int | str) -> None:
        names = {c.name for c in self.qdrant.get_collections().collections}
        if self.collection in names:
            selector = qm.Filter(must=[
                qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id)),
                qm.FieldCondition(key="version_id", match=qm.MatchValue(value=version_id)),
            ])
            rows, offset = [], None
            while True:
                batch, offset = self.qdrant.scroll(self.collection, scroll_filter=selector, limit=256,
                                                    offset=offset, with_payload=True, with_vectors=False)
                rows.extend(dict(p.payload or {}) for p in batch)
                if offset is None:
                    break
            self.qdrant.set_payload(self.collection, payload={"active": True}, points=selector, wait=True)
            for payload in rows:
                payload["active"] = True
            if rows:
                self.lexical.upsert(rows)

    @staticmethod
    def _excluded_payload(payload: dict) -> bool:
        title = str(payload.get("title") or payload.get("source_title") or "")
        # This 1996 law was explicitly repealed when the current Noise
        # Pollution Prevention and Control Law took effect in 2022.
        return "中华人民共和国环境噪声污染防治法" in title

    @staticmethod
    def _expand_queries(query: str) -> list[str]:
        """Split multi-issue hotline tickets and add small, auditable domain expansions."""
        queries = [query.strip()]
        parts = re.split(r"[，,；;。！？!?]|同时|以及|并且|分别", query)

        expansions = (
            (("占道", "店外经营", "摆放桌椅"), "占用城市道路 广场等公共场所 违法经营 店外摆放桌椅 城市管理综合执法机关 行政处罚权"),
            (("噪声", "扰民", "喧哗"), "餐饮场所 噪声排放 商业噪声 食客喧哗 监督管理 行政处罚"),
            (("油烟", "烟道", "异味"), "餐饮场所 油烟排放 专用烟道 大气污染 生态环境 行政处罚"),
            (("电梯", "特种设备"), "住宅电梯 故障 隐患 特种设备安全 使用管理人 市场监督管理"),
            (("维修资金", "专项维修资金"), "住宅专项维修资金 申请列支 审核 备案 住房建设"),
            (("物业", "物业公司"), "物业服务企业 物业管理 监督管理 住房建设"),
            (("个人信息", "身份证", "手机号码"), "个人信息 泄露 身份证号码 手机号码 网络安全 删除 监管 处罚"),
            (("违停", "乱停放", "停车", "机动车"), "机动车停放 道路交通安全 公安机关交通管理部门 属地道路 交通秩序"),
            (("消防通道", "疏散通道", "消防车通道"), "占用 堵塞 封闭 消防车通道 消防救援 监督检查 行政处罚"),
            (("违法建设", "违建", "私搭", "加建", "搭建"), "违法建设 规划许可 查处 拆除 城市管理综合执法 镇街"),
            (("水质", "供水", "自来水", "停水", "水压"), "供水水质 城镇供水 水务部门 监督管理 供水企业"),
            (("路灯", "照明", "灯不亮"), "城市道路照明 路灯 产权 维护 管养单位 设施移交"),
            (("积水", "水浸", "内涝", "下穿隧道"), "道路积水 城市内涝 排水防涝 交通管制 应急处置 水务"),
            (("垃圾", "保洁", "清扫", "异味"), "物业服务 保洁义务 环境卫生 镇街监督 住房建设"),
            (("食品", "发霉", "食堂", "呕吐", "腹泻"), "食品安全 学校 幼儿园 市场监督管理 留样 供货凭证 应急处置"),
            (("学位", "入学", "招生", "公办小学", "适龄儿童"), "白云区教育局 义务教育 公办学校 招生计划 学位安排 教育公平 主管部门 职责"),
            (("噪声", "扰民", "喇叭", "施工机械"), "中华人民共和国噪声污染防治法 现行 商业经营 高音喇叭 建筑施工 职责 行政处罚"),
        )
        for needles, expansion in expansions:
            if any(n in query for n in needles):
                queries.append(expansion)

        # Free-text fragments are useful fallbacks, but domain expansions come
        # first so a small Top-K still covers each issue in a compound ticket.
        queries.extend(p.strip() for p in parts if len(p.strip()) >= 6)

        return list(dict.fromkeys(q for q in queries if q))[:8]

    def search(self, query: str, top_k: int, threshold: float = 0.0, category: str | None = None) -> list[dict]:
        candidate_k = max(int(self.cfg.get("candidate_k", 40)), top_k * 4)
        must = []
        if category:
            must.append(qm.FieldCondition(key="category", match=qm.MatchValue(value=category)))
        must_not = [qm.FieldCondition(key=key, match=qm.MatchValue(value=value))
                    for key, value in RETRIEVAL_EXCLUSIONS]
        query_filter = qm.Filter(
            must=must or None,
            must_not=must_not or None,
        )

        subqueries = self._expand_queries(query)
        vectors = self.models.embed(subqueries)
        combined: dict[str, dict] = {}
        per_query_ids: list[list[str]] = []
        for subquery, vector in zip(subqueries, vectors):
            dense = self.qdrant.query_points(
                self.collection, query=vector.tolist(), query_filter=query_filter,
                limit=candidate_k, with_payload=True
            ).points
            lexical = self.lexical.search(subquery, candidate_k)
            local_scores: dict[str, float] = {}
            for rank, item in enumerate(dense, 1):
                payload = dict(item.payload or {})
                if self._excluded_payload(payload):
                    continue
                cid = payload.get("chunk_id", str(item.id))
                row = combined.setdefault(cid, {"payload": payload, "rrf": 0.0, "dense": 0.0, "lexical": 0.0})
                row["rrf"] += 1 / (60 + rank)
                row["dense"] = max(row["dense"], float(item.score))
                local_scores[cid] = local_scores.get(cid, 0.0) + 1 / (60 + rank)
            for rank, (cid, score, payload) in enumerate(lexical, 1):
                if category and payload.get("category") != category:
                    continue
                if payload.get("document_header") is True:
                    continue
                if self._excluded_payload(payload):
                    continue
                row = combined.setdefault(cid, {"payload": payload, "rrf": 0.0, "dense": 0.0, "lexical": 0.0})
                row["rrf"] += 1 / (60 + rank)
                row["lexical"] = max(row["lexical"], score)
                local_scores[cid] = local_scores.get(cid, 0.0) + 1 / (60 + rank)
            per_query_ids.append([cid for cid, _ in sorted(local_scores.items(), key=lambda x: x[1], reverse=True)])

        globally_ranked = sorted(combined.values(), key=lambda x: x["rrf"], reverse=True)
        # Round-robin guarantees coverage of separate issues (for example
        # occupation, noise and cooking fumes) before filling by global score.
        selected_ids: list[str] = []
        for rank in range(2):
            for ids in per_query_ids:
                if rank < len(ids) and ids[rank] not in selected_ids:
                    selected_ids.append(ids[rank])
        selected_ids.extend(
            r["payload"].get("chunk_id") for r in globally_ranked
            if r["payload"].get("chunk_id") not in selected_ids
        )
        rows = [combined[cid] for cid in selected_ids if cid in combined][:candidate_k]
        reranker = self.models.reranker
        if reranker and rows:
            scores = reranker.predict([(query, r["payload"]["content"]) for r in rows], batch_size=2, show_progress_bar=False)
            for r, score in zip(rows, scores):
                raw = float(score)
                r["score"] = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, raw))))
            rows.sort(key=lambda x: x["score"], reverse=True)
        else:
            for r in rows:
                r["score"] = r["dense"]
        return [r for r in rows if r["score"] >= threshold][:top_k]

    def search_many(self, query: str, top_k: int, categories: list[str], threshold: float = 0.0) -> dict[str, list[dict]]:
        """Search independent category pools while sharing expansion, embedding and Qdrant transport."""
        categories = list(dict.fromkeys(category for category in categories if category))
        if not categories:
            return {}
        candidate_k = max(int(self.cfg.get("candidate_k", 40)), top_k * 4)
        subqueries = self._expand_queries(query)
        vectors = self.models.embed(subqueries)
        must_not = [qm.FieldCondition(key=key, match=qm.MatchValue(value=value))
                    for key, value in RETRIEVAL_EXCLUSIONS]

        requests = []
        for category in categories:
            query_filter = qm.Filter(
                must=[qm.FieldCondition(key="category", match=qm.MatchValue(value=category))],
                must_not=must_not or None,
            )
            requests.extend(
                qm.QueryRequest(query=vector.tolist(), filter=query_filter, limit=candidate_k, with_payload=True)
                for vector in vectors
            )
        responses = self.qdrant.query_batch_points(self.collection, requests=requests)

        # Existing lexical retrieval searches globally before applying the
        # category check, so one shared result per subquery is exactly equivalent.
        lexical_by_query = [self.lexical.search(subquery, candidate_k) for subquery in subqueries]
        output: dict[str, list[dict]] = {}
        response_index = 0
        for category in categories:
            combined: dict[str, dict] = {}
            per_query_ids: list[list[str]] = []
            for lexical in lexical_by_query:
                dense = responses[response_index].points
                response_index += 1
                local_scores: dict[str, float] = {}
                for rank, item in enumerate(dense, 1):
                    payload = dict(item.payload or {})
                    if self._excluded_payload(payload):
                        continue
                    cid = payload.get("chunk_id", str(item.id))
                    row = combined.setdefault(cid, {"payload": payload, "rrf": 0.0, "dense": 0.0, "lexical": 0.0})
                    row["rrf"] += 1 / (60 + rank)
                    row["dense"] = max(row["dense"], float(item.score))
                    local_scores[cid] = local_scores.get(cid, 0.0) + 1 / (60 + rank)
                for rank, (cid, score, payload) in enumerate(lexical, 1):
                    if payload.get("category") != category or payload.get("document_header") is True:
                        continue
                    if self._excluded_payload(payload):
                        continue
                    row = combined.setdefault(cid, {"payload": payload, "rrf": 0.0, "dense": 0.0, "lexical": 0.0})
                    row["rrf"] += 1 / (60 + rank)
                    row["lexical"] = max(row["lexical"], score)
                    local_scores[cid] = local_scores.get(cid, 0.0) + 1 / (60 + rank)
                per_query_ids.append([cid for cid, _ in sorted(local_scores.items(), key=lambda x: x[1], reverse=True)])

            globally_ranked = sorted(combined.values(), key=lambda x: x["rrf"], reverse=True)
            selected_ids: list[str] = []
            for rank in range(2):
                for ids in per_query_ids:
                    if rank < len(ids) and ids[rank] not in selected_ids:
                        selected_ids.append(ids[rank])
            selected_ids.extend(
                row["payload"].get("chunk_id") for row in globally_ranked
                if row["payload"].get("chunk_id") not in selected_ids
            )
            rows = [combined[cid] for cid in selected_ids if cid in combined][:candidate_k]
            reranker = self.models.reranker
            if reranker and rows:
                scores = reranker.predict([(query, row["payload"]["content"]) for row in rows], batch_size=2,
                                          show_progress_bar=False)
                for row, score in zip(rows, scores):
                    raw = float(score)
                    row["score"] = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, raw))))
                rows.sort(key=lambda row: row["score"], reverse=True)
            else:
                for row in rows:
                    row["score"] = row["dense"]
            output[category] = [row for row in rows if row["score"] >= threshold][:top_k]
        return output
