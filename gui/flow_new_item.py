"""Read-only new-item preparation on the existing workbook draft boundary."""
from types import SimpleNamespace
import re

import pandas as pd
from openpyxl.utils import get_column_letter

from flow_recipe import parse_recipe
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.fbist_pattern_plan import compile_ordinary_fbist_pattern_plan
from program_gen.core.logical_item import logical_item_key
from program_gen.core.project_mappings import (
    parse_storage_mappings, validate_storage_mapping_records,
    validate_storage_flow_occupancy, validate_storage_role_occupancy,
)
from program_gen.workbook import WorkbookReader
from gui.workbook_editor import _flow_group_key


def _text(value):
    return '' if value is None or pd.isna(value) else str(value).strip()


def _context(session, payload):
    from gui.server import fingerprint
    editor = session.editor
    editor.ensure_source_current()
    normalized = {**payload,
                  'trimStorageMappings': payload.get('trimStorageMappings', editor.trim_storage_mappings),
                  'verifyStorageMappings': payload.get('verifyStorageMappings', editor.verify_storage_mappings)}
    key = fingerprint(normalized)
    cached = getattr(session, 'new_flow_cache', None)
    if cached and cached['editor'] is editor and cached['key'] == key:
        return cached
    raw = editor.apply(payload.get('baseSha256'), payload.get('changes'),
                       payload.get('appendRows', []), payload.get('flowOrder', []),
                       normalized['trimStorageMappings'], normalized['verifyStorageMappings'], payload.get('patternEdits'), payload.get('patternLinks'))
    existing = getattr(session, 'item_cache', None)
    workbook = existing['workbook'] if existing and existing['key'] == key else WorkbookReader(byte_loader=lambda _: raw).read(editor.name)
    result = {'editor': editor, 'key': key, 'workbook': workbook, 'payload': normalized, 'errors': []}
    for name, build in (
        ('patterns', lambda: compile_ordinary_fbist_pattern_plan(workbook)),
        ('storage', lambda: compile_addr_map_catalog(workbook.dataframe('ADDR_MAP'), workbook.trim_storage_mappings, workbook.verify_storage_mappings)),
    ):
        try:
            result[name] = build()
        except (ValueError, KeyError) as error:
            result[name] = None
            result['errors'].append({'field': name, 'message': str(error)})
    editor.ensure_source_current()
    session.new_flow_cache = result
    return result


def _positions(context, cp):
    flow = context['workbook'].dataframe('FLOW')
    editor = context['editor']
    base = editor.by_name['FLOW']
    order = context['payload'].get('flowOrder') or list(range(1, base['maxRow'] + sum(op['sheet']=='FLOW' for op in context['payload'].get('appendRows', [])) + 1))
    result = []
    previous = None
    for i, row in flow.iterrows():
        key = _flow_group_key(*(_text(row.get(k)) for k in ('CP NO', 'item', 'type', 'Recipe')))
        if _text(row.get('CP NO')).upper() == cp and key != previous:
            result.append({'before': order[int(i) + 1], 'row': int(i) + 2,
                           'label': f"第 {int(i) + 2} 行 · {_text(row.get('item'))} 之前"})
        if previous and previous[0] == cp and _text(row.get('CP NO')).upper() != cp:
            result.append({'before': order[int(i) + 1], 'row': int(i) + 2, 'label': f'{cp} 末尾（需检查后续消费者）'})
        previous = key
    if len(flow) and _text(flow.iloc[-1].get('CP NO')).upper() == cp:
        result.append({'before': 0, 'row': len(flow) + 2, 'label': f'{cp} 末尾（需检查后续消费者）'})
    return result


