from __future__ import annotations

import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program.facts import (
    PinBinding,
    PinGroupFacts,
    PlatformProgramFacts,
)
from program_gen.platforms.s100.pvd_test_renderer import render_pvd_test
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class S100PvdTestRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        cls.plan = next(iter(compilation.plan.catalogs.pvd_test_plans.values()))

    def test_formal_seven_cases_use_one_runtime_loop_with_independent_sessions(self):
        rendered = render_pvd_test(
            self.plan, "Pvd_Test", 12, _facts(self.plan.cp)
        )
        body = rendered.content

        self.assertEqual(body.count("CALL_MACRO POWER_ON(_C_VCC_MAX);"), 1)
        self.assertEqual(body.count("CALL_MACRO POWER_OFF();"), 1)
        self.assertIn("for(int item=0;item<7;item++)", body)
        self.assertIn("int pvd_snd[7]={1,2,3,4,5,6,7};", body)
        self.assertIn("REJECT_BIN = 12;", body)

        self.assertEqual(body.count("LOGIC_FORCE_DPS(VCC4,"), 28)
        online_adjust = (
            "LOGIC_FORCE_DPS(VCC4, 2.87V, 500MA, I7, WAIT=0.5MS);"
        )
        self.assertIn(online_adjust, body)
        self.assertIn(
            "LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 2.87V, 0.0V, 0.0V, VR1);",
            body,
        )
        self.assertIn(
            "LOGIC_SET_CMP_LEVEL(IO_ALLPINS, 1.5785V, 1.2915V, VR2);",
            body,
        )
        self.assertNotIn("pvd_v[item]", body)
        first_power = body.index("CALL_MACRO POWER_ON(_C_VCC_MAX);")
        entry = body.index("RUN_PATTERN(Trigger_HL_5mS:START", first_power)
        adjust = body.index(online_adjust, entry)
        compare = body.index("RUN_PATTERN(PA13_PA14_Compare:LL", adjust)
        power_off = body.index("CALL_MACRO POWER_OFF();", compare)
        self.assertLess(first_power, entry)
        self.assertLess(entry, adjust)
        self.assertLess(adjust, compare)
        self.assertLess(compare, power_off)
        self.assertIn(
            'sprintf(_C_snd_st,"Trigger_Send:S%02X_ST",pvd_snd[item]);',
            body,
        )

        self.assertIn(
            'sprintf(_C_snd_sp,"Trigger_Send:S%02X_SP",pvd_snd[item]);',
            body,
        )

    def test_resources_are_real_deduplicated_sd_without_requirements(self):
        rendered = render_pvd_test(
            self.plan, "Pvd_Test", "12", _facts(self.plan.cp)
        )

        self.assertEqual(rendered.resource_requires, ())
        self.assertEqual(len(rendered.resources), 3)
        self.assertEqual(
            len({resource.logical_identity for resource in rendered.resources}),
            3,
        )
        self.assertTrue(all(
            resource.relative_path.endswith(".sd")
            and b"STUB" not in resource.content.upper()
            for resource in rendered.resources
        ))
        level = next(
            resource for resource in rendered.resources
            if resource.relative_path == "Trigger_HL_5mS.sd"
        )
        self.assertEqual(level.content.count(b"RPT 25000"), 2)


def _facts(cp: str) -> PlatformProgramFacts:
    nrst = PinBinding("NRST", "io", 1, ("1",))
    groups = PinGroupFacts((nrst,), (nrst,), ())
    return PlatformProgramFacts(
        platform="s100",
        cp=cp,
        site_count=1,
        pins=(nrst,),
        pin_groups=groups,
        io_pins=("NRST", "PA0", "PA13", "PA14"),
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
