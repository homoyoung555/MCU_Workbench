"""Local multi-sheet editor and full-program review generation service."""
import argparse
import codecs
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gui.workbook_editor import WorkbookEditor, sha
from program_gen.workbook import WorkbookReader
from program_gen.compiler import ProductCompiler
from gui.test_groups import copy_groups
from gui.links import pattern_links, selected_storage_fields

from gui.paths import RESOURCE_ROOT, WORKSPACE_ROOT
WORKSPACE = WORKSPACE_ROOT
OUTPUT = WORKSPACE / 'outputs/gui_runs'
MASTER = WORKSPACE / 'input/workbook/program_PCD009_V1.0.xlsx'
TEXT_TYPES = {'.pln', '.prg', '.pat', '.dec', '.sd', '.h', '.c', '.cpp',
              '.txt', '.json', '.prj', '.sr', '.ini', '.tim', '.lev', '.xml', '.csv'}


def preview_text(raw):
    truncated = len(raw) > 512 * 1024
    raw = raw[:512 * 1024]
    if b'\x00' in raw:
        raise ValueError('该文件不是支持的文本格式')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            content = codecs.getincrementaldecoder(encoding)().decode(raw, final=not truncated)
            return {'text': content, 'encoding': encoding, 'truncated': truncated, 'bytesShown': len(raw)}
        except UnicodeDecodeError:
            continue
    raise ValueError('无法识别文本编码')


def fingerprint(payload):
    return sha(json.dumps({'baseSha256': payload.get('baseSha256'), 'changes': payload.get('changes'),
                          'appendRows': payload.get('appendRows', []), 'flowOrder': payload.get('flowOrder', []), 'patternEdits': payload.get('patternEdits', []), 'patternLinks': payload.get('patternLinks'),
                          'trimStorageMappings': payload.get('trimStorageMappings'), 'verifyStorageMappings': payload.get('verifyStorageMappings')},
                          sort_keys=True, ensure_ascii=False, allow_nan=False).encode())


def generation_key(payload):
    return sha((str(payload.get('checkId')) + str(payload.get('scope', 'program'))
                + json.dumps(payload.get('targets'), sort_keys=True)).encode())


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(name).name)[:120].rstrip('. ') or 'workbook.xlsx'


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        try:
            stream.write(raw)
            stream.flush()
        except BaseException:
            stream.close()
            path.unlink()
            raise


def effective_copy_editor(editor, append_rows, flow_order):
    """Map canonical appendable FLOW sources to their physical post-sort rows."""
    flow = editor.by_name['FLOW']
    allowed = set(flow['appendableRows'])
    if flow_order:
        allowed = {destination for destination, source in enumerate(flow_order, 1) if source in allowed}
    return SimpleNamespace(by_name={**editor.by_name, 'FLOW': {**flow, 'appendableRows': sorted(allowed)}})


