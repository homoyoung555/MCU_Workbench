import json
import threading
import time

import pytest

from gui.assistant_tasks import AssistantTasks


def wait(tasks, identity):
    for _ in range(200):
        result = tasks.get(identity)
        if result['status'] != 'running':
            return result
        time.sleep(.01)
    raise AssertionError('task did not finish')


class Scripted:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def complete(self, messages, tools, cancel, on_progress=None):
        self.messages.append(json.loads(json.dumps(messages)))
        return next(self.responses)


def tool(name, arguments):
    return {'role': 'assistant', 'content': None, 'reasoning_content': 'private reasoning',
            'tool_calls': [{'id': 'call1', 'type': 'function', 'function': {
                'name': name, 'arguments': json.dumps(arguments)}}]}


def test_complete_replays_reasoning_but_history_does_not_persist_it(tmp_path):
    client = Scripted([tool('capabilities', {}), {'role': 'assistant', 'content': '支持范围已说明'}])
    tasks = AssistantTasks(tmp_path)
    identity = tasks.start({'requestId': 'one', 'text': '可以做什么？', 'context': {}}, client)['id']
    result = wait(tasks, identity)
    assert result['status'] == 'completed'
    assert client.messages[1][2]['reasoning_content'] == 'private reasoning'
    assert 'private reasoning' not in json.dumps(result)
    assert 'private reasoning' not in (tmp_path / identity / 'task.json').read_text(encoding='utf-8')
    assert 'py32f420' in result['answer']
    assert AssistantTasks(tmp_path).get(identity)['answer'] == result['answer']


def test_duplicate_submission_does_not_pay_twice(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Client:
        def complete(self, *args, **kwargs):
            entered.set()
            release.wait(3)
            return {'role': 'assistant', 'content': 'done'}
    tasks = AssistantTasks(tmp_path)
    payload = {'requestId': 'same', 'text': 'help', 'context': {}}
    first = tasks.start(payload, Client())
    assert entered.wait(2)
    assert tasks.start(payload, Client())['id'] == first['id']
    with pytest.raises(ValueError):
        tasks.start({**payload, 'text': 'different'}, Client())
    tasks.cancel(first['id'])
    release.set()
    assert wait(tasks, first['id'])['status'] == 'cancelled'
    assert tasks.get(first['id'])['answer'] == ''


def test_unknown_tool_is_rejected_and_never_executes(tmp_path):
    client = Scripted([tool('run_shell', {'command': 'bad'}), {'role': 'assistant', 'content': '不支持'}])
    tasks = AssistantTasks(tmp_path)
    result = wait(tasks, tasks.start({'requestId': 'x', 'text': 'help', 'context': {}}, client)['id'])
    assert result['status'] == 'completed'
    assert 'unsupported_tool' in client.messages[1][-1]['content']


def test_candidate_is_independent_and_requires_explicit_reset_condition(tmp_path):
    request = {'name': 'RCC_Fields', 'chip': 'py32f420', 'directives': [
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}]}
    client = Scripted([tool('prepare_swd', {'request': request}), {'role': 'assistant', 'content': '已自动关联Link并完成上机'}])
    tasks = AssistantTasks(tmp_path)
    payload = {'requestId': 'reset', 'text': 'generate', 'context': {},
               'conditions': {'product': 'PT104', 'platform': 'chroma', 'initialState': 'reset'}}
    result = wait(tasks, tasks.start(payload, client)['id'])
    assert result['status'] == 'completed'
    assert len(result['candidates']) == 1
    assert '已自动关联' not in result['answer'] and '完成上机' not in result['answer']
    assert '0x02000000' in result['answer'] and '已生成' in result['answer']
    assert '尚未保存或关联' in result['answer']
    assert tasks._conversations[result['id']][-1]['content'] == result['answer']
    assert tasks.artifact(result['id'], result['candidates'][0]['id'], 'excel').read_bytes()[:2] == b'PK'
    from gui.assistant_swd import read_provenance
    raw = tasks.artifact(result['id'], result['candidates'][0]['id'], 'excel').read_bytes()
    assert read_provenance(raw)['record']['materialEvidence']['scope'] == 'bundled_only'
    assert result['candidates'][0]['validation']['hardware'] == 'not_verified'
    from gui.server import Session
    from gui.swd_workspace import SwdWorkspace
    swd = SwdWorkspace(Session(master=None, output=tmp_path / 'workspace'))
    candidate_id = result['candidates'][0]['id']
    with pytest.raises(ValueError, match='草稿'):
        tasks.stage(result['id'], candidate_id, {'changed': True}, swd)
    staged = tasks.stage(result['id'], candidate_id, {}, swd)
    assert not swd.data['documents'] and not swd.file.exists()
    assert staged['document']['rows'][0]['data'] == '0x02000000'
    assert tasks.stage(result['id'], candidate_id, {}, swd)['document']['id'] == staged['document']['id']
    client = Scripted([tool('prepare_swd', {'request': request}), {'role': 'assistant', 'content': '需要复位条件'}])
    result = wait(tasks, tasks.start({**payload, 'requestId': 'unknown', 'conditions': {}}, client)['id'])
    assert not result['candidates']
    assert 'initial' in client.messages[1][-1]['content']