def _options(context, values):
    cp, item, kind = values.get('CP NO', '').upper(), values.get('item', ''), values.get('type', '').lower()
    plan, catalog = context['patterns'], context['storage']
    patterns = {'enter': [], 'dac': []}
    if plan:
        role = 'trim mode' if kind == 'trim' else 'verify mode'
        for pattern in plan.patterns:
            roles = {row.role for row in plan.rows if row.output_pattern == pattern.pattern_name and not row.excluded}
            fields = [field for write in pattern.writes for field in write.fields if field.dynamic]
            option = {'name': pattern.pattern_name,
                      'description': '；'.join(write.addr_bits + ': ' + ', '.join(f.field_name for f in write.fields) for write in pattern.writes),
                      'width': fields[0].bit_width if len(fields) == 1 else None,
                      'reason': ''}
            if role in roles:
                patterns['enter'].append(option)
            if 'trim dac' in roles:
                patterns['dac'].append({**option, 'reason': '' if len(fields) == 1 else '需要且只能有一个动态 DAC 字段'})
    flow = context['workbook'].dataframe('FLOW')
    related = [r for _, r in flow.iterrows() if _text(r.get('type')).lower() == kind and logical_item_key(_text(r.get('item'))) == logical_item_key(item)]
    cps = sorted({cp, *(_text(r.get('CP NO')).upper() for r in related)})
    current = []
    shared = bool(related)
    storage = []
    if catalog:
        selected = catalog.selected_storage_fields(kind, item) if kind in ('trim', 'verify') else None
        if selected is None and (shared or logical_item_key(item) == logical_item_key('Pdr_Trim')) and kind in ('trim', 'verify'):
            matcher = catalog.matches_trim if kind == 'trim' else catalog.matches_verify
            selected = tuple(f for f in catalog.fields if any(matcher(c, item, f) for c in cps))
        current = [{'page': f.page, 'register': f.register, 'field': f.name} for f in (selected or ())]
        occupied = []
        for _, row in flow.iterrows():
            other_kind, other_item, other_cp = (_text(row.get(k)) for k in ('type', 'item', 'CP NO'))
            other_kind = other_kind.lower()
            if other_kind not in ('trim', 'verify') or (other_kind == kind and logical_item_key(other_item) == logical_item_key(item)):
                continue
            fields = catalog.selected_storage_fields(other_kind, other_item)
            if fields is None:
                matcher = catalog.matches_trim if other_kind == 'trim' else catalog.matches_verify
                fields = [f for f in catalog.fields if matcher(other_cp, other_item, f)]
            occupied.extend((f, other_item) for f in fields)
        for f in catalog.storage_fields:
            reason = ''
            if not all(f.register_layout.applies_to(c) for c in cps):
                reason = '不适用于 ' + ' / '.join(cps)
            owners = sorted({owner for old, owner in occupied if old.page.casefold() == f.page.casefold() and old.register.casefold() == f.register.casefold() and max(old.lsb, f.lsb) < min(old.lsb + old.width, f.lsb + f.width)})
            if owners:
                reason = '已被占用：' + '、'.join(owners)
            storage.append({'page': f.page, 'register': f.register, 'field': f.name,
                            'width': f.width, 'lsb': f.lsb, 'reason': reason})
    consumers = []
    for i, row in flow.iterrows():
        if _text(row.get('CP NO')).upper() != cp:
            continue
        try:
            modules = [c.name for c in parse_recipe(_text(row.get('Recipe')))]
        except ValueError:
            continue
        used = [m for m in modules if m in ('BUILDMAP', 'COMMIT', 'SETVPOSP')]
        if used:
            consumers.append({'row': int(i) + 2, 'item': _text(row.get('item')), 'modules': used})
    return {'patterns': patterns, 'storage': storage, 'currentTargets': current, 'sharedMapping': shared,
            'relatedCps': cps, 'positions': _positions(context, cp), 'consumers': consumers,
            'resourceIssues': context['errors']}


