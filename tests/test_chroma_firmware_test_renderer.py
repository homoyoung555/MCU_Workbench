from dataclasses import replace
import unittest
import re

from program_gen.compiler import ProductCompiler
from program_gen.core.firmware_force import ForceVoltageAction, VoltageForcePoint
from program_gen.core.run_sequence import RepowerAction
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.chroma.firmware_test_renderer import (
    ChromaFirmwareRenderError,
    render_firmware_test,
)
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class ChromaFirmwareTestRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plans = tuple(
            cls.compilation.plan.catalogs.firmware_test_plans.values()
        )
        cls.facts = {
            cp: compile_platform_program_facts(
                cls.workbook,
                TargetKey("chroma", cp, "production", f"FW_{cp}"),
            )
            for cp in ("CP1", "CP2", "CP3")
        }

    def test_all_formal_firmware_plans_render_from_typed_facts(self):
        self.assertEqual(len(self.plans), 14)
        for plan in self.plans:
            with self.subTest(cp=plan.cp, item=plan.item):
                rendered = self._render(plan)
                self.assertTrue(rendered.content.endswith("}\n"))
                self.assertEqual(
                    len({item.logical_identity for item in rendered.resources}),
                    len(rendered.resources),
                )
                self.assertEqual(
                    len({item.logical_identity for item in rendered.resource_requires}),
                    len(rendered.resource_requires),
                )

    def test_generated_label_calls_are_closed_over_pattern_resources(self):
        for plan in self.plans:
            rendered = self._render(plan)
            resources = {r.relative_path.removeprefix("pat/").removesuffix(".pat"): r.content.decode("ascii") for r in rendered.resources}
            for start, end in re.findall(r"JUDGE_PAT\(([^,]+),([^)]*)\);", rendered.content):
                if ":" in start:
                    name, label = start.split(":", 1)
                    end_name, end_label = end.split(":", 1)
                    self.assertEqual(name, end_name)
                    self.assertIn("\n" + label + ":\n", resources[name])
                    self.assertIn("\n" + end_label + ":\n", resources[name])

    def test_code_download_is_one_power_session_and_only_requires_external_pattern(self):
        plan = self._plan("CP3", "Download_Code")

        rendered = self._render(plan)

        self.assertEqual(rendered.content.count("POWER_ON(VCC_TYP);"), 1)
        self.assertEqual(rendered.content.count("POWER_OFF();"), 1)
        self.assertIn(
            "JUDGE_PAT(Intergration_V01_05,__Intergration_V01_05);",
            rendered.content,
        )
        self.assertEqual(rendered.resources, ())
        self.assertEqual(len(rendered.resource_requires), 1)
        requirement = rendered.resource_requires[0]
        self.assertEqual(requirement.relative_path, "pat/Intergration_V01_05.pat")
        self.assertNotIn("STUB", rendered.content.upper())

    def test_function_download_and_keil_phases_each_have_a_complete_session(self):
        plan = self._plan("CP1", "SRAM_CKB_Test")

        rendered = self._render(plan)

        self.assertEqual(rendered.content.count("POWER_ON(VCC_MAX);"), 2)
        self.assertEqual(rendered.content.count("POWER_OFF();"), 2)
        self.assertLess(
            rendered.content.index(
                "JUDGE_PAT(SRAM_V02_06_CKB,__SRAM_V02_06_CKB);"
            ),
            rendered.content.index("Trigger_HL_5mS"),
        )
        self.assertIn("WAIT(500mS);", rendered.content)
        self.assertIn("JUDGE_PAT(PA13_PA11_Compare:HH", rendered.content)
        self.assertTrue(any(
            request.relative_path.endswith("Trigger_HL_5mS.pat")
            for request in rendered.resources
        ))
        self.assertTrue(all(
            len(request.relative_path.rsplit("/", 1)[-1].removesuffix(".pat")) <= 30
            for request in rendered.resources
        ))

    def test_send_code_resource_uses_complete_golden_frame(self):
        rendered = self._render(self._plan("CP3", "Power_Test"))
        send = next(
            request for request in rendered.resources
            if "Trigger_Send" in request.relative_path
        )
        self.assertIn(
            b"*1*RPT 632;\n  *0*RPT 422;\n"
            b"  *1*RPT 422;\n  *0*RPT 422;",
            send.content,
        )
        self.assertIn(b"*0*RPT 502;", send.content)

    def test_power_run_test_uses_one_session_and_resets_between_subs_without_dropping_rail(self):
        plan = self._plan("CP3", "Power_Test")

        rendered = self._render(plan)

        self.assertEqual(rendered.content.count("POWER_ON(VCC_MAX);"), 1)
        self.assertEqual(rendered.content.count("POWER_OFF();"), 1)
        self.assertEqual(
            rendered.content.count(
                "JUDGE_PAT(firmware_dut_reset,__firmware_dut_reset);"
            ),
            2,
        )
        reset = next(
            request for request in rendered.resources
            if request.relative_path == "pat/firmware_dut_reset.pat"
        )
        reset_source = reset.content.decode("ascii")
        self.assertIn("*0*RPT 25000", reset_source)
        self.assertIn("*1*RPT 25000", reset_source)
        self.assertIn("*X*STOP", reset_source)
        reset_positions = [
            index for index in range(len(rendered.content))
            if rendered.content.startswith(
                "JUDGE_PAT(firmware_dut_reset,__firmware_dut_reset);", index
            )
        ]
        for position in reset_positions:
            nearby = rendered.content[max(0, position - 160):position + 160]
            self.assertNotIn("POWER_OFF", nearby)
            self.assertNotIn("0V,@6V", nearby)
        self.assertEqual(rendered.content.count("FORCE_V_MLDPS(VCC4,"), 3)
        self.assertEqual(rendered.content.count("JUDGE_I_MLDPS(VCC4,"), 3)
        self.assertIn("@2.5mA,2.5mA", rendered.content)
        self.assertIn("@250uA,250uA", rendered.content)

    def test_rcc_clock_conflict_keeps_clock_running_during_ppmu_compare_then_stops(self):
        plan = self._plan("CP3", "RCC_Test")

        rendered = self._render(plan)

        self.assertIn("FRUN_CLK(PD0,", rendered.content)
        self.assertIn("FRUN_CLK_MODE(PD0,1,0,ON);", rendered.content)
        self.assertIn("JUDGE_PAT(firmware_pc14_clkloop", rendered.content)
        self.assertIn("JUDGE_V_PPMU(PA13,", rendered.content)
        self.assertIn("JUDGE_V_PPMU(PA14,", rendered.content)
        judge = rendered.content.index("JUDGE_V_PPMU(PA14,")
        stop_pattern = rendered.content.index("PAT_CONTINUE();")
        stop_tmu = rendered.content.index("FRUN_CLK_MODE(PD0,1,0,OFF);")
        self.assertLess(judge, stop_pattern)
        self.assertLess(stop_pattern, stop_tmu)
        self.assertTrue(any(
            request.relative_path == "pat/firmware_pc14_clkloop.pat"
            for request in rendered.resources
        ))
        self.assertNotIn("compare_hh", rendered.content)

    def test_rtc_has_the_same_clock_force_compare_cleanup_order(self):
        rendered = self._render(self._plan("CP3", "RTC_Test"))
        self.assertLess(
            rendered.content.index("FRUN_CLK_MODE(PD0,1,0,ON);"),
            rendered.content.index("JUDGE_V_PPMU(PA13,"),
        )
        self.assertLess(
            rendered.content.index("JUDGE_V_PPMU(PA14,"),
            rendered.content.index("PAT_CONTINUE();"),
        )

    def test_voltage_force_is_rendered_from_typed_action_without_reading_flow(self):
        base = self._plan("CP1", "PWR_CP1_Test")
        phase = base.phases[1]
        forced = ForceVoltageAction((VoltageForcePoint("PA7", "1.2"),))
        phase = replace(phase, actions=(forced, *phase.actions))
        plan = replace(
            base,
            phases=(base.phases[0], phase),
            execution_steps=(base.phases[0], phase),
        )

        rendered = self._render(plan)

        self.assertIn("RELAY_ON(PA7,PPMU_PDCL,2mS);", rendered.content)
        self.assertIn("FORCE_V_PPMU(PA7,1.2V,,@32mA,,2mS);", rendered.content)
        self.assertIn("FORCE_V_PPMU(PA7,0V,,@32mA,,2mS);", rendered.content)
        self.assertIn("RELAY_OFF(PA7,PPMU_PDCL,2mS);", rendered.content)

    def test_unsupported_typed_action_fails_stably_instead_of_being_skipped(self):
        base = self._plan("CP1", "PWR_CP1_Test")
        phase = base.phases[1]
        phase = replace(phase, actions=(RepowerAction(),))
        plan = replace(
            base,
            phases=(base.phases[0], phase),
            execution_steps=(base.phases[0], phase),
        )

        with self.assertRaises(ChromaFirmwareRenderError) as raised:
            self._render(plan)

        self.assertEqual(raised.exception.code, "FW.CHROMA.ACTION.UNSUPPORTED")
        self.assertIn("RepowerAction", str(raised.exception))

    def _plan(self, cp, item):
        return next(
            plan for plan in self.plans if plan.cp == cp and plan.item == item
        )

    def _render(self, plan):
        return render_firmware_test(
            plan,
            f"Firmware_{plan.cp}_{plan.item}",
            "9",
            self.facts[plan.cp],
        )


if __name__ == "__main__":
    unittest.main()
