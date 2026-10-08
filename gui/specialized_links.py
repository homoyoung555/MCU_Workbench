"""Read-only association cards for native tests, using compiled plans as facts."""
import re
from types import SimpleNamespace
from openpyxl.utils import get_column_letter
from program_gen.core.adc_test import adc_pattern_names
from program_gen.core.pattern_link_names import PatternLinkNameResolver


def _location(editor, sheet, row, column=None):
    table = editor.by_name.get(sheet, {})
    if not 1 <= row <= table.get('maxRow', 0):
        return []
    col = next((i+1 for i,c in enumerate(table.get('columns', []))
                if str(c.get('label','')).casefold().split(' / ')[0] == str(column).casefold()), None)
    coordinate = f'{get_column_letter(col)}{row}' if col else f'row {row}'
    return [{'sheet':sheet, 'coordinate':coordinate, 'label':f'查看 {sheet}!{coordinate}'}]


def _records(editor, sheet):
    table = editor.by_name.get(sheet, {})
    labels = [str(c.get('label','')).strip().casefold().split(' / ')[0] for c in table.get('columns', [])]
    for row, cells in enumerate(table.get('rows', [])[1:], 2):
        yield row, {k:str(c.get('value') if c.get('value') is not None else '').strip()
                    for k,c in zip(labels,cells)}


def _card(title, text, locations=()):
    return {'title':title, 'text':text, 'locations':list(locations)}


def _actions(actions):
    parts = []
    for a in actions:
        kind = type(a).__name__
        if kind == 'LevelSequenceAction':
            text = f'{a.pin} 电平 {a.levels}（每段 {a.segment_duration_ns/1000000:g} ms）'
        elif kind == 'SendCodeAction': text = f'{a.pin} 发送码 {a.value}'
        elif kind == 'WaitAction': text = f'等待 {a.duration_ms} ms'
        elif kind == 'RepowerAction': text = '重供电'
        elif kind == 'ForceStopAction': text = '停止激励'
        elif kind == 'SupplyForceAction': text = f'{a.rail} 供电 {a.voltage}；限流 {a.current_compliance:g} {a.current_unit}'
        elif kind == 'ForceVoltageAction': text = '；'.join(f'{p.pin} 激励 {p.voltage}' for p in a.points)
        elif kind in ('ClockForceAction','ClockStopAction'):
            text = ('输出时钟 ' if kind == 'ClockForceAction' else '停止时钟 ') + '；'.join(f'{s.pin} {s.frequency_hz:g} Hz' for s in a.signals)
        else: text = f'尚未展开的动作：{kind}'
        parts.append(text)
    return ' → '.join(parts) or '无额外动作'


def _judge(judge):
    if hasattr(judge, 'pins'):
        return '数字判定：' + '；'.join(f'{p}={v}' for p,v in zip(judge.pins,judge.expected))
    return f'量测 {judge.pin}：{judge.low_limit:g} ～ {judge.high_limit:g} {judge.unit}'


def _pattern(name, use, locations=()):
    return {'name':name,'uses':[use],'locations':list(locations),'preview':[],
            'note':'此处定位资源的配置/引用来源；不表示该资源位于 pattern 工作表。'}


def _resource_slot(phase, role, label, names):
    # Reserved external-tool contract. No binding is persisted or consumed yet.
    return {'phase':phase,'role':role,'label':label,'status':'placeholder',
            'configurable':False,'names':names}


def _stage(label, details, slots=()):
    return {'label':label,'details':list(details),
            'patterns':list(dict.fromkeys(n for s in slots for names in s['names'].values() for n in names))}


def _entry(plan, row, details, patterns, slots=(), stages=()):
    return {'flowRow':row,'cp':plan.cp,'item':plan.item,'kind':plan.typed_kind,
            'specialized':True,'patterns':patterns,'unexpanded':[],'details':details,
            'resourceSlots':list(slots),'stages':list(stages)}


