import unittest
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd

from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.project_mappings import (
    MAPPINGS_PART,
    ProjectMappingsError,
    StorageMapping,
    StorageTarget,
    TrimStorageMapping,
    parse_trim_storage_mappings,
    read_storage_mappings,
    validate_trim_storage_mappings,
)


class ProjectMappingsTests(unittest.TestCase):
    def test_explicit_commit_requires_every_global_target_with_same_value(self):
        from flow_recipe import RecipeAssignment, RecipeValueToken
        mappings = (
            TrimStorageMapping('Vref0p8', 'trim0', 'PMU_TRIM0', 'TRM_VREF'),
            TrimStorageMapping('Vref0p8', 'trim0', 'PMU_TRIM0', 'TRM_OTHER'),
        )
        spec = SimpleNamespace(cp='CP1', item='Vref0p8', search=SimpleNamespace(search_bits=5),
                               dac_final_symbol='VREF0P8_DAC_FINAL')
        rows = {1: SimpleNamespace(flow=SimpleNamespace(cp='CP1'), operations=[SimpleNamespace(
            name='COMMIT', assignments=[RecipeAssignment('TRM_VREF', RecipeValueToken('VARIABLE', 'VREF0P8_DAC_FINAL'))])])}
        flow = pd.DataFrame([{'CP NO':'CP1','item':'Vref0p8','type':'trim'}])
        with self.assertRaisesRegex(ProjectMappingsError, '必须同时写入全部'):
            validate_trim_storage_mappings(mappings, flow, _catalog(mappings), {0:spec}, rows)

    def test_trim_storage_mapping_is_a_global_typed_immutable_record(self):
        mapping = TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF")

        self.assertEqual(mapping.item, "Vref0p8")
        self.assertEqual(mapping.field, "TRM_VREF")

    def test_json_part_is_optional_and_v2_is_strict(self):
        self.assertEqual(read_storage_mappings(_workbook_bytes()), ())
        raw = _workbook_bytes('{"version":2,"trimStorage":[{"item":"Vref0p8","page":"trim0","register":"PMU_TRIM0","field":"TRM_VREF"}]}')
        self.assertEqual(read_storage_mappings(raw), (
            StorageMapping("Vref0p8", (StorageTarget("trim0", "PMU_TRIM0", "TRM_VREF"),)),
        ))
        with self.assertRaisesRegex(ProjectMappingsError, "对象数组"):
            parse_trim_storage_mappings({})
        with self.assertRaisesRegex(ProjectMappingsError, "只能包含"):
            parse_trim_storage_mappings([{"item": "x", "page": "p", "register": "r", "field": "f", "extra": "x"}])

    def test_v1_single_cp_mapping_promotes_to_a_global_mapping(self):
        raw = _workbook_bytes('{"version":1,"trimStorage":[{"cp":"CP1","item":"Vref0p8","page":"trim0","register":"PMU_TRIM0","field":"TRM_VREF"}]}')
        self.assertEqual(read_storage_mappings(raw), (
            StorageMapping("Vref0p8", (StorageTarget("trim0", "PMU_TRIM0", "TRM_VREF"),)),
        ))

    def test_v1_different_cp_target_sets_are_rejected(self):
        raw = _workbook_bytes('{"version":1,"trimStorage":[{"cp":"CP1","item":"Vref0p8","page":"trim0","register":"PMU_TRIM0","field":"TRM_VREF"},{"cp":"CP2","item":"Vref0p8","page":"trim0","register":"PMU_TRIM0","field":"TRM_OTHER"}]}')
        with self.assertRaisesRegex(ProjectMappingsError, "无法提升"):
            read_storage_mappings(raw)

    def test_global_mapping_replaces_legacy_matching_for_every_cp_and_has_two_targets(self):
        mappings = (
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_OTHER"),
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF"),
        )
        catalog = _catalog(mappings)
        vref, other = catalog.resolve_fields("TRM_VREF")[0], catalog.resolve_fields("TRM_OTHER")[0]

        self.assertTrue(catalog.matches_trim("CP1", "Vref0p8", vref))
        self.assertTrue(catalog.matches_trim("CP2", "Vref0p8", other))
        self.assertTrue(catalog.matches_trim("CP2", "Vref0p8", vref))

    def test_no_mapping_keeps_legacy_cross_cp_name_matching(self):
        catalog = compile_addr_map_catalog(pd.DataFrame([{
            "Word No.": "trim0", "line": "CP2",
            "bit[31:16]": "reserved", "bit[15:0]": "PMU_TRIM0[15:0]",
            "data type": "lable", "CP Data[31:0]": "32'h00000000",
            "CP addr map": "TRM_VREF[4:0]",
        }]))

        self.assertTrue(catalog.matches_trim(
            "CP1", "Vref", catalog.resolve_field("TRM_VREF")
        ))

    def test_validation_rejects_a_narrow_explicit_target(self):
        mapping = TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF")
        spec = SimpleNamespace(cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=6), dac_final_symbol="VREF0P8_DAC_FINAL")
        flow = pd.DataFrame([{"CP NO": "CP1", "item": "Vref0p8", "type": "trim"}])

        with self.assertRaisesRegex(ProjectMappingsError, "小于所需位宽"):
            validate_trim_storage_mappings((mapping,), flow, _catalog((mapping,)), {0: spec}, {})

    def test_same_explicit_target_as_legacy_is_valid(self):
        mapping = TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF")
        spec = SimpleNamespace(
            cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=5),
            dac=SimpleNamespace(field_width=5), dac_final_symbol="VREF0P8_DAC_FINAL",
        )
        flow = pd.DataFrame([{"CP NO": "CP1", "item": "Vref0p8", "type": "trim"}])

        self.assertEqual(
            validate_trim_storage_mappings((mapping,), flow, _catalog((mapping,)), {0: spec}, {}),
            (mapping,),
        )

    def test_global_targets_validate_every_producing_cp_and_reject_duplicate_target(self):
        mappings = (
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF"),
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF"),
        )
        specs = {
            0: SimpleNamespace(cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=5), dac_final_symbol="VREF0P8_DAC_FINAL"),
            1: SimpleNamespace(cp="CP2", item="Vref0p8", search=SimpleNamespace(search_bits=5), dac_final_symbol="VREF0P8_DAC_FINAL"),
        }
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8", "type": "trim"},
            {"CP NO": "CP2", "item": "Vref0p8", "type": "trim"},
        ])
        with self.assertRaisesRegex(ProjectMappingsError, "重复"):
            validate_trim_storage_mappings(mappings, flow, _catalog(mappings), specs, {})

    def test_global_two_targets_apply_to_every_producing_cp(self):
        mappings = (
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF"),
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_OTHER"),
        )
        specs = {
            0: SimpleNamespace(cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=5), dac_final_symbol="VREF0P8_DAC_FINAL"),
            1: SimpleNamespace(cp="CP2", item="Vref0p8", search=SimpleNamespace(search_bits=5), dac_final_symbol="VREF0P8_DAC_FINAL"),
        }
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8", "type": "trim"},
            {"CP NO": "CP2", "item": "Vref0p8", "type": "trim"},
        ])
        self.assertEqual(
            validate_trim_storage_mappings(mappings, flow, _catalog(mappings), specs, {}),
            mappings,
        )

    def test_default_commit_emits_every_unique_global_target_field(self):
        from program_gen.core.default_commit import compile_default_commit_bindings
        from flow_recipe import RecipeCall
        mappings = (
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF"),
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_OTHER"),
        )
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8", "type": "trim", "OTP": "yes"},
            {"CP NO": "CP1", "item": "Trimdata_Write", "type": "data"},
        ])
        rows = {1: SimpleNamespace(
            flow=SimpleNamespace(cp="CP1"), operations=(RecipeCall("COMMIT"),),
        )}
        catalog = _catalog(mappings)
        assignments = compile_default_commit_bindings(flow, rows, catalog)[1]
        self.assertEqual({field.name for assignment in assignments
                          for field in catalog.resolve_fields(assignment.field)}, {"TRM_VREF", "TRM_OTHER"})
        self.assertTrue(all(len(catalog.resolve_fields(assignment.field)) == 1 for assignment in assignments))

    def test_uid_and_trim_copy_are_one_global_hsi_assignment(self):
        from program_gen.core.default_commit import compile_default_commit_bindings
        from flow_recipe import RecipeCall
        mappings = (
            TrimStorageMapping("Hsi_8M", "uid", "Hsi_8M_Trim", "Hsi_8M"),
            TrimStorageMapping("Hsi_8M", "trim1", "CLK_TRIM0", "Hsi_8M"),
        )
        specs = {
            0: SimpleNamespace(cp="CP1", item="Hsi_8M", search=SimpleNamespace(search_bits=5), dac_final_symbol="HSI_8M_DAC_FINAL"),
            1: SimpleNamespace(cp="CP3", item="Hsi_8M", search=SimpleNamespace(search_bits=5), dac_final_symbol="HSI_8M_DAC_FINAL"),
        }
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Hsi_8M", "type": "trim", "OTP": "yes"},
            {"CP NO": "CP3", "item": "Hsi_8M", "type": "trim", "OTP": "yes"},
            {"CP NO": "CP1", "item": "Trimdata_Write", "type": "data"},
        ])
        catalog = _hsi_catalog(mappings)
        self.assertEqual(validate_trim_storage_mappings(mappings, flow, catalog, specs, {}), mappings)
        rows = {2: SimpleNamespace(
            flow=SimpleNamespace(cp="CP1"), operations=(RecipeCall("COMMIT"),),
        )}
        assignments = compile_default_commit_bindings(flow, rows, catalog)[2]
        self.assertEqual(len(assignments), 2)
        self.assertTrue(all(assignment.field.startswith("__STORAGE_R") for assignment in assignments))

    def test_explicit_commit_in_another_cp_cannot_overwrite_global_target(self):
        from flow_recipe import RecipeAssignment, RecipeValueToken
        mapping = TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF")
        spec = SimpleNamespace(cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=5),
                               dac_final_symbol="VREF0P8_DAC_FINAL")
        flow = pd.DataFrame([{"CP NO": "CP1", "item": "Vref0p8", "type": "trim"}])
        rows = {1: SimpleNamespace(flow=SimpleNamespace(cp="CP2"), operations=(SimpleNamespace(
            name="COMMIT", assignments=(RecipeAssignment("TRM_VREF", RecipeValueToken("VARIABLE", "OTHER")),),
        ),))}
        with self.assertRaisesRegex(ProjectMappingsError, "其他值"):
            validate_trim_storage_mappings((mapping,), flow, _catalog((mapping,)), {0: spec}, rows)

    def test_explicit_multi_copy_dac_write_uses_the_only_restored_copy(self):
        from program_gen.core.dac_write import _compile_source
        mappings = _read_mappings()
        source = _compile_source(
            SimpleNamespace(value_source="ADDR_MAP", item="Vref0p8", dac_symbol="VREF", flow_row_index=10),
            _read_catalog(mappings), "CP1", _persistence("trim1"), None,
        )
        self.assertEqual((source.page, source.register_symbol), ("trim1", "REG_TRIM1"))

    def test_explicit_multi_copy_dac_write_rejects_when_no_copy_is_restored(self):
        from program_gen.core.dac_write import DacWriteCompileError, _compile_source
        with self.assertRaisesRegex(DacWriteCompileError, "NOT_RESTORED"):
            _compile_source(
                SimpleNamespace(value_source="ADDR_MAP", item="Vref0p8", dac_symbol="VREF", flow_row_index=10),
                _read_catalog(_read_mappings()), "CP1", _persistence(), None,
            )

    def test_explicit_multi_copy_reads_choose_stable_copy_and_reject_unequal_widths(self):
        from program_gen.core.dac_adjust import DacAdjustActionPlanError, _target_source
        from program_gen.core.dac_write import DacWriteCompileError, _compile_source
        mappings = _read_mappings()
        catalog = _read_catalog(mappings)
        plan = SimpleNamespace(value_source="ADDR_MAP", item="Vref0p8", dac_symbol="VREF", flow_row_index=10)
        self.assertEqual(_compile_source(plan, catalog, "CP1", _persistence("trim0", "trim1"), None).page, "trim0")
        adjusted = _target_source(SimpleNamespace(cp="CP1", row=10), "Vref0p8", "VREF", (), catalog, _persistence("trim1"))
        self.assertEqual(adjusted.page, "trim1")
        with self.assertRaisesRegex(DacWriteCompileError, "MULTI_COPY_INCOMPATIBLE"):
            _compile_source(plan, _read_catalog(mappings, other_width=6), "CP1", _persistence("trim0"), None)
        with self.assertRaisesRegex(DacAdjustActionPlanError, "MULTI_COPY_INCOMPATIBLE"):
            _target_source(SimpleNamespace(cp="CP1", row=10), "Vref0p8", "VREF", (),
                           _read_catalog(mappings, other_width=6), _persistence("trim0"))

    def test_legacy_adjust_ignores_uid_copy_and_keeps_unique_non_uid_requirement(self):
        from program_gen.core.dac_adjust import _target_source
        from program_gen.core.default_commit import compile_default_commit_bindings
        from flow_recipe import FlowCompileError, RecipeCall
        catalog = _hsi_catalog()
        source = _target_source(SimpleNamespace(cp="CP1", row=10), "Hsi_8M", "HSI", (),
                                catalog, _persistence("trim1"))
        self.assertEqual(source.page, "trim1")
        flow = pd.DataFrame([{"CP NO":"CP1", "item":"Adjust", "type":"adjust"}])
        rows = {0: SimpleNamespace(operations=(
            SimpleNamespace(name="DAC_ADJ", value="A<0.4:Hsi_8M+2"), RecipeCall("COMMIT"),
        ))}
        self.assertEqual(len(compile_default_commit_bindings(flow, rows, catalog)[0]), 1)
        catalog.resolve_register("Hsi_8M_Trim").page = "trim0"
        with self.assertRaisesRegex(FlowCompileError, "唯一"):
            compile_default_commit_bindings(flow, rows, catalog)

    def test_no_mapping_multi_copy_read_keeps_legacy_ambiguity_error(self):
        from program_gen.core.dac_write import DacWriteCompileError, _compile_source
        with self.assertRaisesRegex(DacWriteCompileError, "ADDR_MAP_AMBIGUOUS"):
            _compile_source(
                SimpleNamespace(value_source="ADDR_MAP", item="Hsi_8M", dac_symbol="HSI", flow_row_index=10),
                _hsi_catalog(), "CP1", _persistence("uid", "trim1"), None,
            )

    def test_explicit_target_cannot_overlap_another_implicit_trim(self):
        mapping = TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_OTHER")
        spec = SimpleNamespace(
            cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=5),
            dac=SimpleNamespace(field_width=5), dac_final_symbol="VREF0P8_DAC_FINAL",
        )
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8", "type": "trim"},
            {"CP NO": "CP1", "item": "Other", "type": "trim"},
        ])

        with self.assertRaisesRegex(ProjectMappingsError, "字段重叠"):
            validate_trim_storage_mappings((mapping,), flow, _catalog((mapping,)), {0: spec}, {})

    def test_global_target_cannot_collide_with_legacy_trim_in_another_cp(self):
        mapping = TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_OTHER")
        spec = SimpleNamespace(
            cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=5),
            dac=SimpleNamespace(field_width=5), dac_final_symbol="VREF0P8_DAC_FINAL",
        )
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8", "type": "trim"},
            {"CP NO": "CP2", "item": "Other", "type": "trim"},
        ])
        with self.assertRaisesRegex(ProjectMappingsError, "字段重叠"):
            validate_trim_storage_mappings((mapping,), flow, _catalog((mapping,)), {0: spec}, {})

    def test_global_target_collision_is_rejected_even_when_items_produce_in_different_cps(self):
        mappings = (
            TrimStorageMapping("Vref0p8", "trim0", "PMU_TRIM0", "TRM_VREF"),
            TrimStorageMapping("Other", "trim0", "PMU_TRIM0", "TRM_VREF"),
        )
        specs = {
            0: SimpleNamespace(cp="CP1", item="Vref0p8", search=SimpleNamespace(search_bits=5), dac_final_symbol="VREF0P8_DAC_FINAL"),
            1: SimpleNamespace(cp="CP2", item="Other", search=SimpleNamespace(search_bits=5), dac_final_symbol="OTHER_DAC_FINAL"),
        }
        flow = pd.DataFrame([
            {"CP NO": "CP1", "item": "Vref0p8", "type": "trim"},
            {"CP NO": "CP2", "item": "Other", "type": "trim"},
        ])
        with self.assertRaisesRegex(ProjectMappingsError, "字段重叠"):
            validate_trim_storage_mappings(mappings, flow, _catalog(mappings), specs, {})