def new_flow_item(session, payload):
    from program_gen.core.flow_input import describe_flow_input
    if payload.get('action') in ('resource-options','resource-prepare'):
        from gui.resource_new_item import resource_new_item
        return resource_new_item(session, payload)
    values = payload.get('values', {})
    if not isinstance(values, dict) or len(values) > 50 or any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 32767 for k, v in values.items()):
        raise ValueError('新增测试项字段必须是文本对象')
    values = {k: v.strip() for k, v in values.items()}
    for name in ('type', 'mode', 'OTP', 'UID', 'PUMP'):
        if name in values:
            values[name] = values[name].lower()
    if 'CP NO' in values:
        values['CP NO'] = values['CP NO'].upper()
    action = payload.get('action', 'describe')
    if action not in ('describe', 'options', 'prepare', 'validate-edit'):
        raise ValueError('未知新增测试项操作')
    session.editor.ensure_source_current()
    if payload.get('baseSha256') != session.editor.sha256:
        raise ValueError('母本已变化，请重新打开新增测试项')
    if action == 'validate-edit':
        editor = session.editor
        raw = editor.apply(editor.sha256, payload.get('changes'), payload.get('appendRows', []),
                           payload.get('flowOrder', []), payload.get('trimStorageMappings', editor.trim_storage_mappings),
                           payload.get('verifyStorageMappings', editor.verify_storage_mappings), payload.get('patternEdits'), payload.get('patternLinks'))
        _, compiled = session.compile(raw)
        editor.ensure_source_current()
        return {'ready': compiled.is_valid, 'issues': [{'message': d.message} for d in compiled.diagnostics.errors]}
    context = _context(session, payload) if values.get('type') == 'verify' else None
    description = describe_flow_input(values, version_frame=context['workbook'].dataframe('VERSION') if context else None)
    if action == 'describe':
        if payload.get('editRow') is not None:
            context = context or _context(session, payload)
            description['editRows'] = _editable_phase_rows(context, payload['editRow'])
        return description
    context = _context(session, payload)
    options = _options(context, values)
    result = {**description, **options}
    if description.get('specialized'):
        workbook = context['workbook']
        kind = description['kind']
        resources = []
        if description.get('resourceSheet'):
            sheet = description['resourceSheet']
            frame = workbook.dataframe(sheet)
            resources.append(sheet + ' 专表：' + str(len(frame)) + ' 行配置；完整检查会解析有效用例。')
            if kind == 'ADC_TEST':
                resources.append('通道组：' + values.get('FV/FI', '') + '；需要 ADC CH0..CH21 与 IOMUX IN0..IN21 一一对应。sub 自动与 ADCn 一致。')
            elif kind == 'PVD_TEST':
                resources.append('按 case 配对 up/down；阈值和 expect 来自 PVD，FLOW 提供两个比较引脚和动态执行序列。')
            else:
                resources.append('使用整张 ' + sheet + ' 的有效用例；无需按 FLOW item 同名匹配。SWD 专表 step 仅支持空白、/、RP；KEIL 专表使用执行序列。')
            version = workbook.dataframe('VERSION')
            for _, row in version.iterrows():
                if _text(row.get('CP num')).upper() == values.get('CP NO'):
                    resources.append('VERSION：' + ' · '.join(k + '=' + _text(row.get(k)) for k in ('product name','vcc min','vcc typ','vcc max','GET PIN','SWD PIN')))
        elif kind == 'OS':
            resources.append('OS 使用原生开短路协议；只填写供电、继电器及分 Bin 等参数。')
        elif kind == 'FREQ_TEST':
            freq = workbook.dataframe('FREQ').copy()
            if 'FREQ' in freq:
                freq['FREQ'] = freq['FREQ'].ffill()
                names = list(dict.fromkeys(_text(x) for x in freq['FREQ'] if _text(x) not in ('', '/')))
                resources.append('FREQ 配置组：' + '、'.join(names))
                for _, row in freq.iterrows():
                    if _text(row.get('FREQ')).casefold() == values.get('item', '').casefold():
                        resources.append(' · '.join(k + '=' + _text(row.get(k)) for k in ('source', 'mul', 'div', 'down_limit', 'up_limit', 'step')))
            resources.append('频率目标与限值来自同名 FREQ 组；产品名来自 VERSION，外部晶振依赖 IOMUX。')
            if values.get('mode') == 'keil':
                resources.append('KEIL：FREQ 表 step 填各档位执行序列，默认引脚来自 VERSION GET PIN；需重新供电时以 RP- 开头，并重跑 FLOW 进入步骤。')
        elif kind in ('VERIFY_HEX','VERIFY_KEIL'):
            resources.append('固件阶段按列表顺序连续执行；HEX step 指向下载资源，KEIL 显式使用 RUN_SEQUENCE-JUDGE。全组共用 CP、ITEM 和 Bin，创建前完整检查。')
        else:
            resources.append('固定协议名称：' + ('Pdr_Trim' if kind == 'PDR_TRIM' else 'Pdr_Verify'))
            version = workbook.dataframe('VERSION')
            for _, row in version.iterrows():
                if _text(row.get('CP num')).upper() == values.get('CP NO'):
                    resources.append('VERSION：' + ' · '.join(k + '=' + _text(row.get(k)) for k in ('pdr min', 'pdr target', 'pdr max', 'SWD PIN')))
            resources.append('Pattern：Pdr_Trim / trim dac；固定 4 bit 二分码序。' if kind == 'PDR_TRIM' else '协议 Pattern：enter_fbist_mode、enter_pdr_verify、read_status_mode（Chroma 还需 exit_fbist_mode）。')
        result['resources'] = resources
    if action == 'options':
        return result
    if description.get('specialized'):
        return _prepare_specialized(session, context, payload, values, result)
    return _prepare(session, context, payload, values, result)


