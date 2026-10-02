"""Parse historical 12345 case split files into structured records.

Source layout (V2 assets/knowledge-source/03_历史工单案例):
    <request_type>__拆分/<NNNNN>_<case title>__<10-hex>.md

Each file contains:
    # 广州12345历史工单｜<request_type>
    ## <case title>
    【诉求类型】...
    【留言时间】...
    【事项内容】...
    【实际承办单位】...

No original ticket number exists in the source data; a stable deterministic
source_case_id is derived from the request type and the content hash embedded
in the file name.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


FILE_PATTERN = re.compile(r"^(\d{5})_(.+)__([0-9a-f]{10})\.md$")
DATETIME_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")
FIELD_BLOCK = re.compile(r"【([^】]+)】\s*\n(.*?)(?=\n\s*【|\Z)", re.S)


@dataclass
class ParsedCase:
    file_path: str
    request_type: str
    seq: int
    title: str
    source_case_id: str
    content: str
    event_time: datetime | None
    actual_department_raw: str | None
    full_body: str
    file_sha256: str
    body_sha256: str
    issues: list[str] = field(default_factory=list)


def _field_map(body: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in FIELD_BLOCK.findall(body):
        clean_key = key.strip()
        lines = [line.strip() for line in value.strip().splitlines()]
        while lines and re.fullmatch(r"[-—–_]+", lines[-1]):
            lines.pop()
        clean_value = "\n".join(lines).strip()
        output[clean_key] = clean_value
    return output


def parse_case_file(path: Path) -> ParsedCase | None:
    match = FILE_PATTERN.match(path.name)
    if not match:
        return None
    request_type = path.parent.name.replace("__拆分", "")
    seq = int(match.group(1))
    title = match.group(2)
    name_hash = match.group(3)

    content = path.read_text(encoding="utf-8")
    marker = "\n## "
    index = content.find(marker)
    if index < 0:
        return None
    body = content[index + 1 :].strip()
    heading_end = body.find("\n")
    heading = body[len("## ") : heading_end].strip() if body.startswith("## ") else ""

    fields = _field_map(body)
    issues: list[str] = []

    request_type_field = fields.get("诉求类型", "").strip()
    if request_type_field and request_type_field != request_type:
        issues.append(f"request_type mismatch: folder={request_type} field={request_type_field}")

    event_time: datetime | None = None
    time_text = fields.get("留言时间", "").strip()
    time_match = DATETIME_PATTERN.search(time_text)
    if time_match:
        try:
            event_time = datetime.strptime(time_match.group(0), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                event_time = datetime.strptime(time_match.group(0), "%Y-%m-%d %H:%M")
            except ValueError:
                issues.append(f"unparsable message time: {time_text!r}")
    elif time_text:
        issues.append(f"missing/odd message time text: {time_text[:50]!r}")

    case_content = fields.get("事项内容", "").strip()
    if not case_content:
        issues.append("empty 事项内容")
    if len(case_content) > 50000:
        issues.append("事项内容 too long")

    department = fields.get("实际承办单位", "").strip() or None
    if not department:
        issues.append("missing 实际承办单位")

    if len(title) > 300:
        issues.append("title exceeds 300 chars")

    full_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if not full_sha256.startswith(name_hash):
        issues.append(f"file name hash mismatch: name={name_hash} sha256={full_sha256[:10]}")
    body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()

    return ParsedCase(
        file_path=str(path),
        request_type=request_type,
        seq=seq,
        title=heading or title,
        source_case_id=f"HC-{request_type}-{name_hash}",
        content=case_content,
        event_time=event_time,
        actual_department_raw=department,
        full_body=body,
        file_sha256=full_sha256,
        body_sha256=body_sha256,
        issues=issues,
    )


def parse_all_cases(source_dir: Path) -> tuple[list[ParsedCase], list[Path]]:
    parsed: list[ParsedCase] = []
    unparsed: list[Path] = []
    for path in sorted(source_dir.rglob("*.md")):
        item = parse_case_file(path)
        if item is None:
            unparsed.append(path)
        else:
            parsed.append(item)
    return parsed, unparsed
