"""Persistent SWD inputs, generated revisions and explicit program links."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import secrets


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def provenance(raw, rows=None, sheet=None):
    """Expose embedded AI metadata as untrusted source information only."""
    from gui.assistant_swd import read_provenance
    value = read_provenance(raw)
    status = value.get('status')
    if status not in {'consistent', 'missing', 'modified'}:
        return {'status': 'unknown', 'reason': value.get('reason', status), 'trusted': False}
    if status == 'consistent' and rows is not None:
        from gui.assistant_swd import _digest
        if _digest(rows, value['record']) != value['record'].get('contentDigest'):
            if sheet is not None:
                from gui.swd_generator import _editable_package
                if _editable_package(raw, sheet)[1] is None:
                    return {'status': 'missing', 'trusted': False}
            return {'status': 'modified', 'trusted': False}
    result = {'status': status, 'trusted': False}
    if status == 'consistent':
        record = value['record']
        result.update({key: record[key] for key in ('chipId', 'productProfileId', 'platform', 'knowledgeVersion')
                       if key in record})
    return result


class SwdWorkspace:
    def __init__(self, session):
        self.session = session
        self.root = session.output / 'swd'
        self.file = self.root / 'workspace.json'
        self._pending_documents = {}
        self._source_models = {}
        self._target_links_cache = None
        self._draft_bytes_cache = None
        self._target_firmware_plans = {}
        self._target_editor = None
        self.data = json.loads(self.file.read_text(encoding='utf-8')) if self.file.is_file() else {
            'documents': [], 'generations': [], 'links': {},
            'config': {'chip': 'PT104', 'pins': {'swc': 'PA14', 'swd': 'PA13', 'reset': 'NRST', 'trig': 'TRIGPIN'}},
            'materialsRevision': 0}

    def _persist(self):
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temp.replace(self.file)
        self.session.checked = None

    def _document(self, identity):
        doc = next((d for d in self.data['documents'] if d['id'] == identity), None)
        if doc is None and identity in self._pending_documents:
            doc = self._pending_documents[identity][0]
        if doc is None:
            raise ValueError('SWD 步骤文档不存在')
        return doc

    def _generation(self, identity):
        found = next((g for g in self.data['generations'] + self.data.get('externalGenerations', []) if g['id'] == identity), None)
        if found is None:
            raise ValueError('SWD 生成记录不存在')
        return found

    def _source(self, value):
        if not isinstance(value, dict):
            raise ValueError('SWD 步骤来源必须包含 documentId 和 pattern')
        document_id, pattern = value.get('documentId'), value.get('pattern')
        doc = next((item for item in self.data['documents'] if item['id'] == document_id), None)
        if doc is None:
            raise ValueError('SWD 步骤来源不存在或尚未保存')
        if not isinstance(pattern, str) or pattern not in doc['patterns']:
            raise ValueError('SWD 步骤来源 Pattern 不存在')
        return doc, pattern

    @staticmethod
    def _binding_identity(binding):
        source = binding.get('swdSource')
        if source:
            return 'source:' + digest([source['documentId'], source['pattern']])
        return 'generation:' + binding['generationId']

    def _revision(self, doc):
        from gui.swd_generator import GENERATOR_REVISION
        return digest([GENERATOR_REVISION, doc['rows'], self.data['config'], self.data['materialsRevision']])

    @staticmethod
    def _patterns(rows):
        return list(dict.fromkeys(str(r['pattern']).strip() for r in rows if r.get('pattern')))

    @staticmethod
    def _export_document(raw, doc):
        from gui.swd_generator import export_excel
        rows = [dict(row, row=None) if row['row'] < 0 else row for row in doc['rows']]
        return export_excel(raw, doc['sheet'], rows)

    def import_excel(self, raw, name):
        from gui.swd_generator import load_excel
        from gui.server import safe_name
        if not name.lower().endswith('.xlsx'):
            raise ValueError('请选择 SWD 步骤 .xlsx')
        model, sheet = load_excel(raw)
        name = safe_name(name)
        doc = next((d for d in self.data['documents'] if d['name'] == name), None)
        identity = doc['id'] if doc else secrets.token_hex(16)
        path = self.root / 'imports' / identity / (digest(raw) + '.xlsx')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        value = {'id': identity, 'name': name, 'sheet': sheet, 'source': str(path),
                 'rows': model['rows'], 'patterns': self._patterns(model['rows']),
                 'provenance': provenance(raw)}
        self._source_models[(identity, str(path))] = model
        if doc:
            doc.clear(); doc.update(value)
        else:
            self.data['documents'].append(value)
        self._persist()
        return {**self.state(), 'importedDocumentId': identity}

    def stage_excel(self, raw, name, identity):
        """Stage a separate validated document in memory; save remains explicit."""
        from gui.swd_generator import load_excel
        if not re.fullmatch(r'[0-9a-f]{32}', identity):
            raise ValueError('无效的候选编号')
        if any(doc['id'] == identity for doc in self.data['documents']):
            raise ValueError('该候选已经保存，请从步骤列表打开')
        model, sheet = load_excel(raw)
        if identity not in self._pending_documents:
            doc = {'id': identity, 'name': name, 'sheet': sheet,
                   'rows': model['rows'], 'patterns': self._patterns(model['rows']),
                   'provenance': provenance(raw)}
            self._pending_documents[identity] = (doc, raw)
        return deepcopy(self._pending_documents[identity][0])

    def save(self, payload):
        from gui.swd_generator import load_excel
        doc = self._document(payload.get('documentId'))
        rows = payload.get('rows')
        if not isinstance(rows, list) or len(rows) > 50000 or any(not isinstance(r, dict) for r in rows):
            raise ValueError('SWD 步骤必须是有效行列表（最多50000行）')
        pending = self._pending_documents.get(doc['id'])
        key = (doc['id'], doc.get('source'))
        raw = pending[1] if pending else Path(doc['source']).read_bytes()
        if key not in self._source_models:
            self._source_models[key] = load_excel(raw, doc['sheet'])[0]
        originals = {row['row']: row for row in self._source_models[key]['rows']}
        known_new = {row['row'] for row in doc['rows'] if isinstance(row.get('row'), int) and row['row'] < 0}
        next_new = min(known_new | {0}) - 1
        seen, saved_rows = set(), []
        for row in rows:
            row = deepcopy(row)
            number = row.get('row')
            if number is None:
                number, next_new = next_new, next_new - 1
            elif type(number) is not int or number not in originals and number not in known_new:
                raise ValueError('row必须是原物理行号、已保存步骤标识或None')
            if number in seen:
                raise ValueError('row不能重复')
            seen.add(number)
            for name, value in row.items():
                if name == 'row': continue
                if not isinstance(value, (str, int, float, bool, type(None))):
                    raise ValueError('步骤单元格必须是文本、数字或空值')
                if isinstance(value, str) and (len(value) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value)):
                    raise ValueError('步骤单元格包含无效字符或超过Excel长度限制')
            original = originals.get(number, {})
            for name, value in original.items():
                if isinstance(value, str) and value.startswith('=') and row.get(name, value) != value:
                    raise ValueError(f'第{number}行公式不可在此编辑')
            row = {**original, **row, 'row': number}
            saved_rows.append(row)
        digest(saved_rows)  # Reject non-finite JSON numbers before mutating state.
        if pending:
            source = self.root / 'imports' / doc['id'] / (digest(pending[1]) + '.xlsx')
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(pending[1])
            doc['source'] = str(source)
            self._source_models[(doc['id'], str(source))] = self._source_models[key]
            self.data['documents'].append(doc)
            del self._pending_documents[doc['id']]
        doc['rows'] = saved_rows
        doc['patterns'] = self._patterns(doc['rows'])
        doc['provenance'] = provenance(raw, doc['rows'], doc['sheet'])
        self._persist()
        return self.state()

    def export_excel(self, identity):
        doc = self._document(identity)
        return self._export_document(Path(doc['source']).read_bytes(), doc)

    def create_pattern(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('创建 SWD Pattern 请求必须是对象')
        value = payload.get('name', '')
        if not isinstance(value, str):
            raise ValueError('Pattern 名称必须是字符串')
        name = re.sub(r'\s+', '', value)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('Pattern 名称只允许字母、数字、下划线，不能以数字开头')
        identity = payload.get('documentId')
        if identity is None:
            from io import BytesIO
            import openpyxl
            existing = {doc['name'].casefold() for doc in self.data['documents']}
            existing.update(doc['name'].casefold() for doc, _ in self._pending_documents.values())
            stem, number = 'swd_steps', 1
            filename = stem + '.xlsx'
            while filename.casefold() in existing:
                number += 1
                filename = f'{stem}_{number}.xlsx'
            book = openpyxl.Workbook()
            book.active.title = 'Sheet1'
            book.active.append(['pattern', 'addr', 'data', 'step', 'reset value', 'type', 'continue', 'description'])
            raw = BytesIO(); book.save(raw)
            doc = {'id': secrets.token_hex(16), 'name': filename, 'sheet': 'Sheet1', 'rows': [], 'patterns': []}
            self._pending_documents[doc['id']] = (doc, raw.getvalue())
        else:
            doc = self._document(identity)
        if name in doc['patterns']:
            raise ValueError('该文档已存在同名 Pattern')
        state = self.state()
        draft = next((item for item in state['documents'] if item['id'] == doc['id']), None)
        if draft is None:
            draft = deepcopy(doc)
            state['documents'].append(draft)
        draft['rows'].append({
            'pattern': name, 'row': None, 'type': '', 'addr': '', 'data': '', 'step': '',
            'reset value': '', 'continue': '', 'description': ''})
        draft['patterns'] = self._patterns(draft['rows'])
        state['createdDocumentId'] = doc['id']
        state['createdPattern'] = name
        return state

    def configure(self, payload):
        chip, pins = payload.get('chip', 'PT104'), payload.get('pins')
        if chip not in ('PT104', 'PCD009'):
            raise ValueError('首期请选择 PT104 / PCD009')
        if not isinstance(pins, dict) or set(pins) != {'swc', 'swd', 'reset', 'trig'}:
            raise ValueError('请填写 SWC、SWD、复位和触发管脚')
        if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', v) for v in pins.values()):
            raise ValueError('管脚名只允许字母、数字、下划线，不能以数字开头')
        if len(set(v.casefold() for v in pins.values())) != 4:
            raise ValueError('SWD 管脚不能重复')
        self.data['config'] = {'chip': chip, 'pins': pins}
        self._persist()
        return self.state()

    def generate(self, payload):
        from gui.swd_generator import generate_pattern
        doc = self._document(payload.get('documentId'))
        name = payload.get('pattern', '')
        if name not in doc['patterns'] or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('请选择有效 Pattern 名称')
        config = self.data['config']
        contents = {p: generate_pattern(name, doc['rows'], p, config['pins'], config['chip'])
                    for p in ('chroma', 's100')}
        identity = secrets.token_hex(16)
        files = []
        for platform, raw in contents.items():
            relative = platform + '/' + name + ('.pat' if platform == 'chroma' else '.sd')
            path = self.root / 'generated' / identity / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files.append({'platform': platform, 'path': relative, 'sha256': digest(raw), 'size': len(raw)})
        self.data['generations'].append({'id': identity, 'documentId': doc['id'], 'pattern': name,
                                         'revision': self._revision(doc), 'files': files})
        self._persist()
        return self.state()

    def output(self, identity, filename):
        gen = self._generation(identity)
        if filename not in [f['path'] for f in gen['files']]:
            raise ValueError('文件不属于该 SWD 生成记录')
        root = (self.root / 'generated' / identity).resolve()
        path = (root / filename).resolve()
        if not path.is_relative_to(root):
            raise ValueError('无效的 SWD 产物路径')
        return path

    def _stale(self, gen):
        if gen.get('sourceKind', 'swd') == 'swd':
            doc = next((d for d in self.data['documents'] if d['id'] == gen['documentId']), None)
            if not doc or gen['revision'] != self._revision(doc):
                return '步骤、管脚或芯片资料已变化，请重新生成并确认关联'
        for f in gen['files']:
            path = self.output(gen['id'], f['path'])
            if not path.is_file() or digest(path.read_bytes()) != f['sha256']:
                return 'Pattern 产物已修改或丢失，请重新生成并确认关联'
        return ''

    def pattern_state(self):
        generations = deepcopy(self.data['generations'] + self.data.get('externalGenerations', []))
        document_names = {doc['id']: doc['name'] for doc in self.data['documents']}
        for gen in generations:
            gen['reason'] = self._stale(gen)
            gen['stale'] = bool(gen['reason'])
            gen.setdefault('sourceKind', 'swd')
            if gen['sourceKind'] == 'swd':
                gen['sourceLabel'] = document_names.get(gen.get('documentId'), '')
        links = self.data['links'].get(self.session.editor.sha256, []) if self.session.editor else []
        sources = []
        for doc in self.data['documents']:
            for pattern in doc['patterns']:
                sources.append({'id': 'source:' + digest([doc['id'], pattern]),
                                'documentId': doc['id'], 'pattern': pattern,
                                'sourceKind': 'swd', 'sourceLabel': doc['name'],
                                'config': deepcopy(self.data['config']),
                                'files': [{'platform': 'chroma'}, {'platform': 's100'}]})
        return {'generations': generations, 'sources': sources, 'links': deepcopy(links)}

    def _import_hex(self, task_id, version):
        snapshot = self.session.hex.snapshot(task_id, version)
        revision = digest([snapshot['source'], {p: digest(raw) for p, raw in snapshot['contents'].items()}])
        existing = next((g for g in self.data.get('externalGenerations', []) if g['revision'] == revision), None)
        if existing and not self._stale(existing):
            return existing
        identity = secrets.token_hex(16)
        files = []
        for platform, raw in snapshot['contents'].items():
            relative = platform + '/' + snapshot['pattern'] + ('.pat' if platform == 'chroma' else '.sd')
            path = self.root/'generated'/identity/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files.append({'platform': platform, 'path': relative, 'sha256': digest(raw), 'size': len(raw)})
        gen = {'id': identity, 'sourceKind': 'hex', 'source': snapshot['source'],
               'pattern': snapshot['pattern'], 'revision': revision, 'files': files}
        self.data.setdefault('externalGenerations', []).append(gen)
        return gen

    def materials(self):
        from gui.swd_materials import MaterialLibrary
        return MaterialLibrary(self.root / 'materials')

    def import_material(self, raw, name, kind=None):
        library = self.materials()
        before = digest(library.state())
        if kind is None:
            library.import_material(raw, name)
        else:
            library.import_material(raw, name, kind)
        if digest(library.state()) != before:
            self.data['materialsRevision'] += 1
            self._persist()
        return self.state()

    def state(self):
        value = deepcopy(self.data)
        for doc in value['documents']:
            doc['revision'] = self._revision(doc)
            doc.pop('source', None)
            doc.setdefault('provenance', {'status': 'unknown', 'reason': 'legacy_workspace', 'trusted': False})
        for gen in value['generations']:
            gen['reason'] = self._stale(gen)
            gen['stale'] = bool(gen['reason'])
        value['materials'] = self.materials().state()
        return value

    def _key(self):
        if not self.session.editor:
            raise ValueError('请先打开程序 Excel')
        return self.session.editor.sha256

    def targets(self, draft=None):
        from gui.links import pattern_links
        from gui.workbook_editor import WorkbookEditor
        # A confirmed name-only edit already has a validated resource preview.
        # Check its bytes before constructing another full WorkbookModel.
        if self._target_links_cache is not None and isinstance(draft, dict):
            raw = self._draft_bytes(draft)
            if self._target_links_cache[0] == raw:
                return self._target_state(self._target_links_cache[1])
        workbook, raw = self.session.scan.candidate(draft)
        if raw == self.session.editor.raw:
            links = self.session.links
            self._target_editor = self.session.editor
            self._target_firmware_plans = getattr(self.session, 'base_firmware_plans', {})
            self._target_links_cache = (raw, links)
        elif self._target_links_cache is not None and self._target_links_cache[0] == raw:
            links = self._target_links_cache[1]
        else:
            from program_gen.compiler import ProductCompiler
            compiled = ProductCompiler().compile(workbook)
            self._target_editor = WorkbookEditor(raw, self.session.editor.name)
            self._target_firmware_plans = compiled.plan.catalogs.firmware_test_plans if compiled.is_valid else {}
            links = pattern_links(compiled, self._target_editor, workbook.dataframe('FLOW'), workbook)
            self._target_links_cache = (raw, links)
        return self._target_state(links)

    def _draft_bytes(self, draft):
        from gui.server import fingerprint
        editor = self.session.editor
        if draft.get('baseSha256') == '' and not draft.get('changes'):
            draft = {'baseSha256': editor.sha256, 'changes': []}
        editor.ensure_source_current()
        key = (id(editor), fingerprint(draft))
        if self._draft_bytes_cache is None or self._draft_bytes_cache[0] != key:
            raw = editor.apply(draft.get('baseSha256'), draft.get('changes'),
                draft.get('appendRows', []), draft.get('flowOrder', []), draft.get('trimStorageMappings'),
                draft.get('verifyStorageMappings'), draft.get('patternEdits'), draft.get('patternLinks'))
            self._draft_bytes_cache = (key, raw)
        return self._draft_bytes_cache[1]

    def _target_state(self, links):
        targets = []
        for entry in links:
            for slot in entry.get('resourceSlots', []):
                if slot.get('status') == 'generated':
                    continue
                names = slot.get('names', {})
                # Each named resource is a selectable reference, not a whole test.
                for index in range(max((len(v) for v in names.values()), default=0)):
                    selected = {p: [v[index]] for p, v in names.items() if index < len(v)}
                    target = {'row': entry['flowRow'], 'cp': entry['cp'], 'item': entry['item'],
                              'phase': slot['phase'], 'role': slot['role'], 'names': selected}
                    target['id'] = digest({k: v for k, v in target.items() if k != 'row'})[:24]
                    if not any(t['id'] == target['id'] for t in targets):
                        targets.append(target)
        bindings = self.data['links'].get(self._key(), [])
        return {'targets': targets, 'links': deepcopy(bindings), 'previewLinks': links}

    def link(self, payload):
        target_state = self.targets(payload.get('draft'))
        targets = target_state['targets']
        target = next((t for t in targets if t['id'] == payload.get('targetId')), None)
        generation_id = payload.get('generationId')
        hex_task_id = payload.get('hexTaskId')
        if generation_id is not None and (not isinstance(generation_id, str) or not generation_id.strip()):
            raise ValueError('generationId 必须是非空字符串')
        if hex_task_id is not None and (not isinstance(hex_task_id, str) or not hex_task_id.strip()):
            raise ValueError('hexTaskId 必须是非空字符串')
        swd_source = payload.get('swdSource')
        has_swd_source = swd_source is not None
        selections = sum(value is not None for value in
                         (generation_id, hex_task_id, swd_source))
        if selections > 1:
            raise ValueError('一次只能选择一个 Pattern 来源')
        if not target:
            if not selections:
                key = self._key()
                bindings = self.data['links'].setdefault(key, [])
                before = len(bindings)
                bindings[:] = [b for b in bindings if b['target']['id'] != payload.get('targetId')]
                if len(bindings) == before:
                    raise ValueError('程序引用已变化，请刷新后选择')
                self._persist()
                return self.targets(payload.get('draft'))
            raise ValueError('程序引用已变化，请刷新后选择')
        key = self._key()
        bindings = self.data['links'].setdefault(key, [])
        if hex_task_id:
            if target['role'] != 'download':
                raise ValueError('HEX 产物只能关联固件下载资源')
            generation_id = self._import_hex(hex_task_id, payload.get('hexRun'))['id']
        if has_swd_source:
            doc, pattern = self._source(swd_source)
            selected_identity = 'source:' + digest([doc['id'], pattern])
        if generation_id:
            gen = self._generation(generation_id)
            if gen.get('sourceKind') == 'hex' and target['role'] != 'download':
                raise ValueError('HEX 产物只能关联固件下载资源')
            reason = self._stale(gen)
            if reason:
                raise ValueError(reason)
            selected_identity = 'generation:' + generation_id
        if selections:
            for binding in bindings:
                if binding['target']['id'] == target['id'] or binding['target']['cp'] != target['cp']:
                    continue
                for p in ('chroma', 's100'):
                    a = target['names'].get(p, target['names'].get('shared', []))
                    b = binding['target']['names'].get(p, binding['target']['names'].get('shared', []))
                    if set(a) & set(b) and self._binding_identity(binding) != selected_identity:
                        raise ValueError('该资源名由其他测试项共享，不能关联不同 Pattern 产物；请先解除已有 Link')
        updated_draft = None
        if selections and payload.get('adoptSourceName'):
            from gui.pattern_link_selection import adopt_source_name, rebase_bindings
            source_name = pattern if has_swd_source else gen['pattern']
            old_names = {n for names in target['names'].values() for n in names}
            if source_name not in old_names:
                for entry in target_state['previewLinks']:
                    if entry['cp'] == target['cp'] and any(slot.get('status') == 'generated'
                            and source_name in {n for names in slot['names'].values() for n in names}
                            for slot in entry.get('resourceSlots', [])):
                        raise ValueError('来源名称与本工具生成资源冲突，未保存 Link')
                for other in targets:
                    if other['cp'] != target['cp'] or other['id'] == target['id']:
                        continue
                    if source_name in {n for names in other['names'].values() for n in names}:
                        existing = next((b for b in bindings if b['target']['id'] == other['id']), None)
                        if existing is None or self._binding_identity(existing) != selected_identity:
                            raise ValueError('来源名称已被同 CP 其他资源使用，未保存 Link')
            updated_draft, renamed, renamed_targets = adopt_source_name(self, target, source_name, payload.get('draft'), target_state['previewLinks'])
            remaining = [b for b in bindings if b['target']['id'] != target['id']]
            remaining = rebase_bindings(remaining, targets, renamed_targets)
            for binding in remaining:
                if binding['target']['cp'] != renamed['cp']:
                    continue
                for platform in ('chroma', 's100'):
                    a = renamed['names'].get(platform, renamed['names'].get('shared', []))
                    b = binding['target']['names'].get(platform, binding['target']['names'].get('shared', []))
                    if set(a) & set(b) and self._binding_identity(binding) != selected_identity:
                        raise ValueError('来源 Pattern 名称与同 CP 已关联资源冲突，未保存 Link')
            target = renamed
            bindings[:] = remaining
        bindings[:] = [b for b in bindings if b['target']['id'] != target['id']]
        if generation_id:
            bindings.append({'target': target, 'generationId': generation_id})
        elif has_swd_source:
            bindings.append({'target': target, 'swdSource': {'documentId': doc['id'], 'pattern': pattern}})
        self._persist()
        result = self.targets(updated_draft if updated_draft is not None else payload.get('draft'))
        if updated_draft is not None:
            result['draft'] = updated_draft
        return result

    def persist(self, workbook_sha):
        if self.session.editor:
            bindings = self.data['links'].get(self._key(), [])
            self.data['links'][workbook_sha] = deepcopy(bindings)
            # Saving a program must not invalidate its already-checked snapshot.
            checked = self.session.checked
            self._persist()
            self.session.checked = checked

    def freeze(self, draft=None, cps=None):
        if not self.session.editor:
            return []
        bindings = self.data['links'].get(self._key(), [])
        if not bindings:
            return []
        active = {t['id'] for t in self.targets(draft)['targets']}
        result = []
        for binding in bindings:
            target = binding['target']
            if cps is not None and target['cp'] not in cps:
                continue
            if target['id'] not in active:
                raise ValueError('SWD 关联的测试项引用已变化，请重新关联：' + target['item'])
            if binding.get('swdSource'):
                from gui.swd_generator import generate_pattern
                doc, pattern = self._source(binding['swdSource'])
                config = self.data['config']
                try:
                    contents = {platform: generate_pattern(pattern, doc['rows'], platform, config['pins'], config['chip'])
                                for platform in ('chroma', 's100')}
                except ValueError as error:
                    raise ValueError(f'{target["item"]}：SWD 步骤来源 {pattern} 生成失败：{error}') from error
                revision = self._revision(doc)
                result.append({'cp': target['cp'], 'names': target['names'], 'pattern': pattern,
                               'identity': 'source:' + digest([doc['id'], pattern, revision]),
                               'contents': contents, 'sourceKind': 'swd', 'timingOrigin': None})
                continue
            gen = self._generation(binding['generationId'])
            reason = self._stale(gen)
            if reason:
                raise ValueError(target['item'] + '：' + reason)
            contents = {}
            for f in gen['files']:
                raw = self.output(gen['id'], f['path']).read_bytes()
                if digest(raw) != f['sha256']:
                    raise ValueError('SWD 产物读取期间变化')
                contents[f['platform']] = raw
            result.append({'cp': target['cp'], 'names': target['names'], 'pattern': gen['pattern'],
                           'identity': gen['id'] + ':' + gen['revision'], 'contents': contents,
                           'sourceKind': gen.get('sourceKind', 'swd'),
                           'timingOrigin': gen.get('source', {}).get('profile', {}).get('platform')})
        return result
