import unittest
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd

from program_gen.core.addr_map import compile_addr_map_catalog, storage_field_catalog
from program_gen.core.default_commit import compile_default_commit_bindings
from program_gen.core.project_mappings import (
    StorageMapping,
    StorageTarget,
    read_storage_mappings,
    read_verify_storage_mappings,
    validate_storage_mapping_records,
    validate_storage_role_occupancy,
    validate_storage_flow_occupancy,
    validate_storage_explicit_commits,
)


def _catalog(trim=(), verify=()):
    return compile_addr_map_catalog(pd.DataFrame([
        {
            "Word No.": "trim0", "line": "CP1", "bit[31:16]": "reserved",
            "bit[15:0]": "PMU_TRIM0[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'h00000000",
            "description": "{7'h0,BG_ABS_TRIM_VDDK[3:0],BG_TC_TRIM_VDDK[4:0]}",
            "CP addr map": "Vref0p8_ABS[3:0],VREF0P8_TC[4:0]",
        },
        {
            "Word No.": "trim1", "line": "CP1", "bit[31:16]": "reserved",
            "bit[15:0]": "CLK_TRIM0[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'h00000000",
            "description": "HSI_ABS_TRIMCR_VDDK[11:0]",
            "CP addr map": "Hsi_8M[11:0]",
        },
    ]), trim, verify)


