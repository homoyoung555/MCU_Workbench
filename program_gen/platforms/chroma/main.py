# Chroma 平台主流程：按 FLOW 表生成各 CP 的 .pln/.pat 程序。
#   - 生产多 site 程序：仅当 chroma 是 VERSION.tester 指定平台时生成，输出到 Chroma_program/。
#   - 实验室单 site 程序：始终生成（站点段换成 1SLAB → 单 site），输出到 Chroma_program/LAB/CHROMA/。
from program_gen.core.flash_seq import flash_pattern_dic_created
from program_gen.core.flash_seq import fbist_mode_pattern_created, flash_mode_value_get, flash_pattern_label_created, nm_read_pattern_created, otp_read_pattern_created, read_status_mode_created
from program_gen.core.pattern_data import fbist_pattern_get, pattern_testitem_merge_rname, pattern_testitem_merge_rpattern
from program_gen.platforms.chroma.adc_writer import adc_test_write
from program_gen.platforms.chroma.opa_writer import opa_test_write
from program_gen.platforms.chroma.pvd_writer import pvd_test_write
from program_gen.platforms.chroma.dac_writer import dac_test_write
from program_gen.platforms.chroma.freq_writer import freq_test_write
from program_gen.platforms.chroma.comp_writer import comp_test_write
from program_gen.platforms.chroma.dc_scan_writer import dc_scan_test_write
from program_gen.platforms.chroma.vilvih_writer import vilvih_test_write, vilvih_swd_test_write
from program_gen.platforms.chroma.pattern_files import clock_force_pattern_created, fbist_pattern_created, flash_compare_patterns_created, get_pin_patterns_created
from program_gen.platforms.chroma.project_files import dec_file_created
from program_gen.platforms.chroma.scan_writer import scan_test_write
from program_gen.platforms.chroma.startup import Hw_Sw_Bin, TEST_PRO, item_variable_created, pln_file_created, start_up_write
from program_gen.platforms.chroma.writers import commit_shmoo_item_write, dynamic_enter_helpers_write, hex_download_write, id_write, keil_pattern_write, main_write, margin_write, nm_read_write, os_write, otp_read_write, shmoo_item_write, sub_flow_write, swd_pattern_write, trim_data_read_write, trim_item_write, uid_write, verify_item_write, vt_write
from program_gen.core.reindent import reindent_tree
from program_gen import state as G
from program_gen.compiler import ProductCompiler


def lab_program_name(name):
    """生产程序名 → 单 site 实验室程序名：把站点段（倒数第 2 段）换成 "1SLAB"。
    例 ..._12SS_CP1 → ..._1SLAB_CP1（MAX_SITE 解析为 1、dec 名为 pin_1SLAB.dec、
    CP 后缀不变，故 99 处按 split("_")[-1] 的 CP 过滤逻辑全部原样复用）。"""
    parts = str(name).split("_")
    parts[-2] = "1SLAB"
    return "_".join(parts)


def _cp_indices(cp):
    """cp（如 "CP1"）→ VERSION 行下标集合；cp=None 时返回 None（代表不过滤/全部）。"""
    if not cp:
        return None
    cp_col = G.col("VERSION", "CP num")
    return {i for i in range(len(cp_col)) if str(cp_col[i]) == cp}


