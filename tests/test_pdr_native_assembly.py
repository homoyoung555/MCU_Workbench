"""PDR_TRIM native typed-kind assembly through the public Skeleton V2 seam."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.pdr_trim_assembly import compile_pdr_trim_assembly
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.platform_program.facts import PinBinding
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class PdrTrimNativeAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = next(iter(cls.compilation.plan.catalogs.dedicated_trim_plans.values()))

    def test_empty_plan_set_is_safe_and_does_not_create_support(self):
        target = TargetKey("chroma", "CP2", "lab", "PDR_EMPTY_CP2")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma")

        assembly = compile_pdr_trim_assembly(
            (), TypedKindContext(self.compilation, target, facts, producer)
        )

        self.assertEqual(assembly.typed_kind, "PDR_TRIM")
        self.assertEqual(assembly.contributions, ())
        self.assertEqual(assembly.bodies, ())

    def test_nonempty_relay_must_be_declared_by_platform_facts(self):
        target = TargetKey("s100", "CP1", "lab", "PDR_RELAY_MISSING_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100")

        with self.assertRaisesRegex(ValueError, "PDR.RELAY.UNDECLARED"):
            compile_pdr_trim_assembly(
                (replace(self.plan, relay="UR_PDR"),),
                TypedKindContext(self.compilation, target, facts, producer),
            )

    def test_s100_relay_closes_body_and_project_resource_contract(self):
        target = TargetKey("s100", "CP1", "lab", "PDR_RELAY_S100_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        relay = PinBinding(
            "UR_PDR", "relay",
            max(pin.pin_no for pin in facts.pins) + 1,
            ("150",),
        )
        facts = replace(
            facts,
            pins=(*facts.pins, relay),
            relay_pins=(*facts.relay_pins, relay),
        )
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100")
        assembly = compile_pdr_trim_assembly(
            (replace(self.plan, relay="UR_PDR"),),
            TypedKindContext(self.compilation, target, facts, producer),
        )

        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
        ))
        source = render_plan.artifact(f"{target.program_name}.prg").content.decode("gbk")
        project = render_plan.artifact(f"{target.program_name}.prj").content.decode("gbk")
        self.assertIn(
            "IO_CLOSE_USER_RELAY(UR_PDR,CONNECT_MODE,ALL_SITE_ON,WAIT=1MS)",
            source,
        )
        self.assertIn(
            "IO_CLOSE_USER_RELAY(UR_PDR,DISCONNECT_MODE,ALL_SITE_ON,WAIT=1MS)",
            source,
        )
        self.assertIn("150;", project)
        self.assertIn('UR_PDR,["150"];', project)

    def test_native_pdr_modules_do_not_import_workbook_global_or_legacy_writers(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = (
            ".dataframe(",
            "program_gen import state",
            "platforms.chroma.writers",
            "platforms.s100.writers",
            "golden",
        )
        for relative_path in (
            "program_gen/pdr_trim_assembly.py",
            "program_gen/pdr_trim_support.py",
            "program_gen/core/pdr_contribution.py",
            "program_gen/platforms/chroma/pdr_trim_renderer.py",
            "program_gen/platforms/s100/pdr_trim_renderer.py",
        ):
            with self.subTest(path=relative_path):
                source = (root / relative_path).read_text(encoding="utf-8").casefold()
                for token in forbidden:
                    self.assertNotIn(token.casefold(), source)

    def test_chroma_plan_builds_closed_native_program_without_workbook_input(self):
        target = TargetKey("chroma", "CP1", "lab", "PDR_NATIVE_CHROMA_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma")
        assembly = compile_pdr_trim_assembly(
            (self.plan,),
            TypedKindContext(self.compilation, target, facts, producer),
        )

        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
            runtime_declarations=(
                self.compilation.for_cp("CP1").runtime_state.declarations
            ),
        ))

        source = render_plan.artifact(f"{target.program_name}.pln").content.decode("gbk")
        self.assertIn("Pdr_Trim()", source)
        self.assertEqual(
            len(re.findall(r"\bPDR_DAC_FINAL\s*\[MAX_SITE\]\s*(?:[,;])", source)),
            1,
        )
        self.assertIn(f"TEST_NUM={self.plan.test_number};", source)
        self.assertIn("VOLTAGE VCC_PDR_TAR = 2.37V;", source)
        self.assertIn("set_pdr_trim_data(int* a)", source)
        self.assertIn("WRITE_PAT_MEM(SOCKET,PA13,set_pdr_dac:a_data", source)
        startup = source.index("START_UP()\r\n{")
        startup_end = source.index("}\r\n\r\n", startup)
        for role in ("MIN", "TAR", "MAX"):
            self.assertEqual(
                source[startup:startup_end].count(f"SET_LEVELN(PDR_{role}_LVL"),
                2,
            )
        self.assertNotIn("ensure_pdr_trim_levels", source)
        self.assertNotIn("PDR_LEVELS_READY", source)
        self.assertEqual(
            tuple(
                artifact.relative_path
                for artifact in render_plan.artifacts
                if artifact.relative_path.endswith(".pat")
            ),
            (
                "pat/enter_fbist_mode.pat",
                "pat/exit_fbist_mode.pat",
                "pat/read_status_mode.pat",
                "pat/set_all_final_vposp.pat",
                "pat/set_pdr_dac.pat",
            ),
        )

    def test_s100_plan_builds_closed_native_program_without_workbook_input(self):
        target = TargetKey("s100", "CP1", "lab", "PDR_NATIVE_S100_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100")
        assembly = compile_pdr_trim_assembly(
            (self.plan,),
            TypedKindContext(self.compilation, target, facts, producer),
        )

        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
            runtime_declarations=(
                self.compilation.for_cp("CP1").runtime_state.declarations
            ),
        ))

        source = render_plan.artifact(f"{target.program_name}.prg").content.decode("gbk")
        self.assertIn("@@PLAN Pdr_Trim", source)
        self.assertIn("CALL_MACRO POWER_ON(_C_VCC_TYP);", source)
        self.assertIn("double _C_VCC_PDR_TAR = 2.37;", source)
        self.assertIn("@@MACRO set_pdr_trim_data(int* a)", source)
        self.assertEqual(
            len(re.findall(r"\bPDR_DAC_FINAL\s*\[MAX_SITE\]\s*(?:[,;])", source)),
            1,
        )
        self.assertIn(
            "LOGIC_WRITE_PATTERN_MEMORY(set_pdr_dac:a_data_st,"
            "set_pdr_dac:a_data_sp,PA13,GB1,BIT_COUNT=4,SERIAL,MSB_LSB)",
            source,
        )
        self.assertIn(
            "RUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END,1,TS_5MHZ)",
            source,
        )
        self.assertEqual(
            tuple(
                artifact.relative_path
                for artifact in render_plan.artifacts
                if artifact.relative_path.endswith(".sd")
            ),
            (
                "enter_fbist_mode.sd",
                "exit_fbist_mode.sd",
                "read_status_mode.sd",
                "set_all_final_vposp.sd",
                "set_pdr_dac.sd",
            ),
        )


if __name__ == "__main__":
    unittest.main()
