"""Compile Recipe-driven trim rows into a small writer-facing interface."""

from dataclasses import dataclass
import re
from typing import Dict, Optional, Tuple

import pandas as pd

from flow_recipe import (
    FlowCompileError,
    RecipeDuration,
    compile_recipe_program,
    parse_recipe,
)
from program_gen.core.logical_item import logical_dac_final_symbol, logical_item_name


class TrimRecipeError(ValueError):
    """A migrated trim row cannot be represented by the trim writer seam."""


@dataclass(frozen=True)
class TrimRecipeOperation:
    name: str
    pattern_name: Optional[str] = None
    value_source: Optional[str] = None
    value: Optional[str] = None
    default_value: Optional[str] = None
    field_width: Optional[int] = None
    wait: Optional[RecipeDuration] = None
    force_wait: Optional[RecipeDuration] = None
    set_wait: Optional[RecipeDuration] = None


@dataclass(frozen=True)
class TrimRecipePlan:
    flow_row_index: int
    cp: str
    item: str
    mode: str
    operations: Tuple[TrimRecipeOperation, ...]
    dac_final_symbol: str


def compile_trim_recipe_plans(
    flow_frame: pd.DataFrame,
    pattern_frame: pd.DataFrame,
) -> Dict[int, TrimRecipePlan]:
    """Return migrated trim plans keyed by the FLOW dataframe row index.

    Blank Recipe rows are intentionally excluded during the staged V1.3
    migration.  They continue through the legacy writer until their workbook
    rows are migrated.
    """
    if "Recipe" not in flow_frame.columns:
        return {}
    recipe_text = flow_frame["Recipe"].fillna("").astype(str).str.strip()
    migrated = flow_frame.loc[recipe_text.ne("")]
    if migrated.empty:
        return {}

    try:
        program = compile_recipe_program(migrated, pattern_frame)
    except FlowCompileError as exc:
        raise TrimRecipeError(str(exc)) from exc

    plans = {}
    for function in program.functions:
        if function.key.flow_type != "trim":
            for executable_row in function.rows:
                if any(
                    operation.time_parameter(name) is not None
                    for operation in executable_row.operations
                    for name in ("WAIT", "FWAIT", "SWAIT")
                ):
                    raise TrimRecipeError(
                        f"FLOW row {executable_row.flow.excel_row}: "
                        "Verify adapter 尚未接入 Recipe 时间参数"
                    )
            continue
        for executable_row in function.rows:
            resolved_operations = executable_row.operations
            names = [operation.name for operation in resolved_operations]
            enter_count = 0
            while enter_count < len(names) and names[enter_count] in ("ENTER", "RUN"):
                enter_count += 1
            dependency_end = enter_count
            while (
                dependency_end < len(names)
                and names[dependency_end] == "DEPEND"
            ):
                dependency_end += 1
            tail = names[dependency_end:]
            if tail and tail[-1] == "EXPORT":
                tail = tail[:-1]
            if "ENTER" not in names[:enter_count] or tail not in (
                ["TRIM", "JUDGE"],
                ["TRIM", "DAC_ADJ", "JUDGE"],
            ):
                raise TrimRecipeError(
                    f"FLOW row {executable_row.flow.excel_row}: type=trim 当前必须使用 "
                    "ENTER-[DEPEND]-TRIM-[DAC_ADJ]-JUDGE"
                )

            operations = []
            for operation in resolved_operations:
                if operation.name == "ENTER":
                    operations.append(
                        TrimRecipeOperation(
                            name="ENTER",
                            pattern_name=operation.pattern_name or recipe_pattern_name(
                                executable_row.flow.item, operation.pattern_role
                            ),
                            value_source=operation.value_source,
                            value=operation.value,
                            default_value=(operation.dynamic_field.value
                                           if operation.dynamic_field is not None else None),
                            field_width=(operation.dynamic_field.width
                                         if operation.dynamic_field is not None else None),
                            wait=operation.time_parameter("WAIT"),
                        )
                    )
                elif operation.name == "DEPEND":
                    if operation.dynamic_field is None:
                        raise TrimRecipeError(
                            f"FLOW row {executable_row.flow.excel_row}: "
                            "DEPEND 缺少目标 DAC Pattern 字段"
                        )
                    operations.append(
                        TrimRecipeOperation(
                            name="DEPEND",
                            pattern_name=recipe_pattern_name(
                                operation.value, operation.pattern_role
                            ),
                            value_source=operation.value_source,
                            value=operation.value,
                            default_value=operation.dynamic_field.value,
                            field_width=operation.dynamic_field.width,
                        )
                    )
                elif operation.name == "RUN":
                    operations.append(
                        TrimRecipeOperation(
                            name="RUN",
                            pattern_name=operation.value,
                            value_source=operation.value_source,
                            value=operation.value,
                        )
                    )
                elif operation.name == "TRIM":
                    if operation.dynamic_field is None:
                        raise TrimRecipeError(
                            f"FLOW row {executable_row.flow.excel_row}: TRIM 缺少动态 Pattern 字段"
                        )
                    operations.append(
                        TrimRecipeOperation(
                            name="TRIM",
                            pattern_name=operation.pattern_name or recipe_pattern_name(
                                executable_row.flow.item, operation.pattern_role
                            ),
                            value_source=operation.value_source,
                            default_value=operation.dynamic_field.value,
                            field_width=operation.dynamic_field.width,
                            force_wait=operation.time_parameter("FWAIT"),
                            set_wait=operation.time_parameter("SWAIT"),
                        )
                    )
                elif operation.name == "DAC_ADJ":
                    if operation.dynamic_field is None:
                        raise TrimRecipeError(
                            f"FLOW row {executable_row.flow.excel_row}: "
                            "DAC_ADJ 缺少动态 Pattern 字段"
                        )
                    operations.append(
                        TrimRecipeOperation(
                            name="DAC_ADJ",
                            pattern_name=operation.pattern_name or recipe_pattern_name(
                                executable_row.flow.item, operation.pattern_role
                            ),
                            value_source=operation.value_source,
                            value=operation.value,
                            default_value=operation.dynamic_field.value,
                            field_width=operation.dynamic_field.width,
                            force_wait=operation.time_parameter("FWAIT"),
                            set_wait=operation.time_parameter("SWAIT"),
                        )
                    )
                elif operation.name == "JUDGE":
                    if operation.dynamic_field is None:
                        raise TrimRecipeError(
                            f"FLOW row {executable_row.flow.excel_row}: "
                            "JUDGE 缺少最终 DAC Pattern 字段"
                        )
                    operations.append(
                        TrimRecipeOperation(
                            name="JUDGE",
                            pattern_name=operation.pattern_name or recipe_pattern_name(
                                executable_row.flow.item, operation.pattern_role
                            ),
                            value_source=operation.value_source,
                            default_value=operation.dynamic_field.value,
                            field_width=operation.dynamic_field.width,
                            force_wait=operation.time_parameter("FWAIT"),
                            set_wait=operation.time_parameter("SWAIT"),
                        )
                    )
                else:
                    operations.append(
                        TrimRecipeOperation(
                            name=operation.name,
                            force_wait=operation.time_parameter("FWAIT"),
                        )
                    )

            item = executable_row.flow.item
            row_index = executable_row.flow.excel_row - 2
            plans[row_index] = TrimRecipePlan(
                flow_row_index=row_index,
                cp=str(executable_row.flow.cp).strip(),
                item=item,
                mode=executable_row.flow.mode,
                operations=tuple(operations),
                dac_final_symbol=dac_final_symbol(item),
            )
    return plans


