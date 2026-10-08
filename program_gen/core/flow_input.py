"""Read-only FLOW field applicability for the new-item wizard.

This is intentionally a thin projection over the production classifier.  It
does not compile a product, resolve resources, or replace compiler validation.
"""

from __future__ import annotations

import pandas as pd
import re

from flow_recipe import default_recipe
from preflight.schema import TYPED
from program_gen.flow_kinds import FlowKindCompileError, compile_flow_rows


_IDENTITY_FIELDS = ("CP NO", "item", "type", "mode")
_CLASSIFICATION_DEFAULTS = {"FV/FI": "/", "Recipe": ""}
_TRIM_SEARCH_FIELDS = ("DAC bit", "Bisection", "LINE", "step")
SPECIALIZED_FLOW_KINDS = frozenset(('OS', 'FREQ_TEST', 'PDR_TRIM', 'PDR_VERIFY', 'ADC_TEST', 'OPA_TEST', 'DAC_TEST', 'PVD_TEST', 'VERIFY_HEX', 'VERIFY_KEIL'))


def describe_flow_input(values: dict, *, version_frame=None) -> dict:
    result = _describe_flow_input(values, version_frame)
    recipe = _text(values.get('Recipe'))
    simple = not recipe or (result.get('specialized') and recipe == result['fixedValues'].get('Recipe', recipe)) or bool(re.fullmatch(
        r'ENTER(?:\([^()]*\))?-(?:TRIM(?:\([^()]*\))?-)?JUDGE', recipe, re.I))
    result['editGuided'] = result['supported'] and simple
    if result['supported'] and not simple:
        result['clearFields'] = []
        result['notice'] = '复杂 Recipe 保留完整字段编辑；字段适用性由整本检查确认。'
    return result


def _describe_flow_input(values: dict, version_frame) -> dict:
    """Return JSON-safe wizard metadata for one incomplete FLOW row."""
    issues = [
        {"field": field, "message": f"{field} 不能为空"}
        for field in _IDENTITY_FIELDS
        if not _text(values.get(field)) or (field != 'mode' and _text(values.get(field)) == '/')
    ]
    if issues:
        return _result(None, (), (), issues, False, "补齐基础身份后才能确定测试类别。")

    row = {
        field: values.get(field, default)
        for field, default in _CLASSIFICATION_DEFAULTS.items()
    }
    row.update({field: values.get(field, "") for field in _IDENTITY_FIELDS})
    if not _text(row["Recipe"]):
        row["Recipe"] = default_recipe(row["item"], row["type"], row["mode"]) or ""

    try:
        operation = compile_flow_rows(
            pd.DataFrame((row,)),
            workbook_identity="flow-input",
            source_sha256="flow-input",
        )[0]
    except (FlowKindCompileError, ValueError) as exc:
        field = "mode" if "MODE" in str(exc).upper() else "type"
        return _result(
            None,
            (),
            (),
            ({"field": field, "message": str(exc)},),
            False,
            "当前输入无法由生产分类器识别。",
        )

    if operation.typed_kind == "STANDARD_TRIM":
        return _result(
            operation.typed_kind,
            _standard_trim_fields(values),
            (),
            (),
            operation.mode == "fbist",
            "" if operation.mode == "fbist"
            else "STANDARD_TRIM 新增向导仅支持 mode=fbist。",
        )
    if operation.typed_kind == "STANDARD_VERIFY":
        return _result(
            operation.typed_kind,
            _standard_verify_fields(values, version_frame),
            _TRIM_SEARCH_FIELDS,
            (),
            True,
            "",
        )
    if operation.typed_kind in SPECIALIZED_FLOW_KINDS:
        return _specialized_fields(operation.typed_kind, operation.mode, values)
    fields, clear_fields = _unsupported_fields(operation.typed_kind)
    return _result(
        operation.typed_kind,
        fields,
        clear_fields,
        (),
        False,
        _unsupported_notice(operation.typed_kind),
    )


