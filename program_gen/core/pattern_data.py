# PATTERN 表与 FLOW 测试项的关联（平台无关）。
import re

from program_gen import state as G
from program_gen.core.logical_item import logical_item_key
from program_gen.core.recipe_trim import recipe_pattern_name

# fbist_pattern_get 结果缓存：依赖 PATTERN 表与单元格填充色（运行期只读），
# 每次重算要重读上万次 openpyxl 单元格。返回副本防调用方就地修改污染缓存。
_fbist_pattern_cache = None


def _reuse_dac_pairs():
    """扫 `pattern` sheet 收集所有 (trim_item, ref_item) 的 reuse dac 依赖关系对——
    trim_item 这行 `pattern=="reuse dac"`，description 列填被依赖的 trim 项名
    （如 "Hsi_Vrega_Trim"）。两平台共用（PATTERN sheet 平台无关）；item 列的向下
    继承规则跟 fbist_pattern_created 一致：按 F 列底色分组。"""
    items = G.col("PATTERN", "item")
    patterns = G.col("PATTERN", "pattern")
    descs = G.col("PATTERN", "description")
    item_flag = ""
    pairs = []
    for i in range(len(items)):
        if G.wc["F"][i + 1].fill.fgColor.rgb == "00000000":
            if isinstance(items[i], str):
                item_flag = items[i]
        else:
            item_flag = "2768"
        if isinstance(patterns[i], str) and patterns[i] == "reuse dac":
            pairs.append((item_flag, descs[i]))
    return pairs


def reuse_dac_pattern(item_name):
    """item_name 这个 trim 项是否依赖别的 trim 项已经测定的 dac 值（"A trim 依赖 B trim
    已经测定的值"这种跨寄存器场景，不是同地址多字段的 a_data/b_data，是两个独立寄存器，
    直接把 B 已经跑过、已经把最终值写进去的 set_B_dac pattern 再跑一遍即可，B 的 do 循环
    早跑完、pattern 里已经是最终码，不需要重新算/重新灌变量——**前提是 B 真的在同一个
    程序里跑过**，跨 CP 复用见 [[reuse_dac_restore_items]]）。有依赖则按现有命名约定
    （"set_"+去 Trim 后缀+"dac"）派生并返回该 pattern 名，没有则返回 None。"""
    logical_item = _logical_trim_item(item_name)
    for trim_item, ref_item in _reuse_dac_pairs():
        if _logical_trim_item(trim_item) == logical_item:
            return recipe_pattern_name(ref_item, "trim dac")
    return None


def _logical_trim_item(item_name):
    """Normalize only the generated ``_Trim`` execution suffix for linking."""
    text = str(item_name).strip()
    return re.sub(r"_?trim$", "", text, flags=re.IGNORECASE).rstrip("_").casefold()


def reuse_dac_restore_items(cp_no):
    """本 CP（cp_no，如 "CP3"）里需要"从 EPR 读回重新灌值"的被依赖 trim 项名列表（去重，
    保序）——即某 trim 项在本 CP 里跑、且 pattern sheet 标了 reuse dac 依赖 ref_item，但
    ref_item 自己没有在本 CP 里重新 trim 过（它对应 pattern 的内存里没有 live 收敛值，
    例如 CP3 的 Hsi_8/16/24/48M_Trim 依赖 CP1 已经 trim 好的 Hsi_Vrega、CP3 没有
    Hsi_Vrega_Trim 这一步）。ref_item 自己在本 CP 也跑过（如 CP1）则不需要恢复，
    reuse_dac_pattern 直接复用 live 值即可，不进这份列表。"""
    legacy_pairs = _reuse_dac_pairs()
    if not legacy_pairs:
        return _recipe_dac_restore_items(cp_no)

    flow_items = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    result = []
    for trim_item, ref_item in legacy_pairs:
        if ref_item in result:
            continue
        uses_it = any(flow_items[k] == trim_item and flow_cp[k] == cp_no
                      and flow_type[k] == "trim"
                      for k in range(len(flow_items)))
        ref_run_here = any(flow_items[k] == ref_item and flow_cp[k] == cp_no
                            and flow_type[k] == "trim" for k in range(len(flow_items)))
        if uses_it and not ref_run_here:
            result.append(ref_item)
    return result


