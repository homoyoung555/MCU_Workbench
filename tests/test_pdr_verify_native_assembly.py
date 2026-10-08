"""PDR_VERIFY native assembly through the public Skeleton V2 seam."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.pdr_verify_assembly import compile_pdr_verify_assembly
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


class PdrVerifyNativeAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_empty_plan_set_is_safe_and_does_not_create_support(self):
        target = TargetKey("chroma", "CP1", "lab", "PDR_VERIFY_EMPTY_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma")

        assembly = compile_pdr_verify_assembly(
            (), TypedKindContext(self.compilation, target, facts, producer)
        )

        self.assertEqual(assembly.typed_kind, "PDR_VERIFY")
        self.assertEqual(assembly.contributions, ())
        self.assertEqual(assembly.bodies, ())

    def test_chroma_plan_builds_closed_program_with_pdr_levels_in_startup(self):
        target = TargetKey("chroma", "CP1", "lab", "PDR_VERIFY_CHROMA_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma")
        plan = next(iter(
            self.compilation.plan.catalogs.pdr_verify_plans["chroma"].values()
        ))

        assembly = compile_pdr_verify_assembly(
            (plan,), TypedKindContext(self.compilation, target, facts, producer)
        )
        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
        ))

        source = render_plan.artifact(f"{target.program_name}.pln").content.decode("gbk")
        startup = source.index("START_UP()\r\n{")
        startup_end = source.index("}\r\n\r\n", startup)
        self.assertIn("SET_LEVELN(PDR_MAX_LVL", source[startup:startup_end])
        self.assertIn("Pdr_Verify()", source)
        self.assertEqual(
            tuple(
                artifact.relative_path
                for artifact in render_plan.artifacts
                if artifact.relative_path.endswith(".pat")
            ),
            (
                "pat/enter_fbist_mode.pat",
                "pat/enter_pdr_verify.pat",
                "pat/exit_fbist_mode.pat",
                "pat/read_status_mode.pat",
            ),
        )

    def test_cp2_chroma_uses_min_and_max_levels_without_target(self):
        target = TargetKey("chroma", "CP2", "lab", "PDR_VERIFY_CHROMA_CP2")
        source, _render_plan = self._build(target)

        self.assertIn("int PDR_MIN_LVL = 6;", source)
        self.assertIn("int PDR_MAX_LVL = 7;", source)
        self.assertNotIn("PDR_TAR_LVL", source)
        startup = source.index("START_UP()\r\n{")
        startup_end = source.index("}\r\n\r\n", startup)
        self.assertEqual(source[startup:startup_end].count("SET_LEVELN(PDR_"), 4)

    def test_s100_plan_builds_closed_program_with_three_patterns(self):
        target = TargetKey("s100", "CP1", "lab", "PDR_VERIFY_S100_CP1")
        source, render_plan = self._build(target)

        self.assertIn("@@PLAN Pdr_Verify", source)
        self.assertIn("double _C_VCC_PDR_TAR = 2.37;", source)
        self.assertEqual(
            tuple(
                artifact.relative_path
                for artifact in render_plan.artifacts
                if artifact.relative_path.endswith(".sd")
            ),
            (
                "enter_fbist_mode.sd",
                "enter_pdr_verify.sd",
                "read_status_mode.sd",
            ),
        )

    def test_nonempty_relay_must_be_declared_by_platform_facts(self):
        target = TargetKey("s100", "CP1", "lab", "PDR_VERIFY_RELAY_MISSING")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100")
        plan = self._plan("s100", "CP1")

        with self.assertRaisesRegex(ValueError, "PDR_VERIFY.RELAY.UNDECLARED"):
            compile_pdr_verify_assembly(
                (replace(plan, relay="UR_PDR_VERIFY"),),
                TypedKindContext(self.compilation, target, facts, producer),
            )

    def test_s100_relay_closes_body_and_project_resource_contract(self):
        target = TargetKey("s100", "CP1", "lab", "PDR_VERIFY_RELAY_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        relay = PinBinding(
            "UR_PDR_VERIFY", "relay",
            max(pin.pin_no for pin in facts.pins) + 1,
            ("150",),
        )
        facts = replace(
            facts,
            pins=(*facts.pins, relay),
            relay_pins=(*facts.relay_pins, relay),
        )
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100")
        plan = replace(self._plan("s100", "CP1"), relay="UR_PDR_VERIFY")
        assembly = compile_pdr_verify_assembly(
            (plan,), TypedKindContext(self.compilation, target, facts, producer)
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
            "IO_CLOSE_USER_RELAY(UR_PDR_VERIFY,CONNECT_MODE,ALL_SITE_ON,WAIT=1MS)",
            source,
        )
        self.assertIn(
            "IO_CLOSE_USER_RELAY(UR_PDR_VERIFY,DISCONNECT_MODE,ALL_SITE_ON,WAIT=1MS)",
            source,
        )
        self.assertIn('UR_PDR_VERIFY,["150"];', project)

    def test_native_modules_do_not_read_workbook_or_legacy_writers(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = (
            ".dataframe(",
            "program_gen import state",
            "platforms.chroma.writers",
            "platforms.s100.writers",
            "golden",
        )
        for relative_path in (
            "program_gen/pdr_verify_assembly.py",
            "program_gen/pdr_voltage_support.py",
            "program_gen/core/pdr_verify_contribution.py",
            "program_gen/platforms/chroma/pdr_verify_renderer.py",
            "program_gen/platforms/s100/pdr_verify_renderer.py",
        ):
            with self.subTest(path=relative_path):
                source = (root / relative_path).read_text(encoding="utf-8").casefold()
                for token in forbidden:
                    self.assertNotIn(token.casefold(), source)

    def _plan(self, platform: str, cp: str):
        return next(
            plan
            for plan in self.compilation.plan.catalogs.pdr_verify_plans[
                platform
            ].values()
            if plan.cp == cp
        )

    def _build(self, target):
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(
            WORKSPACE_ROOT / "input" / target.platform.casefold()
        )
        assembly = compile_pdr_verify_assembly(
            (self._plan(target.platform.casefold(), target.cp),),
            TypedKindContext(self.compilation, target, facts, producer),
        )
        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp(target.cp).canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
        ))
        extension = ".pln" if target.platform.casefold() == "chroma" else ".prg"
        source = render_plan.artifact(
            f"{target.program_name}{extension}"
        ).content.decode("gbk")
        return source, render_plan


if __name__ == "__main__":
    unittest.main()
