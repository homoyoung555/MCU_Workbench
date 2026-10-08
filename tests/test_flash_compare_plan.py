import unittest
from dataclasses import replace
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

from program_gen.core.flash_compare_plan import (
    BulkCoverage,
    BulkStrategy,
    DataKind,
    FlashCompareCompileError,
    FlashCompareFacts,
    FlashHardwareFacts,
    FlashModeFacts,
    FlashOprFacts,
    FlashRegister,
    FlashRegisterField,
    FlashCompareRequest,
    FlashProductDefinitionMissing,
    KnownPage,
    Operation,
    PageData,
    PageTarget,
    Region,
    Scope,
    compile_flash_compare_plan,
    compile_flash_compare_plans,
    custom_page_data,
    materialize_page_data,
    parse_word_value,
    random_page_data,
    serialize_command_groups,
)
from program_gen.core.flash_compare_renderer import (
    render_flash_compare_plan,
    render_flash_compare_plans,
)
from program_gen.core.flash_compare_product import (
    RequiredFlashCompareCompilation,
    compile_required_flash_compare_plans,
)
from program_gen import state as G
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


FACTS = FlashCompareFacts(
    product_identity="PCD009-test",
    nm_page_count=1024,
    bank_count=2,
    page_bytes=256,
    program_bits=32,
    read_bits=64,
    comp_flag_byte=0x5A,
    known_pages=(
        KnownPage("UID", Region.SM, 0, 0x1A),
        KnownPage("TRIM0", Region.SM, 0, 0x1D),
        KnownPage("TRIM1", Region.SM, 0, 0x1E),
    ),
)


HARDWARE = FlashHardwareFacts(
    clk_pin="PA11",
    swd_pin="PA13",
    registers=(
        FlashRegister("0011110", (FlashRegisterField("RA", 0, 8),)),
        FlashRegister("0011111", (
            FlashRegisterField("AXA", 11, 1), FlashRegisterField("CA", 6, 5),
            FlashRegisterField("PA", 0, 6),
        )),
        FlashRegister("0100000", (
            FlashRegisterField("PE", 6, 1), FlashRegisterField("SEQ", 4, 2),
            FlashRegisterField("MODE", 0, 4),
        )),
        FlashRegister("0100001", (
            FlashRegisterField("READ_MODE", 11, 1), FlashRegisterField("ADDR_MODE", 9, 2),
            FlashRegisterField("COMP_MODE", 8, 1), FlashRegisterField("COMP_DATA", 0, 8),
        )),
        FlashRegister("0100011", (FlashRegisterField("COMPARE_NUMBER", 0, 15),)),
        FlashRegister("0100100", (
            FlashRegisterField("RED3_EN", 9, 1), FlashRegisterField("RED2_EN", 8, 1),
            FlashRegisterField("RED1_EN", 7, 1), FlashRegisterField("RED0_EN", 6, 1),
            FlashRegisterField("OPR_SEL", 4, 2), FlashRegisterField("BANK_SEL", 2, 2),
        )),
        FlashRegister("0110011", (FlashRegisterField("BANK_EN", 8, 2),)),
    ),
    modes=FlashModeFacts("0101", "0001", "0110", "0111", "1000", "1011", "1100", "1110", "1111"),
    opr=FlashOprFacts("00", "10", "01"),
)
RENDER_FACTS = replace(FACTS, hardware=HARDWARE)


def request(**changes):
    values = dict(
        output_identity="optional_flash_pattern",
        scope=Scope.PAGE,
        operation=Operation.PROGRAM,
        data=PageData(DataKind.ZERO),
        pages=(PageTarget(page_index=0),),
    )
    values.update(changes)
    return FlashCompareRequest(**values)


