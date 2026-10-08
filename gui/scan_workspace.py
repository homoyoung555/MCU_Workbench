"""Owned SCAN jobs, immutable inputs and explicit workbook resource associations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import threading
import time


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def configuration_cps(workbook):
    frame = workbook.dataframe('PIN DEC')
    column = next((c for c in frame.columns if str(c).strip().casefold() in ('cp no', 'cp num')), None)
    return list(dict.fromkeys(str(v).strip() for v in frame[column].dropna() if str(v).strip())) if column else []


class ScanWorkspace:
    def __init__(self, session):
        self.session = session
        self.root = session.output / 'scan'
        self.inputs = {}
        self.configuration = None
        self.job = None
        self.jobs = {}
        self._candidate_cache = None
        self._association_key = None
        self.associations = []
        self._persist_lock = threading.Lock()

    def _name(self, value, suffix):
        from gui.server import safe_name
        name = safe_name(value)
        if not name.lower().endswith(suffix):
            raise ValueError('请选择 ' + suffix + ' 文件')
        return name

    def add_input(self, raw, name):
        name = self._name(name, '.wgl')
        if not raw:
            raise ValueError('WGL 文件为空')
        identity = next((k for k, v in self.inputs.items() if v['name'].casefold() == name.casefold()
                         and not v.get('originalPath')), secrets.token_hex(12))
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / 'imports' / identity / digest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
        record = {'id': identity, 'name': name, 'size': len(raw), 'sha256': digest, 'path': str(path.resolve())}
        self.inputs[identity] = record
        return self._public_input(record)

    def register_paths(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 100 or any(not isinstance(p, str) for p in paths):
            raise ValueError('请选择 1–100 个 WGL 文件')
        records = []
        for value in paths:
            path = Path(value).resolve(strict=True)
            name = self._name(path.name, '.wgl')
            if not path.is_file() or not 0 < path.stat().st_size <= 256 * 1024**2:
                raise ValueError('WGL 文件为空或超过 256 MB')
            identity = next((k for k, v in self.inputs.items() if v.get('originalPath') == str(path)), secrets.token_hex(12))
            record = {'id': identity, 'name': name, 'size': path.stat().st_size,
                      'sha256': file_hash(path), 'path': str(path), 'originalPath': str(path)}
            self.inputs[identity] = record
            records.append(self._public_input(record))
        return {'inputs': records}

    @staticmethod
    def _public_input(record):
        return {k: v for k, v in record.items() if k != 'path'}

    def set_configuration(self, raw, name):
        from program_gen.workbook import WorkbookReader
        name = self._name(name, '.xlsx')
        workbook = WorkbookReader(byte_loader=lambda _: raw).read(name)
        self.configuration = {'name': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                              'cps': configuration_cps(workbook), 'workbook': workbook, 'raw': raw}
        return {k: self.configuration[k] for k in ('name', 'sha256', 'cps')}

    def candidate(self, draft=None):
        from gui.server import fingerprint
        from program_gen.workbook import WorkbookReader
        editor = self.session.editor
        if editor is None:
            raise ValueError('请先打开程序 Excel，或选择其他程序 Excel')
        if draft is None or isinstance(draft, dict) and draft.get('baseSha256') == '' and not draft.get('changes'):
            draft = {'baseSha256': editor.sha256, 'changes': []}
        if not isinstance(draft, dict):
            raise ValueError('程序配置快照格式无效')
        key = (id(editor), fingerprint(draft))
        editor.ensure_source_current()
        if not self._candidate_cache or self._candidate_cache[0] != key:
            raw = editor.apply(draft.get('baseSha256'), draft.get('changes'), draft.get('appendRows', []),
                               draft.get('flowOrder', []), draft.get('trimStorageMappings'),
                               draft.get('verifyStorageMappings'), draft.get('patternEdits'), draft.get('patternLinks'))
            workbook = self.session.base_workbook if raw == editor.raw else WorkbookReader(byte_loader=lambda _: raw).read(editor.name)
            self._candidate_cache = (key, workbook, raw)
        return self._candidate_cache[1:]

    def _load_associations(self):
        key = self.session.editor.sha256 if self.session.editor else None
        if key == self._association_key:
            return
        self._association_key, self.associations = key, []
        if key:
            path = self.root / 'bindings' / (key + '.json')
            if path.is_file():
                value = json.loads(path.read_text(encoding='utf-8'))
                self.associations = value['associations']
                for binding in self.associations:
                    if not isinstance(binding.get('jobId'), str) or len(binding['jobId']) != 32 or any(c not in '0123456789abcdef' for c in binding['jobId']):
                        raise ValueError('SCAN 关联记录无效')
                    job_file = self.root / binding['jobId'] / 'job.json'
                    if job_file.is_file():
                        job = json.loads(job_file.read_text(encoding='utf-8'))
                        self.jobs[job['id']] = job
                        for source in job.get('sources', []):
                            self.inputs.setdefault(source['id'], source)
                        if not self.job or self.job['status'] != 'running':
                            self.job = job

    def persist(self, workbook_sha=None):
        key = workbook_sha or self._association_key
        if not key or not self.associations:
            return
        path = self.root / 'bindings' / (key + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        with self._persist_lock:
            temporary.write_text(json.dumps({'version': 1, 'associations': self.associations}, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)

    def _stale_reason(self, job, draft=None):
        if job.get('status') != 'completed':
            return ''
        for source in job['sources']:
            path = Path(source.get('originalPath') or source['path'])
            current = self.inputs.get(source['id'])
            if not path.is_file() or file_hash(path) != source['sha256']:
                return 'WGL 源文件已修改或不可用，需要重新转换'
            if current and not source.get('originalPath') and current['sha256'] != source['sha256']:
                return '重新导入的 WGL 已变化，需要重新转换'
        for output in job.get('result', {}).get('files', []):
            path = Path(job['outputRoot']) / output['path']
            if not path.is_file() or file_hash(path) != output['sha256']:
                return '转换产物已修改或丢失，需要重新转换'
        if job.get('adapt'):
            if job['source'] == 'current':
                if not self.session.editor:
                    return '请打开转换所用的程序配置'
                from gui.scan_conversion import configuration_fingerprint
                workbook, _ = self.candidate(draft)
                if configuration_fingerprint(workbook, job.get('cp')) != job['configurationFingerprint']:
                    return '程序管脚或相关配置已变化，需要重新转换'
            elif self.configuration:
                from gui.scan_conversion import configuration_fingerprint
                if configuration_fingerprint(self.configuration['workbook'], job.get('cp')) != job['configurationFingerprint']:
                    return '另选的程序配置已变化，需要重新转换'
        return ''

    def _binding_reason(self, binding, draft=None):
        job = self.jobs.get(binding['jobId'])
        if not job:
            return '关联转换记录不可用，请重新转换并关联'
        reason = self._stale_reason(job, draft)
        if reason:
            return reason
        from gui.scan_conversion import configuration_fingerprint
        workbook, _ = self.candidate(draft)
        if configuration_fingerprint(workbook, binding['cp']) != binding.get('configurationFingerprint'):
            return '关联测试项的程序管脚或相关配置已变化，需要重新转换'
        return ''

    def state(self, draft=None):
        self._load_associations()
        job = deepcopy(self.job)
        if job:
            try:
                reason = self._stale_reason(job, draft)
            except (ValueError, OSError, KeyError) as error:
                reason = str(error)
            job.update(stale=bool(reason), reason=reason)
            job.pop('sources', None)
        editor = self.session.editor
        cps = configuration_cps(self.session.base_workbook) if editor else []
        associations = deepcopy(self.associations)
        for binding in associations:
            try:
                reason = self._binding_reason(binding, draft)
            except (ValueError, KeyError, OSError) as error:
                reason = str(error)
            binding.update(stale=bool(reason), reason=reason)
        return {'program': {'loaded': editor is not None, 'name': editor.name if editor else '',
                            'sha256': editor.sha256 if editor else '', 'cps': cps},
                'scan': {'inputs': [self._public_input(v) for v in self.inputs.values()],
                         'configuration': ({k: self.configuration[k] for k in ('name', 'sha256', 'cps')}
                                           if self.configuration else None),
                         'job': job, 'associations': associations}}

    def pins(self, payload):
        from gui.scan_conversion import read_wgl_pins
        ids = payload.get('inputIds')
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or any(i not in self.inputs for i in ids):
            raise ValueError('请选择当前已导入的 WGL 文件')
        inputs, union, seen = [], [], set()
        for identity in ids:
            record = self.inputs[identity]
            pins = read_wgl_pins(Path(record['path']))
            inputs.append({'id': identity, 'name': record['name'], 'pins': pins})
            for pin in pins:
                if pin.casefold() not in seen:
                    union.append(pin)
                    seen.add(pin.casefold())
        return {'pins': union, 'inputs': inputs}

    def start(self, payload, *, refresh_associations=True):
        self._load_associations()
        if self.job and self.job['status'] == 'running':
            raise ValueError('已有 SCAN 转换任务正在运行')
        ids, platforms = payload.get('inputIds'), payload.get('platforms')
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or any(i not in self.inputs for i in ids):
            raise ValueError('请选择当前已导入的 WGL 文件')
        if not isinstance(platforms, list) or not platforms or len(platforms) != len(set(platforms)) or any(p not in ('chroma', 's100') for p in platforms):
            raise ValueError('请选择 Chroma 或 S100 平台')
        names = [self.inputs[i]['name'].casefold() for i in ids]
        if len(set(names)) != len(names):
            raise ValueError('同批转换不能包含同名 WGL，请分别转换或修改源文件名称')
        adapt, source, workbook, config_raw, config_sha = payload.get('adapt', False), payload.get('source', 'current'), None, None, None
        if type(adapt) is not bool or source not in ('current', 'other'):
            raise ValueError('适配配置选项无效')
        manual_pins = deepcopy(payload.get('manualPins'))
        if manual_pins is not None and adapt:
            raise ValueError('手动管脚与 Excel 适配不能同时启用')
        from gui.scan_conversion import label_options
        label_marker, label_base = label_options(payload.get('labelMarker'), payload.get('labelBase'))
        cp = payload.get('cp') if adapt else None
        if adapt:
            from gui.scan_conversion import configuration_fingerprint
            if source == 'current':
                workbook, config_raw = self.candidate(payload.get('draft'))
            else:
                if self.configuration is None:
                    raise ValueError('请先选择适配程序 Excel')
                workbook, config_raw = self.configuration['workbook'], self.configuration['raw']
            config_sha = configuration_fingerprint(workbook, cp)
        identity = secrets.token_hex(16)
        folder = self.root / identity
        input_dir = folder / 'input'
        input_dir.mkdir(parents=True, exist_ok=False)
        sources, paths = [], []
        for key in ids:
            record = deepcopy(self.inputs[key])
            snapshot = input_dir / record['name']
            shutil.copyfile(record['path'], snapshot)
            record['sha256'] = file_hash(snapshot)
            record['size'] = snapshot.stat().st_size
            sources.append(record)
            paths.append(snapshot)
        if manual_pins is not None:
            from gui.scan_conversion import manual_pin_orders
            manual_pin_orders(paths, manual_pins)
        if config_raw:
            (input_dir / 'program.xlsx').write_bytes(config_raw)
        job = {'id': identity, 'status': 'running', 'logs': [], 'sources': sources,
               'inputIds': ids, 'platforms': platforms, 'adapt': adapt, 'source': source, 'cp': cp,
               'manualPins': manual_pins,
               'labelMarker': label_marker, 'labelBase': label_base,
               'configurationFingerprint': config_sha,
               'programSha': self.session.editor.sha256 if self.session.editor else None,
               'outputRoot': str((folder / 'output').resolve()), 'createdAt': time.strftime('%Y-%m-%d %H:%M:%S')}
        association_key = self._association_key
        refreshed_fingerprints = {}
        if refresh_associations and self.associations and self.session.editor:
            from gui.scan_conversion import configuration_fingerprint
            target_workbook, _ = self.candidate(payload.get('draft'))
            refreshed_fingerprints = {binding['cp']: configuration_fingerprint(target_workbook, binding['cp']) for binding in self.associations}

        self.job = job
        self.jobs[identity] = job

        def progress(message):
            job['logs'].append(str(message))
            job['logs'] = job['logs'][-500:]

        def execute():
            try:
                from gui.scan_conversion import convert_scan
                result = convert_scan(paths, Path(job['outputRoot']), platforms, workbook=workbook, progress=progress, cp=cp,
                                      manual_pins=manual_pins, label_marker=label_marker, label_base=label_base)
                for entry in result['files']:
                    path = (Path(job['outputRoot']) / entry['path']).resolve()
                    relative = path.relative_to(Path(job['outputRoot']))
                    entry.update(path=relative.as_posix(), sha256=file_hash(path), size=path.stat().st_size)
                job.update(status='completed', result=result)
                # Refresh explicit links only for the same source set and target coverage.
                for binding in self.associations if refresh_associations and self._association_key == association_key else []:
                    old = self.jobs.get(binding['jobId'])
                    if (old and old['inputIds'] == ids and set(old['platforms']).issubset(platforms)
                            and old['adapt'] == adapt and old['source'] == source and old.get('cp') == cp
                            and old.get('manualPins') == manual_pins and old.get('labelMarker') == label_marker
                            and old.get('labelBase') == label_base):
                        binding['jobId'] = identity
                        binding['configurationFingerprint'] = refreshed_fingerprints[binding['cp']]
                        self.session.checked = None
            except Exception as error:
                job.update(status='failed', error=str(error))
                progress('转换失败：' + str(error))
            finally:
                (folder / 'job.json').write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
                if self._association_key == association_key:
                    self.persist()
        threading.Thread(target=execute, daemon=True).start()
        return {'jobId': identity}

    def targets(self, draft=None):
        workbook, _ = self.candidate(draft)
        frame = workbook.dataframe('FLOW')
        targets = []
        for index, row in frame.iterrows():
            if str(row.get('type', '')).strip().lower() == 'verify' and str(row.get('mode', '')).strip().lower() in ('scan', 'mbist'):
                targets.append({'row': int(index) + 2, 'cp': str(row['CP NO']).strip(),
                                'item': str(row['item']).strip(), 'kind': str(row['mode']).strip().lower()})
        return {'targets': targets}

    def link(self, payload):
        self._load_associations()
        job = self.jobs.get(payload.get('jobId'))
        if not job or job['status'] != 'completed':
            raise ValueError('请先完成转换')
        reason = self._stale_reason(job, payload.get('draft'))
        if reason:
            raise ValueError(reason)
        target = next((r for r in self.targets(payload.get('draft'))['targets'] if r['row'] == payload.get('row')), None)
        if not target:
            raise ValueError('请选择当前程序中的 SCAN / MBIST 测试项')
        from gui.scan_conversion import configuration_fingerprint
        workbook, _ = self.candidate(payload.get('draft'))
        target_fingerprint = configuration_fingerprint(workbook, target['cp'])
        if job['adapt']:
            if target_fingerprint != job['configurationFingerprint']:
                raise ValueError('转换配置与目标程序配置不一致，请按当前配置重新转换后关联')
        identity = tuple(target[k] for k in ('cp', 'item', 'kind'))
        self.associations = [a for a in self.associations if tuple(a[k] for k in ('cp', 'item', 'kind')) != identity]
        self.associations.append({**target, 'jobId': job['id'], 'configurationFingerprint': target_fingerprint})
        self.persist()
        self.session.checked = None
        return self.state(payload.get('draft'))['scan']

    def require_current(self, draft=None, cps=None):
        self._load_associations()
        active = {(t['cp'], t['item'], t['kind']) for t in self.targets(draft)['targets']} if self.associations else set()
        for binding in self.associations:
            if (binding['cp'], binding['item'], binding['kind']) not in active or cps is not None and binding['cp'] not in cps:
                continue
            reason = self._binding_reason(binding, draft)
            if reason:
                raise ValueError(binding['item'] + '：' + reason)

    def freeze(self, draft=None, cps=None):
        """Read validated output bytes before preview/generation leaves the request lock."""
        from program_gen.core.scan_test import ScanArtifact, ScanArtifactBinding, ScanBindingSet
        self.require_current(draft, cps)
        active = {(t['cp'], t['item'], t['kind']) for t in self.targets(draft)['targets']} if self.associations else set()
        bindings = []
        for binding in self.associations:
            if (binding['cp'], binding['item'], binding['kind']) not in active or cps is not None and binding['cp'] not in cps:
                continue
            job = self.jobs[binding['jobId']]
            artifacts = []
            for file in job['result']['files']:
                raw = self.output_file(job['id'], file['path']).read_bytes()
                if hashlib.sha256(raw).hexdigest() != file['sha256']:
                    raise ValueError('转换产物在读取期间发生变化，请重新转换')
                artifacts.append(ScanArtifact(file['platform'], file['kind'], file['logicalName'], raw))
            bindings.append(ScanArtifactBinding(binding['cp'], binding['item'], 'VERIFY_' + binding['kind'].upper(),
                                                binding['configurationFingerprint'], tuple(artifacts)))
        return ScanBindingSet(tuple(bindings))

    def output_file(self, identity, filename):
        job = self.jobs.get(identity)
        if not job or job.get('status') != 'completed':
            raise ValueError('转换结果不存在')
        entry = next((f for f in job['result']['files'] if f['path'] == filename), None)
        if not entry:
            raise ValueError('结果中没有此文件')
        path = (Path(job['outputRoot']) / entry['path']).resolve()
        path.relative_to(Path(job['outputRoot']))
        return path
