from __future__ import annotations

import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  chunk_id UNINDEXED, title, content, category, source_path UNINDEXED,
  tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS chunks(
  chunk_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL
);
"""


class LexicalStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def upsert(self, payloads: list[dict]) -> None:
        with self.db:
            for p in payloads:
                cid = p["chunk_id"]
                self.db.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (cid,))
                self.db.execute("INSERT OR REPLACE INTO chunks VALUES (?,?)", (cid, json.dumps(p, ensure_ascii=False)))
                self.db.execute("INSERT INTO chunks_fts(chunk_id,title,content,category,source_path) VALUES (?,?,?,?,?)",
                                (cid, p["title"], p["content"], p["category"], p["source_path"]))

    def delete_document(self, document_id: int | str, version_id: int | str | None = None) -> int:
        """Delete derived rows for a document/version; source data is untouched."""
        rows = self.db.execute("SELECT chunk_id,payload_json FROM chunks").fetchall()
        wanted = []
        for cid, raw in rows:
            payload = json.loads(raw)
            if str(payload.get("document_id")) != str(document_id):
                continue
            if version_id is not None and str(payload.get("version_id")) != str(version_id):
                continue
            wanted.append(cid)
        with self.db:
            for cid in wanted:
                self.db.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (cid,))
                self.db.execute("DELETE FROM chunks WHERE chunk_id=?", (cid,))
        return len(wanted)

    def keys(self) -> set[str]:
        return {str(row[0]) for row in self.db.execute("SELECT chunk_id FROM chunks")}

    def activate_document_version(self, document_id: int | str, version_id: int | str) -> int:
        rows = self.db.execute("SELECT chunk_id,payload_json FROM chunks").fetchall()
        changed = 0
        with self.db:
            for cid, raw in rows:
                payload = json.loads(raw)
                if (str(payload.get("document_id")) == str(document_id)
                        and str(payload.get("version_id")) == str(version_id)):
                    payload["active"] = True
                    self.db.execute("UPDATE chunks SET payload_json=? WHERE chunk_id=?",
                                    (json.dumps(payload, ensure_ascii=False), cid))
                    changed += 1
        return changed

    def search(self, query: str, limit: int) -> list[tuple[str, float, dict]]:
        cleaned = query.replace('"', ' ').strip()
        terms = [x for x in cleaned.split() if len(x) >= 3]
        if len(cleaned) >= 3:
            terms.extend(cleaned[i:i + 3] for i in range(0, len(cleaned) - 2, 2))
        terms = list(dict.fromkeys(terms))
        expression = " OR ".join(f'"{x}"' for x in terms) or '""'
        try:
            rows = self.db.execute(
                "SELECT f.chunk_id, bm25(chunks_fts, 0, 2, 1, 0, 0), c.payload_json "
                "FROM chunks_fts f JOIN chunks c ON c.chunk_id=f.chunk_id "
                "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?", (expression, limit)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        result = []
        for cid, score, payload in rows:
            decoded = json.loads(payload)
            if decoded.get("active") is False:
                continue
            result.append((cid, float(-score), decoded))
        return result
