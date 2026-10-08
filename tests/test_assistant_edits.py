from copy import deepcopy

import pytest

from gui.assistant_edits import prepare_edit


def snapshot():
    return {'document': {'id': 'doc', 'name': 'manual.xlsx', 'rows': [
        {'row': 2, 'pattern': 'Manual', 'type': 'W', 'addr': '0x40021014', 'data': '0xE1000000',
         'step': '/', 'description': '手工配置', 'extra': '保留'},
        {'row': 3, 'pattern': None, 'type': 'us', 'data': '250', 'description': '手工等待'},
        {'row': 4, 'pattern': 'Other', 'type': 'R', 'addr': '0x40021014'}]}, 'popupDraft': None}


def change(**kw):
    return dict(rowIndex=0, peripheral='RCC', register='CFGR1', field='MCO2SEL', value=2, **kw)


def test_only_requested_bits_change_preserving_manual_sequence_and_columns():
    source = snapshot()
    before = deepcopy(source)
    result = prepare_edit(source, [change()])
    assert source == before
    assert result['scope'] == 'document'
    assert result['rows'][0]['data'] == '0xE2000000'
    assert result['rows'][0]['extra'] == '保留'
    assert result['rows'][0]['description'] == '手工配置'
    assert result['rows'][1:] == before['document']['rows'][1:]
    assert result['diff'][0]['before'] == '0xE1000000'
    assert result['diff'][0]['after'] == '0xE2000000'
    assert result['validation']['existingSequence'] == 'not_revalidated'


def test_popup_is_actual_edit_target_not_saved_rows():
    source = snapshot()
    source['popupDraft'] = {'documentId': 'doc', 'pattern': 'Manual', 'rows': [
        {**source['document']['rows'][0], 'data': '0xA1000000'}]}
    result = prepare_edit(source, [change()])
    assert result['scope'] == 'popup'
    assert result['rows'][0]['data'] == '0xA2000000'
    assert source['document']['rows'][0]['data'] == '0xE1000000'


@pytest.mark.parametrize('alteration', [
    {'type': 'R'}, {'step': '24'}, {'data': 'symbol'}, {'addr': '0x40021010'}])
def test_cannot_change_nonliteral_or_wrong_register_row(alteration):
    source = snapshot()
    source['document']['rows'][0].update(alteration)
    with pytest.raises(ValueError):
        prepare_edit(source, [change()])


@pytest.mark.parametrize('operation', [
    {'rowIndex': True, 'peripheral': 'RCC', 'register': 'CFGR1', 'field': 'MCO2SEL', 'value': 2},
    {'rowIndex': 0, 'peripheral': 'RCC', 'register': 'CFGR1', 'field': 'MCO2SEL', 'value': -1},
    {'rowIndex': 0, 'peripheral': 'RCC', 'register': 'CFGR1', 'field': 'MCO2SEL', 'value': 256},
    {'rowIndex': 0, 'peripheral': 'RCC', 'register': 'CFGR1', 'field': 'MCO2SEL', 'value': 2, 'run': 'script'}])
def test_bad_operation_rejected(operation):
    with pytest.raises(ValueError):
        prepare_edit(snapshot(), [operation])


def test_conflicting_updates_to_same_field_are_rejected():
    with pytest.raises(ValueError):
        prepare_edit(snapshot(), [change(), {**change(), 'value': 3}])
