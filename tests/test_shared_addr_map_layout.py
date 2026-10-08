import unittest
from unittest.mock import patch

import pandas as pd

from program_gen import state as G
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.platforms.chroma import writers as chroma_writers
from program_gen.platforms.s100 import writers as s100_writers


class SharedAddrMapLayoutTests(unittest.TestCase):
    def test_both_platforms_consume_the_shared_catalog_with_platform_symbols(self):
        frame = pd.DataFrame([
            {
                "Word No.": "uid", "line": "CP1/2", "bit[31:16]": "complement",
                "bit[15:0]": "Vrefint_Verify", "data type": "lable",
                "CP Data[31:0]": "32'hFFFF_0000", "CP addr map": "Vrefint_Verify",
            },
            {
                "Word No.": "uid", "line": "CP1/2", "bit[31:16]": "16'h0",
                "bit[15:0]": "Hsi_8M_Trim[15:0]", "data type": "lable",
                "CP Data[31:0]": "32'h0000_8FFF", "CP addr map": "Hsi_8M[11:0]",
            },
        ])
        uid_gate = {"Vrefint_Verify": 1}

        catalog = compile_addr_map_catalog(frame)
        with patch.object(G, "ADDR_MAP", frame):
            chroma = chroma_writers._page_field_layout(
                "uid", 64, uid_gate, 1, catalog=catalog
            )
            s100 = s100_writers._page_field_layout(
                "uid", 64, uid_gate, 1, catalog=catalog
            )

        self.assertEqual(chroma, [
            ("    REG_HSI_8M_TRIM[SOCKET]=", 2, 0),
            ("    VREFINT_W[SOCKET]=", 4, 2),
        ])
        self.assertEqual(s100, [
            ("\t\tREG_HSI_8M_TRIM[T_SOCKET]=", 2, 0),
            ("\t\tVREFINT_W[T_SOCKET]=", 4, 2),
        ])


if __name__ == "__main__":
    unittest.main()
