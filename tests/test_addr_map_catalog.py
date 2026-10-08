import unittest

import pandas as pd

from program_gen.core.addr_map import (
    AddrMapCompileError,
    compile_addr_map_catalog, catalog_for_cp,
)


def _frame(*rows):
    columns = (
        "Word No.", "CPU Address", "SM Address", "Contents", "line",
        "bit[31:16]", "bit[15:0]", "data type", "CP Data[31:0]",
        "description", "CP addr map", "备注",
    )
    return pd.DataFrame(rows, columns=columns)


class AddrMapCatalogTests(unittest.TestCase):
    def test_resolves_logical_fields_inside_one_complemented_register(self):
        catalog = compile_addr_map_catalog(_frame(
            (
                "trim1", "0x1FFF 1E60", "RA[8:0] = 0x1E; CA[4:0] = 0xC",
                "Analog IP trimming", "CP1/2/3", "bit[15:0]的反码",
                "ANA_MUX_TRIM2[15:0]", "lable", "32'hFFF9_0006",
                "模拟{12'h0,DLPR1_VSEL_OP_VDDK[1:0],DLPR0_VSEL_OP_VDDK[1:0]}说明",
                "12'h0,DLPR1_VSEL_OP_VDDK[1:0],DLPR0_VSEL_OP_VDDK[1:0]", None,
            ),
        ))

        dlpr0 = catalog.resolve_field("dlpr0_vsel_op_vddk")
        dlpr1 = catalog.resolve_field("DLPR1_VSEL_OP_VDDK")

        self.assertEqual(dlpr0.page, "trim1")
        self.assertEqual(dlpr0.register, "ANA_MUX_TRIM2")
        self.assertEqual((dlpr0.width, dlpr0.lsb), (2, 0))
        self.assertEqual((dlpr1.width, dlpr1.lsb), (2, 2))
        self.assertEqual(dlpr0.register_layout.real_half, "LOW")
        self.assertEqual(dlpr0.register_layout.complement_half, "HIGH")
        self.assertEqual(dlpr0.register_layout.default_real_value, 0x0006)
        self.assertEqual(
            dlpr0.register_layout.description,
            "{12'h0,DLPR1_VSEL_OP_VDDK[1:0],DLPR0_VSEL_OP_VDDK[1:0]}",
        )
        self.assertEqual(
            tuple(
                (segment.name, segment.width, segment.lsb, segment.literal_value)
                for segment in dlpr0.register_layout.segments
            ),
            (
                ("DLPR0_VSEL_OP_VDDK", 2, 0, None),
                ("DLPR1_VSEL_OP_VDDK", 2, 2, None),
                (None, 12, 4, 0),
            ),
        )

        updated_real = dlpr0.register_layout.replace_field(0x0006, dlpr0, 1)
        self.assertEqual(updated_real, 0x0005)
        self.assertEqual(dlpr0.register_layout.storage_word(updated_real), 0xFFFA0005)

    def test_field_value_overflow_is_rejected_without_truncation(self):
        catalog = compile_addr_map_catalog(_frame(
            (
                "trim1", "0x0", "RA=0", "x", "CP1", "bit[15:0]的反码",
                "REG0[15:0]", "lable", "32'hFFFF_0000", "{14'h0,F[1:0]}",
                "14'h0,F[1:0]", None,
            ),
        ))
        field = catalog.resolve_field("F")

        with self.assertRaisesRegex(AddrMapCompileError, "2 bit"):
            field.register_layout.replace_field(0, field, 4)

    def test_capture_layout_keeps_mixed_two_and_four_byte_slots(self):
        catalog = compile_addr_map_catalog(_frame(
            (
                "uid", "0x0", "RA=0", "x", "CP1/2", "bit[15:0]的反码",
                "REG_A[15:0]", "lable", "32'hFFFF_0000", "{16'h0}",
                "16'h0", None,
            ),
            (
                "uid", "0x4", "RA=1", "x", "CP1/2", "16'h0",
                "REG_B[15:0]", "lable", "32'h0000_0000", "{16'h0}",
                "16'h0", None,
            ),
        ))

        layout = catalog.capture_layout("uid", read_bit=64, cp="CP1")

        self.assertEqual(
            [(entry.register, entry.slot_width, entry.real_offset) for entry in layout],
            [("REG_B", 2, 0), ("REG_A", 4, 2)],
        )

    def test_complement_in_low_half_uses_high_half_as_real_value(self):
        catalog = compile_addr_map_catalog(_frame(
            (
                "trim0", "0x0", "RA=0", "x", "CP1", "REG_C[15:0]",
                "bit[31:16]的反码", "lable", "32'h1234_EDCB", "{16'h1234}",
                "16'h1234", None,
            ),
        ))
        register = catalog.resolve_register("REG_C")

        self.assertEqual(register.real_half, "HIGH")
        self.assertEqual(register.complement_half, "LOW")
        self.assertEqual(register.default_real_value, 0x1234)
        self.assertEqual(register.storage_word(0x00A5), 0x00A5FF5A)

    def test_repeated_field_across_registers_is_an_explicit_fanout(self):
        rows = []
        for reg in ("REG_A", "REG_B"):
            rows.append((
                "trim0", "0x0", "RA=0", "x", "CP1", "bit[15:0]的反码",
                f"{reg}[15:0]", "lable", "32'hFFFF_0000", "{{15'h0,F[0:0]}}",
                "15'h0,F[0:0]", None,
            ))

        catalog = compile_addr_map_catalog(_frame(*rows))
        self.assertEqual(
            [field.register for field in catalog.resolve_fields("F")],
            ["REG_A", "REG_B"],
        )
        with self.assertRaisesRegex(AddrMapCompileError, "多个寄存器"):
            catalog.resolve_field("F")


    def test_one_bare_field_consumes_the_remaining_register_width(self):
        catalog = compile_addr_map_catalog(_frame(
            (
                "uid", "0x0", "RA=0", "x", "CP1", "bit[15:0] complement",
                "VERIFY_VALUE", "lable", "32'hFFFF_FFFF", "VERIFY_VALUE",
                "VERIFY_VALUE", None,
            ),
            (
                "factory23", "0x4", "RA=1", "x", "CP1", "bit[15:0] complement",
                "REDRA_CFG0[15:0]", "lable", "32'hFFFF_0000",
                "redra0_val,6'h0,redra0[8:0]",
                "redra0_val,6'h0,redra0[8:0]", None,
            ),
        ))

        self.assertEqual(catalog.resolve_field("VERIFY_VALUE").width, 16)
        self.assertEqual(
            (catalog.resolve_field("redra0_val").width,
             catalog.resolve_field("redra0_val").lsb),
            (1, 15),
        )

    def test_cp_shorthand_applies_to_each_station(self):
        catalog = compile_addr_map_catalog(_frame(
            (
                "trim1", "0x0", "RA=0", "x", "CP1/2/3", "complement",
                "REG0[15:0]", "lable", "32'hFFFF_0000", "F[15:0]",
                "F[15:0]", None,
            ),
        ))

        self.assertTrue(all(
            catalog.resolve_register("REG0").applies_to(cp)
            for cp in ("CP1", "CP2", "CP3")
        ))

    def test_cp_catalog_excludes_other_station_registers(self):
        catalog = compile_addr_map_catalog(_frame(
            ("p1", "0", "0", "x", "CP1", "complement", "REG1[15:0]",
             "lable", "32'hFFFF_0000", "F[15:0]", "F[15:0]", None),
            ("p2", "0", "0", "x", "CP2", "complement", "REG2[15:0]",
             "lable", "32'hFFFF_0000", "G[15:0]", "G[15:0]", None),
        ))

        cp1 = catalog_for_cp(catalog, "CP1")

        self.assertEqual(cp1.pages, ("p1",))
        self.assertEqual(cp1.resolve_field("F").register, "REG1")
        with self.assertRaises(AddrMapCompileError):
            cp1.resolve_field("G")


if __name__ == "__main__":
    unittest.main()