class PagePlanTests(unittest.TestCase):
    def test_fixed_seed_builds_one_reproducible_page_payload(self):
        first = random_page_data(0x5043443030395631, FACTS.page_bytes)
        repeated = random_page_data(0x5043443030395631, FACTS.page_bytes)
        other = random_page_data(0x5043443030395632, FACTS.page_bytes)

        self.assertEqual((first.kind, len(first.payload)), (DataKind.CUSTOM, 256))
        self.assertEqual(first.random_seed, 0x5043443030395631)
        self.assertEqual(first, repeated)
        self.assertNotEqual(first.payload, other.payload)

    def test_nm_page_index_derives_bank_and_ra_at_boundaries(self):
        plan = compile_flash_compare_plan(
            request(
                pages=tuple(PageTarget(page_index=index) for index in (511, 512, 525, 1023))
            ),
            FACTS,
        )
        self.assertEqual(
            tuple((item.logical_bank, item.bank_bits, item.axa, item.ra) for item in plan.passes),
            ((0, "01", 0, 511), (1, "10", 0, 0), (1, "10", 0, 13), (1, "10", 0, 511)),
        )

    def test_known_sm_page_forces_axa_one_and_bank_zero(self):
        plan = compile_flash_compare_plan(
            request(pages=(PageTarget(known_page="trim0"),)), FACTS
        )
        item = plan.passes[0]
        self.assertEqual((item.logical_bank, item.bank_bits, item.axa, item.ra), (0, "01", 1, 0x1D))

    def test_page_operation_stages_are_closed_per_page(self):
        erase = compile_flash_compare_plan(
            request(operation=Operation.ERASE, data=None), FACTS
        )
        program = compile_flash_compare_plan(request(), FACTS)
        read = compile_flash_compare_plan(
            request(operation=Operation.READ), FACTS
        )
        self.assertEqual(erase.passes[0].stages, ("pre_program", "erase", "clear_latches"))
        self.assertEqual(program.passes[0].stages, ("clear_latches", "write_latches", "program"))
        self.assertEqual(read.passes[0].stages, ("read_compare",))
        self.assertEqual((program.program_groups_per_page, read.read_groups_per_page), (64, 32))

    def test_page_target_forms_are_mutually_exclusive(self):
        for target in (PageTarget(), PageTarget(page_index=0, known_page="UID")):
            with self.subTest(target=target), self.assertRaises(FlashCompareCompileError):
                compile_flash_compare_plan(request(pages=(target,)), FACTS)


class DataTests(unittest.TestCase):
    def test_word_input_forms_are_equivalent(self):
        self.assertEqual(parse_word_value("44 33 22 11"), 0x44332211)
        self.assertEqual(parse_word_value("0x44332211"), 0x44332211)

    def test_custom_page_requires_exact_full_page(self):
        words = [0x44332211] + [0] * 63
        data = custom_page_data(words, FACTS.page_bytes)
        self.assertEqual(materialize_page_data(data, FACTS)[:4], bytes.fromhex("44332211"))
        with self.assertRaisesRegex(FlashCompareCompileError, "exactly 64 words"):
            custom_page_data(words[:-1], FACTS.page_bytes)

    def test_pckb_and_nckb_are_eight_byte_inverse_blocks(self):
        pckb = materialize_page_data(PageData(DataKind.PCKB), FACTS)
        nckb = materialize_page_data(PageData(DataKind.NCKB), FACTS)
        self.assertEqual(pckb[:24], bytes(8) + bytes([0xFF]) * 8 + bytes(8))
        self.assertEqual(nckb, bytes(value ^ 0xFF for value in pckb))

    def test_command_groups_keep_group_addresses_and_send_high_word_first(self):
        words = [0x00000000, 0x11111111] + [0] * 62
        data = custom_page_data(words, FACTS.page_bytes)
        program = serialize_command_groups(data, FACTS, FACTS.program_bits)
        read = serialize_command_groups(data, FACTS, FACTS.read_bits)
        self.assertEqual(program[:2], ("0" * 32, "00010001" * 4))
        self.assertEqual(read[0], "00010001" * 4 + "0" * 32)