def _prepare(session, context, payload, values, view):
    # Only the confirmed ordinary FBIST recipes have a complete guided path.
    if not view['supported'] or view['kind'] not in ('STANDARD_TRIM', 'STANDARD_VERIFY'):
        raise ValueError('此 typed kind 请使用现有专用配置；当前向导支持普通 FBIST TRIM / VERIFY')
    issues = list(view['issues'])
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,119}', values.get('item', '')):
        issues.append({'field': 'item', 'message': '名称须以字母或下划线开头，只使用字母、数字、下划线，最多120字符'})
    for field in view['fields']:
        value = values.get(field['name'], str(field.get('default', '')))
        values[field['name']] = value
        if field['required'] and value in ('', '/'):
            issues.append({'field': field['name'], 'message': '请填写 ' + field['label']})
        if value and field.get('choices') and value not in field['choices']:
            issues.append({'field': field['name'], 'message': field['label'] + ' 不是有效选项'})
    for flag in ('OTP', 'UID', 'PUMP'):
        if values.get(flag) not in ('yes', 'no'):
            issues.append({'field': flag, 'message': '请选择 yes / no'})
    if values.get('type') == 'verify' and values.get('PUMP') == 'yes':
        issues.append({'field': 'PUMP', 'message': '普通 VERIFY 不产生 PUMP DAC，请在对应 TRIM 项配置'})
    selected = {}
    for key, field in [('enter', '_enterPattern'), *([('dac', '_dacPattern')] if view['kind'] == 'STANDARD_TRIM' else [])]:
        option = next((p for p in view['patterns'][key] if p['name'] == values.get(field)), None)
        if option is None or option['reason']:
            issues.append({'field': field, 'message': '请选择有效的' + ('进入模式' if key == 'enter' else '写 DAC') + ' Pattern'})
        else:
            selected[key] = option
    if issues:
        return {**view, 'issues': issues, 'ready': False}
    from program_gen.core.trim_spec import _compile_search, _compile_measurement
    from program_gen.core.encoding import calc_limit
    from program_gen.core.standard_verify import compile_standard_verify_plans
    cp, item, kind = values['CP NO'].upper(), values['item'], values['type']
    flow = context['workbook'].dataframe('FLOW')
    if any(_text(r.get('CP NO')).upper() == cp and _text(r.get('type')).lower() == kind and logical_item_key(_text(r.get('item'))) == logical_item_key(item) for _, r in flow.iterrows()):
        raise ValueError('当前 CP 已存在同类型的同名逻辑测试项；请编辑原项或使用其他名称')
    allowed = {'CP NO', 'item', 'type', 'mode', 'OTP', 'UID', 'PUMP', *(f['name'] for f in view['fields'])}
    record = {k: v for k, v in values.items() if k in allowed}
    record['CP NO'] = cp
    for name in view['clearFields']:
        record[name] = '/'
    if kind == 'trim':
        record['step'] = values.get('step', '') if values.get('_codeMode') == 'custom' else '/'
        record['LINE'] = 'no' if values.get('_codeMode') == 'custom' else 'yes'
        try:
            # int(float) would silently round fractional bit counts; reject them first.
            if not re.fullmatch(r'[1-9]\d*', record['DAC bit']):
                raise ValueError('DAC bit 必须是正整数')
            _compile_search(pd.Series(record), selected['dac']['width'], 0)
            _compile_measurement(pd.Series(record), 0)
            calc_limit(record['target'], record['low_range(%)'], record['high_range(%)'], True)
            calc_limit(record['target'], record['low_range(%)'], record['high_range(%)'], False)
        except (ValueError, TypeError, OverflowError) as error:
            return {**view, 'ready': False, 'issues': [{'field': 'parameters', 'message': str(error)}]}
        required_bits = max(int(record['DAC bit']), selected['dac']['width'])
        recipe = f"ENTER(PATTERN={selected['enter']['name']})-TRIM(PATTERN={selected['dac']['name']})-JUDGE"
    else:
        recipe = f"ENTER(ROLE=VERIFY,PATTERN={selected['enter']['name']})-JUDGE"
        required_bits = {'BCD16_MV': 16, 'ADC12_3V3': 12}.get(values.get('_exportFormat'), 0)
        if values['OTP'] == 'yes' or values['UID'] == 'yes':
            if not required_bits:
                raise ValueError('存储 VERIFY 结果前请选择 BCD16_MV 或 ADC12_3V3 编码')
            recipe += f"-EXPORT(FORMAT={values['_exportFormat']})"
    record['Recipe'] = recipe
    parse_recipe(recipe)
    if kind == 'verify':
        from flow_recipe import compile_recipe_rows, compile_result_export_plan_set
        from program_gen.flow_kinds import compile_flow_rows
        frame = pd.DataFrame([record])
        try:
            operations = compile_flow_rows(frame, workbook_identity='new-item', source_sha256=context['editor'].sha256)
            recipes = compile_recipe_rows(frame, context['workbook'].dataframe('pattern'))
            exports = compile_result_export_plan_set(frame, recipes, cp)
            compile_standard_verify_plans(operations, recipes, frame,
                {p.flow_row_index: p for p in exports.plans},
                nm_pattern_frame=context['workbook'].dataframe('NM_pattern'),
                version_frame=context['workbook'].dataframe('VERSION'))
        except (ValueError, TypeError, OverflowError) as error:
            return {**view, 'ready': False, 'issues': [{'field': 'parameters', 'message': str(error)}]}
    targets = payload.get('targets', [])
    parsed = parse_storage_mappings([{'item': item, 'targets': targets}], '新增测试项映射')
    if view['sharedMapping'] and targets != view['currentTargets']:
        raise ValueError('该逻辑项已有其他 CP 的全局映射；新增向导沿用原映射，修改请使用存储映射入口')
    requires_storage = any(values[flag] == 'yes' for flag in ('OTP', 'UID', 'PUMP'))
    if requires_storage and not targets:
        raise ValueError('OTP / UID / PUMP 启用时必须选择 ADDR_MAP 字段')
    if not targets and not view['sharedMapping'] and values.get('_storageMode') != 'none':
        raise ValueError('请选择存储字段，或明确选择“仅运行时结果，不存储”')
    catalog = context['storage']
    if catalog is None:
        raise ValueError('ADDR_MAP 尚有错误：' + '；'.join(e['message'] for e in context['errors']))
    if kind == 'trim' or targets:
        validate_storage_mapping_records(kind, parsed, catalog,
                                         [SimpleNamespace(item=item, cp=c, required_bits=required_bits) for c in view['relatedCps']])
    if values['UID'] == 'yes' and not any(t['page'].casefold() == 'uid' for t in targets):
        raise ValueError('UID=yes 需要选择 uid 页的存储字段')
    if kind == 'verify' and values['OTP'] == 'yes' and not any(t['page'].casefold() != 'uid' for t in targets):
        raise ValueError('VERIFY OTP=yes 需要选择非 uid 页的存储字段')
    before = payload.get('before')
    if type(before) is not int or before not in [p['before'] for p in view['positions']]:
        raise ValueError('请选择当前 CP 内完整测试项的插入位置')
    position = next(p for p in view['positions'] if p['before'] == before)
    after = [c for c in view['consumers'] if c['row'] >= position['row']]
    if (values['OTP'] == 'yes' or values['UID'] == 'yes') and not any(set(c['modules']) & {'COMMIT', 'BUILDMAP'} for c in after):
        raise ValueError('此位置之后没有同 CP 的 BUILDMAP / COMMIT；请将测试项插入存储节点之前')
    if values['PUMP'] == 'yes':
        from program_gen.core.fbist_pattern_plan import compile_pump_fbist_pattern_plan
        if not any('SETVPOSP' in c['modules'] for c in after):
            raise ValueError('PUMP 项必须放在同 CP 后续 SETVPOSP 之前')
    mappings = {k: list(context['payload'][k]) for k in ('trimStorageMappings', 'verifyStorageMappings')}
    mapping_key = 'trimStorageMappings' if kind == 'trim' else 'verifyStorageMappings'
    if not view['sharedMapping'] and (kind == 'trim' or targets):
        mappings[mapping_key] = [*mappings[mapping_key], {'item': item, 'targets': targets}]
    draft, raw, row = _append_record(context, payload, record, mappings)
    editor = context['editor']
    # Local ownership checks do not require a complete ProductCompilation.
    next_catalog = compile_addr_map_catalog(context['workbook'].dataframe('ADDR_MAP'),
                                            parse_storage_mappings(mappings['trimStorageMappings'], 'trim'),
                                            parse_storage_mappings(mappings['verifyStorageMappings'], 'verify'))
    validate_storage_role_occupancy(next_catalog)
    validate_storage_flow_occupancy(pd.concat([flow, pd.DataFrame([record])], ignore_index=True), next_catalog)
    if values['PUMP'] == 'yes':
        workbook = WorkbookReader(byte_loader=lambda _: raw).read(editor.name)
        compile_pump_fbist_pattern_plan(workbook)
    editor.ensure_source_current()
    return {**view, 'ready': True, 'issues': [], 'pendingValidation': True, 'recipeText': recipe,
            'draft': draft, 'row': row,
            'notice': '已完成当前项配置；整本依赖、消费者及生成有效性仍需检查。'}


