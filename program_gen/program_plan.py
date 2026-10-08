"""Deterministic product/CP semantic plans.

The plan is deliberately tester-neutral.  It gives the rest of the pipeline a
stable identity for definitions and scheduling before platform names, files,
or syntax exist.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from program_gen.flow_kinds import FlowOperation, compile_flow_rows


SEMANTIC_GROUPS = (
    "IDENTITY",
    "ENVIRONMENT",
    "RUNTIME_STATE",
    "LIFECYCLE",
    "HELPERS",
    "TESTS",
    "SCHEDULE",
    "RESOURCES",
)


class ProgramPlanError(ValueError):
    """The semantic plan has an invalid dependency or state transition."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class SymbolCardinality(str, Enum):
    PROGRAM = "PROGRAM"
    CP = "CP"
    SITE = "SITE"


class SymbolLifetime(str, Enum):
    TEST = "TEST"
    CP = "CP"
    PROGRAM = "PROGRAM"


@dataclass(frozen=True)
class SymbolRef:
    cp: str
    namespace: str
    semantic_key: str


@dataclass(frozen=True)
class RuntimeSymbol:
    ref: SymbolRef
    producer_order: int
    value_type: str = "INT"
    bit_width: int | None = None
    cardinality: SymbolCardinality = SymbolCardinality.SITE
    lifetime: SymbolLifetime = SymbolLifetime.CP
    declaration_required: bool = True

    @property
    def cp(self) -> str:
        return self.ref.cp

    @property
    def name(self) -> str:
        return self.ref.semantic_key


@dataclass(frozen=True)
class RuntimeSymbolUse:
    consumer_cp: str
    ref: SymbolRef
    consumer_order: int

    @property
    def cp(self) -> str:
        return self.consumer_cp

    @property
    def name(self) -> str:
        return self.ref.semantic_key


@dataclass(frozen=True)
class AllActiveSites:
    kind: str = "ALL_ACTIVE_SITES"


@dataclass(frozen=True)
class GatedSites:
    gate: str
    kind: str = "GATED_SITES"


@dataclass(frozen=True)
class FailedSitesOf:
    action: str
    kind: str = "FAILED_SITES_OF"


SiteScope = AllActiveSites | GatedSites | FailedSitesOf


@dataclass(frozen=True)
class PageVersionRef:
    cp: str
    page: str
    generation: int


@dataclass(frozen=True)
class PageTransition:
    action: str
    before: PageVersionRef | None
    after: PageVersionRef
    scope: SiteScope
    producer: str


@dataclass(frozen=True)
class PageStateTimeline:
    transitions: tuple[PageTransition, ...]


@dataclass(frozen=True)
class PatternVersionRef:
    logical_name: str
    generation: int


@dataclass(frozen=True)
class PreparedPatternVersion:
    ref: PatternVersionRef
    page_input: PageVersionRef
    producer: str


@dataclass(frozen=True)
class SemanticDependency:
    identity: str
    depends_on: tuple[str, ...] = ()


def validate_semantic_dependencies(
    nodes: tuple[SemanticDependency, ...],
) -> tuple[str, ...]:
    """Return a stable topological order or reject missing/cyclic edges."""
    by_id = {_key(node.identity): node for node in nodes}
    if len(by_id) != len(nodes):
        raise ProgramPlanError("PP.DEPENDENCY.CONFLICT", "duplicate node identity")
    for node in nodes:
        missing = [item for item in node.depends_on if _key(item) not in by_id]
        if missing:
            raise ProgramPlanError(
                "PP.DEPENDENCY.MISSING",
                f"{node.identity} depends on unknown {missing[0]}",
            )

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identity: str) -> None:
        key = _key(identity)
        if key in visiting:
            raise ProgramPlanError(
                "PP.DEPENDENCY.CYCLE", f"cycle includes {identity}"
            )
        if key in visited:
            return
        visiting.add(key)
        node = by_id[key]
        for dependency in node.depends_on:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
        ordered.append(node.identity)

    for node in nodes:
        visit(node.identity)
    return tuple(ordered)


