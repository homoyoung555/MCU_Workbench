from __future__ import annotations

import unittest

from flow_recipe import ResolvedRecipeCall
from program_gen.compiler import ProductCompiler
from program_gen.core.firmware_force import (
    ClockForceAction,
    ClockSignal,
    ClockStopAction,
    ForceVoltageAction,
    SupplyForceAction,
    VoltageForcePoint,
)
from program_gen.core.firmware_judge import (
    DigitalCompareJudgePlan,
    ScalarMeasurementJudgePlan,
)
from program_gen.core.firmware_test import (
    DownloadPhase,
    DutResetAction,
    FirmwareTestPlan,
    KeilPhase,
)
from program_gen.core.run_pattern import PatternResourceRef
from program_gen.core.run_sequence import (
    ForceStopAction,
    LevelSequenceAction,
    SendCodeAction,
    WaitAction,
)
from program_gen.core.verify_modules import JudgeMeasurementKind
from program_gen.diagnostics import WorkbookProvenance
from program_gen.platform_program.facts import (
    PinBinding,
    PinGroupFacts,
    PlatformProgramFacts,
)
from program_gen.platforms.s100.firmware_test_renderer import (
    S100FirmwareRenderError,
    render_firmware_test,
    generate_send_code_resource,
    generate_digital_compare_resource,
)
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class S100FirmwareTestRendererTests(unittest.TestCase):
    def test_send_and_compare_resources_share_all_labels(self):
        first = generate_send_code_resource(SendCodeAction("PA0", 1))
        self.assertEqual(first, generate_send_code_resource(SendCodeAction("PA0", 255)))
        self.assertEqual(first.relative_path, "Trigger_Send.sd")
        for value in range(256):
            self.assertIn(f"S{value:02X}_ST:X;".encode(), first.content)
            self.assertIn(f"S{value:02X}_SP:X;".encode(), first.content)
        from dataclasses import replace
        judge = _digital_judge("PVD")
        compare = generate_digital_compare_resource(judge)
        self.assertEqual(compare, generate_digital_compare_resource(replace(judge, expected=("L", "H"), sub="ADC")))
        self.assertEqual(compare.relative_path, "PA13_PA11_Compare.sd")
        for state in ("HH", "HL", "LH", "LL"):
            self.assertIn(f"{state}_ST:XX;".encode(), compare.content)
            self.assertIn(f"{state}_SP:XX;".encode(), compare.content)

    def test_explicit_pin_prefix_and_label_calls_match_generated_sections(self):
        phase = _keil(actions=(
            LevelSequenceAction("PA13", "HL", 5_000_000, explicit_pin=True),
            SendCodeAction("PA0", 1, explicit_pin=True),
            SendCodeAction("PA0", 2, explicit_pin=True),
        ))
        plan = FirmwareTestPlan("CP3", "Direct", "FIRMWARE_RUN_TEST", (phase,), (phase,))
        rendered = render_firmware_test(plan, "Direct", 4, _facts("CP3"))
        self.assertEqual(len(rendered.resources), 3)
        self.assertIn("PA13_Trigger_HL_5mS:START,PA13_Trigger_HL_5mS:END", rendered.content)
        for value in (1, 2):
            self.assertIn(f"PA0_Trigger_Send:S{value:02X}_ST,PA0_Trigger_Send:S{value:02X}_SP", rendered.content)
        send = next(r for r in rendered.resources if r.relative_path == "PA0_Trigger_Send.sd")
        section = send.content.decode().split("S01_ST:X;", 1)[1].split("S01_SP:X;", 1)[0]
        self.assertEqual(section.count("RPT 422;"), 11)
        self.assertIn("X;RPT 100;", section)
        self.assertIn("1;RPT 632;", section)
        self.assertIn("0;RPT 502;", section)

    def test_code_download_and_function_test_keep_required_session_boundaries(self):
        download = _download()
        code_download = FirmwareTestPlan(
            "CP3", "Download_Code", "CODE_DOWNLOAD", (download,), (download,)
        )

        rendered = render_firmware_test(
            code_download, "Download_Code", "9", _facts("CP3")
        )

        self.assertEqual(rendered.content.count("CALL_MACRO POWER_ON"), 1)
        self.assertEqual(rendered.content.count("CALL_MACRO POWER_OFF"), 1)
        self.assertIn("REJECT_BIN = 9;", rendered.content)
        self.assertIn(
            "RUN_PATTERN(firmware_download:START,firmware_download:END,1,TS_5MHZ);",
            rendered.content,
        )
        self.assertEqual(rendered.resources, ())
        self.assertEqual(len(rendered.resource_requires), 1)
        self.assertEqual(
            rendered.resource_requires[0].relative_path, "firmware_download.sd"
        )

        keil = _keil(
            actions=(WaitAction(5),),
            judge=_digital_judge("run"),
        )
        function = FirmwareTestPlan(
            "CP3",
            "Function",
            "FIRMWARE_FUNCTION_TEST",
            (download, keil),
            (download, keil),
        )
        body = render_firmware_test(function, "Function", 7, _facts("CP3")).content
        self.assertEqual(body.count("CALL_MACRO POWER_ON"), 2)
        self.assertEqual(body.count("CALL_MACRO POWER_OFF"), 2)
        self.assertLess(
            body.index("firmware_download:START"), body.index("WAIT(5MS)")
        )

    def test_run_test_keeps_one_power_session_and_resets_only_at_sub_boundary(self):
        first = _keil(
            sub="stop0",
            actions=(
                SupplyForceAction("VCC4", "VCC_MAX", 2400, "uA"),
                WaitAction(100),
            ),
            judge=_current_judge("stop0", 0.5, 1700),
        )
        second = _keil(
            row=2,
            sub="standby",
            actions=(SupplyForceAction("VCC4", "VCC_MAX", 28, "uA"),),
            judge=_current_judge("standby", 0.5, 28),
        )
        plan = FirmwareTestPlan(
            "CP3",
            "Power_Test",
            "FIRMWARE_RUN_TEST",
            (first, second),
            (first, DutResetAction(), second),
        )

        rendered = render_firmware_test(
            plan, "Power_Test", 9, _facts("CP3")
        )
        body = rendered.content

        self.assertEqual(body.count("CALL_MACRO POWER_ON"), 1)
        self.assertEqual(body.count("CALL_MACRO POWER_OFF"), 1)
        self.assertEqual(body.count("LOGIC_FORCE_DPS(VCC4"), 2)
        self.assertEqual(body.count("LOGIC_DPS_MI(VCC4"), 2)
        self.assertEqual(body.count("RUN_PATTERN(dut_reset:START"), 1)
        self.assertLess(body.index("LOG_ALIAS=STOP0"), body.index("dut_reset:START"))
        self.assertLess(body.index("dut_reset:START"), body.index("28UA"))
        reset = next(
            resource
            for resource in rendered.resources
            if resource.logical_identity == "pattern:dut_reset"
        )
        self.assertIn(b"0;RPT 25000;// low 5ms", reset.content)
        self.assertIn(b"1;RPT 25000;// high 5ms", reset.content)
        self.assertNotIn("POWER_OFF", body[body.index("LOG_ALIAS=STOP0"):body.index("28UA")])

    def test_level_send_wait_and_voltage_force_emit_real_typed_actions(self):
        phase = _keil(
            actions=(
                LevelSequenceAction("PA0", "HL", 5_000_000),
                SendCodeAction("PA0", 222),
                WaitAction(200),
                ForceVoltageAction((VoltageForcePoint("PA1", "1.2V"),)),
            ),
            judge=_voltage_judge("PA2", 1.1, 1.3),
        )
        plan = FirmwareTestPlan(
            "CP3", "Direct", "FIRMWARE_RUN_TEST", (phase,), (phase,)
        )

        rendered = render_firmware_test(plan, "Direct", 4, _facts("CP3"))
        body = rendered.content

        self.assertIn("RUN_PATTERN(Trigger_HL_5mS:START", body)
        self.assertIn("RUN_PATTERN(Trigger_Send:SDE_ST", body)
        self.assertIn("WAIT(200MS);", body)
        self.assertIn("LOGIC_PPMU_FV(PA1, 1.2V, E2, I7);", body)
        self.assertIn("LOGIC_PPMU_MV(PA2, DOWN_LIMIT=1.1V", body)
        contents = b"\n".join(resource.content for resource in rendered.resources)
        self.assertIn(b"1;RPT 25000", contents)
        self.assertIn(b"// 0xDE", contents)
        self.assertNotIn(b"STUB", contents)

    def test_mixed_high_and_low_clock_force_closes_group3_sd_sr_and_stops_after_judge(self):
        signals = (
            ClockSignal("PD0", 24_000_000),
            ClockSignal("PC14", 32_768),
        )
        phase = _keil(
            actions=(ClockForceAction(signals), WaitAction(200)),
            judge=_digital_judge("RTC_TEST", pins=("PA13", "PA14")),
            cleanup=(ClockStopAction(signals),),
        )
        plan = FirmwareTestPlan(
            "CP3", "RTC_Test", "FIRMWARE_RUN_TEST", (phase,), (phase,)
        )

        rendered = render_firmware_test(plan, "RTC_Test", 8, _facts("CP3"))
        body = rendered.content

        self.assertIn("LOGIC_SET_FREE_RUN_CLOCK_PIN(PD0,24000000);", body)
        self.assertIn(
            "RUN_PATTERN(pc14_clkloop:START,pc14_clkloop:END,3,TS_FORCE_CLK);",
            body,
        )
        self.assertLess(body.index("PA13_PA14_Compare:HH"), body.index("LOGIC_CLEAR_CONT"))
        self.assertLess(
            body.index("PA13_PA14_Compare:HH"),
            body.index("LOGIC_SET_FREE_RUN_CLOCK_PIN(NULL,24000000)"),
        )
        paths = {resource.relative_path for resource in rendered.resources}
        self.assertTrue({"pc14_clkloop.sd", "Rpc14_clkloop.sr"} <= paths)
        sd = next(r.content for r in rendered.resources if r.relative_path.endswith(".sd"))
        sr = next(r.content for r in rendered.resources if r.relative_path.endswith(".sr"))
        self.assertIn(b"PC14,TRIGPIN,\n\nEND_HEAD", sd)
        self.assertIn(b"PC14,TRIGPIN\n\nEND_HEAD", sr)
        self.assertIn(b"RTN;\n      XX;", sr)

    def test_unsupported_typed_action_fails_with_stable_code(self):
        phase = _keil(
            actions=(ForceStopAction(),),
            judge=_digital_judge("run"),
        )
        plan = FirmwareTestPlan(
            "CP3", "Unsupported", "FIRMWARE_RUN_TEST", (phase,), (phase,)
        )

        with self.assertRaises(S100FirmwareRenderError) as raised:
            render_firmware_test(plan, "Unsupported", 1, _facts("CP3"))

        self.assertEqual(raised.exception.code, "S100.FW.ACTION.UNSUPPORTED")

    def test_all_formal_firmware_plans_render_without_stub_resources(self):
        compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        plans = tuple(compilation.plan.catalogs.firmware_test_plans.values())

        self.assertEqual(len(plans), 14)
        for index, plan in enumerate(plans, start=1):
            with self.subTest(cp=plan.cp, item=plan.item):
                rendered = render_firmware_test(
                    plan, f"Firmware_{index}", index, _facts(plan.cp)
                )
                self.assertNotIn("STUB", rendered.content.upper())
                self.assertTrue(all(
                    b"STUB" not in resource.content.upper()
                    for resource in rendered.resources
                ))


