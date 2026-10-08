import threading
from types import SimpleNamespace

import pytest

from gui.assistant_workbench import WorkbenchTools


class CheckSession:
    def __init__(self, sha='A'):
        self.editor = SimpleNamespace(sha256=sha)
        self.checked = {'id': 'user-check'}
        self.seen = []
        self.guard = threading.Lock()
        self.fail = False

    def check(self, payload):
        assert self.guard.acquire(blocking=False), 'assistant check must release the main-window lock'
        self.guard.release()
        self.seen.append(payload)
        self.checked = {'id': 'temporary'}
        if self.fail:
            raise ValueError('bad draft')
        return {'valid': True, 'errors': 0, 'warnings': 1, 'diagnostics': [{'message': 'warning'}],
                'checkId': 'temporary', 'sha256': 'draft'}


def test_check_uses_frozen_draft_and_restores_user_check():
    session = CheckSession()
    previous = session.checked
    service = WorkbenchTools(session, session.guard)
    record = {'context': {'program': {'draft': {'baseSha256': 'A', 'changes': [{'cell': 'X1', 'value': 3}]}}}}
    result = service.check_program(record, threading.Event())
    assert session.seen == [record['context']['program']['draft']]
    assert session.checked is previous
    assert result['warnings'] == 1
    assert 'checkId' not in result


def test_check_cannot_cross_project_or_leave_state_changed_after_error():
    session = CheckSession('B')
    previous = session.checked
    service = WorkbenchTools(session, session.guard)
    record = {'context': {'program': {'draft': {'baseSha256': 'A', 'changes': []}}}}
    with pytest.raises(ValueError, match='工程'):
        service.check_program(record, threading.Event())
    session.editor.sha256 = 'A'
    session.fail = True
    with pytest.raises(ValueError, match='bad draft'):
        service.check_program(record, threading.Event())
    assert session.checked is previous


def test_cancelled_or_busy_check_does_not_touch_session():
    session = SimpleNamespace(editor=SimpleNamespace(sha256='A'), checked='keep')
    lock = threading.Lock()
    service = WorkbenchTools(session, lock)
    record = {'context': {'program': {'draft': {'baseSha256': 'A', 'changes': []}}}}
    event = threading.Event()
    event.set()
    with pytest.raises(ValueError):
        service.check_program(record, event)
    event.clear()
    lock.acquire()
    try:
        with pytest.raises(ValueError, match='正在'):
            service.check_program(record, event)
    finally:
        lock.release()
    assert session.checked == 'keep'


def test_background_check_waits_for_submit_route_to_release_lock():
    session = CheckSession()
    session.guard.acquire()
    release = threading.Timer(.05, session.guard.release)
    release.start()
    try:
        result = WorkbenchTools(session, session.guard).check_program(
            {'context': {'program': {'draft': {'baseSha256': 'A', 'changes': []}}}}, threading.Event())
        assert result['valid']
    finally:
        release.join()


def test_real_program_check_preserves_master_and_user_check(tmp_path):
    import hashlib
    from gui.server import Session
    from tests.workspace_paths import FORMAL_MASTER

    original = FORMAL_MASTER.read_bytes()
    session = Session(master=FORMAL_MASTER, output=tmp_path / 'output')
    previous = session.checked = {'id': 'main-window-check'}
    draft = {'baseSha256': session.editor.sha256,
             'changes': [{'sheet': 'FLOW', 'cell': 'S4', 'old': .8, 'value': '0.801'}]}
    expected = session.editor.apply(draft['baseSha256'], draft['changes'])
    result = WorkbenchTools(session, threading.Lock()).check_program(
        {'context': {'program': {'draft': draft}}}, threading.Event())
    assert result['valid'], result['diagnostics']
    assert result['sha256'].lower() == hashlib.sha256(expected).hexdigest()
    assert result['changeCount'] == 1
    assert session.checked is previous and session.editor.raw == original
    assert FORMAL_MASTER.read_bytes() == original
    assert not (tmp_path / 'output').exists()


