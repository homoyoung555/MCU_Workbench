import unittest
import re
from pathlib import Path

import pandas as pd

from program_gen.compiler import ProductCompiler
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.flash_label_plan import (
    FlashLabelCompileError,
    compile_flash_label_contract,
)
from program_gen.core.flash_label_renderer import render_flash_label_plan
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.render_plan import ResourceRequirement
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class FlashLabelGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        master = FORMAL_MASTER
        if not master.is_file():
            master = master.with_name("program_PCD009_V1.0.xlsx")
        workbook = WorkbookReader().read(master)
        cls.compilation = ProductCompiler().compile(workbook).require_success()
        cls.plan = cls.compilation.flash_label_plan
        cls.chroma = render_flash_label_plan(cls.plan, "chroma")
        cls.s100 = render_flash_label_plan(cls.plan, "s100")

    def test_product_plan_retains_all_complete_addr_map_pages(self):
        self.assertEqual(
            tuple(page.name for page in self.plan.pages),
            ("FT", "uid", "option0", "option1", "trim0", "trim1", "factory23"),
        )
        self.assertEqual(tuple(page.ra for page in self.plan.pages), tuple(range(0x19, 0x20)))
        self.assertEqual({len(page.words) for page in self.plan.pages}, {64})

    def test_uid_uses_eight_whole_word_labels_on_every_cp(self):
        for variant in self.plan.uid_variants:
            if variant.names.program_pattern is None:
                continue
            self.assertEqual(tuple(i for i, _ in variant.identity_labels), (0, 1, 2, 3, 4, 5, 6, 15))
            self.assertEqual(len(variant.identity_labels), 8)
            for _, spans in variant.identity_labels:
                self.assertEqual(len(spans), 1)
                self.assertEqual((spans[0].msb_index, spans[0].width, spans[0].polarity), (0, 32, ""))
            for result in (self.chroma, self.s100):
                for role in ("program", "read"):
                    name = getattr(variant.names, role + "_pattern")
                    source = next(a.content.decode("ascii") for a in result.artifacts if a.pattern_name == name)
                    lines = source.splitlines()
                    if result.platform == "chroma":
                        for line_index, line in enumerate(lines[:-1]):
                            if line.rstrip().endswith(":"):
                                lines[line_index + 1] = line.strip() + lines[line_index + 1].lstrip()
                    vectors = [line for line in lines
                               if re.search(r"\*[01HLXK]{3}\*|[01HLXK]{3}[01];", line)]
                    for index, spans in variant.identity_labels:
                        label = spans[0].write if role == "program" else spans[0].read
                        start = label.chroma_start if result.platform == "chroma" else label.s100_start
                        position, = [i for i, line in enumerate(vectors) if start + ":" in line]
                        if result.platform == "s100":
                            self.assertIn(label.s100_end + ":", vectors[position+31])
                        actual = "".join(re.search(r"\*([01HLXK]{3})\*|([01HLXK]{3})[01];", line).group(1 if result.platform == "chroma" else 2)[1]
                                         for line in vectors[position:position+32])
                        page = next(p for p in self.plan.pages if p.name == "uid")
                        value = dict(variant.word_overrides).get(index, page.words[index].value)
                        expected = f"{value:032b}"
                        if role == "read":
                            expected = expected.translate(str.maketrans("01", "LH"))
                        self.assertEqual(actual, expected, (name, index))

    def test_renderer_owns_the_complete_legacy_function_artifact_set(self):
        for result in (self.chroma, self.s100):
            names = {artifact.pattern_name for artifact in result.artifacts}
            self.assertEqual(len(names), 33)
            self.assertNotIn("uid_image_capture", names)
            self.assertFalse(any(name.endswith("bake_id") and "_check_" not in name for name in names))
            self.assertIn("fbist_page_erase_FT", names)
            self.assertIn("fbist_page_prog_option1", names)
            self.assertIn("fbist_page_read_cp3_id", names)
            self.assertIn("fbist_page_check_cp2_bake_id", names)
            self.assertIn("factory23_capture", names)

    def test_program_read_capture_and_uid_check_are_readable_variants(self):
        chroma = {item.pattern_name: item.content for item in self.chroma.artifacts}
        s100 = {item.pattern_name: item.content for item in self.s100.artifacts}
        self.assertIn(b"_w_n:", chroma["fbist_page_prog_trim0"])
        self.assertIn(b"_r_n:", chroma["fbist_page_read_trim0"])
        self.assertIn(b"lot0_w:", chroma["fbist_page_prog_cp3_id"])
        self.assertIn(b"uid_info_r:", chroma["fbist_page_read_cp3_id"])
        self.assertIn(b"cp12_id_w:", chroma["fbist_page_prog_cp1_id"])
        self.assertIn(b"cp34_id_r:", chroma["fbist_page_read_cp3_id"])
        self.assertIn(b"project_w:", chroma["fbist_page_prog_cp3_id"])
        for frequency in ("8m", "16m", "24m", "48m"):
            base = f"hsi_{frequency}_trim".encode("ascii")
            self.assertIn(base + b"_w:", chroma["fbist_page_prog_cp3_id"])
            self.assertIn(base + b"_r:", chroma["fbist_page_read_cp3_id"])
            self.assertIn(base + b"_w_st:", s100["fbist_page_prog_cp3_id"])
            self.assertIn(base + b"_r_st:", s100["fbist_page_read_cp3_id"])
            self.assertNotIn(base + b"w", chroma["fbist_page_prog_cp3_id"])
            self.assertNotIn(base + b"r", chroma["fbist_page_read_cp3_id"])
        self.assertIn(b"vrefint_w_n:", chroma["fbist_page_prog_cp3_id"])
        self.assertIn(b"_w_n_st:", s100["fbist_page_prog_trim0"])
        self.assertIn(b"_r_n_sp:", s100["fbist_page_read_trim0"])
        self.assertIn(b"1K1", chroma["trim0_capture"])
        self.assertIn(b"TRIGPIN", s100["trim0_capture"])
        self.assertIn(b"PTN_TRIG", s100["trim0_capture"])
        check = chroma["fbist_page_check_cp1_id"]
        self.assertIn(b"1H1", check)
        self.assertIn(b"1X1", check)

    def test_chroma_labels_are_on_the_line_before_their_vectors(self):
        source = next(
            item.content.decode("ascii")
            for item in self.chroma.artifacts
            if item.pattern_name == "fbist_page_prog_trim0"
        )
        self.assertRegex(source, r"(?m)^      [a-z0-9_]+:\n      \*[01HLXK]{3}\*")
        self.assertNotRegex(source, r"(?m)^      [a-z0-9_]+:\*[01HLXK]{3}\*")

    def test_s100_label_and_plain_vectors_use_one_data_column(self):
        source = next(
            item.content.decode("ascii")
            for item in self.s100.artifacts
            if item.pattern_name == "fbist_page_prog_trim0"
        )
        vector_columns = []
        for line in source.splitlines():
            search_from = line.index(":") + 1 if ":" in line else 0
            match = re.search(r"[01HLXK]{3}[01];", line[search_from:])
            if match:
                vector_columns.append(search_from + match.start())
        self.assertGreater(len(vector_columns), 1)
        self.assertEqual(len(set(vector_columns)), 1)

    def test_each_data_word_has_its_final_32_bit_addr_map_value_comment(self):
        expected = re.compile(
            rb"// ADDR_MAP uid Word\[(\d{2})\] = 32'h([0-9A-F]{4})_([0-9A-F]{4})"
        )
        uid_page = next(page for page in self.plan.pages if page.name == "uid")
        cp1 = next(
            variant for variant in self.plan.uid_variants
            if variant.names.program_pattern == "fbist_page_prog_cp1_id"
        )
        final_values = {
            index: word.value for index, word in enumerate(uid_page.words)
        }
        final_values.update(dict(cp1.word_overrides))

        for result in (self.chroma, self.s100):
            artifact = next(
                item for item in result.artifacts
                if item.pattern_name == cp1.names.program_pattern
            )
            comments = expected.findall(artifact.content)
            self.assertEqual(len(comments), 64)
            actual = {
                int(index): int(high + low, 16)
                for index, high, low in comments
            }
            self.assertEqual(actual, final_values)

    def test_generated_overlay_serves_flash_label_artifact(self):
        producer = GeneratedPatternProducer(self.chroma)
        request = producer.produce(ResourceRequirement(
            logical_identity="pattern:trim0_capture",
            relative_path="pat/trim0_capture.pat",
            spec_identity="v14.pattern/1:chroma:trim0_capture",
            purpose="Flash Label capture",
        ))
        self.assertTrue(request.source_identity.startswith("flash-label:"))
        self.assertIn(b"SPM_PATTERN(trim0_capture)", request.content)

    def test_compilation_factory_overlays_flash_label_with_other_generators(self):
        producer = GeneratedPatternProducer.from_compilation(
            self.compilation, "chroma"
        )
        request = producer.produce(ResourceRequirement(
            logical_identity="pattern:fbist_page_prog_cp3_id",
            relative_path="pat/fbist_page_prog_cp3_id.pat",
            spec_identity="v14.pattern/1:chroma:fbist_page_prog_cp3_id",
            purpose="UID Page Program",
        ))
        self.assertTrue(request.source_identity.startswith("flash-label:"))
        self.assertIn(b"cp12_id_w:", request.content)

    def test_compiler_contract_is_the_only_name_source_for_producer_and_consumer(self):
        binding = self.plan.contract.bind_register("trim1", "ANA_MUX_TRIM2", "CP1")
        self.assertEqual(binding.program_pattern, "fbist_page_prog_trim1")
        self.assertEqual(binding.read_pattern, "fbist_page_read_trim1")
        positive = next(span for span in binding.spans if span.polarity == "p")
        self.assertEqual(positive.write.chroma_start, "ana_mux_trim2_w_p")
        self.assertEqual(positive.read.s100_end, "ana_mux_trim2_r_p_sp")

        chroma = {item.pattern_name: item.content for item in self.chroma.artifacts}
        s100 = {item.pattern_name: item.content for item in self.s100.artifacts}
        self.assertIn(
            (positive.write.chroma_start + ":").encode("ascii"),
            chroma[binding.program_pattern],
        )
        self.assertIn(
            (positive.read.s100_end + ":").encode("ascii"),
            s100[binding.read_pattern],
        )

    def test_renderer_has_no_workbook_global_or_file_access(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "program_gen/core/flash_label_renderer.py"
        ).read_text("utf-8")
        forbidden = (
            "Workbook", "openpyxl", "import pandas", "program_gen import state",
            "G.", "open(", "Path(",
        )
        self.assertEqual(tuple(token for token in forbidden if token in source), ())
        self.assertNotIn('f"fbist_page_', source)

    def test_contract_rejects_two_registers_that_sanitize_to_the_same_label(self):
        catalog = compile_addr_map_catalog(pd.DataFrame((
            {
                "Word No.": "trim0", "line": "CP1",
                "bit[31:16]": "16'h0000", "bit[15:0]": "A[15:0]",
                "data type": "lable", "CP Data[31:0]": "32'h0000_0000",
                "CP addr map": "X[15:0]",
            },
            {
                "Word No.": "trim0", "line": "CP1",
                "bit[31:16]": "16'h0000", "bit[15:0]": "A_VERIFY[15:0]",
                "data type": "lable", "CP Data[31:0]": "32'h0000_0000",
                "CP addr map": "Y[15:0]",
            },
        )))
        with self.assertRaisesRegex(
            FlashLabelCompileError, "FLASH_LABEL.LABEL_NAME_CONFLICT"
        ):
            compile_flash_label_contract(catalog)


if __name__ == "__main__":
    unittest.main()
