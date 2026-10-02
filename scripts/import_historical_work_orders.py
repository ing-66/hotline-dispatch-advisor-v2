"""Import historical 12345 work orders into MySQL work_orders (idempotent).

Default mode is a read-only dry-run that produces an analysis report without
touching MySQL or Qdrant. Use --apply to perform the actual import.

Usage:
    # dry-run (no writes)
    python scripts/import_historical_work_orders.py --out report.json

    # real import
    python scripts/import_historical_work_orders.py --apply --out report.json

Identity: no original ticket numbers exist in the source data, so each case
receives a deterministic source_case_id derived from request type + the
content hash embedded in the source file name: HC-<type>-<10hex>.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.historical_case_parser import parse_all_cases


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "assets" / "knowledge-source" / "03_历史工单案例"
HISTORICAL_SOURCE = "广州12345历史工单官方案例"


def normalize_dept_name(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip()


def map_department(raw: str | None, departments: dict[str, str]) -> str | None:
    """Exact + prefix-normalized matching to department rows; returns id or None.

    Rules (deliberately conservative to avoid cross-district false matches):
      1. normalized exact match;
      2. exact match after removing an optional leading 广州市 from the raw name;
      3. 白云区人民政府/白云区政府 - <镇街> suffix match against street rows
         registered as 广州市白云区人民政府-<镇街>.
    Nothing is guessed for other districts, companies, or 广州政务.
    """
    if not raw:
        return None
    normalized = normalize_dept_name(raw)
    if not normalized:
        return None
    if normalized in departments:
        return departments[normalized]
    if normalized.startswith("广州市"):
        short = normalized[3:]
        if short in departments:
            return departments[short]
    street = re.match(r"^(?:广州市)?白云区人民政府?[-—](.+)$", normalized)
    if street:
        full = f"广州市白云区人民政府-{street.group(1)}"
        if full in departments:
            return departments[full]
    return None


def build_report(parsed: list[Any], unparsed: list[Path], existing_ids: set[str],
                 departments: dict[str, str], apply: bool) -> dict[str, Any]:
    by_type = Counter(p.request_type for p in parsed)
    issues: Counter[str] = Counter()
    duplicate_source_ids: dict[str, int] = {}
    seen: dict[str, int] = {}
    for p in parsed:
        seen[p.source_case_id] = seen.get(p.source_case_id, 0) + 1
        for issue in p.issues:
            issues[issue] += 1
    duplicate_source_ids = {k: v for k, v in seen.items() if v > 1}

    dept_counter: Counter[str] = Counter(p.actual_department_raw for p in parsed if p.actual_department_raw)
    baoyun_departments = {
        d for d in dept_counter if "白云区" in d or "白云区人民政府" in d
    }
    mapped = sum(1 for p in parsed if map_department(p.actual_department_raw, departments))
    unmapped_raw = sorted({normalize_dept_name(p.actual_department_raw)
                           for p in parsed
                           if p.actual_department_raw
                           and map_department(p.actual_department_raw, departments) is None})
    event_times = [p.event_time for p in parsed if p.event_time]
    return {
        "mode": "apply" if apply else "dry-run",
        "source_dir": str(SOURCE_DIR),
        "parsed": len(parsed),
        "unparsed": [str(p) for p in unparsed],
        "by_request_type": dict(by_type),
        "issue_summary": dict(issues),
        "duplicate_source_case_ids": duplicate_source_ids,
        "existing_source_case_ids_in_mysql": len(existing_ids),
        "distinct_departments_raw": len(dept_counter),
        "top_departments_raw": dept_counter.most_common(50),
        "baoyun_related_raw_count": len(baoyun_departments),
        "department_master_size": len(departments),
        "cases_mapped_to_department": mapped,
        "cases_unmapped_raw_distinct": len(unmapped_raw),
        "unmapped_raw_sample": unmapped_raw[:200],
        "event_time_min": min(event_times).isoformat() if event_times else None,
        "event_time_max": max(event_times).isoformat() if event_times else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually write to MySQL")
    parser.add_argument("--source-dir", default=str(SOURCE_DIR))
    parser.add_argument("--out")
    args = parser.parse_args()

    parsed, unparsed = parse_all_cases(Path(args.source_dir))
    print(f"parsed={len(parsed)} unparsed={len(unparsed)}")

    from backend.db.session import SessionLocal
    from backend.domain.models import Department, WorkOrder

    db = SessionLocal()
    try:
        departments = {normalize_dept_name(d.name): d.id for d in db.query(Department).all()}
        existing_ids = {row[0] for row in db.query(WorkOrder.source_case_id).all() if row[0]}

        inserted = skipped = 0
        if args.apply:
            rows: list[WorkOrder] = []
            for item in parsed:
                if item.source_case_id in existing_ids:
                    skipped += 1
                    continue
                department_id = map_department(item.actual_department_raw, departments)
                rows.append(WorkOrder(
                    source_case_id=item.source_case_id,
                    title=item.title[:300],
                    content=item.content,
                    request_type=item.request_type,
                    source=HISTORICAL_SOURCE,
                    event_time=item.event_time.replace(tzinfo=None) if item.event_time else None,
                    actual_department_id=department_id,
                    status="completed",
                    metadata_json={
                        "source_file": item.file_path,
                        "source_seq": item.seq,
                        "source_type": "12345_official_cases",
                        "body_sha256": item.body_sha256,
                        "file_sha256": item.file_sha256,
                        "actual_department_raw": item.actual_department_raw,
                        "department_mapped": department_id is not None,
                    },
                ))
                existing_ids.add(item.source_case_id)
                if len(rows) >= 500:
                    db.add_all(rows)
                    db.commit()
                    inserted += len(rows)
                    rows = []
            if rows:
                db.add_all(rows)
                db.commit()
                inserted += len(rows)

        report = build_report(parsed, unparsed, existing_ids, departments, args.apply)
        report["inserted"] = inserted
        report["skipped_existing"] = skipped
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"report written: {out}")
        print(f"inserted={inserted} skipped_existing={skipped} (mode={'apply' if args.apply else 'dry-run'})")
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
