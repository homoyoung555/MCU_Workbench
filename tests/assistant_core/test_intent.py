"""Intent layer — JSON⇄Directive loader + LLM-output validation.

Schema-tier tests need no KB; semantic-tier and few-shot tests need the built
products and skip when absent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from swd_authoring import (
    Composer,
    has_errors,
    request_from_json,
    validate,
    validate_request,
)
from swd_authoring.intent import (
    Issue,
    directive_from_dict,
    directive_to_dict,
)
from swd_authoring.encoding import CACHE_ROOT

CHIP = "py32f420"
KB_READY = (CACHE_ROOT / CHIP / "fieldmap.json").exists()
FEWSHOT = (Path(__file__).resolve().parents[2] / "swd_authoring"
           / "schema" / "fewshot.json")


def _errors(issues):
    return [x for x in issues if x.level == "error"]


# ---- schema tier (no KB) -----------------------------------------------------

def test_value_coercion():
    assert directive_from_dict({"kind": "field_value", "value": "0b0010"}).value == 2
    assert directive_from_dict({"kind": "field_value", "value": "0x10"}).value == 16
    assert directive_from_dict({"kind": "field_value", "value": "2"}).value == 2
    assert directive_from_dict({"kind": "field_value", "value": 2}).value == 2


def test_missing_required_field():
    issues = validate([directive_from_dict({"kind": "field_value",
                                            "peri": "RCC", "reg": "CFGR1",
                                            "field": "MCO2SEL"})])
    assert any(x.level == "error" and "field_value requires" in x.message
               for x in issues)


def test_unknown_kind():
    issues = validate([directive_from_dict({"kind": "teleport"})])
    assert any(x.level == "error" and "unknown kind" in x.message for x in issues)


def test_missing_kind_raises():
    with pytest.raises(ValueError):
        directive_from_dict({"peri": "RCC"})


def test_roundtrip_to_dict():
    src = {"kind": "field_value", "peri": "RCC", "reg": "CFGR1",
           "field": "MCO2SEL", "value": 2}
    d = directive_from_dict(src)
    back = directive_to_dict(d)
    assert back == src


def test_pin_config_defaults_omitted_in_roundtrip():
    d = directive_from_dict({"kind": "pin_config", "pin": "PA4", "func": "MCO2"})
    back = directive_to_dict(d)
    assert back == {"kind": "pin_config", "pin": "PA4", "func": "MCO2"}


def test_malformed_envelope():
    req, issues = validate_request([1, 2, 3])   # not an object
    assert req is None and has_errors(issues)


# ---- semantic tier (needs KB) ------------------------------------------------

@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_fewshot_all_valid_and_compile():
    fs = json.loads(FEWSHOT.read_text(encoding="utf-8"))
    comp = Composer(CHIP)
    for ex in fs["examples"]:
        req, issues = validate_request(ex["request"])
        if _errors(issues):
            name = ex["request"]["name"]
            assert name in {"OPA_FOLLOWER_OPA1", "RTC_1HZ_LSE"}
            if name == "OPA_FOLLOWER_OPA1":
                assert all("UNKNOWN" in issue.message for issue in _errors(issues))
            else:
                assert all("raw RTC.CRL access" in issue.message for issue in _errors(issues))
            continue
        res = comp.compile(req)
        assert res.rows, f"{ex['request']['name']} produced no rows"


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_bad_symbol_caught():
    _, issues = validate_request({"name": "x", "directives": [
        {"kind": "field_symbol", "symbol": "NOT_A_REAL_SYMBOL"}]})
    assert any(x.level == "error" and "not found in L1" in x.message
               for x in issues)


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_bad_field_caught():
    _, issues = validate_request({"name": "x", "directives": [
        {"kind": "enable_bit", "peri": "RCC", "reg": "CR", "field": "NOPE_BIT"}]})
    assert has_errors(issues)


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_value_exceeds_width():
    _, issues = validate_request({"name": "x", "directives": [
        {"kind": "field_value", "peri": "RCC", "reg": "CFGR1",
         "field": "MCO2SEL", "value": 99}]})
    assert any(x.level == "error" and "exceeds" in x.message for x in issues)


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_legal_documented_value_no_error():
    # MCO2SEL = 0b0010 (HSI) is in-width and documented -> clean
    _, issues = validate_request({"name": "x", "directives": [
        {"kind": "field_value", "peri": "RCC", "reg": "CFGR1",
         "field": "MCO2SEL", "value": "0b0010"}]})
    assert not has_errors(issues)


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_pin_no_af_caught():
    _, issues = validate_request({"name": "x", "directives": [
        {"kind": "pin_config", "pin": "PA4", "func": "TOTALLY_BOGUS"}]})
    assert has_errors(issues)


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_unknown_field_blocks_request():
    req, issues = validate_request({"name": "x", "directives": [
        {"kind": "clk_enable", "periph": "GPIOA", "voltage": 3.3}]})
    assert has_errors(issues)
    assert any(x.level == "error" and "unknown fields" in x.message
               for x in issues)


# ---- routing-completeness lint (data-driven companion-write check) -----------

def _completeness(issues):
    return [x for x in issues if x.code == "completeness"]


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_routing_without_companion_enable_warns():
    # 外接路由 VOUT1_EXT 但没配输出使能(DAC_EXTEN)→ 完整性警告,非 error
    _, issues = validate_request({"name": "x", "chip": CHIP, "directives": [
        {"kind": "clk_enable", "periph": "DAC"},
        {"kind": "field_symbol", "peri": "DAC", "reg": "OC",
         "symbol": "DAC_OUTPUTSELECT_VOUT1_EXT"},
        {"kind": "field_value", "peri": "DAC", "reg": "DHR12R1",
         "field": "DACC1DHR", "value": "0x800"}]})
    assert not has_errors(issues)
    comp = _completeness(issues)
    assert any("DAC_EXTEN" in x.message for x in comp), comp


@pytest.mark.skipif(not KB_READY, reason="KB not built")
@pytest.mark.parametrize("enable_sym", [
    "DAC_OUTPUT_ENABLE_BUFFER_DISABLE",   # agent 选不经 buffer
    "DAC_OUTPUT_ENABLE_BUFFER_ENABLE",    # agent 选经 buffer —— 两者都落 DAC_EXTEN
])
def test_routing_with_companion_enable_clean(enable_sym):
    # 配了使能字段(无论 buffer 开关)→ 不再报完整性警告:lint 只判字段被碰
    _, issues = validate_request({"name": "x", "chip": CHIP, "directives": [
        {"kind": "clk_enable", "periph": "DAC"},
        {"kind": "field_symbol", "peri": "DAC", "reg": "OC",
         "symbol": "DAC_OUTPUTSELECT_VOUT1_EXT"},
        {"kind": "field_symbol", "peri": "DAC", "reg": "OC", "symbol": enable_sym},
        {"kind": "field_value", "peri": "DAC", "reg": "DHR12R1",
         "field": "DACC1DHR", "value": "0x800"}]})
    assert not _completeness(issues)


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_companion_check_is_convention_derived_not_curated():
    # 关键:逐符号声明为空,DAC 漏 EXTEN 仍被逮住 —— 靠家族命名约定,零逐符号策展。
    # 换同族新芯片照抄 companion_conventions 即可,不必逐符号写 symbol_implies_*。
    from swd_authoring import EncodingDB
    db = EncodingDB(CHIP)
    assert db.companion_writes("DAC_OUTPUTSELECT_VOUT1_EXT") == []   # 无逐符号策展
    assert db.companion_conventions()                               # 有家族约定
    _, issues = validate_request({"name": "x", "chip": CHIP, "directives": [
        {"kind": "clk_enable", "periph": "DAC"},
        {"kind": "field_symbol", "peri": "DAC", "reg": "OC",
         "symbol": "DAC_OUTPUTSELECT_VOUT1_EXT"},
        {"kind": "field_value", "peri": "DAC", "reg": "DHR12R1",
         "field": "DACC1DHR", "value": "0x800"}]}, db)
    assert any(x.code == "completeness" and "DAC_EXTEN" in x.message for x in issues)


@pytest.mark.skipif(not KB_READY, reason="KB not built")
def test_no_routing_no_false_positive():
    # 普通 DAC 内部输出(无外接路由)→ 不触发 routing 完整性警告
    _, issues = validate_request({"name": "x", "chip": CHIP, "directives": [
        {"kind": "clk_enable", "periph": "DAC"},
        {"kind": "enable_bit", "peri": "DAC", "reg": "CR", "field": "EN1"},
        {"kind": "field_value", "peri": "DAC", "reg": "DHR12R1",
         "field": "DACC1DHR", "value": "0x800"}]})
    assert not any("外接路由" in x.message for x in issues)
