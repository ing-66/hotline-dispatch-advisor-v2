"""Compare two verify_knowledge_service.py snapshots (before/after migration).

Usage:
    python scripts/compare_knowledge_baselines.py ^
        --before D:\...\baseline_before.json ^
        --after  D:\...\baseline_after.json
"""

from __future__ import annotations

import argparse
import json


def category_pairs(payload: dict) -> dict[tuple[int, str, str], list[str]]:
    """Map (query_index, group, category) -> top chunk ids."""
    output: dict[tuple[int, str, str], list[str]] = {}
    for q_index, query_block in enumerate(payload.get("queries", [])):
        for group, categories in query_block.get("categories", {}).items():
            for category, result in categories.items():
                key = (q_index, group, category)
                output[key] = [str(item.get("chunk_id") or "") for item in result.get("top", [])]
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()

    with open(args.before, encoding="utf-8") as fh:
        before = json.load(fh)
    with open(args.after, encoding="utf-8") as fh:
        after = json.load(fh)

    before_map = category_pairs(before)
    after_map = category_pairs(after)
    keys = sorted(set(before_map) | set(after_map))

    top1_same = 0
    overlap_nonempty = 0
    missing = 0
    for key in keys:
        old_ids = before_map.get(key, [])
        new_ids = after_map.get(key, [])
        if not old_ids and not new_ids:
            missing += 1
            continue
        if old_ids and new_ids and old_ids[0] == new_ids[0]:
            top1_same += 1
        old_set = set(x for x in old_ids if x)
        new_set = set(x for x in new_ids if x)
        if old_set & new_set:
            overlap_nonempty += 1

    empty_diff = [key for key in keys if bool(before_map.get(key)) != bool(after_map.get(key))]
    print(f"total (query, group, category) pairs: {len(keys)}")
    print(f"pairs with same top-1 chunk: {top1_same}")
    print(f"pairs with at least one overlapping chunk: {overlap_nonempty}")
    print(f"pairs that changed between empty/non-empty: {len(empty_diff)}")
    if empty_diff:
        print("changed pairs:")
        for key in empty_diff:
            print(f"  q{key[0]} {key[1]} | {key[2]} | before={before_map.get(key)} after={after_map.get(key)}")
    if missing:
        print(f"pairs empty in both: {missing}")


if __name__ == "__main__":
    main()