def run(
    base_dir=None,
    master=None,
    cp=None,
    variant=None,
    workbook_model=None,
    product_compilation=None,
):
    """cp: None=全部 CP，或指定 "CP1"/"CP2"/"CP3" 只生成该 CP。
    variant: None/"both"=LAB+量产都生成，"lab"=只生成 LAB 单 site 版，
    "production"=只生成量产多 site 版（仍受 tester==chroma 门控）。"""
    variant = variant or "both"
    workbook_model = workbook_model or G.load_workbook_model(base_dir, master)
    product_compilation = (
        product_compilation or ProductCompiler().compile(workbook_model)
    ).require_success()
    if product_compilation.workbook_identity != workbook_model.identity:
        raise ValueError("ProductCompilation does not belong to the supplied WorkbookModel")
    # 实验室单 site pass（两平台都生成）。先按 lab 模式 init（顺带读取 tester）。
    if variant in ("both", "lab"):
        G.init(base_dir, platform="chroma", mode="lab", master=master,
               workbook_model=workbook_model)
        G.product_compilation = product_compilation
        lab_names = [lab_program_name(n) for n in G.col("VERSION", "Program Name")]
        _generate(lab_names, product_compilation, only=_cp_indices(cp))

    # 生产多 site pass：仅当 chroma 是 VERSION.tester 指定平台时生成。
    if variant in ("both", "production"):
        G.init(base_dir, platform="chroma", mode="production", master=master,
               workbook_model=workbook_model)
        G.product_compilation = product_compilation
        tester = str(G.col("VERSION", "tester")[0]).strip().lower()
        if tester == "chroma":
            _generate(
                list(G.col("VERSION", "Program Name")),
                product_compilation,
                only=_cp_indices(cp),
            )

    # 生成后统一规整 .pln 行首缩进（纯空白，按字节透传）。
    reindent_tree(G.BASE_DIR, "chroma")


