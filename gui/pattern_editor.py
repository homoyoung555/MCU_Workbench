"""Item-scoped Pattern edits with template-preserving OOXML materialization."""
from copy import deepcopy
import re
import xml.etree.ElementTree as ET

from openpyxl.utils import coordinate_to_tuple, get_column_letter

from gui.workbook_editor import NS


def pattern_items(editor):
    sheet = editor.by_name.get('pattern')
    if not sheet:
        return []
    labels = [c['label'] for c in sheet['columns']]
    if labels != ['item', 'addr', 'description', 'pattern']:
        return []
    items, current, group = [], None, None
    for row, cells in enumerate(sheet['rows'][1:], 2):
        name, addr, description, role = [c['value'] for c in cells]
        if name is not None and str(name).strip():
            name = str(name).strip()
            if current is None or current['item'] != name:
                if current:
                    current['end'] = row - 1
                current = {'item': name, 'start': row, 'end': sheet['maxRow'], 'groups': []}
                items.append(current)
                group = None
        if current is None:
            continue
        if role is not None and str(role).strip():
            role = str(role).strip()
            if group is None or group['role'] != role:
                group = {'role': role, 'steps': []}
                current['groups'].append(group)
        if description is not None and str(description).strip() or addr is not None and str(addr).strip():
            if group is None:
                group = {'role': '', 'steps': []}
                current['groups'].append(group)
            group['steps'].append({'sourceRow': row, 'addr': '' if addr is None else str(addr),
                                   'description': '' if description is None else str(description)})
    seen = set()
    for item in items:
        item['editable'] = item['item'] not in seen and all(
            cell['editable'] or str(cell['reason']).startswith('合并单元格的从格')
            for row in sheet['rows'][item['start'] - 1:item['end']] for cell in row) and all(
                re.fullmatch(r'[01]{7}', step['addr'])
                for group in item['groups'] for step in group['steps'])
        seen.add(item['item'])
    duplicates = {i['item'] for i in items if sum(j['item'] == i['item'] for j in items) > 1}
    for item in items:
        if item['item'] in duplicates:
            item['editable'] = False
    return items


def validate_edits(editor, edits):
    if not isinstance(edits, list) or len(edits) > 200:
        raise ValueError('Pattern修改必须是至多200个item的数组')
    originals = {i['item']: i for i in pattern_items(editor)}
    sheet = editor.by_name.get('pattern')
    if edits and (not sheet or [c['label'] for c in sheet['columns']] != ['item', 'addr', 'description', 'pattern']):
        raise ValueError('Pattern编辑要求原模板的item、addr、description、pattern四列')
    if edits and sheet.get('note', '').startswith('含公式'):
        raise ValueError('Pattern模板只读：' + sheet['note'])
    result, seen, count = [], set(), 0
    for entry in edits:
        if not isinstance(entry, dict) or set(entry) != {'item', 'groups'}:
            raise ValueError('Pattern item修改格式错误')
        name = _text(entry['item'], 'item', 120)
        if not name or name != name.strip() or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('Pattern item仅支持字母、数字、下划线，且不能以数字开头')
        if name.casefold() in seen:
            raise ValueError('Pattern item重复')
        seen.add(name.casefold())
        original = originals.get(name)
        if not original and any(n.casefold() == name.casefold() for n in originals):
            raise ValueError('新item与既有名称仅大小写不同')
        if original and not original['editable']:
            raise ValueError(f'{name}含只读或非连续记录，请在原表处理')
        groups = entry['groups']
        if not isinstance(groups, list) or not groups or len(groups) > 100:
            raise ValueError(f'{name}至少保留一个用途')
        source_rows, roles, cleaned = set(), set(), []
        for group in groups:
            if not isinstance(group, dict) or set(group) != {'role', 'steps'}:
                raise ValueError('Pattern用途格式错误')
            role = _text(group['role'], '用途', 120)
            if not role.strip() or role != role.strip() or role in roles:
                raise ValueError('Pattern用途不能为空或重复')
            roles.add(role)
            steps = group['steps']
            if not isinstance(steps, list) or not steps or len(steps) > 1000:
                raise ValueError(f'{name}/{role}尚未添加FB写入')
            normalized = []
            for step in steps:
                if not isinstance(step, dict) or set(step) != {'sourceRow', 'addr', 'description'}:
                    raise ValueError('Pattern写入步骤格式错误')
                source = step['sourceRow']
                if source is not None:
                    if type(source) is not int or not original or not original['start'] <= source <= original['end'] or source in source_rows:
                        raise ValueError('Pattern来源行无效或重复')
                    source_rows.add(source)
                address = _text(step['addr'], 'FB地址', 32)
                description = _text(step['description'], '字段', 32767)
                if not re.fullmatch(r'[01]{7}', address):
                    raise ValueError('FB地址必须为7位二进制')
                if not description.strip() or any(not line.split('=', 1)[-1].strip() for line in description.splitlines() if line.strip()):
                    raise ValueError(f'{name}/{role}存在尚未填写的字段值')
                for line in description.splitlines():
                    field = re.search(r'[\[<](\d+)\s*:\s*(\d+)[\]>]\s*=\s*([01xX]*)(\*)?\s*$', line)
                    if field and len(field[3]) != abs(int(field[1]) - int(field[2])) + 1:
                        raise ValueError(f'{name}/{role}字段值位数尚未填完整：{line}')
                normalized.append({'sourceRow': source, 'addr': address, 'description': description})
                count += 1
            cleaned.append({'role': role, 'steps': normalized})
        result.append({'item': name, 'groups': cleaned})
    if count > 5000:
        raise ValueError('单次Pattern修改超过5000次写入')
    return result


