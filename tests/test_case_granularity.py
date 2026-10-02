"""Guard rails against over-conservative refusal and historical-case fact leakage."""

from __future__ import annotations

from backend.gateways.real_llm import SYSTEM_PROMPT
from backend.services.analysis_context import build_case_context


def test_prompt_forbids_inferring_street_from_history():
    assert "不得把 Evidence 中的具体镇街" in SYSTEM_PROMPT
    assert "棠景街" in SYSTEM_PROMPT
    assert "当前工单未写镇街时" in SYSTEM_PROMPT


def test_prompt_allows_generic_local_government_when_street_unknown():
    assert "属地街道办事处/属地镇人民政府" in SYSTEM_PROMPT
    assert "confidence 0.4~0.6" in SYSTEM_PROMPT


def test_prompt_keeps_insufficient_as_last_resort():
    assert "没有任何有效证据时，才允许" in SYSTEM_PROMPT


def test_context_defaults_to_baiyun_without_district():
    ctx = build_case_context("小区物业不清理垃圾")
    assert ctx["case_jurisdiction"] == "广州市白云区"
    assert ctx["outside_default_jurisdiction"] is False


def test_context_detects_explicit_baiyun_and_other_district():
    baiyun = build_case_context("白云区某小区电梯故障")
    assert baiyun["case_jurisdiction"] == "广州市白云区"
    assert baiyun["outside_default_jurisdiction"] is False

    tianhe = build_case_context("天河区某小区物业不清理垃圾")
    assert tianhe["outside_default_jurisdiction"] is True
    assert "非白云区" in tianhe["case_jurisdiction"]
