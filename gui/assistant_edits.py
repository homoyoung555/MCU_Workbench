"""Prepare field-only edits of existing literal writes without rebuilding a flow."""
from copy import deepcopy
import re

from swd_authoring import EncodingDB, validate_request


def _word(value):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r'(?:0[xX][0-9a-fA-F]{1,8}|[0-9]{1,10})', value.strip()):
        number = int(value, 16 if value.strip().lower().startswith('0x') else 10)
    else:
        raise ValueError('仅可修改明确32位常量写入，不能解释符号或复合位移')
    if not 0 <= number <= 0xFFFFFFFF:
        raise ValueError('写入值超出32位范围')
    return number


def prepare_edit(snapshot, operations):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('document'), dict):
        raise ValueError('请先选择已有SWD步骤文档')
    popup = snapshot.get('popupDraft')
    target = popup or snapshot['document']
    if popup and popup.get('documentId') != snapshot['document'].get('id'):
        raise ValueError('弹窗与当前文档不一致')
    original = target.get('rows')
    if not isinstance(original, list) or not isinstance(operations, list) or not 1 <= len(operations) <= 64:
        raise ValueError('需提供1至64项明确的字段修改')
    rows, db = deepcopy(original), EncodingDB('py32f420')
    version = db.knowledge_version()
    used, diff = {}, []
    for operation in operations:
        keys = {'rowIndex', 'peripheral', 'register', 'field', 'value'}
        if not isinstance(operation, dict) or set(operation) != keys:
            raise ValueError('修改须且仅须包含行下标、外设实例、寄存器、字段和值')
        index = operation['rowIndex']
        if type(index) is not int or not 0 <= index < len(rows):
            raise ValueError('修改行下标无效')
        row = rows[index]
        if row.get('type') != 'W' or row.get('step') != '/':
            raise ValueError('当前只支持type=W且step=/的直接常量字段修改')
        peri, reg, field = (operation[key] for key in ('peripheral', 'register', 'field'))
        if any(not isinstance(value, str) or not value for value in (peri, reg, field)):
            raise ValueError('外设实例、寄存器与字段必须明确')
        if (peri.upper() == 'RCC' and reg.upper() == 'CSR') or (peri.upper() in ('ADC', 'ADC1', 'ADC2') and reg.upper() == 'SMPR3'):
            raise ValueError('该寄存器存在尚未裁决的来源冲突')
        directive = {'kind': 'field_value', 'peri': peri, 'reg': reg, 'field': field, 'value': operation['value']}
        _, issues = validate_request({'chip': 'py32f420', 'name': 'Edit', 'directives': [directive]}, db)
        if issues:
            raise ValueError('; '.join(str(issue) for issue in issues))
        info = db.field(peri, reg, field)
        if not info.get('address') or _word(info['address']) != _word(row.get('addr')):
            raise ValueError('指定外设实例/寄存器与原行地址不一致或存在歧义')
        # This edits a previously authored literal. It is not a runtime RMW.
        # Refuse mixed access words where preserving a literal could retrigger
        # write-one/command bits, even when the requested field itself is RW.
        for name in db.register_fields(peri, reg):
            if str(db.field(peri, reg, name).get('access', '')).upper() not in {'RW', 'R', 'RO'}:
                raise ValueError('修改目标寄存器含未知或特殊访问语义，不能安全重写原字')
        mask = ((1 << info['width']) - 1) << info['pos']
        encoded = operation['value'] << info['pos']
        previous_mask, previous_bits = used.get(index, (0, 0))
        if (previous_bits ^ encoded) & previous_mask & mask:
            raise ValueError('同一字段存在矛盾修改')
        used[index] = (previous_mask | mask, (previous_bits & ~mask) | encoded)
        before = _word(row.get('data'))
        after = (before & ~mask) | encoded
        if after != before:
            diff.append({'rowIndex': index, 'field': f'{peri}.{reg}.{field}',
                         'before': f'0x{before:08X}', 'after': f'0x{after:08X}',
                         'mask': f'0x{mask:08X}', 'value': operation['value']})
            row['data'] = f'0x{after:08X}'
    if not diff:
        raise ValueError('指定字段已经是目标值，没有可应用差异')
    if version != db.knowledge_version():
        raise ValueError('知识版本已改变，请重新准备修改')
    return {'kind': 'edit', 'name': '修改 ' + snapshot['document']['name'],
            'documentId': snapshot['document']['id'], 'scope': 'popup' if popup else 'document',
            'pattern': popup.get('pattern') if popup else snapshot.get('pattern'),
            'beforeRows': deepcopy(original), 'rows': rows, 'diff': diff, 'knowledgeVersion': version,
            'validation': {'changedFields': 'passed', 'existingSequence': 'not_revalidated',
                           'platformCompiler': 'not_run', 'hardware': 'not_verified'}}