def _specialized_fields(kind, mode, values):
    from program_gen.core.dedicated_trim import _PDR_SEARCH_CODES
    fixed = {name: '/' for name in (*_TRIM_SEARCH_FIELDS, 'FV/FI', 'meas pin',
                                    'UNIT', 'low_range(%)', 'target', 'high_range(%)')}
    fixed.update(Recipe='', OTP='no', UID='no', PUMP='no', PE='no')
    fields = [
        _field('sub', '子项', False, '单行专用测试项的子项标识。', default='/'),
        _field('relay', '继电器', False, '不使用时填写 /。', default='/'),
        _field('Vcc', '供电配置', True, 'PDR_TRIM 仅支持 VCC_MIN/VCC_TYP/VCC_MAX。' if kind == 'PDR_TRIM' else '填写当前 CP 的供电配置；电压由 VERSION 提供。'),
        _field('Hbin', '硬件 Bin', False, '失败时的硬件 bin。'),
        _field('Sbin', '软件 Bin', False, '失败时的软件 bin。'),
    ]
    if kind == 'FREQ_TEST':
        fixed.update({'FV/FI': 'FREQ', 'Recipe': 'FREQ_TEST'})
        if mode == 'keil':
            del fixed['step']
            fields.append(_field('step', '进入/退出步骤', False,
                'X 前为进入步骤，X 后为全部档位完成后的退出步骤；不填 X 时全部作为进入步骤。各档位使用 FREQ 表 step；RP 后会重跑进入步骤。', default='/'))
        del fixed['meas pin']
        fields.insert(2, _field('meas pin', '测量引脚', True, '频率输出的实际测量引脚。'))
    if kind == 'PDR_TRIM':
        fixed.update({'DAC bit': '4', 'Bisection': 'yes', 'LINE': 'no',
                      'step': ','.join(map(str, _PDR_SEARCH_CODES))})
        del fixed['OTP']
        del fixed['UID']
    resource_sheet = kind.split('_')[0] if kind in ('ADC_TEST','OPA_TEST','DAC_TEST','PVD_TEST') else None
    if resource_sheet:
        fixed['Recipe'] = kind
        if kind == 'ADC_TEST':
            adc_id = _text(values.get('FV/FI')).upper()
            fixed.update({'FV/FI': adc_id, 'sub': adc_id, 'Recipe': 'SWD_CAPTURE-ADC_JUDGE'})
            fields = [f for f in fields if f['name'] != 'sub']
        if kind == 'DAC_TEST':
            del fixed['target']
            fields.insert(0, _field('target', 'DAC 分辨率', True, '填写满量程码数，例如 4096；不是目标电压。'))
        if kind == 'PVD_TEST':
            fixed['FV/FI'] = 'PVD'
            del fixed['meas pin']
            fields.insert(0, _field('meas pin', '比较引脚', True, '两个不同引脚，用 + 连接；顺序对应 PVD expect。'))
        if mode == 'keil' and kind != 'ADC_TEST':
            del fixed['step']
            fields.append(_field('step', '执行步骤', True,
                '执行序列，动态码来自 PVD 专表 step。' if kind == 'PVD_TEST' else '包含且只包含一个 X 占位，将专表步骤插入该位置。'))
    if kind in ('VERIFY_HEX', 'VERIFY_KEIL') or (kind == 'ADC_TEST' and mode == 'keil'):
        del fixed['step']
        fields.append(_field('step', '下载 Pattern' if kind == 'VERIFY_HEX' else '执行步骤', True,
            '填写已有固件下载资源名，Recipe 留空。' if kind == 'VERIFY_HEX' else '按现有 RUN_SEQUENCE 语法填写；例如 PA0:HL-5ms-222。'))
        if kind != 'VERIFY_HEX':
            recipe = _text(values.get('Recipe')) or 'RUN_SEQUENCE-JUDGE'
            fixed['Recipe'] = recipe if kind == 'ADC_TEST' else 'RUN_SEQUENCE-JUDGE'
            if kind == 'ADC_TEST':
                fields.append(_field('Recipe', '采集与判定 Recipe', True,
                    'RUN_SEQUENCE-JUDGE 或 RUN_SEQUENCE-SRAM_CAPTURE(地址,22x16@2)-ADC_JUDGE；地址须按固件填写。'))
                del fixed['Recipe']
            capture = kind == 'ADC_TEST' and 'SRAM_CAPTURE' in recipe.upper()
            if not capture:
                for name in ('meas pin','target'):
                    del fixed[name]
                fields.extend((_field('meas pin','判定引脚',True,'多个引脚用 + 连接，与 H/L 位数一致。'),
                               _field('target','期望值',True,'数字判定填写 H/L 序列；通用 KEIL 量测填写目标数值。')))
                if kind == 'VERIFY_KEIL':
                    for name in ('UNIT','low_range(%)','high_range(%)','FV/FI'): del fixed[name]
                    fields.extend((_field('UNIT','单位',True,'数字判定填写 /；量测按实际电压/电流单位填写。'),
                                   _field('low_range(%)','下限',False,'数字判定保留 /。',default='/'),
                                   _field('high_range(%)','上限',False,'数字判定保留 /。',default='/'),
                                   _field('FV/FI','激励',False,'仅执行步骤含 F 时使用。',default='/')))
            if kind == 'VERIFY_KEIL':
                fields = [{**f,'required':True} if f['name']=='sub' else f for f in fields]
    supported = kind != 'FREQ_TEST' or mode in ('swd', 'keil')
    if kind == 'ADC_TEST': supported = mode in ('swd','keil')
    result = _result(kind, fields, [n for n, v in fixed.items() if v == '/' ], (), supported,
                     '沿用已有专表/协议资源；确认创建时检查整本依赖。' if supported else f'{kind} 仅支持 mode=swd 或 keil。')
    result.update(specialized=True, fixedValues=fixed)
    if resource_sheet: result['resourceSheet'] = resource_sheet
    return result


