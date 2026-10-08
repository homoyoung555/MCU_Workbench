import unittest

from program_gen.core.encoding import addr_map_field_width, addr_map_literal_value


class AddrMapLayoutTests(unittest.TestCase):
    def test_v5_k268_nonzero_lsb_slice_keeps_low_nibble_reserved(self):
        fields = [
            "1'h0",
            "Hsi_Vrega_Trimming[2:0]",
            "Hsi10M_Trimming[3:0]",
            "Vref1p0_ABS_Trimming[7:4]",
            "4'h0",
        ]

        used_bits = 0
        shifts = []
        for field in fields:
            used_bits += addr_map_field_width(field)
            shifts.append(16 - used_bits)

        self.assertEqual(shifts, [15, 12, 8, 4, 0])
        self.assertEqual(used_bits, 16)

    def test_addr_map_literal_accepts_straight_and_curly_apostrophes(self):
        self.assertEqual(addr_map_literal_value("4'h6"), 6)
        self.assertEqual(addr_map_literal_value("4‘h6"), 6)
        self.assertEqual(addr_map_literal_value("4’h6"), 6)


if __name__ == "__main__":
    unittest.main()
