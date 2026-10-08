"""Narrow access to existing workbench operations, coordinated with its session."""
from copy import copy, deepcopy
import hashlib
from pathlib import Path
import time


class WorkbenchTools:
    def __init__(self, session, guard):
        self.session, self.guard = session, guard
        self._prepared = {}

    def clear_prepared(self):
        self._prepared.clear()

    def _acquire(self, cancel):
        # A fast model may call a tool before its submitting HTTP route releases the guard.
        deadline = time.monotonic() + 2
        while not cancel.is_set() and time.monotonic() < deadline:
            if self.guard.acquire(timeout=.05):
                return
        if cancel.is_set():
            raise ValueError('任务已取消')
        raise ValueError('工作台正在处理其他操作，请稍后重试')

    def _sources(self, kind, request):
        if kind == 'hex':
            ids = request.get('taskIds')
            workspace = self.session.hex
            if not isinstance(ids, list) or not ids or any(i not in workspace.tasks for i in ids):
                raise ValueError('请在HEX页面选择当前已导入的任务与转换参数')
            paths = {i: workspace.root / i / 'input.hex' for i in ids}
        else:
            ids = request.get('inputIds')
            workspace = self.session.scan
            if not isinstance(ids, list) or not ids or any(i not in workspace.inputs for i in ids):
                raise ValueError('请在SCAN页面选择当前已导入的WGL与转换参数')
            paths = {i: Path(workspace.inputs[i]['path']) for i in ids}
        return {i: hashlib.sha256(path.read_bytes()).hexdigest() for i, path in paths.items()}

    def prepare_action(self, kind, record, cancel):
        if kind not in ('hex', 'scan', 'program'):
            raise ValueError('不支持该工作台操作')
        context = record['context'].get(kind) or {}
        request = deepcopy(context.get('generation') if kind == 'program' else context.get('request'))
        if not isinstance(request, dict):
            raise ValueError('请先在对应工作台页面选好输入、目标和参数，再重新提问')
        if cancel.is_set():
            raise ValueError('任务已取消')
        self._acquire(cancel)
        try:
            if kind == 'program':
                draft = context.get('draft') or {}
                if self.session.editor is None or self.session.editor.sha256 != draft.get('baseSha256'):
                    raise ValueError('程序工程已切换，请重新提问')
                if not request.get('targets'):
                    raise ValueError('请先在程序页选择生成目标')
                isolated = copy(self.session)
                isolated.checked = None
                request = {**draft, **request}
            else:
                sources = self._sources(kind, request)
        finally:
            self.guard.release()
        if kind == 'program':
            check_request = {**request, 'scope': 'program' if request.get('scope') == 'patterns' else request.get('scope', 'program')}
            result = isolated.check(check_request)
            if not result['valid']:
                raise ValueError('当前程序检查未通过，请先用check_program读取问题并修正')
            request['checkId'] = result['checkId']
            self._prepared[record['id']] = isolated
        if cancel.is_set():
            raise ValueError('任务已取消')
        return {'kind': 'action', 'operation': kind, 'name': {'hex': 'HEX转换', 'scan': 'SCAN转换', 'program': '程序生成'}[kind],
                'request': request, 'sources': sources if kind != 'program' else {},
                'notice': '按提问时页面设置启动；仅生成独立输出，不保存或关联工程。启动后取消聊天不会停止转换/生成。'}

    def execute_action(self, candidate, record):
        # The HTTP caller holds the workbench guard and has verified the latest UI snapshot.
        kind, request = candidate['operation'], deepcopy(candidate['request'])
        if kind == 'program':
            isolated = self._prepared.get(record['id'])
            if isolated is None or self.session.editor is not isolated.editor:
                raise ValueError('检查会话已失效，请重新准备生成任务')
            if self.session.job and self.session.job['status'] == 'running':
                raise ValueError('已有程序生成任务正在运行')
            result = isolated.generate(request)
            self.session.job = isolated.job
            return {'page': 'program', **result}
        if candidate['sources'] != self._sources(kind, request):
            raise ValueError('转换输入已改变，请重新准备任务')
        result = (self.session.scan.start(request, refresh_associations=False) if kind == 'scan'
                  else self.session.hex.start(request))
        return {'page': kind, 'jobId': result.get('jobId'), 'taskIds': request.get('taskIds', [])}

    def check_program(self, record, cancel):
        context = record.get('context', {}).get('program') or {}
        draft = context.get('draft')
        if not isinstance(draft, dict) or not draft.get('baseSha256'):
            raise ValueError('请先打开程序并读取当前草稿')
        if cancel.is_set():
            raise ValueError('任务已取消')
        self._acquire(cancel)
        try:
            if self.session.editor is None or self.session.editor.sha256 != draft['baseSha256']:
                raise ValueError('程序工程已切换，请基于当前工程重新提问')
            # Session.check only assigns checked; editor.apply/compile read their snapshots.
            # A shallow session copy pins the current editor while keeping check credentials isolated.
            isolated = copy(self.session)
            isolated.checked = None
        finally:
            self.guard.release()
        result = isolated.check(deepcopy(draft))
        if cancel.is_set():
            raise ValueError('任务已取消，检查结果未交付')
        return {key: result[key] for key in ('scope', 'valid', 'errors', 'warnings', 'diagnostics',
                                            'sha256', 'changeCount', 'appendCount') if key in result}
