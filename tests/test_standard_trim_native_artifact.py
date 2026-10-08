"""STANDARD_TRIM native complete-artifact tracer-bullet tests."""

from __future__ import annotations

import json
import ast
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.render_plan import TargetKey
from program_gen.platform_program import (
    StandardTrimProgramStagingRenderer,
    WorkspacePatternProducer,
    build_standard_trim_program_plan,
    compile_platform_program_facts,
)
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class StandardTrimNativeArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.spec = next(
            spec for spec in cls.compilation.plan.catalogs.trim_specs.values()
            if spec.cp == "CP1" and spec.item == "Hsi_8M"
        )

    def _plan(self, platform: str):
        target = TargetKey(platform, "CP1", "lab", f"NATIVE_{platform.upper()}_CP1")
        producer = WorkspacePatternProducer(
            WORKSPACE_ROOT / "input" / platform
        )
        return build_standard_trim_program_plan(
            self.compilation,
            target,
            specs=(self.spec,),
            platform_facts=compile_platform_program_facts(self.workbook, target),
            pattern_producer=producer,
        )

    def _all_trim_plan(self, platform: str):
        target = TargetKey(platform, "CP1", "lab", f"ALL_TRIM_{platform.upper()}_CP1")
        specs = tuple(
            spec for spec in self.compilation.plan.catalogs.trim_specs.values()
            if spec.cp == "CP1" and not spec.item.casefold().startswith("pdr")
        )
        return specs, build_standard_trim_program_plan(
            self.compilation,
            target,
            specs=specs,
            platform_facts=compile_platform_program_facts(self.workbook, target),
            pattern_producer=WorkspacePatternProducer(
                WORKSPACE_ROOT / "input" / platform
            ),
        )

    def test_chroma_complete_artifact_is_closed_without_golden_or_legacy(self):
        plan = self._plan("chroma")
        paths = tuple(artifact.relative_path for artifact in plan.artifacts)
        self.assertEqual(
            paths,
            (
                "NATIVE_CHROMA_CP1.pln",
                "pat/enter_fbist_mode.pat",
                "pat/enter_hsi_8m.pat",
                "pat/exit_fbist_mode.pat",
                "pat/nm_read.pat",
                "pat/otp_read.pat",
                "pat/pin.dec",
                "pat/set_hsi_8m_dac.pat",
                "pat/set_hsi_vrega_dac.pat",
                "pat/set_iref1u_dac.pat",
                "pat/set_vref0p8_abs_dac.pat",
            ),
        )
        source = plan.artifact("NATIVE_CHROMA_CP1.pln").content.decode("gbk")
        for structure in ("START_UP()", "test_start()", "TEST_PRO{", "test_end()", "RELEASE()"):
            self.assertIn(structure, source)
        self.assertIn("Hsi_8M_Trim()", source)
        self.assertIn("Hsi_8M_Dac_Loop()", source)
        self.assertIn("OTP_Read()", source)
        self.assertIn("NM_Data_Read()", source)
        self.assertIn(
            "OTP_Read                          ?                       : "
            "#C(hw_Debug",
            source,
        )
        self.assertIn(
            "NM_Data_Read                      ?                       : "
            "#C(hw_Debug",
            source,
        )
        self.assertEqual(len(re.findall(r"hw_Debug\s+=!250;", source)), 1)
        self.assertEqual(len(re.findall(r"sw_Debug\s+=!250;", source)), 1)
        self.assertNotIn("Golden", source)
        self.assertNotIn("legacy", source.casefold())
        manifest = json.loads(plan.manifest_json)
        self.assertEqual(len(manifest["artifacts"]), len(plan.artifacts))
        self.assertTrue(all(row["sha256"] for row in manifest["artifacts"]))

    def test_chroma_pattern_adapter_projects_typed_clock_pin_into_seed_header(self):
        target = TargetKey(
            "chroma",
            "CP1",
            "production",
            "V_PCD2509V1_PY32F420A_C8_30C_V00_50_24SS_CP1",
        )
        plan = build_standard_trim_program_plan(
            self.compilation,
            target,
            specs=(self.spec,),
            platform_facts=compile_platform_program_facts(self.workbook, target),
            pattern_producer=WorkspacePatternProducer(
                WORKSPACE_ROOT / "input" / "chroma"
            ),
        )

        pattern = plan.artifact("pat/enter_fbist_mode.pat").content.decode("gbk")
        self.assertIn("HEADER\r\n\r\nPA11, PA13, NRST;", pattern)
        self.assertNotIn("HEADER\r\n\r\nPA14, PA13, NRST;", pattern)

    def test_cp3_omits_version_targets_marked_not_applicable(self):
        spec = next(
            item for item in self.compilation.plan.catalogs.trim_specs.values()
            if item.cp == "CP3" and item.item == "Hsi_8M"
        )
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(
                    platform,
                    "CP3",
                    "lab",
                    f"NATIVE_{platform.upper()}_CP3",
                )
                plan = build_standard_trim_program_plan(
                    self.compilation,
                    target,
                    specs=(spec,),
                    platform_facts=compile_platform_program_facts(
                        self.workbook, target
                    ),
                    pattern_producer=WorkspacePatternProducer(
                        WORKSPACE_ROOT / "input" / platform
                    ),
                )
                extension = "pln" if platform == "chroma" else "prg"
                source = plan.artifact(
                    f"{target.program_name}.{extension}"
                ).content.decode("gbk")

                self.assertNotIn(" = /", source)
                self.assertNotIn("VPOSE_TAR", source)
                self.assertNotIn("VTE_VOLTAGE", source)

    def test_business_globals_follow_platform_base_globals(self):
        for platform in ("chroma", "s100"):
            source = self._plan(platform).artifact(
                f"NATIVE_{platform.upper()}_CP1.{ 'pln' if platform == 'chroma' else 'prg' }"
            ).content.decode("gbk")
            base = "const int MAX_SITE" if platform == "chroma" else "#define MAX_SITE"
            self.assertLess(source.index(base), source.index("HSI_8M_DAC_FINAL[MAX_SITE]"))

    def test_trim_export_copies_final_dac_to_public_snapshot_on_both_platforms(self):
        self.assertEqual(self.spec.dac_export_symbol, "HSI_8M_DAC_EXPORT")
        self.assertEqual(self.spec.operations[-1].kind, "EXPORT")

        for platform, expected in (
            ("chroma", "HSI_8M_DAC_EXPORT[I]=HSI_8M_DAC_FINAL[I];"),
            ("s100", "HSI_8M_DAC_EXPORT[T_SOCKET]=HSI_8M_DAC_FINAL[T_SOCKET];"),
        ):
            with self.subTest(platform=platform):
                source = self._plan(platform).artifact(
                    f"NATIVE_{platform.upper()}_CP1."
                    f"{'pln' if platform == 'chroma' else 'prg'}"
                ).content.decode("gbk")
                self.assertEqual(source.count("HSI_8M_DAC_EXPORT[MAX_SITE]"), 1)
                self.assertIn(expected, source)

    def test_standard_trim_dac_globals_come_only_from_runtime_declaration_plan(self):
        for cp in ("CP1", "CP3"):
            specs = tuple(
                spec for spec in self.compilation.plan.catalogs.trim_specs.values()
                if spec.cp == cp and not spec.item.casefold().startswith("pdr")
            )

            for platform in ("chroma", "s100"):
                with self.subTest(cp=cp, platform=platform):
                    target = TargetKey(
                        platform,
                        cp,
                        "lab",
                        f"DAC_GLOBALS_{platform.upper()}_{cp}",
                    )
                    plan = build_standard_trim_program_plan(
                        self.compilation,
                        target,
                        specs=specs,
                        platform_facts=compile_platform_program_facts(
                            self.workbook, target
                        ),
                        pattern_producer=WorkspacePatternProducer(
                            WORKSPACE_ROOT / "input" / platform
                        ),
                    )
                    extension = "pln" if platform == "chroma" else "prg"
                    source = plan.artifact(
                        f"{target.program_name}.{extension}"
                    ).content.decode("gbk")
                    self.assertNotIn("// Trim DAC globals", source)
                    for spec in specs:
                        declaration = f"{spec.dac_final_symbol}[MAX_SITE]"
                        self.assertEqual(source.count(declaration), 1)

    def test_chroma_test_pro_uses_golden_columns_and_terminal_semantics(self):
        source = self._plan("chroma").artifact("NATIVE_CHROMA_CP1.pln").content.decode("gbk")
        self.assertIn(
            "  Hsi_8M_Trim                       ?                       : "
            "#C(hw_Hsi_8M_Trim                        ,sw_Hsi_8M_Trim                        );",
            source,
        )
        self.assertIn(
            "  last_item_test                    ?#C(all_pass,all_pass)  : "
            "#C(fail_last_item_test                   ,fail_last_item_test                   );",
            source,
        )

    def test_all_cp1_standard_trims_except_pdr_form_a_closed_native_plan(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                specs, plan = self._all_trim_plan(platform)
                self.assertEqual(len(specs), 31)
                self.assertFalse(any("pdr" in spec.item.casefold() for spec in specs))
                extension = "pln" if platform == "chroma" else "prg"
                source = plan.artifact(
                    f"ALL_TRIM_{platform.upper()}_CP1.{extension}"
                ).content.decode("gbk")
                for spec in specs:
                    definition = next(
                        item for item in self.compilation.for_cp("CP1").canonical_schedule.definitions
                        if item.item.casefold() == spec.item.casefold()
                        and item.source_rows == (spec.flow_row_index + 2,)
                    )
                    self.assertIn(definition.render_name, source)
                self.assertNotIn("Pdr_Trim", source)
                if platform == "chroma":
                    self.assertIn("double VPOSE_TAR = 1.4;", source)
                    self.assertIn("double trimTar=VPOSE_TAR;", source)
                    for symbol in (
                        "VPOSE_TAR", "VNEGE_TAR", "VPOSP_TAR", "VNEGP_TAR",
                    ):
                        self.assertEqual(
                            len(re.findall(
                                rf"^(?:VOLTAGE|double) {symbol} =",
                                source,
                                re.MULTILINE,
                            )),
                            1,
                            msg=symbol,
                        )
                else:
                    self.assertIn("double _C_VPOSE_TAR = 1.4;", source)
                    self.assertIn("double trimTar=_C_VPOSE_TAR;", source)
                    for symbol in (
                        "VPOSE_TAR", "VNEGE_TAR", "VPOSP_TAR", "VNEGP_TAR",
                    ):
                        self.assertEqual(
                            source.count(f"double _C_{symbol} ="),
                            1,
                            msg=symbol,
                        )
                    timing = plan.artifact("ALL_TRIM_S100_CP1.tim").content.decode("gbk")
                    self.assertIn("@@AC_SET_4", timing)
                    self.assertIn("[NAME=TS_erase]", timing)
                    self.assertIn("PERIOD    = 560;", timing)
                    self.assertIn("@@AC_SET_5", timing)
                    self.assertIn("[NAME=TS_pgm]", timing)
                    self.assertIn("PERIOD    = 200;", timing)

    def test_s100_complete_artifact_uses_its_own_required_structures(self):
        plan = self._plan("s100")
        paths = tuple(artifact.relative_path for artifact in plan.artifacts)
        self.assertEqual(
            paths,
            (
                "enter_fbist_mode.sd",
                "enter_hsi_8m.sd",
                "exit_fbist_mode.sd",
                "fbist_capture_nm_bank0.sd",
                "fbist_capture_nm_bank1.sd",
                "NATIVE_S100_CP1.hed",
                "NATIVE_S100_CP1.prg",
                "NATIVE_S100_CP1.prj",
                "NATIVE_S100_CP1.tim",
                "otp_read.sd",
                "set_hsi_8m_dac.sd",
                "set_hsi_vrega_dac.sd",
                "set_iref1u_dac.sd",
                "set_vref0p8_abs_dac.sd",
            ),
        )
        source = plan.artifact("NATIVE_S100_CP1.prg").content.decode("gbk")
        self.assertIn("@@START_UP", source)
        self.assertIn("@@MACRO test_start()", source)
        self.assertIn("@@BOOKING", source)
        self.assertIn("@@PLAN Hsi_8M_Trim", source)
        self.assertIn("@@PLAN OTP_Read", source)
        self.assertIn("@@PLAN NM_Data_Read", source)
        self.assertIn("@@UNBOOKING\r\n\tOTP_Read;\r\n\tNM_Data_Read;", source)
        self.assertEqual(source.count("REJECT_BIN=16;"), 2)
        self.assertNotIn("TEST_END", source)
        self.assertNotIn("RELEASE", source)
        project = plan.artifact("NATIVE_S100_CP1.prj").content.decode("gbk")
        self.assertIn("SYSTEM_CLK    = 200Mhz", project)
        self.assertIn("TESTER_TYPE   = 7D", project)
        self.assertIn("BIN_MAP_TABLE = NEW_HARDWARE_BIN_STYLE", project)
        timing = plan.artifact("NATIVE_S100_CP1.tim").content.decode("gbk")
        self.assertIn("[NAME=TS_5MHZ]", timing)
        self.assertIn("@@AC_SET_2", timing)
        self.assertIn("@@AC_SET_4", timing)
        self.assertIn("@@AC_SET_5", timing)

    def test_native_renderer_materializes_manifest_and_hashes_in_shadow_staging(self):
        target = TargetKey("chroma", "CP1", "lab", "NATIVE_CHROMA_CP1")
        renderer = StandardTrimProgramStagingRenderer(
            lambda selected_target: compile_platform_program_facts(
                self.workbook, selected_target
            ),
            {"chroma": WORKSPACE_ROOT / "input" / "chroma"},
            select_specs=lambda _compilation, _target: (self.spec,),
        )
        with TemporaryDirectory() as temp:
            staging = Path(temp) / "shadow-stage"
            artifacts = renderer(
                self.compilation,
                SimpleNamespace(target=target, staging_directory=staging),
            )
            manifest_path = staging / ".render-manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(artifacts.manifest_identity, self._plan("chroma").identity)
            for row in manifest["artifacts"]:
                materialized = next(
                    item for item in artifacts.artifacts
                    if item.relative_path == row["path"]
                )
                self.assertEqual(materialized.sha256, row["sha256"])

    def test_platform_program_infrastructure_is_owned_above_standard_trim(self):
        standard_trim = Path(__file__).resolve().parents[1] / "program_gen" / "standard_trim"
        self.assertFalse(tuple((standard_trim / "native").glob("*.py")))
        forbidden = {
            "NativePlatformFacts", "compile_native_platform_facts",
            "PatternProducer", "WorkspacePatternProducer", "SkeletonProducer",
            "ArtifactMaterializer", "project_contribution",
        }
        for path in standard_trim.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = {
                alias.name.rsplit(".", 1)[-1]
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names
            }
            self.assertFalse(forbidden & imported, msg=path.name)
        for name in ("chroma.py", "s100.py"):
            source = (
                standard_trim.parent / "platform_program" / name
            ).read_text(encoding="utf-8")
            self.assertNotIn("TrimSpec", source)
            self.assertNotIn("spec.dac", source)


if __name__ == "__main__":
    unittest.main()
