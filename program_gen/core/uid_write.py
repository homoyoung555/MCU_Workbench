"""Compile UID recipes once; adapters receive only resolved plans."""

from dataclasses import dataclass, replace
import re
from types import MappingProxyType

from flow_recipe import RecipeValueToken
from program_gen.core.id_module import compile_id_module_plan
from program_gen.core.commit_module import CommitFieldValue, compile_commit_module_plan
from program_gen.core.otp_program import (
    PagePatternPlan, compile_load_map_module_plan, compile_pgm_otp_module_plan,
)
from program_gen.core.trimdata_read import (
    CheckOtpPlan, ReadOtpMapPagePlan, ReadOtpMapPlan, _run,
)


@dataclass(frozen=True, slots=True)
class UidStep:
    module: str
    module_plan: object
    gated: bool = False


@dataclass(frozen=True, slots=True)
class UidWritePlan:
    row: int
    excel_row: int
    cp: str
    item: str
    provenance: object
    effective_recipe: tuple[str, ...]
    steps: tuple[UidStep, ...]
    test_number: int
    power_profile: str
    enter_fbist_mode: object
    gate_symbol: str | None


@dataclass(frozen=True, slots=True)
class IdTestPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    test_number: int
    steps: tuple[UidStep, ...]


def compile_id_test_plans(flow_operations, recipe_rows, id_plans, flow, flash_label_plan):
    plans = {}
    for operation in flow_operations:
        if operation.typed_kind != "ID":
            continue
        identity = id_plans.for_row(operation.row)
        variant = uid_target_variant(identity.target.target, flash_label_plan)
        if not variant.names.check_pattern:
            raise ValueError(f"ID.CHECK_PATTERN.MISSING: {identity.target.target}")
        plan = compile_id_module_plan(identity, cp=operation.cp,
            power_profile=flow.iloc[operation.row].get("Vcc", ""),
            enter_fbist_mode=_run("enter_fbist_mode"), check_pattern=_run(variant.names.check_pattern))
        if tuple(call.name for call in recipe_rows[operation.row].operations) != (plan.module_name,):
            raise ValueError(f"ID.RECIPE.INVALID: FLOW!A{operation.row + 2}")
        plans[operation.row] = IdTestPlan(operation.row, operation.row + 2, operation.cp,
            operation.item, (operation.row + 1) * 100, (UidStep(plan.module_name, plan),))
    return MappingProxyType(plans)


def uid_target_variant(target, flash_label_plan):
    match = re.fullmatch(r"CP(\d+)(?:_?(BAKE))?ID", target, re.I)
    if not match:
        raise ValueError(f"UID.TARGET.INVALID: {target!r}")
    key = f"cp{match[1]}_" + ("bake_id" if match[2] else "id")
    try:
        return next(variant for variant in flash_label_plan.uid_variants if variant.name == key)
    except StopIteration as error:
        raise ValueError(f"UID.TARGET.UNDEFINED: {target!r}") from error


