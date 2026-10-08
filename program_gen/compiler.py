"""The single public workbook-to-product compilation boundary.

ProductCompiler owns the ordering and interaction of the existing typed core
compilers.  It never renders tester text and never reads or writes files.  The
two platform adapters consume ProductCompilation instead of reconstructing
Recipe, ADDR_MAP, Trim, Persistence, Shmoo, and UID plans independently.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping

import pandas as pd

from flow_recipe import (
    DacWritePlanSet,
    ExecutableFlowRow,
    ResultExportPlanSet,
    FlowCompileError,
    compile_dac_write_plan_set,
    compile_recipe_rows,
    compile_result_export_plan_set,
    default_recipe,
    validate_explicit_recipe_patterns,
)
from pattern_bundle import PatternCompileError
from program_gen.core.addr_map import (
    AddrMapCatalog,
    AddrMapCompileError,
    compile_addr_map_catalog,
)
from program_gen.core.commit_shmoo import (
    CommitShmooPlan,
    CommitShmooPlanError,
    compile_commit_shmoo_plans,
)
from program_gen.core.commit_module import (
    CommitModuleCompileError,
    compile_commit_module_plans,
)
from program_gen.core.default_commit import compile_default_commit_bindings
from program_gen.core.dedicated_trim import (
    DedicatedTrimCompileError,
    DedicatedTrimPlan,
    compile_dedicated_trim_plans,
)
from program_gen.core.declaration_plan import DeclarationCompileError
from program_gen.core.dac_adjust import (
    DacAdjustActionPlanError,
    compile_dac_adjust_action_plans,
)
from program_gen.core.dac_write import (
    DacWriteCompileError,
    compile_dac_write_module_plans,
)
from program_gen.core.fbist_pattern_plan import (
    FbistPatternCompileError,
    FbistPatternGenerationPlan,
    compile_fbist_pattern_plan,
)
from program_gen.core.flash_window import (
    FlashWindowCompileError,
    FlashWindowPlan,
    compile_flash_window_plans,
)
from program_gen.core.project_mappings import (
    ProjectMappingsError,
    validate_storage_mapping_records,
    validate_storage_flow_occupancy,
    validate_storage_explicit_commits,
    validate_storage_role_occupancy,
    verify_storage_sources,
)
from program_gen.core.firmware_test import (
    FirmwareTestCompileError,
    compile_firmware_test_plans,
    validate_firmware_recipe_contract,
)
from program_gen.core.adc_test import (
    AdcTestCompileError,
    compile_adc_test_plans,
)
from program_gen.core.pvd_test import (
    PvdTestCompileError,
    compile_pvd_test_plans,
)
from program_gen.core.dc_parametric import (
    DcParametricCompileError,
    compile_dc_parametric_plans,
)
from program_gen.core.vih_vil import (
    VihVilCompileError,
    compile_vih_vil_plans,
)
from program_gen.core.freq_test import (
    FreqTestCompileError,
    compile_freq_test_plans,
)
from program_gen.core.opa_test import OpaTestCompileError, compile_opa_test_plans
from program_gen.core.dac_test import DacTestCompileError, compile_dac_test_plans
from program_gen.core.scan_test import ScanTestCompileError, compile_scan_test_plans
from program_gen.core.flash_compare_product import (
    FlashCompareProductCompileError,
    RequiredFlashCompareCompilation,
    compile_required_flash_compare_plans,
)
from program_gen.core.flash_label_plan import (
    FlashLabelCompileError,
    FlashLabelGenerationPlan,
    compile_flash_label_contract,
    compile_flash_label_plan,
)
from program_gen.core.input_normalization import normalize_flow_table
from program_gen.core.memory_wakeup import (
    MemoryWakeupCompileError,
    MemoryWakeupPlan,
    compile_memory_wakeup_plan,
)
from program_gen.core.os_plan import OsPlan, OsPlanError, compile_os_plan
from program_gen.core.nm_test import NmTestCompileError, compile_main_plans
from program_gen.core.vt_test import VtTestCompileError, compile_vt_plans, validate_vt_gate_schedule
from program_gen.core.margin_test import MarginTestCompileError, compile_margin_plans, validate_margin_gate_schedule
from program_gen.core.pdr_verify import (
    PdrVerifyPlan,
    PdrVerifyPlanError,
    compile_pdr_verify_plan,
)
from program_gen.core.schedule_plan import SchedulePlanError
from program_gen.core.persistence_recipe import (
    PersistenceCompileError,
    PersistencePlanSet,
    compile_persistence_plan_set,
)
from program_gen.core.result_binding import (
    ResultBindingCompileError,
    compile_persisted_result_imports,
    compile_product_result_bindings,
)
from program_gen.core.result_use_def import ResultUseDefError, validate_export_use_def
from program_gen.core.shmoo import ShmooPlan, ShmooRecipeError, compile_shmoo_plans
from program_gen.core.system_read import (
    SystemReadCompileError,
    bind_system_read_specs,
    compile_system_read_facts,
)
from program_gen.core.standard_verify import (
    StandardVerifyPlanError,
    compile_standard_verify_plans,
)
from program_gen.core.trim_data import (
    TrimDataCompileError,
    TrimDataPlan,
    compile_trim_data_plan,
)
from program_gen.core.trimdata_read import (
    TrimdataReadCompileError,
    TrimdataReadPlan,
    compile_trimdata_read_plan,
)
from program_gen.core.trimdata_write import (
    TrimdataWriteCompileError,
    TrimdataWritePlan,
    compile_trimdata_write_plans,
    compile_write_page_scopes,
)
from program_gen.core.trim_use_def import (
    TrimDacUseDefError,
    validate_trim_dac_use_def,
)
from program_gen.core.trim_spec import TrimCompileError, TrimSpec, compile_trim_specs
from program_gen.core.uid_plan import (
    BuildUidPlan,
    BuildUidSchema,
    IdPlanError,
    IdPlanSet,
    UidPlanCompiler,
    compile_id_plan_set,
)
from program_gen.core.uid_write import compile_uid_write_plans, compile_id_test_plans
from program_gen.core.build_uid_module import compile_build_uid_module_plan
from program_gen.diagnostics import (
    Diagnostic,
    Diagnostics,
    ERROR,
    WARN,
    WorkbookProvenance,
)
from program_gen.flow_kinds import FlowKindCompileError, compile_flow_rows
from program_gen.workbook import WorkbookModel
from program_gen.program_plan import (
    ProductCatalogs,
    ProductPlan,
    ProgramPlanError,
    compile_program_plan,
)


_BUILD_UID_SCHEMA = BuildUidSchema(
    startup_cache_inputs=("LOT_ID", "WAFER_ID", "WAFER_SLOT", "X", "Y"),
    global_symbols=("WAFERID", "LOT_ID", "WAFER_SLOT", "X_CO", "Y_CO"),
    fields=(
        "LOT_ID", "X_CO", "Y_CO", "XY_CO", "DATE", "TESTING_HOUSE_ID",
        "CP_VERNO", "CRC", "PROJECT_NAME_VERSION", "WAFER_SLOT",
        "CP1_VERSION", "CP2_VERSION",
    ),
    crc_field="CRC",
    crc_input_fields=(
        "LOT_ID", "WAFER_SLOT", "XY_CO", "X_CO", "Y_CO", "DATE",
        "TESTING_HOUSE_ID", "CP_VERNO",
    ),
)

# ponytail: one SHA-scoped exception; delete it when the formal FLOW gains a consumer.
_TEMPORARY_UNCONSUMED_EXPORTS = {
    "DC5ABE696160B448BEDA4B0449EC707521932D3DEF585F89A5333BDC7888C347":
        frozenset((("CP2", "Vrefint"),)),
    "130E57A8BBAC13D77DEB77FA9F811C67A3EF49D589EBA74D809A8F00A01916A2":
        frozenset((("CP2", "Vrefint"),)),
    "34C4AB1FED243ED4F985D6BC919C950C6F13EDAC37022E6DA87BA10DA77D3EEC":
        frozenset((("CP2", "Vrefint"),)),
    "4F0EDED2A2E43A6C0EB2B65185CA542A0AEA854875FD6B2F3C39C3BE3B169476":
        frozenset((("CP2", "Vrefint"),)),
    "93742EB91AC52E10EFC1EB95FD329FA86A480C9EF42436CAFF1200CC09F03AAB":
        frozenset((("CP2", "Vrefint"),)),
    "03A695974FFB0A761942F1D2F229352F1E790D26DF27DEDC50C517FB94B8BFED":
        frozenset((("CP2", "Vrefint"),)),
    "451A7FC8BA3751F80E8B57D68DCE7D3F15460E899B0D5B66AEAC3E83E6C022E7":
        frozenset((("CP2", "Vrefint"),)),
    "D8DFD2EC9F8C177EC74AD05FB87D0CF69BB50EEECDA1E175578272720D4440C7":
        frozenset((("CP2", "Vrefint"),)),
    "E97D9609F0845F8EC103F84AE1FA502BDA4D774B7595D72CF667C1B7791EEEDC":
        frozenset((("CP2", "Vrefint"),)),
    "05D28E2B7B287645FC369086C0190076842D27AB6027FD0A1B7F564237D5A744":
        frozenset((("CP2", "Vrefint"),)),
    "19192D4B9D5DE8CDCBF989E6E837803BD0C406128478766CED4D44A04BDCAED7":
        frozenset((("CP2", "Vrefint"),)),
    "EC90D9FF5D20CF96DB0A6CE78DCE961676AF77F36CE289BF8F64B8C714289003":
        frozenset((("CP2", "Vrefint"),)),
}


class ProductCompileError(ValueError):
    """A ProductCompilation contains blocking diagnostics."""

    def __init__(self, diagnostics: Diagnostics):
        self.diagnostics = diagnostics
        super().__init__(
            "product compilation failed with "
            f"{len(diagnostics.blocking_errors)} blocking ERROR diagnostic(s)"
        )


@dataclass(frozen=True)
class _CpBuildInputs:
    cp: str
    dac_write_plans: DacWritePlanSet
    result_export_plans: ResultExportPlanSet
    build_uid_rows: Mapping[int, BuildUidPlan]
    memory_wakeup_plan: MemoryWakeupPlan | None
    flash_window_plans: Mapping[int, FlashWindowPlan]
    trimdata_read_plans: Mapping[int, TrimdataReadPlan]
    trimdata_write_plans: Mapping[int, TrimdataWritePlan]


@dataclass(frozen=True)
class LegacyAdapterView:
    """R2 bridge for old renderers; it contains no workbook DataFrames."""

    cp: str
    flow_operations: tuple
    recipe_rows: Mapping[int, ExecutableFlowRow]
    trim_specs: Mapping[int, TrimSpec]
    dedicated_trim_plans: Mapping[int, DedicatedTrimPlan]
    os_plans: Mapping[int, OsPlan]
    pdr_verify_plans: Mapping[int, PdrVerifyPlan]
    declarations: object
    canonical_schedule: object
    dac_write_plans: DacWritePlanSet
    result_export_plans: ResultExportPlanSet
    id_plans: IdPlanSet
    persistence_plans: PersistencePlanSet
    build_uid_rows: Mapping[int, BuildUidPlan]
    shmoo_plans: Mapping[int, ShmooPlan]
    commit_shmoo_plans: Mapping[int, CommitShmooPlan]
    addr_map_catalog: AddrMapCatalog
    trim_data_plan: TrimDataPlan
    memory_wakeup_plan: MemoryWakeupPlan | None
    flash_window_plans: Mapping[int, FlashWindowPlan]
    trimdata_read_plans: Mapping[int, TrimdataReadPlan]
    trimdata_write_plans: Mapping[int, TrimdataWritePlan]


@dataclass(frozen=True)
class ProductCompilation:
    workbook_identity: str
    workbook_sha256: str
    identity: str
    diagnostics: Diagnostics
    plan: ProductPlan | None
    pattern_links: tuple[dict, ...] = ()

    @property
    def cp_plans(self):
        return self.plan.cp_plans if self.plan is not None else MappingProxyType({})

    @property
    def is_valid(self) -> bool:
        return self.diagnostics.is_valid

    def require_success(self) -> "ProductCompilation":
        if not self.is_valid:
            raise ProductCompileError(self.diagnostics)
        return self

    @property
    def pattern_compilation(self) -> FbistPatternGenerationPlan:
        """The immutable FBIST pattern generation plan (workbook-free)."""
        self.require_success()
        assert self.plan is not None
        plan = self.plan.catalogs.fbist_pattern_plan
        if not isinstance(plan, FbistPatternGenerationPlan):
            raise ProductCompileError(self.diagnostics)
        return plan

    @property
    def flash_compare_compilation(self) -> RequiredFlashCompareCompilation:
        """Workbook-free Flash facts plus the fixed NM_pattern plans."""
        self.require_success()
        assert self.plan is not None
        compiled = self.plan.catalogs.flash_compare_compilation
        if not isinstance(compiled, RequiredFlashCompareCompilation):
            raise ProductCompileError(self.diagnostics)
        return compiled

    @property
    def flash_label_plan(self) -> FlashLabelGenerationPlan:
        """Workbook-free product-level Flash Label generation plan."""
        self.require_success()
        assert self.plan is not None
        compiled = self.plan.catalogs.flash_label_plan
        if not isinstance(compiled, FlashLabelGenerationPlan):
            raise ProductCompileError(self.diagnostics)
        return compiled

    def for_cp(self, cp: str):
        self.require_success()
        assert self.plan is not None
        key = str(cp).strip().upper()
        try:
            return self.plan.cp_plans[key]
        except KeyError as exc:
            raise KeyError(f"product compilation does not contain {key}") from exc

    def system_read_specs(self, cp: str):
        """Publish workbook-free specs for both mandatory system read kinds."""
        cp_plan = self.for_cp(cp)
        assert self.plan is not None
        try:
            facts = self.plan.catalogs.system_read_facts[cp_plan.cp]
        except KeyError as error:
            raise KeyError(
                f"product compilation has no system read facts for {cp_plan.cp}"
            ) from error
        return bind_system_read_specs(facts, cp_plan.canonical_schedule)

    def adapter_view(self, cp: str, platform: str) -> LegacyAdapterView:
        """Return one complete compatibility input for a legacy renderer."""
        cp_plan = self.for_cp(cp)
        assert self.plan is not None
        catalogs = self.plan.catalogs
        platform_key = str(platform).strip().casefold()
        if platform_key not in ("chroma", "s100"):
            raise ValueError(f"unsupported platform adapter: {platform!r}")
        if catalogs.addr_map is None or catalogs.trim_data is None:
            raise ProductCompileError(self.diagnostics)
        if catalogs.id_plans is None:
            raise ProductCompileError(self.diagnostics)
        return LegacyAdapterView(
            cp=cp_plan.cp,
            flow_operations=catalogs.flow_operations,
            recipe_rows=catalogs.recipe_rows,
            trim_specs=catalogs.trim_specs,
            dedicated_trim_plans=catalogs.dedicated_trim_plans,
            os_plans=catalogs.os_plans[platform_key],
            pdr_verify_plans=catalogs.pdr_verify_plans[platform_key],
            declarations=cp_plan.runtime_state.declarations,
            canonical_schedule=cp_plan.canonical_schedule,
            dac_write_plans=cp_plan.dac_write_plans,
            result_export_plans=cp_plan.result_export_plans,
            id_plans=catalogs.id_plans,
            persistence_plans=catalogs.persistence,
            build_uid_rows=cp_plan.build_uid_rows,
            shmoo_plans=catalogs.shmoo_plans,
            commit_shmoo_plans=catalogs.commit_shmoo_plans,
            addr_map_catalog=catalogs.addr_map,
            trim_data_plan=catalogs.trim_data,
            memory_wakeup_plan=cp_plan.memory_wakeup_plan,
            flash_window_plans=cp_plan.flash_window_plans,
            trimdata_read_plans=cp_plan.trimdata_read_plans,
            trimdata_write_plans=cp_plan.trimdata_write_plans,
        )


class ProductCompiler:
    """Compile one immutable WorkbookModel without platform or filesystem I/O."""

    def compile(self, workbook: WorkbookModel) -> ProductCompilation:
        if not isinstance(workbook, WorkbookModel):
            raise TypeError("ProductCompiler.compile expects WorkbookModel")

        diagnostics = list(_input_diagnostics(workbook))
        if any(item.severity == ERROR for item in diagnostics):
            return _failed_compilation(workbook, diagnostics)

        flow = normalize_flow_table(workbook.dataframe("FLOW"))
        pattern = workbook.dataframe("pattern")
        addr_map = workbook.dataframe("ADDR_MAP")
        flow_sheet = workbook["FLOW"]
        flow.attrs["common_dac_dependencies"] = tuple(
            str(flow.iloc[row]["item"]).strip()
            for row in range(len(flow))
            if flow_sheet["B"][row + 1].fill.fgColor.type == "rgb"
            and flow_sheet["B"][row + 1].fill.fgColor.rgb == "FFFFFF00"
            and not _is_external_scan_or_mbist_row(flow.iloc[row])
        )
        if "Recipe" not in flow.columns:
            diagnostics.append(Diagnostic(
                code="PF.RECIPE.COLUMN_MISSING_LEGACY",
                severity="WARN",
                message="缺少 Recipe 列：将按 legacy writer 语义生成",
                provenance=_provenance(workbook, "FLOW"),
                remediation="仅在迁移到显式 Recipe 流程时新增该列并逐行填写",
                source="PREFLIGHT",
                category="G Recipe",
            ))
            flow = flow.copy()
            flow["Recipe"] = ""
        else:
            blank_recipe = flow["Recipe"].isna() | flow["Recipe"].astype(str).str.strip().eq("")
            active = ~flow.get("item", "").isna() & flow.get("item", "").astype(str).str.strip().ne("")
            blank_indices = tuple(flow.index[blank_recipe & active])
            if blank_indices:
                column = list(flow.columns).index("Recipe") + 1
                first = int(blank_indices[0]) + 2
                diagnostics.append(Diagnostic(
                    code="PF.RECIPE.MIGRATION_INCOMPLETE",
                    severity="WARN",
                    message=f"Recipe 迁移尚未完成：{len(blank_indices)} 行为空",
                    provenance=_provenance(
                        workbook,
                        "FLOW",
                        flow_sheet.cell(first, column).coordinate,
                    ),
                    remediation="在接入新版生成路径前补齐；旧母本缺少 Recipe 列仍按 legacy 语义生成",
                    source="PREFLIGHT",
                    category="G Recipe",
                ))

        for index, record in flow.iterrows():
            if str(record.get("Recipe", "")).strip() and not pd.isna(record.get("Recipe")):
                continue
            effective = default_recipe(
                record.get("item", ""),
                record.get("type", ""),
                record.get("mode", ""),
            )
            if effective is not None:
                flow.at[index, "Recipe"] = effective

        try:
            flow_operations = compile_flow_rows(
                flow,
                workbook_identity=workbook.identity,
                source_sha256=workbook.source_sha256,
            )
            scan_test_plans = compile_scan_test_plans(flow_operations, flow)
            validate_firmware_recipe_contract(flow_operations, flow)
            recipe_rows = compile_recipe_rows(flow, pattern)
            adc_test_plans = compile_adc_test_plans(
                flow_operations,
                recipe_rows,
                flow,
                workbook.dataframe("ADC"),
                workbook.dataframe("IOMUX"),
                workbook.dataframe("VERSION"),
            )
            firmware_test_plans = compile_firmware_test_plans(
                flow_operations,
                recipe_rows,
                flow,
                workbook.dataframe("VERSION"),
            )
            pvd_test_plans = compile_pvd_test_plans(
                flow_operations,
                recipe_rows,
                flow,
                workbook.dataframe("PVD"),
                workbook.dataframe("VERSION"),
                disabled_pvd_rows=frozenset(
                    row for row, flag in _sheet_row_flags(
                        workbook, "PVD", len(workbook.dataframe("PVD")), 1
                    ).items()
                    if flag == "comment_out"
                ),
            )
            dc_parametric_plans = compile_dc_parametric_plans(
                flow_operations,
                recipe_rows,
                flow,
                workbook.dataframe("VERSION"),
            )
            vih_vil_plans = compile_vih_vil_plans(
                flow_operations,
                recipe_rows,
                flow,
                workbook.dataframe("VERSION"),
            )
            freq_test_plans = compile_freq_test_plans(
                flow_operations,
                recipe_rows,
                flow,
                workbook.dataframe("FREQ"),
                workbook.dataframe("IOMUX"),
                workbook.dataframe("VERSION"),
            )
            opa_test_plans = compile_opa_test_plans(
                flow_operations, recipe_rows, flow,
                workbook.dataframe("OPA"), workbook.dataframe("VERSION"),
            )
            dac_test_plans = compile_dac_test_plans(
                flow_operations, recipe_rows, flow,
                workbook.dataframe("DAC"), workbook.dataframe("VERSION"),
            )
            catalog = compile_addr_map_catalog(
                addr_map, workbook.trim_storage_mappings, workbook.verify_storage_mappings
            )
            system_read_facts = compile_system_read_facts(
                workbook.dataframe("VERSION"),
                addr_map,
                workbook.dataframe("FLASH_EPR"),
            )
            trim_data_plan = compile_trim_data_plan(flow)
            version_columns = (
                tuple(workbook.dataframe("VERSION").columns)
                if workbook.has_sheet("VERSION")
                else None
            )
            nm_pattern = (
                workbook.dataframe("NM_pattern")
                if workbook.has_sheet("NM_pattern")
                else None
            )
            cps = _cp_order(flow, workbook)
            export_by_cp = {
                cp: compile_result_export_plan_set(flow, recipe_rows, cp)
                for cp in cps
            }
            exports_by_row = {
                plan.flow_row_index: plan
                for plan_set in export_by_cp.values()
                for plan in plan_set.plans
            }
            trim_specs = compile_trim_specs(
                flow,
                pattern,
                version_columns,
                nm_pattern,
                version_frame=(
                    workbook.dataframe("VERSION")
                    if workbook.has_sheet("VERSION")
                    else None
                ),
                result_export_plans=exports_by_row,
            )
            trim_storage_sources = tuple(SimpleNamespace(
                item=spec.item, cp=spec.cp,
                required_bits=max(spec.search.search_bits, getattr(getattr(spec, "dac", None), "field_width", 0)),
            ) for spec in trim_specs.values())
            validate_storage_mapping_records(
                "trim", workbook.trim_storage_mappings, catalog, trim_storage_sources
            )
            verify_sources = verify_storage_sources(flow, exports_by_row)
            validate_storage_mapping_records(
                "verify", workbook.verify_storage_mappings, catalog, verify_sources
            )
            validate_storage_role_occupancy(catalog)
            validate_storage_flow_occupancy(flow, catalog)
            validate_storage_explicit_commits(catalog, trim_specs, verify_sources, recipe_rows)
            id_plans = compile_id_plan_set(flow)
            shmoo_plans = compile_shmoo_plans(flow, pattern)
            commit_shmoo_plans = compile_commit_shmoo_plans(
                flow, recipe_rows, catalog
            )

            exports = {
                plan.flow_row_index: plan.symbol
                for plan_set in export_by_cp.values()
                for plan in plan_set.plans
            }
            default_bindings = compile_default_commit_bindings(
                flow, recipe_rows, catalog, export_symbols=exports
            )
            persistence_plans = compile_persistence_plan_set(
                flow,
                recipe_rows,
                catalog,
                node_write_pages=compile_write_page_scopes(flow, recipe_rows, catalog),
                node_default_bindings={
                    row_index + 2: bindings
                    for row_index, bindings in default_bindings.items()
                },
            )
            allowed_unconsumed = _TEMPORARY_UNCONSUMED_EXPORTS.get(
                workbook.source_sha256, frozenset()
            )
            validate_export_use_def(
                export_by_cp,
                recipe_rows,
                allowed_unconsumed=allowed_unconsumed,
            )
            for cp, item in sorted(allowed_unconsumed):
                diagnostics.append(Diagnostic(
                    code="EXPORT.USE_DEF.UNCONSUMED",
                    severity=WARN,
                    message=(
                        f"EXPORT.USE_DEF.UNCONSUMED: {cp}/{item} has no "
                        "OTP/UID/DAC_ADJ consumer; temporary formal-master exception"
                    ),
                    provenance=_provenance(workbook, "FLOW"),
                    remediation=(
                        "Remove this temporary exception after the formal FLOW adds "
                        "a CP-local OTP, UID, or DAC_ADJ consumer"
                    ),
                    category="Compiler",
                ))
            result_bindings = compile_product_result_bindings(
                export_by_cp,
                persistence_plans,
                explicitly_unlinked_verify_items=(
                    mapping.item for mapping in workbook.verify_storage_mappings
                    if not mapping.targets
                ),
            )
            result_imports = compile_persisted_result_imports(
                result_bindings, (), ()
            )
            fbist_pattern_plan = compile_fbist_pattern_plan(
                workbook,
                flow,
                trim_specs=trim_specs,
                recipe_rows=recipe_rows,
            )
            validate_explicit_recipe_patterns(
                recipe_rows,
                (pattern.pattern_name for pattern in fbist_pattern_plan.patterns),
            )
            flash_compare_compilation = compile_required_flash_compare_plans(workbook)
            flash_label_contract = compile_flash_label_contract(catalog)
            flash_label_plan = compile_flash_label_plan(
                catalog, flash_compare_compilation.facts,
                contract=flash_label_contract,
            )
            trimdata_read_plans = MappingProxyType({
                operation.row: compile_trimdata_read_plan(
                    persistence_plans.rows[operation.row],
                    trim_data_plan,
                    catalog,
                    excel_row=operation.row + 2,
                    item=operation.item,
                    provenance=operation.provenance,
                    power_profile=str(flow.iloc[operation.row].get("Vcc", "")),
                    fbist_plan=fbist_pattern_plan,
                    flash_labels=flash_label_contract,
                    read_bit=flash_compare_compilation.facts.read_bits,
                )
                for operation in flow_operations
                if operation.typed_kind == "TRIMDATA_READ"
            })
            commit_modules = compile_commit_module_plans(
                persistence_plans,
                catalog,
                swd_pin=fbist_pattern_plan.swd_pin,
                flash_labels=flash_label_contract,
            )
            trimdata_write_plans = compile_trimdata_write_plans(
                flow_operations,
                persistence_plans,
                commit_modules,
                flow,
                flash_label_contract,
                catalog=catalog,
                swd_pin=fbist_pattern_plan.swd_pin,
                recipe_rows=recipe_rows,
            )
            try:
                build_uid_modules = {
                    row: compile_build_uid_module_plan(cp=recipe.flow.cp,
                        version_frame=workbook.dataframe("VERSION"), flash_label_plan=flash_label_plan)
                    for row, recipe in recipe_rows.items()
                    if any(call.name == "BUILDUID" for call in recipe.operations)
                }
                uid_plans = compile_uid_write_plans(
                    flow_operations, recipe_rows, persistence_plans, id_plans, flow, catalog,
                    flash_label_plan, swd_pin=fbist_pattern_plan.swd_pin,
                    read_bit=flash_compare_compilation.facts.read_bits,
                    build_uid_modules=build_uid_modules,
                )
                id_module_plans = compile_id_test_plans(
                    flow_operations, recipe_rows, id_plans, flow, flash_label_plan,
                )
            except ValueError as error:
                raise FlowCompileError(str(error)) from error
            dac_write_by_cp = {
                cp: compile_dac_write_plan_set(recipe_rows, cp)
                for cp in cps
            }
            dac_final_producers = {
                cp: {
                    symbol: tuple(
                        row for row, spec in trim_specs.items()
                        if spec.cp.casefold() == cp.casefold()
                        and spec.dac_final_symbol == symbol
                    )
                    for symbol in {
                        spec.dac_final_symbol
                        for spec in trim_specs.values()
                        if spec.cp.casefold() == cp.casefold()
                    }
                }
                for cp in cps
            }
            dac_write_modules = {
                row: module
                for cp in cps
                for row, module in compile_dac_write_module_plans(
                    dac_write_by_cp[cp], catalog, fbist_pattern_plan, cp,
                    persistence_plans, dac_final_producers[cp],
                ).items()
            }
            dac_adjust_plans = compile_dac_adjust_action_plans(
                flow_operations,
                recipe_rows,
                export_by_cp,
                trim_specs,
                catalog,
                persistence_plans,
                fbist_pattern_plan,
                commit_modules,
            )
            standard_verify_plans = compile_standard_verify_plans(
                flow_operations,
                recipe_rows,
                flow,
                {
                    plan.flow_row_index: plan
                    for plan_set in export_by_cp.values()
                    for plan in plan_set.plans
                },
                dac_write_rows=dac_write_modules,
                nm_pattern_frame=nm_pattern,
                version_frame=workbook.dataframe("VERSION"),
                commit_rows=commit_modules,
            )
            flash_windows = compile_flash_window_plans(
                flow_operations,
                recipe_rows,
                flow,
                trim_specs,
                catalog,
                fbist_pattern_plan,
                flash_compare_compilation.requests,
                dac_adjust_plans,
                persistence_plans=persistence_plans,
                result_bindings=result_bindings,
            )
            main_plans = compile_main_plans(
                flow_operations, recipe_rows, flow, flash_compare_compilation.requests,
                fbist_pattern_plan, flash_windows.vposp_snapshots,
            )
            vt_plans = compile_vt_plans(
                flow_operations, recipe_rows, flow, workbook.dataframe("VERSION"),
                flash_compare_compilation.requests, fbist_pattern_plan, id_module_plans,
                flash_label_plan=flash_label_plan,
            )
            margin_plans = compile_margin_plans(
                flow_operations, recipe_rows, flow, flash_compare_compilation.requests,
                fbist_pattern_plan, id_module_plans,
                flash_label_plan=flash_label_plan,
            )
            for warning in flash_windows.warnings:
                diagnostics.append(Diagnostic(
                    code=warning.code,
                    severity=WARN,
                    message=warning.message,
                    provenance=_provenance(
                        workbook, "FLOW", f"row {warning.excel_row}"
                    ),
                    remediation=(
                        "确认该 Trim 必须位于 BUILDMAP 后；其字段当前保持 ADDR_MAP 默认值，"
                        "并确保后续 producer 由合法 consumer 消费"
                    ),
                    category="Compiler",
                ))
            validate_trim_dac_use_def(
                flow,
                recipe_rows,
                flash_windows.plans,
                persistence_plans,
            )
            dedicated_trim_plans = compile_dedicated_trim_plans(
                flow,
                flow_operations,
                pattern_frame=pattern,
                version_frame=workbook.dataframe("VERSION"),
            )
            os_plans = MappingProxyType({
                platform: MappingProxyType({
                    operation.row: compile_os_plan(operation, platform)
                    for operation in flow_operations
                    if operation.typed_kind == "OS"
                })
                for platform in ("chroma", "s100")
            })
            pdr_verify_plans = MappingProxyType({
                platform: MappingProxyType({
                    operation.row: compile_pdr_verify_plan(
                        flow,
                        operation,
                        platform,
                        version_frame=workbook.dataframe("VERSION"),
                    )
                    for operation in flow_operations
                    if operation.typed_kind == "PDR_VERIFY"
                })
                for platform in ("chroma", "s100")
            })

            cp_plans = {}
            for cp in cps:
                memory_wakeup = _memory_wakeup_for_cp(
                    cp, flow, trim_data_plan, catalog
                )
                cp_plans[cp] = _CpBuildInputs(
                    cp=cp,
                    dac_write_plans=dac_write_by_cp[cp],
                    result_export_plans=export_by_cp[cp],
                    build_uid_rows=MappingProxyType(dict(
                        _compile_build_uid_rows(recipe_rows, cp)
                    )),
                    memory_wakeup_plan=memory_wakeup,
                    flash_window_plans=MappingProxyType({
                        row: plan for row, plan in flash_windows.plans.items()
                        if plan.cp.casefold() == cp.casefold()
                    }),
                    trimdata_read_plans=MappingProxyType({
                        row: plan for row, plan in trimdata_read_plans.items()
                        if plan.cp.casefold() == cp.casefold()
                    }),
                    trimdata_write_plans=MappingProxyType({
                        row: plan for row, plan in trimdata_write_plans.items()
                        if plan.cp.casefold() == cp.casefold()
                    }),
                )
        except (
            AddrMapCompileError,
            CommitModuleCompileError,
            CommitShmooPlanError,
            FlowCompileError,
            IdPlanError,
            MemoryWakeupCompileError,
            PatternCompileError,
            PersistenceCompileError,
            ShmooRecipeError,
            TrimCompileError,
            TrimDataCompileError,
            ProjectMappingsError,
            FlowKindCompileError,
            AdcTestCompileError,
            FirmwareTestCompileError,
            PvdTestCompileError,
            DcParametricCompileError,
            VihVilCompileError,
            DedicatedTrimCompileError,
            OsPlanError,
            PdrVerifyPlanError,
            StandardVerifyPlanError,
            SystemReadCompileError,
            ResultBindingCompileError,
            ResultUseDefError,
            FbistPatternCompileError,
            DacWriteCompileError,
            DacAdjustActionPlanError,
            FlashWindowCompileError,
            NmTestCompileError,
            VtTestCompileError,
            MarginTestCompileError,
            FlashCompareProductCompileError,
            FlashLabelCompileError,
            TrimDacUseDefError,
            TrimdataReadCompileError,
            TrimdataWriteCompileError,
            FreqTestCompileError,
            OpaTestCompileError,
            DacTestCompileError,
            ScanTestCompileError,
        ) as exc:
            diagnostics.append(_compiler_exception_diagnostic(workbook, exc))
            return _failed_compilation(workbook, diagnostics)

        diagnostic_set = Diagnostics.from_iterable(diagnostics)
        cp_plans = MappingProxyType(dict(cp_plans))
        catalogs = ProductCatalogs(
            flow_operations=flow_operations,
            recipe_rows=MappingProxyType(dict(recipe_rows)),
            addr_map=catalog,
            trim_specs=MappingProxyType(dict(trim_specs)),
            dedicated_trim_plans=dedicated_trim_plans,
            os_plans=os_plans,
            pdr_verify_plans=pdr_verify_plans,
            standard_verify_plans=standard_verify_plans,
            adc_test_plans=adc_test_plans,
            firmware_test_plans=firmware_test_plans,
            pvd_test_plans=pvd_test_plans,
            dc_parametric_plans=dc_parametric_plans,
            vih_vil_plans=vih_vil_plans,
            freq_test_plans=freq_test_plans,
            opa_test_plans=opa_test_plans,
            dac_test_plans=dac_test_plans,
            scan_test_plans=scan_test_plans,
            dac_adjust_plans=dac_adjust_plans,
            flash_window_plans=flash_windows.plans,
            main_plans=main_plans,
            vt_plans=vt_plans,
            margin_plans=margin_plans,
            trimdata_read_plans=trimdata_read_plans,
            trimdata_write_plans=trimdata_write_plans,
            uid_plans=uid_plans,
            id_module_plans=id_module_plans,
            trim_data=trim_data_plan,
            id_plans=id_plans,
            persistence=persistence_plans,
            default_commit_bindings=MappingProxyType(dict(default_bindings)),
            shmoo_plans=MappingProxyType(dict(shmoo_plans)),
            commit_shmoo_plans=MappingProxyType(dict(commit_shmoo_plans)),
            system_read_facts=system_read_facts,
            result_bindings=result_bindings,
            result_imports=result_imports,
            fbist_pattern_plan=fbist_pattern_plan,
            flash_compare_compilation=flash_compare_compilation,
            flash_label_plan=flash_label_plan,
        )
        semantic_identity = _compilation_identity(workbook, catalogs, cp_plans)
        try:
            program_plan = compile_program_plan(
                flow,
                workbook_identity=workbook.identity,
                workbook_sha256=workbook.source_sha256,
                recipe_rows=recipe_rows,
                row_flags=_flow_row_flags(workbook, len(flow)),
                trim_specs=trim_specs,
                cp_compilations=cp_plans,
                persistence_plans=persistence_plans,
                catalogs=catalogs,
                semantic_identity=semantic_identity,
                flow_operations=flow_operations,
                result_imports=result_imports,
            )
            validate_vt_gate_schedule(vt_plans, id_module_plans, program_plan.cp_plans)
            validate_margin_gate_schedule(margin_plans, id_module_plans, program_plan.cp_plans)
        except (ProgramPlanError, DeclarationCompileError, SchedulePlanError, VtTestCompileError, MarginTestCompileError) as exc:
            diagnostics.append(_compiler_exception_diagnostic(workbook, exc))
            return _failed_compilation(workbook, diagnostics)
        return ProductCompilation(
            workbook_identity=workbook.identity,
            workbook_sha256=workbook.source_sha256,
            identity=program_plan.identity,
            diagnostics=diagnostic_set,
            plan=program_plan,
            pattern_links=tuple(getattr(workbook, 'pattern_links', ())),
        )


def _is_external_scan_or_mbist_row(record) -> bool:
    """SCAN/MBIST artifacts are frozen external resources, never DAC sources."""
    return (
        str(record.get("type", "")).strip().casefold() == "verify"
        and str(record.get("mode", "")).strip().casefold() in {"scan", "mbist"}
    )


def _input_diagnostics(workbook: WorkbookModel) -> tuple[Diagnostic, ...]:
    # Input-only rules do not invoke any business compiler.  ProductCompiler
    # owns Recipe/Persistence compilation; preflight later projects this result.
    from preflight.checker import _run_input_checks

    return tuple(
        _diagnostic_from_finding(workbook, item)
        for item in _run_input_checks(workbook)
    )


def _flow_row_flags(workbook: WorkbookModel, row_count: int) -> Mapping[int, str | None]:
    sheet = workbook["FLOW"]
    flags = {}
    for row in range(row_count):
        color = sheet["B"][row + 1].fill.fgColor
        flag = None
        if color.type == "rgb" and color.rgb == "FF92D050":
            flag = "force_pass"
        elif (
            color.type == "theme"
            and color.theme == 0
            and abs(color.tint - (-0.5)) < 1e-6
        ):
            flag = "comment_out"
        flags[row] = flag
    return MappingProxyType(flags)


def _sheet_row_flags(
    workbook: WorkbookModel,
    sheet_name: str,
    row_count: int,
    column: int,
) -> Mapping[int, str | None]:
    sheet = workbook[sheet_name]
    flags = {}
    for row in range(row_count):
        color = sheet.cell(row + 2, column).fill.fgColor
        flags[row] = (
            "comment_out"
            if color.type == "theme"
            and color.theme == 0
            and abs(color.tint - (-0.5)) < 1e-6
            else None
        )
    return MappingProxyType(flags)


def _finding_code(finding) -> str:
    prefix = str(finding.category).split(maxsplit=1)[0].upper()
    message = str(finding.message)
    if prefix == "A":
        if "首尾" in message:
            return "PF.CHAR.OUTER_SPACE"
        if "不间断" in message or "NBSP" in message:
            return "PF.CHAR.NONBREAKING_SPACE"
        if "零宽" in message or "隐形" in message:
            return "PF.CHAR.ZERO_WIDTH"
        return "PF.CHAR.FULLWIDTH"
    if prefix == "B":
        if "缺少 sheet" in message:
            return "PF.SCHEMA.SHEET_MISSING"
        if "缺少列" in message:
            return "PF.SCHEMA.COLUMN_MISSING"
        if "item 为空" in message:
            return "PF.FLOW.ITEM_BLANK_MIDROW"
        return "PF.SCHEMA.REQUIRED_EMPTY"
    if prefix == "C1":
        return "PF.TYPE.BITSTRING_NUMERIC"
    if prefix == "C2":
        return "PF.TYPE.NUMBER_INVALID"
    if prefix == "C3":
        return "PF.TYPE.LIMIT_INVALID"
    if prefix == "C":
        return "PF.TYPE.PIN_CONTAINS_SPACE"
    if prefix == "D":
        return "PF.FLOW.PVD_MODE_UNSUPPORTED" if "PVD" in message else "PF.TYPE.ENUM_INVALID"
    if prefix == "E":
        return "PF.BITFIELD.OVERLAP"
    if prefix == "F":
        if "查不到" in message:
            return "PF.FBMAP.FIELD_MISSING"
        if "位段" in message:
            return "PF.FBMAP.BIT_RANGE_CONFLICT"
        return "PF.FBMAP.ADDRESS_UNRESOLVED"
    if prefix == "H":
        return (
            "PF.LOGICAL_ITEM.DEPEND_SOURCE_MISSING"
            if "DEPEND" in message else "PF.LOGICAL_ITEM.ROLE_SUFFIX"
        )
    return "PF.CONTRACT"


def _provenance(
    workbook: WorkbookModel, sheet: str, coordinate: str = ""
) -> WorkbookProvenance:
    return WorkbookProvenance(
        sheet=str(sheet),
        coordinate=str(coordinate),
        workbook_identity=workbook.identity,
        source_sha256=workbook.source_sha256,
    )


def _diagnostic_from_finding(workbook: WorkbookModel, finding) -> Diagnostic:
    return Diagnostic(
        code=_finding_code(finding),
        severity=str(finding.severity).upper(),
        message=str(finding.message),
        provenance=_provenance(workbook, finding.sheet, finding.coord),
        remediation=str(finding.suggest).strip() or "修正该母本输入后重新编译",
        source="PREFLIGHT",
        category=str(finding.category),
    )


def _compiler_exception_diagnostic(
    workbook: WorkbookModel, exc: Exception
) -> Diagnostic:
    name = type(exc).__name__
    if isinstance(exc, ResultUseDefError):
        stage = (str(exc).partition(":")[0], "FLOW")
    elif isinstance(exc, (
        ProgramPlanError,
        FlowKindCompileError,
        AdcTestCompileError,
        FirmwareTestCompileError,
        PvdTestCompileError,
        DeclarationCompileError,
        SchedulePlanError,
        PdrVerifyPlanError,
        VtTestCompileError,
        MarginTestCompileError,
    )):
        stage = (exc.code, "FLOW")
    else:
        stage = {
        "FlowCompileError": ("COMPILER.RECIPE", "FLOW"),
        "PatternCompileError": ("COMPILER.PATTERN", "pattern"),
        "FbistPatternCompileError": ("COMPILER.FBIST_PATTERN", "pattern"),
        "FlashCompareProductCompileError": ("COMPILER.FLASH_COMPARE", "FLASH_EPR"),
        "AddrMapCompileError": ("COMPILER.ADDR_MAP", "ADDR_MAP"),
        "ProjectMappingsError": ("COMPILER.PROJECT_MAPPINGS", "WORKBOOK"),
        "CommitModuleCompileError": ("COMPILER.COMMIT_MODULE", "FLOW"),
        "TrimCompileError": ("COMPILER.TRIM", "FLOW"),
        "TrimDataCompileError": ("COMPILER.TRIM_DATA", "FLOW"),
        "PersistenceCompileError": ("COMPILER.PERSISTENCE", "FLOW"),
        "CommitShmooPlanError": ("COMPILER.COMMIT_SHMOO", "FLOW"),
        "ShmooRecipeError": ("COMPILER.SHMOO", "FLOW"),
        "IdPlanError": ("COMPILER.UID", "FLOW"),
        "MemoryWakeupCompileError": ("COMPILER.MEMORY_WAKEUP", "FLOW"),
        "FlashWindowCompileError": ("COMPILER.FLASH_WINDOW", "FLOW"),
        "TrimdataReadCompileError": ("COMPILER.TRIMDATA_READ", "FLOW"),
        "TrimdataWriteCompileError": ("COMPILER.TRIMDATA_WRITE", "FLOW"),
        "TrimDacUseDefError": ("COMPILER.TRIM_USE_DEF", "FLOW"),
        }.get(name, ("COMPILER.INTERNAL_CONTRACT", "WORKBOOK"))
    message = str(exc)
    row = re.search(r"(?:FLOW|Excel) row (\d+)", message, flags=re.IGNORECASE)
    return Diagnostic(
        code=stage[0],
        severity=ERROR,
        message=message or name,
        provenance=_provenance(
            workbook, stage[1], f"row {row.group(1)}" if row else ""
        ),
        remediation="修正诊断指向的母本契约；ProductCompiler 不会猜测或自动补全业务语义",
        category="Compiler",
    )


def _cp_order(flow, workbook: WorkbookModel) -> tuple[str, ...]:
    cps = []
    if "CP NO" in flow.columns:
        for value in flow["CP NO"]:
            cp = str(value).strip().upper()
            if re.fullmatch(r"CP\d+", cp) and cp not in cps:
                cps.append(cp)
    if not cps and workbook.has_sheet("VERSION"):
        version = workbook.dataframe("VERSION")
        if "CP num" in version.columns:
            for value in version["CP num"]:
                cp = str(value).strip().upper()
                if re.fullmatch(r"CP\d+", cp) and cp not in cps:
                    cps.append(cp)
    return tuple(cps)


def _memory_wakeup_for_cp(
    cp: str,
    flow,
    trim_data_plan: TrimDataPlan,
    catalog: AddrMapCatalog,
) -> MemoryWakeupPlan | None:
    # Legacy renderer bridge; native CP1/CP2 routing is FLASH_WINDOW.
    if cp.upper() != "CP1":
        return None
    selected = flow[
        (flow["CP NO"].astype(str).str.strip().str.upper() == cp)
        & (flow["item"].astype(str).str.strip().str.casefold() == "memory_wakeup")
    ]
    if selected.empty:
        return None
    return compile_memory_wakeup_plan(trim_data_plan, catalog, cp=cp)


def _compile_build_uid_rows(
    recipe_rows: Mapping[int, ExecutableFlowRow], cp: str
) -> Mapping[int, BuildUidPlan]:
    selected = tuple(row for row in recipe_rows.values() if row.flow.cp == cp)
    modules = tuple(operation.name for row in selected for operation in row.operations)
    plan = UidPlanCompiler(_BUILD_UID_SCHEMA).plan_for_cp(cp, recipe_modules=modules)
    if plan is None:
        return {}
    owner = next(
        row for row in selected
        if any(operation.name == "BUILDUID" for operation in row.operations)
    )
    return {owner.flow.excel_row - 2: plan}


def _failed_compilation(
    workbook: WorkbookModel, diagnostics: list[Diagnostic]
) -> ProductCompilation:
    diagnostic_set = Diagnostics.from_iterable(diagnostics)
    identity = hashlib.sha256(json.dumps(
        {
            "workbook": workbook.identity,
            "diagnostics": _canonical(diagnostic_set),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")).hexdigest().upper()
    return ProductCompilation(
        workbook_identity=workbook.identity,
        workbook_sha256=workbook.source_sha256,
        identity=identity,
        diagnostics=diagnostic_set,
        plan=None,
        pattern_links=tuple(getattr(workbook, 'pattern_links', ())),
    )


def _compilation_identity(
    workbook,
    plan,
    cp_plans,
) -> str:
    payload = {
        "workbook": workbook.identity,
        "plan": plan,
        "cp_plans": cp_plans,
    }
    raw = json.dumps(
        _canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest().upper()


def _canonical(value: Any, _seen: set[int] | None = None):
    seen = set() if _seen is None else _seen
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
        return value
    if isinstance(value, Enum):
        return _canonical(value.value, seen)
    identity = id(value)
    if identity in seen:
        return {"$ref": type(value).__qualname__}
    if is_dataclass(value):
        seen.add(identity)
        try:
            return {
                field.name: _canonical(getattr(value, field.name), seen)
                for field in fields(value)
                if not field.name.startswith("_")
                and not (
                    field.metadata.get("canonical_omit_if_empty", False)
                    and not getattr(value, field.name)
                )
            }
        finally:
            seen.remove(identity)
    if isinstance(value, Mapping):
        seen.add(identity)
        try:
            return [
                [_canonical(key, seen), _canonical(item, seen)]
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            ]
        finally:
            seen.remove(identity)
    if isinstance(value, (tuple, list, set, frozenset)):
        seen.add(identity)
        try:
            items = [_canonical(item, seen) for item in value]
            return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
        finally:
            seen.remove(identity)
    return str(value)
