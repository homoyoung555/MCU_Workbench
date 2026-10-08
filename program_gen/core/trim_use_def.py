"""Validate CP-local Trim DAC_FINAL producers against declared consumers."""

from program_gen.core.logical_item import logical_dac_final_symbol


class TrimDacUseDefError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def validate_trim_dac_use_def(
    flow_frame,
    recipe_rows,
    flash_window_plans,
    persistence_plans,
) -> None:
    page_consumers = []
    for row, plan in flash_window_plans.items():
        symbols = frozenset(
            write.symbol
            for step in plan.steps
            if step.module == "BUILDMAP"
            for register in step.module_plan.registers
            for write in register.writes
        )
        page_consumers.append((plan.cp.casefold(), row, symbols))
    for row, plan in persistence_plans.rows.items():
        symbols = frozenset(
            write.value.token
            for operation in plan.operations
            if operation.module == "COMMIT"
            for write in operation.field_writes
            if write.value.kind == "VARIABLE"
        )
        page_consumers.append((plan.cp.casefold(), row, symbols))

    set_vposp_rows = frozenset(
        (row_plan.flow.cp.casefold(), row)
        for row, row_plan in recipe_rows.items()
        if any(call.name == "SETVPOSP" for call in row_plan.operations)
    )
    for row, record in flow_frame.iterrows():
        if str(record.get("type", "")).strip().casefold() != "trim":
            continue
        cp = str(record.get("CP NO", "")).strip().casefold()
        item = str(record.get("item", "")).strip()
        symbol = logical_dac_final_symbol(item)
        page_required = _yes(record.get("OTP")) or _yes(record.get("UID"))
        pump_required = _yes(record.get("PUMP"))
        if page_required and not any(
            consumer_cp == cp and consumer_row > row and symbol in symbols
            for consumer_cp, consumer_row, symbols in page_consumers
        ):
            raise TrimDacUseDefError(
                "TRIM.USE_DEF.PAGE_IMAGE_UNCONSUMED",
                f"FLOW row {row + 2} {record.get('CP NO')}/{item} "
                "declares OTP/UID but has no later BUILDMAP/COMMIT consumer",
            )
        if pump_required and not any(
            consumer_cp == cp and consumer_row > row
            for consumer_cp, consumer_row in set_vposp_rows
        ):
            raise TrimDacUseDefError(
                "TRIM.USE_DEF.SETVPOSP_UNCONSUMED",
                f"FLOW row {row + 2} {record.get('CP NO')}/{item} "
                "declares PUMP but has no later SETVPOSP consumer",
            )


def _yes(value) -> bool:
    return str(value).strip().casefold() == "yes"


__all__ = ["TrimDacUseDefError", "validate_trim_dac_use_def"]