def _sweep(plan, family, editor, workbook=None):
    row = plan.row + 2
    source = _location(editor,'FLOW',row,'step')
    details = [_card(f'{family} 执行配置',f'{plan.protocol.upper()} · 供电 {plan.power_profile}',source)]
    if family == 'FREQ':
        details.append(_card('量测引脚',plan.measurement_pin,_location(editor,'FLOW',row,'meas pin')))
    if family == 'DAC':
        details.append(_card('DAC 分辨率',str(plan.resolution),_location(editor,'FLOW',row,'target')))
    patterns = []
    if getattr(plan,'init_pattern',None): patterns.append(_pattern(plan.init_pattern,'初始化',source))
    if plan.protocol == 'keil':
        details.append(_card('进入步骤',_actions(plan.entry_actions)+'；后续 RP 重供电后重新执行。',source))
    if plan.cases:
        text = f'使用 {family} 专表的 {len(plan.cases)} 个测试点；各点参数、限值和步骤请在专表查看。'
        repowers = sum(c.repower_before for c in plan.cases)
        if repowers: text += f' 其中 {repowers} 个测试点前会重供电。'
        details.append(_card(f'{family} 专表配置',text,
                             _location(editor,family,plan.cases[0].sheet_row)))
    if plan.protocol == 'keil': details.append(_card('退出步骤',_actions(plan.exit_actions)+'；全部测试点结束后执行。',source))
    slots = []
    for role,label,names in (
        ('init','初始化 Pattern',[getattr(plan,'init_pattern',None)]),
        ('config','测试配置 Pattern',[getattr(c,'config_pattern',None) for c in plan.cases]),
        ('code','DAC 码配置 Pattern',[getattr(c,'code_pattern',None) for c in plan.cases])):
        names = list(dict.fromkeys(n for n in names if n))
        if names: slots.append(_resource_slot(family,role,label,{'shared':names}))
    if family == 'DAC' and plan.protocol == 'swd' and workbook is not None:
        from program_gen.platform_program.facts import compile_pin_map_facts
        names = []
        for platform in ('chroma','s100'):
            try:
                facts = compile_pin_map_facts(workbook,SimpleNamespace(platform=platform,cp=plan.cp,variant='production'))
            except ValueError as exc:
                details.append(_card('DAC 引脚资源待确认',f'{platform}：{exc}',source))
                continue
            names.extend(f'{plan.product}_DAC_{c.mode}_{p.name}_Test'
                         for p in facts.pin_groups.dac_out for c in plan.cases)
        if names:
            slots.append(_resource_slot('DAC','output','输出模式配置 Pattern',{'shared':list(dict.fromkeys(names))}))
    stages=[]
    entry=[i for i,d in enumerate(details) if d['title']=='进入步骤']
    exit_=[i for i,d in enumerate(details) if d['title']=='退出步骤']
    if getattr(plan,'init_pattern',None) or (plan.protocol=='keil' and plan.entry_actions):
        stages.append(_stage('进入',[0]+entry,[s for s in slots if s['role']=='init']))
    stages.append(_stage('测试与判定',[i for i in range(len(details)) if i not in entry+exit_],
                         [s for s in slots if s['role']!='init']))
    if plan.protocol=='keil' and plan.exit_actions: stages.append(_stage('退出',exit_))
    return [_entry(plan,row,details,patterns,slots,stages)]


def _adc_sources(editor, adc_id):
    sources, group = {}, ''
    for row,record in _records(editor,'ADC'):
        group = record.get('adc','').upper() or group
        channel = next((record[k] for k in ('chanel','channel','ch') if record.get(k)), '')
        if group == adc_id and re.fullmatch(r'\d+(?:\.0)?',channel):
            sources[int(float(channel))] = _location(editor,'ADC',row)
    return sources


def _iomux_sources(editor, adc_id, channel):
    # Source navigation only: the actual resolved pin is always taken from the plan.
    tokens = {f'{adc_id}_IN{channel}'}
    if adc_id in ('ADC1','ADC2'): tokens.add(f'ADC12_IN{channel}')
    return [location for row,record in _records(editor,'IOMUX')
            if tokens.intersection(t.strip().upper() for t in record.get('analog','').split('/'))
            for location in _location(editor,'IOMUX',row,'analog')]


