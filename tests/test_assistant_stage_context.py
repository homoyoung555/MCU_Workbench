from copy import deepcopy
from types import SimpleNamespace
import pytest
from gui.assistant_tasks import AssistantTasks
from gui.swd_workspace import SwdWorkspace
from tests.test_assistant_tasks import Scripted, tool, wait


def candidate(tmp_path, snapshot):
    swd = SwdWorkspace(SimpleNamespace(output=tmp_path / 'workspace', editor=None, checked=None))
    tasks = AssistantTasks(tmp_path / 'tasks')
    request = {'name': 'Stage', 'chip': 'py32f420', 'directives': [
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}]}
    record = wait(tasks, tasks.start({'requestId': 'stage', 'text': 'generate', 'context': snapshot,
        'conditions': {'product': 'PCD009', 'platform': 'chroma', 'initialState': 'reset'}},
        Scripted([tool('prepare_swd', {'request': request}), {'role': 'assistant', 'content': 'done'}]),
        materials=swd.materials().state())['id'])
    return tasks, record, swd


def test_home_candidate_can_stage_after_first_editor_load(tmp_path):
    before = {'page': 'home', 'program': None, 'swd': {}, 'hex': None}
    tasks, record, swd = candidate(tmp_path, before)
    after = {**before, 'page': 'swd', 'swd': {'document': None, 'pattern': '', 'dirty': False,
        'configDirty': False, 'popupDraft': None, 'materialVersion': swd.materials().state()['version']}}
    staged = tasks.stage(record['id'], record['candidates'][0]['id'], after, swd)
    assert staged['context'] == after
    assert staged['document']['rows'][0]['data'] == '0x02000000'
    for change in ({'dirty': True}, {'configDirty': True}, {'popupDraft': {'rows': []}}):
        with pytest.raises(ValueError):
            tasks.stage(record['id'], record['candidates'][0]['id'], {**after, 'swd': {**after['swd'], **change}}, swd)


def test_page_navigation_is_not_a_draft_edit_but_row_changes_are(tmp_path):
    before = {'page': 'swd', 'swd': {'document': {'rows': [{'data': '0x1'}]}}}
    tasks, record, swd = candidate(tmp_path, before)
    after = deepcopy(before)
    after['page'] = 'home'
    assert tasks.stage(record['id'], record['candidates'][0]['id'], after, swd)['context'] == after
    after['swd']['document']['rows'][0]['data'] = '0x2'
    with pytest.raises(ValueError, match='草稿'):
        tasks.stage(record['id'], record['candidates'][0]['id'], after, swd)
