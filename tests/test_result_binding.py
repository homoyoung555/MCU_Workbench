from types import SimpleNamespace
import unittest

from flow_recipe import ResultExportPlan, ResultExportPlanSet, RecipeValueToken
from program_gen.core.persistence_recipe import (
    PersistenceFieldWrite,
    PersistenceOperation,
    PersistencePlanSet,
    PersistenceRowPlan,
)
from program_gen.core.result_binding import (
    PersistedResultConsumer,
    ResultBindingCompileError,
    TrustedPageImageRead,
    compile_persisted_result_imports,
    compile_product_result_bindings,
)


def _export(*, row=0, cp="CP1", item="Vrefint", sub="/", symbol="VREFINT_EXPORT",
            export_format="BCD16_MV", uid=True):
    return ResultExportPlan(
        flow_row_index=row,
        item=item,
        sub=sub,
        flow_type="verify",
        source_kind="MEASUREMENT",
        format=export_format,
        symbol=symbol,
        c_type="int",
        explicit=False,
        implied_by_uid=uid,
        persist_to_uid=uid,
    )


def _persistence(symbol="VREFINT_EXPORT", *, width=16, field="Vrefint_Verify"):
    write = PersistenceFieldWrite(
        field=field,
        page="uid",
        register="Vrefint_Verify",
        lsb=0,
        width=width,
        value=RecipeValueToken("VARIABLE", symbol),
    )
    operation = PersistenceOperation(
        "COMMIT", 12, (), ("uid",), (write,), "DEFAULT"
    )
    return PersistencePlanSet({10: PersistenceRowPlan("CP1", 12, (operation,))})


class ResultBindingTests(unittest.TestCase):
    def test_verify_export_has_explicit_stable_identity_and_uid_field_contract(self):
        plan = compile_product_result_bindings(
            {"CP1": ResultExportPlanSet((_export(),))},
            _persistence(),
        )

        binding = plan.bindings[0]
        self.assertEqual(
            (
                binding.identity.source_cp,
                binding.identity.item,
                binding.identity.sub,
                binding.identity.role,
            ),
            ("CP1", "Vrefint", "/", "VERIFY_RESULT"),
        )
        self.assertEqual(binding.symbol, "VREFINT_EXPORT")
        self.assertEqual(binding.encoding, "BCD16_MV")
        self.assertEqual(
            (
                binding.targets[0].destination,
                binding.targets[0].page,
                binding.targets[0].field,
                binding.targets[0].register,
                binding.targets[0].width,
            ),
            ("UID", "uid", "Vrefint_Verify", "Vrefint_Verify", 16),
        )

    def test_different_results_cannot_publish_the_same_cp_local_symbol(self):
        exports = ResultExportPlanSet((
            _export(item="First", symbol="RESULT_EXPORT", uid=False),
            _export(row=1, item="Second", symbol="RESULT_EXPORT", uid=False),
        ))

        with self.assertRaisesRegex(
            ResultBindingCompileError, "RB.SYMBOL.CONFLICT"
        ):
            compile_product_result_bindings(
                {"CP1": exports}, PersistencePlanSet({})
            )

    def test_persisted_field_must_hold_the_encoded_result_width(self):
        with self.assertRaisesRegex(
            ResultBindingCompileError, "RB.ENCODING.WIDTH_MISMATCH"
        ):
            compile_product_result_bindings(
                {"CP1": ResultExportPlanSet((_export(),))},
                _persistence(width=12),
            )

    def test_cross_cp_import_attaches_to_an_upstream_trusted_page_read_fact(self):
        bindings = compile_product_result_bindings(
            {"CP1": ResultExportPlanSet((_export(),))}, _persistence()
        )
        identity = bindings.bindings[0].identity

        imports = compile_persisted_result_imports(
            bindings,
            (PersistedResultConsumer("CP2", identity, consumer_order=9),),
            (TrustedPageImageRead(
                "CP2", "uid", producer_order=4,
                operation_identity="PAGE_READ:CP2:UID:4",
            ),),
        )

        plan = imports.imports[0]
        self.assertEqual(plan.consumer_cp, "CP2")
        self.assertEqual(plan.symbol, "VREFINT_EXPORT")
        self.assertEqual(plan.result_identity.source_cp, "CP1")
        self.assertEqual(plan.operation_identity, "PAGE_READ:CP2:UID:4")

    def test_cross_cp_consumer_before_restore_is_a_compile_error(self):
        bindings = compile_product_result_bindings(
            {"CP1": ResultExportPlanSet((_export(),))}, _persistence()
        )
        identity = bindings.bindings[0].identity

        with self.assertRaisesRegex(
            ResultBindingCompileError, "RB.IMPORT.BEFORE_RESTORE"
        ):
            compile_persisted_result_imports(
                bindings,
                (PersistedResultConsumer("CP2", identity, consumer_order=3),),
                (TrustedPageImageRead(
                    "CP2", "uid", producer_order=4,
                    operation_identity="PAGE_READ:CP2:UID:4",
                ),),
            )


if __name__ == "__main__":
    unittest.main()
