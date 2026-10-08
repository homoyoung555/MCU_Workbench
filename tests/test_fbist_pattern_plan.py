"""FbistPatternGenerationPlan: upstream compilation of the FBIST pattern chain.

The plan freezes every upstream fact (pattern sheet rows, item/pattern
inheritance, valid-row cell format, VERSION pins, description fields, addr,
PUMP aggregation and label identity) into an immutable, workbook-free object.
Generators must only consume the plan.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path
import unittest

import pandas as pd

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from program_gen.core.fbist_pattern_plan import (
    FbistPatternCompileError,
    FbistPatternField,
    FbistPatternGenerationPlan,
    FbistPatternWrite,
    compile_fbist_pattern_plan,
)
from program_gen.workbook import (
    AlignmentModel,
    CellModel,
    ColorModel,
    FillModel,
    FontModel,
    SheetModel,
    TableModel,
    WorkbookModel,
    WorkbookReader,
)


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


# --------------------------------------------------------------------------
# synthetic WorkbookModel helpers (pattern sheet F-column fill = valid-row rule)
# --------------------------------------------------------------------------

_BLACK = "00000000"


def _cell(value=None, *, fill_rgb: str = _BLACK, row: int = 1, column: int = 1) -> CellModel:
    return CellModel(
        sheet="pattern",
        row=row,
        column=column,
        coordinate=f"R{row}C{column}",
        value=value,
        formula=None,
        cached_value=value,
        data_type=None,
        number_format="General",
        style_id=0,
        fill=FillModel(
            fill_type=None,
            fgColor=ColorModel(type="rgb", rgb=fill_rgb),
            bgColor=ColorModel(),
        ),
        font=FontModel(None, None, False, False, None, False, ColorModel()),
        alignment=AlignmentModel(None, None, None, None, 0.0, 0),
    )


def make_workbook(
    *,
    pattern_rows: list[dict],
    flow_rows: list[dict],
    version_rows: list[dict],
    pattern_fills: list[str] | None = None,
) -> WorkbookModel:
    """Build one immutable WorkbookModel with a minimal pattern sheet."""
    pattern_frame = pd.DataFrame(
        [
            {
                "item": row.get("item"),
                "addr": row.get("addr"),
                "description": row.get("description"),
                "pattern": row.get("pattern"),
            }
            for row in pattern_rows
        ],
        dtype=object,
    )
    flow_frame = pd.DataFrame(flow_rows, dtype=object)
    version_frame = pd.DataFrame(version_rows, dtype=object)
    fills = pattern_fills or [_BLACK] * len(pattern_rows)
    if len(fills) != len(pattern_rows):
        raise AssertionError("pattern_fills must match pattern_rows")
    # sheet row 1 is the header; fixture row i lives at sheet row i+2, which is
    # exactly the excel_row the plan compiler derives from the DataFrame index.
    sheet_rows = [
        tuple(_cell(row=1, column=c + 1) for c in range(6)),
    ]
    for r in range(len(pattern_rows)):
        sheet_rows.append(
            tuple(
                _cell(
                    row=r + 2,
                    column=c + 1,
                    fill_rgb=(fills[r] if c == 5 else _BLACK),
                )
                for c in range(6)
            )
        )
    pattern_sheet = SheetModel(
        title="pattern",
        state="visible",
        max_row=len(pattern_rows) + 1,
        max_column=6,
        rows=tuple(sheet_rows),
        merged_ranges=(),
        row_dimensions=(),
        column_dimensions=(),
    )
    tables = tuple(
        TableModel.from_dataframe(title, frame)
        for title, frame in (
            ("pattern", pattern_frame),
            ("FLOW", flow_frame),
            ("VERSION", version_frame),
        )
    )
    return WorkbookModel(
        source_path="fixture.xlsx",
        source_size=0,
        source_sha256="FIXTURE",
        sheets=(pattern_sheet,),
        tables=tables,
        identity="fixture-identity",
    )


def compile_fixture(
    *,
    pattern_rows: list[dict],
    flow_rows: list[dict],
    version_rows: list[dict] | None = None,
    pattern_fills: list[str] | None = None,
) -> FbistPatternGenerationPlan:
    workbook = make_workbook(
        pattern_rows=pattern_rows,
        flow_rows=flow_rows,
        version_rows=version_rows or [{"CLK PIN": "PA11", "SWD PIN": "PA13"}],
        pattern_fills=pattern_fills,
    )
    flow = workbook.dataframe("FLOW")
    return compile_fbist_pattern_plan(workbook, flow)


def _patterns(plan: FbistPatternGenerationPlan) -> dict[str, object]:
    return {item.pattern_name: item for item in plan.patterns}


class PlanCompileTests(unittest.TestCase):
    def test_compiles_inherited_rows_into_ordered_writes_per_pattern(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vref0p8_ABS", "addr": "0101111", "description": "3,PMU_TMODE=0101", "pattern": "trim mode"},
                {"addr": "0011101", "description": "7,trim_sel=1\n6,sleep=0\n5,reset=0\n4,tmode[4:0]=10100"},
                {"addr": "0000000", "description": "8,BG_ABS_TRIM[3:0]=0000*", "pattern": "trim dac"},
                {"addr": "0100010", "description": "2,fbist_trg=0"},
                {"addr": "0101111", "description": "3,PMU_TMODE=0101", "pattern": "verify mode"},
            ],
            flow_rows=[{"CP NO": "CP1", "item": "Vref0p8_ABS", "type": "trim", "PUMP": "no"}],
        )
        names = tuple(item.pattern_name for item in plan.patterns)
        self.assertEqual(
            names,
            ("enter_vref0p8_abs", "set_vref0p8_abs_dac", "enter_vref0p8_abs_verify"),
        )
        enter = _patterns(plan)["enter_vref0p8_abs"]
        self.assertEqual(len(enter.writes), 2)
        self.assertEqual(enter.writes[0].addr_bits, "0101111")
        self.assertEqual(enter.writes[1].addr_bits, "0011101")
        self.assertEqual(enter.writes[1].data_bits, "0000000010010100")
        dac = _patterns(plan)["set_vref0p8_abs_dac"]
        self.assertEqual(tuple(write.addr_bits for write in dac.writes), ("0000000", "0100010"))
        field = dac.writes[0].fields[0]
        self.assertEqual(field.field_name, "BG_ABS_TRIM[3:0]")
        self.assertEqual(field.label_base, "bg_abs_trim")
        self.assertEqual((field.start_bit, field.bit_width, field.bit_hi, field.bit_lo), (8, 4, 8, 5))
        self.assertTrue(field.dynamic)
        self.assertEqual(field.value, "0000*")
        verify = _patterns(plan)["enter_vref0p8_abs_verify"]
        self.assertEqual(len(verify.writes), 1)

    def test_output_name_rules_and_bor_and_verify_suffix(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Bor_Trim", "addr": "0000000", "description": "4,BOR_OPCR[3:0]=0000*", "pattern": "trim dac"},
                {"item": "Bor_Trim", "addr": "0000001", "description": "5,BOR_TC[3:0]=0000*", "pattern": "trim dac"},
                {"item": "Foo_Verify_Verify", "addr": "0000000", "description": "2,x[1:0]=00", "pattern": "verify mode"},
            ],
            flow_rows=[],
        )
        self.assertEqual(
            tuple(item.pattern_name for item in plan.patterns),
            ("set_bor_verify_dac", "set_bor_dac", "enter_foo_verify"),
        )

    def test_version_pins_are_compiled_into_the_plan(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vref0p8_ABS", "addr": "0000000", "description": "8,BG_ABS_TRIM[3:0]=0000*", "pattern": "trim dac"},
            ],
            flow_rows=[],
            version_rows=[{"CLK PIN": "PB6", "SWD PIN": "PB2"}],
        )
        self.assertEqual(plan.clk_pin, "PB6")
        self.assertEqual(plan.swd_pin, "PB2")

    def test_dynamic_detection_covers_star_and_x(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "A", "addr": "0000000", "description": "8,a[3:0]=0000*", "pattern": "trim dac"},
                {"item": "B", "addr": "0000000", "description": "8,b[3:0]=xxxx", "pattern": "trim dac"},
                {"item": "C", "addr": "0000000", "description": "8,c[3:0]=0101", "pattern": "trim dac"},
            ],
            flow_rows=[],
        )
        by_name = {item.pattern_name: item for item in plan.patterns}
        self.assertTrue(by_name["set_a_dac"].writes[0].fields[0].dynamic)
        self.assertTrue(by_name["set_b_dac"].writes[0].fields[0].dynamic)
        self.assertFalse(by_name["set_c_dac"].writes[0].fields[0].dynamic)

    def test_invalid_fill_rows_are_excluded_and_do_not_break_inheritance(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "A", "addr": "0000000", "description": "3,a[2:0]=000", "pattern": "trim mode"},
                {"addr": "0000001", "description": "3,b[2:0]=000", "pattern": "trim dac"},
                {"addr": "0000010", "description": "3,c[2:0]=000"},
                {"item": "B", "addr": "0000000", "description": "3,d[2:0]=000", "pattern": "trim mode"},
            ],
            flow_rows=[],
            pattern_fills=[_BLACK, _BLACK, "FFFFFF00", _BLACK],
        )
        rows = {row.excel_row: row for row in plan.rows}
        self.assertEqual(rows[4].excluded, "invalid fill")
        self.assertEqual(rows[3].role, "trim dac")  # row 3 still inherits item A
        dac = _patterns(plan)["set_a_dac"]
        self.assertEqual(tuple(write.addr_bits for write in dac.writes), ("0000001",))

    def test_special_roles_are_excluded_from_generation(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "read_status_mode", "addr": "1011", "description": "32'h12345678", "pattern": "read_status_mode"},
                {"item": "Hsi_8M", "addr": "0000000", "description": "3,reuse dac", "pattern": "reuse dac"},
                {"item": "X", "addr": "0000000", "description": "3,x[2:0]=000", "pattern": "trim mode"},
                {"addr": "0000000", "description": "8,legacy[3:0]=0000*", "pattern": "set_all_final_vposp"},
            ],
            flow_rows=[],
        )
        self.assertEqual(
            tuple(item.pattern_name for item in plan.patterns), ("enter_x",)
        )
        reasons = {row.excel_row: row.excluded for row in plan.rows}
        self.assertEqual(reasons[2], "read_status_mode")
        self.assertEqual(reasons[3], "reuse dac")
        self.assertEqual(reasons[5], "legacy aggregate block")
        self.assertEqual(plan.pump_aggregate.pattern_name, "set_all_final_vposp")
        self.assertEqual(plan.pump_aggregate.writes, ())

    def test_pump_aggregation_merges_same_addr_and_skips_static_pulse_rows(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vposp", "addr": "0011101", "description": "7,trim_sel=1\n6,sleep=0\n5,reset=0\n4,tmode[4:0]=01110", "pattern": "trim mode"},
                {"addr": "0010100", "description": "9,prog_pdac[4:0]=00000*", "pattern": "trim dac"},
                {"addr": "0100010", "description": "2,fbist_trg=0"},
                {"addr": "0100010", "description": "2,fbist_trg=1"},
                {"item": "Vnegp", "addr": "0011101", "description": "7,trim_sel=1\n6,sleep=0\n5,reset=0\n4,tmode[4:0]=00010", "pattern": "trim mode"},
                {"addr": "0010100", "description": "4,prog_ndac[4:0]=00000*", "pattern": "trim dac"},
                {"item": "Mr_VDDD_DC", "addr": "0101110", "description": "2,MR_VSEL_OPTR_VDDK[2:0]=001*", "pattern": "trim mode"},
                {"addr": "0000010", "description": "7,MR_TRIM_VDDK[3:0]=0000*", "pattern": "trim dac"},
            ],
            flow_rows=[
                {"CP NO": "CP1", "item": "Vposp", "type": "trim", "PUMP": "yes"},
                {"CP NO": "CP1", "item": "Vnegp", "type": "trim", "PUMP": "yes"},
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "trim", "PUMP": "no"},
            ],
        )
        aggregate = plan.pump_aggregate
        self.assertEqual(aggregate.pattern_name, "set_all_final_vposp")
        self.assertEqual(tuple(plan.pump_items), ("vposp", "vnegp"))
        self.assertEqual(len(aggregate.writes), 1)
        write = aggregate.writes[0]
        self.assertEqual(write.addr_bits, "0010100")
        self.assertEqual(
            tuple(field.label_base for field in write.fields), ("prog_pdac", "prog_ndac")
        )
        self.assertEqual(write.data_bits, "0" * 16)
        self.assertEqual(
            tuple(target.item for target in aggregate.targets), ("Vposp", "Vnegp")
        )
        # static pulse rows stay in the ordinary DAC pattern, not the aggregate
        dac = _patterns(plan)["set_vposp_dac"]
        self.assertEqual(
            tuple(write.addr_bits for write in dac.writes),
            ("0010100", "0100010", "0100010"),
        )
        # non-pump item has no aggregate participation
        self.assertEqual(
            _patterns(plan)["set_mr_vddd_dc_dac"].writes[0].fields[0].label_base,
            "mr_trim_vddk",
        )

    def test_pump_dac_rows_join_aggregate_without_own_pattern(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vpose", "addr": "0011101", "description": "7,trim_sel=1\n6,sleep=0\n5,reset=0\n4,tmode[4:0]=01110", "pattern": "trim mode"},
                {"addr": "0010101", "description": "9,ers_pdac[4:0]=00000*", "pattern": "pump dac"},
                {"addr": "0010101", "description": "4,ers_ndac[4:0]=00000*", "pattern": "pump dac"},
            ],
            flow_rows=[{"CP NO": "CP1", "item": "Vpose", "type": "trim", "PUMP": "yes"}],
        )
        self.assertEqual(tuple(item.pattern_name for item in plan.patterns), ("enter_vpose",))
        write = plan.pump_aggregate.writes[0]
        self.assertEqual(write.addr_bits, "0010101")
        self.assertEqual(
            tuple(field.label_base for field in write.fields), ("ers_pdac", "ers_ndac")
        )
        self.assertEqual(
            tuple(target.role for target in plan.pump_aggregate.targets),
            ("pump dac", "pump dac"),
        )

    def test_pump_aggregate_exposes_only_dynamic_fields(self):
        plan = compile_fixture(
            pattern_rows=[{
                "item": "Vposp",
                "addr": "0010100",
                "description": "9,prog_pdac[4:0]=00000*\n4,static_mode[1:0]=01",
                "pattern": "trim dac",
            }],
            flow_rows=[{
                "CP NO": "CP1",
                "item": "Vposp",
                "type": "trim",
                "PUMP": "yes",
            }],
        )

        self.assertEqual(
            tuple(target.field.label_base for target in plan.pump_aggregate.targets),
            ("prog_pdac",),
        )
        self.assertEqual(
            tuple(field.label_base for field in plan.pump_aggregate.writes[0].fields),
            ("prog_pdac",),
        )

    def test_pump_selection_is_case_insensitive_and_reads_flow_only(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vposp", "addr": "0010100", "description": "9,prog_pdac[4:0]=00000*", "pattern": "trim dac"},
            ],
            flow_rows=[{"CP NO": "CP1", "item": "Vposp", "type": "trim", "PUMP": "Yes"}],
        )
        self.assertEqual(tuple(plan.pump_items), ("vposp",))
        self.assertEqual(len(plan.pump_aggregate.writes), 1)

    def test_compile_errors(self):
        cases = {
            "overlap": (
                [{"item": "A", "addr": "0000000", "description": "5,a[2:0]=000\n4,b[1:0]=00", "pattern": "trim dac"}],
                "位段重叠",
            ),
            "incomplete": (
                [{"item": "A", "addr": "0000000", "description": "2,a[3:0]=0000", "pattern": "trim dac"}],
                "2,a[3:0]=0000",
            ),
            "bad addr": (
                [{"item": "A", "addr": "1011", "description": "3,a[2:0]=000", "pattern": "trim dac"}],
                "addr",
            ),
            "blank addr": (
                [{"item": "A", "description": "3,a[2:0]=000", "pattern": "trim dac"}],
                "addr",
            ),
            "unparseable line": (
                [{"item": "A", "addr": "0000000", "description": "hello world", "pattern": "trim dac"}],
                "hello world",
            ),
            "no role": (
                [{"item": "A", "addr": "0000000", "description": "3,a[2:0]=000"}],
                "role",
            ),
        }
        for label, (rows, needle) in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(FbistPatternCompileError) as ctx:
                    compile_fixture(pattern_rows=rows, flow_rows=[])
                self.assertIn(needle, str(ctx.exception))

    def test_aggregate_label_conflict_is_a_typed_diagnostic(self):
        with self.assertRaises(FbistPatternCompileError) as ctx:
            compile_fixture(
                pattern_rows=[
                    {"item": "Vposp", "addr": "0010100", "description": "9,prog_pdac[4:0]=00000*", "pattern": "trim dac"},
                    {"item": "Vposx", "addr": "0010101", "description": "9,prog_pdac[4:0]=00000*", "pattern": "trim dac"},
                ],
                flow_rows=[
                    {"CP NO": "CP1", "item": "Vposp", "type": "trim", "PUMP": "yes"},
                    {"CP NO": "CP1", "item": "Vposx", "type": "trim", "PUMP": "yes"},
                ],
            )
        self.assertIn("prog_pdac", str(ctx.exception))

    def test_plan_is_immutable_and_workbook_free(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vposp", "addr": "0010100", "description": "9,prog_pdac[4:0]=00000*", "pattern": "trim dac"},
            ],
            flow_rows=[{"CP NO": "CP1", "item": "Vposp", "type": "trim", "PUMP": "yes"}],
        )

        def walk(value, seen):
            if id(value) in seen:
                return
            seen.add(id(value))
            self.assertNotIsInstance(
                value, (pd.DataFrame, pd.Series),
                f"plan must not carry pandas objects: {type(value).__name__}",
            )
            if is_dataclass(value):
                for field in fields(value):
                    walk(getattr(value, field.name), seen)
            elif isinstance(value, tuple):
                for item in value:
                    walk(item, seen)

        walk(plan, set())
        with self.assertRaises(FrozenInstanceError):
            plan.patterns = ()

    def test_compile_is_deterministic(self):
        rows = [
            {"item": "Vposp", "addr": "0010100", "description": "9,prog_pdac[4:0]=00000*", "pattern": "trim dac"},
            {"item": "Vnegp", "addr": "0010100", "description": "4,prog_ndac[4:0]=00000*", "pattern": "trim dac"},
        ]
        flow = [{"CP NO": "CP1", "item": "Vposp", "type": "trim", "PUMP": "yes"},
                {"CP NO": "CP1", "item": "Vnegp", "type": "trim", "PUMP": "yes"}]
        first = compile_fixture(pattern_rows=rows, flow_rows=flow)
        second = compile_fixture(pattern_rows=rows, flow_rows=flow)
        self.assertEqual(first, second)
        self.assertEqual(first.identity, second.identity)


class PlanFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.flow = cls.workbook.dataframe("FLOW")
        cls.plan = compile_fbist_pattern_plan(cls.workbook, cls.flow)

    def test_formal_master_compiles_to_a_complete_plan(self):
        plan = self.plan
        self.assertEqual(plan.clk_pin, "PA11")
        self.assertEqual(plan.swd_pin, "PA13")
        self.assertEqual(
            tuple(plan.pump_items),
            ("vref0p8_abs", "iref1u", "isa", "vpose", "vnege", "vposp", "vnegp", "vbl"),
        )
        names = tuple(item.pattern_name for item in plan.patterns)
        self.assertIn("enter_vref0p8_tc", names)
        self.assertIn("set_vref0p8_tc_dac", names)
        self.assertIn("set_vposp_dac", names)
        self.assertIn("enter_vposp_verify", names)
        self.assertNotIn("set_all_final_vposp", names)  # legacy fixed block excluded

    def test_formal_master_aggregate_merges_shared_addresses(self):
        aggregate = self.plan.pump_aggregate
        self.assertEqual(aggregate.pattern_name, "set_all_final_vposp")
        writes = {write.addr_bits: write for write in aggregate.writes}
        self.assertEqual(
            tuple(writes),
            ("0000000", "0000001", "0010010", "0010101", "0010100", "0001111"),
        )
        merged = writes["0010100"]
        self.assertEqual(
            tuple(field.label_base for field in merged.fields),
            ("prog_pdac", "prog_ndac"),
        )
        ers = writes["0010101"]
        self.assertEqual(
            tuple(field.label_base for field in ers.fields), ("ers_pdac", "ers_ndac")
        )
        bases = tuple(
            field.label_base for write in aggregate.writes for field in write.fields
        )
        self.assertEqual(len(bases), len(set(bases)), f"duplicate labels: {bases}")
        self.assertEqual(len(aggregate.targets), 8)

    def test_formal_master_field_details(self):
        dac = next(item for item in self.plan.patterns if item.pattern_name == "set_vposp_dac")
        write = dac.writes[0]
        self.assertEqual(write.addr_bits, "0010100")
        field = write.fields[0]
        self.assertEqual(field.field_name, "prog_pdac[4:0]")
        self.assertEqual((field.start_bit, field.bit_width, field.bit_hi, field.bit_lo), (9, 5, 9, 5))
        self.assertTrue(field.dynamic)

    def test_deleting_the_legacy_fixed_block_does_not_change_the_plan(self):
        """The plan must not depend on pattern rows 238-244 (the future
        deleted fixed set_all_final_vposp block)."""
        frame = self.workbook.dataframe("pattern")
        without_block = frame.drop(index=frame.index[236:243])  # sheet rows 238-244
        tables = tuple(
            TableModel.from_dataframe("pattern", without_block)
            if table.title == "pattern"
            else table
            for table in self.workbook.tables
        )
        variant = WorkbookModel(
            source_path=self.workbook.source_path,
            source_size=self.workbook.source_size,
            source_sha256=self.workbook.source_sha256,
            sheets=self.workbook.sheets,
            tables=tables,
            identity=self.workbook.identity,
        )
        plan = compile_fbist_pattern_plan(variant, self.flow)
        # the generation surface must be identical; only the row snapshot loses
        # the deleted excluded rows
        self.assertEqual(plan.patterns, self.plan.patterns)
        self.assertEqual(plan.pump_aggregate, self.plan.pump_aggregate)
        self.assertEqual(plan.pump_items, self.plan.pump_items)
        self.assertEqual(plan.clk_pin, self.plan.clk_pin)
        self.assertEqual(plan.swd_pin, self.plan.swd_pin)
        self.assertEqual(plan.dynamic_enter_patterns, self.plan.dynamic_enter_patterns)
        self.assertEqual(
            {row.excel_row for row in plan.rows},
            {row.excel_row for row in self.plan.rows} - set(range(238, 245)),
        )


if __name__ == "__main__":
    unittest.main()
