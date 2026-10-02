"""Read-only analysis: which historical-case departments can be mapped to
department names present in the authoritative V2 knowledge assets.

No MySQL/Qdrant writes. Outputs a JSON report for review.

Usage:
    python scripts/analyze_department_coverage.py [--out <json>]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.historical_case_parser import parse_all_cases


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_01 = PROJECT_ROOT / "assets" / "knowledge-source" / "01_机构职责"
ASSET_02 = PROJECT_ROOT / "assets" / "knowledge-source" / "02_权责清单"
HISTORICAL_DIR = PROJECT_ROOT / "assets" / "knowledge-source" / "03_历史工单案例"

SUFFIXES = ("__拆分", "_行政处罚", "_行政许可", "_行政强制", "_行政检查", "_行政确认", "_行政裁决", "_其他行政权力")


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip()


def asset_master_names() -> set[str]:
    names: set[str] = set()
    for child in ASSET_02.iterdir():
        name = child.name
        if child.suffix == ".md":
            name = child.stem
        for suffix in SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        names.add(normalize(name))

    # Street/town names from 01 street split files' first heading.
    street_dir = ASSET_01 / "白云区镇街机构职能和机构设置__拆分"
    if street_dir.is_dir():
        for path in sorted(street_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            match = re.match(r"^#\s+(.+)$", text)
            if match and len(match.group(1).strip()) <= 30:
                names.add(normalize(match.group(1)))
    # District-level bureaus under 白云区政府部门职责明细.md
    duties = ASSET_01 / "白云区政府部门职责明细.md"
    if duties.is_file():
        for line in duties.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                name = line[3:].strip()
                if len(name) <= 30:
                    names.add(normalize(name))
    return {n for n in names if n and n not in ("机构职责", "机构设置", "白云区政府部门职责明细")}


def match_raw(raw: str, names: set[str]) -> str | None:
    normalized = normalize(raw)
    if not normalized:
        return None
    if normalized in names:
        return normalized
    for name in names:
        if name in normalized or normalized in name:
            return name
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()

    parsed, _ = parse_all_cases(HISTORICAL_DIR)
    names = asset_master_names()
    counter: Counter[str] = Counter(p.actual_department_raw for p in parsed if p.actual_department_raw)
    matched: Counter[str] = Counter()
    unmatched: Counter[str] = Counter()
    matched_cases = 0
    for raw, count in counter.items():
        target = match_raw(raw, names)
        if target:
            matched[target] += count
            matched_cases += count
        else:
            unmatched[raw] = count

    baoyun = sum(count for raw, count in counter.items() if "白云区" in raw)
    report: dict[str, Any] = {
        "total_cases_with_department": sum(counter.values()),
        "cases_matched": matched_cases,
        "cases_unmatched": sum(counter.values()) - matched_cases,
        "cases_with_baoyun_text": baoyun,
        "master_names_count": len(names),
        "master_names": sorted(names),
        "matched_by_master": dict(matched),
        "unmatched_distinct": len(unmatched),
        "unmatched_top": unmatched.most_common(100),
    }
    print(f"master names={len(names)}")
    print(f"cases with department={sum(counter.values())} matched={matched_cases} unmatched={sum(counter.values()) - matched_cases}")
    print("master sample:", sorted(names)[:60])
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report written: {out}")


if __name__ == "__main__":
    main()