def _generate(code_name, product_compilation, only=None):
    """对给定的程序名列表（与 VERSION 行同序）生成一整套 .pln/.pat/.dec。
    生产传各 CP 程序名；实验室传各 CP 的单 site 程序名。输出根由 G.OUT_DIR 决定。
    only: 只生成这些 VERSION 行下标对应的程序（None=全部）——"只生成某个 CP" 用，
    未选中下标不会被 dec/pln 的 'w' 截断覆盖，主循环也直接跳过。"""
    # 按 CP 生成 pin dec，写入各程序自己的 pat/ 文件夹
    dec_file_created(code_name, only=only)
    fbist_pattern_created(product_compilation.pattern_compilation)
    pln_file_created(code_name, only=only)

    read_bit = G.col("VERSION", "read bit")[0]
    G.flash_mode_dic = flash_mode_value_get()
    G.flash_epr_pattern = flash_pattern_dic_created()
    flash_compare_patterns_created(product_compilation.flash_compare_compilation)
    fbist_mode_pattern_created()
    flash_pattern_label_created(read_bit)
    otp_read_pattern_created()   # OTP_READ debug 项 pattern（无条件）
    nm_read_pattern_created()    # NM_Data_Read debug 项 pattern（无条件，仅 chroma）
    read_status_mode_created()   # read_status_mode pattern（母本 pattern sheet 驱动，替换原种子）
    get_pin_patterns_created(code_name)  # keil 组紧凑记法用的 force_1_0/send_num/reset_pattern（无条件，仅 chroma）
    clock_force_pattern_created()  # RCC/RTC 外灌时钟"同 PMU 组"降级用的 <pin>_clkloop（2026-07-07）

    for G.i in range(len(code_name)):
        if only is not None and G.i not in only:
            continue
        print(f"========== 开始处理 {code_name[G.i]} ==========")
        cp_suffix = code_name[G.i].split("_")[-1]
        trim_count = os_count = verify_count = uid_count = 0
        with open(G.OUT_DIR + "\\" + code_name[G.i] + "\\" + code_name[G.i] + ".pln", 'a') as G.f:
            compiled = product_compilation.adapter_view(cp_suffix, "chroma")
            G.compiled_adapter = compiled
            recipe_rows = compiled.recipe_rows
            dac_write_plans = compiled.dac_write_plans
            result_export_plans = compiled.result_export_plans
            item_variable_created(
                code_name, G.i, G.f,
                dac_write_plans=dac_write_plans,
                result_export_plans=result_export_plans,
                addr_map_catalog=compiled.addr_map_catalog,
            )
            Hw_Sw_Bin(
                code_name, G.f, canonical_schedule=compiled.canonical_schedule
            )
            start_up_write(code_name, G.f)

            name = pattern_testitem_merge_rname(code_name)
            pattern = pattern_testitem_merge_rpattern(code_name)
            temp_list = fbist_pattern_get()
            trim_specs = compiled.trim_specs
            dedicated_trim_plans = compiled.dedicated_trim_plans
            persistence_plans = compiled.persistence_plans
            id_plans = compiled.id_plans
            commit_shmoo_plans = compiled.commit_shmoo_plans
            shmoo_plans = compiled.shmoo_plans
            flow_operations = {item.row: item for item in compiled.flow_operations}

            # FLOW 列提升到循环外（原先每个条件都重新取列）
            flow_item = G.col("FLOW", "item")
            for No in range(len(flow_item)):
                if flow_operations.get(No) and flow_operations[No].mode == "fbist":
                    sub_flow_write(code_name, G.f, name, pattern, temp_list, No)

            cp_suffix = code_name[G.i].split("_")[-1]
            dynamic_enter_helpers_write(
                code_name, G.f, trim_specs, cp_suffix, temp_list, recipe_rows,
                dac_write_plans=dac_write_plans,
            )

            for No in range(len(flow_item)):
                operation = flow_operations.get(No)
                kind = operation.typed_kind if operation is not None else ""
                if operation is not None and operation.source_type == "verify":
                    _write_typed_verify(
                        operation, code_name, G.f, No,
                        recipe_rows=recipe_rows,
                        dac_write_plans=dac_write_plans,
                        result_export_plans=result_export_plans,
                    )
                    verify_count += 1
                    continue
                if kind == "SHMOO" and No in commit_shmoo_plans:
                    commit_shmoo_item_write(
                        code_name, G.f, commit_shmoo_plans[No]
                    )
                elif kind == "SHMOO" and No in shmoo_plans:
                    shmoo_item_write(code_name, G.f, shmoo_plans[No])
                if kind == "STANDARD_TRIM":
                    trim_spec = trim_specs.get(No)
                    if trim_spec is None:
                        raise ValueError(f"ProductPlan lacks TrimSpec for FLOW row {No}")
                    for variant in trim_spec.search.variants:
                        mode = "yes" if variant.kind == "BISECTION" else "no"
                        trim_item_write(code_name, G.f, name, pattern, No, mode,
                                        temp_list, trim_spec=trim_spec)
                    trim_count += 1
                if kind == "PDR_TRIM":
                    dedicated_trim_plan = dedicated_trim_plans[No]
                    trim_item_write(
                        code_name, G.f, name, pattern, No, "yes", temp_list,
                        dedicated_trim_plan=dedicated_trim_plan,
                    )
                    trim_count += 1
                if kind == "OS":
                    os_write(code_name, G.f, compiled.os_plans[No])
                    os_count += 1
                if kind in ("WRITE", "READ", "WAKE", "DATA"):
                    trim_data_read_write(
                        code_name, G.f, No, read_bit, recipe_rows.get(No),
                        persistence_plans.for_row(No),
                        trim_data_plan=compiled.trim_data_plan,
                    )
                if kind == "MARGIN":
                    margin_write(code_name, G.f, No)
                if kind == "MAIN":
                    main_write(code_name, G.f, No)
                if kind == "VT":
                    vt_write(code_name, G.f, No)
                if kind == "UID":
                    uid_write(
                        code_name, G.f, No, read_bit, recipe_rows.get(No),
                        id_plan=id_plans.for_row(No),
                    )
                    uid_count += 1
                if kind == "ID":
                    id_write(code_name, G.f, No, id_plan=id_plans.for_row(No))

            # OTP_READ debug 项：无条件生成，不进 FLOW / 不进 TEST_PRO 测试列表
            otp_read_write(code_name, G.f)
            # NM_Data_Read debug 项：无条件生成函数体，接入 TEST_PRO（见 startup）
            nm_read_write(code_name, G.f)

            if trim_count > 0:
                print(f"  --> 完成 {cp_suffix} TRIM ({trim_count} items)")
            if os_count > 0:
                print(f"  --> 完成 {cp_suffix} OS ({os_count} items)")
            if verify_count > 0:
                print(f"  --> 完成 {cp_suffix} VERIFY ({verify_count} items)")
            if uid_count > 0:
                print(f"  --> 完成 {cp_suffix} UID ({uid_count} items)")

            TEST_PRO(
                code_name,
                trim_specs=trim_specs,
                canonical_schedule=compiled.canonical_schedule,
            )
        print(f"========== 完成 {code_name[G.i]} ==========\n")