def _workbook_bytes(mapping_json=None):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        if mapping_json is not None:
            archive.writestr(MAPPINGS_PART, mapping_json)
    return output.getvalue()


def _catalog(mappings=()):
    return compile_addr_map_catalog(pd.DataFrame([{
        "Word No.": "trim0",
        "line": "",
        "bit[31:16]": "reserved",
        "bit[15:0]": "PMU_TRIM0[15:0]",
        "data type": "lable",
        "CP Data[31:0]": "32'h00000000",
        "CP addr map": "TRM_VREF[4:0],TRM_OTHER[10:5]",
    }]), tuple(mappings))


def _hsi_catalog(mappings=()):
    return compile_addr_map_catalog(pd.DataFrame([
        {
            "Word No.": "uid", "line": "",
            "bit[31:16]": "reserved", "bit[15:0]": "Hsi_8M_Trim[15:0]",
            "data type": "lable", "CP Data[31:0]": "32'h00000000",
            "CP addr map": "Hsi_8M[4:0]",
        },
        {
            "Word No.": "trim1", "line": "",
            "bit[31:16]": "reserved", "bit[15:0]": "CLK_TRIM0[15:0]",
            "data type": "lable", "CP Data[31:0]": "32'h00000000",
            "CP addr map": "Hsi_8M[4:0]",
        },
    ]), tuple(mappings))


