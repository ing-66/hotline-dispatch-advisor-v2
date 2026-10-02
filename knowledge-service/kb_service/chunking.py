from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import yaml


LEGAL_CATEGORIES = {"04_国家法律法规", "05_广州地方性法规", "06_广州政府规章", "07_广州行政规范性文件"}
ARTICLE_RE = re.compile(r"(?m)^(第[零〇一二三四五六七八九十百千万两0-9]+条(?:\s|　)*)")
HEADING_RE = re.compile(r"(?m)^(#{1,6}\s+.+|[一二三四五六七八九十]+、.+|（[一二三四五六七八九十]+）.+)$")


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    category: str
    title: str
    source_path: str
    sha256: str
    ordinal: int
    start: int
    end: int
    section: str
    content: str
    metadata: dict

    def payload(self) -> dict:
        item = asdict(self)
        item.pop("content")
        item["content"] = self.content
        return item


def _frontmatter(text: str) -> tuple[dict, int]:
    if not text.startswith("---"):
        return {}, 0
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, 0
    try:
        data = yaml.safe_load(m.group(1)) or {}
        return (data if isinstance(data, dict) else {}), m.end()
    except yaml.YAMLError:
        return {}, 0


def _boundaries(body: str, category: str) -> list[int]:
    pattern = ARTICLE_RE if category in LEGAL_CATEGORIES else HEADING_RE
    points = [m.start() for m in pattern.finditer(body)]
    return sorted(set([0, *points, len(body)]))


def _split_long(text: str, absolute_start: int, target: int = 900, overlap: int = 120):
    cursor = 0
    while cursor < len(text):
        hard_end = min(len(text), cursor + target)
        end = hard_end
        if hard_end < len(text):
            floor = max(cursor + target // 2, cursor)
            candidates = [text.rfind(x, floor, hard_end) for x in ("\n\n", "。", "；", "\n")]
            end = max(candidates)
            if end < floor:
                end = hard_end
            else:
                end += 1
        yield absolute_start + cursor, absolute_start + end, text[cursor:end]
        if end >= len(text):
            break
        cursor = max(cursor + 1, end - overlap)


def chunk_file(path: Path, source_root: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8-sig")
    meta, body_start = _frontmatter(raw)
    body = raw[body_start:]
    rel = path.relative_to(source_root).as_posix()
    category = rel.split("/", 1)[0]
    first_line = next((x.strip().lstrip("#").strip() for x in body.splitlines() if x.strip()), "")
    title = str(meta.get("title") or meta.get("标题") or first_line or path.stem)
    for key, value in re.findall(r"(?m)^\*\*([^*：:]+)\*\*\s*[：:]\s*(.*?)\s*$", body):
        if value:
            meta.setdefault(key.strip(), value.strip())
    for key, value in re.findall(r"(?m)^【([^】]+)】\s*\n([^\n]+)", body):
        if value.strip() and len(value.strip()) <= 300:
            meta.setdefault(key.strip(), value.strip())
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    document_id = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:32]
    points = _boundaries(body, category)
    chunks: list[Chunk] = []
    ordinal = 0
    for left, right in zip(points, points[1:]):
        section_text = body[left:right].strip()
        if not section_text:
            continue
        section = section_text.splitlines()[0][:160]
        prefix = f"文件：{title}\n类别：{category}\n章节：{section}\n"
        for start, end, piece in _split_long(section_text, body_start + left):
            content = prefix + piece.strip()
            chunk_id = hashlib.sha256(f"{rel}:{start}:{end}:{sha}".encode("utf-8")).hexdigest()
            chunks.append(Chunk(chunk_id, document_id, category, title, rel, sha, ordinal,
                                start, end, section, content, meta))
            ordinal += 1
    return chunks
