"""Restore a Qdrant collection snapshot into a running Qdrant instance.

Usage:
    python scripts/restore_qdrant_snapshot.py ^
        --snapshot D:\...\hotline_dispatch_v2-....snapshot

Localhost traffic bypasses HTTP(S)_PROXY via trust_env=False.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, help="path to .snapshot file")
    parser.add_argument("--collection", default=os.environ.get("KS_COLLECTION", "hotline_dispatch_v2"))
    parser.add_argument("--base", default="http://127.0.0.1:6333")
    args = parser.parse_args()

    path = Path(args.snapshot)
    if not path.is_file():
        raise SystemExit(f"snapshot file not found: {path}")

    url = f"{args.base.rstrip('/')}/collections/{args.collection}/snapshots/upload"
    with httpx.Client(trust_env=False, timeout=600.0) as client:
        with open(path, "rb") as fh:
            response = client.post(
                url,
                params={"wait": "true", "priority": "snapshot"},
                files={"snapshot": (path.name, fh, "application/octet-stream")},
            )
    print(f"HTTP {response.status_code}")
    print(response.text[:2000])
    if response.status_code >= 400:
        raise SystemExit("snapshot restore failed")


if __name__ == "__main__":
    main()
