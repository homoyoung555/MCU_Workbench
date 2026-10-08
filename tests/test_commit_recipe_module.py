import unittest

import pandas as pd

from flow_recipe import RecipeValueToken
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.commit_module import (
    compile_commit_module_plan,
    compile_commit_module_plans,
)
from program_gen.core.flash_label_plan import compile_flash_label_contract
from program_gen.core.persistence_recipe import (
    PersistenceFieldWrite,
    PersistenceOperation,
    PersistencePlanSet,
    PersistenceRowPlan,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY


class CommitRecipeModuleTests(unittest.TestCase):
    def test_chroma_runtime_rmw_refreshes_only_the_touched_register_patterns(self):
        catalog = _catalog()
        plan = compile_commit_module_plan(
            _operation(), catalog, cp="CP1", swd_pin="PA13",
            flash_labels=compile_flash_label_contract(catalog),
        )

        emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", plan, "chroma")
        source = "\n".join(emission.statements)

        self.assertIn(
            "REG_ANA_MUX_TRIM2[SOCKET]=(REG_ANA_MUX_TRIM2[SOCKET]&0xFFFC)"
            "|((1&0x3)<<0);",
            source,
        )
        self.assertIn(
            "convert_to_string(REG_ANA_MUX_TRIM2[SOCKET],16,"
            "BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
            source,
        )
        self.assertIn(
            "fbist_page_prog_trim1:ana_mux_trim2_w_p+I,,BUFF_W_P[I]", source
        )
        self.assertIn(
            "fbist_page_read_trim1:ana_mux_trim2_r_n+I,,BUFF_R_N[I]", source
        )
        self.assertNotIn("for(J=15;J>=0;J--)", source)
        self.assertEqual(
            tuple(item.logical_identity for item in emission.resource_requires),
            (
                "pattern:fbist_page_prog_trim1",
                "pattern:fbist_page_read_trim1",
            ),
        )
        self.assertNotIn("JUDGE_PAT(", source)

    def test_s100_refresh_prepares_complement_once_without_restoring_register(self):
        operation = _operation(RecipeValueToken("VARIABLE", "VALUE_EXPORT"))
        catalog = _catalog()
        plan = compile_commit_module_plan(
            operation, catalog, cp="CP1", swd_pin="PA13",
            flash_labels=compile_flash_label_contract(catalog),
        )

        emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", plan, "s100")
        source = "\n".join(emission.statements)

        self.assertIn("((VALUE_EXPORT[T_SOCKET]&0x3)<<0);", source)
        self.assertEqual(
            source.count("CALL_MACRO Bitwise_not_arry(REG_ANA_MUX_TRIM2);"),
            1,
        )
        self.assertIn(
            "fbist_page_prog_trim1:ana_mux_trim2_w_p_st", source
        )
        self.assertIn(
            "fbist_page_read_trim1:ana_mux_trim2_r_n_sp", source
        )
        self.assertNotIn("RUN_PATTERN(", source)

    def test_product_level_compiler_preserves_each_commit_occurrence_per_row(self):
        first = _operation()
        second = _operation(RecipeValueToken("DECIMAL", "2"))
        persistence = PersistencePlanSet({
            0: PersistenceRowPlan("CP1", 2, (first, second)),
        })

        catalog = _catalog()
        plans = compile_commit_module_plans(
            persistence, catalog, swd_pin="PA13",
            flash_labels=compile_flash_label_contract(catalog),
        )

        self.assertEqual(len(plans[0]), 2)
        self.assertEqual(
            tuple(plan.writes[0].value.token for plan in plans[0]),
            ("1", "2"),
        )

    def test_uid_register_without_complement_uses_cp_pattern_and_plain_labels(self):
        catalog = compile_addr_map_catalog(pd.DataFrame([{
            "Word No.": "uid", "line": "CP1", "bit[31:16]": "16'h0000",
            "bit[15:0]": "HSI_8M_TRIM[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'h0000_0000", "CP addr map": "VALUE[15:0]",
        }]))
        operation = PersistenceOperation(
            "COMMIT", 2, ("uid",), ("uid",),
            (PersistenceFieldWrite(
                "VALUE", "uid", "HSI_8M_TRIM", 0, 16,
                RecipeValueToken("HEX", "0x1234"),
            ),),
            "EXPLICIT",
        )
        plan = compile_commit_module_plan(
            operation, catalog, cp="CP1", swd_pin="PA13",
            flash_labels=compile_flash_label_contract(catalog),
        )

        chroma = "\n".join(
            NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", plan, "chroma").statements
        )
        s100 = "\n".join(
            NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", plan, "s100").statements
        )

        self.assertIn("fbist_page_prog_cp1_id:hsi_8m_trim_w+I,,BUFF_W_P[I]", chroma)
        self.assertNotIn("hsi_8m_trimw", chroma)
        self.assertIn("REG_HSI_8M_TRIM[SOCKET]=(0x1234&0xFFFF);", chroma)
        self.assertNotIn("REG_HSI_8M_TRIM[SOCKET]=(REG_HSI_8M_TRIM", chroma)
        self.assertIn("fbist_page_read_cp1_id:hsi_8m_trim_r_st", s100)
        self.assertNotIn("Bitwise_not_arry", s100)
        self.assertIn("REG_HSI_8M_TRIM[T_SOCKET]=(0x1234&0xFFFF);", s100)
        self.assertNotIn("REG_HSI_8M_TRIM[T_SOCKET]=(REG_HSI_8M_TRIM", s100)


def _operation(value=RecipeValueToken("DECIMAL", "1")):
    return PersistenceOperation(
        module="COMMIT",
        excel_row=2,
        requested_pages=("trim1",),
        effective_pages=("trim1",),
        field_writes=(PersistenceFieldWrite(
            field="DLPR0_VSEL_OP_VDDK",
            page="trim1",
            register="ANA_MUX_TRIM2",
            lsb=0,
            width=2,
            value=value,
        ),),
        commit_source="EXPLICIT",
    )


def _catalog():
    return compile_addr_map_catalog(pd.DataFrame([{
        "Word No.": "trim1",
        "line": "CP1,CP2",
        "bit[31:16]": "反码",
        "bit[15:0]": "ANA_MUX_TRIM2[15:0]",
        "data type": "lable",
        "CP Data[31:0]": "32'hFFF9_0006",
        "CP addr map": (
            "OTHER[13:4],DLPR1_VSEL_OP_VDDK[1:0],"
            "DLPR0_VSEL_OP_VDDK[1:0]"
        ),
    }]))


if __name__ == "__main__":
    unittest.main()
