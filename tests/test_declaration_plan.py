from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from pathlib import Path
from types import SimpleNamespace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.addr_map import AddrMapCatalog, RegisterLayout
from program_gen.core.declaration_plan import (
    DeclarationCompileError,
    DeclarationKind,
    compile_declaration_plan,
)
from program_gen.core.persistence_recipe import (
    PersistenceOperation,
    PersistenceRowPlan,
)
from program_gen.program_plan import (
    RuntimeSymbol,
    SymbolCardinality,
    SymbolLifetime,
    SymbolRef,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


def _register(page: str, name: str) -> RegisterLayout:
    return RegisterLayout(
        page=page,
        register=name,
        row_index=0,
        page_row_index=0,
        cp_tokens=frozenset(("CP1",)),
        default_storage_word=0,
        real_half="LOW",
        complement_half=None,
    )


def _catalog(*registers: RegisterLayout) -> AddrMapCatalog:
    return AddrMapCatalog(
        tuple(registers),
        {item.register.casefold(): item for item in registers},
        {},
    )


def _cp_plan(
    *,
    symbols=(),
    persistence_rows=None,
    memory_wakeup_plan=None,
    result_import_plans=(),
):
    return SimpleNamespace(
        cp="CP1",
        runtime_state=SimpleNamespace(
            symbols=tuple(symbols),
            persistence_rows=persistence_rows or {},
            memory_wakeup_plan=memory_wakeup_plan,
            result_import_plans=tuple(result_import_plans),
        ),
    )


class DeclarationPlanTests(unittest.TestCase):
    def test_cross_cp_import_declares_a_cp_local_symbol_without_faking_export(self):
        imported = SimpleNamespace(
            consumer_cp="CP1",
            symbol="VREFINT_EXPORT",
            c_type="int",
            target=SimpleNamespace(width=16),
            result_identity=SimpleNamespace(
                canonical="CP0:Vrefint:/:VERIFY_RESULT"
            ),
            operation_identity="PAGE_READ:CP1:UID:4",
        )

        plan = compile_declaration_plan(
            _cp_plan(result_import_plans=(imported,)),
            SimpleNamespace(addr_map=_catalog()),
        )

        declaration = plan.require("VREFINT_EXPORT")
        self.assertEqual(declaration.kind, DeclarationKind.EXPORT)
        self.assertEqual(declaration.semantic_ref.cp, "CP1")
        self.assertTrue(declaration.sources[0].startswith("RESULT_IMPORT:CP0:"))

    def test_runtime_and_page_consumers_form_one_typed_declaration_closure(self):
        hsi = _register("uid", "Hsi_8M_Trim")
        other = _register("uid", "UID_WORD")
        catalog = _catalog(hsi, other)
        runtime = (
            RuntimeSymbol(
                SymbolRef("CP1", "RESULT", "HSI_8M_DAC_FINAL"),
                producer_order=1,
                value_type="INT",
                bit_width=10,
            ),
            RuntimeSymbol(
                SymbolRef("CP1", "RESULT", "VREFINT_EXPORT"),
                producer_order=2,
                value_type="DOUBLE",
            ),
            RuntimeSymbol(
                SymbolRef("CP1", "BUILD_UID", "WAFERID"),
                producer_order=3,
                value_type="RUNTIME",
            ),
        )
        persistence = {
            7: PersistenceRowPlan(
                "CP1",
                9,
                (
                    PersistenceOperation(
                        "READOTPMAP", 9, ("uid",), ("uid",)
                    ),
                ),
            )
        }

        plan = compile_declaration_plan(
            _cp_plan(symbols=runtime, persistence_rows=persistence),
            SimpleNamespace(addr_map=catalog),
        )

        self.assertEqual(
            tuple(item.name for item in plan.dac_final),
            ("HSI_8M_DAC_FINAL",),
        )
        self.assertEqual(tuple(item.name for item in plan.exports), ("VREFINT_EXPORT",))
        self.assertEqual(tuple(item.name for item in plan.build_uid), ("WAFERID",))
        self.assertEqual(
            tuple(item.name for item in plan.register_images),
            ("REG_HSI_8M_TRIM", "REG_UID_WORD"),
        )
        hsi_declaration = plan.require("REG_HSI_8M_TRIM")
        self.assertEqual(hsi_declaration.register, "Hsi_8M_Trim")
        self.assertTrue(
            any(
                source.startswith("PERSISTENCE:FLOW:9:READOTPMAP:PAGE:uid")
                for source in hsi_declaration.sources
            )
        )

    def test_conflicting_names_are_rejected_case_insensitively(self):
        catalog = _catalog(_register("uid", "FOO"))
        persistence = {
            0: PersistenceRowPlan(
                "CP1",
                2,
                (PersistenceOperation("LOADMAP", 2, ("uid",), ("uid",)),),
            )
        }
        runtime = RuntimeSymbol(
            SymbolRef("CP1", "RESULT", "reg_foo"),
            producer_order=1,
            value_type="DOUBLE",
        )

        with self.assertRaisesRegex(DeclarationCompileError, "DP.DECLARATION.CONFLICT"):
            compile_declaration_plan(
                _cp_plan(symbols=(runtime,), persistence_rows=persistence),
                SimpleNamespace(addr_map=catalog),
            )

    def test_formal_product_derives_hsi_register_images_from_typed_sources(self):
        compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        required_hsi = {
            "REG_HSI_8M_TRIM",
            "REG_HSI_16M_TRIM",
            "REG_HSI_24M_TRIM",
            "REG_HSI_48M_TRIM",
        }

        for cp in ("CP1", "CP2", "CP3"):
            with self.subTest(cp=cp):
                first = compile_declaration_plan(
                    compilation.for_cp(cp), compilation.plan.catalogs
                )
                second = compile_declaration_plan(
                    compilation.for_cp(cp), compilation.plan.catalogs
                )
                self.assertEqual(first, second)
                self.assertEqual(first.identity, second.identity)
                self.assertTrue(required_hsi.issubset(set(first.names)))
                for name in required_hsi:
                    declaration = first.require(name)
                    self.assertEqual(declaration.kind, DeclarationKind.REGISTER_IMAGE)
                    self.assertIs(
                        compilation.plan.catalogs.addr_map.resolve_register(
                            declaration.register
                        ),
                        next(
                            item
                            for item in compilation.plan.catalogs.addr_map.registers
                            if item.register == declaration.register
                        ),
                    )
                    self.assertTrue(
                        any(
                            source.startswith(("PERSISTENCE:", "MEMORY_WAKEUP:"))
                            for source in declaration.sources
                        )
                    )
                    expected_source = (
                        "MEMORY_WAKEUP:BUILDMAP:"
                        if cp == "CP1"
                        else "PERSISTENCE:"
                    )
                    self.assertTrue(
                        any(
                            source.startswith(expected_source)
                            for source in declaration.sources
                        )
                    )

        cp1 = compile_declaration_plan(
            compilation.for_cp("CP1"), compilation.plan.catalogs
        )
        cp2 = compile_declaration_plan(
            compilation.for_cp("CP2"), compilation.plan.catalogs
        )
        cp3 = compile_declaration_plan(
            compilation.for_cp("CP3"), compilation.plan.catalogs
        )
        self.assertIn("HSI_8M_DAC_FINAL", tuple(item.name for item in cp1.dac_final))
        self.assertIn("PDR_DAC_FINAL", tuple(item.name for item in cp1.dac_final))
        self.assertTrue(
            {
                binding.dac_final_symbol
                for binding in compilation.for_cp("CP1").memory_wakeup_plan.build_map.field_bindings
            }.issubset({item.name for item in cp1.dac_final})
        )
        self.assertTrue(
            {
                "REG_" + binding.field.register.upper()
                for binding in compilation.for_cp("CP1").memory_wakeup_plan.build_map.field_bindings
            }.issubset(set(cp1.names))
        )
        self.assertIn("VREFINT_EXPORT", tuple(item.name for item in cp2.exports))
        self.assertTrue(
            {"WAFERID", "LOT_ID", "WAFER_SLOT"}.issubset(
                {item.name for item in cp3.build_uid}
            )
        )
        self.assertTrue({"X_CO", "Y_CO"}.isdisjoint(set(cp3.names)))

    def test_module_contains_no_raw_dataframe_or_hsi_name_patch(self):
        source = (
            ROOT / "program_gen" / "core" / "declaration_plan.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("pandas", source)
        self.assertNotIn("DataFrame", source)
        self.assertNotIn("generated_flow_item_name", source)
        self.assertNotIn("HSI_8M_TRIM", source.upper())
        self.assertNotIn("HSI_16M_TRIM", source.upper())
        self.assertNotIn("HSI_24M_TRIM", source.upper())
        self.assertNotIn("HSI_48M_TRIM", source.upper())


if __name__ == "__main__":
    unittest.main()
