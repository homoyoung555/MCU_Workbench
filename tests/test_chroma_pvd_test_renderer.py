from dataclasses import replace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.run_sequence import LevelSequenceAction, RepowerAction, SendCodeAction
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.chroma.pvd_test_renderer import (
    ChromaPvdRenderError,
    render_pvd_test,
)
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class ChromaPvdTestRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        compilation = ProductCompiler().compile(workbook).require_success()
        cls.plan = next(iter(compilation.plan.catalogs.pvd_test_plans.values()))
        cls.facts = compile_platform_program_facts(
            workbook,
            TargetKey("chroma", cls.plan.cp, "production", "PVD_CP3"),
        )

    def test_formal_plan_uses_one_runtime_loop_with_independent_sessions(self):
        rendered = self._render()
        body = rendered.content

        self.assertIn("for(int item=0;item<7;item++)", body)
        self.assertEqual(body.count("POWER_ON(VCC_MAX);"), 1)
        self.assertEqual(body.count("POWER_OFF();"), 1)
        self.assertEqual(body.count("POWER_Shmoo_ON("), 4)
        self.assertIn("int pvd_snd[7]={1,2,3,4,5,6,7};", body)
        self.assertIn(
            'sprintf(snd_st,"Trigger_Send:S%02X_ST",pvd_snd[item]);',
            body,
        )
        self.assertIn('sprintf(snd_sp,"Trigger_Send:S%02X_SP",pvd_snd[item]);', body)
        self.assertNotIn("NRST", body)
        self.assertEqual(rendered.resource_requires, ())
        self.assertEqual(len(rendered.resources), 3)
        self.assertEqual(
            len({resource.logical_identity for resource in rendered.resources}),
            len(rendered.resources),
        )
        self.assertTrue(all(
            b"STUB" not in resource.content.upper()
            for resource in rendered.resources
        ))

    def test_loop_data_and_body_preserve_case_point_order(self):
        rendered = self._render().content
        voltage_rows = ",".join(
            "{" + ",".join(f"{point.voltage:.12g}" for point in case.points) + "}"
            for case in self.plan.cases
        )
        self.assertIn(f"double pvd_v[7][4]={{{voltage_rows}}};", rendered)
        self.assertIn('char pvd_case[7][2]={"1","2","3","4","5","6","7"};', rendered)

        expected = (
            "POWER_ON(VCC_MAX);",
            "Trigger_HL_5mS",
            "Trigger_Send:SDE_ST",
            "Trigger_Send:S0F_ST",
            'sprintf(snd_st,"Trigger_Send:S%02X_ST",pvd_snd[item]);',
            "POWER_Shmoo_ON(pvd_v[item][0]);",
            "PA13_PA14_Compare:LL_ST",
            "POWER_Shmoo_ON(pvd_v[item][1]);",
            "PA13_PA14_Compare:HH_ST",
            "POWER_Shmoo_ON(pvd_v[item][2]);",
            "PA13_PA14_Compare:HH_ST",
            "POWER_Shmoo_ON(pvd_v[item][3]);",
            "PA13_PA14_Compare:LL_ST",
            "POWER_OFF();",
        )
        cursor = 0
        positions = []
        for token in expected:
            cursor = rendered.index(token, cursor)
            positions.append(cursor)
            cursor += len(token)
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            'sprintf(pvd_log,"PVD:%s:1:LL",pvd_case[item]);', rendered
        )

    def test_generated_patterns_are_real_and_hl_uses_five_milliseconds_per_segment(self):
        rendered = self._render()
        level = next(
            resource for resource in rendered.resources
            if resource.relative_path.endswith("Trigger_HL_5mS.pat")
        )
        compare = next(
            resource for resource in rendered.resources
            if resource.relative_path.endswith("PA13_PA14_Compare.pat")
        )
        send = next(
            resource for resource in rendered.resources
            if resource.relative_path.endswith("Trigger_Send.pat")
        )

        self.assertIn(b"*1*RPT 25000", level.content)
        self.assertIn(b"*0*RPT 25000", level.content)
        self.assertIn(b"*HH*RPT 100", compare.content)
        self.assertIn(b"PA13,PA14;", compare.content)
        self.assertIn(
            b"*1*RPT 632;\n  *0*RPT 422;\n"
            b"  *1*RPT 422;\n  *0*RPT 422;",
            send.content,
        )
        self.assertIn(b"*0*RPT 502;", send.content)
        self.assertTrue(all(
            len(resource.relative_path.rsplit("/", 1)[-1].removesuffix(".pat")) <= 30
            for resource in rendered.resources
        ))

    def test_platform_cp_and_pin_contracts_fail_with_stable_codes(self):
        with self.assertRaises(ChromaPvdRenderError) as platform_error:
            render_pvd_test(
                self.plan,
                "Pvd_Test",
                9,
                replace(self.facts, platform="s100"),
            )
        self.assertEqual(
            platform_error.exception.code,
            "PVD.CHROMA.FACTS.PLATFORM_MISMATCH",
        )

        with self.assertRaises(ChromaPvdRenderError) as cp_error:
            render_pvd_test(
                self.plan,
                "Pvd_Test",
                9,
                replace(self.facts, cp="CP2"),
            )
        self.assertEqual(cp_error.exception.code, "PVD.CHROMA.FACTS.CP_MISMATCH")

        missing = replace(
            self.facts,
            pins=tuple(pin for pin in self.facts.pins if pin.name != "PA14"),
        )
        with self.assertRaises(ChromaPvdRenderError) as pin_error:
            render_pvd_test(self.plan, "Pvd_Test", 9, missing)
        self.assertEqual(pin_error.exception.code, "PVD.CHROMA.PIN.UNDECLARED")

    def test_unsupported_action_and_non_five_ms_level_fail_stably(self):
        case = replace(self.plan.cases[0], entry_actions=(RepowerAction(),))
        with self.assertRaises(ChromaPvdRenderError) as unsupported:
            self._render(replace(self.plan, cases=(case, *self.plan.cases[1:])))
        self.assertEqual(
            unsupported.exception.code,
            "PVD.CHROMA.ACTION.UNSUPPORTED",
        )

        case = replace(
            self.plan.cases[0],
            entry_actions=(LevelSequenceAction("PA0", "HL", 1_000_000),),
        )
        with self.assertRaises(ChromaPvdRenderError) as timing:
            self._render(replace(self.plan, cases=(case, *self.plan.cases[1:])))
        self.assertEqual(
            timing.exception.code,
            "PVD.CHROMA.LEVEL.PROFILE_UNSUPPORTED",
        )

    def test_loop_rejects_mixed_explicit_pin_naming(self):
        case = self.plan.cases[1]
        actions = list(case.entry_actions)
        index = next(i for i, action in enumerate(actions) if isinstance(action, SendCodeAction))
        actions[index] = replace(actions[index], explicit_pin=True)
        changed = replace(case, entry_actions=tuple(actions))
        with self.assertRaises(ChromaPvdRenderError) as error:
            self._render(replace(self.plan, cases=(self.plan.cases[0], changed, *self.plan.cases[2:])))
        self.assertEqual(error.exception.code, "PVD.CHROMA.CASE.ACTION_SHAPE_MISMATCH")

    def _render(self, plan=None):
        return render_pvd_test(
            plan or self.plan,
            "Pvd_Test",
            9,
            self.facts,
        )


if __name__ == "__main__":
    unittest.main()
