"""Read-only associations for compiler-bound memory tests and modules."""
from gui.specialized_links import _card, _location, _records


def module_patterns(module, plan):
    if module == 'READOTPMAP':
        return [p.capture.pattern.name for p in plan.pages]
    if module == 'CHECKOTP':
        return [r.pattern.name for r in (plan.set_all_final_vposp,*plan.page_reads)]
    if module == 'PGMOTP':
        return [plan.enter_fbist_mode.pattern.name,plan.set_all_final_vposp.pattern.name]+[
            s.run.pattern.name for p in plan.page_program.page_operations for s in p.steps]
    if module == 'LOADMAP':
        return list(dict.fromkeys(n for p in plan.page_operations
                                 for n in (p.patterns.program_pattern,p.patterns.read_pattern) if n))
    if module in ('READID','CHECKID'):
        return [plan.enter_fbist_mode.pattern.name,plan.check_pattern.pattern.name]
    return None


def module_details(spec, steps, editor):
    details=[]
    source=_location(editor,'FLOW',spec.excel_row,'Recipe')
    for step in steps:
        p=step.module_plan
        if p is None: continue
        locations=list(source)
        if step.module=='READOTPMAP':
            text=f'采集引脚 {p.swd_pin}；读取位宽 {p.read_bit}。'+ '；'.join(
                f'页 {page.page}：{page.byte_count} 字节，'+', '.join(
                    f'{e.register}@{e.real_offset}（{e.slot_width}字节）' for e in page.layout)
                +('；恢复 '+', '.join(page.restore_registers) if page.restore_registers is not None else '；恢复全部寄存器')
                for page in p.pages)
            locations.extend(l for page in p.pages if page.layout
                             for l in _location(editor,'ADDR_MAP',page.layout[0].row_index+2))
        elif step.module=='LOADMAP':
            text=f'数据来源 {p.image_source}；目标页 '+', '.join(p.target_pages)+'；装载编程/回读比较数据，本步骤不执行烧写。'
            text+='；'.join(f'{t.register_symbol} → {t.page}/{t.register}' for t in p.targets)
            text+='；'.join(f'{w.page}[{w.word_index}]=0x{w.value:X}' for w in p.word_writes)
        elif step.module=='PGMOTP':
            text=f'供电 {p.power_profile}；'+ '；'.join(
                f'页 {page.patterns.page}：'+' → '.join(s.action+('（仅失败站点）' if s.site_scope=='FAILED_SITES' else '') for s in page.steps)
                for page in p.page_program.page_operations)
        elif step.module=='CHECKOTP':
            text='使用当前比较数据回读校验；不擦除、不编程。'
        elif step.module=='COMMIT':
            text='更新编程与比较数据，本步骤不烧写。'+ '；'.join(
                f'{w.value.token} → {w.page}/{w.register}.{w.field}[{w.lsb+w.width-1}:{w.lsb}]' for w in p.writes)
            text+='；'.join(f'{v.value.token} → {v.field}' for v in p.field_values)
        elif step.module in ('READID','CHECKID'):
            text=f'供电 {p.power_profile}；ID角色 {p.id_item.role}；失败处理 {p.id_item.failure_policy}。'
            if p.gate_symbol: text+=f' 门控结果 {p.gate_symbol}。'
        else: continue
        details.append(_card(step.module,text,locations))
    return details


def test_entry(plan, kind, editor):
    test=plan.test
    actions=[('进入',test.enter.pattern.name),('进入测量模式',test.enter_vt.pattern.name),
             ('扫描与记录' if kind=='MARGIN' else '读取与判定',test.read.pattern.name)]
    source=_location(editor,'FLOW',plan.excel_row,'Recipe')
    details=[_card('进入',f'供电 {test.power_profile}；执行进入模式 Pattern。',source),
             _card('进入测量模式','执行已编译的 VT 模式配置。',source)]
    if kind=='MARGIN':
        text=f'{test.start_voltage:g} → {test.end_voltage:g} V；二分搜索 {test.iterations} 次；记录 {test.result_label}，只记录结果，不按该结果拒测。范围与迭代次数由生成器固定。'
    else:
        text=f'测试电压 {test.voltage:g} V；'+('失败重试一次。' if test.retry_failed else '不重试。')
        column=plan.item.split('_')[0]+(' bake' if '_BAKE_' in plan.item.upper() else '')+' target'
        source=source+[l for row,r in _records(editor,'VERSION') if r.get('cp num','').upper()==plan.cp.upper()
                       for l in _location(editor,'VERSION',row,column)]
    if test.gate: text+=f' 使用已产生的门控结果 {test.gate.gate_symbol}，本项不重新执行 ID 测试。'
    details.append(_card(actions[-1][0],text,source))
    return (plan.excel_row,plan.cp,plan.item,kind,actions,[],details)


def generated_names(catalogs):
    names={p.output_identity for p in getattr(getattr(catalogs,'flash_compare_compilation',None),'plans',())}
    labels=getattr(catalogs,'flash_label_plan',None)
    for page in (*getattr(labels,'pages',()),*getattr(labels,'uid_variants',())):
        for key in ('erase_pattern','program_pattern','read_pattern','capture_pattern','check_pattern'):
            name=getattr(page.names,key,None)
            if name: names.add(name)
    return names