def validate_runtime_state(
    *,
    definitions: tuple[RuntimeSymbol, ...],
    uses: tuple[RuntimeSymbolUse, ...],
) -> Mapping[str, RuntimeSymbol]:
    """Close CP runtime symbols and reject use-before-definition."""
    symbols: dict[tuple[str, str], RuntimeSymbol] = {}
    for definition in definitions:
        key = (
            _key(definition.ref.cp),
            _key(definition.ref.namespace),
            _key(definition.ref.semantic_key),
        )
        previous = symbols.get(key)
        if previous is not None and previous != definition:
            raise ProgramPlanError(
                "PP.SYMBOL.CONFLICT",
                f"{definition.cp}.{definition.name} has conflicting definitions",
            )
        symbols[key] = definition
    for use in uses:
        source_cp = use.ref.cp
        if _key(source_cp) != _key(use.consumer_cp):
            raise ProgramPlanError(
                "PP.SYMBOL.CROSS_CP_RUNTIME",
                f"{use.consumer_cp}.{use.name} cannot consume runtime state from {source_cp}",
            )
        key = (
            _key(source_cp),
            _key(use.ref.namespace),
            _key(use.ref.semantic_key),
        )
        definition = symbols.get(key)
        if definition is None:
            raise ProgramPlanError(
                "PP.SYMBOL.MISSING", f"{use.cp}.{use.name} is not defined"
            )
        if definition.producer_order >= use.consumer_order:
            raise ProgramPlanError(
                "PP.SYMBOL.FORWARD_REFERENCE",
                f"{use.cp}.{use.name} is consumed before it is produced",
            )
    return MappingProxyType({
        f"{cp.upper()}.{namespace.upper()}.{name.upper()}": item
        for (cp, namespace, name), item in symbols.items()
    })


@dataclass(frozen=True)
class TestDefinition:
    identity: str
    cp: str
    item: str
    flow_type: str
    typed_kind: str
    family: str
    mode: str
    source_rows: tuple[int, ...]
    datalog_points: tuple[str, ...]
    effective_recipe: tuple[str, ...]


@dataclass(frozen=True)
class ScheduleEntry:
    identity: str
    definition_id: str
    order: int
    enabled: bool
    force_pass: bool
    hardware_bin: str
    software_bin: str
    placement: str = "BOOKED"


@dataclass(frozen=True)
class IdentityGroup:
    cp: str
    definition_ids: tuple[str, ...]


@dataclass(frozen=True)
class EnvironmentGroup:
    configured_catalogs: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeStateGroup:
    symbols: tuple[RuntimeSymbol, ...]
    page_timeline: PageStateTimeline
    prepared_patterns: tuple[PreparedPatternVersion, ...]
    site_scope: SiteScope
    dac_write_plans: object
    result_export_plans: object
    build_uid_rows: Mapping[int, object]
    memory_wakeup_plan: object | None
    persistence_rows: Mapping[int, object]
    result_import_plans: tuple = ()
    declarations: object | None = None
    flash_window_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    trimdata_read_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    trimdata_write_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True)
class LifecycleGroup:
    contributions: tuple[str, ...]


@dataclass(frozen=True)
class HelpersGroup:
    identities: tuple[str, ...]


@dataclass(frozen=True)
class TestsGroup:
    definitions: tuple[TestDefinition, ...]


@dataclass(frozen=True)
class ScheduleGroup:
    schedule: tuple[ScheduleEntry, ...]
    canonical: object | None = None


@dataclass(frozen=True)
class ResourceClosureState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class ResourcesGroup:
    identities: tuple[str, ...]
    state: ResourceClosureState

    @property
    def closure_complete(self) -> bool:
        return self.state is ResourceClosureState.CLOSED


