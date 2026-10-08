import os
from pathlib import Path
import unittest

from program_gen import state as G
from tests.workspace_paths import FORMAL_MASTER, S100_SEED_ROOT


class StateDependencyTests(unittest.TestCase):
    def test_yellow_flow_items_are_compiled_as_common_dac_dependencies(self):
        original_cwd = Path.cwd()
        try:
            G.init(
                str(S100_SEED_ROOT),
                platform="s100",
                mode="production",
                master=str(FORMAL_MASTER),
            )
            self.assertEqual(
                G.FLOW.attrs["common_dac_dependencies"],
                ("Vref0p8_ABS", "Iref1u"),
            )
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
