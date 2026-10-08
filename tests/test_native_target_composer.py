from __future__ import annotations

from unittest.mock import patch
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program import (
    WorkspacePatternProducer,
    build_native_target_plan,
    compile_platform_program_facts,
)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookModel, WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class NativeTargetComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_one_interface_composes_every_cp3_kind_without_workbook_reads(self) -> None:
        target = TargetKey("chroma", "CP3", "lab", "NATIVE_ALL_CHROMA_CP3")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = GeneratedPatternProducer.from_compilation(
            self.compilation,
            "chroma",
            fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma"),
        )

        with patch.object(
            WorkbookModel,
            "dataframe",
            side_effect=AssertionError("native composer reopened workbook data"),
        ):
            plan = build_native_target_plan(
                self.compilation, target, facts, producer
            )

        paths = {artifact.relative_path for artifact in plan.artifacts}
        self.assertIn("NATIVE_ALL_CHROMA_CP3.pln", paths)
        self.assertIn("pat/pin.dec", paths)
        source = plan.artifact("NATIVE_ALL_CHROMA_CP3.pln").content.decode("gbk")
        schedule = self.compilation.for_cp("CP3").canonical_schedule
        self.assertTrue(all(definition.render_name in source for definition in schedule.definitions))
        self.assertRegex(source, r"(?m)^  hw_Download_Code\s+=!9;\r?$")
        self.assertRegex(source, r"(?m)^  sw_Download_Code\s+=!16;\r?$")

    def test_composition_is_deterministic(self) -> None:
        target = TargetKey("s100", "CP1", "lab", "NATIVE_ALL_S100_CP1")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = GeneratedPatternProducer.from_compilation(
            self.compilation,
            "s100",
            fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100"),
        )

        first = build_native_target_plan(self.compilation, target, facts, producer)
        second = build_native_target_plan(self.compilation, target, facts, producer)

        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.artifacts, second.artifacts)
        source = first.artifact("NATIVE_ALL_S100_CP1.prg").content.decode("gbk")
        self.assertNotIn("@@END_PLAN@@PLAN", source)
        erase = first.artifact("fbist_erase_main_1st_page.sd").content.decode("ascii")
        self.assertEqual(erase.count("pe_1:"), 1)
        timing = first.artifact("NATIVE_ALL_S100_CP1.tim").content.decode("gbk")
        self.assertIn("[NAME=VIH_5MHZ]", timing)

    def test_every_supported_formal_target_closes(self) -> None:
        targets = (
            *(('chroma', cp, variant)
              for variant in ("lab", "production")
              for cp in ("CP1", "CP2", "CP3")),
            *(('s100', cp, "lab") for cp in ("CP1", "CP2", "CP3")),
        )
        producers = {
            platform: GeneratedPatternProducer.from_compilation(
                self.compilation,
                platform,
                fallback=WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / platform
                ),
            )
            for platform in ("chroma", "s100")
        }
        for platform, cp, variant in targets:
            with self.subTest(platform=platform, cp=cp, variant=variant):
                target = TargetKey(
                    platform, cp, variant,
                    f"NATIVE_ALL_{platform.upper()}_{variant.upper()}_{cp}",
                )
                facts = compile_platform_program_facts(self.workbook, target)
                plan = build_native_target_plan(
                    self.compilation, target, facts, producers[platform]
                )
                extension = "pln" if platform == "chroma" else "prg"
                self.assertIsNotNone(
                    plan.artifact(f"{target.program_name}.{extension}")
                )
                if platform == "chroma" and cp == "CP1":
                    source = plan.artifact(
                        f"{target.program_name}.{extension}"
                    ).content.decode("gbk")
                    self.assertEqual(source.count("// PDR voltage profiles"), 1)
                if platform == "s100" and cp == "CP3":
                    project = plan.artifact(
                        f"{target.program_name}.prj"
                    ).content.decode("gbk")
                    self.assertIn("Rpc14_clkloop.sr", project)
                    timing = plan.artifact(
                        f"{target.program_name}.tim"
                    ).content.decode("gbk")
                    self.assertIn("[NAME=TS_FORCE_CLK]", timing)


if __name__ == "__main__":
    unittest.main()