def _read_mappings():
    return (
        TrimStorageMapping("Vref0p8", "trim0", "TRIM0", "TRM_VREF"),
        TrimStorageMapping("Vref0p8", "trim1", "TRIM1", "TRM_OTHER"),
    )


def _read_catalog(mappings=(), *, other_width=5):
    return compile_addr_map_catalog(pd.DataFrame([
        {
            "Word No.": "trim0", "line": "",
            "bit[31:16]": "reserved", "bit[15:0]": "TRIM0[15:0]",
            "data type": "lable", "CP Data[31:0]": "32'h00000000",
            "CP addr map": "TRM_VREF[4:0]",
        },
        {
            "Word No.": "trim1", "line": "",
            "bit[31:16]": "reserved", "bit[15:0]": "TRIM1[15:0]",
            "data type": "lable", "CP Data[31:0]": "32'h00000000",
            "CP addr map": f"TRM_OTHER[{other_width - 1}:0]",
        },
    ]), tuple(mappings))


def _persistence(*pages):
    operations = tuple(
        SimpleNamespace(module="READOTPMAP", requested_pages=(page,), effective_pages=(), excel_row=index + 2)
        for index, page in enumerate(pages)
    )
    return SimpleNamespace(rows={0: SimpleNamespace(cp="CP1", operations=operations)})


if __name__ == "__main__":
    unittest.main()
