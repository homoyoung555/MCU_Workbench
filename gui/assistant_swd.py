"""Adapt deterministic compiler results to the existing SWD file boundary.

This module creates independent artifacts, never workspace edits or links.
"""
from io import BytesIO
from dataclasses import dataclass, field
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

import openpyxl

from gui.swd_generator import export_excel, generate_pattern, load_excel, pin_defaults

_PROVENANCE = 'mcu/ai-provenance.json'
_CONTENT_TYPE = 'application/vnd.mcu.ai-provenance.v1+json'
_CONFIG_KEYS = ('chipId', 'productProfileId', 'platform', 'pins', 'initialState', 'knowledgeVersion')
_ROW_KEYS = ('pattern', 'addr', 'data', 'type', 'step', 'reset value', 'continue', 'description')


def _digest(rows, config):
    semantic = {'version': 1, 'config': {key: config[key] for key in _CONFIG_KEYS},
                'rows': [{key: row.get(key) for key in _ROW_KEYS} for row in rows]}
    return hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def _embed(raw, record):
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, 'w') as target:
        for entry in source.infolist():
            if entry.filename == _PROVENANCE:
                continue
            content = source.read(entry.filename)
            if entry.filename == '[Content_Types].xml':
                tree = ET.fromstring(content)
                for item in list(tree):
                    if item.attrib.get('PartName') == '/' + _PROVENANCE:
                        tree.remove(item)
                ET.SubElement(tree, '{http://schemas.openxmlformats.org/package/2006/content-types}Override',
                              PartName='/' + _PROVENANCE, ContentType=_CONTENT_TYPE)
                content = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
            elif entry.filename == '_rels/.rels':
                tree = ET.fromstring(content)
                for item in list(tree):
                    if item.attrib.get('Type') == 'urn:mcu:relationships:ai-provenance:v1':
                        tree.remove(item)
                ET.SubElement(tree, '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
                              Id='mcuAiProvenanceV1', Type='urn:mcu:relationships:ai-provenance:v1',
                              Target=_PROVENANCE)
                content = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
            target.writestr(entry, content)
        target.writestr(_PROVENANCE, json.dumps(record, ensure_ascii=False, sort_keys=True))
    return output.getvalue()


def bind_material_evidence(candidate, evidence):
    """Keep the frozen cross-source evidence with the independent Excel."""
    provenance = read_provenance(candidate['excel'])
    if provenance.get('status') != 'consistent':
        raise CandidateError('INVALID_PROVENANCE', '候选来源元数据已失效')
    record = provenance['record']
    record['materialEvidence'] = evidence
    raw = _embed(candidate['excel'], record)
    return {**candidate, 'excel': raw, 'fileSha256': hashlib.sha256(raw).hexdigest(),
            'materialEvidence': evidence}


def read_provenance(raw):
    """Report consistency only: embedded metadata is not a trusted signature."""
    try:
        with ZipFile(BytesIO(raw)) as package:
            if _PROVENANCE not in package.namelist():
                return {'status': 'missing'}
            info = package.getinfo(_PROVENANCE)
            if info.file_size > 2_000_000:
                return {'status': 'unknown', 'reason': 'metadata_too_large'}
            record = json.loads(package.read(_PROVENANCE))
        if not isinstance(record, dict) or record.get('schemaVersion') != 1:
            return {'status': 'unknown', 'reason': 'unsupported_version'}
        model, _ = load_excel(raw)
        if _digest(model['rows'], record) != record.get('contentDigest'):
            return {'status': 'modified'}
        return {'status': 'consistent', 'record': record}
    except (BadZipFile, ValueError, KeyError, TypeError):
        return {'status': 'unknown', 'reason': 'invalid'}


class CandidateError(ValueError):
    def __init__(self, code, message, questions=None):
        self.code = code
        self.questions = [] if questions is None else questions
        super().__init__(f'{code}: {message}')


def _word(value, label):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise CandidateError('INVALID_WORD', f'{label}必须是32位无符号整数')
    return value


@dataclass(frozen=True)
class Comparison:
    addr: int
    data: int
    mask: int
    type: str
    desc: str = ''
    phase: int = 11
    sources: list = field(default_factory=list)


def compare_row(address, *, compare_mask, expected_value, description=''):
    """One masked read; mixed comparisons are deliberately not split."""
    _word(address, '地址')
    mask = _word(compare_mask, '比较掩码')
    expected = _word(expected_value, '期望值')
    if not mask or expected & ~mask:
        raise CandidateError('INVALID_COMPARE', '比较掩码不能为空，期望值不能超出掩码')
    if expected not in (0, mask):
        raise CandidateError('MIXED_COMPARE_UNSUPPORTED', '当前步骤语言无法保证混合位比较为同一次读取')
    # Domain data is a selected-bit mask for either comparison polarity.
    return Comparison(address, mask, mask, 'C_H' if expected else 'C_L', description)


