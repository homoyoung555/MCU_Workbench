"""Project row-scoped Pattern choices onto the existing Recipe cell edits."""
from copy import deepcopy

from openpyxl.utils import get_column_letter

from flow_recipe import parse_recipe, compile_result_export_plan_set
from gui.recipe_editor import inspect_recipe
from program_gen.core.recipe_trim import recipe_pattern_name
from program_gen.core.fbist_pattern_plan import compile_ordinary_fbist_pattern_plan
from program_gen.workbook import WorkbookReader


def trim_pattern(session, payload):
    from gui.server import fingerprint

    editor = session.editor
    editor.ensure_source_current()
    row = payload.get('row')
    if type(row) is not int or row < 2:
        raise ValueError('请选择普通 TRIM / VERIFY 的 FLOW 行')
    changes = payload.get('changes')
    additions, order = payload.get('appendRows', []), payload.get('flowOrder', [])

    def apply(edits):
        return editor.apply(payload.get('baseSha256'), edits, additions, order,
                            payload.get('trimStorageMappings'), payload.get('verifyStorageMappings'), payload.get('patternEdits'), payload.get('patternLinks'))

    raw = apply(changes)
    normalized = {**payload,
                  'trimStorageMappings': payload.get('trimStorageMappings', editor.trim_storage_mappings),
                  'verifyStorageMappings': payload.get('verifyStorageMappings', editor.verify_storage_mappings)}
    key = fingerprint(normalized)
    projection = getattr(session, 'trim_pattern_cache', None)
    if projection and projection['editor'] is editor and projection['key'] == key and projection['row'] == row:
        result, recipe = deepcopy(projection['result']), deepcopy(projection['recipe'])
        uses = result['uses']
    else:
        cached = getattr(session, 'item_cache', None)
        if cached and cached['key'] == key:
            workbook, compiled = cached['workbook'], cached['compilation']
        else:
            workbook = WorkbookReader(byte_loader=lambda _: raw).read(editor.name)
            compiled = None
        specs = compiled.plan.catalogs.trim_specs if compiled and compiled.is_valid else {}
        spec = specs.get(row - 2)
        flow = workbook.dataframe('FLOW')
        if row - 2 >= len(flow):
            raise ValueError('FLOW 行不存在，请重新读取草稿')
        record = flow.iloc[row - 2]
        def field(name):
            value = record.get(name)
            return value.strip() if isinstance(value, str) else ''
        item, cp, mode = field('item'), field('CP NO'), field('mode')
        kind = field('type').casefold()
        if kind not in ('trim', 'verify') or not item or not cp:
            raise ValueError('请先填写当前行的 CP NO、item，并将 type 设为 trim 或 verify')
        if spec is None and (mode.casefold() not in ('', 'fbist') or item.casefold() in ('pdr_trim', 'bor_trim')):
            raise ValueError('此入口支持普通 FBIST TRIM / VERIFY；专用流程请在 Recipe 编辑器配置')
        text = record.get('Recipe')
        text = text if isinstance(text, str) else ''
        if kind == 'verify' and not text.strip():
            # Preserve the native legacy VERIFY chain, including UID-implied export.
            exports = compile_result_export_plan_set(flow.loc[[row - 2]], {}, cp)
            text = 'ENTER-JUDGE' + ('-EXPORT' if exports.plans else '')
        recipe = inspect_recipe({'text': text, 'item': item, 'type': kind, 'mode': mode or 'fbist'})
        if recipe['error']:
            raise ValueError(recipe['error'])
        calls = parse_recipe(text or recipe['defaultText'])
        plan = compiled.plan.catalogs.fbist_pattern_plan if compiled and compiled.is_valid else compile_ordinary_fbist_pattern_plan(workbook)
        patterns = {p.pattern_name: p for p in plan.patterns}
        enter_ops = iter(op for op in spec.operations if op.kind == 'ENTER') if spec else iter(())
        uses = []
        for index, call in enumerate(calls):
            if call.name not in ('ENTER', 'TRIM', 'RUN', 'DEPEND'):
                continue
            role = ('verify mode' if (call.named_parameter('ROLE') or kind.upper()) == 'VERIFY' else 'trim mode') if call.name == 'ENTER' else 'trim dac'
            implicit = call.name in ('ENTER', 'TRIM')
            default = recipe_pattern_name(item, role) if implicit else None
            current = ((next(enter_ops).reference if call.name == 'ENTER' else spec.dac.pattern_name) if spec else call.named_parameter('PATTERN') or default) if implicit else call.argument
            names = list(patterns) if call.name == 'RUN' else list(dict.fromkeys(
                r.output_pattern for r in plan.rows if r.role == role and r.output_pattern in patterns and not r.excluded))
            options = [{'name': name, 'description': '；'.join(
                            f'{w.addr_bits}: ' + ', '.join(f.field_name for f in w.fields)
                            for w in patterns[name].writes)} for name in names]
            if call.name == 'DEPEND':
                options = []
                for i, dep in flow.iloc[:row - 2].iterrows():
                    dep_item = dep.get('item')
                    if not isinstance(dep_item, str) or dep.get('CP NO') != cp or str(dep.get('type')).casefold() != 'trim' or dep_item.casefold() == item.casefold():
                        continue
                    name = recipe_pattern_name(dep_item, 'trim dac')
                    if name in patterns:
                        description = f'FLOW 第 {i + 2} 行 · ' + name
                        if i in specs:
                            description += ' · 结果：' + specs[i].dac_final_symbol
                        options.append({'name': dep_item, 'description': description})
            # Only a compiled reference may represent an external Pattern or alias.
            if spec and current not in [o['name'] for o in options]:
                options.insert(0, {'name': current, 'description': '当前 Recipe 已解析的映射'})
            explicit = not implicit or call.named_parameter('PATTERN') is not None
            uses.append({'step': index, 'module': call.name,
                         'label': {'ENTER': '进入测试模式', 'TRIM': '设置 DAC', 'RUN': '执行 Pattern', 'DEPEND': '依赖测试项'}[call.name],
                         'current': current, 'default': default, 'explicit': explicit, 'canReset': implicit,
                         'source': ('Recipe 显式选择' if explicit else '按当前 item / 角色解析') + ('' if current in [o['name'] for o in options] else '（尚未匹配，请选择）'),
                         'options': options})
        result = {'row': row, 'cp': cp, 'item': item, 'uses': uses, 'recipeText': text or recipe['defaultText'],
                  'pendingValidation': not bool(compiled and compiled.is_valid),
                  'notice': 'mode 尚未填写，当前按 FBIST 的默认 Recipe 配置映射；完成后仍需填写测试参数并检查。' if not mode else ''}
        session.trim_pattern_cache = {'editor': editor, 'key': key, 'row': row,
                                      'result': deepcopy(result), 'recipe': deepcopy(recipe)}
    if 'pattern' not in payload:
        editor.ensure_source_current()
        return result
    step, selected = payload.get('step'), payload['pattern']
    use = next((u for u in uses if type(step) is int and u['step'] == step), None)
    if use is None:
        raise ValueError('请选择当前测试项的有效 Pattern 用途')
    if selected is not None and (not isinstance(selected, str) or not selected):
        raise ValueError('此用途必须绑定 Pattern，不能解除；可恢复按 item 解析')
    if selected is not None and selected not in [o['name'] for o in use['options']]:
        raise ValueError('所选 Pattern 不存在或不适用于此用途')
    if use['module'] in ('RUN', 'DEPEND'):
        if selected is None:
            raise ValueError('此步骤必须显式选择映射，不能恢复按 item 解析')
        arguments = [selected]
    else:
        arguments = [a.strip() for a in recipe['steps'][step]['arguments'].split(',')
                     if a.strip() and a.split('=', 1)[0].strip().upper() != 'PATTERN']
        if selected is not None:
            arguments.append('PATTERN=' + selected)
    recipe['steps'][step]['arguments'] = ','.join(arguments)
    value = '\n'.join(s['module'] + ('(' + s['arguments'] + ')' if s['arguments'] else '')
                      for s in recipe['steps'])
    parse_recipe(value)
    result['recipeText'] = value
    # Editor edits use original row identities, while compilation uses displayed order.
    original_row = order[row - 1] if order else row
    sheet = editor.by_name['FLOW']
    column = next(i for i, c in enumerate(sheet['columns']) if c['label'] == 'Recipe')
    if original_row <= sheet['maxRow']:
        old = sheet['rows'][original_row - 1][column]['value']
    else:
        operation = additions[original_row - sheet['maxRow'] - 1]
        old = sheet['rows'][operation['sourceRow'] - 1][column]['value'] if operation['copy'] else None
    cell = f'{get_column_letter(column + 1)}{original_row}'
    change = {'sheet': 'FLOW', 'cell': cell, 'old': old, 'value': value}
    edits = [c for c in changes if (c['sheet'], c['cell']) != ('FLOW', cell)] + [change]
    apply(edits)  # Mapping edits never certify a complete test row.
    editor.ensure_source_current()
    use['current'] = selected if selected is not None else use['default']
    use['explicit'] = selected is not None
    use['source'] = 'Recipe 显式选择（待检查）' if selected is not None else '按当前 item / 角色解析（待检查）'
    result['pendingValidation'] = True
    session.trim_pattern_cache = {'editor': editor, 'key': fingerprint({**normalized, 'changes': edits}),
                                  'row': row, 'result': deepcopy(result), 'recipe': deepcopy(recipe)}
    return {**result, 'valid': True, 'change': change, 'diagnostics': [], 'links': []}