def _editable_phase_rows(context, row):
    """Locate a contiguous native ADC/firmware group in the materialized draft."""
    from program_gen.flow_kinds import compile_flow_rows
    operations = compile_flow_rows(context['workbook'].dataframe('FLOW'),
                                   workbook_identity='flow-edit', source_sha256=context['editor'].sha256)
    index = next((i for i, operation in enumerate(operations) if operation.row + 2 == row), None)
    if type(row) is not int or index is None:
        raise ValueError('请选择有效 FLOW 行')
    selected = operations[index]
    kinds = {'ADC_TEST'} if selected.typed_kind == 'ADC_TEST' else {'VERIFY_HEX', 'VERIFY_KEIL'}
    if selected.typed_kind not in kinds:
        return []
    def same(operation):
        return (operation.typed_kind in kinds and operation.cp.casefold() == selected.cp.casefold()
                and operation.item.casefold() == selected.item.casefold()
                and operation.source_type.casefold() == selected.source_type.casefold())
    start = end = index
    while start > 0 and operations[start - 1].row + 1 == operations[start].row and same(operations[start - 1]): start -= 1
    while end + 1 < len(operations) and operations[end].row + 1 == operations[end + 1].row and same(operations[end + 1]): end += 1
    return [operation.row + 2 for operation in operations[start:end + 1]]