def export_candidate(result, *, chip_id, product_profile_id, platform,
                     initial_state, knowledge_version, static_validated=False):
    """Export only a fully compiled configuration with explicit reset precondition.

    Reset is a caller-confirmed precondition, not a hardware action or claim.
    The legacy SWD initialization is retained; it does not prove peripheral reset.
    """
    if chip_id != 'py32f420' or not isinstance(product_profile_id, str) or product_profile_id.upper() not in {'PT104', 'PCD009'}:
        raise CandidateError('UNSUPPORTED_PRODUCT', '芯片与产品配置映射尚未支持')
    if platform not in {'chroma', 's100'}:
        raise CandidateError('UNSUPPORTED_PLATFORM', '请选择Chroma或S100')
    if initial_state != 'reset':
        raise CandidateError('UNKNOWN_INITIAL_STATE', '整字配置需要已确认的复位初始条件')
    if not knowledge_version:
        raise CandidateError('MISSING_KNOWLEDGE_VERSION', '必须绑定资料版本')
    if result.warnings:
        raise CandidateError('INCOMPLETE_COMPILATION', '存在未解决编译诊断：' + '; '.join(result.warnings))
    if not result.rows:
        raise CandidateError('INCOMPLETE_COMPILATION', '空配置')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', result.name):
        raise CandidateError('INVALID_PATTERN_NAME', 'Pattern名称需为1至80位字母、数字或下划线且不以数字开头')
    rows = []
    for index, item in enumerate(result.rows):
        if item.type not in {'W', 'C_H', 'C_L'}:
            raise CandidateError('UNSUPPORTED_OPERATION', f'尚未验证的操作：{item.type}')
        address = _word(item.addr, '地址')
        if address % 4:
            raise CandidateError('UNALIGNED_ADDRESS', '32位寄存器地址必须按4字节对齐')
        value = _word(item.data, '数据')
        if item.type in {'C_H', 'C_L'}:
            mask = _word(item.mask, '比较掩码')
            if not mask or value != mask:
                raise CandidateError('INVALID_COMPARE', '领域比较行必须提供一致的选中位掩码')
            if item.type == 'C_L':
                value = (~mask) & 0xFFFFFFFF
        rows.append({'row': None, 'pattern': result.name if index == 0 else None,
                     'addr': f'0x{address:08X}', 'data': f'0x{value:08X}', 'type': item.type,
                     'step': '/', 'reset value': None, 'continue': 'Y' if index == 0 else None,
                     'description': item.desc})
    book = openpyxl.Workbook()
    book.active.title = 'Sheet1'
    book.active.append(['pattern', 'addr', 'data', 'type', 'step', 'reset value', 'continue', 'description'])
    stream = BytesIO()
    book.save(stream)
    raw = export_excel(stream.getvalue(), 'Sheet1', rows)
    loaded, _ = load_excel(raw)
    pins = pin_defaults(product_profile_id)
    pattern = generate_pattern(result.name, loaded['rows'], platform, chip=product_profile_id, pins=pins)
    config = {'chipId': chip_id, 'productProfileId': product_profile_id, 'platform': platform,
              'pins': pins, 'initialState': initial_state, 'knowledgeVersion': knowledge_version}
    validation = {'format': 'passed', 'staticRules': 'passed' if static_validated else 'not_run',
                  'targetGeneration': 'passed',
                  'platformCompiler': 'not_run', 'hardware': 'not_verified'}
    digest = _digest(loaded['rows'], config)
    record = {'schemaVersion': 1, **config, 'contentDigest': digest, 'validation': validation,
              'steps': [{'id': f'{digest[:16]}:{index + 1}', 'sources': list(item.sources),
                         'phase': item.phase, 'mask': item.mask}
                        for index, item in enumerate(result.rows)]}
    raw = _embed(raw, record)
    return {'excel': raw, 'pattern': pattern, 'rows': loaded['rows'], **config,
            'fileSha256': hashlib.sha256(raw).hexdigest(), 'validation': validation}


def prepare_candidate(payload, *, product_profile_id, platform, initial_state, db=None):
    """Public offline path: validate real intents, compile, then export independently.

    An injected DB may include validated, address-scoped user reset evidence.
    Live workspace materials must still be reconciled by the caller.
    """
    from swd_authoring import Composer, EncodingDB, validate_request

    if not isinstance(payload, dict) or not isinstance(payload.get('directives'), list):
        raise CandidateError('INVALID_REQUEST', '配置必须包含directives列表')
    # These documented cross-source conflicts have not yet been adjudicated.
    # Blocking the affected register avoids silently preferring the bundled cache.
    for directive in payload['directives']:
        if not isinstance(directive, dict):
            raise CandidateError('INVALID_REQUEST', '每条配置意图必须是对象')
        peri, reg = str(directive.get('peri', '')).upper(), str(directive.get('reg', '')).upper()
        if (peri == 'RCC' and reg == 'CSR') or (peri in {'ADC', 'ADC1', 'ADC2'} and reg == 'SMPR3'):
            raise CandidateError('MATERIAL_CONFLICT', f'{peri}.{reg}跨来源地址差异尚未裁决')
    db = db or EncodingDB('py32f420')
    version = db.knowledge_version()
    request, issues = validate_request(payload, db)
    if request is None or issues:
        raise CandidateError('INVALID_INTENT', '; '.join(str(issue) for issue in issues))
    result = Composer('py32f420', db=db).compile(request)
    if db.knowledge_version() != version:
        raise CandidateError('STALE_KNOWLEDGE', '编译过程中资料版本已改变，请重新生成')
    if result.missing_resets:
        raise CandidateError('MISSING_RESET', '缺少已确认的寄存器复位值，无法安全生成整字写入（INCOMPLETE_COMPILATION）',
                             result.missing_resets)
    return export_candidate(result, chip_id=request.chip, product_profile_id=product_profile_id,
                            platform=platform, initial_state=initial_state,
                            knowledge_version=version, static_validated=True)