def _adc(plan, editor):
    details, slots, stages = [], [], []
    for index,p in enumerate(plan.phases,1):
        first_detail,first_slot=len(details),len(slots)
        locations = _location(editor,'FLOW',p.row+2,'Recipe')
        label = {'SWD_CAPTURE':'SWD 采集','KEIL_SRAM_CAPTURE':'KEIL SRAM 采集',
                 'KEIL_DIGITAL_COMPARE':'KEIL 数字判定'}[p.kind.value]
        details.append(_card(f'阶段 {index} · {p.adc_id} · FLOW {p.row+2}',
                             f'{label}；供电 {p.power_profile}；参考电压 {p.reference_voltage:g} V；独立供电阶段。',locations))
        if p.run_actions: details.append(_card('执行步骤',_actions(p.run_actions),_location(editor,'FLOW',p.row+2,'step')))
        if p.sram_capture:
            layout = p.sram_capture.layout
            details.append(_card('SRAM 采集布局',f'{layout.canonical_spec}；小端无符号；采集引脚 {p.sram_capture.capture_pin}',locations))
        elif p.kind.value == 'SWD_CAPTURE':
            details.append(_card('SWD 采集布局',f'{p.capture.slot_count} 通道 × {p.capture.word_width_bits} bit；有效码宽 {p.capture.code_width_bits} bit；采集引脚 {p.capture_pin}',locations))
            names = adc_pattern_names(p.adc_id)
            for i,(role,resource_label) in enumerate((('config','配置 Pattern'),('capture','采集 Pattern'))):
                slots.append(_resource_slot(p.adc_id,role,resource_label,{'shared':[names[i]]}))
        if p.digital_judge: details.append(_card('判定引脚',_judge(p.digital_judge),_location(editor,'FLOW',p.row+2,'meas pin')))
        sources = _adc_sources(editor,p.adc_id)
        if p.slots:
            internal = sum(slot.source_kind.value=='INTERNAL' for slot in p.slots)
            text = f'{p.adc_id} 共 {len(p.slots)} 个通道（外部 {len(p.slots)-internal}，内部 {internal}）；通道参数见 ADC 专表，引脚映射见 IOMUX。'
            first = p.slots[0].channel
            details.append(_card(f'{p.adc_id} 通道配置',text,
                                 sources.get(first,[]) + _iomux_sources(editor,p.adc_id,first)[:1]))
        stages.append(_stage(f'{p.adc_id} · {label}',range(first_detail,len(details)),slots[first_slot:]))
    return [_entry(plan,row,details,[],slots,stages) for row in plan.excel_rows]


def _firmware(plan, editor):
    details, patterns = [], []
    for index,step in enumerate(plan.execution_steps,1):
        if type(step).__name__ == 'DutResetAction':
            details.append(_card('阶段间复位',f'低电平 {step.low_duration_ms} ms → 高电平 {step.high_duration_ms} ms；最终释放为高电平。'))
            continue
        locations = _location(editor,'FLOW',step.row+2,'step')
        if hasattr(step,'pattern'):
            text = f'下载资源 {step.pattern.name}；供电 {step.power_profile}。'
            patterns.append(_pattern(step.pattern.name,'固件下载',locations))
        else:
            text = _actions(step.actions)+'；'+_judge(step.judge)
            if step.cleanup_actions: text += '；清理：'+_actions(step.cleanup_actions)
            text += f'；供电 {step.power_profile}。'
        details.append(_card(f'执行顺序 {index} · {step.sub} · FLOW {step.row+2}',text,locations))
    details.insert(0,_card('固件阶段组','按编译后的同 CP、同 ITEM 连续阶段展示执行顺序；不推断其他测试项使用了哪个固件。',
                          [l for row in plan.excel_rows for l in _location(editor,'FLOW',row)]))
    slots=[_resource_slot(str(p.row+2),'download','固件下载 Pattern',{'shared':[p.pattern.name]})
           for p in plan.phases if hasattr(p,'pattern')]
    stages=[_stage('复位' if type(s).__name__=='DutResetAction' else s.sub,[i+1],
                   [slot for slot in slots if slot['phase']==str(getattr(s,'row',-2)+2)])
            for i,s in enumerate(plan.execution_steps)]
    return [_entry(plan,row,details,patterns,slots,stages) for row in plan.excel_rows]


def _dc(plan, editor):
    details = [_card(f'{p.sub} · FLOW {p.row+2}',
                     f'供电 {plan.power_profile}；激励 {p.force.value}；量测 {p.measurement.low_limit:g} ～ {p.measurement.high_limit:g} {p.measurement.unit}。',
                     _location(editor,'FLOW',p.row+2,'step')) for p in plan.phases]
    slots = [_resource_slot('DC','config','配置 Pattern',{'shared':list(plan.config_patterns)})]
    stages=[_stage(p.sub,[i],[_resource_slot('DC','config','配置',{'shared':[p.config_pattern]})])
            for i,p in enumerate(plan.phases)]
    return [_entry(plan,row,details,[],slots,stages) for row in plan.excel_rows]