class StorageFieldsTests(unittest.TestCase):
    def test_description_is_the_physical_catalog_and_constants_preserve_offsets(self):
        entries = storage_field_catalog(_catalog())
        self.assertEqual(
            [(entry.field, entry.lsb, entry.width, entry.source) for entry in entries],
            [
                ("BG_TC_TRIM_VDDK", 0, 5, "description"),
                ("BG_ABS_TRIM_VDDK", 5, 4, "description"),
                ("HSI_ABS_TRIMCR_VDDK", 0, 12, "description"),
            ],
        )

    def test_one_description_target_is_not_expanded_by_the_cp_addr_map_name(self):
        mapping = StorageMapping("Hsi_8M", (
            StorageTarget("trim1", "CLK_TRIM0", "HSI_ABS_TRIMCR_VDDK"),
        ))
        catalog = _catalog((mapping,))
        selected = catalog.selected_storage_fields("trim", "Hsi_8M")
        self.assertEqual([(field.name, field.register) for field in selected], [
            ("HSI_ABS_TRIMCR_VDDK", "CLK_TRIM0"),
        ])
        self.assertTrue(catalog.storage_field_reference(selected[0]).startswith("__STORAGE_R"))

    def test_buildmap_writes_the_selected_description_field_not_only_cp_addr_map_fields(self):
        from program_gen.core.flash_window import _compile_build_map
        mapping = StorageMapping("Vref0p8_TC", (
            StorageTarget("trim0", "PMU_TRIM0", "BG_TC_TRIM_VDDK"),
        ))
        catalog = _catalog((mapping,))
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8_TC", "type": "trim"},
            {"CP NO": "CP1", "item": "Build", "type": "write"},
        ])
        plan, _warnings = _compile_build_map(
            SimpleNamespace(cp="CP1", row=1), flow, catalog, None, None
        )
        writes = [write for register in plan.registers for write in register.writes]
        self.assertEqual([(write.field, write.lsb, write.width) for write in writes], [
            ("BG_TC_TRIM_VDDK", 0, 5),
        ])

    def test_verify_uses_measurement_result_target_not_trim_target(self):
        trim = StorageMapping("Vref0p8", (
            StorageTarget("trim0", "PMU_TRIM0", "BG_ABS_TRIM_VDDK"),
        ))
        verify = StorageMapping("Vref0p8", (
            StorageTarget("trim0", "PMU_TRIM0", "BG_TC_TRIM_VDDK"),
        ))
        catalog = _catalog((trim,), (verify,))
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8", "type": "verify", "OTP": "yes"},
            {"CP NO": "CP1", "item": "Trimdata_Rewrite", "type": "write", "OTP": "/"},
        ])
        rows = {1: SimpleNamespace(operations=(SimpleNamespace(name="COMMIT", assignments=()),))}
        bindings = compile_default_commit_bindings(flow, rows, catalog, export_symbols={0: "VREF_RESULT"})
        self.assertEqual(len(bindings[1]), 1)
        self.assertEqual(bindings[1][0].value.token, "VREF_RESULT")
        self.assertNotEqual(bindings[1][0].field, "BG_ABS_TRIM_VDDK")

    def test_empty_targets_explicitly_unlink_and_invalid_width_is_rejected(self):
        catalog = _catalog()
        unlinked = StorageMapping("Hsi_8M", ())
        self.assertEqual(validate_storage_mapping_records(
            "trim", (unlinked,), catalog,
            (SimpleNamespace(item="Hsi_8M", cp="CP1", required_bits=12),),
        ), (unlinked,))
        too_narrow = StorageMapping("Hsi_8M", (
            StorageTarget("trim0", "PMU_TRIM0", "BG_ABS_TRIM_VDDK"),
        ))
        with self.assertRaisesRegex(ValueError, "小于所需位宽"):
            validate_storage_mapping_records(
                "trim", (too_narrow,), catalog,
                (SimpleNamespace(item="Hsi_8M", cp="CP1", required_bits=12),),
            )

    def test_trim_and_verify_cannot_claim_the_same_physical_bits(self):
        target = StorageTarget("trim0", "PMU_TRIM0", "BG_ABS_TRIM_VDDK")
        catalog = _catalog((StorageMapping("Trim", (target,)),), (StorageMapping("Verify", (target,)),))
        with self.assertRaisesRegex(ValueError, "存储字段重叠"):
            validate_storage_role_occupancy(catalog)

    def test_v3_groups_preserve_explicit_empty_unlink_and_v2_migrates(self):
        def workbook(document):
            output = BytesIO()
            with ZipFile(output, "w") as archive:
                archive.writestr("mcu/mappings.json", document)
            return output.getvalue()
        v3 = workbook('{"version":3,"trimStorage":[{"item":"Hsi_8M","targets":[]}],"verifyStorage":[{"item":"Vref","targets":[{"page":"trim0","register":"PMU_TRIM0","field":"BG_TC_TRIM_VDDK"}]}]}')
        self.assertEqual(read_storage_mappings(v3), (StorageMapping("Hsi_8M", ()),))
        self.assertEqual(read_verify_storage_mappings(v3)[0].targets[0].field, "BG_TC_TRIM_VDDK")
        v2 = workbook('{"version":2,"trimStorage":[{"item":"Hsi_8M","page":"trim1","register":"CLK_TRIM0","field":"Hsi_8M"}]}')
        self.assertEqual(read_storage_mappings(v2)[0].targets[0].register, "CLK_TRIM0")

    def test_explicit_verify_target_conflicts_with_an_unmapped_legacy_trim(self):
        catalog = _catalog((), (StorageMapping("Result", (
            StorageTarget("trim0", "PMU_TRIM0", "BG_ABS_TRIM_VDDK"),
        )),))
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8_ABS", "type": "trim"},
            {"CP NO": "CP1", "item": "Result", "type": "verify"},
        ])
        with self.assertRaisesRegex(ValueError, "存储字段重叠"):
            validate_storage_flow_occupancy(flow, catalog)

    def test_explicit_commit_cannot_write_a_mapped_verify_field_from_another_symbol(self):
        from flow_recipe import RecipeAssignment, RecipeValueToken
        mapping = StorageMapping("Vref", (
            StorageTarget("trim0", "PMU_TRIM0", "BG_TC_TRIM_VDDK"),
        ))
        catalog = _catalog((), (mapping,))
        sources = (SimpleNamespace(item="Vref", symbol="VREF_RESULT"),)
        rows = {0: SimpleNamespace(operations=(SimpleNamespace(
            name="COMMIT", assignments=(RecipeAssignment("BG_TC_TRIM_VDDK", RecipeValueToken("VARIABLE", "OTHER")),),
        ),))}
        with self.assertRaisesRegex(ValueError, "其他值"):
            validate_storage_explicit_commits(catalog, {}, sources, rows)

    def test_cp_addr_alias_expansion_cannot_write_an_unselected_physical_copy(self):
        from flow_recipe import RecipeAssignment, RecipeValueToken
        frame = pd.DataFrame([
            {"Word No.": "trim0", "line": "CP1", "bit[31:16]": "reserved", "bit[15:0]": "R0[15:0]", "data type": "lable", "CP Data[31:0]": "32'h0", "description": "PHYSICAL_A[4:0]", "CP addr map": "ALIAS[4:0]"},
            {"Word No.": "trim1", "line": "CP1", "bit[31:16]": "reserved", "bit[15:0]": "R1[15:0]", "data type": "lable", "CP Data[31:0]": "32'h0", "description": "PHYSICAL_B[4:0]", "CP addr map": "ALIAS[4:0]"},
        ])
        catalog = compile_addr_map_catalog(frame, (), (StorageMapping("Result", (
            StorageTarget("trim0", "R0", "PHYSICAL_A"),
        )),))
        sources = (SimpleNamespace(item="Result", symbol="RESULT_EXPORT"),)
        rows = {0: SimpleNamespace(operations=(SimpleNamespace(
            name="COMMIT", assignments=(RecipeAssignment("ALIAS", RecipeValueToken("VARIABLE", "RESULT_EXPORT")),),
        ),))}
        with self.assertRaisesRegex(ValueError, "必须同时写入"):
            validate_storage_explicit_commits(catalog, {}, sources, rows)

    def test_explicit_verify_unlink_suppresses_automatic_uid_requirement(self):
        from flow_recipe import ResultExportPlan, ResultExportPlanSet
        from program_gen.core.persistence_recipe import PersistencePlanSet
        from program_gen.core.result_binding import compile_product_result_bindings
        export = ResultExportPlan(0, "Vref", "/", "verify", "MEASUREMENT", "BCD16_MV", "VREF_EXPORT", "int", False, True, True)
        plan = compile_product_result_bindings(
            {"CP1": ResultExportPlanSet((export,))}, PersistencePlanSet({}),
            explicitly_unlinked_verify_items=("Vref",),
        )
        self.assertEqual(plan.bindings[0].targets, ())


if __name__ == "__main__":
    unittest.main()