@dataclass(frozen=True)
class CpProgramPlan:
    identity_group: IdentityGroup
    environment: EnvironmentGroup
    runtime_state: RuntimeStateGroup
    lifecycle: LifecycleGroup
    helpers: HelpersGroup
    tests: TestsGroup
    scheduling: ScheduleGroup
    resources: ResourcesGroup
    identity: str

    @property
    def cp(self) -> str:
        return self.identity_group.cp

    @property
    def semantic_groups(self) -> tuple[str, ...]:
        return SEMANTIC_GROUPS

    @property
    def definitions(self) -> tuple[TestDefinition, ...]:
        return self.tests.definitions

    @property
    def schedule(self) -> tuple[ScheduleEntry, ...]:
        return self.scheduling.schedule

    @property
    def canonical_schedule(self):
        return self.scheduling.canonical

    @property
    def dac_write_plans(self):
        return self.runtime_state.dac_write_plans

    @property
    def result_export_plans(self):
        return self.runtime_state.result_export_plans

    @property
    def build_uid_rows(self):
        return self.runtime_state.build_uid_rows

    @property
    def memory_wakeup_plan(self):
        return self.runtime_state.memory_wakeup_plan

    @property
    def persistence_rows(self):
        return self.runtime_state.persistence_rows

    @property
    def result_import_plans(self):
        return self.runtime_state.result_import_plans

    @property
    def flash_window_plans(self):
        return self.runtime_state.flash_window_plans

    @property
    def trimdata_read_plans(self):
        return self.runtime_state.trimdata_read_plans

    @property
    def trimdata_write_plans(self):
        return self.runtime_state.trimdata_write_plans


@dataclass(frozen=True)
class ProductCatalogs:
    flow_operations: tuple[FlowOperation, ...]
    recipe_rows: Mapping[int, object]
    addr_map: object
    trim_specs: Mapping[int, object]
    dedicated_trim_plans: Mapping[int, object]
    os_plans: Mapping[str, Mapping[int, object]]
    pdr_verify_plans: Mapping[str, Mapping[int, object]]
    standard_verify_plans: Mapping[int, object]
    adc_test_plans: Mapping[int, object]
    firmware_test_plans: Mapping[int, object]
    pvd_test_plans: Mapping[int, object]
    dc_parametric_plans: Mapping[int, object]
    vih_vil_plans: Mapping[int, object]
    freq_test_plans: Mapping[int, object]
    opa_test_plans: Mapping[int, object]
    dac_test_plans: Mapping[int, object]
    dac_adjust_plans: Mapping[int, object] = field(
        metadata={"canonical_omit_if_empty": True}
    )
    trim_data: object
    id_plans: object
    persistence: object
    default_commit_bindings: Mapping[int, tuple]
    shmoo_plans: Mapping[int, object]
    commit_shmoo_plans: Mapping[int, object]
    system_read_facts: Mapping[str, object]
    result_bindings: object
    result_imports: object
    scan_test_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({}),
        metadata={"canonical_omit_if_empty": True},
    )
    fbist_pattern_plan: object | None = None
    flash_compare_compilation: object | None = None
    flash_label_plan: object | None = None
    flash_window_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({}),
        metadata={"canonical_omit_if_empty": True},
    )
    trimdata_read_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({}),
        metadata={"canonical_omit_if_empty": True},
    )
    trimdata_write_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({}),
        metadata={"canonical_omit_if_empty": True},
    )
    uid_plans: Mapping[int, object] = field(default_factory=lambda: MappingProxyType({}))
    id_module_plans: Mapping[int, object] = field(default_factory=lambda: MappingProxyType({}))
    main_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({}),
        metadata={"canonical_omit_if_empty": True},
    )
    vt_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({}),
        metadata={"canonical_omit_if_empty": True},
    )
    margin_plans: Mapping[int, object] = field(
        default_factory=lambda: MappingProxyType({}),
        metadata={"canonical_omit_if_empty": True},
    )


