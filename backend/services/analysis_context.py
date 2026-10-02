"""Business context used by AI analysis.

case_jurisdiction and knowledge_scope are intentionally different:
- case_jurisdiction: where this ticket is being handled (default: Baiyun).
- knowledge_scope: legal/institutional hierarchy that may legitimately apply
  to a Baiyun matter (national / Guangdong / Guangzhou / Baiyun).
"""

from __future__ import annotations

import re
from typing import Any


GUANGZHOU_DISTRICTS = {
    "白云区": "广州市白云区",
    "越秀区": "广州市越秀区",
    "海珠区": "广州市海珠区",
    "荔湾区": "广州市荔湾区",
    "天河区": "广州市天河区",
    "黄埔区": "广州市黄埔区",
    "花都区": "广州市花都区",
    "番禺区": "广州市番禺区",
    "南沙区": "广州市南沙区",
    "从化区": "广州市从化区",
    "增城区": "广州市增城区",
}

EXTERNAL_AREA_KEYWORDS = (
    "深圳市", "佛山市", "东莞市", "中山市", "珠海市", "惠州市", "江门市", "肇庆市",
    "广东省", "越秀区", "海珠区", "荔湾区", "天河区", "黄埔区", "花都区", "番禺区",
    "南沙区", "从化区", "增城区",
)


def build_case_context(content: str) -> dict[str, Any]:
    """Infer explicit jurisdiction from the ticket or fall back to default.

    Does not alter the original ticket text. Returns only analysis context.
    """
    text = re.sub(r"\s+", "", content or "")
    explicit_district: str | None = None
    for district, full in GUANGZHOU_DISTRICTS.items():
        if district in text:
            explicit_district = district
            break

    outside_default = False
    if explicit_district is not None and explicit_district != "白云区":
        outside_default = True
    elif explicit_district is None:
        for keyword in EXTERNAL_AREA_KEYWORDS:
            if keyword in text:
                outside_default = True
                break

    return {
        "case_jurisdiction": "广州市白云区" if not outside_default else "非白云区（需核实转派范围）",
        "case_default_city": "广州市",
        "case_default_district": "白云区",
        "system_default_jurisdiction": "广州市白云区",
        "explicit_district": explicit_district,
        "outside_default_jurisdiction": outside_default,
    }
