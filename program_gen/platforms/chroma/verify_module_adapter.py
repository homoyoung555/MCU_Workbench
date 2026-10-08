"""Chroma Adapters for shared ENTER and JUDGE plans."""

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
            "  TEST_NUM++;",
            f'  TEST_NO(TEST_NUM); DATALOG_MSG="{name}";',
            f"  JUDGE_PAT({name},__{name});",
            "",
        ),
        resource_requires=(ResourceRequirement(
            plan.pattern.logical_identity,
            f"pat/{name}.pat",
            f"v13.pattern/1:chroma:{name}",
            "ENTER Pattern",
        ),),
    )


def adapt_judge(plan: JudgePlan) -> RecipeModuleEmission:
    fact = plan.measurement
    lines = []
    if plan.dac_final is not None:
        dac = plan.dac_final
        lines.extend((
            "  TEST_NUM++;",
            f'  TEST_NO(TEST_NUM); DATALOG_MSG="{plan.item.lower()}_trim";',
            "",
            "  SOCKET_INC(FRZ_OFF)",
            "  {",
            f'    JUDGE_VARIABLE(SOCKET,{dac.symbol}[SOCKET],0, '
            f'{dac.max_code}, "{dac.alias}");',
            "  }",
            "",
        ))
    if fact.kind is JudgeMeasurementKind.FREQUENCY:
        lines.append(f"  SET_TFTM_MODE({fact.pin}, SCHMITT_ON);")
        lines.append(f'  DATALOG_MSG="{fact.alias}";')
        lines.append(
            f"  JUDGE_FREQ({fact.pin}, , , ,{_num(fact.low_limit)}{fact.unit}, "
            f"{_num(fact.high_limit)}{fact.unit}, {fact.gate}, , {fact.settle}, );"
        )
    else:
        operation = "V" if fact.kind is JudgeMeasurementKind.VOLTAGE else "I"
        if fact.kind is JudgeMeasurementKind.VOLTAGE:
            lines.append(
                f"  FORCE_I_PPMU({fact.pin}, {fact.force}, @2uA, ,6V, -2V ,3mS);"
            )
        else:
            lines.append(
                f"  FORCE_V_PPMU({fact.pin}, {fact.force}, ,@2uA, , 2mS);"
            )
        lines.append(f'  DATALOG_MSG="{fact.alias}";')
        lines.append(
            f"  JUDGE_{operation}_PPMU({fact.pin}, {_num(fact.low_limit)}{fact.unit}, "
            f"{_num(fact.high_limit)}{fact.unit}, 2mS,16,AVE,{fact.settle},,);"
        )
    return RecipeModuleEmission(statements=tuple(lines))


def _num(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


__all__ = ["adapt_enter", "adapt_judge"]
