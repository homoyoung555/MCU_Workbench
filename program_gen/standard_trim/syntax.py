"""Chroma / S100 platform syntax profiles for STANDARD_TRIM function blocks.

The profiles own the registered platform statement forms (pattern runs, power,
measure/judge/force statements, function headers, search loops).  They are
pure: they consume typed contract facts and return exact statement text.

Timing literals that belong to the platform syntax (e.g. ``WAIT(3MS)`` inside
the S100 frequency force) live here; the recipe-level waits and the measurement
settle (``50mS`` / ``50uS``) come from the typed contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple


@dataclass(frozen=True, slots=True)
class ChromaSyntax:
    """Chroma PLN function-block statement forms (C-like)."""

    platform: str = "chroma"

    def function_header(self, render_name: str) -> str:
        return f"{render_name}()"

    def function_open(self) -> str:
        return "{"

    def function_close(self) -> str:
        return "}"

    def test_num(self, test_number: int) -> str:
        return f"  TEST_NUM={test_number};"

    def datalog_msg(self, message: str, *, test_num: bool = True) -> str:
        if test_num:
            return f'  TEST_NO(TEST_NUM);DATALOG_MSG="{message}";'
        return f'  DATALOG_MSG="{message}";'

    def pattern_run(self, pattern: str) -> Tuple[str, ...]:
        return (
            "  TEST_NUM++;",
            f'  TEST_NO(TEST_NUM); DATALOG_MSG="{pattern}";',
            f"  JUDGE_PAT({pattern},__{pattern});",
            "",
        )

    def power_on(self, rail: str) -> str:
        return f"  POWER_ON({rail});"

    def power_off(self) -> str:
        return "  POWER_OFF();"

    def power_down_fail_comment(self) -> str:
        return "  //POWER_DOWN_FAIL_SITE_X(MODE_B);"

    def relay_on(self, relay: str) -> str:
        return f"  SET_CBIT({relay}, ON, 5mS);"

    def relay_off(self, relay: str) -> str:
        return f"  SET_CBIT({relay}, OFF, 5mS);"

    def frequency_force(self, pin: str) -> str:
        return f"  SET_TFTM_MODE({pin}, SCHMITT_ON);"

    def frequency_release(self, pin: str) -> str:
        return f"  SET_TFTM_MODE({pin}, SCHMITT_OFF);"

    def ppmu_relay_on(self, pin: str) -> str:
        return f"  RELAY_ON({pin},PPMU_PDCL,2mS);"

    def ppmu_release(
        self, pin: str, family: str, requires_reset: bool
    ) -> Tuple[str, ...]:
        lines = []
        if requires_reset:
            if family == "CURRENT":
                lines.append(f"  FORCE_V_PPMU({pin}, 0V, ,@2uA, , 2mS);")
            else:
                lines.append(
                    f"  FORCE_I_PPMU({pin}, 0uA, @2uA, ,6V, -2V ,3mS);"
                )
        lines.append(f"  RELAY_OFF({pin}, PPMU_PDCL, 2mS);")
        return tuple(lines)

    def measurement_force(self, family: str, pin: str, force: str) -> str:
        if family == "FREQUENCY":
            return self.frequency_force(pin)
        if family == "VOLTAGE":
            return f"  FORCE_I_PPMU({pin}, {force}, @2uA, ,6V, -2V ,3mS);"
        if family == "CURRENT":
            return f"  FORCE_V_PPMU({pin}, {force}, ,@2uA, , 2mS);"
        raise ValueError(f"unsupported measurement family {family!r}")

    def measure(self, family: str, pin: str, gate: str, settle: str) -> str:
        if family == "FREQUENCY":
            return self.measure_frequency(pin, gate, settle)
        operation = "V" if family == "VOLTAGE" else "I"
        return f"    MEAS_{operation}_PPMU({pin}, 2mS, 16, AVE, {settle});"

    def result(self, family: str, pin: str) -> str:
        if family == "FREQUENCY":
            return self.result_frequency(pin)
        if family == "VOLTAGE":
            return f"      trimValue[SOCKET] = RESULT_PIN(SOCKET, {pin});"
        return f"      trimValue[SOCKET] = RESULT_PIN(SOCKET, {pin})*1000000; //uA"

    def judge_measurement(
        self, family: str, pin: str, low: float, high: float, unit: str,
        gate: str, settle: str,
    ) -> str:
        if family == "FREQUENCY":
            return self.judge_frequency(pin, low, high, unit, gate, settle)
        operation = "V" if family == "VOLTAGE" else "I"
        return (
            f"  JUDGE_{operation}_PPMU({pin}, {_num(low)}{unit}, {_num(high)}{unit}, "
            f"2mS,16,AVE,{settle},,);"
        )

    def measure_frequency(
        self, pin: str, gate: str, settle: str, indent: str = "    "
    ) -> str:
        return f"{indent}MEAS_FREQ({pin}, , , , {gate}, , {settle}, );"

    def judge_frequency(
        self, pin: str, low: float, high: float, unit: str,
        gate: str, settle: str,
    ) -> str:
        return (
            f"  JUDGE_FREQ({pin}, , , ,{_num(low)}{unit}, {_num(high)}{unit}, "
            f"{gate}, , {settle}, );"
        )

    def judge_variable(
        self, expression: str, low, high, alias: str, indent: str = "      "
    ) -> str:
        return f'{indent}JUDGE_VARIABLE(SOCKET,{expression}, {low}, {high}, "{alias}");'

    def judge_variable(
        self, expression: str, low, high, alias: str,
        indent: str = "      ", quoted: bool = True,
    ) -> str:
        label = f'"{alias}"' if quoted else str(alias)
        return f"{indent}JUDGE_VARIABLE(SOCKET,{expression}, {low}, {high}, {label});"

    def judge_variable_final(
        self, expression: str, low, high, alias: str
    ) -> str:
        return f'    JUDGE_VARIABLE(SOCKET,{expression},{low}, {high}, "{alias}");'

    def result_frequency(self, pin: str) -> str:
        return f"      trimValue[SOCKET] = RESULT_PIN(SOCKET, {pin})/1000; //Khz"

    def helper_call(self, helper: str, argument: str) -> str:
        return f"  {helper}({argument});"

    def helper_call_loop(self, helper: str) -> str:
        return f"    {helper}(trimDac);"

    def socket_inc_open(self) -> str:
        return "    SOCKET_INC(FRZ_OFF)"

    def socket_inc_body_open(self) -> str:
        return "    {"

    def socket_inc_body_close(self) -> str:
        return "    }"


@dataclass(frozen=True, slots=True)
class S100Syntax:
    """S100 ``@@PLAN`` function-block statement forms."""

    platform: str = "s100"

    def plan_header(self, render_name: str) -> Tuple[str, ...]:
        return (
            f"@@PLAN {render_name}",
            "\tSITE_SEQUENCE      = OFF;",
            "\tGO_THROUGH         = ON;",
            "\tDISABLE_BY_MARK_NO = NULL;",
            "\tS_SETUP_FILE       = c:\\set.dat;",
            f"\tREMARK             = {render_name};",
            "",
        )

    def plan_footer(self) -> Tuple[str, ...]:
        return (
            "\tCONDITION",
            "\tIF_FAIL",
            "\tREJECT_BIN = {bin};",
            "@@END_PLAN",
            "",
        )

    def power_on(self, rail: str) -> str:
        return f"\tCALL_MACRO POWER_ON(_C_{rail});"

    def power_off(self) -> str:
        return "\tCALL_MACRO POWER_OFF();"

    def pattern_run_protocol(self, pattern: str) -> str:
        return f"\tRUN_PATTERN({pattern}:START,{pattern}:END,1,TS_5MHZ);"

    def pattern_run_enter(self, pattern: str) -> str:
        return f"\tRUN_PATTERN({pattern}:START,{pattern}:END,1,TS_5MHZ);"

    def pattern_run_depend(self, pattern: str) -> str:
        return f"\tRUN_PATTERN({pattern}:START,{pattern}:END,1,TS_5MHZ);"

    def pattern_run_exit(self, pattern: str) -> str:
        return f"\tRUN_PATTERN({pattern}:START,{pattern}:END,1,TS_5MHZ);"

    def helper_call(self, helper: str, argument: str) -> str:
        return f"\tCALL_MACRO {helper}({argument});"

    def helper_call_loop(self, helper: str) -> str:
        return f"\t\tCALL_MACRO {helper}(trimDac);"

    def frequency_force(self, pin: str) -> Tuple[str, ...]:
        return (
            f"\tLOGIC_SET_CMP_LEVEL({pin}, 0.8V, 0.3V, VR1);",
            "\tWAIT(3MS);",
            f"\tLOGIC_TMU_STARTPIN({pin}, VOH, POS);  // Should use VOH for STARTPIN",
            f"\tLOGIC_TMU_STOPPIN({pin}, VOL, POS);  // Should use VOL for STARTPIN",
        )

    def measurement_force(self, family: str, pin: str, force: str) -> Tuple[str, ...]:
        if family == "FREQUENCY":
            return self.frequency_force(pin)
        if family == "VOLTAGE":
            return (f"\tLOGIC_PPMU_FI({pin}, {force}, E1, I1);", "\tWAIT(3MS);")
        if family == "CURRENT":
            return (f"\tLOGIC_PPMU_FV({pin}, {force},  E1, I1);", "\tWAIT(3MS);")
        raise ValueError(f"unsupported measurement family {family!r}")

    def ppmu_release(
        self, pin: str, family: str, requires_reset: bool
    ) -> Tuple[str, ...]:
        if not requires_reset:
            return ()
        operation = "FV" if family == "CURRENT" else "FI"
        value = "0V" if family == "CURRENT" else "0uA"
        return (f"\tLOGIC_PPMU_{operation}({pin}, {value}, E2, I5);",)

    def measurement(self, family: str, pin: str, settle: str, *, indent: str) -> Tuple[str, ...]:
        if family == "FREQUENCY":
            return (*self.frequency_measure(settle, indent=indent),
                    self.assign_result(pin).replace("\t\t", indent, 1),
                    self.divide_result().replace("\t\t", indent, 1))
        operation = "MV" if family == "VOLTAGE" else "MI"
        lines = [
            f"{indent}LOGIC_PPMU_{operation}({pin}, MEAS_LOOP=8, AVG);",
            f"{indent}C_ASSIGN(GB3,{pin});",
        ]
        if family == "CURRENT":
            lines.append(f"{indent}C_MUL(GB3,1000000);")
        return tuple(lines)

    def frequency_measure(self, settle: str, indent: str = "\t\t") -> Tuple[str, ...]:
        return (
            f"{indent}LOGIC_TMU_SET_AND_START(CMD_TRIG, NULL, AVG=128, HYS_ON);",
            f"{indent}WAIT(3MS);",
            f"{indent}LOGIC_TMU_MEAS_FREQ(TIME_OUT={settle});",
        )

    def assign_result(self, pin: str) -> str:
        return f"\t\tC_ASSIGN(GB3,{pin});"

    def divide_result(self) -> str:
        return "\t\tC_DIV(GB3, 1000);"

    def assign_result_final(self, pin: str) -> str:
        return f"\tC_ASSIGN(GB3,{pin});"

    def divide_result_final(self) -> str:
        return "\tC_DIV(GB3, 1000);"

    def compare_dac_final(self, max_code: int, alias: str) -> str:
        return (
            f"\tC_COMPARE(GB5,DOWN_LIMIT=0, UP_LIMIT={max_code}, "
            f"LOG_ALIAS= {alias});"
        )

    def compare_value_final(self, low: float, high: float, unit: str, alias: str) -> str:
        return (
            f"\tC_COMPARE(GB3, DOWN_LIMIT={_num(low)}, UP_LIMIT={_num(high)}, "
            f"LOG_ALIAS={alias}, LOG_UNIT={unit});"
        )

    def compare_value_point(self, log_alias: str, unit: str) -> str:
        return f"\tC_COMPARE(GB3, LOG_ALIAS={log_alias}, LOG_UNIT={unit});"


def _num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


__all__ = ["ChromaSyntax", "S100Syntax", "_num"]