def test_restart_marks_unfinished_interrupted_without_network(tmp_path):
    folder = tmp_path / ('a' * 32)
    folder.mkdir()
    (folder / 'task.json').write_text(json.dumps({'id': folder.name, 'status': 'running', 'answer': '',
        'requestId': 'old', 'requestDigest': 'x', 'candidates': []}), encoding='utf-8')
    tasks = AssistantTasks(tmp_path)
    assert tasks.get(folder.name)['status'] == 'interrupted'


def test_provider_failure_keeps_safe_code_and_message(tmp_path):
    from gui.assistant_model import ModelError
    class Client:
        def complete(self, *args, **kwargs):
            raise ModelError('auth', '身份验证失败，请检查本机 API 密钥。')
    tasks = AssistantTasks(tmp_path)
    result = wait(tasks, tasks.start({'requestId': 'auth', 'text': 'help', 'context': {}}, Client())['id'])
    assert result['errorCode'] == 'auth'
    assert '身份验证失败' in result['error']


def test_knowledge_search_can_discover_field_names_without_guessing(tmp_path):
    client = Scripted([tool('search_knowledge', {'query': 'MCO2', 'peripheral': 'RCC'}),
                       {'role': 'assistant', 'content': '查询完成'}])
    tasks = AssistantTasks(tmp_path)
    result = wait(tasks, tasks.start({'requestId': 'search', 'text': 'MCO2字段', 'context': {}}, client)['id'])
    assert result['status'] == 'completed'
    output = json.loads(client.messages[1][-1]['content'])
    assert any(item['field'] == 'MCO2SEL' for item in output['fields'])
    assert output['knowledgeVersion']


def test_edit_tool_prepares_diff_without_requiring_reset_or_writing_workspace(tmp_path):
    context = {'swd': {'document': {'id': 'original', 'name': 'manual.xlsx', 'rows': [
        {'row': 2, 'pattern': 'Manual', 'type': 'W', 'step': '/', 'addr': '0x40021014', 'data': '0xE1000000'}]}}}
    client = Scripted([tool('prepare_swd_edit', {'operations': [
        {'rowIndex': 0, 'peripheral': 'RCC', 'register': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}]}),
        {'role': 'assistant', 'content': '已应用，WAIT是100ms'}])
    tasks = AssistantTasks(tmp_path)
    result = wait(tasks, tasks.start({'requestId': 'edit', 'text': '修改MCO2SEL', 'context': context}, client)['id'])
    candidate = result['candidates'][0]
    assert candidate['kind'] == 'edit'
    assert '100ms' not in result['answer'] and '已应用' not in result['answer']
    assert '0xE1000000 → 0xE2000000' in result['answer']
    assert candidate['rows'][0]['data'] == '0xE2000000'
    assert tasks.stage(result['id'], candidate['id'], context, None)['edit']['diff']
    assert context['swd']['document']['rows'][0]['data'] == '0xE1000000'


def test_stale_material_snapshot_rejected_before_model_call(tmp_path):
    client = Scripted([])
    tasks = AssistantTasks(tmp_path)
    with pytest.raises(ValueError, match='资料'):
        tasks.start({'requestId': 'materials', 'text': 'help', 'context': {'swd': {'materialVersion': 'old'}}},
                    client, materials={'version': 'new', 'materials': []})
    assert not client.messages


def test_real_imported_width_conflict_blocks_artifact_delivery(tmp_path):
    from pathlib import Path
    from gui.swd_materials import MaterialLibrary
    library = MaterialLibrary(tmp_path / 'materials')
    cache = Path(__file__).resolve().parents[1] / 'gui/data/py32f420_svd_cache.json'
    library.import_material(cache.read_bytes(), cache.name, kind='svd_cache')
    materials = library.state()
    client = Scripted([tool('prepare_swd', {'request': {'name': 'Conflict', 'chip': 'py32f420', 'directives': [
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}]}}),
        {'role': 'assistant', 'content': '资料有冲突，无法交付'}])
    tasks = AssistantTasks(tmp_path / 'tasks')
    result = wait(tasks, tasks.start({'requestId': 'conflict', 'text': '配置MCO2SEL',
        'context': {'swd': {'materialVersion': materials['version']}},
        'conditions': {'product': 'PT104', 'platform': 'chroma', 'initialState': 'reset'}}, client, materials=materials)['id'])
    assert not result['candidates']
    assert 'PPRE1' in client.messages[1][-1]['content']


