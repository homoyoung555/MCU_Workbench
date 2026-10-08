"""STANDARD_TRIM / Hsi_8M CP1 domain-fact forensic matrix (pure, read-only).

This module builds the domain-fact evidence package for one STANDARD_TRIM
target.  It consumes ONLY the already-compiled typed facts of a
``ProductCompilation`` (via a duck-typed snapshot extraction) and never:

- reads Excel raw objects (no openpyxl / pandas / WorkbookReader),
- reads ``G``, calls legacy platform writers, or consumes Golden output,
- scans the filesystem or re-derives facts from file names / item names,
- invents default values, and never fabricates contracts with placeholders,
- produces tester text, ``ProgramContribution``, ``SectionFragment`` or any
  renderer/registry change.

Every fact is marked CONFIRMED / MISSING / CONTRADICTED with its scope, typed
producer, authoritative source, confirmed value (or the precise reason it is
missing) and the adjudication question that needs a ruling before the next
round can design a typed domain model.  If not all seven domain contracts have
a complete authoritative typed source, the package STOPS at "pending
confirmation" and proposes no model interface draft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import html
from typing import Iterable, Mapping, Sequence, Tuple


# The seven STANDARD_TRIM domain contracts under forensic review.  They match
# the gap declaration in program_gen.shadow.typed_profile.MISSING_DOMAIN_MODELS.
CONTRACTS = (
    "PowerContract",
    "FbistContract",
    "MeasurementContract",
    "TimingContract",
    "RelayContract",
    "HelperContract",
    "SkeletonProducer",
)


class FactStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    MISSING = "MISSING"
    CONTRADICTED = "CONTRADICTED"


@dataclass(frozen=True)
class DomainFact:
    """One forensic fact about one of the seven domain contracts.

    ``value`` carries the confirmed typed value, or, when the fact is MISSING,
    the precise reason it has no authoritative typed source.  ``adjudication``
    is the question that needs 蛤蟆羊先生's ruling.
    """

    contract: str
    fact_name: str
    scope: str
    typed_producer: str
    authority: str
    status: FactStatus
    value: str
    adjudication: str = ""


@dataclass(frozen=True)
class StandardTrimFactSnapshot:
    """Pure snapshot of the typed facts consumed for one STANDARD_TRIM target.

    Every field below is copied from typed plan objects (TrimSpec, canonical
    schedule, TestDefinition, plan groups, TargetPlatformProfile).  No value is
    invented here and no default is injected: a missing value stays ``None``.
    """

    # target identity
    cp: str
    item: str
    platform: str
    variant: str
    program_name: str
    # flow classification
    mode: str
    typed_kind: str
    family: str
    flow_type: str
    # TrimSpec
    vcc: str
    protocol_enter_pattern: str
    protocol_exit_pattern: str
    dac_pattern_name: str
    dac_field_name: str
    dac_field_width: int
    dac_default_value: str
    measurement_family: str
    measurement_unit: str
    measurement_pin: str
    measurement_force: str
    measurement_target: object
    measurement_low_limit: str
    measurement_high_limit: str
    search_bits: int
    search_domain_source: str
    search_variant_kinds: Tuple[str, ...]
    search_scheduled_kinds: Tuple[str, ...]
    dependencies: Tuple[str, ...]
    adjust: str
    dac_final_symbol: str
    # canonical recipe
    effective_recipe: Tuple[str, ...]
    datalog_points: Tuple[str, ...]
    # typed operation waits (None means the mother does not provide a value)
    enter_wait: object
    trim_force_wait: object
    trim_set_wait: object
    judge_force_wait: object
    judge_set_wait: object
    per_point_wait_any: bool
    # typed helper references
    dependency_helper_names: Tuple[str, ...]
    # canonical schedule
    definition_identity: str
    definition_render_name: str
    schedule_entries: Tuple[str, ...]
    hardware_bin: str
    software_bin: str
    # CP plan groups
    environment_catalogs: Tuple[str, ...]
    lifecycle_contributions: Tuple[str, ...]
    helper_identities: Tuple[str, ...]
    resource_identities: Tuple[str, ...]
    runtime_symbol: str
    runtime_symbol_width: int
    # platform file-level naming facts (TargetPlatformProfile)
    chroma_section_order: Tuple[str, ...]
    s100_section_order: Tuple[str, ...]
    chroma_enter_pattern_path: str
    s100_enter_pattern_path: str
    chroma_program_extension: str
    s100_program_extension: str
    # provenance
    workbook_identity: str
    compilation_identity: str
    # the presence of FBIST protocol patterns inside the CP resource closure
    fbist_protocol_in_resources: bool


def extract_snapshot(
    compilation,
    *,
    cp: str = "CP1",
    item: str = "Hsi_8M",
    platform: str = "chroma",
    variant: str = "lab",
    program_name: str = "V_TEST_CP1",
) -> StandardTrimFactSnapshot:
    """Extract a pure snapshot from a compiled ProductCompilation graph.

    The extraction is duck-typed: it only reads attributes of the compiled
    plan objects (ProductCompilation -> ProductPlan -> catalogs / CpProgramPlan
    / CanonicalSchedulePlan / TrimSpec / TargetPlatformProfile).  It never
    opens files, never imports the workbook reader or pandas, and never calls
    any legacy writer.
    """
    _require(compilation is not None, "compilation cannot be None")
    plan = compilation.plan
    _require(plan is not None, "compilation.plan is None (failed compilation)")
    catalogs = plan.catalogs

    specs = [
        spec
        for spec in catalogs.trim_specs.values()
        if str(spec.cp).strip().casefold() == str(cp).strip().casefold()
        and str(spec.item).strip().casefold() == str(item).strip().casefold()
    ]
    _require(
        len(specs) == 1,
        f"expected exactly one TrimSpec for {cp}/{item}, found {len(specs)}",
    )
    spec = specs[0]

    cp_plan = plan.cp_plans[str(cp).strip().upper()]
    schedule = cp_plan.canonical_schedule
    _require(
        schedule is not None,
        "CP canonical schedule is None; STANDARD_TRIM matrix requires it",
    )

    definitions = [
        definition
        for definition in schedule.definitions
        if str(definition.cp).strip().casefold() == str(cp).strip().casefold()
        and str(definition.item).strip().casefold() == str(item).strip().casefold()
        and str(definition.source_rows) == f"({spec.flow_row_index + 2},)"
    ]
    _require(
        len(definitions) == 1,
        f"expected exactly one canonical definition for {cp}/{item} "
        f"(row {spec.flow_row_index + 2}), found {len(definitions)}",
    )
    definition = definitions[0]
    entries = [
        entry
        for entry in schedule.entries
        if str(entry.definition_id).casefold()
        == str(definition.identity).casefold()
    ]

    test_definitions = [
        test
        for test in cp_plan.definitions
        if str(test.identity).casefold() == str(definition.identity).casefold()
    ]
    _require(
        len(test_definitions) == 1,
        f"expected exactly one TestDefinition for {definition.identity!r}",
    )
    test = test_definitions[0]

    symbols = [
        symbol
        for symbol in cp_plan.runtime_state.symbols
        if str(symbol.ref.namespace).casefold() == "result"
        and str(symbol.ref.semantic_key).casefold()
        == str(spec.dac_final_symbol).casefold()
    ]
    _require(
        len(symbols) <= 1,
        f"expected at most one RESULT symbol for {spec.dac_final_symbol!r}",
    )

    profile_facts = _platform_profile_facts(platform)
    chroma_profile = _platform_profile_facts("chroma")
    s100_profile = _platform_profile_facts("s100")

    operation_waits = {
        operation.kind: operation
        for operation in spec.operations
    }
    per_point = getattr(spec.search, "per_point_actions", ())
    per_point_wait_any = any(
        getattr(operation, "wait", None) is not None
        or getattr(operation, "force_wait", None) is not None
        or getattr(operation, "set_wait", None) is not None
        for operation in per_point
    )

    helper_names = tuple(
        sorted(
            {
                operation.helper_name
                for operation in spec.operations
                if operation.kind == "DEPEND" and operation.helper_name
            }
        )
    )

    environment = cp_plan.environment
    lifecycle = cp_plan.lifecycle
    helpers = cp_plan.helpers
    resources = cp_plan.resources

    return StandardTrimFactSnapshot(
        cp=str(cp).strip().upper(),
        item=str(item).strip(),
        platform=str(platform).strip().casefold(),
        variant=str(variant).strip(),
        program_name=str(program_name).strip(),
        mode=str(spec.mode),
        typed_kind=str(test.typed_kind),
        family=str(test.family),
        flow_type=str(test.flow_type),
        vcc=str(spec.vcc),
        protocol_enter_pattern=str(spec.protocol.enter_pattern),
        protocol_exit_pattern=str(spec.protocol.exit_pattern),
        dac_pattern_name=str(spec.dac.pattern_name),
        dac_field_name=str(spec.dac.field.name),
        dac_field_width=int(spec.dac.field_width),
        dac_default_value=str(spec.dac.default_value),
        measurement_family=str(spec.measurement.family),
        measurement_unit=str(spec.measurement.unit),
        measurement_pin=str(spec.measurement.pin),
        measurement_force=str(spec.measurement.force),
        measurement_target=spec.measurement.target,
        measurement_low_limit=str(spec.measurement.low_limit),
        measurement_high_limit=str(spec.measurement.high_limit),
        search_bits=int(spec.search.search_bits),
        search_domain_source=str(spec.search.domain_source),
        search_variant_kinds=tuple(v.kind for v in spec.search.variants),
        search_scheduled_kinds=tuple(
            v.kind for v in spec.search.variants if v.scheduled
        ),
        dependencies=tuple(spec.dependencies),
        adjust="NONE" if spec.adjust is None else str(spec.adjust),
        dac_final_symbol=str(spec.dac_final_symbol),
        effective_recipe=tuple(test.effective_recipe),
        datalog_points=tuple(test.datalog_points),
        enter_wait=_wait_text(operation_waits.get("ENTER")),
        trim_force_wait=_wait_text(operation_waits.get("TRIM"), "force_wait"),
        trim_set_wait=_wait_text(operation_waits.get("TRIM"), "set_wait"),
        judge_force_wait=_wait_text(operation_waits.get("JUDGE"), "force_wait"),
        judge_set_wait=_wait_text(operation_waits.get("JUDGE"), "set_wait"),
        per_point_wait_any=per_point_wait_any,
        dependency_helper_names=helper_names,
        definition_identity=str(definition.identity),
        definition_render_name=str(definition.render_name),
        schedule_entries=tuple(
            _entry_text(entry) for entry in entries
        ),
        hardware_bin=str(entries[0].bin_binding.hardware_bin)
        if entries else "",
        software_bin=str(entries[0].bin_binding.software_bin)
        if entries else "",
        environment_catalogs=tuple(
            str(item_name) for item_name in environment.configured_catalogs
        ),
        lifecycle_contributions=tuple(
            str(item_name) for item_name in lifecycle.contributions
        ),
        helper_identities=tuple(
            str(item_name) for item_name in helpers.identities
        ),
        resource_identities=tuple(
            str(item_name) for item_name in resources.identities
        ),
        runtime_symbol=str(symbols[0].name) if symbols else "",
        runtime_symbol_width=int(symbols[0].bit_width) if symbols else 0,
        chroma_section_order=tuple(chroma_profile.section_order),
        s100_section_order=tuple(s100_profile.section_order),
        chroma_enter_pattern_path=chroma_profile.pattern_path(
            spec.protocol.enter_pattern
        ),
        s100_enter_pattern_path=s100_profile.pattern_path(
            spec.protocol.enter_pattern
        ),
        chroma_program_extension=chroma_profile.program_extension,
        s100_program_extension=s100_profile.program_extension,
        workbook_identity=str(compilation.workbook_identity),
        compilation_identity=str(compilation.identity),
        fbist_protocol_in_resources=(
            str(spec.protocol.enter_pattern).casefold()
            in {str(name).casefold() for name in resources.identities}
        ),
    )


# ---------------------------------------------------------------------------
# Fact inventory: the forensic matrix for the seven domain contracts.
# ---------------------------------------------------------------------------


def build_fact_matrix(snapshot: StandardTrimFactSnapshot) -> Tuple[DomainFact, ...]:
    """Return the deterministic forensic fact list for the snapshot."""
    facts: list[DomainFact] = []

    def add(
        contract: str,
        name: str,
        scope: str,
        producer: str,
        authority: str,
        status: FactStatus,
        value: str,
        adjudication: str = "",
    ) -> None:
        facts.append(DomainFact(
            contract=contract,
            fact_name=name,
            scope=scope,
            typed_producer=producer,
            authority=authority,
            status=status,
            value=value,
            adjudication=adjudication,
        ))

    scope_neutral = f"{snapshot.cp} / platform-neutral / {snapshot.variant}"
    scope_chroma = f"{snapshot.cp} / chroma / {snapshot.variant}"
    scope_s100 = f"{snapshot.cp} / s100 / {snapshot.variant}"
    scope_both = f"{snapshot.cp} / chroma+s100 / {snapshot.variant}"

    # ------------------------------------------------------------------
    # PowerContract
    # ------------------------------------------------------------------
    add(
        "PowerContract",
        "供电轨 Vcc 值",
        scope_neutral,
        "TrimSpec.vcc",
        "FLOW 'Vcc' 单元格 → program_gen/core/trim_spec.py _compile_spec",
        FactStatus.CONFIRMED,
        snapshot.vcc,
        "VCC_TYP 是符号轨名还是电压字面量？POWER_ON 消费哪个轨名？",
    )
    add(
        "PowerContract",
        "POWER_ON 上电序列",
        scope_both,
        "无 typed producer",
        "ProductCompilation 无 PowerPlan；EnvironmentGroup 仅声明 'LEVEL' 目录名",
        FactStatus.MISSING,
        "缺失原因：typed 层未编译任何上电序列事实；PlatformRenderPlanner/旧 writer 中的 "
        "POWER_ON 实现不属于本包可消费的 typed 来源",
        "STANDARD_TRIM 的 POWER_ON 序列是否固定（如 RELAY→POWER_ON(Vcc)→FBIST 进入）？"
        "归属 PowerContract 还是 SkeletonProducer 默认骨架？",
    )
    add(
        "PowerContract",
        "POWER_OFF 下电序列",
        scope_both,
        "无 typed producer",
        "同上：typed 层无下电序列事实",
        FactStatus.MISSING,
        "缺失原因：与 POWER_ON 相同，typed 层无任何下电/安全释放事实",
        "POWER_OFF 是否每次测试函数结尾固定执行？失败路径是否相同？",
    )
    add(
        "PowerContract",
        "电源建立/稳定时间",
        scope_both,
        "无 typed producer",
        "TrimSpec/TrimOperation 无 power 等待字段",
        FactStatus.MISSING,
        "缺失原因：typed 层不存在电源稳定时间字段",
        "电源稳定时间是否需要 typed 字段，还是固定由平台默认（不允许默认值的裁决项）？",
    )
    add(
        "PowerContract",
        "平台电源能力 Profile",
        scope_both,
        "无 typed producer",
        "TargetPlatformProfile 仅含文件命名事实，无电源轨/API 能力",
        FactStatus.MISSING,
        "缺失原因：无平台电源能力 typed 事实（轨集合、DPS 通道、API 形态）",
        "PowerContract 是否需要按平台注册电源轨集合与 POWER_ON/OFF API 契约？",
    )

    # ------------------------------------------------------------------
    # FbistContract
    # ------------------------------------------------------------------
    add(
        "FbistContract",
        "FBIST 进入 Pattern 逻辑名",
        scope_neutral,
        "TrimSpec.protocol.enter_pattern (TrimProtocolPlan)",
        "program_gen/core/trim_spec.py _compile_spec（硬编码常量，非母本输入）",
        FactStatus.CONFIRMED,
        snapshot.protocol_enter_pattern,
        "该值为 typed 层硬编码而非母本输入：是否权威？两平台是否同名？",
    )
    add(
        "FbistContract",
        "FBIST 退出 Pattern 逻辑名",
        scope_neutral,
        "TrimSpec.protocol.exit_pattern (TrimProtocolPlan)",
        "program_gen/core/trim_spec.py _compile_spec（硬编码常量，非母本输入）",
        FactStatus.CONFIRMED,
        snapshot.protocol_exit_pattern,
        "退出 Pattern 是否每次 FBIST 结束都执行？",
    )
    add(
        "FbistContract",
        "FBIST 进入 Pattern 平台文件映射",
        scope_both,
        "TargetPlatformProfile.pattern_path",
        "program_gen/shadow/profile.py（chroma 'pat/...'、s100 '' 前缀 + 扩展名）",
        FactStatus.CONFIRMED,
        f"chroma: {snapshot.chroma_enter_pattern_path}; "
        f"s100: {snapshot.s100_enter_pattern_path}",
        "",
    )
    add(
        "FbistContract",
        "FBIST 进入/退出时序（WAIT）",
        scope_both,
        "无 typed producer",
        "TrimProtocolPlan 无等待字段；TrimOperation.wait 属于 ENTER 模块而非 FBIST 协议",
        FactStatus.MISSING,
        "缺失原因：FBIST 协议层无任何时序事实",
        "进入 FBIST 后是否固定需要 WAIT？默认值由谁裁决？",
    )
    add(
        "FbistContract",
        "per-item ENTER 与共享 FBIST 协议 Pattern 的关系",
        scope_neutral,
        "TrimSpec.operations[ENTER].reference + TrimSpec.protocol",
        "typed 层同时存在 enter_hsi_8m（ENTER 模块）与 enter_fbist_mode（协议）",
        FactStatus.MISSING,
        "缺失原因：typed 层无事实说明两者执行顺序/嵌套关系；"
        "resources 闭包含 enter_hsi_8m 但不含 enter_fbist_mode（见 CONTRADICTED 项）",
        "执行顺序：先 FBIST 协议 Pattern 再 per-item ENTER Pattern？还是二选一？",
    )
    fbist_resource_value = (
        "一致：CpProgramPlan.resources 与 Contribution 的 standard_trim_pattern_names "
        "均包含 enter_fbist_mode/exit_fbist_mode（单一所有权：Recipe → closure → "
        "reference；闭包缺失任一 Recipe 资源声明时以 SC.RESOURCE.CLOSURE_MISSING 阻断）"
        if snapshot.fbist_protocol_in_resources
        else "矛盾：CpProgramPlan.resources 不含 enter_fbist_mode/exit_fbist_mode；"
        "standard_trim_contribution.standard_trim_pattern_names 却要求这两个 Pattern "
        "进入资源清单，两个 typed producer 相互矛盾"
    )
    add(
        "FbistContract",
        "FBIST 协议 Pattern 的资源闭包归属",
        scope_neutral,
        "CpProgramPlan.resources.identities（Recipe→closure 单一所有权）vs "
        "standard_trim_contribution.standard_trim_pattern_names（closure→reference）",
        "program_plan.py _resource_identities（含协议 Pattern）vs "
        "core/standard_trim_contribution.py _validate_resource_closure",
        FactStatus.CONFIRMED
        if snapshot.fbist_protocol_in_resources else FactStatus.CONTRADICTED,
        fbist_resource_value,
        "" if snapshot.fbist_protocol_in_resources
        else "FBIST 协议 Pattern 是否属于 STANDARD_TRIM 的资源需求？以哪个 typed producer 为准？",
    )

    # ------------------------------------------------------------------
    # MeasurementContract
    # ------------------------------------------------------------------
    add(
        "MeasurementContract",
        "测量族 family",
        scope_neutral,
        "TrimSpec.measurement.family",
        "FLOW 'UNIT' 单元格 → trim_spec._compile_measurement",
        FactStatus.CONFIRMED,
        snapshot.measurement_family,
        "",
    )
    add(
        "MeasurementContract",
        "测量单位 unit",
        scope_neutral,
        "TrimSpec.measurement.unit",
        "FLOW 'UNIT' 单元格（原样保留）",
        FactStatus.CONFIRMED,
        snapshot.measurement_unit,
        "",
    )
    add(
        "MeasurementContract",
        "测量 pin",
        scope_neutral,
        "TrimSpec.measurement.pin",
        "FLOW 'meas pin' 单元格",
        FactStatus.CONFIRMED,
        snapshot.measurement_pin,
        "",
    )
    add(
        "MeasurementContract",
        "Force 类型 (FV/FI)",
        scope_neutral,
        "TrimSpec.measurement.force",
        "FLOW 'FV/FI' 单元格",
        FactStatus.CONFIRMED,
        snapshot.measurement_force,
        "Hsi_8M 为 '/'（无 force）：FREQUENCY 测量是否需要 Force 语义？",
    )
    add(
        "MeasurementContract",
        "target 目标值",
        scope_neutral,
        "TrimSpec.measurement.target",
        "FLOW 'target' 单元格（保留 int/float 原始类型）",
        FactStatus.CONFIRMED,
        _display(snapshot.measurement_target),
        "",
    )
    add(
        "MeasurementContract",
        "low/high limit 百分比",
        scope_neutral,
        "TrimSpec.measurement.low_limit / high_limit",
        "FLOW 'low_range(%)' / 'high_range(%)' 单元格",
        FactStatus.CONFIRMED,
        f"low={snapshot.measurement_low_limit}, high={snapshot.measurement_high_limit}",
        "limit 解释（相对 target 的百分比？）是否有权威 typed 定义？",
    )
    add(
        "MeasurementContract",
        "每点测量动作 MEASURE",
        scope_neutral,
        "TrimSpec.search.per_point_actions (TrimOperation 'MEASURE')",
        "trim_spec._compile_spec：per_point = SET_DAC → [PE] → MEASURE",
        FactStatus.CONFIRMED,
        "EACH_SEARCH_POINT MEASURE 存在于搜索逐点动作中",
        "",
    )
    add(
        "MeasurementContract",
        "测量方法/积分/采样方式",
        scope_both,
        "无 typed producer",
        "MeasurementPlan 无测量方法字段",
        FactStatus.MISSING,
        "缺失原因：FREQUENCY 测量的积分/采样/判断方法无 typed 事实",
        "频率测量方法（周期平均？采样数？）由 MeasurementContract 定义还是平台 Profile？",
    )
    add(
        "MeasurementContract",
        "JUDGE 判定与 Datalog 语义",
        scope_neutral,
        "TrimSpec.operations[JUDGE] + TestDefinition.datalog_points",
        "JUDGE 动作存在于 TrimSpec；Datalog 身份来自 canonical definition",
        FactStatus.CONFIRMED,
        f"JUDGE 动作存在；datalog_points={snapshot.datalog_points}",
        "JUDGE 的 pass/fail 判定与 Datalog 输出是否需要独立 typed 契约？",
    )
    add(
        "MeasurementContract",
        "JUDGE limit 应用语义",
        scope_neutral,
        "无 typed producer",
        "MeasurementPlan 仅有 limit 字面量，无应用规则",
        FactStatus.MISSING,
        "缺失原因：limit 如何应用到 target（比例/绝对）无 typed 事实",
        "±0.4% 的判定公式由谁权威定义？",
    )

    # ------------------------------------------------------------------
    # TimingContract
    # ------------------------------------------------------------------
    add(
        "TimingContract",
        "Recipe 时间参数能力（WAIT/FWAIT/SWAIT 解析）",
        scope_both,
        "flow_recipe.RecipeDuration + TrimOperation.wait/force_wait/set_wait",
        "flow_recipe.py _MODULE_TIME_PARAMETERS + recipe_trim.py",
        FactStatus.CONFIRMED,
        "typed 字段存在（amount+unit，US/MS）；母本可显式填写",
        "",
    )
    add(
        "TimingContract",
        "ENTER WAIT",
        scope_neutral,
        "TrimOperation.wait",
        "Recipe 'ENTER(WAIT=...)' 参数；本 item 未填写",
        FactStatus.MISSING
        if snapshot.enter_wait is None else FactStatus.CONFIRMED,
        _wait_reason(snapshot.enter_wait, "ENTER WAIT"),
        "未填写时是否允许平台默认时序？（本包不注入默认值）",
    )
    add(
        "TimingContract",
        "TRIM FWAIT（Force 等待）",
        scope_neutral,
        "TrimOperation.force_wait",
        "Recipe 'TRIM(FWAIT=...)' 参数；本 item 未填写",
        FactStatus.MISSING
        if snapshot.trim_force_wait is None else FactStatus.CONFIRMED,
        _wait_reason(snapshot.trim_force_wait, "TRIM FWAIT"),
        "TRIM 循环内 Force 后是否需要等待？",
    )
    add(
        "TimingContract",
        "TRIM SWAIT（Set DAC 等待）",
        scope_neutral,
        "TrimOperation.set_wait",
        "Recipe 'TRIM(SWAIT=...)' 参数；本 item 未填写",
        FactStatus.MISSING
        if snapshot.trim_set_wait is None else FactStatus.CONFIRMED,
        _wait_reason(snapshot.trim_set_wait, "TRIM SWAIT"),
        "SET_DAC 后是否需要等待？",
    )
    add(
        "TimingContract",
        "JUDGE FWAIT / SWAIT",
        scope_neutral,
        "TrimOperation.force_wait / set_wait (JUDGE)",
        "Recipe 'JUDGE(FWAIT=...,SWAIT=...)' 参数；本 item 未填写",
        FactStatus.MISSING
        if snapshot.judge_force_wait is None and snapshot.judge_set_wait is None
        else FactStatus.CONFIRMED,
        _wait_reason(
            snapshot.judge_force_wait or snapshot.judge_set_wait,
            "JUDGE 时序",
        ),
        "JUDGE 前是否需要重新 Force/Set 并等待？",
    )
    add(
        "TimingContract",
        "逐点 SET_DAC/MEASURE 间时序",
        scope_neutral,
        "TrimSpec.search.per_point_actions",
        "per_point 动作无 wait 字段值",
        FactStatus.MISSING
        if not snapshot.per_point_wait_any else FactStatus.CONFIRMED,
        "缺失原因：EACH_SEARCH_POINT 的 SET_DAC/MEASURE 无任何等待事实"
        if not snapshot.per_point_wait_any else "逐点动作存在等待事实",
        "逐点测量是否需要固定等待？",
    )
    add(
        "TimingContract",
        "平台等待语义（WAIT → tester 语句/电平稳定）",
        scope_both,
        "无 typed producer",
        "typed 层仅保留 RecipeDuration，无平台语义",
        FactStatus.MISSING,
        "缺失原因：WAIT 如何落到各平台语句无 typed 事实",
        "TimingContract 与平台 Profile 的分工？",
    )

    # ------------------------------------------------------------------
    # RelayContract
    # ------------------------------------------------------------------
    add(
        "RelayContract",
        "RELAY 环境目录声明",
        scope_neutral,
        "CpProgramPlan.environment.configured_catalogs",
        "program_plan.py compile_program_plan（硬编码目录元组）",
        FactStatus.CONFIRMED,
        f"{snapshot.environment_catalogs}（含 'RELAY'）",
        "",
    )
    add(
        "RelayContract",
        "每目标 relay 值（FLOW 'relay' 列）",
        scope_neutral,
        "无 typed producer",
        "ProductCompilation 未编译 relay 列；platform_render.resolve_standard_trim_context "
        "在 render 层直接读 workbook FLOW/PIN DEC（不属于本包可消费的 typed 来源）",
        FactStatus.MISSING,
        "缺失原因：relay 单元格未被编译进 ProductCompilation 的任何 typed 计划；"
        "本包不读 Excel 原始对象，故该值不可作为 typed 事实",
        "FLOW 'relay' 列是否应编译进 typed RelayContract（逐目标）？"
        "PIN DEC 校验（relay 必须声明）权威落在哪层？",
    )
    add(
        "RelayContract",
        "CBIT 策略（relay ON/OFF 时序）",
        scope_both,
        "无 typed producer",
        "typed 层无 CBIT/relay 时序事实（5mS 等仅存在于旧 writer，不作为事实源）",
        FactStatus.MISSING,
        "缺失原因：无 CBIT 开关时序的 typed 事实",
        "relay ON/OFF 时序（如 5mS）与 FBIST 进出场的关系由谁裁决？",
    )
    add(
        "RelayContract",
        "平台 relay API 契约",
        scope_both,
        "无 typed producer",
        "SET_CBIT/RELAY_ON 等仅存在于 legacy platform writers",
        FactStatus.MISSING,
        "缺失原因：无平台 relay API 的 typed 注册事实",
        "RelayContract 是否需要按平台声明 relay API 能力？",
    )

    # ------------------------------------------------------------------
    # HelperContract
    # ------------------------------------------------------------------
    add(
        "HelperContract",
        "DEPEND helper_name 字段存在性",
        scope_neutral,
        "TrimOperation.helper_name (DEPEND)",
        "program_gen/core/trim_spec.py _compile_dependency_operation",
        FactStatus.CONFIRMED,
        f"{snapshot.dependency_helper_names}",
        "helper 名由 item 名经 recipe_trim.trim_data_helper_name 字符串推导——"
        "按取证规则不得作为事实来源；真实 helper 名需确认",
    )
    add(
        "HelperContract",
        "本 item 自身 trim-data helper 引用",
        scope_neutral,
        "standard_trim_contribution 的 HELPER SymbolRequirement "
        "(trim_data_helper_name(spec.item))",
        "core/standard_trim_contribution.py：requires HELPER "
        "trim_data_helper_name(spec.item)",
        FactStatus.MISSING,
        "缺失原因：helper 名 'set_hsi_8m_trim_data' 由 item 名推导，无权威 typed 来源；"
        "该 Contribution 投影本身被 Gap Model 阻断（SG.PROJECTION.UNAVAILABLE）",
        "set_hsi_8m_trim_data 的真实签名/命名由谁确认？",
    )
    add(
        "HelperContract",
        "helper 签名/参数契约",
        scope_neutral,
        "无 typed producer",
        "typed 层仅有 helper_name 字符串，无签名",
        FactStatus.MISSING,
        "缺失原因：无 helper 参数（如 DAC 值来源）、返回/副作用契约",
        "helper 接收什么参数（REG 值？DAC code？）？",
    )
    add(
        "HelperContract",
        "helper 形态（函数/宏）与平台命名",
        scope_both,
        "无 typed producer",
        "CpProgramPlan.helpers.identities 仅含模块名（OS_TEST/DEPEND/...），"
        "不含 helper 函数名",
        FactStatus.MISSING,
        "缺失原因：helpers 组是模块级身份，非 helper 函数契约",
        "helper 是函数还是宏？两平台命名是否一致？",
    )
    add(
        "HelperContract",
        "DEPEND 的 Set-DAC 需求声明",
        scope_neutral,
        "TrimOperation.source_symbol + helper_name (DEPEND)",
        "trim_spec._compile_dependency_operation（DAC_FINAL 来源 + helper）",
        FactStatus.CONFIRMED,
        "DEPEND 引用 DAC_FINAL 来源（VREF0P8_ABS_DAC_FINAL 等）并声明 set-helper 需求",
        "",
    )

    # ------------------------------------------------------------------
    # SkeletonProducer
    # ------------------------------------------------------------------
    add(
        "SkeletonProducer",
        "Chroma section 顺序",
        scope_chroma,
        "TargetPlatformProfile.section_order",
        "program_gen/shadow/profile.py CHROMA_PROFILE",
        FactStatus.CONFIRMED,
        f"{snapshot.chroma_section_order}",
        "",
    )
    add(
        "SkeletonProducer",
        "S100 section 顺序",
        scope_s100,
        "TargetPlatformProfile.section_order",
        "program_gen/shadow/profile.py S100_PROFILE",
        FactStatus.CONFIRMED,
        f"{snapshot.s100_section_order}",
        "",
    )
    add(
        "SkeletonProducer",
        "程序扩展名与 Pattern 前缀",
        scope_both,
        "TargetPlatformProfile.program_extension / pattern_prefix",
        "program_gen/shadow/profile.py",
        FactStatus.CONFIRMED,
        f"chroma .{snapshot.chroma_program_extension.removeprefix('.')} / pat/; "
        f"s100 .{snapshot.s100_program_extension.removeprefix('.')} / 无前缀",
        "",
    )
    add(
        "SkeletonProducer",
        "Lifecycle 贡献组（空）",
        scope_neutral,
        "CpProgramPlan.lifecycle (LifecycleGroup)",
        "program_plan.py compile_program_plan：LifecycleGroup(())",
        FactStatus.CONFIRMED,
        f"lifecycle.contributions={snapshot.lifecycle_contributions}（当前无 typed 生产者提交）",
        "Lifecycle Hook（START_UP/test_start/TEST_PRO/test_end/RELEASE）"
        "的 typed 形态由 SkeletonProducer 定义？",
    )
    add(
        "SkeletonProducer",
        "骨架内容（START_UP/test_start/TEST_PRO/test_end/RELEASE）",
        scope_both,
        "无 typed producer",
        "typed 层无 SkeletonProducer；骨架文本仅存在于 legacy platform writers "
        "（不作为事实源）",
        FactStatus.MISSING,
        "缺失原因：无 typed 骨架生产者；Gap Model 声明 SkeletonProducer 缺失",
        "骨架内容是否每个平台固定生成、不可裁掉（CONTEXT.md 语义）？",
    )
    add(
        "SkeletonProducer",
        "环境目录声明（PIN/LEVEL/TIMING/RELAY/BIN）",
        scope_neutral,
        "CpProgramPlan.environment.configured_catalogs",
        "program_plan.py compile_program_plan（硬编码目录元组）",
        FactStatus.CONFIRMED,
        f"{snapshot.environment_catalogs}",
        "环境目录与各 Contract 的对应关系是否需要在模型层显式化？",
    )

    return tuple(facts)


def pending_adjudication_questions(
    snapshot: StandardTrimFactSnapshot,
    facts: Sequence[DomainFact],
) -> Tuple[str, ...]:
    """Return the de-duplicated adjudication questions that need a ruling."""
    seen = set()
    questions = []
    for fact in facts:
        question = str(fact.adjudication).strip()
        key = question.casefold()
        if question and key not in seen:
            seen.add(key)
            questions.append(question)
    return tuple(questions)


def typed_contracts_complete(facts: Sequence[DomainFact]) -> bool:
    """True only when every contract has a complete authoritative typed source.

    A contract counts as complete only when it carries a CONFIRMED fact for its
    core semantic value AND none of its core facts is MISSING/CONTRADICTED.
    For the current STANDARD_TRIM / Hsi_8M CP1 evidence this is False, which
    forces the package to stop at "pending confirmation".
    """
    by_contract: dict[str, list[DomainFact]] = {}
    for fact in facts:
        by_contract.setdefault(fact.contract, []).append(fact)
    for contract in CONTRACTS:
        contract_facts = by_contract.get(contract, ())
        if not contract_facts:
            return False
        if any(
            fact.status in (FactStatus.MISSING, FactStatus.CONTRADICTED)
            for fact in contract_facts
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Pure HTML report renderer.
# ---------------------------------------------------------------------------


def render_html(
    snapshot: StandardTrimFactSnapshot,
    facts: Sequence[DomainFact],
    questions: Sequence[str],
) -> str:
    """Render the standalone HTML fact-matrix report (no tester text)."""
    complete = typed_contracts_complete(facts)
    contract_summary = _contract_summary(facts)
    rows = "\n".join(_fact_row(fact) for fact in facts)
    question_items = "\n".join(
        f"    <li>{html.escape(question)}</li>" for question in questions
    )
    verdict = (
        "<p class=\"verdict ok\">七项契约均已具备完整权威 typed 来源 —— "
        "可进入下一轮模型接口草案。</p>"
        if complete
        else "<p class=\"verdict pending\"><strong>结论：待确认。</strong> "
        "并非全部七项契约都具备完整权威 typed 来源，本轮停止于事实矩阵，"
        "不提出模型接口草案、不生成 tester 文本 / Contribution / "
        "SectionFragment、不注册、不编译。</p>"
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>STANDARD_TRIM / {html.escape(snapshot.item)} {html.escape(snapshot.cp)} 事实矩阵（待确认）</title>
<style>
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.75rem 0; }}
  th, td {{ border: 1px solid #bbb; padding: 0.4rem 0.6rem; font-size: 0.85rem;
           vertical-align: top; text-align: left; }}
  th {{ background: #f0f0f0; }}
  .CONFIRMED {{ color: #1a7f37; font-weight: 600; }}
  .MISSING {{ color: #b35900; font-weight: 600; }}
  .CONTRADICTED {{ color: #cf222e; font-weight: 600; }}
  .verdict {{ border: 1px solid; border-radius: 6px; padding: 0.75rem 1rem; }}
  .verdict.pending {{ background: #fff8e1; border-color: #e0a800; }}
  .verdict.ok {{ background: #e6ffec; border-color: #1a7f37; }}
  .meta {{ color: #555; font-size: 0.85rem; }}
  code {{ background: #f6f8fa; padding: 0 0.25rem; }}
</style>
</head>
<body>
<h1>STANDARD_TRIM / {html.escape(snapshot.item)} {html.escape(snapshot.cp)} 的 domain-fact 取证包</h1>
<p class="meta">
  目标：<code>{html.escape(snapshot.cp)} / {html.escape(snapshot.item)} / {html.escape(snapshot.platform)} / {html.escape(snapshot.variant)} / {html.escape(snapshot.program_name)}</code><br>
  作用域：{html.escape(snapshot.cp)}（CP）/ chroma+s100（平台）/ {html.escape(snapshot.variant)}（variant）<br>
  输入：仅消费 WorkbookModel / ProductCompilation 中已显式编译的 typed facts
  （TrimSpec、Canonical Schedule、TestDefinition、TargetKey、TargetPlatformProfile、
  EnvironmentGroup、LifecycleGroup、HelpersGroup、ResourcesGroup、RuntimeSymbol）。<br>
  未使用：Excel 原始对象、G、旧 writer、Golden / 旧输出、文件名 / item 名推导。<br>
  Workbook identity：<code>{html.escape(snapshot.workbook_identity)}</code><br>
  Compilation identity：<code>{html.escape(snapshot.compilation_identity)}</code>
</p>
{verdict}
<h2>逐项事实矩阵</h2>
<table>
<thead>
<tr><th>事实名</th><th>作用域</th><th>当前 typed producer</th><th>权威来源</th>
<th>状态</th><th>已确认值 / 缺失原因</th><th>需要裁决的问题</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
<h2>契约汇总</h2>
<table>
<thead><tr><th>契约</th><th>CONFIRMED</th><th>MISSING</th><th>CONTRADICTED</th></tr></thead>
<tbody>
{contract_summary}
</tbody>
</table>
<h2>待蛤蟆羊先生裁决的问题（{len(questions)} 项）</h2>
<ol>
{question_items}
</ol>
<p class="meta">本报告由 program_gen/forensics/standard_trim_matrix.py（纯函数，无 G / legacy writer /
Golden / filesystem 扫描依赖）生成。</p>
</body>
</html>
"""


