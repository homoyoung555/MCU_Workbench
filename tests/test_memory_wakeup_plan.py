import unittest

import pandas as pd

from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.memory_wakeup import (
    DacValueSourceKind,
    MemoryWakeupCompileError,
    MemoryWakeupOperationKind,
    compile_memory_wakeup_plan,
)
from program_gen.core.trim_data import compile_trim_data_plan


def _addr_map_frame():
    return pd.DataFrame(
        [
            {
                "Word No.": "trim0",
                "line": "CP1,CP2",
                "bit[31:16]": "REG_TRIM0[15:0] complement",
                "bit[15:0]": "REG_TRIM0[15:0]",
                "data type": "lable",
                "CP Data[31:0]": "32'hFFFF_0000",
                "CP addr map": "Vposp[3:0],Iref1U[3:0]",
            }
        ]
    )


def _flow_frame():
    return pd.DataFrame(
        [
            {"CP NO": "CP1", "item": "Vposp", "type": "trim", "DAC bit": 4, "PUMP": "yes"},
            {"CP NO": "CP1", "item": "Iref1U", "type": "trim", "DAC bit": 4, "PUMP": "no"},
        ]
    )


class MemoryWakeupPlanTests(unittest.TestCase):
    def test_memory_wakeup_plan_is_cp1_only(self):
        with self.assertRaisesRegex(MemoryWakeupCompileError, "只允许 CP1"):
            compile_memory_wakeup_plan(
                compile_trim_data_plan(_flow_frame()),
                compile_addr_map_catalog(_addr_map_frame()),
                cp="CP2",
            )

    def test_compiles_cp1_memory_wakeup_as_three_explicit_operations(self):
        plan = compile_memory_wakeup_plan(
            compile_trim_data_plan(_flow_frame()),
            compile_addr_map_catalog(_addr_map_frame()),
            cp="CP1",
        )

        self.assertEqual(
            tuple(operation.kind for operation in plan.operations),
            (
                MemoryWakeupOperationKind.BUILDMAP,
                MemoryWakeupOperationKind.SETVPOSP,
                MemoryWakeupOperationKind.NMLOOP,
            ),
        )
        self.assertFalse(plan.build_map.loads_pattern)
        self.assertFalse(plan.build_map.runs_pattern)
        self.assertFalse(plan.set_vposp.runs_pattern)
        self.assertFalse(plan.nm_loop.runs_set_all_final_vposp)
        self.assertTrue(plan.nm_loop.runs_nm_erase_program_read)

    def test_buildmap_binds_all_cp_trim_fields_and_setvposp_only_binds_pumps(self):
        plan = compile_memory_wakeup_plan(
            compile_trim_data_plan(_flow_frame()),
            compile_addr_map_catalog(_addr_map_frame()),
            cp="CP1",
        )

        self.assertEqual(
            [binding.item for binding in plan.build_map.field_bindings],
            ["Vposp", "Iref1U"],
        )
        vposp_build = plan.build_map.field_bindings[0]
        self.assertEqual(vposp_build.dac_final_symbol, "VPOSP_DAC_FINAL")
        self.assertEqual(vposp_build.field.register, "REG_TRIM0")
        self.assertEqual((vposp_build.field.lsb, vposp_build.field.width), (4, 4))

        self.assertEqual([pump.item for pump in plan.set_vposp.pumps], ["Vposp"])
        pump = plan.set_vposp.pumps[0]
        self.assertEqual(
            tuple(source.kind for source in pump.sources),
            (DacValueSourceKind.CURRENT_DAC_FINAL, DacValueSourceKind.RESTORED_REG),
        )
        self.assertEqual(pump.sources[0].symbol, "VPOSP_DAC_FINAL")
        self.assertEqual(pump.sources[1].register, "REG_TRIM0")
        self.assertEqual((pump.sources[1].lsb, pump.sources[1].width), (4, 4))
        self.assertEqual(
            pump.select_source(current_dac_final_available=True, restored_reg_available=True).kind,
            DacValueSourceKind.CURRENT_DAC_FINAL,
        )
        self.assertEqual(
            pump.select_source(current_dac_final_available=False, restored_reg_available=True).kind,
            DacValueSourceKind.RESTORED_REG,
        )
        with self.assertRaisesRegex(MemoryWakeupCompileError, "Vposp.*没有可用"):
            pump.select_source(
                current_dac_final_available=False,
                restored_reg_available=False,
            )

    def test_buildmap_and_pump_restore_preserve_all_repeated_field_locations(self):
        addr_map = pd.concat(
            [
                _addr_map_frame(),
                pd.DataFrame(
                    [
                        {
                            "Word No.": "uid",
                            "line": "CP1",
                            "bit[31:16]": "REG_UID[15:0] complement",
                            "bit[15:0]": "REG_UID[15:0]",
                            "data type": "lable",
                            "CP Data[31:0]": "32'hFFFF_0000",
                            "CP addr map": "Iref1U[3:0]",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        plan = compile_memory_wakeup_plan(
            compile_trim_data_plan(_flow_frame()),
            compile_addr_map_catalog(addr_map),
            cp="CP1",
        )
        self.assertEqual(
            [(binding.item, binding.field.page) for binding in plan.build_map.field_bindings],
            [("Vposp", "trim0"), ("Iref1U", "trim0"), ("Iref1U", "uid")],
        )

        duplicate_pump = addr_map.copy()
        duplicate_pump.loc[1, "CP addr map"] = "Vposp[3:0],Iref1U[3:0]"
        duplicate_plan = compile_memory_wakeup_plan(
            compile_trim_data_plan(_flow_frame()),
            compile_addr_map_catalog(duplicate_pump),
            cp="CP1",
        )
        pump = duplicate_plan.set_vposp.pumps[0]
        self.assertEqual(
            [source.register for source in pump.restored_sources],
            ["REG_TRIM0", "REG_UID"],
        )
        self.assertEqual(
            pump.select_source(
                current_dac_final_available=True, restored_reg_available=True
            ).kind,
            DacValueSourceKind.CURRENT_DAC_FINAL,
        )
        with self.assertRaisesRegex(MemoryWakeupCompileError, "多个 REG fallback"):
            pump.select_source(
                current_dac_final_available=False, restored_reg_available=True
            )
        self.assertEqual(
            pump.select_restored_source({"REG_TRIM0": 3, "REG_UID": 3}).register,
            "REG_TRIM0",
        )
        with self.assertRaisesRegex(MemoryWakeupCompileError, "值不一致"):
            pump.select_restored_source({"REG_TRIM0": 3, "REG_UID": 4})

    def test_addr_map_historical_trim_suffix_uses_logical_item_identity(self):
        addr_map = _addr_map_frame()
        addr_map.loc[0, "CP addr map"] = "Vposp_Trim[3:0],Iref1U_Trim[3:0]"

        plan = compile_memory_wakeup_plan(
            compile_trim_data_plan(_flow_frame()),
            compile_addr_map_catalog(addr_map),
            cp="CP1",
        )

        self.assertEqual(
            [binding.field.name for binding in plan.build_map.field_bindings],
            ["Vposp_Trim", "Iref1U_Trim"],
        )
        self.assertEqual(plan.set_vposp.pumps[0].field.name, "Vposp_Trim")


if __name__ == "__main__":
    unittest.main()
