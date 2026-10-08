"""S100 Adapters for shared ENTER and JUDGE plans."""

from program_gen.core.verify_modules import (
    EnterPlan,
    JudgeMeasurementKind,
    JudgePlan,
)
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


def adapt_enter(plan: EnterPlan) -> RecipeModuleEmission:
    name = plan.pattern.name
    return RecipeModuleEmission(
        statements=(
            f"\tRUN_PATTERN({name}:START,{name}:END,1,{plan.timing_profile});",
            "",
        ),
        resource_requires=(ResourceRequirement(
            plan.pattern.logical_identity,
            f"{name}.sd",
            f"v13.pattern/1:s100:{name}",
            "ENTER Pattern",
        ),),
    )


def adapt_judge(plan: JudgePlan) -> RecipeModuleEmission:
    fact = plan.measurement
    if fact.kind is JudgeMeasurementKind.FREQUENCY:
        thresholds = "0.8V, 0.3V" if fact.pin == "TP" else "2V, 2V"
        force_lines = (
            f"\tLOGIC_SET_CMP_LEVEL({fact.pin}, {thresholds}, VR1);",
            "\tWAIT(3MS);",
            f"\tLOGIC_TMU_STARTPIN({fact.pin}, VOH, POS);",
            f"\tLOGIC_TMU_STOPPIN({fact.pin}, VOL, POS);",
        )
        measure_lines = (
            "\tLOGIC_TMU_SET_AND_START(CMD_TRIG, NULL, AVG=128, HYS_ON);",
            "\tWAIT(3MS);",
        )
    else:
        operation = "MV" if fact.kind is JudgeMeasurementKind.VOLTAGE else "MI"
        force_operation = "FI" if operation == "MV" else "FV"
        level_separator = ", " if operation == "MV" else ",  "
        force_lines = (
            f"\tLOGIC_PPMU_{force_operation}({fact.pin}, {fact.force}"
            f"{level_separator}E1, I1);",
            "\tWAIT(3MS);",
        )
        measure_lines = ()
    if plan.dac_final is None:
        if fact.kind is JudgeMeasurementKind.FREQUENCY:
            judge_line = (
                f"\tLOGIC_TMU_MEAS_FREQ(DOWN_LIMIT={_num(fact.low_limit)}{fact.unit}, "
                f"UP_LIMIT={_num(fact.high_limit)}{fact.unit},TIME_OUT={fact.settle}, "
                f"LOG_ALIAS={fact.alias}, LOG_UNIT={fact.unit});"
            )
        else:
            judge_line = (
                f"\tLOGIC_PPMU_{operation}({fact.pin}, "
                f"DOWN_LIMIT={_num(fact.low_limit)}{fact.unit}, "
                f"UP_LIMIT={_num(fact.high_limit)}{fact.unit}, MEAS_LOOP=8, AVG, "
                f"LOG_ALIAS={fact.alias}, LOG_UNIT={fact.unit});"
            )
        lines = (*force_lines, *measure_lines, judge_line)
    else:
        dac = plan.dac_final
        if fact.kind is JudgeMeasurementKind.FREQUENCY:
            measurement = (
                f"\tLOGIC_TMU_MEAS_FREQ(TIME_OUT={fact.settle});",
                f"\tC_ASSIGN(GB3,{fact.pin});",
                "\tC_DIV(GB3, 1000);",
            )
        else:
            measurement_lines = [
                f"\tLOGIC_PPMU_{operation}({fact.pin}, MEAS_LOOP=8, AVG);",
                f"\tC_ASSIGN(GB3,{fact.pin});",
            ]
            if fact.kind is JudgeMeasurementKind.CURRENT:
                measurement_lines.append("\tC_MUL(GB3,1000000);")
            measurement = tuple(measurement_lines)
        measurement_gap = ("",) if fact.kind is not JudgeMeasurementKind.VOLTAGE else ()
        lines = (
            *force_lines,
            *measure_lines,
            *measurement,
            *measurement_gap,
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
            "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
            "\t\ttrimFinalValue[T_SOCKET]=GB[2+T_SOCKET*64];",
            "\t}",
            "",
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
            f"\t\tGB[4+T_SOCKET*64]={dac.symbol}[T_SOCKET];",
            "\t\tGB[2+T_SOCKET*64]=trimFinalValue[T_SOCKET];",
            "\t}",
            "",
            f"\tC_COMPARE(GB5,DOWN_LIMIT=0, UP_LIMIT={dac.max_code}, "
            f"LOG_ALIAS= {dac.alias});",
            "",
            f"\tC_COMPARE(GB3, DOWN_LIMIT={_num(fact.low_limit)}, "
            f"UP_LIMIT={_num(fact.high_limit)}, LOG_ALIAS={fact.alias}, "
            f"LOG_UNIT={fact.unit});",
        )
    return RecipeModuleEmission(statements=lines)


def _num(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


__all__ = ["adapt_enter", "adapt_judge"]
