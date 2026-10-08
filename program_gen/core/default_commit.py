"""Compile no-argument COMMIT defaults from FLOW ownership columns.

The module deliberately resolves only named ADDR_MAP label fields.  Fixed UID
manufacturing/ID flags belong to BUILDUID/ID plans and are not guessed here.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from flow_recipe import (
    ExecutableFlowRow, FlowCompileError, RecipeAssignment, RecipeValueToken,
)
from program_gen.core.addr_map import AddrMapCatalog
from program_gen.core.logical_item import logical_dac_final_symbol, logical_item_name
from program_gen.core.result_use_def import parse_dac_adj_consumer


def compile_default_commit_bindings(
    flow_frame: pd.DataFrame,
    rows: Mapping[int, ExecutableFlowRow],
    catalog: AddrMapCatalog,
    *,
    export_symbols: Mapping[int, str] | None = None,
) -> dict[int, tuple[RecipeAssignment, ...]]:
    """Return caller-supplied defaults for each naked COMMIT FLOW row.

    Defaults follow the agreed node ownership:
    Trimdata_Write consumes preceding Trim OTP values; Trimdata_Rewrite consumes
    preceding Verify OTP values; a normal Pgm_*ID_Read consumes preceding UID
    exports.  BakeID and BUILDUID fixed fields stay in their dedicated plans.
    """
    exports = dict(export_symbols or {})
    result: dict[int, tuple[RecipeAssignment, ...]] = {}
    for row_index, executable in rows.items():
        if not any(call.name == "COMMIT" and not call.assignments
                   for call in executable.operations):
            continue
        record = flow_frame.loc[row_index]
        cp = str(record.get("CP NO", "")).strip()
        item = str(record.get("item", "")).strip()
        item_key = item.casefold()
        flow_type = str(record.get("type", "")).strip().casefold()
        if flow_type == "adjust":
            adjustments = tuple(
                parse_dac_adj_consumer(call.value, row_index)
                for call in executable.operations
                if call.name == "DAC_ADJ"
            )
            if len(adjustments) != 1 or adjustments[0] is None:
                raise FlowCompileError(
                    f"FLOW row {row_index + 2}: type=adjust 的裸 COMMIT "
                    "需要且只允许一个 DAC_ADJ"
                )
            target = adjustments[0].target_item
            fields = tuple(
                field for field in (catalog.selected_storage_fields("trim", target)
                                    if catalog.has_trim_storage_mapping(target)
                                    else catalog.fields)
                if field.register_layout.applies_to(cp) and catalog.matches_trim(cp, target, field)
            )
            if not catalog.has_trim_storage_mapping(target):
                fields = tuple(field for field in fields if field.page.casefold() != "uid")
                if len(fields) != 1:
                    raise FlowCompileError(
                        f"FLOW row {row_index + 2}: 调整目标 {target!r} 必须映射到唯一的当前 CP 非 UID Trim 字段"
                    )
            if not fields:
                raise FlowCompileError(
                    f"FLOW row {row_index + 2}: 调整目标 {target!r} 没有当前 CP 适用的 Trim 存储字段"
                )
            result[row_index] = tuple(
                RecipeAssignment(
                    field=name,
                    value=RecipeValueToken(
                        "VARIABLE", logical_dac_final_symbol(target)
                    ),
                )
                for name in dict.fromkeys(catalog.storage_field_reference(field, exact=True)
                                          if catalog.has_trim_storage_mapping(target) else field.name
                                          for field in fields)
            )
            continue
        if item_key == "trimdata_write":
            source_type, destination = "trim", "OTP"
        elif item_key == "trimdata_rewrite":
            source_type, destination = "verify", "OTP"
        elif flow_type == "uid" and "bakeid" not in item_key:
            source_type, destination = None, "UID"
        else:
            result[row_index] = ()
            continue

        assignments = []
        seen = set()
        for source_index, source in flow_frame.iterrows():
            if source_index >= row_index:
                break
            if str(source.get("CP NO", "")).strip() != cp:
                continue
            actual_type = str(source.get("type", "")).strip().casefold()
            if actual_type not in ("trim", "verify"):
                continue
            if source_type is not None and actual_type != source_type:
                continue
            column = "UID" if destination == "UID" else "OTP"
            if str(source.get(column, "")).strip().casefold() != "yes":
                continue
            fields = _source_fields(source, actual_type, catalog, destination, cp)
            if not fields:
                continue
            if actual_type == "trim":
                value_symbol = logical_dac_final_symbol(source.get("item", ""))
            else:
                try:
                    value_symbol = exports[source_index]
                except KeyError as error:
                    raise FlowCompileError(
                        f"FLOW row {source_index + 2}: 持久化 Verify 缺少上游 "
                        "Result EXPORT symbol"
                    ) from error
            for field in fields:
                key = (field.page.casefold(), field.register.casefold(), field.lsb, field.width)
                if key in seen:
                    continue
                seen.add(key)
                assignments.append(RecipeAssignment(
                    field=catalog.storage_field_reference(
                        field,
                        exact=(actual_type == "trim" and catalog.has_trim_storage_mapping(source.get("item", "")))
                        or (actual_type == "verify" and catalog.has_verify_storage_mapping(source.get("item", ""))),
                    ),
                    value=RecipeValueToken("VARIABLE", value_symbol),
                ))
        result[row_index] = tuple(assignments)
    return result


def _source_fields(source, flow_type: str, catalog: AddrMapCatalog, destination: str, cp: str):
    item = logical_item_name(source.get("item", ""))
    if flow_type == "trim":
        candidates = catalog.selected_storage_fields("trim", item)
        fields = tuple(field for field in (candidates if candidates is not None else catalog.fields)
                       if catalog.matches_trim(cp, item, field))
    else:
        candidates = catalog.selected_storage_fields("verify", item)
        fields = tuple(field for field in (candidates if candidates is not None else catalog.fields)
                       if catalog.matches_verify(cp, item, field))
    if destination == "UID":
        return tuple(field for field in fields if field.page.casefold() == "uid")
    if ((flow_type == "trim" and catalog.has_trim_storage_mapping(item))
            or (flow_type == "verify" and catalog.has_verify_storage_mapping(item))):
        return fields
    return tuple(field for field in fields if field.page.casefold() != "uid")