def _text(value, label, limit):
    if not isinstance(value, str) or len(value) > limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]', value) or value.lstrip().startswith('='):
        raise ValueError(label + '内容无效')
    return value


def patch_pattern_xml(xml, editor, edits):
    """Rebuild changed item blocks only; retain other XML parts and row styles."""
    edits = validate_edits(editor, edits)
    if not edits:
        return xml
    root = ET.fromstring(xml)
    for tag in ('sheetProtection', 'hyperlinks', 'conditionalFormatting', 'autoFilter', 'tableParts',
                'drawing', 'legacyDrawing', 'rowBreaks', 'extLst', 'dataValidations'):
        if root.find(NS + tag) is not None:
            raise ValueError('pattern含依赖行号的对象，当前不能安全增删步骤：' + tag)
    if root.findall('.//' + NS + 'f'):
        raise ValueError('pattern含公式，不能调整记录结构')
    original_items = pattern_items(editor)
    by_name = {i['item']: i for i in original_items}
    old_rows = {int(r.attrib['r']): r for r in root.find(NS + 'sheetData')}
    template = next((r for n, r in old_rows.items() if n > 1 and r.find(NS + 'c') is not None), None)
    if template is None:
        raise ValueError('pattern缺少可沿用的模板数据行')
    output, old_to_new, new_merges = [], {}, []
    changed = {e['item']: e for e in edits}
    changed_ranges = [(by_name[n]['start'], by_name[n]['end']) for n in changed if n in by_name]
    starts = {i['start']: i for i in original_items if i['item'] in changed}
    prefix = re.search(r'<((?:[\w.-]+:)?)worksheet\b', xml)[1]

    def append_original(n):
        target = len(output) + 1
        old_to_new[n] = target
        row = deepcopy(old_rows.get(n, ET.Element(NS + 'row', {'r': str(n)})))
        row.attrib['r'] = str(target)
        for cell in row:
            if 'r' in cell.attrib:
                cell.attrib['r'] = re.sub(r'\d+$', str(target), cell.attrib['r'])
        output.append(row)

    def append_item(entry):
        first = len(output) + 1
        original = by_name.get(entry['item'])
        for group in entry['groups']:
            group_first = len(output) + 1
            for step in group['steps']:
                n = len(output) + 1
                source = old_rows.get(step['sourceRow']) if step['sourceRow'] else None
                row = deepcopy(source if source is not None else template)
                row.attrib['r'] = str(n)
                # The template has merged A/D children with different border-only styles;
                # reuse each group's master cell styles when making a new master.
                masters = old_rows.get(original['start'], template) if original else template
                for cell in list(row):
                    row.remove(cell)
                vals = {1: entry['item'] if n == first else '', 2: step['addr'],
                        3: step['description'], 4: group['role'] if n == group_first else ''}
                for c in range(1, 5):
                    candidates = list(masters) if c in (1, 4) else list(source if source is not None else template)
                    old = next((cell for cell in candidates if re.sub(r'\d+$', '', cell.attrib.get('r', '')) == get_column_letter(c)), None)
                    attrs = {'r': get_column_letter(c) + str(n)}
                    if old is not None and 's' in old.attrib:
                        attrs['s'] = old.attrib['s']
                    cell = ET.SubElement(row, NS + 'c', attrs)
                    if vals[c]:
                        cell.attrib['t'] = 'inlineStr'
                        text = ET.SubElement(ET.SubElement(cell, NS + 'is'), NS + 't', {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'})
                        text.text = vals[c]
                output.append(row)
            if len(output) > group_first:
                new_merges.append(f'D{group_first}:D{len(output)}')
        if len(output) > first:
            new_merges.append(f'A{first}:A{len(output)}')
        output.append(ET.Element(NS + 'row', {'r': str(len(output) + 1)}))

    n = 1
    while n <= editor.by_name['pattern']['maxRow']:
        if n in starts:
            item = starts[n]
            append_item(changed[item['item']])
            n = item['end'] + 1
        else:
            append_original(n)
            n += 1
    for entry in edits:
        if entry['item'] not in by_name:
            append_item(entry)
    if len(output) * 4 + sum(s['maxRow'] * s['maxCol'] for s in editor.sheets if s['name'] != 'pattern') > 500000:
        raise ValueError('Pattern修改超过工作簿大小限制')
    merges = root.find(NS + 'mergeCells')
    if merges is not None:
        for area in merges:
            a, b = area.attrib['ref'].split(':')
            r1, c1 = coordinate_to_tuple(a)
            r2, c2 = coordinate_to_tuple(b)
            overlaps = [(lo, hi) for lo, hi in changed_ranges if r1 <= hi and r2 >= lo]
            if overlaps:
                if c1 != c2 or c1 not in (1, 4) or not any(lo <= r1 <= r2 <= hi for lo, hi in overlaps):
                    raise ValueError('Pattern合并范围跨item或不属于item/用途列')
                continue
            new_merges.append(f'{get_column_letter(c1)}{old_to_new[r1]}:{get_column_letter(c2)}{old_to_new[r2]}')
    # Serialize only sheetData/mergeCells; keep namespace declarations and all
    # unrelated worksheet markup byte-identical, including extensions and styles.
    def serialize(element):
        value = ET.tostring(element, encoding='unicode')
        value = re.sub(r'\s+xmlns:ns\d+="[^"]+"', '', value)
        return re.sub(r'(<\/?)(?:ns\d+:)', lambda m: m[1] + prefix, value)
    data = '<' + prefix + 'sheetData>' + ''.join(serialize(r) for r in output) + '</' + prefix + 'sheetData>'
    xml = re.sub(r'<(?P<t>(?:[\w.-]+:)?sheetData)\b[^>]*>.*?</(?P=t)>', lambda _: data, xml, count=1, flags=re.S)
    merge_xml = '<' + prefix + 'mergeCells count="' + str(len(new_merges)) + '">' + ''.join(
        '<' + prefix + 'mergeCell ref="' + m + '"/>' for m in new_merges) + '</' + prefix + 'mergeCells>' if new_merges else ''
    match = re.search(r'<(?P<t>(?:[\w.-]+:)?mergeCells)\b[^>]*(?:/>|>.*?</(?P=t)>)', xml, re.S)
    if match:
        xml = xml[:match.start()] + merge_xml + xml[match.end():]
    else:
        close = '</' + prefix + 'sheetData>'
        xml = xml.replace(close, close + merge_xml, 1)
    xml = re.sub(r'(<(?:[\w.-]+:)?dimension\b[^>]*\bref=")[^"]+(" *)', lambda m: m[1] + f'A1:D{len(output)}' + m[2], xml, count=1)
    ET.fromstring(xml)
    return xml