def _append_record(context, payload, record, mappings):
    records = record if isinstance(record, list) else [record]
    cp, before = records[0]['CP NO'], payload.get('before')
    editor, base = context['editor'], context['editor'].by_name['FLOW']
    draft = context['payload']
    additions = [*draft.get('appendRows', [])]
    source = next((r for r in base['appendableRows'] if _text(base['rows'][r - 1][0]['value']).upper() == cp), None)
    if source is None:
        raise ValueError('该 CP 没有可复用格式的可编辑 FLOW 行')
    row = base['maxRow'] + sum(op['sheet']=='FLOW' for op in additions) + 1
    additions.extend({'sheet':'FLOW','sourceRow':source,'copy':False} for _ in records)
    order = list(draft.get('flowOrder') or range(1, row))
    position = order.index(before) if before else len(order)
    order[position:position] = list(range(row, row + len(records)))
    changes = [*draft.get('changes', [])]
    for offset, record in enumerate(records):
        for index, column in enumerate(base['columns'], 1):
            if column['label'] in record:
                changes.append({'sheet':'FLOW','cell':f'{get_column_letter(index)}{row + offset}',
                                'old':None,'value':str(record[column['label']])})
    raw = editor.apply(editor.sha256, changes, additions, order, mappings['trimStorageMappings'], mappings['verifyStorageMappings'], draft.get('patternEdits'), draft.get('patternLinks'))
    return ({'changes': changes, 'appendRows': additions, 'flowOrder': order, **mappings,
             'patternEdits': draft.get('patternEdits', []), 'patternLinks': draft.get('patternLinks', editor.pattern_links)}, raw, order.index(row) + 1)


