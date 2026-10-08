import json
import pytest

from gui.assistant_tasks import AssistantTasks
from gui.assistant_swd import read_provenance
from tests.test_assistant_tasks import Scripted, tool, wait


REQUEST = {'name': 'PA4_MCO', 'chip': 'py32f420', 'directives': [
    {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2},
    {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2PRE', 'value': 14},
    {'kind': 'clk_enable', 'periph': 'GPIOA'},
    {'kind': 'pin_config', 'pin': 'PA4', 'func': 'MCO2'}]}


def start(tasks, identity='one', product='PCD009'):
    client = Scripted([tool('prepare_swd', {'request': REQUEST}),
                       {'role': 'assistant', 'content': 'done'}])
    result = wait(tasks, tasks.start({'requestId': identity, 'text': 'PA4 MCO HSI8M /128',
        'context': {}, 'conditions': {'product': product, 'platform': 'chroma', 'initialState': 'reset'}}, client)['id'])
    return result, client


def answers(record, value='全0'):
    return [{'id': q['id'], 'value': value, 'source': '用户工程确认'} for q in record['knowledgeQuestions']]


def test_missing_reset_asks_user_persists_and_retries_without_model(tmp_path):
    tasks = AssistantTasks(tmp_path)
    record, client = start(tasks)
    assert record['status'] == 'needs_input'
    assert len(client.messages) == 1 and not record['candidates']
    q, = record['knowledgeQuestions']
    assert q['address'] == 0x40024020 and q['peripheral'] == 'GPIOA'
    assert q['fields'] == ['AFSEL' + str(i) for i in range(8)]
    tasks = AssistantTasks(tmp_path)  # Pending question survives a restart.
    result = tasks.confirm_knowledge(record['id'], answers(record), {})
    assert result['status'] == 'completed', result
    candidate, = result['candidates']
    assert len(candidate['rows']) == 7
    assert next(row for row in candidate['rows'] if row['addr'] == '0x40024020')['data'] == '0x00000000'
    provenance = read_provenance(tasks.artifact(result['id'], candidate['id'], 'excel').read_bytes())
    assert '用户工程确认' in json.dumps(provenance, ensure_ascii=False)
    assert '用户工程确认' in result['answer']
    assert tasks.confirm_knowledge(record['id'], answers(record), {})['candidates'] == result['candidates']
    tasks = AssistantTasks(tmp_path)
    repeated, _ = start(tasks, 'two')
    assert repeated['status'] == 'completed'
    other, _ = start(tasks, 'three', 'PT104')
    assert other['status'] == 'needs_input'
    tasks.clear()
    assert start(AssistantTasks(tmp_path), 'after-clear')[0]['status'] == 'completed'


@pytest.mark.parametrize('value', ['不确定', '-1', '0x100000000', '', True])
def test_invalid_answer_leaves_pending_and_does_not_save(tmp_path, value):
    tasks = AssistantTasks(tmp_path)
    record, _ = start(tasks)
    with pytest.raises(ValueError):
        tasks.confirm_knowledge(record['id'], answers(record, value), {})
    assert tasks.get(record['id'])['status'] == 'needs_input'
    assert not (tmp_path / 'reset-confirmations.json').exists()


def test_confirmation_rejects_changed_context_and_unknown_question(tmp_path):
    tasks = AssistantTasks(tmp_path)
    record, _ = start(tasks)
    with pytest.raises(ValueError, match='草稿'):
        tasks.confirm_knowledge(record['id'], answers(record), {'changed': True})
    answer = answers(record)
    answer[0]['id'] = 'invented'
    with pytest.raises(ValueError):
        tasks.confirm_knowledge(record['id'], answer, {})
    assert not (tmp_path / 'reset-confirmations.json').exists()


def test_confirmation_reconciles_imported_reset_conflict_before_saving(tmp_path):
    from tests.test_assistant_materials import _source, _state
    source = _source(address='0x40024020', bits='[3:0]', reset='1', access='')
    source.update(peripheral='GPIOA', name='AFRL')
    source['fields'][0]['name'] = 'AFSEL0'
    tasks = AssistantTasks(tmp_path)
    record = wait(tasks, tasks.start({'requestId': 'conflict', 'text': 'PA4', 'context': {},
        'conditions': {'product': 'PCD009', 'platform': 'chroma', 'initialState': 'reset'}},
        Scripted([tool('prepare_swd', {'request': REQUEST})]), materials=_state(source))['id'])
    assert record['status'] == 'needs_input'
    with pytest.raises(ValueError, match='复位值'):
        tasks.confirm_knowledge(record['id'], answers(record), {})
    assert not (tmp_path / 'reset-confirmations.json').exists()


def test_new_knowledge_invalidates_previously_generated_candidate(tmp_path):
    tasks = AssistantTasks(tmp_path)
    record, _ = start(tasks)
    request = {**REQUEST, 'directives': REQUEST['directives'][:2]}
    old = wait(tasks, tasks.start({'requestId': 'old', 'text': 'RCC', 'context': {},
        'conditions': record['conditions']}, Scripted([tool('prepare_swd', {'request': request}),
        {'role': 'assistant', 'content': 'done'}]))['id'])
    tasks.confirm_knowledge(record['id'], answers(record), {})
    with pytest.raises(ValueError, match='知识资料版本'):
        tasks.stage(old['id'], old['candidates'][0]['id'], {}, None)


def test_confirmed_field_is_queryable_and_matches_imported_zero_reset(tmp_path):
    from tests.test_assistant_materials import _source, _state
    source = _source(address='0x40024020', bits='[3:0]', reset='0', access='')
    source.update(peripheral='GPIOA', name='AFRL')
    source['fields'][0]['name'] = 'AFSEL0'
    tasks = AssistantTasks(tmp_path)
    record = wait(tasks, tasks.start({'requestId': 'agree', 'text': 'PA4', 'context': {},
        'conditions': {'product': 'PCD009', 'platform': 'chroma', 'initialState': 'reset'}},
        Scripted([tool('prepare_swd', {'request': REQUEST})]), materials=_state(source))['id'])
    result = tasks.confirm_knowledge(record['id'], answers(record), {})
    assert result['status'] == 'completed'
    field = tasks._db(result).field('GPIOA', 'AFRL', 'AFSEL0')
    assert field['reset'] == 0 and field['resetSupplement']['source'] == '用户工程确认'