def _download() -> DownloadPhase:
    return DownloadPhase(
        0,
        "download",
        _provenance(0),
        "VCC_TYP",
        PatternResourceRef(
            "firmware_download",
            "firmware-download:firmware_download",
            ("START", "END"),
        ),
    )


def _keil(
    *,
    row: int = 1,
    sub: str = "run",
    actions=(),
    judge=None,
    cleanup=(),
) -> KeilPhase:
    return KeilPhase(
        row,
        sub,
        _provenance(row),
        "VCC_TYP",
        (
            ResolvedRecipeCall("RUN_SEQUENCE", None),
            ResolvedRecipeCall("JUDGE", None),
        ),
        tuple(actions),
        judge or _digital_judge(sub),
        tuple(cleanup),
    )


def _digital_judge(sub: str, *, pins=("PA13", "PA11")):
    return DigitalCompareJudgePlan(
        tuple(pins),
        tuple("H" for _ in pins),
        "/",
        sub,
        _provenance(1),
    )


def _current_judge(sub: str, low: float, high: float):
    return ScalarMeasurementJudgePlan(
        JudgeMeasurementKind.CURRENT,
        "VCC4",
        low,
        high,
        "uA",
        sub,
        _provenance(1),
    )


def _voltage_judge(pin: str, low: float, high: float):
    return ScalarMeasurementJudgePlan(
        JudgeMeasurementKind.VOLTAGE,
        pin,
        low,
        high,
        "V",
        "direct",
        _provenance(1),
    )