def _vih_vil(plan, editor):
    details, slots = [], []
    if hasattr(plan,'config_pattern'):
        details.append(_card('VIH/VIL 执行配置',f'SWD · 供电 {plan.power_profile}；电平组合 '+ ' / '.join(plan.cases),
                             _location(editor,'FLOW',plan.row+2,'step')))
        for role,label,names in (('config','配置 Pattern',[plan.config_pattern]),
                                 ('capture','采集 Pattern',list(plan.capture_patterns))):
            slots.append(_resource_slot('VIH/VIL',role,label,{'shared':names}))
    else:
        for v in plan.variants:
            details.append(_card(f'{v.sub} · FLOW {v.row+2}',_actions(v.entry_actions),
                                 _location(editor,'FLOW',v.row+2,'step')))
            slot=_resource_slot(v.sub,'compare','比较 Pattern',{'shared':[v.pattern]})
            slot['status']='generated'
            slots.append(slot)
    stages=([_stage('配置',[0],slots[:1]),_stage('采集与判定',[0],slots[1:])]
            if hasattr(plan,'config_pattern') else [_stage(v.sub,[i],slots[i:i+1]) for i,v in enumerate(plan.variants)])
    return [_entry(plan,row,details,[],slots,stages) for row in plan.excel_rows]


def _project_slot_names(entry, resolver):
    """Project only declared external resource slots for the Link UI."""
    if resolver.is_empty:
        return entry
    cp = entry['cp']
    original_slots = entry['resourceSlots']
    by_original = {}
    for slot in original_slots:
        if slot.get('status') == 'generated':
            for values in slot.get('names', {}).values():
                for original in values:
                    by_original.setdefault(original, [original])
            continue
        names = slot.get('names', {})
        source_platforms = tuple(names)
        projected = {platform: [resolver.resolve(cp, platform, original) for original in values]
                     for platform, values in names.items() if platform != 'shared'}
        if 'shared' in names:
            chroma = [resolver.resolve(cp, 'chroma', original) for original in names['shared']]
            s100 = [resolver.resolve(cp, 's100', original) for original in names['shared']]
            if chroma == s100 and not projected:
                projected = {'shared': chroma}
            else:
                if 'chroma' not in source_platforms:
                    projected['chroma'] = chroma
                if 's100' not in source_platforms:
                    projected['s100'] = s100
        for platform, values in names.items():
            targets = ('chroma', 's100') if platform == 'shared' else (platform,)
            for original in values:
                by_original.setdefault(original, list(dict.fromkeys(
                    resolver.resolve(cp, target, original) for target in targets
                )))
        slot['names'] = projected
    for stage in entry.get('stages', []):
        stage['patterns'] = list(dict.fromkeys(
            name for original in stage.get('patterns', [])
            for name in by_original.get(original, [resolver.resolve(cp, 'chroma', original), resolver.resolve(cp, 's100', original)])
        ))
    expanded = []
    for pattern in entry.get('patterns', []):
        names = tuple(dict.fromkeys((resolver.resolve(cp, 'chroma', pattern['name']),
                                     resolver.resolve(cp, 's100', pattern['name']))))
        expanded.extend(dict(pattern, name=name) for name in names)
    entry['patterns'] = expanded
    return entry


def specialized_links(catalogs, editor, workbook=None):
    result = []
    for family in ('opa','dac','freq'):
        for plan in getattr(catalogs,family+'_test_plans',{}).values():
            result.extend(_sweep(plan,family.upper(),editor,workbook))
    for plan in getattr(catalogs,'adc_test_plans',{}).values(): result.extend(_adc(plan,editor))
    for plan in getattr(catalogs,'firmware_test_plans',{}).values(): result.extend(_firmware(plan,editor))
    for plan in getattr(catalogs,'dc_parametric_plans',{}).values(): result.extend(_dc(plan,editor))
    for plan in getattr(catalogs,'vih_vil_plans',{}).values(): result.extend(_vih_vil(plan,editor))
    resolver = PatternLinkNameResolver(getattr(workbook, 'pattern_links', ()))
    return [_project_slot_names(entry, resolver) for entry in result]
