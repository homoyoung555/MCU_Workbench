"""Immutable HEX uploads, a serial conversion queue, and downloadable results."""
from copy import deepcopy
import json
import re
from pathlib import Path
import secrets
import threading
import time
import zipfile

from gui.hex_conversion import convert_hex, parse_hex, prepare_hex, configured_profile, profiles


class HexWorkspace:
    def __init__(self, root, runner=None):
        self.root = Path(root)
        self.tasks = {}
        self.lock = threading.RLock()
        self.runner = runner or convert_hex
        for path in sorted(self.root.glob('*/task.json'), key=lambda p: p.stat().st_mtime):
            try:
                task = json.loads(path.read_text(encoding='utf-8'))
                if task['id'] != path.parent.name or task.get('archived'):
                    continue
                if task['status'] in ('running', 'queued'):
                    task.update(status='failed', error='上次转换中断，请重试')
                self.tasks[task['id']] = task
            except (ValueError, KeyError, OSError):
                continue

    def _persist(self, task):
        path = self.root/task['id']/'task.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    def state(self):
        with self.lock:
            return {'profiles': profiles(), 'tasks': deepcopy(list(self.tasks.values())),
                    'running': any(t['status'] in ('queued', 'running') for t in self.tasks.values())}

    def add_input(self, raw, name):
        from gui.server import safe_name
        if not name.lower().endswith('.hex'):
            raise ValueError('请选择 Intel HEX 文件')
        image = parse_hex(raw)
        with self.lock:
            identity = secrets.token_hex(12)
            folder = self.root/identity
            folder.mkdir(parents=True, exist_ok=False)
            (folder/'input.hex').write_bytes(raw)
            task = {'id': identity, 'name': safe_name(name), 'bytes': len(raw), 'status': 'ready',
                    'summary': image['summary'], 'profileId': None, 'result': None, 'error': None, 'logs': []}
            self.tasks[identity] = task
            self._persist(task)
            return deepcopy(task)

    def start(self, payload):
        with self.lock:
            if self.state()['running']:
                raise ValueError('HEX 转换队列正在运行')
            ids = payload.get('taskIds')
            if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in self.tasks for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('请选择有效的 HEX 任务')
            profile = configured_profile(payload.get('profileId'), payload)
            for identity in ids:
                task = self.tasks[identity]
                # Validate every task before queuing any: do not partially start a batch.
                prepare_hex(parse_hex((self.root/identity/'input.hex').read_bytes()), profile)
            for identity in ids:
                task = self.tasks[identity]
                task.update(status='queued', profileId=profile['id'], profile=deepcopy(profile), result=None, error=None, logs=[])
                self._persist(task)
            threading.Thread(target=self._execute, args=(ids, deepcopy(profile)), daemon=True).start()
            return self.state()

    def _execute(self, ids, profile):
        for identity in ids:
            with self.lock:
                task = self.tasks[identity]
                task['status'] = 'running'
                run = self.root/identity/('run-' + secrets.token_hex(8))
                output = run/'output'
                output.mkdir(parents=True)
                task['run'] = run.name
                self._persist(task)
            def progress(message):
                with self.lock:
                    task['logs'].append(str(message))
                    task['logs'] = task['logs'][-300:]
            try:
                result = self.runner((self.root/identity/'input.hex').read_bytes(), profile, output, task['name'], progress)
                metadata = {'input':task['name'], 'inputSha256':task['summary']['sha256'],
                            'profile':profile, 'conversion':result.get('summary'),
                            'notice':'仅生成 Pattern，未执行机台下载或硬件验证'}
                (output/'conversion.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
                archive = run/'output.zip'
                with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
                    for file in result['files']:
                        path = (output/file['name']).resolve()
                        path.relative_to(output.resolve())
                        package.write(path, path.name)
                    package.write(output/'conversion.json', 'conversion.json')
                with self.lock:
                    task.update(status='completed', result=result)
            except Exception as error:
                with self.lock:
                    task.update(status='failed', error=str(error))
                    progress('转换失败：' + str(error))
            finally:
                with self.lock:
                    self._persist(task)

    def _completed(self, identity):
        task = self.tasks.get(identity)
        if not task or task['status'] != 'completed':
            raise ValueError('请先成功完成转换')
        run = (self.root/identity/task['run']).resolve()
        run.relative_to((self.root/identity).resolve())
        return task, run

    def download(self, identity):
        with self.lock:
            _, run = self._completed(identity)
            return run/'output.zip'

    def snapshot(self, identity, version):
        """Freeze exactly the completed run the program Link dialog displayed."""
        with self.lock:
            task, run = self._completed(identity)
            if task['run'] != version:
                raise ValueError('HEX 生成版本已变化，请刷新后重新选择')
            contents = {}
            pattern = None
            with zipfile.ZipFile(run/'output.zip') as archive:
                for entry in task['result']['files']:
                    name = entry['name']
                    path = (run/'output'/name).resolve()
                    path.relative_to((run/'output').resolve())
                    platform = {'.pat': 'chroma', '.sd': 's100'}.get(path.suffix.lower())
                    if not platform or platform in contents:
                        raise ValueError('HEX 每个平台必须只有一个 Pattern 文件')
                    raw = path.read_bytes()
                    if raw != archive.read(name):
                        raise ValueError('HEX 产物已修改，请重新转换')
                    text = raw.decode('utf-8-sig')
                    if platform == 'chroma':
                        names = re.findall(r'\bSPM_PATTERN\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)', text)
                        if len(names) != 1:
                            raise ValueError('HEX Pattern 声明无效')
                        pattern = names[0]
                    elif any(not re.search(r'^\s*' + label + r'\s*:', text, re.M) for label in ('START', 'END')):
                        raise ValueError('HEX S100 产物缺少 START / END 标签')
                    contents[platform] = text.encode('gb18030')
            if not contents:
                raise ValueError('HEX 生成结果没有 Pattern')
            return {'pattern': pattern or Path(task['result']['files'][0]['name']).stem,
                    'contents': contents, 'source': {'taskId': identity, 'run': version,
                    'name': task['name'], 'profile': deepcopy(task['profile']),
                    'inputSha256': task['summary']['sha256']}}

    def preview(self, identity, filename):
        with self.lock:
            task, run = self._completed(identity)
            if filename not in [item['name'] for item in task['result']['files']]:
                raise ValueError('输出文件不存在')
            path = (run/'output'/filename).resolve()
            path.relative_to((run/'output').resolve())
            with path.open(encoding='utf-8-sig') as stream:
                return stream.read(100000)

    def clear(self, payload=None):
        with self.lock:
            if self.state()['running']:
                raise ValueError('请等待转换完成后清空历史')
            for task in self.tasks.values():
                task['archived'] = True
                self._persist(task)
            self.tasks.clear()
            return self.state()