class BulkPlanTests(unittest.TestCase):
    def test_even_odd_is_parity_major_and_cross_page_inverts_chessboard(self):
        plan = compile_flash_compare_plan(
            request(
                scope=Scope.BULK,
                pages=(),
                bulk_strategy=BulkStrategy.EVEN_ODD,
                bulk_coverage=BulkCoverage.NM_ONLY,
                data=PageData(DataKind.PCKB),
            ),
            FACTS,
        )
        self.assertEqual(
            tuple((item.logical_bank, item.parity, item.ra, item.data.kind) for item in plan.passes),
            (
                (0, "odd", 1, DataKind.PCKB),
                (1, "odd", 1, DataKind.PCKB),
                (0, "even", 0, DataKind.NCKB),
                (1, "even", 0, DataKind.NCKB),
            ),
        )

    def test_all_pages_keeps_selected_phase_and_coverage_is_axa(self):
        plan = compile_flash_compare_plan(
            request(
                scope=Scope.BULK,
                pages=(),
                bulk_strategy=BulkStrategy.ALL_PAGES,
                bulk_coverage=BulkCoverage.NM_PLUS_SM,
                data=PageData(DataKind.NCKB),
            ),
            FACTS,
        )
        self.assertEqual(
            tuple((item.logical_bank, item.axa, item.ra, item.data.kind) for item in plan.passes),
            ((0, 1, 0, DataKind.NCKB), (1, 1, 0, DataKind.NCKB)),
        )

    def test_bulk_erase_has_no_strategy_and_closes_each_bank(self):
        plan = compile_flash_compare_plan(
            request(
                scope=Scope.BULK,
                operation=Operation.ERASE,
                data=None,
                pages=(),
                bulk_coverage=BulkCoverage.NM_PLUS_SM,
            ),
            FACTS,
        )
        self.assertEqual(len(plan.passes), 2)
        self.assertEqual(plan.passes[0].stages, ("pre_program", "erase", "clear_latches"))
        self.assertTrue(all(item.axa == 1 for item in plan.passes))
        with self.assertRaisesRegex(FlashCompareCompileError, "has no"):
            compile_flash_compare_plan(
                request(
                    scope=Scope.BULK,
                    operation=Operation.ERASE,
                    data=None,
                    pages=(),
                    bulk_strategy=BulkStrategy.ALL_PAGES,
                ),
                FACTS,
            )

    def test_bulk_read_is_nm_only_internal_compare(self):
        plan = compile_flash_compare_plan(
            request(scope=Scope.BULK, operation=Operation.READ, pages=()), FACTS
        )
        self.assertEqual(tuple(item.axa for item in plan.passes), (0, 0))
        self.assertEqual(tuple(item.compare_number for item in plan.passes), (0x4000, 0x4000))
        self.assertEqual(plan.comp_flag_bits, "01011010")
        with self.assertRaisesRegex(FlashCompareCompileError, "NM_ONLY"):
            compile_flash_compare_plan(
                request(
                    scope=Scope.BULK,
                    operation=Operation.READ,
                    pages=(),
                    bulk_coverage=BulkCoverage.NM_PLUS_SM,
                ),
                FACTS,
            )

    def test_bulk_custom_read_is_rejected(self):
        with self.assertRaisesRegex(FlashCompareCompileError, "Page Read"):
            compile_flash_compare_plan(
                request(
                    scope=Scope.BULK,
                    operation=Operation.READ,
                    pages=(),
                    data=custom_page_data([0] * 64, FACTS.page_bytes),
                ),
                FACTS,
            )

    def test_repair_uses_same_address_and_compare_payload_as_bulk_read(self):
        bulk_read = compile_flash_compare_plan(
            request(scope=Scope.BULK, operation=Operation.READ, pages=()), FACTS
        )
        repair = compile_flash_compare_plan(
            request(
                scope=Scope.BULK,
                operation=Operation.REPAIR,
                pages=(),
                repair_bank=1,
            ),
            FACTS,
        )
        baseline = bulk_read.passes[1]
        actual = repair.passes[0]
        self.assertEqual(
            (actual.logical_bank, actual.bank_bits, actual.axa, actual.ra, actual.data, actual.compare_number),
            (baseline.logical_bank, baseline.bank_bits, baseline.axa, baseline.ra, baseline.data, baseline.compare_number),
        )
        self.assertEqual((baseline.fbist_cmd, actual.fbist_cmd), ("1101", "1010"))
        self.assertEqual(actual.stages, ("repair_compare_internal",))

    def test_repair_requires_one_explicit_bank_and_builtin_compare_data(self):
        with self.assertRaisesRegex(FlashCompareCompileError, "repair_bank"):
            compile_flash_compare_plan(
                request(scope=Scope.BULK, operation=Operation.REPAIR, pages=()), FACTS
            )
        with self.assertRaisesRegex(FlashCompareCompileError, "Page Read"):
            compile_flash_compare_plan(
                request(
                    scope=Scope.BULK,
                    operation=Operation.REPAIR,
                    pages=(),
                    repair_bank=0,
                    data=custom_page_data([0] * 64, FACTS.page_bytes),
                ),
                FACTS,
            )


class BoundaryTests(unittest.TestCase):
    def test_sector_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(FlashProductDefinitionMissing, "SECTOR_PRODUCT_DEFINITION_MISSING"):
            compile_flash_compare_plan(
                request(scope=Scope.SECTOR), FACTS
            )

    def test_plan_is_deterministic(self):
        first = compile_flash_compare_plan(request(), FACTS)
        second = compile_flash_compare_plan(request(), FACTS)
        self.assertEqual(first, second)
        self.assertEqual(first.identity, second.identity)

    def test_batch_api_preserves_order_and_rejects_identity_collision(self):
        first = request(output_identity="first")
        second = request(output_identity="second", operation=Operation.READ)
        plans = compile_flash_compare_plans((first, second), RENDER_FACTS)
        self.assertEqual(tuple(item.output_identity for item in plans), ("first", "second"))
        result = render_flash_compare_plans(plans, "chroma")
        self.assertEqual(tuple(item.pattern_name for item in result.artifacts), ("first", "second"))
        with self.assertRaisesRegex(FlashCompareCompileError, "duplicate"):
            compile_flash_compare_plans((first, first), RENDER_FACTS)


