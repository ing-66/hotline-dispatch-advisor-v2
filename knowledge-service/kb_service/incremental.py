"""MySQL-driven incremental knowledge index lifecycle.

MySQL is authoritative. Qdrant and FTS are derived targets. New-version rows are
staged with ``active=false`` and become visible only after every item succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
from dataclasses import dataclass
from typing import Protocol

import pymysql
from pymysql.cursors import DictCursor
from qdrant_client import models as qm

from .config import load_config
from .db.config import mysql_config
from .engine import Engine


class IndexTargets(Protocol):
    def upsert(self, payloads: list[dict]) -> None: ...
    def activate_document_version(self, document_id: int, version_id: int) -> None: ...
    def delete_document(self, document_id: int, version_id: int | None = None) -> None: ...
    def keys(self) -> tuple[set[str], set[str]]: ...


class EngineTargets:
    def __init__(self, cfg: dict):
        self.engine = Engine(cfg)

    def upsert(self, payloads: list[dict]) -> None:
        self.engine.upsert(payloads)

    def activate_document_version(self, document_id: int, version_id: int) -> None:
        self.engine.activate_document_version(document_id, version_id)

    def delete_document(self, document_id: int, version_id: int | None = None) -> None:
        self.engine.delete_document(document_id, version_id)

    def keys(self) -> tuple[set[str], set[str]]:
        lexical = self.engine.lexical.keys()
        vector: set[str] = set()
        names = {c.name for c in self.engine.qdrant.get_collections().collections}
        if self.engine.collection in names:
            offset = None
            while True:
                rows, offset = self.engine.qdrant.scroll(
                    self.engine.collection, limit=256, offset=offset, with_payload=True, with_vectors=False,
                    scroll_filter=qm.Filter(must_not=[
                        qm.FieldCondition(key="active", match=qm.MatchValue(value=False))
                    ]),
                )
                vector.update(str(p.payload.get("chunk_id")) for p in rows if p.payload)
                if offset is None:
                    break
        return vector, lexical


def _connect(raw: dict, database: str):
    cfg = mysql_config(raw, database)
    conn = pymysql.connect(host=cfg["host"], port=cfg["port"], user=cfg["user"],
                           password=cfg["password"], database=cfg["database"], charset="utf8mb4",
                           autocommit=False, cursorclass=DictCursor)
    with conn.cursor() as cur:
        cur.execute("SET time_zone='+00:00'")
    return conn


@dataclass
class MysqlIndexRepository:
    raw_config: dict
    database: str = "dev"
    batch_id: str | None = None

    def claim(self, owner: str) -> dict | None:
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                batch_sql = ("AND JSON_UNQUOTE(JSON_EXTRACT(scope,'$.batch_id'))=%s"
                             if self.batch_id else "AND JSON_EXTRACT(scope,'$.batch_id') IS NULL")
                values = (self.batch_id,) if self.batch_id else ()
                cur.execute(f"""SELECT * FROM kb_index_jobs
                    WHERE is_deleted=0 AND cancel_requested=0
                      AND (status='pending' OR (status='running' AND lease_until<UTC_TIMESTAMP(3)))
                      {batch_sql}
                    ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""", values)
                job = cur.fetchone()
                if not job:
                    conn.commit(); return None
                cur.execute("""UPDATE kb_index_jobs SET status='running',attempt_count=attempt_count+1,
                    lease_owner=%s,lease_until=DATE_ADD(UTC_TIMESTAMP(3),INTERVAL 5 MINUTE),
                    started_at=COALESCE(started_at,UTC_TIMESTAMP(3)),error_summary=NULL WHERE id=%s""",
                            (owner, job["id"]))
                conn.commit(); job["status"] = "running"; return job
        finally:
            conn.close()

    def items(self, job_id: int) -> list[dict]:
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT i.*,c.chunk_no,c.heading,c.content,c.sha256 chunk_sha,
                    d.title,d.original_rel_path,COALESCE(cat.name,'') category
                    FROM kb_index_job_items i
                    LEFT JOIN kb_chunks c ON c.id=i.chunk_id
                    LEFT JOIN kb_documents d ON d.id=i.document_id
                    LEFT JOIN kb_categories cat ON cat.id=d.category_id
                    WHERE i.job_id=%s AND i.is_deleted=0 AND i.status<>'succeeded' ORDER BY i.id""", (job_id,))
                return list(cur.fetchall())
        finally:
            conn.close()

    def canceled(self, job_id: int) -> bool:
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT cancel_requested FROM kb_index_jobs WHERE id=%s", (job_id,))
                row = cur.fetchone(); return not row or bool(row["cancel_requested"])
        finally:
            conn.close()

    def mark_item(self, item_id: int, status: str, error: str | None = None) -> None:
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                cur.execute("""UPDATE kb_index_job_items SET status=%s,retry_count=retry_count+%s,last_error=%s,
                    processed_at=IF(%s='succeeded',UTC_TIMESTAMP(3),processed_at) WHERE id=%s""",
                            (status, 1 if status == "failed" else 0, error, status, item_id))
            conn.commit()
        finally:
            conn.close()

    def mark_items(self, item_ids: list[int], status: str, error: str | None = None) -> None:
        if not item_ids:
            return
        conn = _connect(self.raw_config, self.database)
        try:
            placeholders = ",".join(["%s"] * len(item_ids))
            with conn.cursor() as cur:
                cur.execute(f"""UPDATE kb_index_job_items SET status=%s,retry_count=retry_count+%s,
                    last_error=%s,processed_at=IF(%s='succeeded',UTC_TIMESTAMP(3),processed_at)
                    WHERE id IN ({placeholders})""",
                            (status, 1 if status == "failed" else 0, error, status, *item_ids))
            conn.commit()
        finally:
            conn.close()

    def renew(self, job_id: int, owner: str) -> None:
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                cur.execute("""UPDATE kb_index_jobs SET lease_until=DATE_ADD(UTC_TIMESTAMP(3),INTERVAL 5 MINUTE)
                    WHERE id=%s AND status='running' AND lease_owner=%s""", (job_id, owner))
            conn.commit()
        finally:
            conn.close()

    def finish(self, job: dict) -> None:
        scope = job["scope"] if isinstance(job["scope"], dict) else json.loads(job["scope"] or "{}")
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                if job["job_type"] in ("index_document", "reindex_document", "repair"):
                    doc, ver = int(scope["document_id"]), int(scope["version_id"])
                    cur.execute("SELECT version_no,asset_id FROM kb_document_versions WHERE id=%s FOR UPDATE", (ver,))
                    version = cur.fetchone()
                    cur.execute("UPDATE kb_document_versions SET status='superseded' WHERE document_id=%s AND status='published' AND id<>%s", (doc, ver))
                    cur.execute("UPDATE kb_document_versions SET status='published',published_at=UTC_TIMESTAMP(3) WHERE id=%s", (ver,))
                    cur.execute("UPDATE kb_documents SET current_version_no=%s,asset_id=%s,status='published' WHERE id=%s AND is_deleted=0",
                                (version["version_no"], version["asset_id"], doc))
                elif job["job_type"] == "delete_document":
                    cur.execute("UPDATE kb_documents SET status='disabled' WHERE id=%s", (int(scope["document_id"]),))
                cur.execute("""UPDATE kb_index_jobs SET status='succeeded',processed_items=total_items,
                    failed_items=0,lease_owner=NULL,lease_until=NULL,finished_at=UTC_TIMESTAMP(3) WHERE id=%s""", (job["id"],))
                cur.execute("""INSERT INTO operation_logs(actor_user_id,actor_name,action,target_type,target_id,detail)
                    VALUES(NULL,'index-worker','kb.index.succeeded','kb_index_job',%s,%s)""",
                            (str(job["id"]), json.dumps({"job_type": job["job_type"]})))
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    def fail(self, job_id: int, error: str, canceled: bool = False) -> None:
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                cur.execute("""UPDATE kb_index_jobs SET status=%s,error_summary=%s,lease_owner=NULL,lease_until=NULL,
                    failed_items=(SELECT COUNT(*) FROM kb_index_job_items WHERE job_id=%s AND status='failed'),
                    finished_at=UTC_TIMESTAMP(3) WHERE id=%s""", ("canceled" if canceled else "failed", error[:4000], job_id, job_id))
            conn.commit()
        finally:
            conn.close()

    def expected_active_keys(self) -> set[str]:
        conn = _connect(self.raw_config, self.database)
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT c.id FROM kb_chunks c JOIN kb_document_versions v ON v.id=c.document_version_id
                    JOIN kb_documents d ON d.id=v.document_id
                    WHERE d.is_deleted=0 AND d.status='published' AND v.status='published'
                      AND d.current_version_no=v.version_no""")
                return {str(r["id"]) for r in cur.fetchall()}
        finally:
            conn.close()

    def enqueue_repairs(self, chunk_ids: set[str]) -> list[int]:
        if not chunk_ids:
            return []
        conn = _connect(self.raw_config, self.database)
        created = []
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(chunk_ids))
                cur.execute(f"""SELECT c.id chunk_id,c.chunk_no,c.document_version_id version_id,
                    v.document_id,v.version_no,v.sha256 FROM kb_chunks c
                    JOIN kb_document_versions v ON v.id=c.document_version_id
                    WHERE c.id IN ({placeholders}) ORDER BY v.id,c.chunk_no""", tuple(chunk_ids))
                groups: dict[tuple[int, int], list[dict]] = {}
                for row in cur.fetchall():
                    groups.setdefault((row["document_id"], row["version_id"]), []).append(row)
                for (doc, ver), rows in groups.items():
                    batch_key = self.batch_id or "default"
                    digest = hashlib.sha256((f"repair:{batch_key}:" + ":".join(str(r["chunk_id"]) for r in rows)).encode()).hexdigest()
                    scope_data = {"document_id": doc, "version_id": ver, "previous_version_id": ver}
                    if self.batch_id:
                        scope_data["batch_id"] = self.batch_id
                    scope = json.dumps(scope_data)
                    cur.execute("""INSERT INTO kb_index_jobs(idempotency_key,job_type,status,scope,trigger_source,total_items)
                        VALUES(%s,'repair','pending',%s,'system',%s)
                        ON DUPLICATE KEY UPDATE status=IF(status='succeeded','pending',status),cancel_requested=0,
                          error_summary=NULL,finished_at=NULL,id=LAST_INSERT_ID(id)""", (digest, scope, len(rows)))
                    job_id = cur.lastrowid
                    for row in rows:
                        cur.execute("""INSERT INTO kb_index_job_items(job_id,document_id,version_id,chunk_id,action,target_key)
                            VALUES(%s,%s,%s,%s,'upsert_vectors',%s)
                            ON DUPLICATE KEY UPDATE status='pending',last_error=NULL""",
                                    (job_id, doc, ver, row["chunk_id"], f"doc:{doc}:ver:{row['version_no']}:chunk:{row['chunk_no']}"))
                    created.append(job_id)
            conn.commit(); return created
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()


class Worker:
    def __init__(self, repo, targets: IndexTargets, owner: str | None = None, batch_size: int = 16):
        self.repo, self.targets = repo, targets
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}"
        self.batch_size = max(1, int(batch_size))

    @staticmethod
    def payload(item: dict) -> dict:
        cid = str(item["chunk_id"])
        return {"point_id": hashlib.sha256(f"kb:{cid}".encode()).hexdigest(), "chunk_id": cid,
                "document_id": int(item["document_id"]), "version_id": int(item["version_id"]),
                "ordinal": int(item.get("chunk_no") or 0), "title": item.get("title") or "",
                "section": item.get("heading") or "", "content": item.get("content") or "",
                "category": item.get("category") or "", "source_path": item.get("original_rel_path") or "",
                "sha256": item.get("chunk_sha") or "", "active": False, "metadata": {}}

    def run_once(self) -> dict | None:
        job = self.repo.claim(self.owner)
        if not job: return None
        scope = job["scope"] if isinstance(job["scope"], dict) else json.loads(job["scope"] or "{}")
        try:
            if job["job_type"] == "delete_document":
                self.targets.delete_document(int(scope["document_id"]))
            else:
                items = self.repo.items(job["id"])
                for start in range(0, len(items), self.batch_size):
                    batch = items[start:start + self.batch_size]
                    if self.repo.canceled(job["id"]):
                        self.repo.fail(job["id"], "cancel requested", canceled=True)
                        return {"id": job["id"], "status": "canceled"}
                    if hasattr(self.repo, "renew"):
                        self.repo.renew(job["id"], self.owner)
                    try:
                        self.targets.upsert([self.payload(item) for item in batch])
                        if hasattr(self.repo, "mark_items"):
                            self.repo.mark_items([item["id"] for item in batch], "succeeded")
                        else:
                            for item in batch: self.repo.mark_item(item["id"], "succeeded")
                    except Exception as exc:
                        if hasattr(self.repo, "mark_items"):
                            self.repo.mark_items([item["id"] for item in batch], "failed", repr(exc))
                        else:
                            for item in batch: self.repo.mark_item(item["id"], "failed", repr(exc))
                        raise
                doc, ver = int(scope["document_id"]), int(scope["version_id"])
                self.targets.activate_document_version(doc, ver)
                old = scope.get("previous_version_id")
                if old and int(old) != ver:
                    self.targets.delete_document(doc, int(old))
            self.repo.finish(job)
            return {"id": job["id"], "status": "succeeded"}
        except Exception as exc:
            self.repo.fail(job["id"], repr(exc))
            return {"id": job["id"], "status": "failed", "error": repr(exc)}

    def consistency(self) -> dict:
        expected = self.repo.expected_active_keys()
        vector, lexical = self.targets.keys()
        return {"expected": len(expected), "vector": len(vector), "fts": len(lexical),
                "missing_vector": sorted(expected-vector), "extra_vector": sorted(vector-expected),
                "missing_fts": sorted(expected-lexical), "extra_fts": sorted(lexical-expected)}

    def repair(self) -> dict:
        report = self.consistency()
        missing = set(report["missing_vector"]) | set(report["missing_fts"])
        report["repair_jobs"] = self.repo.enqueue_repairs(missing)
        return report

    def rebuild(self) -> dict:
        """Queue every currently published MySQL chunk; safe for an empty target."""
        expected = self.repo.expected_active_keys()
        return {"expected": len(expected), "rebuild_jobs": self.repo.enqueue_repairs(expected)}


def _run_all(worker: Worker, max_jobs: int | None = None) -> dict:
    """Run claimable jobs in-process until none remain (model loaded once).

    Semantics are identical to repeated `--once` invocations: each loop pass
    claims one job under the same lease rules and executes it through the real
    state machine. A failed job is left as 'failed' (never auto-retried here);
    the caller may reset it via the admin retry API and run again.
    """
    ran, ok, failed, canceled = 0, 0, [], 0
    while not max_jobs or ran < max_jobs:
        r = worker.run_once()
        if not r:
            break
        ran += 1
        if r["status"] == "succeeded":
            ok += 1
        elif r["status"] == "canceled":
            canceled += 1
        else:
            failed.append({"id": r.get("id"), "error": (r.get("error") or "")[:500]})
    return {"ran": ran, "succeeded": ok, "canceled": canceled,
            "failed_count": len(failed), "failed": failed[:20]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Incremental knowledge index worker")
    ap.add_argument("--db", choices=("dev", "test"), default="dev")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--run-all", action="store_true", help="keep claiming jobs until none are left (phase 7 bulk)")
    ap.add_argument("--max-jobs", type=int, default=None)
    ap.add_argument("--batch-id", default=None, help="claim only this migration batch; default claims non-batch UI jobs")
    args = ap.parse_args(); cfg = load_config()
    targets = EngineTargets(cfg)
    if os.environ.get("HOTLINE_INDEX_TEST_EMBEDDINGS") == "1":
        if args.db != "test" or cfg.get("qdrant_url"):
            raise SystemExit("test embeddings require --db test and a local isolated Qdrant path")
        import numpy as np
        class _DeterministicTestModels:
            reranker = None
            @staticmethod
            def embed(texts):
                rows = []
                for value in texts:
                    raw = hashlib.sha256(str(value).encode("utf-8")).digest()
                    vec = np.array([b - 127.5 for b in raw], dtype=float)
                    rows.append(vec / np.linalg.norm(vec))
                return np.array(rows)
        targets.engine.models = _DeterministicTestModels()
    repo = MysqlIndexRepository(cfg, args.db, args.batch_id)
    worker = Worker(repo, targets, batch_size=int(cfg.get("index_batch_size", 16)))
    result = (worker.rebuild() if args.rebuild else worker.repair() if args.repair
              else worker.consistency() if args.check else _run_all(worker, args.max_jobs) if args.run_all
              else worker.run_once())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