def _recipe_dac_restore_items(cp_no):
    """Resolve cross-CP restores from explicit Recipe DEPEND operations.

    Common yellow DAC dependencies are intentionally excluded here: their OTP
    values are already reconstructed by the ordinary Trimdata read path.  This
    hook only restores a dependency explicitly named by the item Recipe, whose
    set-DAC pattern memory would otherwise no longer contain the prior-CP code.
    """
    from program_gen.core.recipe_trim import compile_trim_recipe_plans

    plans = compile_trim_recipe_plans(G.FLOW, G.PATTERN)
    flow_items = G.FLOW["item"].tolist()
    flow_cp = G.FLOW["CP NO"].tolist()
    flow_type = G.FLOW["type"].tolist()
    current_cp = str(cp_no).strip()
    result = []
    seen = set()
    for plan in plans.values():
        if plan.cp != current_cp:
            continue
        for operation in plan.operations:
            if operation.name != "DEPEND" or not operation.value:
                continue
            ref_item = str(operation.value).strip()
            ref_key = logical_item_key(ref_item)
            if ref_key in seen:
                continue
            ref_run_here = any(
                logical_item_key(flow_items[index]) == ref_key
                and str(flow_cp[index]).strip() == current_cp
                and str(flow_type[index]).strip().casefold() == "trim"
                for index in range(len(flow_items))
            )
            if not ref_run_here:
                seen.add(ref_key)
                result.append(ref_item)
    return result


def pattern_testitem_merge_rname(code_name):
    pattern = []
    name = []
    pattern_item = G.col("PATTERN", "item")
    pattern_pattern = G.col("PATTERN", "pattern")
    flow_type = G.col("FLOW", "type")
    flow_cp = G.col("FLOW", "CP NO")
    flow_item = G.col("FLOW", "item")
    cp_suffix = code_name[G.i].split("_")[-1]
    pattern_name = ""
    for j in range(len(pattern_item)):
        if type(pattern_item[j]) == str:
            G.function_name = pattern_item[j]
        if type(pattern_pattern[j]) == str and pattern_pattern[j] != "reuse dac":
            # reuse dac 行不是真正要跑的 pattern（是"依赖别的 trim 项"标记，见 _reuse_dac_pattern），
            # 排除掉，否则会插进 name/pattern 的位置序列，打乱 trim_item_write 里 pattern[j+1] 的相邻假设
            pattern_name = pattern_pattern[j]
            for z in range(len(flow_type)):
                if cp_suffix == flow_cp[z]:
                    # Shmoo consumes its Pattern bundle through compile_shmoo_plans().
                    # Feeding it into this legacy Trim/Verify adjacency list duplicates
                    # every role and shifts Chroma's historical pattern-index TEST_NUMs.
                    if flow_type[z] not in ("os", "shmoo"):
                        if flow_item[z] == G.function_name:
                            name.append(G.function_name)
                            pattern.append(pattern_name)
    return name


def pattern_testitem_merge_rpattern(code_name):
    pattern = []
    name = []
    temp_list = fbist_pattern_get()
    pattern_item = G.col("PATTERN", "item")
    flow_type = G.col("FLOW", "type")
    flow_cp = G.col("FLOW", "CP NO")
    flow_item = G.col("FLOW", "item")
    cp_suffix = code_name[G.i].split("_")[-1]
    pattern_name = ""
    for j in range(len(pattern_item)):
        if type(pattern_item[j]) == str:
            G.function_name = pattern_item[j]
        if type(temp_list[j]) == str and temp_list[j] != "reuse dac":
            # 排除原因同 pattern_testitem_merge_rname 的 reuse dac 过滤
            pattern_name = temp_list[j]
            for z in range(len(flow_type)):
                if cp_suffix == flow_cp[z]:
                    if flow_type[z] not in ("os", "shmoo"):
                        if flow_item[z] == G.function_name:
                            name.append(G.function_name)
                            pattern.append(pattern_name)
    return pattern


def fbist_pattern_get():
    global _fbist_pattern_cache
    if _fbist_pattern_cache is not None:
        return list(_fbist_pattern_cache)

    name = G.col("PATTERN", "pattern")
    item = G.col("PATTERN", "item")
    name_flag = ""

    for i in range(len(item)):
        if G.wc["F"][i + 1].fill.fgColor.rgb == "00000000":
            if type(item[i]) == str:
                name_flag = item[i]
            if type(item[i]) == float:
                item[i] = name_flag
        else:
            item[i] = "2768"

    new_temp_list = []
    for i in range(len(name)):
        if name[i] in ("trim mode", "trim dac", "verify mode"):
            new_temp_list.append(recipe_pattern_name(item[i], name[i]))
        else:
            new_temp_list.append(name[i])

    _fbist_pattern_cache = new_temp_list
    return list(new_temp_list)