def test_hex_action_requires_explicit_execution_and_uses_frozen_options(tmp_path):
    from gui.hex_workspace import HexWorkspace
    from gui.server import Session
    session = Session(master=None, output=tmp_path)
    session.hex = HexWorkspace(tmp_path / 'hex')
    task = session.hex.add_input(b':0400000001020304F2\n:00000001FF\n', 'sample.hex')
    service = WorkbenchTools(session, threading.Lock())
    options = {'taskIds': [task['id']], 'profileId': 'test-profile'}
    record = {'id': 'record', 'context': {'hex': {'request': options}}}
    candidate = service.prepare_action('hex', record, threading.Event())
    assert session.hex.state()['tasks'][0]['status'] == 'ready'
    seen = []
    session.hex.start = lambda payload: seen.append(payload) or {'running': True}
    result = service.execute_action(candidate, record)
    assert seen == [options] and result['page'] == 'hex'
    (session.hex.root / task['id'] / 'input.hex').write_bytes(b'changed')
    with pytest.raises(ValueError, match='输入'):
        service.execute_action(candidate, record)


def test_real_hex_and_scan_actions_produce_downloadable_outputs(tmp_path):
    import time
    from gui.server import Session, make_server
    from tests.test_gui_hex_conversion import sample_hex
    from tests.test_gui_scan_conversion import WGL
    server = make_server(0, Session(master=None, output=tmp_path))
    try:
        service = server.assistant.workbench
        task = server.hex.add_input(sample_hex(), 'sample.hex')
        record = {'id': 'hex-action', 'context': {'hex': {'request': {
            'taskIds': [task['id']], 'profileId': 'swd-sram-pt100', 'outputPlatform': 'both'}}}}
        candidate = service.prepare_action('hex', record, threading.Event())
        service.execute_action(candidate, record)
        deadline = time.monotonic() + 30
        while server.hex.state()['running'] and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.hex.state()['tasks'][0]['status'] == 'completed'
        assert server.hex.download(task['id']).is_file()
        source = server.scan.add_input(WGL.encode(), 'sample.wgl')
        record = {'id': 'scan-action', 'context': {'scan': {'request': {
            'inputIds': [source['id']], 'platforms': ['chroma', 's100'], 'adapt': False}}}}
        candidate = service.prepare_action('scan', record, threading.Event())
        service.execute_action(candidate, record)
        while server.scan.job['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.scan.job['status'] == 'completed', server.scan.job
        assert server.scan.job['result']['files']
        assert not server.scan.associations
    finally:
        server.server_close()


def test_real_program_generation_action_preserves_main_check(tmp_path, monkeypatch):
    import time
    from gui.server import Session
    from tests.workspace_paths import FORMAL_MASTER
    # Keep the production write boundary enabled, rooted in this test's isolated output.
    output = tmp_path.parent / 'program'
    monkeypatch.setattr('gui.generation._RUN_PARENT', output)
    session = Session(master=FORMAL_MASTER, output=output)
    previous = session.checked = {'id': 'main-check'}
    service = WorkbenchTools(session, threading.Lock())
    target = next(t['id'] for t in session.targets if t['platform'] == 'chroma' and t['variant'] == 'lab')
    record = {'id': 'program-action', 'context': {'program': {
        'draft': {'baseSha256': session.editor.sha256, 'changes': []},
        'generation': {'scope': 'program', 'targets': [target], 'validate': False}}}}
    candidate = service.prepare_action('program', record, threading.Event())
    assert session.checked is previous and session.job is None
    result = service.execute_action(candidate, record)
    assert result['jobId'] == session.job['id']
    deadline = time.monotonic() + 120
    while session.job['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.1)
    import json
    (tmp_path / 'assistant-program-result.json').write_text(json.dumps(session.job, ensure_ascii=False, indent=2), encoding='utf-8')
    assert session.job['status'] == 'completed', json.dumps(session.job, ensure_ascii=False)
    assert session.checked is previous
    assert session.editor.raw == FORMAL_MASTER.read_bytes()
