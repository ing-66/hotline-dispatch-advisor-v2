from __future__ import annotations

from typing import Any

import httpx

from backend.gateways.contracts import KnowledgeGateway, RetrievalResult


class KnowledgeGatewayError(RuntimeError):
    """An explicit, user-safe knowledge retrieval failure."""


class KnowledgeConnectionError(KnowledgeGatewayError): pass
class KnowledgeTimeoutError(KnowledgeGatewayError): pass
class KnowledgeAuthenticationError(KnowledgeGatewayError): pass
class KnowledgeCollectionError(KnowledgeGatewayError): pass
class KnowledgeResponseError(KnowledgeGatewayError): pass


KNOWLEDGE_CATEGORIES = {
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

SOURCE_TYPES = {
    "department_duties": "department_duty",
    "responsibilities": "authority_list",
    "historical_cases": "historical_case",
    "regulations": "policy",
}


class QdrantKnowledgeAdapter(KnowledgeGateway):
    """Calls the external Knowledge API that owns Qdrant and embeddings."""

    def __init__(self, url: str, api_key: str, collection: str, timeout: float = 30.0,
                 client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.collection = collection
        self.timeout = timeout
        self._client = client

    def health(self) -> dict[str, Any]:
        try:
            response = self._request("GET", "/health")
            payload = self._json_object(response)
            if payload.get("collection") != self.collection:
                raise KnowledgeCollectionError(
                    f"Knowledge API collection mismatch: expected {self.collection!r}, got {payload.get('collection')!r}"
                )
            if not isinstance(payload.get("qdrant"), dict) or not payload["qdrant"].get("ok"):
                raise KnowledgeConnectionError("Knowledge API reports Qdrant unavailable")
            return payload
        except KnowledgeGatewayError:
            raise

    def search(self, query: str, knowledge_base_ids: list[str], top_k: int = 12,
               filters: dict[str, Any] | None = None) -> list[RetrievalResult]:
        if not query.strip():
            return []
        requested = knowledge_base_ids or list(KNOWLEDGE_CATEGORIES)
        unknown = set(requested) - KNOWLEDGE_CATEGORIES.keys()
        if unknown:
            raise KnowledgeResponseError(f"Unknown knowledge base IDs: {sorted(unknown)}")
        requests: list[tuple[str, str, dict[str, Any]]] = []
        for knowledge_base_id in requested:
            for category in KNOWLEDGE_CATEGORIES[knowledge_base_id]:
                body = {
                    "knowledge_id": self.collection,
                    "query": query,
                    "retrieval_setting": {"top_k": top_k, "score_threshold": (filters or {}).get("score_threshold", 0.0)},
                    "metadata_condition": {"category": category},
                }
                requests.append((knowledge_base_id, category, body))

        def retrieve(spec: tuple[str, str, dict[str, Any]]) -> list[RetrievalResult]:
            knowledge_base_id, category, body = spec
            response = self._request("POST", "/retrieval", json=body)
            payload = self._json_object(response)
            records = payload.get("records")
            if not isinstance(records, list):
                raise KnowledgeResponseError("Knowledge API response field 'records' is not a list")
            parsed_results: list[RetrievalResult] = []
            for position, record in enumerate(records):
                parsed = self._parse_record(record, knowledge_base_id, category, position)
                if parsed is not None:
                    parsed_results.append(parsed)
            return parsed_results

        if len(requests) == 1:
            batches = [retrieve(requests[0])]
        else:
            response = self._request("POST", "/retrieval/batch", json={
                "knowledge_id": self.collection,
                "query": query,
                "categories": [category for _, category, _ in requests],
                "retrieval_setting": {
                    "top_k": top_k,
                    "score_threshold": (filters or {}).get("score_threshold", 0.0),
                },
            })
            payload = self._json_object(response)
            grouped = payload.get("records_by_category")
            if not isinstance(grouped, dict):
                raise KnowledgeResponseError("Knowledge API batch response is malformed")
            batches = []
            for knowledge_base_id, category, _ in requests:
                records = grouped.get(category)
                if not isinstance(records, list):
                    raise KnowledgeResponseError(f"Knowledge API batch category is malformed: {category}")
                parsed_results = []
                for position, record in enumerate(records):
                    parsed = self._parse_record(record, knowledge_base_id, category, position)
                    if parsed is not None:
                        parsed_results.append(parsed)
                batches.append(parsed_results)
        results = [item for batch in batches for item in batch]
        deduplicated: dict[str, RetrievalResult] = {}
        for item in sorted(results, key=lambda item: item.score, reverse=True):
            deduplicated.setdefault(item.evidence_id, item)

        unique = list(deduplicated.values())
        if len(unique) <= top_k:
            return unique

        # Balance Evidence Pack coverage across the requested knowledge groups.
        # Pure score ordering lets high-similarity historical cases crowd out
        # department duties / regulations that the model needs for judgment.
        buckets: dict[str, list[RetrievalResult]] = {}
        for item in unique:
            buckets.setdefault(item.knowledge_base_id, []).append(item)

        group_order = [knowledge_base_id for knowledge_base_id in requested if knowledge_base_id in buckets]
        selected: list[RetrievalResult] = []
        selected_ids: set[str] = set()
        cursor: dict[str, int] = {group: 0 for group in group_order}

        if len(group_order) > 0:
            # Keep broad evidence coverage without letting irrelevant groups
            # consume half of the final pack. Remaining slots are score-driven.
            base_per_group = 1
            for group in group_order:
                for _ in range(base_per_group):
                    items = buckets[group]
                    while cursor[group] < len(items) and items[cursor[group]].evidence_id in selected_ids:
                        cursor[group] += 1
                    if cursor[group] >= len(items):
                        break
                    item = items[cursor[group]]
                    selected.append(item)
                    selected_ids.add(item.evidence_id)
                    cursor[group] += 1

        # Fill remaining capacity with the globally highest scores.
        for item in unique:
            if len(selected) >= top_k:
                break
            if item.evidence_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item.evidence_id)
        return selected[:top_k]

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        client = self._client or httpx.Client(timeout=self.timeout)
        close = self._client is None
        try:
            response = client.request(method, f"{self.url}{path}", headers=headers, **kwargs)
            if response.status_code in (401, 403):
                raise KnowledgeAuthenticationError("Knowledge API authentication failed")
            if response.status_code == 404:
                raise KnowledgeCollectionError("Knowledge API endpoint or collection does not exist")
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise KnowledgeTimeoutError("Knowledge API request timed out") from exc
        except httpx.HTTPError as exc:
            raise KnowledgeConnectionError("Knowledge API request failed") from exc
        finally:
            if close: client.close()

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try: payload = response.json()
        except ValueError as exc: raise KnowledgeResponseError("Knowledge API returned invalid JSON") from exc
        if not isinstance(payload, dict): raise KnowledgeResponseError("Knowledge API returned a non-object response")
        return payload

    @staticmethod
    def _parse_record(record: Any, knowledge_base_id: str, category: str, position: int) -> RetrievalResult | None:
        if not isinstance(record, dict): return None
        content = record.get("content")
        if not isinstance(content, str) or not content.strip(): return None
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        chunk_id = str(metadata.get("chunk_id") or metadata.get("point_id") or f"result-{position}")
        source_type = SOURCE_TYPES.get(knowledge_base_id, "other")
        case_id = metadata.get("source_case_id") or metadata.get("case_id") or metadata.get("source_record_id")
        normalized_metadata = {**metadata, "source_type": source_type, "source_id": case_id or metadata.get("document_id") or chunk_id}
        if case_id is not None: normalized_metadata["case_id"] = str(case_id)
        if metadata.get("work_order_id") is not None:
            normalized_metadata["work_order_id"] = str(metadata["work_order_id"])
        try: score = float(record.get("score", 0.0))
        except (TypeError, ValueError): score = 0.0
        return RetrievalResult(
            evidence_id=f"{knowledge_base_id}:{chunk_id}", knowledge_base_id=knowledge_base_id,
            external_id=str(case_id) if case_id is not None else chunk_id,
            document_id=str(metadata["document_id"]) if metadata.get("document_id") is not None else None,
            document_title=str(metadata.get("source_title") or record.get("title") or category),
            point_id=chunk_id, content=content, score=score, metadata=normalized_metadata,
        )
