import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
)
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.pvd_test_assembly import compile_pvd_test_assembly
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class PvdNativeAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = next(iter(cls.compilation.plan.catalogs.pvd_test_plans.values()))

    def test_formal_pvd_plan_assembles_one_canonical_body_on_both_platforms(self):
        for platform in ("chroma", "s100"):
            target = TargetKey(platform, "CP3", "lab", f"PVD_{platform}")
            facts = compile_platform_program_facts(self.workbook, target)
            assembly = compile_pvd_test_assembly(
                (self.plan,),
                TypedKindContext(self.compilation, target, facts, None),
            )

            self.assertEqual(assembly.typed_kind, "PVD_TEST")
            self.assertEqual(len(assembly.contributions), 1)
            self.assertEqual(len(assembly.bodies), 1)
            contribution = assembly.contributions[0]
            self.assertEqual(len(contribution.definitions), 1)
            self.assertEqual(len(contribution.schedule_entries), 1)
            self.assertEqual(contribution.resource_requires, ())
            self.assertGreater(len(contribution.resources), 0)
            self.assertNotIn(
                b"STUB",
                b"\n".join(resource.content for resource in contribution.resources),
            )
            self.assertEqual(assembly.bodies[0].fragment.section, "TESTS")
            self.assertEqual(
                assembly.bodies[0].fragment.order,
                contribution.schedule_entries[0].ordinal,
            )

    def test_registered_pvd_slice_closes_in_platform_program_builder(self):
        self.assertIn("PVD_TEST", NATIVE_TYPED_KIND_REGISTRY.registered_kinds)
        for platform in ("chroma", "s100"):
            target = TargetKey(platform, "CP3", "lab", f"PVD_{platform}")
            facts = compile_platform_program_facts(self.workbook, target)
            producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
            context = TypedKindContext(self.compilation, target, facts, producer)
            assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                "PVD_TEST", (self.plan,), context
            )

            rendered = PlatformProgramBuilder(producer).build(
                ProgramAssemblyInput(
                    target,
                    facts,
                    self.compilation.for_cp("CP3").canonical_schedule,
                    assembly.contributions,
                    assembly.bodies,
                )
            )

            extension = ".pln" if platform == "chroma" else ".prg"
            program = rendered.artifact(target.program_name + extension).content
            self.assertNotIn(b"STUB", program)
            self.assertIn(b"Pvd_Test", program)
            if platform == "chroma":
                self.assertIn(b"int SHMOO_LVL = 5;", program)
                self.assertEqual(program.count(b"POWER_Shmoo_ON(double vccVolt)"), 1)
                self.assertIn(
                    b"SET_LEVELN(SHMOO_LVL,IO_ALLPINS,0.0V,vccVolt,",
                    program,
                )
            if platform == "s100":
                project = rendered.artifact(target.program_name + ".prj").content
                for resource in assembly.contributions[0].resources:
                    self.assertIn(resource.relative_path.encode("gbk"), project)
                self.assertIn(
                    b"LOGIC_SET_CMP_LEVEL(IO_ALLPINS, 1.5785V, 1.2915V, VR2);",
                    program,
                )
                self.assertNotIn(b"pvd_v[item]", program)


if __name__ == "__main__":
    unittest.main()