def compile_uid_write_plans(flow_operations, recipe_rows, persistence, id_plans,
                            flow, catalog, flash_label_plan, *, swd_pin, read_bit,
                            build_uid_modules=None):
    plans = {}
    for operation in flow_operations:
        if operation.typed_kind != "UID":
            continue
        contract = flash_label_plan.contract
        uid_page = next(page for page in contract.pages if page.page.casefold() == "uid")
        identity = id_plans.for_row(operation.row)
        variant = uid_target_variant(identity.target.target, flash_label_plan)
        gate = id_plans.bake_gate_for_row(operation.row)
        if operation.row not in recipe_rows:
            raise ValueError(f"UID.RECIPE.MISSING: FLOW!A{operation.row + 2}")
        calls = recipe_rows[operation.row].operations
        modules = tuple(call.name for call in calls)
        expected = (("READOTPMAP", "LOADMAP", "CHECKOTP", "COMMIT", "PGMOTP")
                    if gate else ("BUILDUID", "COMMIT", "PGMOTP")
                    if "BUILDUID" in modules else ("COMMIT", "PGMOTP"))
        if modules != expected:
            raise ValueError(f"UID.RECIPE.INVALID: FLOW!A{operation.row + 2}: {modules!r}")
        persisted_steps = persistence.rows[operation.row].operations
        if tuple(step.module for step in persisted_steps) != modules:
            raise ValueError(f"UID.RECIPE.PLAN_MISMATCH: FLOW!A{operation.row + 2}")
        for step in persisted_steps:
            if step.module in ("READOTPMAP", "LOADMAP", "CHECKOTP", "PGMOTP"):
                if step.requested_pages != ("uid",) or any(page != "uid" for page in step.effective_pages):
                    raise ValueError(f"UID.PAGE_SCOPE.INVALID: FLOW!A{operation.row + 2}/{step.module}")
        normal_variant = uid_target_variant(operation.cp + "ID", flash_label_plan)
        page = PagePatternPlan("uid", uid_page.erase_pattern,
                               normal_variant.names.program_pattern, normal_variant.names.read_pattern, True)
        profile = str(flow.iloc[operation.row].get("Vcc", "")).strip().upper()
        pass_values = _identity_values(variant, page)
        if not pass_values:
            raise ValueError(f"UID.PASS_ID.MISSING: {identity.target.target}")
        steps = []
        build = (build_uid_modules or {}).get(operation.row)
        prior_registers = tuple(register for register in catalog.registers
            if register.page.casefold() == "uid" and register.applies_to(operation.cp)
            and _has_prior_uid_value(register.register, operation.row, flow, catalog)) if gate else ()
        for persisted in persistence.rows[operation.row].operations:
            module = persisted.module
            if module == "COMMIT":
                # A field name may fan out to OTP and UID; this Kind owns UID only.
                selected = replace(persisted, field_writes=tuple(
                    write for write in persisted.field_writes if write.page.casefold() == "uid"
                ))
                plan = compile_commit_module_plan(selected, catalog, cp=operation.cp,
                                                  swd_pin=swd_pin, flash_labels=contract)
                plan = replace(plan, targets=tuple(replace(target,
                    program_pattern=page.program_pattern, read_pattern=page.read_pattern,
                ) for target in plan.targets))
                values = pass_values if build is None else tuple(
                    CommitFieldValue(word.label.semantic_name, RecipeValueToken("VARIABLE", word.symbol),
                                     page.program_pattern, page.read_pattern, (word.label,),
                                     value_type=word.value_type)
                    for word in build.words)
                plan = replace(plan, field_values=values)
            elif module == "PGMOTP":
                plan = compile_pgm_otp_module_plan((page,), cp=operation.cp, power_profile=profile)
            elif module == "READOTPMAP":
                capture = ReadOtpMapPagePlan("uid", _run(uid_page.capture_pattern, "capture"),
                    catalog.capture_layout("uid", read_bit=read_bit),
                    restore_registers=tuple(register.register for register in prior_registers))
                plan = ReadOtpMapPlan(operation.cp, (capture,), (), swd_pin, read_bit)
            elif module == "LOADMAP":
                plan = compile_load_map_module_plan((page,), catalog, contract, cp=operation.cp,
                    swd_pin=swd_pin, image_source="READOTPMAP_UID", registers=prior_registers)
                previous_target = re.sub(r"_?BakeID$", "ID", identity.target.target, flags=re.I)
                previous_variant = uid_target_variant(previous_target, flash_label_plan)
                temporary = tuple(replace(value, read_dont_care=True)
                                  for value in _identity_values(previous_variant, page))
                # Current-CP PASS/manufacturing defaults must not certify a Bake write.
                later_words = set(dict(normal_variant.word_overrides)) - set(dict(variant.word_overrides))
                later_fields = tuple(CommitFieldValue(span.semantic_name,
                    RecipeValueToken("HEX", f"0x{(1 << span.width) - 1:X}"),
                    page.program_pattern, page.read_pattern, (span,), read_dont_care=True)
                    for word, spans in normal_variant.identity_labels if word in later_words for span in spans)
                prepared = {span for field in temporary + later_fields for span in field.labels}
                identity_masks = tuple(CommitFieldValue(span.semantic_name,
                    RecipeValueToken("HEX", "0x0"), page.program_pattern, page.read_pattern,
                    (span,), read_dont_care=True, write_program=False)
                    for _, spans in normal_variant.identity_labels for span in spans if span not in prepared)
                restored = {register.register for register in prior_registers}
                masks = tuple(CommitFieldValue(register.register, RecipeValueToken("HEX", "0xFFFF"),
                    page.program_pattern, page.read_pattern,
                    contract.bind_register("uid", register.register, operation.cp).spans,
                    read_dont_care=True, write_program=False)
                    for register in catalog.registers if register.page.casefold() == "uid"
                    and register.applies_to(operation.cp) and register.register not in restored)
                plan = replace(plan, field_values=temporary + later_fields + identity_masks + masks)
            elif module == "CHECKOTP":
                plan = CheckOtpPlan(operation.cp, _run("set_all_final_vposp"), (_run(page.read_pattern),))
            elif module == "BUILDUID":
                if build is None:
                    raise ValueError(f"UID.BUILDUID.PLAN_MISSING: FLOW!A{operation.row + 2}")
                plan = build
            else:
                raise ValueError(f"UID.MODULE.UNSUPPORTED: {module}")
            steps.append(UidStep(module, plan, bool(gate and module in ("COMMIT", "PGMOTP"))))
        plans[operation.row] = UidWritePlan(
            operation.row, operation.row + 2, operation.cp, operation.item, operation.provenance,
            modules, tuple(steps), (operation.row + 1) * 100, profile,
            _run("enter_fbist_mode"), gate.gate_symbol if gate else None,
        )
    return MappingProxyType(plans)


def _identity_values(variant, page):
    overrides = dict(variant.word_overrides)
    return tuple(CommitFieldValue(span.semantic_name,
        RecipeValueToken("HEX", f"0x{(overrides[word] >> (32 - span.msb_index - span.width)) & ((1 << span.width) - 1):08X}"),
        page.program_pattern, page.read_pattern, (span,))
        for word, spans in variant.identity_labels if word in overrides for span in spans)


def _has_prior_uid_value(register, row, flow, catalog):
    fields = catalog.resolve_register(register).fields
    source_rows = [index for index, source in flow.iterrows()
        if str(source.get("UID", "")).strip().casefold() == "yes"
        and index < row
        and str(source.get("CP NO", "")).strip().casefold() != str(flow.iloc[row].get("CP NO", "")).strip().casefold()
        and str(source.get("type", "")).strip().casefold() in ("trim", "verify")
        and any(catalog.matches_trim(str(source.get("CP NO", "")), source.get("item", ""), field)
                or (str(source.get("item", "")) + "_Verify").casefold() == field.name.casefold()
                for field in fields)]
    return bool(source_rows)
