from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from program_gen.pin_dec import (
    compile_pin_map_generation_plan,
    generate_pin_dec,
    generate_s100_prj_resources,
)
from program_gen.platform_program.chroma import project_contribution
from program_gen.platform_program.s100 import (
    project_contribution as s100_project_contribution,
)
from program_gen.platform_program.facts import (
    compile_pin_map_facts,
    compile_platform_program_facts,
)
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER
from tools.generate_pin_dec import main
from tools.generate_s100_prj_resources import main as s100_main


class _PinWorkbook:
    """A workbook facade containing only the tables the pin compiler may read."""

    def __init__(self, frames) -> None:
        self._frames = frames

    def dataframe(self, title):
        try:
            return self._frames[title].copy(deep=True)
        except KeyError:
            raise KeyError(f"missing pin table: {title}") from None


class PinDecGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)

    def _target(self, cp: str, variant: str) -> TargetKey:
        return TargetKey("chroma", cp, variant, f"PIN_DEC_{cp}_{variant}")

    def _pin_only_workbook(self, target: TargetKey) -> _PinWorkbook:
        version = self.workbook.dataframe("VERSION")
        version = version.loc[
            version["CP num"].astype(str).str.strip().str.casefold()
            == target.cp.casefold(),
            ["CP num", "NRST PIN", "SWD PIN", "CLK PIN"],
        ]
        frames = {
            "VERSION": version,
            "IOMUX": self.workbook.dataframe("IOMUX"),
        }
        if target.variant == "lab":
            frame = self.workbook.dataframe("PIN DEC SINGEL")
            frames["PIN DEC SINGEL"] = frame.loc[
                frame["TESTER"].astype(str).str.strip().str.casefold()
                == target.platform.casefold()
            ]
        else:
            frame = self.workbook.dataframe("PIN DEC")
            frames["PIN DEC"] = frame.loc[
                frame["CP NO"].astype(str).str.strip().str.casefold()
                == target.cp.casefold()
            ]
            # CP1 Chroma production has a multi-site KP relay; its map is required.
            frames["KP RELAY"] = self.workbook.dataframe("KP RELAY")
        return _PinWorkbook(frames)

    def test_pin_facts_need_only_pin_tables_and_minimal_version_fields(self) -> None:
        target = self._target("CP1", "production")
        complete = generate_pin_dec(
            compile_pin_map_generation_plan(
                compile_platform_program_facts(self.workbook, target)
            )
        )

        pin_facts = compile_pin_map_facts(
            self._pin_only_workbook(target), target
        )
        standalone = generate_pin_dec(compile_pin_map_generation_plan(pin_facts))

        self.assertEqual(standalone, complete)

    def test_pin_facts_reject_conflicting_site_channels(self) -> None:
        target = self._target("CP1", "lab")
        workbook = self._pin_only_workbook(target)
        pin_frame = workbook._frames["PIN DEC SINGEL"]
        valid = pin_frame.loc[
            pin_frame["Trace"].astype(str).str.strip().ne("")
            & ~pin_frame["Trace"].astype(str).str.contains("GND", case=False)
            & pin_frame["E/C(Pad Name)"].notna()
        ].iloc[[0]].copy()
        valid.loc[:, "Trace"] = "9988"
        workbook._frames["PIN DEC SINGEL"] = pd.concat(
            (pin_frame, valid), ignore_index=True
        )

        with self.assertRaisesRegex(ValueError, "STN.PIN.SITE_CONFLICT"):
            compile_pin_map_facts(workbook, target)

    def test_standalone_output_is_the_complete_program_pin_dec(self) -> None:
        target = self._target("CP1", "lab")
        facts = compile_platform_program_facts(self.workbook, target)

        standalone = generate_pin_dec(compile_pin_map_generation_plan(facts))
        embedded = project_contribution(target, facts).resources[0].content

        self.assertEqual(standalone, embedded)

    def test_chroma_pin_numbers_preserve_craft_resource_numbering(self) -> None:
        target = self._target("CP1", "lab")
        facts = compile_platform_program_facts(self.workbook, target)
        output = generate_pin_dec(
            compile_pin_map_generation_plan(facts)
        ).decode("ascii")

        self.assertIn("PC14 = 13  =   2 = IO;", output)
        self.assertIn(
            "ODD_pins = PC15+PD1+NRST+PA1+PA7+PA9+PA13+PA14+PC10+PD2;",
            output,
        )
        self.assertIn(
            "EVEN_pins = PC14+PD0+PA0+PA2+PA8+PA11+PA15+PC12;",
            output,
        )

    def test_production_cp1_kp_channels_follow_every_site(self) -> None:
        target = self._target("CP1", "production")
        facts = compile_platform_program_facts(self.workbook, target)
        plan = compile_pin_map_generation_plan(facts)

        self.assertEqual(len(plan.kp_channels), 84)
        self.assertEqual(plan.kp_channels[:4], ("2084", "2092", "2085", "2093"))
        self.assertEqual(plan.kp_channels[-1], "2156")

    def test_cli_writes_only_the_requested_pin_dec(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated" / "pin.dec"

            result = main([
                "--workbook", str(FORMAL_MASTER),
                "--cp", "CP3",
                "--variant", "lab",
                "--output", str(output),
            ])

            self.assertEqual(result, 0)
            self.assertTrue(output.is_file())
            self.assertEqual(tuple(output.parent.iterdir()), (output,))
            self.assertIn(b"PIN_LIST(CP_1S)", output.read_bytes())

    def test_s100_standalone_resources_are_embedded_in_every_formal_prj(self) -> None:
        for variant in ("lab", "production"):
            for cp in ("CP1", "CP2", "CP3"):
                with self.subTest(variant=variant, cp=cp):
                    target = TargetKey(
                        "s100", cp, variant, f"PIN_RESOURCES_{variant}_{cp}"
                    )
                    facts = compile_platform_program_facts(self.workbook, target)
                    standalone = generate_s100_prj_resources(
                        compile_pin_map_generation_plan(facts)
                    )
                    contribution = s100_project_contribution(
                        target, facts, pattern_names=(), bins=(1,), timing_sets=()
                    )
                    complete = next(
                        resource.content for resource in contribution.resources
                        if resource.relative_path.endswith(".prj")
                    )

                    self.assertIn(standalone, complete)
                    self.assertIn(b"@@PIN_DEFINE_TABLE", standalone)
                    self.assertIn(b"@@USER_RELAY_TABLE", standalone)
                    self.assertIn(b"@@PIN_GROUP_TABLE", standalone)
                    self.assertNotIn(b"@@START_UP_TABLE", standalone)
                    self.assertNotIn(b"@@BIN_MAP", standalone)

    def test_s100_cli_writes_only_resource_definitions(self) -> None:
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "s100_pin_resources.prj"

            result = s100_main([
                "--workbook", str(FORMAL_MASTER),
                "--cp", "CP2",
                "--variant", "lab",
                "--output", str(output),
            ])

            self.assertEqual(result, 0)
            content = output.read_bytes()
            self.assertTrue(content.startswith(b"@@PIN_DEFINE_TABLE"))
            self.assertTrue(content.endswith(b"@@END_PIN_GROUP_TABLE\r\n\r\n"))
            self.assertNotIn(b"@@START_UP_TABLE", content)


if __name__ == "__main__":
    unittest.main()
