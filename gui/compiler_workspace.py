"""Uploaded program copies and a single background vendor-compiler queue."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import threading
import time
import zipfile


def relative_file(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('文件路径无效')
    path = PurePosixPath(value)
    parts = value.split('/')
    reserved = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)
    if path.is_absolute() or any(p in ('', '.', '..') or p.endswith((' ', '.')) or
            re.search(r'[<>:"|?*\x00-\x1f]', p) or reserved.match(p) for p in parts):
        raise ValueError('文件路径必须位于所选程序文件夹内')
    return path


class CompilerWorkspace:
    def __init__(self, root, runner=None):
        self.root = Path(root)
        self.tasks = {}
        self.lock = threading.RLock()
        self.worker = None
        self.runner = runner
        for metadata in sorted(self.root.glob('*/task.json'), key=lambda p: p.stat().st_mtime):
            try:
                task = json.loads(metadata.read_text(encoding='utf-8'))
                if task['id'] != metadata.parent.name or task.get('archived'):
                    continue
                if task['status'] in ('running', 'queued', 'uploading'):
                    task.update(status='interrupted', phase='上次运行已中断，请重新编译或重新上传')
                self.tasks[task['id']] = task
            except (ValueError, KeyError, OSError):
                continue

    def state(self):
        from gui.compiler_runner import tool_status, COMPILER_MODES
        with self.lock:
            return {'tasks': [deepcopy({k: v for k, v in task.items() if k != 'files'})
                              for task in self.tasks.values()],
                    'running': any(t['status'] in ('queued', 'running') for t in self.tasks.values()),
                    'tools': tool_status(), 'modes': deepcopy(COMPILER_MODES)}

    def _task(self, identity):
        if identity not in self.tasks:
            raise ValueError('编译任务不存在')
        return self.tasks[identity]

    def _persist(self, task):
        folder = self.root / task['id']
        temporary = folder / 'task.tmp'
        temporary.write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
        temporary.replace(folder / 'task.json')

    def create(self, payload):
        name = payload.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 180:
            raise ValueError('请提供程序文件夹名称')
        with self.lock:
            identity = secrets.token_hex(12)
            (self.root / identity / 'source').mkdir(parents=True)
            task = {'id': identity, 'name': name, 'status': 'uploading', 'platform': None,
                    'phase': '正在上传', 'error': None, 'result': None, 'files': [], 'bytes': 0}
            self.tasks[identity] = task
            self._persist(task)
            return deepcopy(task)

    def discard(self, payload):
        with self.lock:
            task = self._task(payload.get('id'))
            if task['status'] not in ('uploading', 'interrupted') or task.get('entry'):
                raise ValueError('只能放弃未完成上传')
            task.update(status='failed', error='上传未完成，已放弃', phase='请重新添加文件夹')
            self._persist(task)
            return self.state()

    def clear_history(self, payload):
        with self.lock:
            if (self.worker and self.worker.is_alive()) or any(t['status'] in ('uploading', 'queued', 'running') for t in self.tasks.values()):
                raise ValueError('上传或编译期间不能清空列表')
            for identity, task in list(self.tasks.items()):
                task['archived'] = True
                self._persist(task)
                del self.tasks[identity]
            return self.state()

    def start(self, payload):
        from gui.compiler_runner import COMPILER_MODES
        ids = payload.get('ids')
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError('串行队列正在运行，请等待结束')
            if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
                raise ValueError('请选择 1–100 个不同的编译任务')
            tasks = [self._task(i) for i in ids]
            if any(not t.get('entry') or t['status'] in ('uploading', 'queued', 'running') for t in tasks):
                raise ValueError('请先完成所有选中程序的上传')
            modes = payload.get('modes', {})
            if not isinstance(modes, dict) or any(identity not in ids for identity in modes):
                raise ValueError('编译模式配置无效')
            chosen = {t['id']: modes.get(t['id'], t.get('mode', 'all')) for t in tasks}
            if any(not isinstance(chosen[t['id']], str) or chosen[t['id']] not in COMPILER_MODES[t['platform']] for t in tasks):
                raise ValueError('当前平台不支持此编译模式')
            for task in tasks:
                task.update(status='queued', phase='等待串行编译', result=None, error=None, mode=chosen[task['id']])
                self._persist(task)
            self.worker = threading.Thread(target=self._execute, args=(ids,), daemon=True)
            self.worker.start()
            return self.state()

    def _execute(self, ids):
        for identity in ids:
            task = self.tasks[identity]
            started = time.monotonic()
            folder = self.root / identity
            log = folder / 'compile.log'
            try:
                with self.lock:
                    task.update(status='running', phase='准备编译副本')
                    self._persist(task)
                # A fresh directory prevents uploaded or previous output proving success.
                working = folder / ('run-' + secrets.token_hex(6)) / Path(task['entry']).stem
                source = folder / 'source'
                previous = task.get('lastSuccessfulRun', '')
                if task.get('mode', 'all') != 'all' and re.fullmatch(r'run-[0-9a-f]{12}', previous):
                    source = folder / previous / Path(task['entry']).stem
                    if not source.is_dir():
                        raise ValueError('上次成功的编译副本已缺失，请重新全部编译')
                shutil.copytree(source, working)
                log.write_text('', encoding='utf-8')
                def progress(message):
                    with self.lock:
                        task['phase'] = message
                runner = self.runner
                if runner is None:
                    from gui.compiler_runner import compile_program
                    runner = compile_program
                result = runner(working, task['platform'], task['entry'], log, progress, mode=task.get('mode', 'all'))
                result['mode'] = task.get('mode', 'all')
                result['elapsed'] = round(time.monotonic() - started, 3)
                if result.get('ok'):
                    archive = folder / 'compiled.zip'
                    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
                        for path in working.rglob('*'):
                            if path.is_file():
                                output.write(path, str(Path(working.name) / path.relative_to(working)))
                    result['outputAvailable'] = True
                    task['lastSuccessfulRun'] = working.parent.name
                with self.lock:
                    task.update(status='passed' if result['ok'] else 'failed', result=result,
                                phase='编译通过' if result['ok'] else '编译失败，请查看日志与建议')
                    self._persist(task)
            except Exception as error:
                from gui.compiler_runner import diagnostics
                message = 'Error: ' + str(error)
                with log.open('a', encoding='utf-8') as stream:
                    stream.write('\n' + message + '\n')
                with self.lock:
                    task.update(status='failed', phase='任务失败', error=str(error), result={
                        'ok': False, 'stages': [], 'diagnostics': diagnostics(message),
                        'elapsed': round(time.monotonic() - started, 3), 'outputAvailable': False})
                    self._persist(task)

    def log(self, identity):
        with self.lock:
            self._task(identity)
            path = self.root / identity / 'compile.log'
            if not path.exists():
                return {'text': ''}
            with path.open('rb') as stream:
                size = path.stat().st_size
                if size > 2 * 1024**2:
                    stream.seek(size - 2 * 1024**2)
                text = stream.read().decode('utf-8', errors='replace')
            return {'text': ('（显示日志末尾，完整日志可下载）\n' if size > 2 * 1024**2 else '') + text}

    def download(self, identity, kind):
        with self.lock:
            task = self._task(identity)
            if kind not in ('log', 'output'):
                raise ValueError('不支持的下载类型')
            if kind == 'output' and not (task.get('result') or {}).get('outputAvailable'):
                raise ValueError('本次没有完整编译产物')
            path = self.root / identity / ('compile.log' if kind == 'log' else 'compiled.zip')
            if not path.is_file():
                raise ValueError('文件尚未生成')
            return path

    def add_file(self, identity, name, raw):
        relative = relative_file(name)
        with self.lock:
            task = self._task(identity)
            if task['status'] != 'uploading':
                raise ValueError('上传已经结束，不能修改编译输入')
            if len(task['files']) >= 20000 or task['bytes'] + len(raw) > 2 * 1024**3:
                raise ValueError('每个程序最多 20000 个文件、2 GiB')
            if name.casefold() in {p.casefold() for p in task['files']}:
                raise ValueError('上传包含重复文件路径')
            target = self.root / identity / 'source' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            task['files'].append(name)
            task['bytes'] += len(raw)
            return {'id': identity, 'files': len(task['files'])}

    def ready(self, payload):
        with self.lock:
            task = self._task(payload.get('id'))
            if task['status'] != 'uploading':
                raise ValueError('任务已结束上传')
            entries = [p for p in task['files'] if PurePosixPath(p).suffix.lower() in ('.pln', '.prj')]
            if len(entries) != 1:
                raise ValueError('每个文件夹必须包含唯一的 PLN 或 PRJ 入口；多个程序请分别添加')
            entry = entries[0]
            if '/' in entry:
                raise ValueError('请直接选择包含 PLN 或 PRJ 入口的程序文件夹')
            task.update(entry=entry, platform='chroma' if entry.lower().endswith('.pln') else 's100',
                        status='ready', phase='等待编译')
            self._persist(task)
            return deepcopy(task)