def _provenance(row: int) -> WorkbookProvenance:
    return WorkbookProvenance("FLOW", f"A{row + 2}", "wb", "sha")


def _facts(cp: str) -> PlatformProgramFacts:
    nrst = PinBinding("NRST", "io", 1, ("1",))
    groups = PinGroupFacts((nrst,), (nrst,), ())
    return PlatformProgramFacts(
        platform="s100",
        cp=cp,
        site_count=1,
        pins=(nrst,),
        pin_groups=groups,
        io_pins=("NRST", "PA0", "PA1", "PA2", "PA11", "PA13", "PA14", "PC14", "PD0"),
        power_pins=("VCC4",),
        force_rails=("VCC4",),
        relay_pins=(),
        clk_pin="PA0",
        swd_pin="PA13",
        nrst_pin="PF2",
        vcc_min="VCC_MIN",
        vcc_typ="VCC_TYP",
        vcc_max="VCC_MAX",
        erase_time_ms=1,
        program_time_ms=1,
        kp_channel=None,
        page_bytes=256,
        vte_voltage=None,
        vtp_voltage=None,
        vpose_target=None,
        vnege_target=None,
        vposp_target=None,
        vnegp_target=None,
        program_version_token="V00_01",
    )


if __name__ == "__main__":
    unittest.main()
