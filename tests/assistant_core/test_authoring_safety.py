"""Public request gate regressions from the 2026-09-21 implementation plan."""
from swd_authoring import Composer, EncodingDB, has_errors, validate_request
import pytest


def _validate(directives):
    return validate_request({"name": "safety", "chip": "py32f420", "directives": directives}, EncodingDB())


def test_negative_field_value_and_wait_are_blocked():
    _, issues = _validate([
        {"kind": "field_value", "peri": "RCC", "reg": "CFGR1", "field": "MCO2SEL", "value": -1},
        {"kind": "wait", "us": -1},
    ])
    assert has_errors(issues)
    assert len([x for x in issues if x.level == "error"]) == 2


def test_same_field_same_phase_conflict_is_blocked():
    _, issues = _validate([
        {"kind": "field_value", "peri": "RCC", "reg": "CFGR1", "field": "MCO2SEL", "value": 1},
        {"kind": "field_value", "peri": "RCC", "reg": "CFGR1", "field": "MCO2SEL", "value": 2},
    ])
    assert any("conflicting writes" in x.message for x in issues)


def test_raw_gpio_write_cannot_bypass_swd_pin_protection():
    _, issues = _validate([
        {"kind": "write_reg", "peri": "GPIOA", "reg": "MODER", "value": 0},
    ])
    assert any("protected SWD" in x.message for x in issues)


def test_read_only_field_write_is_blocked():
    _, issues = _validate([
        {"kind": "field_value", "peri": "RCC", "reg": "CR", "field": "HSIRDY", "value": 1},
    ])
    assert any("not writable" in x.message for x in issues)


def test_adc_ready_is_after_aden_and_keeps_a_nonzero_compare_mask():
    request, issues = _validate([
        {"kind": "enable_bit", "peri": "ADC", "instance": "ADC1", "reg": "CR", "field": "ADEN"},
        {"kind": "check_ready", "peri": "ADC", "instance": "ADC1", "reg": "ISR", "field": "ADRDY"},
    ])
    assert not has_errors(issues)
    rows = Composer(db=EncodingDB()).compile(request).rows
    assert [row.type for row in rows] == ["W", "C_H"]
    assert rows[-1].mask == rows[-1].data != 0


def test_unknown_attributes_instances_and_special_raw_registers_block():
    _, issues = _validate([
        {"kind": "clk_enable", "periph": "GPIOA", "typo": True},
        {"kind": "enable_bit", "peri": "ADC", "instance": "ADC9", "reg": "CR", "field": "ADEN"},
        {"kind": "write_reg", "peri": "RTC", "reg": "CRL", "value": 0x20},
    ])
    assert len([x for x in issues if x.level == "error"]) == 3


def test_direct_compile_never_returns_partial_success():
    from swd_authoring import ComposeRequest, Directive
    with pytest.raises(ValueError):
        Composer().compile(ComposeRequest(name='broken', directives=[
            Directive(kind='field_value', peri='RCC', reg='CFGR1', field='MCO2SEL', value=2),
            Directive(kind='not_a_real_operation')]))


@pytest.mark.parametrize('value', [-1, 2])
def test_enable_bit_uses_the_same_value_limits(value):
    _, issues = _validate([{'kind': 'enable_bit', 'peri': 'RCC', 'reg': 'CR', 'field': 'HSION', 'value': value}])
    assert has_errors(issues)


def test_symbol_and_literal_cannot_conflict_on_same_real_field():
    _, issues = _validate([
        {'kind': 'field_symbol', 'peri': 'RCC', 'reg': 'CFGR1', 'symbol': 'RCC_MCOSOURCE_HSI'},
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO1SEL', 'value': 3}])
    assert has_errors(issues)


@pytest.mark.parametrize('directive', [
    {'kind': 'field_symbol', 'peri': 'ADC', 'reg': 'CFGR1', 'symbol': 'RCC_MCOSOURCE_HSI'},
    {'kind': 'field_value', 'peri': 'ADC', 'instance': 'ADC9', 'reg': 'CFGR', 'field': 'RES', 'value': 1},
    {'kind': 'write_reg', 'peri': 'GPIO', 'reg': 'MODER', 'value': 0},
    {'kind': 'field_value', 'peri': 'GPIOA', 'reg': 'MODER', 'field': 'MODE13', 'value': 0},
    {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO1SEL', 'value': 2, 'phase': 99},
])
def test_resolved_addresses_and_phases_cannot_bypass_validation(directive):
    _, issues = _validate([directive])
    assert has_errors(issues)


def test_request_cannot_switch_the_knowledge_chip():
    _, issues = validate_request({'name': 'wrong', 'chip': 'unknown', 'directives': [
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}]}, EncodingDB())
    assert has_errors(issues)


def test_reviewed_access_evidence_is_address_and_field_specific():
    db = EncodingDB()
    assert db.reviewed_access(0x40024020, 16, 4) == 'RW'
    assert db.reviewed_access(0x40024420, 16, 4) == ''
    assert db.reviewed_access(0x40024020, 16, 8) == ''