@dataclass(frozen=True)
class ProductPlan:
    workbook_identity: str
    workbook_sha256: str
    catalogs: ProductCatalogs
    cp_plans: Mapping[str, CpProgramPlan]
    identity: str

    def canonical_json(self) -> str:
        return json.dumps(
            _canonical_product(self, include_identity=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def compile_program_plan(
    flow: pd.DataFrame,
    *,
    workbook_identity: str,
    workbook_sha256: str,
    recipe_rows: Mapping[int, object],
    row_flags: Mapping[int, str | None],
    trim_specs: Mapping[int, object] = MappingProxyType({}),
    cp_compilations: Mapping[str, object] = MappingProxyType({}),
    persistence_plans: object | None = None,
    catalogs: ProductCatalogs | None = None,
    semantic_identity: str = "",
    result_imports=None,
    flow_operations: tuple[FlowOperation, ...] | None = None,
) -> ProductPlan:
    """Compile FLOW order into stable Definition and Schedule identities."""
    flow_operations = flow_operations or compile_flow_rows(
        flow,
        workbook_identity=workbook_identity,
        source_sha256=workbook_sha256,
    )
    operations_by_row = {operation.row: operation for operation in flow_operations}
    groups: list[tuple[str, list[dict]]] = []
    for row_index, record in flow.iterrows():
        item = _text(record.get("item"))
        cp = _text(record.get("CP NO")).upper()
        flow_type = _text(record.get("type"))
        if not item or not cp or not flow_type:
            continue
        recipe_row = recipe_rows.get(int(row_index))
        is_shmoo = any(
            call.named_parameter("SHMOO") == "STEP"
            for call in getattr(recipe_row, "operations", ())
        )
        key = "\x1f".join((
            cp,
            item.casefold(),
            flow_type.casefold(),
            "SHMOO" if is_shmoo else "BASE",
        ))
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append({"index": int(row_index), "record": record})

    by_cp: dict[str, list[tuple[int, TestDefinition, ScheduleEntry]]] = {}
    row_orders: dict[int, int] = {}
    for definition_order, (_key_value, rows) in enumerate(groups):
        first = rows[0]["record"]
        cp = _text(first.get("CP NO")).upper()
        item = _text(first.get("item"))
        flow_type = _text(first.get("type"))
        indices = tuple(row["index"] for row in rows)
        row_orders.update((index, definition_order) for index in indices)
        source_rows = tuple(index + 2 for index in indices)
        definition_id = _stable_id("DEF", cp, flow_type, item, source_rows)
        operation = operations_by_row[indices[0]]
        recipe = tuple(
            operation.name
            for index in indices
            for operation in getattr(recipe_rows.get(index), "operations", ())
        )
        firmware_plan = getattr(catalogs, "firmware_test_plans", {}).get(indices[0])
        pvd_plan = getattr(catalogs, "pvd_test_plans", {}).get(indices[0])
        adc_plan = getattr(catalogs, "adc_test_plans", {}).get(indices[0])
        dc_plan = getattr(catalogs, "dc_parametric_plans", {}).get(indices[0])
        vih_vil_plan = getattr(catalogs, "vih_vil_plans", {}).get(indices[0])
        freq_test_plan = getattr(catalogs, "freq_test_plans", {}).get(indices[0])
        opa_test_plan = getattr(catalogs, "opa_test_plans", {}).get(indices[0])
        dac_test_plan = getattr(catalogs, "dac_test_plans", {}).get(indices[0])
        scan_test_plan = getattr(catalogs, "scan_test_plans", {}).get(indices[0])
        if adc_plan is not None:
            recipe = adc_plan.effective_recipe
        if firmware_plan is not None:
            recipe = tuple(
                module
                for phase in firmware_plan.phases
                for module in phase.effective_recipe
            )
        if pvd_plan is not None:
            recipe = pvd_plan.effective_recipe
        if dc_plan is not None:
            recipe = dc_plan.effective_recipe
        if vih_vil_plan is not None:
            recipe = vih_vil_plan.effective_recipe
        if freq_test_plan is not None:
            recipe = freq_test_plan.effective_recipe
        if opa_test_plan is not None:
            recipe = opa_test_plan.effective_recipe
        if dac_test_plan is not None:
            recipe = dac_test_plan.effective_recipe
        if scan_test_plan is not None:
            recipe = scan_test_plan.effective_recipe
        if not recipe and indices[0] in getattr(catalogs, "dedicated_trim_plans", {}):
            recipe = tuple(catalogs.dedicated_trim_plans[indices[0]].effective_recipe)
        if not recipe and indices[0] in getattr(catalogs, "os_plans", {}).get("chroma", {}):
            recipe = (catalogs.os_plans["chroma"][indices[0]].effective_recipe,)
        if not recipe and indices[0] in getattr(catalogs, "pdr_verify_plans", {}).get("chroma", {}):
            recipe = ("PDR_VERIFY",)
        if not recipe and indices[0] in getattr(catalogs, "standard_verify_plans", {}):
            recipe = catalogs.standard_verify_plans[indices[0]].effective_recipe
        recipe = recipe or ("LEGACY",)
        definition = TestDefinition(
            identity=definition_id,
            cp=cp,
            item=item,
            flow_type=flow_type,
            typed_kind=(
                adc_plan.typed_kind
                if adc_plan is not None
                else firmware_plan.typed_kind
                if firmware_plan is not None
                else pvd_plan.typed_kind
                if pvd_plan is not None
                else dc_plan.typed_kind
                if dc_plan is not None
                else vih_vil_plan.typed_kind
                if vih_vil_plan is not None
                else freq_test_plan.typed_kind
                if freq_test_plan is not None
                else opa_test_plan.typed_kind
                if opa_test_plan is not None
                else dac_test_plan.typed_kind
                if dac_test_plan is not None
                else scan_test_plan.typed_kind
                if scan_test_plan is not None
                else operation.typed_kind
            ),
            family=operation.family,
            mode=operation.mode,
            source_rows=source_rows,
            datalog_points=tuple(_text(row["record"].get("sub")) for row in rows),
            effective_recipe=recipe,
        )
        flags = tuple(row_flags.get(index) for index in indices)
        schedule = ScheduleEntry(
            identity=_stable_id("SCHEDULE", definition_id),
            definition_id=definition_id,
            order=definition_order,
            enabled="comment_out" not in flags,
            force_pass="force_pass" in flags,
            hardware_bin=_text(first.get("Hbin")),
            software_bin=_text(first.get("Sbin")),
        )
        by_cp.setdefault(cp, []).append((definition_order, definition, schedule))

    cp_plans: dict[str, CpProgramPlan] = {}
    for cp, entries in by_cp.items():
        flow_definitions = tuple(entry[1] for entry in entries)
        flow_schedule = tuple(entry[2] for entry in entries)
        otp_read = TestDefinition(
            identity=_stable_id("DEF", cp, "SYSTEM", "OTP_READ"),
            cp=cp,
            item="OTP_READ",
            flow_type="system_auxiliary",
            typed_kind="SYSTEM_OTP_READ",
            family="SYSTEM_AUXILIARY",
            mode="SYSTEM",
            source_rows=(),
            datalog_points=(),
            effective_recipe=("SYSTEM_OTP_READ",),
        )
        nm_data_read = TestDefinition(
            identity=_stable_id("DEF", cp, "SYSTEM", "NM_Data_Read"),
            cp=cp,
            item="NM_Data_Read",
            flow_type="system_auxiliary",
            typed_kind="SYSTEM_NM_DATA_READ",
            family="SYSTEM_AUXILIARY",
            mode="SYSTEM",
            source_rows=(),
            datalog_points=(),
            effective_recipe=("SYSTEM_NM_DATA_READ",),
        )
        definitions = flow_definitions + (otp_read, nm_data_read)
        schedule = flow_schedule + tuple(
            ScheduleEntry(
                identity=_stable_id("SCHEDULE", definition.identity),
                definition_id=definition.identity,
                order=len(flow_schedule) + offset,
                enabled=True,
                force_pass=False,
                hardware_bin="",
                software_bin="",
                placement="SYSTEM_UNBOOKED",
            )
            for offset, definition in enumerate((otp_read, nm_data_read))
        )
        identity_group = IdentityGroup(cp, tuple(item.identity for item in definitions))
        environment = EnvironmentGroup(("PIN", "LEVEL", "TIMING", "RELAY", "BIN"))
        cp_compilation = cp_compilations.get(cp)
        symbols = _runtime_symbols(
            cp, trim_specs, cp_compilation, row_orders
        )
        page_timeline, prepared_patterns = _persistence_versions(
            cp, persistence_plans
        )
        validate_runtime_state(definitions=symbols, uses=())
        runtime_state = RuntimeStateGroup(
            symbols,
            page_timeline,
            prepared_patterns,
            AllActiveSites(),
            getattr(cp_compilation, "dac_write_plans", None),
            getattr(cp_compilation, "result_export_plans", None),
            MappingProxyType(dict(getattr(cp_compilation, "build_uid_rows", {}))),
            getattr(cp_compilation, "memory_wakeup_plan", None),
            MappingProxyType({
                row: plan
                for row, plan in getattr(persistence_plans, "rows", {}).items()
                if _key(getattr(plan, "cp", "")) == _key(cp)
            }),
            tuple(getattr(result_imports, "for_cp", lambda _cp: ())(cp)),
            None,
            MappingProxyType(dict(
                getattr(cp_compilation, "flash_window_plans", {})
            )),
            MappingProxyType(dict(
                getattr(cp_compilation, "trimdata_read_plans", {})
            )),
            MappingProxyType(dict(
                getattr(cp_compilation, "trimdata_write_plans", {})
            )),
        )
        if catalogs is not None:
            from program_gen.core.declaration_plan import (
                compile_runtime_declaration_plan,
            )
            runtime_state = replace(
                runtime_state,
                declarations=compile_runtime_declaration_plan(
                    cp, runtime_state, catalogs
                ),
            )
        lifecycle = LifecycleGroup(())
        helpers = HelpersGroup(tuple(dict.fromkeys(tuple(
            operation
            for definition in definitions
            for operation in definition.effective_recipe
            if operation not in ("LEGACY", "ENTER", "JUDGE", "TRIM")
            and not operation.startswith("SYSTEM_")
        ) + tuple(
            plan.helper_name
            for plan in getattr(
                getattr(cp_compilation, "dac_write_plans", None),
                "helper_plans", (),
            )
        ))))
        tests = TestsGroup(definitions)
        scheduling = ScheduleGroup(schedule)
        if catalogs is not None:
            from program_gen.core.schedule_plan import compile_schedule_groups
            scheduling = replace(
                scheduling,
                canonical=compile_schedule_groups(
                    cp, definitions, schedule, flow, trim_specs
                ),
            )
        resources = ResourcesGroup(
            _resource_identities(cp, trim_specs, cp_compilation),
            ResourceClosureState.DISCOVERED,
        )
        payload = {
            "identity_group": asdict(identity_group),
            "environment": asdict(environment),
            "runtime_state": _canonical_runtime_state(runtime_state),
            "lifecycle": asdict(lifecycle),
            "helpers": asdict(helpers),
            "tests": asdict(tests),
            "scheduling": _canonical_scheduling(scheduling),
            "resources": asdict(resources),
        }
        cp_plans[cp] = CpProgramPlan(
            identity_group=identity_group,
            environment=environment,
            runtime_state=runtime_state,
            lifecycle=lifecycle,
            helpers=helpers,
            tests=tests,
            scheduling=scheduling,
            resources=resources,
            identity=_hash(payload),
        )

    cp_plans_proxy = MappingProxyType(dict(cp_plans))
    product_payload = {
        "workbook_identity": workbook_identity,
        "workbook_sha256": workbook_sha256,
        "semantic_identity": semantic_identity,
        "cp_plans": {
            cp: _canonical_cp(plan) for cp, plan in cp_plans_proxy.items()
        },
    }
    return ProductPlan(
        workbook_identity=workbook_identity,
        workbook_sha256=workbook_sha256,
        catalogs=catalogs,
        cp_plans=cp_plans_proxy,
        identity=_hash(product_payload),
    )


def _text(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value).strip()


def _runtime_symbols(cp, trim_specs, cp_compilation, row_orders):
    selected: dict[str, RuntimeSymbol] = {}
    for row, spec in sorted(trim_specs.items()):
        if _key(getattr(spec, "cp", "")) != _key(cp):
            continue
        symbol = RuntimeSymbol(
            SymbolRef(cp, "RESULT", getattr(spec, "dac_final_symbol")),
            row_orders.get(int(row), int(row)),
            value_type="INT",
            bit_width=getattr(getattr(spec, "dac", None), "field_width", None),
        )
        selected.setdefault(_key(symbol.name), symbol)
    if cp_compilation is not None:
        for plan in getattr(
            getattr(cp_compilation, "result_export_plans", None), "plans", ()
        ):
            symbol = RuntimeSymbol(
                SymbolRef(cp, "RESULT", plan.symbol),
                row_orders.get(plan.flow_row_index, plan.flow_row_index),
                value_type=plan.c_type.upper(),
            )
            selected.setdefault(_key(symbol.name), symbol)
        for plan in getattr(
            getattr(cp_compilation, "dac_write_plans", None), "plans", ()
        ):
            if not plan.needs_global_variable:
                continue
            symbol = RuntimeSymbol(
                SymbolRef(cp, "DAC", plan.dac_symbol),
                row_orders.get(plan.flow_row_index, plan.flow_row_index),
                value_type="INT",
                bit_width=plan.field_width,
            )
            selected.setdefault(_key(symbol.name), symbol)
        for plan in getattr(cp_compilation, "build_uid_rows", {}).values():
            for name in plan.global_symbols:
                value_type, bit_width, cardinality, declaration_required = {
                    "WAFERID": ("CHAR", 32, SymbolCardinality.CP, True),
                    "LOT_ID": ("CHAR", 32, SymbolCardinality.CP, True),
                    "WAFER_SLOT": ("INT", None, SymbolCardinality.CP, True),
                    "X_CO": ("INT", None, SymbolCardinality.SITE, False),
                    "Y_CO": ("INT", None, SymbolCardinality.SITE, False),
                }[name]
                selected.setdefault(
                    _key(name), RuntimeSymbol(
                        SymbolRef(cp, "BUILD_UID", name),
                        -1,
                        value_type=value_type,
                        bit_width=bit_width,
                        cardinality=cardinality,
                        declaration_required=declaration_required,
                    )
                )
    return tuple(selected.values())


def _persistence_versions(cp, persistence_plans):
    current_pages: dict[str, PageVersionRef] = {}
    pattern_generations: dict[str, int] = {}
    transitions = []
    prepared = []
    for _row, row_plan in sorted(
        getattr(persistence_plans, "rows", {}).items()
    ):
        if _key(getattr(row_plan, "cp", "")) != _key(cp):
            continue
        for operation in row_plan.operations:
            pages = operation.effective_pages or operation.requested_pages
            if operation.module in ("BUILDMAP", "READOTPMAP", "COMMIT", "BUILDUID"):
                for page in pages:
                    before = current_pages.get(page)
                    after = PageVersionRef(
                        cp, page, 1 if before is None else before.generation + 1
                    )
                    transitions.append(PageTransition(
                        operation.module,
                        before,
                        after,
                        AllActiveSites(),
                        f"FLOW:{operation.excel_row}:{operation.module}",
                    ))
                    current_pages[page] = after
            if operation.module in ("LOADMAP", "COMMIT"):
                for page in pages:
                    page_input = current_pages.get(page)
                    if page_input is None:
                        raise ProgramPlanError(
                            "PP.PAGE.VERSION_MISSING",
                            f"{cp}.{page} has no complete PageImageVersion",
                        )
                    generation = pattern_generations.get(page, 0) + 1
                    pattern_generations[page] = generation
                    prepared.append(PreparedPatternVersion(
                        PatternVersionRef(page, generation),
                        page_input,
                        f"FLOW:{operation.excel_row}:{operation.module}",
                    ))
    return PageStateTimeline(tuple(transitions)), tuple(prepared)


def _resource_identities(cp, trim_specs, cp_compilation):
    resources = []
    for _row, spec in sorted(trim_specs.items()):
        if _key(getattr(spec, "cp", "")) != _key(cp):
            continue
        resources.append(spec.dac.pattern_name)
        resources.extend(
            operation.reference
            for operation in spec.operations
            if operation.reference
        )
        resources.extend(
            operation.reference
            for operation in spec.search.per_point_actions
            if operation.reference
        )
        # Single resource ownership: the canonical Recipe declares the FBIST
        # protocol enter/exit patterns on TrimSpec.protocol, so the CP
        # resource closure must own them too.  STANDARD_TRIM contributions
        # reference only closure-owned identities.
        protocol = getattr(spec, "protocol", None)
        if protocol is not None:
            for name in (protocol.enter_pattern, protocol.exit_pattern):
                if name:
                    resources.append(name)
    if cp_compilation is not None:
        resources.extend(
            plan.pattern_name
            for plan in getattr(
                getattr(cp_compilation, "dac_write_plans", None), "plans", ()
            )
        )
    return tuple(dict.fromkeys(resources))


def _key(value) -> str:
    return str(value).strip().casefold()


def _stable_id(*parts) -> str:
    return ":".join(str(part) for part in parts)


def _hash(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _canonical_cp(plan: CpProgramPlan) -> dict:
    return {
        "identity_group": asdict(plan.identity_group),
        "environment": asdict(plan.environment),
        "runtime_state": _canonical_runtime_state(plan.runtime_state),
        "lifecycle": asdict(plan.lifecycle),
        "helpers": asdict(plan.helpers),
        "tests": asdict(plan.tests),
        "scheduling": _canonical_scheduling(plan.scheduling),
        "resources": asdict(plan.resources),
        "identity": plan.identity,
    }


def _canonical_product(plan: ProductPlan, *, include_identity: bool) -> dict:
    result = {
        "workbook_identity": plan.workbook_identity,
        "workbook_sha256": plan.workbook_sha256,
        "cp_plans": {cp: _canonical_cp(item) for cp, item in plan.cp_plans.items()},
    }
    if include_identity:
        result["identity"] = plan.identity
    return result


def _canonical_runtime_state(state: RuntimeStateGroup) -> dict:
    return {
        "symbols": [asdict(item) for item in state.symbols],
        "page_timeline": asdict(state.page_timeline),
        "prepared_patterns": [asdict(item) for item in state.prepared_patterns],
        "site_scope": asdict(state.site_scope),
        "declarations": (
            None
            if state.declarations is None
            else {"identity": state.declarations.identity}
        ),
    }


def _canonical_scheduling(group: ScheduleGroup) -> dict:
    return {
        "schedule": [asdict(item) for item in group.schedule],
        "canonical": None if group.canonical is None else {
            "cp": group.canonical.cp,
            "definitions": [asdict(item) for item in group.canonical.definitions],
            "entries": [
                {
                    **asdict(item),
                    "bin_binding": {
                        **asdict(item.bin_binding),
                        "kind": item.bin_binding.kind.value,
                    },
                }
                for item in group.canonical.entries
            ],
        },
    }