def _fact_row(fact: DomainFact) -> str:
    status = fact.status.value
    return (
        f"<tr><td>{html.escape(fact.fact_name)}</td>"
        f"<td>{html.escape(fact.scope)}</td>"
        f"<td>{html.escape(fact.typed_producer)}</td>"
        f"<td>{html.escape(fact.authority)}</td>"
        f"<td class=\"{status}\">{status}</td>"
        f"<td>{html.escape(fact.value)}</td>"
        f"<td>{html.escape(fact.adjudication)}</td></tr>"
    )


def _contract_summary(facts: Sequence[DomainFact]) -> str:
    counts: dict[str, dict[FactStatus, int]] = {}
    for fact in facts:
        counts.setdefault(fact.contract, {}).setdefault(fact.status, 0)
        counts[fact.contract][fact.status] += 1
    rows = []
    for contract in CONTRACTS:
        statuses = counts.get(contract, {})
        rows.append(
            f"<tr><td>{html.escape(contract)}</td>"
            f"<td class=\"CONFIRMED\">{statuses.get(FactStatus.CONFIRMED, 0)}</td>"
            f"<td class=\"MISSING\">{statuses.get(FactStatus.MISSING, 0)}</td>"
            f"<td class=\"CONTRADICTED\">{statuses.get(FactStatus.CONTRADICTED, 0)}</td></tr>"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Small pure helpers.
# ---------------------------------------------------------------------------


def _platform_profile_facts(platform: str):
    """Return TargetPlatformProfile facts (single-sourced from shadow profile)."""
    from program_gen.shadow.profile import PROFILES  # noqa: PLC0415

    return PROFILES[str(platform).strip().casefold()]


def _wait_text(operation, attribute: str = "wait") -> object:
    if operation is None:
        return None
    value = getattr(operation, attribute, None)
    if value is None:
        return None
    amount = getattr(value, "amount", None)
    unit = getattr(value, "unit", None)
    if amount is None or unit is None:
        return str(value)
    return f"{amount}{unit}"


def _wait_reason(value: object, label: str) -> str:
    if value is None:
        return f"缺失原因：母本 Recipe 未填写 {label}，typed 层为 None（本包不注入默认值）"
    return f"已确认值：{value}"


def _entry_text(entry) -> str:
    return (
        f"{entry.identity} | render={entry.render_name} | variant={entry.variant} "
        f"| enabled={entry.enabled}"
    )


def _display(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"STANDARD_TRIM fact matrix: {message}")


__all__ = [
    "CONTRACTS",
    "DomainFact",
    "FactStatus",
    "StandardTrimFactSnapshot",
    "build_fact_matrix",
    "extract_snapshot",
    "pending_adjudication_questions",
    "render_html",
    "typed_contracts_complete",
]
