import unittest

import pandas as pd

from flow_recipe import (
    RecipeAssignment,
    RecipeValueToken,
    compile_recipe_rows,
    compile_recipe_program,
)
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.persistence_recipe import (
    PersistenceCompileError,
    compile_persistence_plan_set,
    compile_persistence_plan,
)


class PersistenceRecipeTests(unittest.TestCase):
    def test_plan_set_owns_same_cp_readotpmap_dedup_across_writer_rows(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Pgm_CP1_BakeID", "type": "uid",
             "sub": "/", "Recipe": "READOTPMAP(UID)-LOADMAP(UID)-CHECKOTP(UID)"},
            {"CP NO": "CP2", "item": "Other_Trim", "type": "trim",
             "sub": "/", "Recipe": "ENTER-TRIM-JUDGE"},
            {"CP NO": "CP2", "item": "Pgm_CP2ID_Read", "type": "uid",
             "sub": "/", "Recipe": "READOTPMAP(UID)-LOADMAP(UID)-CHECKOTP(UID)"},
        ])
        pattern = pd.DataFrame([
            {"item": "Other_Trim", "addr": "0", "description": "",
             "pattern": "trim mode"},
            {"item": None, "addr": "0", "description": "3,DAC[3:0]=0000*",
             "pattern": "trim dac"},
        ])
        rows = compile_recipe_rows(flow, pattern)

        plans = compile_persistence_plan_set(flow, rows, _catalog())

        first = plans.for_row(0).operation("READOTPMAP")
        second = plans.for_row(2).operation("READOTPMAP")
        self.assertEqual(first.effective_pages, ("uid",))
        self.assertEqual(second.requested_pages, ("uid",))
        self.assertEqual(second.effective_pages, ())
        self.assertIsNone(plans.for_row(1))
    def test_loadmap_requires_a_complete_page_image(self):
        with self.assertRaisesRegex(PersistenceCompileError, "LOADMAP.*完整 Page Image"):
            self._compile("LOADMAP")

        plan = self._compile("BUILDMAP-LOADMAP")

        self.assertEqual([operation.module for operation in plan.operations], [
            "BUILDMAP", "LOADMAP",
        ])
        self.assertEqual(plan.operations[1].effective_pages, ("trim1",))

    def test_pattern_consumers_require_prepared_program_and_read_patterns(self):
        for recipe, module in (("BUILDMAP-CHECKOTP", "CHECKOTP"),
                               ("BUILDMAP-PGMOTP", "PGMOTP")):
            with self.subTest(recipe=recipe):
                with self.assertRaisesRegex(PersistenceCompileError, module + ".*Pattern"):
                    self._compile(recipe)

        plan = self._compile("BUILDMAP-LOADMAP-CHECKOTP-PGMOTP")

        self.assertEqual([operation.module for operation in plan.operations], [
            "BUILDMAP", "LOADMAP", "CHECKOTP", "PGMOTP",
        ])

    def test_bare_pattern_consumers_exclude_uid_but_explicit_uid_is_preserved(self):
        bare = self._compile(
            "BUILDMAP-LOADMAP-CHECKOTP-PGMOTP",
            node_default_pages=("trim1", "uid"),
        )
        consumers = {
            operation.module: operation.requested_pages
            for operation in bare.operations
            if operation.module in ("CHECKOTP", "PGMOTP")
        }
        self.assertEqual(consumers, {
            "CHECKOTP": ("trim1",),
            "PGMOTP": ("trim1",),
        })

        explicit = self._compile(
            "BUILDMAP-LOADMAP(UID)-PGMOTP(UID)",
            node_default_pages=("trim1", "uid"),
        )
        pgmotp = next(
            operation for operation in explicit.operations
            if operation.module == "PGMOTP"
        )
        self.assertEqual(pgmotp.requested_pages, ("uid",))

    def test_readotpmap_deduplicates_each_page_within_one_cp(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Bake", "type": "uid", "sub": "first",
             "Recipe": "READOTPMAP(UID)"},
            {"CP NO": "CP2", "item": "Bake", "type": "uid", "sub": "second",
             "Recipe": "READOTPMAP(UID)-LOADMAP(UID)"},
        ])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        rows = compile_recipe_program(flow, pattern).functions[0].rows

        plan = compile_persistence_plan(rows, _catalog())

        reads = [operation for operation in plan.operations
                 if operation.module == "READOTPMAP"]
        self.assertEqual(reads[0].requested_pages, ("uid",))
        self.assertEqual(reads[0].effective_pages, ("uid",))
        self.assertEqual(reads[1].requested_pages, ("uid",))
        self.assertEqual(reads[1].effective_pages, ())

    def test_uid_bare_program_and_default_commit_are_scoped_to_uid(self):
        defaults = tuple(RecipeAssignment(field=name, value=RecipeValueToken("HEX", "0x1"))
                         for name in ("UID_FIELD", "DLPR0_VSEL_OP_VDDK"))
        plan = self._compile("BUILDMAP-COMMIT-PGMOTP", flow_type="uid",
                             node_default_pages=("trim1", "uid"), node_default_bindings=defaults)
        self.assertEqual(plan.operations[-1].requested_pages, ("uid",))
        self.assertEqual(plan.operations[1].effective_pages, ("uid",))
        self.assertEqual([write.field for write in plan.operations[1].field_writes], ["UID_FIELD"])
        with self.assertRaisesRegex(PersistenceCompileError, "UID.*DLPR0_VSEL_OP_VDDK"):
            self._compile("BUILDMAP-COMMIT(DLPR0_VSEL_OP_VDDK=1)", flow_type="uid",
                          node_default_pages=("trim1", "uid"))

    def test_explicit_commit_resolves_fields_checks_constants_and_prepares_patterns(self):
        with self.assertRaisesRegex(PersistenceCompileError, "COMMIT.*完整 Page Image"):
            self._compile("COMMIT(DLPR0_VSEL_OP_VDDK=1)")
        with self.assertRaisesRegex(PersistenceCompileError, "不存在字段"):
            self._compile("BUILDMAP-COMMIT(MISSING=1)")
        with self.assertRaisesRegex(PersistenceCompileError, "2 bit"):
            self._compile("BUILDMAP-COMMIT(DLPR0_VSEL_OP_VDDK=4)")

        plan = self._compile(
            "BUILDMAP-COMMIT(DLPR0_VSEL_OP_VDDK=1)-PGMOTP"
        )

        commit = plan.operations[1]
        self.assertEqual(commit.effective_pages, ("trim1",))
        self.assertEqual(
            [(write.field, write.page, write.register, write.lsb, write.width,
              write.value.kind, write.value.token)
             for write in commit.field_writes],
            [("DLPR0_VSEL_OP_VDDK", "trim1", "ANA_MUX_TRIM2", 0, 2,
              "DECIMAL", "1")],
        )

    def test_bare_commit_uses_only_caller_supplied_node_default_bindings(self):
        defaults = (
            RecipeAssignment(
                field="DLPR0_VSEL_OP_VDDK",
                value=RecipeValueToken(kind="VARIABLE", token="DLPR0_DEFAULT"),
            ),
        )

        bare = self._compile("BUILDMAP-COMMIT-PGMOTP", node_default_bindings=defaults)
        overridden = self._compile(
            "BUILDMAP-COMMIT-COMMIT(DLPR0_VSEL_OP_VDDK=2)-PGMOTP",
            node_default_bindings=defaults,
        )

        self.assertEqual(bare.operations[1].field_writes[0].value.token, "DLPR0_DEFAULT")
        all_writes = [write for operation in overridden.operations
                      if operation.module == "COMMIT" for write in operation.field_writes]
        self.assertEqual([write.value.token for write in all_writes], ["DLPR0_DEFAULT", "2"])

        no_op = self._compile("BUILDMAP-COMMIT")
        self.assertEqual(no_op.operations[1].effective_pages, ())
        with self.assertRaisesRegex(PersistenceCompileError, "PGMOTP.*Pattern"):
            self._compile("BUILDMAP-COMMIT-PGMOTP")

    def test_commit_step_is_only_valid_in_shmoo_context(self):
        with self.assertRaisesRegex(PersistenceCompileError, "STEP.*shmoo"):
            self._compile(
                "BUILDMAP-COMMIT(DLPR0_VSEL_OP_VDDK=STEP)", flow_type="write"
            )

        plan = self._compile(
            "BUILDMAP-COMMIT(DLPR0_VSEL_OP_VDDK=STEP)", flow_type="shmoo"
        )

        self.assertEqual(plan.operations[1].field_writes[0].value.kind, "STEP")

    def test_builduid_may_appear_at_most_once_per_cp_and_inserts_nothing(self):
        with self.assertRaisesRegex(PersistenceCompileError, "BUILDUID.*每道 CP.*一次"):
            self._compile("BUILDUID-BUILDUID", flow_type="uid")

        plan = self._compile("BUILDUID", flow_type="uid")

        self.assertEqual([operation.module for operation in plan.operations], ["BUILDUID"])

    def _compile(
        self, recipe, *, flow_type="data", node_default_bindings=(),
        node_default_pages=("trim1",),
    ):
        flow = pd.DataFrame([{
            "CP NO": "CP1", "item": "Trimdata_Write_Read", "type": flow_type,
            "sub": "/", "Recipe": recipe,
        }])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        rows = compile_recipe_program(flow, pattern).functions[0].rows
        return compile_persistence_plan(
            rows,
            _catalog(),
            node_default_pages={2: tuple(node_default_pages)},
            node_default_bindings={2: tuple(node_default_bindings)},
        )


def _catalog():
    return compile_addr_map_catalog(pd.DataFrame([
        {
            "Word No.": "trim1", "line": "CP1,CP2", "bit[31:16]": "反码",
            "bit[15:0]": "ANA_MUX_TRIM2[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'hFFF9_0006",
            "CP addr map": "OTHER[13:4],DLPR1_VSEL_OP_VDDK[1:0],DLPR0_VSEL_OP_VDDK[1:0]",
        },
        {
            "Word No.": "uid", "line": "CP1,CP2", "bit[31:16]": "反码",
            "bit[15:0]": "UID_REG0[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'hFFFF_0000", "CP addr map": "UID_FIELD[15:0]",
        },
    ]))


if __name__ == "__main__":
    unittest.main()
