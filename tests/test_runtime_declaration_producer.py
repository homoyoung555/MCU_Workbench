import unittest

from program_gen.core.declaration_plan import (
    Declaration,
    DeclarationKind,
    RuntimeDeclarationPlan,
)
from program_gen.platform_program.runtime_declarations import (
    compile_runtime_declaration_contribution,
)
from program_gen.program_plan import SymbolCardinality, SymbolLifetime, SymbolRef
from program_gen.render_plan import TargetKey


class RuntimeDeclarationProducerTests(unittest.TestCase):
    def test_one_cp_plan_is_the_only_input_for_business_globals(self):
        plan = RuntimeDeclarationPlan("CP1", (
            Declaration(
                "HSI_8M_DAC_FINAL", DeclarationKind.DAC_FINAL, "INT", 4,
                SymbolCardinality.SITE, SymbolLifetime.CP,
                SymbolRef("CP1", "RESULT", "HSI_8M_DAC_FINAL"),
            ),
            Declaration(
                "VREFINT_EXPORT", DeclarationKind.EXPORT, "INT", None,
                SymbolCardinality.SITE, SymbolLifetime.CP,
                SymbolRef("CP1", "RESULT", "VREFINT_EXPORT"),
            ),
            Declaration(
                "REG_UID_WORD", DeclarationKind.REGISTER_IMAGE, "INT", 16,
                SymbolCardinality.SITE, SymbolLifetime.CP,
                register="UID_WORD", page="uid",
            ),
            Declaration(
                "REG_TRIM0", DeclarationKind.REGISTER_IMAGE, "INT", 16,
                SymbolCardinality.SITE, SymbolLifetime.CP,
                register="TRIM0", page="trim0",
            ),
            Declaration(
                "REG_TRIM1", DeclarationKind.REGISTER_IMAGE, "INT", 16,
                SymbolCardinality.SITE, SymbolLifetime.CP,
                register="TRIM1", page="trim0",
            ),
        ), "DECLARATION-ID")
        target = TargetKey("chroma", "CP1", "lab", "RUNTIME_DECL")

        contribution = compile_runtime_declaration_contribution(target, plan)
        source = contribution.sections[0].content.decode("gbk")

        self.assertEqual(
            source,
            "// Typed runtime declarations\r\n"
            "// Trim DAC final\r\n"
            "int HSI_8M_DAC_FINAL[MAX_SITE];\r\n\r\n"
            "// Export variables\r\n"
            "int VREFINT_EXPORT[MAX_SITE];\r\n\r\n"
            "// Addr Map page: uid\r\n"
            "int REG_UID_WORD[MAX_SITE];\r\n\r\n"
            "// Addr Map page: trim0\r\n"
            "int REG_TRIM0[MAX_SITE],REG_TRIM1[MAX_SITE];\r\n\r\n",
        )
        self.assertEqual(contribution.provides, ())

    def test_plan_cp_must_match_target_cp(self):
        target = TargetKey("s100", "CP2", "lab", "RUNTIME_DECL")
        with self.assertRaisesRegex(ValueError, "RD.TARGET.CP_MISMATCH"):
            compile_runtime_declaration_contribution(
                target, RuntimeDeclarationPlan("CP1", (), "EMPTY")
            )


if __name__ == "__main__":
    unittest.main()