def _standard_trim_fields(values: dict) -> tuple[dict, ...]:
    custom_codes = _text(values.get("_codeMode")).casefold() == "custom"
    return (
        _field("sub", "子项", False, "同一测试项的子项标识。", default="/"),
        _field("relay", "继电器", False, "测试继电器；不使用时保留 '/'.", default="/"),
        _field("DAC bit", "DAC 位数", True, "普通 TRIM 搜索位数。"),
        _field("Bisection", "搜索方式", True, "选择二分或全码搜索。", choices=True),
        _field("step", "自定义码序", custom_codes, "仅自定义码序时填写。"),
        *({**field, 'required': False, 'default': '/'}
          if field['name'] == 'FV/FI' and 'hz' in _text(values.get('UNIT')).casefold()
          else field for field in _measurement_fields(required=True)),
        _field("Vcc", "供电配置", True, "本测试项使用的供电配置。"),
        _field("Hbin", "硬件 Bin", False, "失败时的硬件 bin。"),
        _field("Sbin", "软件 Bin", False, "失败时的软件 bin。"),
        _field("PE", "擦写窗口", False, "需要页面擦写或编程窗口时选择。", choices=True, default="no"),
    )


def _standard_verify_fields(values, version_frame) -> tuple[dict, ...]:
    from program_gen.core.standard_verify import _version_target
    from program_gen.core.encoding import calc_limit
    source = _version_target(version_frame, values.get('CP NO', ''), values.get('item', ''))
    frequency = _text(values.get('UNIT')).casefold().endswith('hz')
    target_required = frequency
    if source is None:
        try:
            for low in (True, False):
                calc_limit(None, values.get('low_range(%)', ''), values.get('high_range(%)', ''), low)
        except (ValueError, TypeError):
            target_required = True
    measurement = list(_measurement_fields(required=False, required_fields=(
        'UNIT', 'meas pin', *(() if source else ('low_range(%)', 'high_range(%)')),
        *(('target',) if target_required else ()),
    ), verify=True))
    for field in measurement:
        if field['name'] in ('low_range(%)', 'high_range(%)', 'target'):
            field['help'] = (f'限值来源 VERSION:{source[0]} = {source[1]}，上下限 ±0.05；原 FLOW 值保留。'
                             if source else '限值来源 FLOW；百分比/正负偏移需要目标值，绝对限值可不填目标值。')
            if frequency and field['name'] == 'target':
                field['help'] += ' 频率测量仍需要 FLOW target 计算测量时间。'
    return (
        _field("sub", "子项", False, "同一测试项的子项标识。", default="/"),
        _field("relay", "继电器", False, "测试继电器；不使用时保留 '/'.", default="/"),
        *measurement,
        _field("Vcc", "供电配置", True, "STANDARD_VERIFY 计划直接使用的供电配置。"),
        _field("Hbin", "硬件 Bin", False, "失败时的硬件 bin。"),
        _field("Sbin", "软件 Bin", False, "失败时的软件 bin。"),
        _field("PE", "擦写窗口", False, "需要页面擦写或编程窗口时选择。", choices=True, default="no"),
    )