def test_followup_replays_full_session_and_restart_uses_explicit_history(tmp_path):
    tasks = AssistantTasks(tmp_path)
    first = wait(tasks, tasks.start({'requestId': 'first', 'text': '解释范围', 'context': {}},
        Scripted([tool('capabilities', {}), {'role': 'assistant', 'content': '首个回答'}]))['id'])
    client = Scripted([{'role': 'assistant', 'content': '接续回答'}])
    second = wait(tasks, tasks.start({'requestId': 'second', 'parentId': first['id'],
        'text': '那需要什么资料？', 'context': {}}, client)['id'])
    assert second['parentId'] == first['id']
    assert client.messages[0][2]['reasoning_content'] == 'private reasoning'
    assert client.messages[0][-2]['content'] == first['answer']
    assert 'private reasoning' not in (tmp_path / second['id'] / 'task.json').read_text(encoding='utf-8')
    resumed = AssistantTasks(tmp_path)
    client = Scripted([{'role': 'assistant', 'content': '重启后继续'}])
    wait(resumed, resumed.start({'requestId': 'third', 'parentId': second['id'],
        'text': '请继续', 'context': {}}, client)['id'])
    assert all(message['role'] in ('system', 'user') for message in client.messages[0])
    assert client.messages[0][1]['content'] and 'py32f420' in client.messages[0][1]['content']
    assert '接续回答' in json.dumps(client.messages[0], ensure_ascii=False)


def test_followup_cannot_reuse_other_project_or_incomplete_task(tmp_path):
    tasks = AssistantTasks(tmp_path)
    first = wait(tasks, tasks.start({'requestId': 'first', 'text': 'A工程',
        'context': {'program': {'name': 'A.xlsx', 'sha256': 'aaa'}}},
        Scripted([{'role': 'assistant', 'content': 'A工程事实'}]))['id'])
    with pytest.raises(ValueError, match='工程|对象'):
        tasks.start({'requestId': 'other', 'parentId': first['id'], 'text': '继续',
            'context': {'program': {'name': 'B.xlsx', 'sha256': 'bbb'}}}, Scripted([]))
    with pytest.raises(ValueError, match='不存在'):
        tasks.start({'requestId': 'missing', 'parentId': 'bad', 'text': '继续', 'context': {}}, Scripted([]))


def test_clear_history_removes_owned_tasks_but_preserves_unrelated_files(tmp_path):
    tasks = AssistantTasks(tmp_path)
    result = wait(tasks, tasks.start({'requestId': 'first', 'text': '问题', 'context': {}},
        Scripted([{'role': 'assistant', 'content': '回答'}]))['id'])
    unrelated = tmp_path / 'user-note.txt'
    unrelated.write_text('keep', encoding='utf-8')
    assert tasks.clear() == {'removed': 1}
    assert tasks.list() == [] and AssistantTasks(tmp_path).list() == []
    assert not (tmp_path / result['id']).exists()
    assert unrelated.read_text() == 'keep'


def test_workbench_action_is_explicit_stale_safe_and_idempotent(tmp_path):
    class Service:
        calls = 0
        def prepare_action(self, operation, record, cancel):
            return {'kind': 'action', 'operation': operation, 'request': {'taskIds': ['input']}}
        def execute_action(self, candidate, record):
            self.calls += 1
            return {'page': 'hex', 'taskIds': ['input']}
    service = Service()
    tasks = AssistantTasks(tmp_path, service)
    client = Scripted([tool('prepare_workbench_action', {'operation': 'hex'}),
                       {'role': 'assistant', 'content': '转换已经完成'}])
    result = wait(tasks, tasks.start({'requestId': 'action', 'text': '转换', 'context': {}}, client)['id'])
    candidate = result['candidates'][0]
    assert service.calls == 0
    assert '转换已经完成' not in result['answer'] and '尚未启动' in result['answer']
    with pytest.raises(ValueError, match='改变'):
        tasks.execute(result['id'], candidate['id'], {'changed': True})
    first = tasks.execute(result['id'], candidate['id'], {})
    assert tasks.execute(result['id'], candidate['id'], {}) == first
    assert service.calls == 1


def test_connection_test_requires_real_tool_roundtrip(tmp_path):
    tasks = AssistantTasks(tmp_path)
    client = Scripted([tool('connection_probe', {}), {'role': 'assistant', 'content': '连接成功'}])
    result = wait(tasks, tasks.start({'requestId': 'probe', 'text': '连接测试', 'context': {}},
                                    client, connection_test=True)['id'])
    assert result['status'] == 'completed'
    assert client.messages[1][-1]['role'] == 'tool'
    assert result['events'][0]['tool'] == 'connection_probe'
    assert not result['candidates']
    client = Scripted([{'role': 'assistant', 'content': '伪造成功'}])
    result = wait(tasks, tasks.start({'requestId': 'bad-probe', 'text': '连接测试', 'context': {}},
                                    client, connection_test=True)['id'])
    assert result['status'] == 'failed'
