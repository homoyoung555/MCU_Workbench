"""Expose compiler-owned FLOW definition boundaries for the GUI copy dialog."""


def copy_groups(compilation, editor):
    if not compilation.is_valid:
        return []
    allowed=set(editor.by_name.get('FLOW',{}).get('appendableRows',[]))
    catalogs=compilation.plan.catalogs
    result=[]
    for cp in compilation.plan.cp_plans.values():
        schedule={s.definition_id:s for s in cp.schedule}
        for definition in cp.definitions:
            rows=list(definition.source_rows)
            if not rows:  # Compiler-created system definitions have no editable FLOW group.
                continue
            entry=schedule.get(definition.identity)
            dc=getattr(catalogs,'dc_parametric_plans',{}).get(rows[0]-2)
            result.append({'id':definition.identity,'cp':definition.cp,'item':definition.item,
                           'type':definition.flow_type,'kind':definition.typed_kind,'rows':rows,
                           'subs':list(definition.datalog_points),'recipe':list(definition.effective_recipe),
                           'enabled':entry.enabled if entry else None,
                           'hbin':entry.hardware_bin if entry else '', 'sbin':entry.software_bin if entry else '',
                           'copyable':all(r in allowed for r in rows),
                           'patterns':list(dc.config_patterns) if dc else [],
                           'sharedSheets':['VERSION','PIN DEC'],
                           'notes':['复制当前FLOW定义的全部来源行，保留sub、参数、bin和颜色。',
                                    '关联子表继续使用当前工作簿配置，不创建独立副本；改名后需检查引用。',
                                    '关联清单仅列已识别信息；未列出的依赖仍由完整检查和生成确认。']})
    return result