def _measurement_fields(*, required: bool, required_fields=(), verify=False) -> tuple[dict, ...]:
    is_required = lambda name: required or name in required_fields
    unit = _field('UNIT', '单位', is_required('UNIT'), '按当前测试类别支持的单位填写。', choices=True)
    supported_units = {'a', 'ma', 'ua', 'na', 'v', 'hz', 'khz', 'mhz'} | ({'mv'} if verify else set())
    unit['choices'] = [u for u in unit['choices'] if u.casefold() in supported_units]
    return (
        _field("FV/FI", "激励", is_required("FV/FI"), "测量激励或专用族标记。"),
        _field("meas pin", "测量引脚", is_required("meas pin"), "测量或判定使用的引脚。"),
        unit,
        _field("low_range(%)", "下限", is_required("low_range(%)"), "最终编译可能从 VERSION 推导限值。"),
        _field("target", "目标值", is_required("target"), "最终编译可能从 VERSION 推导目标或限值。"),
        _field("high_range(%)", "上限", is_required("high_range(%)"), "最终编译可能从 VERSION 推导限值。"),
    )


def _unsupported_fields(kind: str) -> tuple[tuple[dict, ...], tuple[str, ...]]:
    if kind == "OPA_TEST":
        return (
            (
                _field("sub", "子项", False, "同一测试项的子项标识。", default="/"),
                _field("relay", "继电器", False, "测试继电器；不使用时保留 '/'.", default="/"),
                _field("Vcc", "供电配置", True, "OPA 专用流程所需供电配置。"),
                _field("step", "流程步骤", False, "KEIL OPA 的步骤由专用流程解释。"),
            ),
            ("FV/FI", "meas pin", "low_range(%)", "target", "high_range(%)"),
        )
    if kind == "DAC_TEST":
        return (
            (
                _field("sub", "子项", False, "同一测试项的子项标识。", default="/"),
                _field("relay", "继电器", False, "测试继电器；不使用时保留 '/'.", default="/"),
                _field("target", "DAC 分辨率", True, "DAC 专用流程所需满量程码数。"),
                _field("Vcc", "供电配置", True, "DAC 专用流程所需供电配置。"),
                _field("step", "流程步骤", False, "KEIL DAC 的步骤由专用流程解释。"),
            ),
            ("FV/FI", "meas pin", "low_range(%)", "high_range(%)"),
        )
    return (), ()


def _unsupported_notice(kind: str) -> str:
    if kind in {"VERIFY_HEX", "VERIFY_KEIL"}:
        return f"{kind} 是固件阶段；同一 item 的连续行仍需由专用流程编排，新增向导尚未实现。"
    return f"{kind} 已由生产分类器识别，但新增测试项向导尚未实现该专用字段。"


def _field(name: str, label: str, required: bool, help_text: str, *, choices=False, default=None) -> dict:
    result = {"name": name, "label": label, "required": required, "help": help_text}
    if choices:
        enum = TYPED[("FLOW", name)].get("enum", ())
        result["choices"] = [str(value) for value in enum]
    if default is not None:
        result["default"] = str(default)
    return result


def _result(kind, fields, clear_fields, issues, supported, notice) -> dict:
    return {
        "kind": kind,
        "fields": list(fields),
        "clearFields": list(clear_fields),
        "issues": list(issues),
        "supported": bool(supported),
        "notice": notice,
    }


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()