class PureRendererTests(unittest.TestCase):
    def test_platform_publishers_write_only_renderer_artifacts(self):
        plan = compile_flash_compare_plan(request(), RENDER_FACTS)
        compilation = RequiredFlashCompareCompilation(RENDER_FACTS, (plan,), ())
        publishers = (
            ("chroma", ".pat", "program_gen.platforms.chroma.pattern_files"),
            ("s100", ".sd", "program_gen.platforms.s100.pattern_files"),
        )
        for platform, extension, module_name in publishers:
            with self.subTest(platform=platform), TemporaryDirectory() as temporary:
                module = __import__(module_name, fromlist=["flash_compare_patterns_created"])
                with patch.object(G, "BASE_DIR", temporary):
                    result = module.flash_compare_patterns_created(compilation)
                output = Path(temporary, "pat_temp", f"optional_flash_pattern{extension}")
                self.assertEqual(output.read_bytes(), result.artifacts[0].content)

    def test_both_platforms_render_from_plan_only(self):
        plan = compile_flash_compare_plan(request(), RENDER_FACTS)
        chroma = render_flash_compare_plan(plan, "chroma")
        s100 = render_flash_compare_plan(plan, "s100")
        self.assertEqual(chroma.artifacts[0].relative_path, "pat/optional_flash_pattern.pat")
        self.assertEqual(s100.artifacts[0].relative_path, "optional_flash_pattern.sd")
        self.assertIn(b"SPM_PATTERN(optional_flash_pattern)", chroma.artifacts[0].content)
        self.assertIn(b"@@PATTERN_DEFINE", s100.artifacts[0].content)
        self.assertIn(b"Cmd[3:0]=1001 write data", chroma.artifacts[0].content)

    def test_repair_has_its_own_redundancy_protocol(self):
        read = compile_flash_compare_plan(
            request(scope=Scope.BULK, operation=Operation.READ, pages=()), RENDER_FACTS
        )
        repair = compile_flash_compare_plan(
            request(
                scope=Scope.BULK, operation=Operation.REPAIR, pages=(), repair_bank=1,
            ),
            RENDER_FACTS,
        )
        read_text = render_flash_compare_plan(read, "chroma").artifacts[0].content
        repair_text = render_flash_compare_plan(repair, "chroma").artifacts[0].content
        self.assertIn(b"Cmd[3:0]=1101", read_text)
        self.assertIn(b"Cmd[3:0]=1010", repair_text)
        self.assertIn(b"RED3_EN=1, RED2_EN=1, RED1_EN=1, RED0_EN=1", repair_text)
        self.assertNotIn(b"RED3_EN=1, RED2_EN=1, RED1_EN=1, RED0_EN=1", read_text)

    def test_renderer_has_no_workbook_global_or_file_access(self):
        source = (Path(__file__).resolve().parents[1] / "program_gen/core/flash_compare_renderer.py").read_text("utf-8")
        forbidden = ("Workbook", "openpyxl", "import pandas", "program_gen import state", "G.", "open(", "Path(")
        self.assertEqual(tuple(token for token in forbidden if token in source), ())


class FormalMasterCompilationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = compile_required_flash_compare_plans(
            WorkbookReader().read(FORMAL_MASTER)
        )

    def test_hardware_facts_are_frozen_upstream(self):
        facts = self.compilation.facts
        self.assertEqual(
            (facts.nm_page_count, facts.bank_count, facts.page_bytes, facts.program_bits, facts.read_bits),
            (1024, 2, 256, 32, 64),
        )
        self.assertEqual(facts.boot_loader_page_count, 23)
        self.assertEqual(len(facts.hardware.registers), 7)
        self.assertEqual(facts.hardware.modes.program_page, "1100")

    def test_all_required_patterns_compile_after_ra_and_random_decisions(self):
        self.assertEqual(len(self.compilation.plans), 31)
        self.assertEqual(self.compilation.unsupported, ())
        self.assertIs(self.compilation.require_complete(), self.compilation)

        random = next(
            plan for plan in self.compilation.plans
            if plan.output_identity == "fbist_page_epr_rdm_nm"
        )
        self.assertEqual(len(random.passes), 1024)
        self.assertEqual(len({item.data.payload for item in random.passes}), 1)
        self.assertEqual(len(random.passes[0].data.payload), 256)
        self.assertEqual(random.passes[0].data.random_seed, 0x5043443030395631)

        pckb_sm = next(
            plan for plan in self.compilation.plans
            if plan.output_identity == "fbist_bulk_prog_ckbd_nm_sm"
        )
        self.assertEqual(len(pckb_sm.passes), 4)
        self.assertEqual(tuple(item.axa for item in pckb_sm.passes), (1, 1, 1, 1))
        self.assertEqual(
            tuple((item.parity, item.data.kind) for item in pckb_sm.passes),
            (("odd", DataKind.PCKB), ("odd", DataKind.PCKB),
             ("even", DataKind.NCKB), ("even", DataKind.NCKB)),
        )

    def test_bootloader_epr_is_composite_and_repair_is_single_bank(self):
        by_name = {plan.output_identity: plan for plan in self.compilation.plans}
        epr = by_name["fbist_page_epr_all0_btld"]
        repair = by_name["fbist_bulk_repair_ckbd_bank1"]
        self.assertEqual((epr.operation, len(epr.passes)), (Operation.EPR, 23))
        self.assertEqual((repair.operation, len(repair.passes)), (Operation.REPAIR, 1))
        self.assertEqual((repair.passes[0].logical_bank, repair.passes[0].fbist_cmd), (1, "1010"))

    def test_one_required_plan_renders_without_workbook(self):
        plan = next(
            item for item in self.compilation.plans
            if item.output_identity == "fbist_bulk_repair_all0_bank0"
        )
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                result = render_flash_compare_plan(plan, platform)
                self.assertTrue(result.artifacts[0].content)

    def test_confirmed_legacy_sequences_match_both_platform_goldens(self):
        by_name = {plan.output_identity: plan for plan in self.compilation.plans}
        workspace = FORMAL_MASTER.parents[2]
        cases = (
            "fbist_erase_main_1st_page",
            "fbist_bulk_erase_nm",
            "fbist_bulk_erase_nm_sm",
            "fbist_bulk_prog_all0_nm",
            "fbist_bulk_prog_ckbd_nm",
            "fbist_bulk_read_all0_nm",
        )
        for platform, root_name, extension in (
            ("chroma", "Chroma", "pat"),
            ("s100", "S100", "sd"),
        ):
            root = workspace / "golden" / "PCD009_V0.9" / root_name
            for name in cases:
                with self.subTest(platform=platform, pattern=name):
                    actual = render_flash_compare_plan(
                        by_name[name], platform
                    ).artifacts[0].content.decode("ascii")
                    golden = next(root.glob(f"**/{name}.{extension}")).read_text(
                        encoding="utf-8", errors="replace"
                    )
                    self.assertEqual(
                        _semantic_vectors(actual, platform),
                        _semantic_vectors(golden, platform),
                    )

    def test_repair_sequences_match_chroma_goldens(self):
        by_name = {plan.output_identity: plan for plan in self.compilation.plans}
        root = FORMAL_MASTER.parents[2] / "golden" / "PCD009_V0.9" / "Chroma"
        names = tuple(
            sorted(name for name in by_name if name.startswith("fbist_bulk_repair_"))
        )
        self.assertEqual(len(names), 8)
        for name in names:
            with self.subTest(pattern=name):
                actual = render_flash_compare_plan(
                    by_name[name], "chroma"
                ).artifacts[0].content.decode("ascii")
                golden = next(root.glob(f"**/{name}.pat")).read_text(
                    encoding="utf-8", errors="replace"
                )
                self.assertEqual(
                    _semantic_vectors(actual, "chroma"),
                    _semantic_vectors(golden, "chroma"),
                )

    def test_epr_uses_confirmed_page_read_policy_not_stale_golden_fields(self):
        plan = next(
            item for item in self.compilation.plans
            if item.output_identity == "fbist_page_epr_all0_btld"
        )
        text = render_flash_compare_plan(plan, "chroma").artifacts[0].content.decode("ascii")
        self.assertIn("READ_MODE=1", text)
        self.assertIn("COMPARE_NUMBER=000000000000000", text)


def _semantic_vectors(text, platform):
    rows = []
    for line in text.splitlines():
        stripped = re.sub(r"//.*", "", line).strip()
        stripped = re.sub(r"^pe_\d+:", "", stripped)
        if platform == "chroma" and "*" in stripped:
            rows.append(stripped)
        elif platform == "s100" and (
            re.search(r"[01HLXK]{3};", stripped)
            or stripped.startswith(("START:", "END:"))
        ):
            rows.append(stripped)
    return tuple(rows)


if __name__ == "__main__":
    unittest.main()
