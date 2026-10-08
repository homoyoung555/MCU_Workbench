"""Registered typed-kind modules feeding the native platform assembler."""

from __future__ import annotations

import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class TypedKindRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_registered_standard_trim_compiles_one_typed_plan_into_native_assembly(self):
        target = TargetKey("chroma", "CP1", "lab", "REGISTERED_STANDARD_TRIM_CP1")
        spec = next(
            spec for spec in self.compilation.plan.catalogs.trim_specs.values()
            if spec.cp == "CP1" and spec.item == "Hsi_8M"
        )

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "STANDARD_TRIM",
            (spec,),
            TypedKindContext(
                compilation=self.compilation,
                target=target,
                platform_facts=compile_platform_program_facts(
                    self.workbook, target
                ),
                pattern_producer=WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / "chroma"
                ),
            ),
        )

        self.assertEqual(
            NATIVE_TYPED_KIND_REGISTRY.registered_kinds,
            (
                "STANDARD_TRIM", "OS", "PDR_TRIM", "PDR_VERIFY",
                "STANDARD_VERIFY", "DAC_ADJUST", "FLASH_WINDOW",
                "TRIMDATA_READ", "TRIMDATA_WRITE", "UID", "ID", "MAIN", "VT", "MARGIN",
                "CODE_DOWNLOAD", "FIRMWARE_FUNCTION_TEST", "FIRMWARE_RUN_TEST",
            "PVD_TEST", "ADC_TEST", "DC_PARAMETRIC_TEST",
            "DC_VIH_VIL", "FREQ_TEST", "OPA_TEST", "DAC_TEST",
            "VERIFY_SCAN", "VERIFY_MBIST",
            ),
        )
        self.assertEqual(assembly.typed_kind, "STANDARD_TRIM")
        self.assertEqual(len(assembly.bodies), 2)
        self.assertEqual(len(assembly.contributions), 2)
        self.assertEqual(
            assembly.contributions[0].definitions[0].typed_kind,
            "STANDARD_TRIM",
        )
        self.assertNotIn(
            "int HSI_8M_DAC_FINAL[MAX_SITE];",
            assembly.contributions[1].sections[0].content.decode("gbk"),
        )
        self.assertIn(
            "HSI_8M_DAC_FINAL",
            self.compilation.for_cp("CP1").runtime_state.declarations.names,
        )

    def test_registered_pdr_trim_builds_native_program_with_startup_levels(self):
        target = TargetKey("chroma", "CP1", "lab", "REGISTERED_PDR_TRIM_CP1")
        plan = next(
            iter(self.compilation.plan.catalogs.dedicated_trim_plans.values())
        )
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma")

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "PDR_TRIM",
            (plan,),
            TypedKindContext(self.compilation, target, facts, producer),
        )
        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
        ))

        self.assertEqual(
            NATIVE_TYPED_KIND_REGISTRY.registered_kinds,
            (
                "STANDARD_TRIM", "OS", "PDR_TRIM", "PDR_VERIFY",
                "STANDARD_VERIFY", "DAC_ADJUST", "FLASH_WINDOW",
                "TRIMDATA_READ", "TRIMDATA_WRITE", "UID", "ID", "MAIN", "VT", "MARGIN",
                "CODE_DOWNLOAD", "FIRMWARE_FUNCTION_TEST", "FIRMWARE_RUN_TEST",
            "PVD_TEST", "ADC_TEST", "DC_PARAMETRIC_TEST",
            "DC_VIH_VIL", "FREQ_TEST", "OPA_TEST", "DAC_TEST",
            "VERIFY_SCAN", "VERIFY_MBIST",
            ),
        )
        self.assertEqual(assembly.typed_kind, "PDR_TRIM")
        source = render_plan.artifact(f"{target.program_name}.pln").content.decode("gbk")
        startup = source.index("START_UP()\r\n{")
        startup_end = source.index("}\r\n\r\n", startup)
        self.assertEqual(
            source[startup:startup_end].count("SET_LEVELN(PDR_TAR_LVL"),
            2,
        )

    def test_registered_standard_trim_is_safely_empty_when_cp_has_no_plans(self):
        target = TargetKey("chroma", "CP2", "lab", "REGISTERED_STANDARD_TRIM_CP2")

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "STANDARD_TRIM",
            (),
            TypedKindContext(
                compilation=self.compilation,
                target=target,
                platform_facts=compile_platform_program_facts(
                    self.workbook, target
                ),
                pattern_producer=WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / "chroma"
                ),
            ),
        )

        self.assertEqual(assembly.typed_kind, "STANDARD_TRIM")
        self.assertEqual(assembly.contributions, ())
        self.assertEqual(assembly.bodies, ())

    def test_registered_os_compiles_one_typed_plan_into_native_assembly(self):
        target = TargetKey("s100", "CP1", "lab", "REGISTERED_OS_CP1")
        plan = next(
            plan
            for plan in self.compilation.plan.catalogs.os_plans["s100"].values()
            if plan.cp == "CP1"
        )

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "OS",
            (plan,),
            TypedKindContext(
                compilation=self.compilation,
                target=target,
                platform_facts=compile_platform_program_facts(
                    self.workbook, target
                ),
                pattern_producer=WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / "s100"
                ),
            ),
        )

        self.assertEqual(assembly.typed_kind, "OS")
        self.assertEqual(len(assembly.bodies), 1)
        self.assertEqual(len(assembly.contributions), 2)
        self.assertEqual(
            assembly.contributions[0].definitions[0].typed_kind,
            "OS",
        )

    def test_registered_os_is_safely_empty_when_target_has_no_plans(self):
        target = TargetKey("s100", "CP2", "lab", "REGISTERED_OS_CP2")

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "OS",
            (),
            TypedKindContext(
                compilation=self.compilation,
                target=target,
                platform_facts=compile_platform_program_facts(
                    self.workbook, target
                ),
                pattern_producer=WorkspacePatternProducer(
                    WORKSPACE_ROOT / "input" / "s100"
                ),
            ),
        )

        self.assertEqual(assembly.typed_kind, "OS")
        self.assertEqual(assembly.contributions, ())
        self.assertEqual(assembly.bodies, ())

    def test_registered_pdr_verify_builds_native_program_with_startup_levels(self):
        target = TargetKey("chroma", "CP1", "lab", "REGISTERED_PDR_VERIFY_CP1")
        plan = next(
            plan
            for plan in self.compilation.plan.catalogs.pdr_verify_plans[
                "chroma"
            ].values()
            if plan.cp == "CP1"
        )
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma")

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "PDR_VERIFY",
            (plan,),
            TypedKindContext(self.compilation, target, facts, producer),
        )
        render_plan = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target=target,
            platform_facts=facts,
            canonical_schedule=self.compilation.for_cp("CP1").canonical_schedule,
            contributions=assembly.contributions,
            bodies=assembly.bodies,
        ))

        self.assertEqual(assembly.typed_kind, "PDR_VERIFY")
        source = render_plan.artifact(f"{target.program_name}.pln").content.decode("gbk")
        self.assertIn("Pdr_Verify()", source)
        startup = source.index("START_UP()\r\n{")
        startup_end = source.index("}\r\n\r\n", startup)
        self.assertEqual(
            source[startup:startup_end].count("SET_LEVELN(PDR_TAR_LVL"),
            2,
        )

    def test_registered_pdr_verify_is_safely_empty_without_plans(self):
        target = TargetKey("s100", "CP3", "lab", "REGISTERED_PDR_VERIFY_EMPTY")
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "s100")

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "PDR_VERIFY",
            (),
            TypedKindContext(self.compilation, target, facts, producer),
        )

        self.assertEqual(assembly.typed_kind, "PDR_VERIFY")
        self.assertEqual(assembly.contributions, ())
        self.assertEqual(assembly.bodies, ())

    def test_registered_standard_verify_compiles_native_assembly(self):
        target = TargetKey("chroma", "CP3", "lab", "REGISTERED_STANDARD_VERIFY_CP3")
        plan = next(
            plan
            for plan in self.compilation.plan.catalogs.standard_verify_plans.values()
            if plan.cp == "CP3" and plan.item == "Hsi_Pre_Check"
        )
        facts = compile_platform_program_facts(self.workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / "chroma")

        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
            "STANDARD_VERIFY",
            (plan,),
            TypedKindContext(self.compilation, target, facts, producer),
        )

        self.assertEqual(assembly.typed_kind, "STANDARD_VERIFY")
        self.assertEqual(len(assembly.contributions), 1)
        self.assertEqual(len(assembly.bodies), 1)
        self.assertEqual(
            assembly.contributions[0].definitions[0].typed_kind,
            "STANDARD_VERIFY",
        )


if __name__ == "__main__":
    unittest.main()