def _prepare_specialized(session, context, payload, values, view):
    if not view['supported']:
        raise ValueError(view['notice'])
    issues = list(view['issues'])
    item, cp = values.get('item', ''), values.get('CP NO', '')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,119}', item):
        issues.append({'field': 'item', 'message': '名称须以字母或下划线开头，只使用字母、数字、下划线，最多120字符'})
    canonical = {'PDR_TRIM': 'Pdr_Trim', 'PDR_VERIFY': 'Pdr_Verify'}.get(view['kind'])
    if canonical and item != canonical:
        issues.append({'field': 'item', 'message': '专用协议名称必须为 ' + canonical})
    record, field_issues = _specialized_record(values, view)
    issues.extend(field_issues)
    flow = context['workbook'].dataframe('FLOW')
    if any(_text(r.get('CP NO')).upper() == cp and _text(r.get('type')).lower() == record['type'] and logical_item_key(_text(r.get('item'))) == logical_item_key(item) for _, r in flow.iterrows()):
        issues.append({'field': 'item', 'message': '当前 CP 已存在同名逻辑测试项，请编辑原项'})
    if type(payload.get('before')) is not int or payload['before'] not in [p['before'] for p in view['positions']]:
        issues.append({'field': 'before', 'message': '请选择当前 CP 内完整测试项的插入位置'})
    if issues:
        return {**view, 'ready': False, 'issues': issues}
    records = [record]
    if values.get('_group'):
        from program_gen.core.flow_input import describe_flow_input
        phases = payload.get('phases')
        if not isinstance(phases, list) or not 1 <= len(phases) <= 20:
            raise ValueError('整组新增需要 1 至 20 个阶段')
        allowed = {'adc': {'ADC_TEST'}, 'firmware': {'VERIFY_HEX','VERIFY_KEIL'}}.get(values['_group'])
        if allowed is None: raise ValueError('未知阶段组')
        records = []
        for index, phase in enumerate(phases, 1):
            if not isinstance(phase, dict) or len(phase)>50 or any(not isinstance(k,str) or not isinstance(v,str) or len(v)>32767 for k,v in phase.items()):
                raise ValueError('阶段字段必须是文本对象')
            phase = {**phase, **{k:values.get(k,'') for k in ('CP NO','item','type','Hbin','Sbin','relay')}}
            phase_view = describe_flow_input(phase)
            if not phase_view['supported'] or phase_view['kind'] not in allowed:
                issues.append({'field':f'阶段 {index}','message':'阶段类型与当前组不匹配'})
                continue
            phase_record, errors = _specialized_record(phase, phase_view)
            issues.extend({**e,'field':f"阶段 {index} / {e['field']}"} for e in errors)
            records.append(phase_record)
        if issues: return {**view,'ready':False,'issues':issues}
    mappings = {k: list(context['payload'][k]) for k in ('trimStorageMappings', 'verifyStorageMappings')}
    draft, raw, row = _append_record(context, payload, records, mappings)
    try:
        _, compiled = session.compile(raw)
        issues = [{'field': '完整检查', 'message': d.message} for d in compiled.diagnostics.errors]
        if not compiled.is_valid and not issues:
            issues = [{'field': '完整检查', 'message': '当前草稿尚未通过编译检查'}]
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        issues = [{'field': '完整检查', 'message': str(error)}]
    context['editor'].ensure_source_current()
    if issues:
        return {**view, 'ready': False, 'issues': issues}
    return {**view, 'ready': True, 'issues': [], 'pendingValidation': True,
            'draft': draft, 'row': row, 'recipeText': '\n'.join(f"{i}. {r.get('sub','/')} · {r['mode']} · {r['Recipe'] or '原生下载/专用流程'}" for i,r in enumerate(records,1)), 'rowCount': len(records),
            'notice': '专用项与当前草稿已通过编译检查；后续修改后仍需重新检查。'}


def _specialized_record(values, view):
    issues = []
    record = {k: values.get(k, '') for k in ('CP NO', 'item', 'type', 'mode')}
    for field in view['fields']:
        value = values.get(field['name'], str(field.get('default', '/')))
        if field['required'] and (value == '' or value == '/' and field['name'] != 'UNIT'):
            issues.append({'field': field['name'], 'message': '请填写 ' + field['label']})
        record[field['name']] = value
    if view['kind'] == 'DAC_TEST' and not re.fullmatch(r'[1-9]\d*', record.get('target', '')):
        issues.append({'field': 'target', 'message': 'DAC 分辨率必须是正整数满量程码数'})
    # Protocol constants are owned by the native planner, not by hidden form state.
    record.update(view['fixedValues'])
    if view['kind'] == 'PDR_TRIM':
        for flag in ('OTP', 'UID'):
            record[flag] = values.get(flag, 'no')
            if record[flag] not in ('yes', 'no'):
                issues.append({'field': flag, 'message': '请选择 yes / no'})
    return record, issues
