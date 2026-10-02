"""Knowledge API retrieval policy: document-header points never enter Evidence Packs."""

from __future__ import annotations

import sys
from pathlib import Path


KNOWLEDGE_SERVICE = Path(__file__).resolve().parents[1] / "knowledge-service"
if str(KNOWLEDGE_SERVICE) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_SERVICE))

from kb_service.filter_policy import RETRIEVAL_EXCLUSIONS  # noqa: E402


def test_document_header_is_excluded():
    assert ("document_header", True) in RETRIEVAL_EXCLUSIONS


def test_inactive_points_remain_excluded():
    assert ("active", False) in RETRIEVAL_EXCLUSIONS
