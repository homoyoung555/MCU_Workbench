"""OS family native-renderer slice: resolve → body → section → planner.

Second family migrated onto the ``PlatformRenderPlanner`` registry template.
Proves the PDR_VERIFY seam is reusable: a different business plan, a different
render context, the same fan-out/assembly/golden contract.
"""

from __future__ import annotations

from tests.workspace_paths import (
    CHROMA_GOLDEN_ROOT,
    CHROMA_SEED_ROOT,
    FORMAL_MASTER as EXTERNAL_FORMAL_MASTER,
    S100_GOLDEN_ROOT,
    S100_SEED_ROOT,
    WORKSPACE_ROOT,
)

from pathlib import Path
from dataclasses import replace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.os_assembly import compile_os_assembly
from program_gen.platform_render import (
    PlatformRenderPlanner,
    resolve_os_context,
    resolve_pin_dec,
)
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.platform_program.facts import PinBinding
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
CHROMA_GOLDEN = (
    CHROMA_GOLDEN_ROOT / "LAB" / "CHROMA"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1.pln"
)
S100_GOLDEN = (
    S100_GOLDEN_ROOT / "LAB" / "S100"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1.prg"
)


def _read_gbk(path: Path) -> list[str]:
    return path.read_bytes().decode("gbk", errors="replace").splitlines()


def _golden_os_body() -> list[str]:
    lines = _read_gbk(CHROMA_GOLDEN)
    start = next(i for i, l in enumerate(lines) if l.strip() == "Os_Test()")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return lines[start:end + 1]


def _golden_s100_os_body() -> list[str]:
    lines = _read_gbk(S100_GOLDEN)
    start = next(i for i, l in enumerate(lines) if l.strip() == "@@PLAN Os_Test")
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "@@END_PLAN")
    return lines[start:end + 1]


class OsRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.lab_pin_dec = resolve_pin_dec(cls.workbook, "lab", "chroma")

    def _plan(self, cp: str = "CP1"):
        return next(
            plan
            for plan in self.compilation.plan.catalogs.os_plans["chroma"].values()
            if plan.cp == cp
        )

    def test_resolve_pin_dec_projects_lab_single_site(self):
        context = resolve_os_context(self.lab_pin_dec, "CP1")
        self.assertEqual(context.power_pins, ("VCC4",))
        self.assertTrue(context.kp_relay)
        # single-site lab: only even site S0, odd group empty
        self.assertEqual(
            context.site_groups,
            (((0,), "F0/S0"), ((), "F1/S1")),
        )

    def test_chroma_os_body_matches_golden_byte_for_byte(self):
        from program_gen.platforms.chroma.os_renderer import render_os_body

        plan = self._plan()
        context = resolve_os_context(self.lab_pin_dec, "CP1")
        body = render_os_body(
            plan, context=context, test_number=(plan.row + 1) * 100
        )
        self.assertEqual(body.splitlines(), _golden_os_body())

    def test_chroma_named_relay_wraps_the_complete_os_body(self):
        from program_gen.platforms.chroma.os_renderer import render_os_body

        plan = replace(self._plan(), relay="UR_OS")
        body = render_os_body(
            plan,
            context=resolve_os_context(self.lab_pin_dec, "CP1"),
            test_number=(plan.row + 1) * 100,
        )

        self.assertTrue(body.startswith(
            "Os_Test()\n{\n  SET_CBIT(UR_OS, ON, 5mS);\n"
        ))
        self.assertTrue(body.endswith(
            "  SET_CBIT(UR_OS, OFF, 5mS);\n}\n"
        ))

    def test_planner_registers_os_and_renders_its_body(self):
        planner = PlatformRenderPlanner(
            section_order=("HEADER", "GLOBALS", "STARTUP", "TESTS", "FLOW"),
            seed_root=CHROMA_SEED_ROOT,
        )
        self.assertEqual(
            planner.families,
            ("pdr_verify", "os", "pdr_trim", "standard_trim"),
        )

        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
        render_plan = planner.plan(self.compilation, target, self.workbook)

        content = render_plan.artifact("V_TEST_CP1.pln").content.decode()
        self.assertIn("\n".join(_golden_os_body()), content)
        # PDR_VERIFY also still renders alongside OS in the same plan.
        self.assertIn("Pdr_Verify()", content)

    def test_s100_os_body_matches_golden_byte_for_byte(self):
        from program_gen.platforms.s100.os_renderer import render_os_body

        s100_pin = resolve_pin_dec(self.workbook, "lab", "s100")
        plan = next(
            plan
            for plan in self.compilation.plan.catalogs.os_plans["s100"].values()
            if plan.cp == "CP1"
        )
        context = resolve_os_context(s100_pin, "CP1")
        schedule = self.compilation.for_cp("CP1").canonical_schedule
        definition = next(
            d for d in schedule.definitions if d.item.casefold() == "os_test"
        )
        entry = next(
            e for e in schedule.entries if e.definition_id == definition.identity
        )
        body = render_os_body(
            plan,
            power_pins=context.power_pins,
            reject_bin=entry.bin_binding.hardware_bin,
        )
        self.assertEqual(body.splitlines(), _golden_s100_os_body())

    def test_s100_named_relay_wraps_the_os_actions(self):
        from program_gen.platforms.s100.os_renderer import render_os_body

        plan = next(
            plan
            for plan in self.compilation.plan.catalogs.os_plans["s100"].values()
            if plan.cp == "CP1"
        )
        plan = replace(plan, relay="UR_OS")
        schedule = self.compilation.for_cp("CP1").canonical_schedule
        definition = next(
            definition
            for definition in schedule.definitions
            if definition.item.casefold() == "os_test"
        )
        entry = next(
            entry
            for entry in schedule.entries
            if entry.definition_id == definition.identity
        )
        body = render_os_body(
            plan,
            power_pins=("VCC4",),
            reject_bin=entry.bin_binding.hardware_bin,
        )

        relay_connect = (
            "\tIO_CLOSE_USER_RELAY(UR_OS,CONNECT_MODE,ALL_SITE_ON,WAIT=1MS);"
        )
        relay_disconnect = (
            "\tIO_CLOSE_USER_RELAY(UR_OS,DISCONNECT_MODE,ALL_SITE_ON,WAIT=1MS);"
        )
        self.assertNotIn("SET_CBIT(UR_OS", body)
        self.assertLess(
            body.index(relay_connect),
            body.index("\tCALL_MACRO test_start();"),
        )
        self.assertLess(
            body.rindex("\tWAIT(5mS);"),
            body.index(relay_disconnect),
        )
        self.assertLess(
            body.index(relay_disconnect),
            body.index("\tCONDITION"),
        )

    def test_os_assembly_rejects_a_relay_missing_from_target_facts(self):
        target = TargetKey("chroma", "CP1", "lab", "OS_RELAY_UNDECLARED")
        facts = compile_platform_program_facts(self.workbook, target)
        plan = replace(self._plan(), relay="UR_OS")

        with self.assertRaisesRegex(ValueError, "OS.RELAY.UNDECLARED"):
            compile_os_assembly(
                (plan,),
                TypedKindContext(
                    self.compilation, target, facts, pattern_producer=None
                ),
            )

    def test_os_assembly_consumes_declared_relay_in_both_platform_artifacts(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP1", "lab", f"OS_RELAY_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                relay = PinBinding(
                    "UR_OS",
                    "relay",
                    max(pin.pin_no for pin in facts.pins) + 1,
                    tuple("150" for _ in range(facts.site_count)),
                )
                facts = replace(
                    facts,
                    pins=(*facts.pins, relay),
                    relay_pins=(relay,),
                )
                plan = next(
                    plan
                    for plan in self.compilation.plan.catalogs.os_plans[
                        platform
                    ].values()
                    if plan.cp == "CP1"
                )
                plan = replace(plan, relay="UR_OS")
                producer = WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / platform
                )
                assembly = compile_os_assembly(
                    (plan,),
                    TypedKindContext(
                        self.compilation, target, facts, producer
                    ),
                )
                render_plan = PlatformProgramBuilder(producer).build(
                    ProgramAssemblyInput(
                        target=target,
                        platform_facts=facts,
                        canonical_schedule=self.compilation.for_cp(
                            "CP1"
                        ).canonical_schedule,
                        contributions=assembly.contributions,
                        bodies=assembly.bodies,
                    )
                )
                extension = "pln" if platform == "chroma" else "prg"
                source = render_plan.artifact(
                    f"{target.program_name}.{extension}"
                ).content.decode("gbk")
                if platform == "chroma":
                    self.assertIn("SET_CBIT(UR_OS, ON, 5mS);", source)
                    self.assertIn("SET_CBIT(UR_OS, OFF, 5mS);", source)
                else:
                    self.assertIn(
                        "IO_CLOSE_USER_RELAY(UR_OS,CONNECT_MODE,"
                        "ALL_SITE_ON,WAIT=1MS);",
                        source,
                    )
                    self.assertIn(
                        "IO_CLOSE_USER_RELAY(UR_OS,DISCONNECT_MODE,"
                        "ALL_SITE_ON,WAIT=1MS);",
                        source,
                    )
                    self.assertNotIn("SET_CBIT(UR_OS", source)

    def test_planner_renders_s100_os_body(self):
        planner = PlatformRenderPlanner(
            section_order=("HEADER", "GLOBALS", "TESTS", "FLOW"),
            seed_root=S100_SEED_ROOT,
        )
        s100_pin = resolve_pin_dec(self.workbook, "lab", "s100")
        target = TargetKey("s100", "CP1", "lab", "V_TEST_CP1")
        render_plan = planner.plan(self.compilation, target, self.workbook)
        content = render_plan.artifact("V_TEST_CP1.prg").content.decode()
        self.assertIn("\n".join(_golden_s100_os_body()), content)


if __name__ == "__main__":
    unittest.main()
