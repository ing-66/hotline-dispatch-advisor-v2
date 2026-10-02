"""Register canonical department master rows from authoritative V2 knowledge assets.

The knowledge assets only contain Baiyun-district department/town data, so the
master is deliberately limited to entities provable from those assets. All other
case-level department strings remain unmapped (actual_department_id = NULL) and
are reported as anomalies. Nothing is guessed or generated from case data.

Default is a read-only dry-run. Use --apply to insert rows.

Usage:
    python scripts/import_department_master.py [--apply] [--out <json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from backend.db.session import SessionLocal
from backend.domain.models import Department


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_01 = PROJECT_ROOT / "assets" / "knowledge-source" / "01_机构职责"
ASSET_02 = PROJECT_ROOT / "assets" / "knowledge-source" / "02_权责清单"
SUFFIXES = ("__拆分", "_行政处罚", "_行政许可", "_行政强制", "_行政检查", "_行政确认", "_行政裁决", "_其他行政权力")
STREET_DIR = ASSET_01 / "白云区镇街机构职能和机构设置__拆分"


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip()


def clean_asset_name(name: str) -> str:
    if name.endswith("__拆分"):
        name = name[: -len("__拆分")]
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def collect_master() -> dict[str, dict[str, Any]]:
    """Return canonical name -> provenance metadata."""
    master: dict[str, dict[str, Any]] = {}

    for child in sorted(ASSET_02.iterdir()):
        stem = clean_asset_name(child.stem if child.suffix == ".md" else child.name)
        name = normalize(stem)
        if not name or name in ("疑似数据异常", "白云区政府部门职责明细"):
            continue
        if "白云区" not in name:
            continue
        master.setdefault(name, {"sources": []})["sources"].append(f"02:{child.name}")

    streets: set[str] = set()
    if STREET_DIR.is_dir():
        for path in sorted(STREET_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            match = re.match(r"^#\s+(.+)$", lines[0]) if lines else None
            if match:
                street = normalize(match.group(1))
                if street and len(street) <= 30:
                    streets.add(street)
    for street in sorted(streets):
        canonical = f"广州市白云区人民政府-{street}"
        master.setdefault(canonical, {"sources": []})["sources"].append("01:白云区镇街机构职能和机构设置")

    for entry in master.values():
        entry["sources"] = sorted(set(entry["sources"]))
    return master


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()

    master = collect_master()
    print(f"candidate canonical departments={len(master)}")

    db = SessionLocal()
    try:
        existing = {normalize(d.name): d.id for d in db.query(Department).all()}
        inserted = skipped = 0
        added: list[str] = []
        if args.apply:
            for name, meta in master.items():
                if name in existing:
                    skipped += 1
                    continue
                row = Department(
                    code="DEPT-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:16],
                    name=name,
                    active=True,
                    metadata_json={"master_sources": meta["sources"], "source_kind": "knowledge_assets"},
                )
                db.add(row)
                existing[name] = row.id
                added.append(name)
            db.commit()
            inserted = len(added)

        report: dict[str, Any] = {
            "mode": "apply" if args.apply else "dry-run",
            "candidate_count": len(master),
            "inserted": inserted,
            "skipped_existing": skipped,
            "names": [{"name": name, "sources": meta["sources"]} for name, meta in sorted(master.items())],
        }
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"report written: {out}")
        print(f"inserted={inserted} skipped={skipped} mode={'apply' if args.apply else 'dry-run'}")
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