def dynamic_enter_operations(
    plans: Dict[int, TrimRecipePlan],
    current_cp: Optional[str],
) -> Tuple[TrimRecipeOperation, ...]:
    """Return one helper specification per parameterized ENTER pattern for a CP."""
    selected = {}
    for plan in plans.values():
        if current_cp is not None and plan.cp != str(current_cp).strip():
            continue
        for operation in plan.operations:
            if operation.name != "ENTER" or operation.value_source != "ARGUMENT":
                continue
            previous = selected.get(operation.pattern_name)
            if previous is not None and (
                previous.default_value != operation.default_value
                or previous.field_width != operation.field_width
            ):
                raise TrimRecipeError(
                    f"pattern {operation.pattern_name!r} 的动态 ENTER 字段定义不一致"
                )
            selected.setdefault(operation.pattern_name, operation)
    return tuple(selected.values())


def recipe_pattern_name(item: str, role: str) -> str:
    """Give each explicit Pattern role a stable, collision-free file name."""
    slug = _item_slug(item)
    if role == "trim mode":
        return f"enter_{slug}"
    if role == "trim dac":
        return f"set_{slug}_dac"
    if role == "verify mode":
        return f"enter_{slug}" if slug.endswith("_verify") else f"enter_{slug}_verify"
    raise TrimRecipeError(f"item {item!r} 不支持 pattern role {role!r}")


def pattern_output_name(item: str, role: str, description: str) -> str:
    """Resolve legacy Pattern rows whose item/role pair is not unique.

    PT088 has two ``Bor_Trim`` DAC groups: the trim flow writes BOR_TRIM,
    while BOR Verify sweeps BOR_OPCR. They must not be merged into one file.
    """
    name = recipe_pattern_name(item, role)
    if (
        name == "set_bor_dac"
        and role == "trim dac"
        and re.search(r"\bBOR_OPCR(?:\s*\[|\s*=)", str(description), re.IGNORECASE)
    ):
        return "set_bor_verify_dac"
    return name


def dac_final_symbol(item: str) -> str:
    return logical_dac_final_symbol(item)


def trim_data_helper_name(item: str) -> str:
    """Return the existing cross-platform helper/macro name for one DAC pattern."""
    pattern_name = recipe_pattern_name(item, "trim dac")
    return pattern_name.removesuffix("dac") + "trim_data"


def generated_flow_item_name(flow_frame: pd.DataFrame, row_index: int) -> str:
    """Return the generated function identity during staged Recipe migration."""
    record = flow_frame.iloc[row_index]
    item = str(record["item"]).strip()
    recipe_value = record.get("Recipe")
    recipe = "" if pd.isna(recipe_value) else str(recipe_value).strip()
    flow_type = str(record["type"]).strip().lower()
    if recipe and any(
        call.named_parameter("SHMOO") == "STEP"
        for call in parse_recipe(recipe)
    ) and not item.lower().endswith("shmoo"):
        return item + "_Shmoo"
    if recipe and flow_type == "trim" and not item.lower().endswith("trim"):
        return item + "_Trim"
    mode_value = record.get("mode")
    mode = "" if pd.isna(mode_value) else str(mode_value).strip().lower()
    if mode == "fbist" and flow_type == "verify" and not item.lower().endswith("verify"):
        return item + "_Verify"
    if mode == "fbist" and flow_type == "shmoo" and not item.lower().endswith("shmoo"):
        return item + "_Shmoo"
    return item


def _item_slug(item: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", logical_item_name(item)).strip("_").lower()
    if not slug:
        raise TrimRecipeError("item 不能生成空名称")
    return slug