class Session:
    def __init__(self, master=MASTER, output=OUTPUT):
        self.output, self.checked, self.job = Path(output), None, None
        self.editor = None
        if master is not None:
            self.load(master.read_bytes(), master.name, master)

    def compile(self, raw):
        workbook = WorkbookReader(byte_loader=lambda _: raw).read(WORKSPACE / 'scratch/gui-inputs' / self.editor.name)
        return workbook, ProductCompiler().compile(workbook)

    def load(self, raw, name, source=None):
        editor = WorkbookEditor(raw, name, source)
        workbook = WorkbookReader(byte_loader=lambda _: raw).read(WORKSPACE / 'scratch/gui-inputs' / editor.name)
        compilation = ProductCompiler().compile(workbook)
        from gui.generation import available_targets, available_pin_targets
        targets = available_targets(workbook, compilation) if compilation.is_valid else []
        diagnostics = [asdict(d) for d in compilation.diagnostics.items]
        groups = copy_groups(compilation, editor)
        self.editor, self.checked = editor, None
        self.base_workbook = workbook
        self.base_firmware_plans = compilation.plan.catalogs.firmware_test_plans if compilation.is_valid else {}
        from gui.pattern_editor import pattern_items
        from gui.fb_mapping import _targets
        import fb_map
        self.pattern_items = pattern_items(editor)
        try:
            self.pattern_target_options = _targets(fb_map.build_index_from_workbook(workbook))
        except ValueError:
            self.pattern_target_options = []
        self.base_diagnostics, self.targets = diagnostics, targets
        self.pin_targets = available_pin_targets(workbook)
        self.groups = groups
        self.links = pattern_links(compilation, editor, workbook.dataframe('FLOW'), workbook)
        self.item_cache = {'key': fingerprint({'baseSha256': editor.sha256, 'changes': [],
                                              'patternLinks': editor.pattern_links, 'trimStorageMappings': editor.trim_storage_mappings, 'verifyStorageMappings': editor.verify_storage_mappings}),
                           'workbook': workbook, 'compilation': compilation}
        return self.state()

    def state(self):
        from gui.generation import available_fbist_targets, available_flash_targets, available_flash_label_targets, available_pump_targets
        if self.editor is None:
            return {'loaded': False, 'name': '', 'sha256': '', 'sheets': [], 'targets': [],
                    'groups': [], 'links': {}, 'diagnostics': [], 'pinTargets': [],
                    'patternItems': [], 'patternTargets': [], 'trimStorageMappings': [],
                    'verifyStorageMappings': [], 'outputRoot': str(self.output), 'jobId': None}
        return {'loaded': True, 'name': self.editor.name, 'sha256': self.editor.sha256, 'sheets': self.editor.sheets,
                'patternLinks': self.editor.pattern_links, 'trimStorageMappings': self.editor.trim_storage_mappings, 'verifyStorageMappings': self.editor.verify_storage_mappings,
                'patternItems': self.pattern_items, 'patternTargets': self.pattern_target_options,
                'fbistTargets': available_fbist_targets(),
                'flashTargets': available_flash_targets(),
                'flashLabelTargets': available_flash_label_targets(),
                'pumpTargets': available_pump_targets(),
                'targets': self.targets, 'pinTargets': self.pin_targets, 'diagnostics': self.base_diagnostics, 'outputRoot': str(self.output),
                'groups': self.groups, 'links': self.links, 'jobId': self.job['id'] if self.job else None}

    def new_flow_item(self, payload):
        from gui.flow_new_item import new_flow_item
        return new_flow_item(self, payload)

    def storage_mapping(self, payload):
        """Validate one physical-field click in the same compilation boundary as generation."""
        from program_gen.core.logical_item import logical_item_key
        from program_gen.core.project_mappings import verify_storage_sources
        editor, row = self.editor, payload.get('row')
        if type(row) is not int or row < 2:
            raise ValueError('请选择 TRIM / VERIFY 的 FLOW 行')
        raw = editor.apply(payload.get('baseSha256'), payload.get('changes'),
                           payload.get('appendRows', []), payload.get('flowOrder', []),
                           payload.get('trimStorageMappings'), payload.get('verifyStorageMappings'), payload.get('patternEdits'), payload.get('patternLinks'))
        key = fingerprint(payload)
        cached = getattr(self, 'item_cache', None)
        if cached and cached['key'] == key:
            workbook, compiled = cached['workbook'], cached['compilation']
        else:
            workbook, compiled = self.compile(raw)
        if not compiled.is_valid:
            # A new TRIM needs this picker to resolve its missing storage binding.
            # Prepare options with a temporary opt-out; never persist it here.
            frame = workbook.dataframe('FLOW')
            if row - 2 in frame.index:
                record = frame.loc[row - 2]
                item = str(record.get('item', '')).strip()
                mappings = payload.get('trimStorageMappings', editor.trim_storage_mappings)
                errors = compiled.diagnostics.errors
                if (str(record.get('type', '')).strip().casefold() == 'trim'
                        and not any(logical_item_key(m['item']) == logical_item_key(item) for m in mappings)
                        and errors and all(item in d.message and '在 ADDR_MAP 中没有适用字段' in d.message for d in errors)):
                    prepared = editor.apply(payload.get('baseSha256'), payload.get('changes'),
                        payload.get('appendRows', []), payload.get('flowOrder', []),
                        [*mappings, {'item': item, 'targets': []}], payload.get('verifyStorageMappings'), payload.get('patternEdits'), payload.get('patternLinks'))
                    workbook, compiled = self.compile(prepared)
        if not compiled.is_valid:
            raise ValueError('请先修正当前工作簿的编译错误：' +
                             '；'.join(d.message for d in compiled.diagnostics.errors[:3]))
        catalogs, flow = compiled.plan.catalogs, workbook.dataframe('FLOW')
        if row - 2 not in flow.index:
            raise ValueError('FLOW 行不存在')
        record = flow.loc[row - 2]
        kind, item, cp = (str(record.get(k, '')).strip() for k in ('type', 'item', 'CP NO'))
        kind = kind.upper()
        if kind == 'TRIM':
            spec = catalogs.trim_specs.get(row - 2)
            if spec is None:
                raise ValueError('当前行不是可映射的普通 TRIM')
            symbol = spec.dac_final_symbol
            related = [s for s in catalogs.trim_specs.values() if logical_item_key(s.item) == logical_item_key(item)]
        elif kind == 'VERIFY':
            exports = {p.flow_row_index: p for c in compiled.cp_plans.values() for p in c.result_export_plans.plans}
            sources = verify_storage_sources(flow, exports)
            source = next((p for p in sources if p.flow_row_index == row - 2), None)
            if source is None:
                raise ValueError('此 VERIFY 尚无可存储的测量结果格式；请先配置 RESULT EXPORT 的 BCD16_MV 或 ADC12_3V3 格式')
            symbol = source.symbol
            related = [s for s in sources if logical_item_key(s.item) == logical_item_key(item)]
        else:
            raise ValueError('请选择 TRIM / VERIFY 测试项')
        cps = list(dict.fromkeys(s.cp for s in related))

        def view(catalog):
            selected = selected_storage_fields(catalog, kind, cp, item)
            current = [{'page': f.page, 'register': f.register, 'field': f.name} for f in selected]
            options = [{'page': f.page, 'register': f.register, 'field': f.name,
                        'width': f.width, 'lsb': f.lsb, 'source': 'description' if f.source == 'description' else 'CP addr map',
                        'sourceRow': f.register_layout.row_index + 2}
                       for f in catalog.storage_fields if all(f.register_layout.applies_to(c) for c in cps)]
            return {'current': current, 'options': options}

        if 'targets' not in payload:
            editor.ensure_source_current()
            return {'row': row, 'kind': kind, 'cp': cp, 'cps': cps, 'item': item, 'symbol': symbol,
                    **view(catalogs.addr_map)}
        targets = payload['targets']
        if targets is not None and (not isinstance(targets, list) or len(targets) > 1000):
            raise ValueError('映射目标必须是字段数组；恢复导入映射使用 null')
        trim = payload.get('trimStorageMappings', editor.trim_storage_mappings)
        verify = payload.get('verifyStorageMappings', editor.verify_storage_mappings)
        mappings = trim if kind == 'TRIM' else verify
        mappings = [m for m in mappings if logical_item_key(m['item']) != logical_item_key(item)]
        if targets is not None:
            mappings.append({'item': item, 'targets': targets})
        if kind == 'TRIM':
            trim = mappings
        else:
            verify = mappings
        candidate = editor.apply(payload.get('baseSha256'), payload.get('changes'),
                                 payload.get('appendRows', []), payload.get('flowOrder', []), trim, verify, payload.get('patternEdits'), payload.get('patternLinks'))
        proposed_workbook, proposed = self.compile(candidate)
        editor.ensure_source_current()
        if self.editor is not editor:
            raise ValueError('母本已重新载入，请重新选择映射')
        result = {'valid': proposed.is_valid, 'trimStorageMappings': trim, 'verifyStorageMappings': verify,
                  'diagnostics': [asdict(d) for d in proposed.diagnostics.items]}
        if proposed.is_valid:
            self.item_cache = {'key': fingerprint({**payload, 'trimStorageMappings': trim, 'verifyStorageMappings': verify}),
                               'workbook': proposed_workbook, 'compilation': proposed}
            result.update(view(proposed.plan.catalogs.addr_map))
            result['links'] = pattern_links(proposed, WorkbookEditor(candidate, editor.name), proposed_workbook.dataframe('FLOW'), proposed_workbook)
        return result

    def fb_mapping(self, payload):
        if payload.get('patternEdits'):
            raise ValueError('Pattern结构已调整，请使用item编辑区中的FB写入选择，避免旧行号映射')
        from gui.fb_mapping import fb_mapping
        return fb_mapping(self, payload)

    def pattern_targets(self, payload):
        import fb_map
        from gui.fb_mapping import _targets
        # Read the current FB MAP draft without requiring an incomplete new
        # Pattern to be materializable or the entire program to compile.
        entries = payload.get('changes', [])
        if not isinstance(entries, list) or any(not isinstance(c, dict) for c in entries):
            raise ValueError('单元格修改格式错误')
        changes = [c for c in entries if c.get('sheet') == 'FB MAP']
        raw = self.editor.apply(payload.get('baseSha256'), changes)
        workbook = WorkbookReader(byte_loader=lambda _: raw).read('pattern-targets.xlsx')
        self.editor.ensure_source_current()
        return {'targets': _targets(fb_map.build_index_from_workbook(workbook))}

    def trim_pattern(self, payload):
        from gui.trim_pattern import trim_pattern
        return trim_pattern(self, payload)

    def item_preview(self, payload):
        from gui.item_preview import render_item_preview
        editor = self.editor
        editor.ensure_source_current()
        row, platform, variant = payload.get('row'), payload.get('platform'), payload.get('variant', 'lab')
        if type(row) is not int or row < 2 or platform not in ('chroma', 's100') or variant not in ('lab', 'production'):
            raise ValueError('请选择有效的FLOW行、平台与LAB／Production')
        if (not isinstance(payload.get('changes'), list) or not isinstance(payload.get('appendRows', []), list)
                or not isinstance(payload.get('flowOrder', []), list)):
            raise ValueError('改动、新增行和FLOW排序清单必须是数组')
        if row > editor.by_name.get('FLOW', {}).get('maxRow', 0) + sum(op['sheet']=='FLOW' for op in payload.get('appendRows', [])):
            raise ValueError('FLOW行超出当前草稿范围')
        key = fingerprint(payload)
        cached = getattr(self, 'item_cache', None)
        if not cached or cached['key'] != key:
            raw = editor.apply(payload.get('baseSha256'), payload['changes'], payload.get('appendRows', []),
                               payload.get('flowOrder', []), payload.get('trimStorageMappings'), payload.get('verifyStorageMappings'), payload.get('patternEdits'), payload.get('patternLinks'))
            workbook = WorkbookReader(byte_loader=lambda _: raw).read(WORKSPACE / 'scratch/gui-inputs' / editor.name)
            compiled = ProductCompiler().compile(workbook)
            cached = {'key': key, 'workbook': workbook, 'compilation': compiled}
        frame = cached['workbook'].dataframe('FLOW')
        record = frame.loc[row - 2] if row - 2 in frame.index else {}
        bindings = (self.scan.freeze(payload, {str(record.get('CP NO', '')).strip()})
                    if hasattr(self, 'scan') and str(record.get('mode', '')).strip().lower() in ('scan', 'mbist') else None)
        result = render_item_preview(cached['workbook'], cached['compilation'], row, platform, variant, scan_bindings=bindings)
        editor.ensure_source_current()
        if self.editor is not editor:
            raise ValueError('母本已重新载入，当前预览已过期')
        self.item_cache = cached  # One draft only; never grants save/generate permission.
        return {**result, 'row': row, 'snapshot': key}

    def output_preview(self, job_id, target_index, filename=None):
        job = self.job
        if not job or job['id'] != job_id or job['status'] == 'running' or not job.get('result'):
            raise ValueError('生成结果不可用，请打开当前已结束的任务')
        outputs = job['result']['outputs']
        if not target_index.isdecimal() or int(target_index) >= len(outputs):
            raise ValueError('生成目标不存在')
        target = outputs[int(target_index)]
        run = Path(job['result']['run_dir']).resolve()
        root = Path(target['path']).resolve()
        if (target.get('error') or run.parent != self.output.resolve()
                or not root.is_relative_to(run / 'review') or not root.is_dir()):
            raise ValueError('该目标没有可查看的输出目录')
        result = {'inputSha256': job['inputSha256'], 'target': target['id']}
        text_types = TEXT_TYPES
        if filename is None:
            files = []
            for directory, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()
                           and not (Path(directory) / name).is_junction()]
                for name in names:
                    path = Path(directory) / name
                    if path.is_file() and path.resolve().is_relative_to(root):
                        files.append({'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
                                      'previewable': path.suffix.lower() in text_types})
                        if len(files) > 10000:
                            raise ValueError('目标文件超过10000个，请通过输出目录查看')
            result['files'] = sorted(files, key=lambda f: (Path(f['path']).suffix.lower() not in {'.pln', '.prg'}, f['path'].casefold()))
            return result
        relative = Path(filename)
        path = (root / relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or ':' in filename or not path.is_relative_to(root):
            raise ValueError('只能查看当前生成目标内的文件')
        if not path.is_file() or path.suffix.lower() not in text_types:
            raise ValueError('文件不存在或不支持文本预览，请通过输出目录查看')
        with path.open('rb') as stream:
            raw = stream.read(512 * 1024 + 1)
        return {**result, 'path': filename, **preview_text(raw)}

    def preview(self, payload):
        from gui.generation import preview_plan
        checked, scope, ids = self.require_generation(payload)
        target = payload.get('target')
        if target not in ids:
            raise ValueError('请选择已检查且已勾选的预览目标')
        checked.pop('preview', None)
        plan = preview_plan(checked['workbook'], checked['compilation'], target, scope, scan_bindings=checked.get('scanBindings'), swd_bindings=checked.get('swdBindings'))
        self.editor.ensure_source_current()
        # ponytail: retain one target only; selecting another replaces this cache.
        identity = secrets.token_hex(16)
        checked['preview'] = {'id': identity, 'plan': plan}
        files = [{'path': a.relative_path, 'size': a.size,
                  'previewable': Path(a.relative_path).suffix.lower() in TEXT_TYPES} for a in plan.artifacts]
        files.sort(key=lambda f: (Path(f['path']).suffix.lower() not in {'.pln', '.prg'}, f['path'].casefold()))
        return {'previewId': identity, 'target': target, 'scope': scope, 'inputSha256': sha(checked['raw']),
                'files': files, 'releaseBlockers': list(plan.release_blockers)}

    def preview_file(self, identity, filename):
        self.editor.ensure_source_current()
        preview = self.checked.get('preview') if self.checked else None
        if not preview or preview['id'] != identity:
            raise ValueError('代码预览已过期，请重新检查并预览')
        if not filename or Path(filename).suffix.lower() not in TEXT_TYPES:
            raise ValueError('文件不存在或不支持文本预览')
        try:
            artifact = preview['plan'].artifact(filename)
        except KeyError:
            raise ValueError('文件不属于当前代码预览') from None
        return {'path': filename, **preview_text(artifact.content)}

    def check(self, payload):
        self.checked = None
        scope = payload.get('scope', 'program')
        if scope not in ('pin', 'program', 'fbist', 'flash', 'flash_labels', 'pump'):
            raise ValueError('检查范围应为整本、Pin、普通FBIST、Flash擦写/比较、Flash页／UID或PUMP汇总')
        if not isinstance(payload.get('appendRows', []), list) or not isinstance(payload.get('flowOrder', []), list):
            raise ValueError('新增行和FLOW排序清单必须是数组')
        raw = self.editor.apply(payload.get('baseSha256'), payload.get('changes'), payload.get('appendRows', []),
                                payload.get('flowOrder', []), payload.get('trimStorageMappings'), payload.get('verifyStorageMappings'), payload.get('patternEdits'), payload.get('patternLinks'))
        if scope in ('pin', 'fbist', 'flash', 'flash_labels', 'pump'):
            from gui.generation import (available_pin_targets, check_pin_targets, available_fbist_targets,
                                        check_fbist_targets, available_flash_targets, check_flash_targets,
                                        available_flash_label_targets, check_flash_label_targets, available_pump_targets, check_pump_targets)
            workbook = WorkbookReader(byte_loader=lambda _: raw).read(WORKSPACE / 'scratch/gui-inputs' / self.editor.name)
            diagnostics = {'pin': check_pin_targets, 'fbist': check_fbist_targets, 'flash': check_flash_targets, 'flash_labels': check_flash_label_targets, 'pump': check_pump_targets}[scope](workbook, payload.get('targets'))
            self.editor.ensure_source_current()
            choices = available_pin_targets(workbook) if scope == 'pin' else {'fbist': available_fbist_targets, 'flash': available_flash_targets, 'flash_labels': available_flash_label_targets, 'pump': available_pump_targets}[scope]()
            target_field = {'pin': 'pinTargets', 'fbist': 'fbistTargets', 'flash': 'flashTargets', 'flash_labels': 'flashLabelTargets', 'pump': 'pumpTargets'}[scope]
            identity = secrets.token_hex(16) if not diagnostics else None
            if identity:
                selected = [t for t in choices if t['id'] in payload['targets']]
                self.checked = {'id': identity, 'scope': scope, 'fingerprint': fingerprint(payload), 'raw': raw,
                                'workbook': workbook, 'compilation': None, 'saved': None, 'targets': [], target_field: selected}
            return {'scope': scope, 'checkId': identity, 'valid': not diagnostics, 'errors': len(diagnostics),
                    'warnings': 0, 'diagnostics': diagnostics, target_field: choices, 'checkedTargets': payload['targets'],
                    'changeCount': len(payload['changes']), 'appendCount': len(payload.get('appendRows', [])), 'sha256': sha(raw)}
        workbook, compiled = self.compile(raw)
        self.editor.ensure_source_current()
        from gui.generation import available_targets, available_pin_targets
        targets = available_targets(workbook, compiled) if compiled.is_valid else []
        pin_targets = available_pin_targets(workbook)
        identity = secrets.token_hex(16) if compiled.is_valid else None
        if identity:
            self.checked = {'id': identity, 'scope': 'program', 'fingerprint': fingerprint(payload), 'raw': raw,
                            'workbook': workbook, 'compilation': compiled, 'saved': None, 'targets': targets, 'pinTargets': pin_targets}
        return {'scope': 'program', 'checkId': identity, 'valid': compiled.is_valid, 'errors': len(compiled.diagnostics.errors),
                'groups': copy_groups(compiled, effective_copy_editor(self.editor, payload.get('appendRows', []), payload.get('flowOrder', []))),
                'links': pattern_links(compiled, WorkbookEditor(raw, self.editor.name), workbook.dataframe('FLOW'), workbook),
                'warnings': len(compiled.diagnostics.warnings), 'diagnostics': [asdict(d) for d in compiled.diagnostics.items],
                'targets': targets, 'pinTargets': pin_targets, 'changeCount': len(payload['changes']),
                'appendCount': len(payload.get('appendRows', [])), 'sha256': sha(raw)}

    def require_checked(self, payload, scope='program'):
        self.editor.ensure_source_current()
        if not self.checked or payload.get('checkId') != self.checked['id'] or fingerprint(payload) != self.checked['fingerprint']:
            raise ValueError('检查结果与当前草稿不匹配，请重新检查')
        if self.checked.get('scope', 'program') != scope:
            raise ValueError('检查范围不匹配：资源检查只授权对应资源输出，完整程序和另存检查结果需要整本检查')
        return self.checked

    def save(self, payload):
        checked = self.require_checked(payload)
        path = checked['saved']
        if path:
            if path.read_bytes() != checked['raw']:
                raise ValueError('已保存的副本被外部修改，请重新检查后另存')
        else:
            path = self.output / 'workbooks' / (checked['id'][:10] + '_' + safe_name(self.editor.name))
            write_new(path, checked['raw'])
            checked['saved'] = path
        if hasattr(self, 'scan'):
            self.scan.persist(sha(checked['raw']))
        if hasattr(self, 'swd'):
            self.swd.persist(sha(checked['raw']))
        return {'path': str(path.resolve()), 'sha256': sha(checked['raw'])}

    def save_draft(self, payload):
        """Save an unchecked copy through the same protected OOXML edit boundary."""
        if not isinstance(payload.get('appendRows', []), list) or not isinstance(payload.get('flowOrder', []), list):
            raise ValueError('新增行和FLOW排序清单必须是数组')
        raw = self.editor.apply(payload.get('baseSha256'), payload.get('changes'), payload.get('appendRows', []),
                                payload.get('flowOrder', []), payload.get('trimStorageMappings'), payload.get('verifyStorageMappings'), payload.get('patternEdits'), payload.get('patternLinks'))
        digest = sha(raw)
        name = re.sub(r'^DRAFT_UNCHECKED_[0-9A-F]{16}_', '', safe_name(self.editor.name))
        path = self.output / 'drafts' / ('DRAFT_UNCHECKED_' + digest[:16] + '_' + Path(name).stem[:80] + '.xlsx')
        self.editor.ensure_source_current()
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('草稿副本已存在且内容不同，未覆盖；请先处理该文件：' + str(path))
        else:
            write_new(path, raw)
        if hasattr(self, 'scan'):
            self.scan.persist(digest)
        if hasattr(self, 'swd'):
            self.swd.persist(digest)
        return {'path': str(path.resolve()), 'sha256': digest, 'validation': 'NOT_CHECKED'}

    def require_generation(self, payload):
        scope = payload.get('scope', 'program')
        if scope not in ('program', 'patterns', 'pin', 'fbist', 'flash', 'flash_labels', 'pump'):
            raise ValueError('请选择完整程序、Pattern、Pin、普通FBIST、Flash擦写/比较、Flash页／UID或PUMP汇总资源')
        checked = self.require_checked(payload, scope if scope in ('pin', 'fbist', 'flash', 'flash_labels', 'pump') else 'program')
        ids = payload.get('targets')
        valid = {t['id'] for t in checked[{'pin': 'pinTargets', 'fbist': 'fbistTargets', 'flash': 'flashTargets', 'flash_labels': 'flashLabelTargets', 'pump': 'pumpTargets'}.get(scope, 'targets')]}
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or any(i not in valid for i in ids):
            raise ValueError('请选择当前母本适用的生成目标')
        if payload.get('validate', False) is not False:
            raise ValueError('本版本生成查看版，尚未接入GUI厂商编译选项')
        if scope in ('program', 'patterns') and hasattr(self, 'scan'):
            checked['scanBindings'] = self.scan.freeze(payload, {i.split(':')[1] for i in ids})
        if scope in ('program', 'patterns') and hasattr(self, 'swd'):
            checked['swdBindings'] = self.swd.freeze(payload, {i.split(':')[1] for i in ids})
        return checked, scope, ids

    def generate(self, payload):
        checked, scope, ids = self.require_generation(payload)
        key = generation_key(payload)
        if self.job and self.job['requestKey'] == key:
            return {'jobId': self.job['id']}  # Retry after a lost HTTP response resumes the same job.
        job_id = secrets.token_hex(12)
        folder = self.output / (time.strftime('%Y%m%d_%H%M%S_') + job_id[:10])
        folder.mkdir(parents=True, exist_ok=False)
        job = {'id': job_id, 'requestKey': key, 'status': 'running', 'phase': '准备输入快照',
               'logs': [], 'result': None, 'error': None, 'inputSha256': sha(checked['raw'])}
        self.job = job

        def progress(message):
            if isinstance(message, dict):
                event = message.get('event')
                target = message.get('target', '')
                if isinstance(target, dict):
                    target = f"{target.get('platform','')} {target.get('cp','')} {target.get('variant','')}"
                message = {'started': f"准备生成 {message.get('target_count', '')} 个目标",
                           'rendering': f'正在生成 {target}', 'rendered': f'已生成 {target}',
                           'failed': f"生成失败 {target}: {message.get('error','')}",
                           'completed': '所有目标处理结束'}.get(event, str(message))
            job['phase'] = str(message)
            job['logs'].append(time.strftime('%H:%M:%S ') + str(message))
            job['logs'] = job['logs'][-1000:]

        def execute():
            try:
                from gui.generation import generate_review
                write_new(folder / 'input' / safe_name(self.editor.name), checked['raw'])
                label = {'program': '完整程序及配套资源', 'patterns': 'Pattern资源', 'pin': 'Pin资源', 'fbist': '普通FBIST资源', 'flash': 'Flash擦写/比较资源', 'flash_labels': 'Flash页／UID资源', 'pump': 'PUMP汇总资源'}[scope]
                progress('开始生成' + label)
                result = generate_review(checked['workbook'], checked['compilation'], ids, folder, validate=False, progress=progress, scope=scope, scan_bindings=checked.get('scanBindings'), swd_bindings=checked.get('swdBindings'))
                job['result'] = result
                failed = result.get('status') not in ('REVIEW_READY', 'REVIEW_READY_WITH_WARNINGS')
                job['status'] = 'failed' if failed else 'completed'
                job['phase'] = '生成失败，请查看日志' if failed else label + '已输出（未厂商编译）'
                progress(job['phase'])
            except Exception as error:
                job['error'] = str(error)
                progress('生成失败：' + str(error))
                job['status'] = 'failed'

        threading.Thread(target=execute, daemon=True).start()
        return {'jobId': job_id}


def make_server(port=8765, session=None, *, empty=False, compiler_enabled=False):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(120)

        def log_message(self, *_): pass

        def reply(self, status, value, mime='application/json; charset=utf-8'):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            for k, v in {'Content-Type': mime, 'Content-Length': str(len(raw)), 'Cache-Control':'no-store',
                         'X-Frame-Options':'SAMEORIGIN','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}.items():
                self.send_header(k, v)
            self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError): pass

        def allowed(self):
            return (self.headers.get('Host') == self.server.origin.removeprefix('http://')
                    and self.headers.get('Origin', self.server.origin) == self.server.origin)

        def authenticated(self):
            return self.allowed() and secrets.compare_digest(self.headers.get('X-GUI-Session',''), self.server.token)

        def do_GET(self):
            if not self.allowed(): return self.reply(403, {'error':'仅允许本地同源访问'})
            if not self.server.compiler_enabled and (urlsplit(self.path).path == '/compiler' or urlsplit(self.path).path.startswith('/api/compiler/')):
                return self.reply(403, {'error': 'V0.5 程序编译暂未开放'})
            if self.path in ('/', '/program', '/swd', '/compiler', '/hex', '/assistant'):
                page = (ROOT / 'gui' / ({'/': 'workbench.html', '/program': 'index.html', '/swd': 'swd.html', '/compiler': 'compiler.html', '/hex': 'hex.html', '/assistant': 'assistant.html'}[self.path])).read_text(encoding='utf-8')
                config = '<script type="application/json" id="connection">'+json.dumps({'token':self.server.token})+'</script>'
                return self.reply(200, page.replace('</head>',config+'</head>').encode(), 'text/html; charset=utf-8')
            if self.path in ('/workbench.js', '/workbench.css', '/swd.js', '/compiler.js', '/hex.js', '/assistant.js'):
                mime = 'text/javascript' if self.path.endswith('.js') else 'text/css'
                return self.reply(200, (ROOT / 'gui' / self.path[1:]).read_bytes(), mime + '; charset=utf-8')
            if self.path == '/help':
                return self.reply(200,(ROOT/'gui/使用说明.html').read_bytes(),'text/html; charset=utf-8')
            if not self.authenticated(): return self.reply(403, {'error':'页面会话失效，请刷新页面'})
            try:
                parsed = urlsplit(self.path)
                if parsed.path == '/api/assistant/state':
                    return self.reply(200, {'settings': self.server.assistant_settings.state(), 'tasks': self.server.assistant.list()})
                if parsed.path == '/api/assistant/task':
                    return self.reply(200, self.server.assistant.get(parse_qs(parsed.query).get('id', [''])[0]))
                if parsed.path == '/api/assistant/artifact':
                    query = parse_qs(parsed.query)
                    path = self.server.assistant.artifact(query.get('id', [''])[0], query.get('candidate', [''])[0], query.get('kind', [''])[0])
                    return self.reply(200, path.read_bytes(), 'application/octet-stream')
                if parsed.path == '/api/hex/state': return self.reply(200, self.server.hex.state())
                if parsed.path == '/api/pattern/state': return self.reply(200, self.server.swd.pattern_state())
                if parsed.path == '/api/hex/download':
                    identity = parse_qs(parsed.query).get('task', [''])[0]
                    return self.reply(200, self.server.hex.download(identity).read_bytes(), 'application/zip')
                if parsed.path == '/api/hex/preview':
                    query = parse_qs(parsed.query)
                    value = self.server.hex.preview(query.get('task', [''])[0], query.get('file', [''])[0])
                    return self.reply(200, value.encode('utf-8'), 'text/plain; charset=utf-8')
                if parsed.path == '/api/compiler/state': return self.reply(200, self.server.compiler.state())
                if parsed.path == '/api/compiler/log':
                    return self.reply(200, self.server.compiler.log(parse_qs(parsed.query).get('id', [''])[0]))
                if parsed.path == '/api/compiler/download':
                    query = parse_qs(parsed.query)
                    path = self.server.compiler.download(query.get('id', [''])[0], query.get('kind', [''])[0])
                    return self.reply(200, path.read_bytes(), 'application/octet-stream')
                if parsed.path == '/api/swd/state': return self.reply(200, self.server.swd.state())
                if parsed.path == '/api/swd/download':
                    query = parse_qs(parsed.query)
                    return self.reply(200, self.server.swd.output(query.get('id', [''])[0], query.get('file', [''])[0]).read_bytes(), 'application/octet-stream')
                if parsed.path == '/api/swd/excel':
                    return self.reply(200, self.server.swd.export_excel(parse_qs(parsed.query).get('id', [''])[0]), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                if parsed.path == '/api/state': return self.reply(200,self.server.session.state())
                if parsed.path == '/api/workbench': return self.reply(200, self.server.scan.state())
                if parsed.path in ('/api/scan/output', '/api/scan/download'):
                    query = parse_qs(parsed.query)
                    path = self.server.scan.output_file(query.get('id', [''])[0], query.get('file', [''])[0])
                    if parsed.path.endswith('/download'):
                        return self.reply(200, path.read_bytes(), 'application/octet-stream')
                    with path.open('rb') as stream:
                        return self.reply(200, preview_text(stream.read(512 * 1024 + 1)))
                if parsed.path == '/api/preview':
                    query = parse_qs(parsed.query)
                    return self.reply(200, self.server.session.preview_file(query.get('id', [''])[0], query.get('file', [None])[0]))
                if parsed.path == '/api/output':
                    query = parse_qs(parsed.query)
                    return self.reply(200, self.server.session.output_preview(
                        query.get('id', [''])[0], query.get('target', [''])[0], query.get('file', [None])[0]))
                if parsed.path == '/api/job':
                    job=self.server.session.job
                    if job and parse_qs(parsed.query).get('id') == [job['id']]: return self.reply(200,job)
                return self.reply(404,{'error':'没有找到此资源或生成任务'})
            except (ValueError, OSError) as e: self.reply(422,{'error':str(e)})
            except Exception as e: self.reply(500,{'error':str(e)})

        def do_POST(self):
            if not self.authenticated(): return self.reply(403, {'error':'页面会话失效，请刷新后恢复草稿'})
            if not self.server.compiler_enabled and urlsplit(self.path).path.startswith('/api/compiler/'):
                return self.reply(403, {'error': 'V0.5 程序编译暂未开放'})
            if self.path not in ('/api/assistant/confirm-knowledge', '/api/assistant/test', '/api/assistant/execute', '/api/assistant/clear', '/api/assistant/stage', '/api/assistant/settings', '/api/assistant/start', '/api/assistant/cancel', '/api/load','/api/check','/api/save','/api/save-draft','/api/flow-new-item','/api/storage-mapping','/api/trim-pattern','/api/fb-mapping','/api/pattern-targets','/api/item-preview','/api/recipe','/api/preview','/api/generate','/api/stop', '/api/scan/input', '/api/scan/config', '/api/scan/register', '/api/scan/pins', '/api/scan/start', '/api/scan/status', '/api/scan/targets', '/api/scan/link', '/api/swd/import', '/api/swd/material', '/api/swd/confirm', '/api/swd/save', '/api/swd/config', '/api/swd/generate', '/api/swd/targets', '/api/swd/link', '/api/swd/create', '/api/swd/cache', '/api/compiler/create', '/api/compiler/file', '/api/compiler/ready', '/api/compiler/start', '/api/compiler/discard', '/api/compiler/clear', '/api/hex/input', '/api/hex/start', '/api/hex/clear'):
                return self.reply(404,{'error':'未提供此操作'})
            guard = self.server.preview_guard if self.path == '/api/item-preview' else self.server.guard
            if not guard.acquire(blocking=False): return self.reply(409,{'error':'正在处理上一操作，请稍后重试'})
            try:
                session=self.server.session
                if session.job and session.job['status']=='running' and self.path!='/api/generate' and not self.path.startswith(('/api/scan/', '/api/swd/', '/api/compiler/', '/api/hex/', '/api/assistant/')):
                    return self.reply(409,{'error':'完整程序正在生成，请等待结束后再载入、检查或关闭服务'})
                if self.path == '/api/stop' and self.server.scan.job and self.server.scan.job['status'] == 'running':
                    return self.reply(409, {'error': 'SCAN 正在转换，请等待结束后关闭服务'})
                if self.path == '/api/stop' and self.server.hex.state()['running']:
                    return self.reply(409, {'error': 'HEX 正在转换，请等待队列结束后关闭服务'})
                if self.path == '/api/stop' and self.server.compiler.state()['running']:
                    return self.reply(409, {'error': '程序正在编译，请等待队列结束后关闭服务'})
                if session.editor is None and self.path not in ('/api/load', '/api/recipe', '/api/stop') and not self.path.startswith(('/api/scan/', '/api/swd/', '/api/compiler/', '/api/hex/', '/api/assistant/')):
                    raise ValueError('请先打开程序 Excel')
                length=int(self.headers.get('Content-Length','0'))
                binary = self.path in ('/api/load', '/api/scan/input', '/api/scan/config', '/api/swd/import', '/api/swd/material', '/api/compiler/file', '/api/hex/input')
                maximum = (256 if self.path in ('/api/scan/input', '/api/compiler/file') else 32) * 1024**2 if binary else 4*1024**2
                minimum = 0 if self.path == '/api/compiler/file' else 1
                if not minimum <= length <= maximum: return self.reply(413,{'error':'请求为空或超过当前大小限制'})
                expected='application/octet-stream' if binary else 'application/json'
                if self.headers.get('Content-Type','').split(';')[0]!=expected:
                    return self.reply(415,{'error':'请求内容格式不正确'})
                raw=self.rfile.read(length)
                if len(raw) != length: raise ValueError('上传内容不完整，请重新添加文件夹')
                if self.path == '/api/hex/input':
                    result = self.server.hex.add_input(raw, unquote(self.headers.get('X-File-Name', '')))
                elif self.path == '/api/compiler/file':
                    result = self.server.compiler.add_file(self.headers.get('X-Task-Id', ''), unquote(self.headers.get('X-File-Name', '')), raw)
                elif self.path in ('/api/swd/import', '/api/swd/material'):
                    name = unquote(self.headers.get('X-File-Name', ''))
                    operation = self.server.swd.import_excel if self.path.endswith('/import') else self.server.swd.import_material
                    result = operation(raw, name)
                elif self.path in ('/api/scan/input', '/api/scan/config'):
                    name = unquote(self.headers.get('X-File-Name', ''))
                    operation = self.server.scan.add_input if self.path.endswith('/input') else self.server.scan.set_configuration
                    result = operation(raw, name)
                elif self.path=='/api/load':
                    name=unquote(self.headers.get('X-File-Name','workbook.xlsx'))
                    if not name.lower().endswith('.xlsx'): raise ValueError('请选择xlsx母本')
                    result=session.load(raw,safe_name(name))
                else:
                    payload=json.loads(raw)
                    if not isinstance(payload,dict): raise ValueError('请求必须是对象')
                    if self.path == '/api/assistant/settings': result = self.server.assistant_settings.save(payload)
                    elif self.path == '/api/assistant/clear': result = self.server.assistant.clear()
                    elif self.path == '/api/assistant/confirm-knowledge':
                        result = self.server.assistant.confirm_knowledge(payload.get('id'), payload.get('answers'), payload.get('context'),
                                                                        materials=self.server.swd.materials().state())
                    elif self.path == '/api/assistant/cancel': result = self.server.assistant.cancel(payload.get('id'))
                    elif self.path == '/api/assistant/execute':
                        result = self.server.assistant.execute(payload.get('id'), payload.get('candidate'), payload.get('context'))
                    elif self.path == '/api/assistant/stage':
                        result = self.server.assistant.stage(payload.get('id'), payload.get('candidate'), payload.get('context'), self.server.swd)
                    elif self.path in ('/api/assistant/start', '/api/assistant/test'):
                        from gui.assistant_model import ModelClient, ModelConfig
                        config = self.server.assistant_settings.client_config()
                        testing = self.path == '/api/assistant/test'
                        if testing:
                            payload = {'requestId': payload.get('requestId'), 'text': '模型连接与工具往返测试', 'context': {}}
                        result = self.server.assistant.start(payload, ModelClient(ModelConfig(**config)), materials=self.server.swd.materials().state(), connection_test=testing)
                    elif self.path == '/api/hex/start': result = self.server.hex.start(payload)
                    elif self.path == '/api/hex/clear': result = self.server.hex.clear(payload)
                    elif self.path.startswith('/api/compiler/'):
                        operation = {'/api/compiler/create': self.server.compiler.create, '/api/compiler/ready': self.server.compiler.ready,
                                     '/api/compiler/start': self.server.compiler.start, '/api/compiler/discard': self.server.compiler.discard, '/api/compiler/clear': self.server.compiler.clear_history}[self.path]
                        result = operation(payload)
                    elif self.path == '/api/swd/save': result = self.server.swd.save(payload)
                    elif self.path == '/api/swd/create': result = self.server.swd.create_pattern(payload)
                    elif self.path == '/api/swd/cache':
                        result = self.server.swd.import_material(
                            (RESOURCE_ROOT / 'gui/data/py32f420_svd_cache.json').read_bytes(),
                            'PY32F420_cached_materials.json', kind='svd_cache')
                    elif self.path == '/api/swd/config': result = self.server.swd.configure(payload)
                    elif self.path == '/api/swd/generate': result = self.server.swd.generate(payload)
                    elif self.path == '/api/swd/targets': result = self.server.swd.targets(payload.get('draft'))
                    elif self.path == '/api/swd/link': result = self.server.swd.link(payload)
                    elif self.path == '/api/swd/confirm':
                        self.server.swd.materials().confirm(payload.get('conflictId'), payload.get('sourceId'), payload.get('note', ''))
                        result = self.server.swd.state()
                    elif self.path == '/api/scan/register': result = self.server.scan.register_paths(payload.get('paths'))
                    elif self.path == '/api/scan/pins': result = self.server.scan.pins(payload)
                    elif self.path == '/api/scan/start': result = self.server.scan.start(payload)
                    elif self.path == '/api/scan/status': result = self.server.scan.state(payload.get('draft'))['scan']
                    elif self.path == '/api/scan/targets': result = self.server.scan.targets(payload.get('draft'))
                    elif self.path == '/api/scan/link': result = self.server.scan.link(payload)
                    elif self.path=='/api/check': result=session.check(payload)
                    elif self.path=='/api/save': result=session.save(payload)
                    elif self.path=='/api/save-draft': result=session.save_draft(payload)
                    elif self.path=='/api/preview': result=session.preview(payload)
                    elif self.path=='/api/item-preview': result=session.item_preview(payload)
                    elif self.path=='/api/flow-new-item': result=session.new_flow_item(payload)
                    elif self.path=='/api/storage-mapping': result=session.storage_mapping(payload)
                    elif self.path=='/api/fb-mapping': result=session.fb_mapping(payload)
                    elif self.path=='/api/pattern-targets': result=session.pattern_targets(payload)
                    elif self.path=='/api/trim-pattern': result=session.trim_pattern(payload)
                    elif self.path=='/api/recipe':
                        from gui.recipe_editor import inspect_recipe
                        result=inspect_recipe(payload)
                    elif self.path=='/api/generate':
                        if session.job and session.job['status']=='running':
                            proposed=generation_key(payload)
                            if session.job['requestKey']!=proposed: return self.reply(409,{'error':'已有生成任务正在运行'})
                        result=session.generate(payload)
                    else: result={'stopped':True}
                self.reply(200,result)
                if self.path=='/api/stop': threading.Thread(target=self.server.shutdown,daemon=True).start()
            except (ValueError,TypeError,KeyError) as e: self.reply(422,{'error':str(e)})
            except Exception as e: self.reply(500,{'error':'本地处理失败：'+str(e)})
            finally: guard.release()

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.compiler_enabled = compiler_enabled
    server.origin='http://127.0.0.1:'+str(server.server_port)
    server.token=secrets.token_hex(24)
    server.guard=threading.Lock()
    server.preview_guard=threading.Lock()
    server.session = session or Session(master=None if empty else MASTER)
    from gui.hex_workspace import HexWorkspace
    server.hex = HexWorkspace(server.session.output / 'hex')
    server.session.hex = server.hex
    from gui.scan_workspace import ScanWorkspace
    server.scan = ScanWorkspace(server.session)
    server.session.scan = server.scan
    from gui.swd_workspace import SwdWorkspace
    server.swd = SwdWorkspace(server.session)
    server.session.swd = server.swd
    from gui.compiler_workspace import CompilerWorkspace
    server.compiler = CompilerWorkspace(server.session.output / 'compiler')
    from gui.assistant_tasks import AssistantTasks
    from gui.assistant_settings import AssistantSettings
    from gui.assistant_workbench import WorkbenchTools
    server.assistant = AssistantTasks(server.session.output / 'assistant' / 'tasks', WorkbenchTools(server.session, server.guard))
    server.assistant_settings = AssistantSettings(server.session.output / 'assistant')
    return server


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    service=make_server(args.port, empty=True)
    print(json.dumps({'url':service.origin,'outputRoot':str(OUTPUT)},ensure_ascii=False),flush=True)
    try: service.serve_forever()
    except KeyboardInterrupt: pass
    finally: service.server_close()
