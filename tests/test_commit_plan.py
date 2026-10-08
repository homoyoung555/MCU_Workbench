import unittest

import pandas as pd

from flow_recipe import RecipeValueToken
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.commit_plan import (
    CommitExecutionError,
    CommitExecutor,
    execute_commit_operations,
    validate_trimdata_recipe_contract,
)
from program_gen.core.page_image import PageImageStore
from program_gen.core.persistence_recipe import (
    PersistenceFieldWrite,
    PersistenceOperation,
)


class CommitPlanTests(unittest.TestCase):
    def test_commit_updates_real_register_and_delegates_storage_encoding(self):
        catalog = _catalog()
        store = PageImageStore()
        store.establish_page(
            "trim1", {"ANA_MUX_TRIM2": 0x0006}, source="READOTPMAP"
        )
        executor = CommitExecutor(store, catalog)

        executor.add_commit((_write("DLPR0_VSEL_OP_VDDK", "DECIMAL", "1"),))
        flush = executor.flush_before("PGMOTP")

        self.assertEqual(store.register_value("trim1", "ANA_MUX_TRIM2"), 0x0005)
        self.assertEqual(flush.pages, ("trim1",))
        self.assertEqual(
            [(word.page, word.register, word.storage_word) for word in flush.words],
            [("trim1", "ANA_MUX_TRIM2", 0xFFFA0005)],
        )

    def test_explicit_commit_overrides_default_and_consecutive_commits_flush_once(self):
        catalog = _catalog()
        store = PageImageStore()
        store.establish_page(
            "trim1", {"ANA_MUX_TRIM2": 0x0006}, source="BUILDMAP"
        )
        executor = CommitExecutor(store, catalog)

        executor.add_commit(
            (_write("DLPR0_VSEL_OP_VDDK", "DECIMAL", "0"),), source="DEFAULT"
        )
        executor.add_commit(
            (_write("DLPR1_VSEL_OP_VDDK", "DECIMAL", "3"),), source="EXPLICIT"
        )
        executor.add_commit(
            (_write("DLPR0_VSEL_OP_VDDK", "DECIMAL", "1"),), source="EXPLICIT"
        )
        flush = executor.flush_before("PGMOTP")

        self.assertEqual(flush.pages, ("trim1",))
        self.assertEqual(len(flush.words), 1)
        self.assertEqual(store.register_value("trim1", "ANA_MUX_TRIM2"), 0x000D)
        self.assertEqual(flush.words[0].storage_word, 0xFFF2000D)
        self.assertEqual(len(flush.warnings), 1)
        self.assertIn("DLPR0_VSEL_OP_VDDK", flush.warnings[0])
        self.assertIn("显式", flush.warnings[0])

        empty = executor.flush_before("CHECKOTP")
        self.assertEqual(empty.pages, ())
        self.assertEqual(empty.words, ())

    def test_rhs_uses_step_and_variable_environment_and_missing_values_are_atomic(self):
        catalog = _catalog()
        store = PageImageStore()
        store.establish_page(
            "trim1", {"ANA_MUX_TRIM2": 0x0006}, source="READOTPMAP"
        )
        executor = CommitExecutor(
            store, catalog, values={"DLPR_VALUE": 2}, step=1
        )

        executor.add_commit((
            _write("DLPR0_VSEL_OP_VDDK", "STEP", "STEP"),
            _write("DLPR1_VSEL_OP_VDDK", "VARIABLE", "DLPR_VALUE"),
        ))
        executor.flush_before("PGMOTP")

        self.assertEqual(store.register_value("trim1", "ANA_MUX_TRIM2"), 0x0009)

        for kind, token in (("VARIABLE", "MISSING"), ("STEP", "STEP")):
            isolated = PageImageStore()
            isolated.establish_page(
                "trim1", {"ANA_MUX_TRIM2": 0x0006}, source="READOTPMAP"
            )
            no_environment = CommitExecutor(isolated, catalog)
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(CommitExecutionError, "没有可用来源"):
                    no_environment.add_commit(
                        (_write("DLPR0_VSEL_OP_VDDK", kind, token),)
                    )
                self.assertEqual(
                    isolated.register_value("trim1", "ANA_MUX_TRIM2"), 0x0006
                )

        atomic = PageImageStore()
        atomic.establish_page(
            "trim1", {"ANA_MUX_TRIM2": 0x0006}, source="READOTPMAP"
        )
        atomic_executor = CommitExecutor(atomic, catalog)
        with self.assertRaises(CommitExecutionError):
            atomic_executor.add_commit((
                _write("DLPR0_VSEL_OP_VDDK", "DECIMAL", "1"),
                _write("DLPR1_VSEL_OP_VDDK", "VARIABLE", "MISSING"),
            ))
        empty = atomic_executor.flush_before("PGMOTP")
        self.assertEqual(empty.pages, ())
        self.assertEqual(
            atomic.register_value("trim1", "ANA_MUX_TRIM2"), 0x0006
        )

    def test_operation_executor_flushes_consecutive_commits_before_pattern_consumer(self):
        catalog = _catalog()
        store = PageImageStore()
        store.establish_page(
            "trim1", {"ANA_MUX_TRIM2": 0x0006}, source="BUILDMAP"
        )
        operations = (
            _operation(
                "COMMIT", (_write("DLPR0_VSEL_OP_VDDK", "DECIMAL", "0"),),
                commit_source="DEFAULT",
            ),
            _operation(
                "COMMIT", (_write("DLPR0_VSEL_OP_VDDK", "DECIMAL", "1"),),
                commit_source="EXPLICIT",
            ),
            _operation("COMMIT", (_write("DLPR1_VSEL_OP_VDDK", "DECIMAL", "3"),)),
            _operation("SETVPOSP"),
            _operation("PGMOTP"),
        )

        plan = execute_commit_operations(operations, store, catalog)

        self.assertEqual(len(plan.flushes), 1)
        self.assertEqual(plan.flushes[0].consumer, "PGMOTP")
        self.assertEqual(plan.flushes[0].pages, ("trim1",))
        self.assertEqual(len(plan.flushes[0].warnings), 1)
        self.assertEqual(plan.consumers, ("SETVPOSP", "PGMOTP"))

    def test_same_logical_field_can_fan_out_to_multiple_physical_targets(self):
        catalog = _fanout_catalog()
        store = PageImageStore()
        store.establish_page("trim1", {"REG_A": 0}, source="BUILDMAP")
        store.establish_page("uid", {"REG_B": 0}, source="BUILDMAP")
        executor = CommitExecutor(store, catalog)
        writes = (
            PersistenceFieldWrite(
                field="SHARED", page="trim1", register="REG_A", lsb=0, width=2,
                value=RecipeValueToken(kind="DECIMAL", token="2"),
            ),
            PersistenceFieldWrite(
                field="SHARED", page="uid", register="REG_B", lsb=0, width=2,
                value=RecipeValueToken(kind="DECIMAL", token="2"),
            ),
        )

        executor.add_commit(writes)
        flush = executor.flush_before("PGMOTP")

        self.assertEqual(flush.pages, ("trim1", "uid"))
        self.assertEqual(store.register_value("trim1", "REG_A"), 2)
        self.assertEqual(store.register_value("uid", "REG_B"), 2)

    def test_trimdata_write_and_rewrite_contracts_are_explicit(self):
        validate_trimdata_recipe_contract(
            "Trimdata_Write", ("COMMIT", "PGMOTP")
        )
        validate_trimdata_recipe_contract(
            "Trimdata_Write", ("COMMIT", "SETVPOSP", "PGMOTP")
        )
        validate_trimdata_recipe_contract(
            "Trimdata_Rewrite", ("COMMIT", "PGMOTP")
        )

        invalid = (
            ("Trimdata_Write", ("PGMOTP",)),
            ("Trimdata_Write", ("COMMIT", "CHECKOTP", "PGMOTP")),
            ("Trimdata_Rewrite", ("COMMIT", "SETVPOSP", "PGMOTP")),
            ("Trimdata_Rewrite", ("COMMIT",)),
        )
        for node, modules in invalid:
            with self.subTest(node=node, modules=modules):
                with self.assertRaises(CommitExecutionError):
                    validate_trimdata_recipe_contract(node, modules)


