import pytest

from gui.assistant_swd import CandidateError, prepare_candidate
from swd_authoring import Composer, ComposeRequest, Directive, EncodingDB


AFRL = 0x40024020
SUPPLEMENT = {
    'address': AFRL, 'peripheral': 'GPIOA', 'register': 'AFRL', 'value': 0,
    'source': '用户工程确认', 'confirmedAt': '2026-09-22T00:00:00+08:00',
}


def _pa4_request():
    return {'name': 'MCO_PA4_HSI_8M', 'chip': 'py32f420', 'directives': [
        {'kind': 'check_ready', 'peri': 'RCC', 'reg': 'CR', 'field': 'HSIRDY'},
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2},
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2PRE', 'value': 14},
        {'kind': 'clk_enable', 'periph': 'GPIOA'},
        {'kind': 'pin_config', 'pin': 'PA4', 'func': 'MCO2'},
    ]}


def test_confirmed_gpioa_afrl_reset_completes_pa4_candidate_with_provenance():
    db = EncodingDB('py32f420', reset_supplements=[SUPPLEMENT])
    artifact = prepare_candidate(_pa4_request(), product_profile_id='PT104',
                                 platform='chroma', initial_state='reset', db=db)
    assert artifact['rows']
    result = Composer('py32f420', db=db).compile(
        ComposeRequest('PA4', directives=[Directive(kind='pin_config', pin='PA4', func='MCO2')]))
    afrl = next(row for row in result.rows if row.addr == AFRL)
    assert not result.missing_resets
    assert any('用户工程确认' in source for source in afrl.sources)
    assert all('L0reset' not in source for source in afrl.sources)


def test_gpioa_supplement_does_not_fill_gpiob_same_register_type():
    db = EncodingDB('py32f420', reset_supplements=[SUPPLEMENT])
    word, missing = db.reset_word('GPIOB', 'AFRL', 0x40024420)
    assert word == 0
    assert missing == [f'AFSEL{i}' for i in range(8)]


def test_reset_supplement_rejects_known_reset_conflict():
    with pytest.raises(ValueError, match='conflicts'):
        EncodingDB('py32f420', reset_supplements=[{
            **SUPPLEMENT, 'address': 0x40024000, 'register': 'MODER', 'value': 0,
        }])


def test_supplement_changes_version_and_field_provenance_only_when_present():
    plain = EncodingDB('py32f420')
    empty = EncodingDB('py32f420', reset_supplements=[])
    db = EncodingDB('py32f420', reset_supplements=[SUPPLEMENT])
    assert plain.knowledge_version() == empty.knowledge_version()
    assert db.knowledge_version() != plain.knowledge_version()
    field = db.field('GPIOA', 'AFRL', 'AFSEL0')
    assert field['resetSupplement']['value'] == 0
    assert field['resetSupplement']['source'] == '用户工程确认'
    assert db.reset_source(AFRL) == '用户工程确认'
    with pytest.raises(CandidateError) as error:
        prepare_candidate(_pa4_request(), product_profile_id='PT104',
                          platform='chroma', initial_state='reset')
    assert error.value.code == 'MISSING_RESET'
    assert error.value.questions == [{
        'address': AFRL, 'peripheral': 'GPIOA', 'register': 'AFRL',
        'fields': [f'AFSEL{i}' for i in range(8)],
    }]