def _write_typed_verify(
    operation, code_name, stream, row, *, recipe_rows,
    dac_write_plans, result_export_plans,
):
    """Translate one compiler-owned verify kind; no FLOW business inference."""
    kind = operation.typed_kind
    pattern_dir = G.OUT_DIR + "\\" + code_name[G.i] + "\\pat"
    if kind == "STANDARD_VERIFY":
        verify_item_write(
            code_name, stream, row, recipe_rows.get(row),
            dac_write_plan=dac_write_plans.for_row(row),
            result_export_plan=result_export_plans.for_row(row),
        )
    elif kind == "PDR_VERIFY":
        pdr_verify_plan = _chroma_pdr_verify_plan(
            operation, code_name, row
        )
        verify_item_write(
            code_name,
            stream,
            row,
            pdr_verify_plan=pdr_verify_plan,
        )
    elif kind == "VERIFY_HEX":
        hex_download_write(code_name, stream, row)
    elif kind in ("VERIFY_SCAN", "VERIFY_MBIST"):
        scan_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_ADC":
        adc_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_COMP":
        comp_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_OPA":
        opa_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_DAC":
        dac_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_FREQ":
        freq_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_PVD":
        pvd_test_write(code_name, stream, row, pattern_dir)
    elif kind.startswith("VERIFY_DC_"):
        dc_scan_test_write(code_name, stream, row, pattern_dir, operation.mode)
    elif kind == "VERIFY_VIH_VIL" and operation.mode == "keil":
        vilvih_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_VIH_VIL" and operation.mode == "swd":
        vilvih_swd_test_write(code_name, stream, row, pattern_dir)
    elif kind == "VERIFY_KEIL":
        keil_pattern_write(code_name, stream, row)
    elif kind == "VERIFY_SWD":
        swd_pattern_write(code_name, stream, row, pattern_dir)
    else:
        raise ValueError(f"unsupported Chroma typed verify kind: {kind}")


def _chroma_pdr_verify_plan(operation, code_name, row):
    adapter = getattr(G, "compiled_adapter", None)
    plans = getattr(adapter, "pdr_verify_plans", None)
    plan = None if plans is None else plans.get(row)
    if plan is None:
        raise ValueError(
            f"CHROMA.PDR_VERIFY.PLAN_MISSING: no typed plan for FLOW row {row}"
        )
    program_cp = code_name[G.i].split("_")[-1]
    adapter_cp = getattr(adapter, "cp", None)
    if (
        plan.cp.casefold() != operation.cp.casefold()
        or not isinstance(adapter_cp, str)
        or adapter_cp.casefold() != program_cp.casefold()
    ):
        raise ValueError(
            "CHROMA.PDR_VERIFY.CP_MISMATCH: plan/operation or adapter/program CP differ"
        )
    if plan.item.casefold() != operation.item.casefold():
        raise ValueError(
            "CHROMA.PDR_VERIFY.ITEM_MISMATCH: plan and operation item differ"
        )
    if plan.row != row or plan.provenance != operation.provenance:
        raise ValueError(
            "CHROMA.PDR_VERIFY.PROVENANCE_MISMATCH: plan and operation source differ"
        )
    if getattr(plan.platform, "value", None) != "chroma":
        raise ValueError(
            "CHROMA.PDR_VERIFY.PROFILE_MISMATCH: typed plan is not Chroma"
        )
    if plan.typed_kind != "PDR_VERIFY":
        raise ValueError(
            "CHROMA.PDR_VERIFY.KIND_MISMATCH: typed plan kind is not PDR_VERIFY"
        )
    return plan