def _write(field, kind, token):
    return PersistenceFieldWrite(
        field=field,
        page="trim1",
        register="ANA_MUX_TRIM2",
        lsb=0 if field == "DLPR0_VSEL_OP_VDDK" else 2,
        width=2,
        value=RecipeValueToken(kind=kind, token=token),
    )


def _operation(module, writes=(), commit_source=None):
    return PersistenceOperation(
        module=module,
        excel_row=2,
        requested_pages=("trim1",),
        effective_pages=("trim1",) if writes else (),
        field_writes=tuple(writes),
        commit_source=commit_source,
    )


def _catalog():
    return compile_addr_map_catalog(pd.DataFrame([{
        "Word No.": "trim1", "line": "CP1,CP2", "bit[31:16]": "反码",
        "bit[15:0]": "ANA_MUX_TRIM2[15:0]", "data type": "lable",
        "CP Data[31:0]": "32'hFFF9_0006",
        "CP addr map": "OTHER[13:4],DLPR1_VSEL_OP_VDDK[1:0],DLPR0_VSEL_OP_VDDK[1:0]",
    }]))


def _fanout_catalog():
    return compile_addr_map_catalog(pd.DataFrame([
        {
            "Word No.": "trim1", "line": "CP1", "bit[31:16]": "反码",
            "bit[15:0]": "REG_A[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'hFFFF_0000", "CP addr map": "PAD[13:0],SHARED[1:0]",
        },
        {
            "Word No.": "uid", "line": "CP1", "bit[31:16]": "反码",
            "bit[15:0]": "REG_B[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'hFFFF_0000", "CP addr map": "PAD2[13:0],SHARED[1:0]",
        },
    ]))


if __name__ == "__main__":
    unittest.main()
