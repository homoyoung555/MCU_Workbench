"""BUILDUID compiler-to-adapter contract, independent of workbooks and legacy."""

from dataclasses import replace
from types import SimpleNamespace
import unittest
import random
import re

import pandas as pd

from program_gen.core.build_uid_module import compile_build_uid_module_plan
from program_gen.core.flash_label_plan import (
    FlashLabelRange, FlashLabelSpan, FlashUidVariant, FlashUidVariantNames, FlashLabelWordPlan,
)
from program_gen.platforms.chroma.build_uid_adapter import (
    adapt_build_uid as chroma_build, render_build_uid_support as chroma_support,
)
from program_gen.platforms.s100.build_uid_adapter import (
    adapt_build_uid as s100_build, render_build_uid_support as s100_support,
)


def fixture():
    def span(name, width=8, polarity="", msb=0):
        return FlashLabelSpan(name, msb, width, polarity,
                              FlashLabelRange("custom_w", "custom_w_st", "custom_w_sp"),
                              FlashLabelRange("custom_r", "custom_r_st", "custom_r_sp"))
    labels = ((0, (span("lot_number", 32),)),
              (1, (span("lot_number", 24), span("slot_number", msb=24))),
              (2, tuple(span(n, msb=i*8) for i, n in enumerate(("xy_coor", "x_coor", "y_coor", "year_month")))),
              (3, tuple(span(n, msb=i*8) for i, n in enumerate(("testing_house_id", "cp_ver_no", "crc_8")))),
              (4, (span("cp1_ver"), span("cp2_ver", msb=8))),
              (15, (span("project", 16, "n"), span("project", 16, "p", msb=16))))
    word_labels = tuple((i, (span(name, 32),)) for i, name in (
        (0, "lot0"), (1, "lot1"), (2, "uid_xy"), (3, "uid_info"),
        (4, "cp_ver"), (5, "cp12_id"), (6, "cp34_id"), (15, "project")))
    variant = FlashUidVariant(FlashUidVariantNames("cp4_id", "custom_prog", "custom_read", None),
                              ((3, 0xFFFFFF78), (5, 0x65BA78BA), (6, 0x9AFFFFFF)), identity_labels=word_labels)
    version = pd.DataFrame([{"CP num": "CP4", "Program Name": "V_TEST_V01_00_CP4",
                             "CP spec": "0x12", "CP ver high": "0x34", "CP ver low": "0x56",
                             "project name": "088", "project ver": "0x78"}])
    return version, SimpleNamespace(uid_variants=(variant,), uid_field_layout=labels,
                                    pages=(SimpleNamespace(name="uid", words=tuple(FlashLabelWordPlan(0xFFFFFFFF, "fixed") for _ in range(64))),))


class BuildUidModuleTests(unittest.TestCase):
    def test_compiled_facts_drive_both_platforms_without_pattern_mutation(self):
        version, labels = fixture()
        plan = compile_build_uid_module_plan(cp="CP4", version_frame=version, flash_label_plan=labels)
        self.assertEqual(dict(plan.constants)["PROJECT_NAME"], 88)
        self.assertEqual(len(plan.crc_table), 256)
        crc = 0
        for byte in b"123456789":
            crc = plan.crc_table[crc ^ byte]
        self.assertEqual((~crc) & 0xFF, 0x0B)
        self.assertEqual([(f.index, f.width) for f in plan.fields if f.semantic_name == "lot_number"], [(0, 32), (4, 24)])
        self.assertEqual(len(next(f for f in plan.fields if f.semantic_name == "project").spans), 2)
        self.assertNotIn("cp3_ver", {f.semantic_name for f in plan.fields})
        ch = "\n".join(chroma_build(plan).statements)
        si = "\n".join(s100_build(plan).statements)
        self.assertIn("READ_PROBER_XY", ch)
        self.assertIn("JUDGE_VARIABLE", ch)
        self.assertIn("C_COMPARE", si)
        self.assertEqual(si.count("C_COMPARE("), 2)
        self.assertIn("GB[0+T_SOCKET*64]=X_CO[T_SOCKET];\n    C_COMPARE", si)
        self.assertIn("LOT_ID[0]", ch)
        self.assertIn("Sys_gszProberWaferID[0]", si)
        self.assertIn("ucPtr[7]=wafer_num", si)
        self.assertIn("abs(Y_CO[T_SOCKET])", si)
        self.assertIn("(Y_CO[T_SOCKET]>>4)&0xF0", si)
        self.assertGreater(si.index("unsigned char CRC8=GetCRC8"), si.index("ucPtr[13]"))
        self.assertIn("  }\n  unsigned char CRC8=GetCRC8", si)
        self.assertIn("    unsigned char CRC8=GetCRC8", ch)
        self.assertIn("CRC8)", si)
        for body in (ch, si):
            self.assertNotIn("WRITE_PAT", body)
            self.assertNotIn("REG_", body)
        cglobals, chelpers, cstart, ctest = chroma_support(plan)
        self.assertIn("LOAD_ID_FLAG=1", cstart)
        self.assertIn("INPUT_BOX", ctest)
        self.assertIn("LOAD_ID_FLAG=0", ctest)
        self.assertIn("0x07", chelpers)
        self.assertIn("PROJECT_NAME=88", cglobals)
        self.assertEqual(s100_support(plan)[2:], ("", ""))
        for support in (chroma_support, s100_support):
            declarations = support(plan)[0]
            for word in plan.words:
                self.assertIn(f"uint32_t {word.symbol}[MAX_SITE];", declarations)
        for policy in plan.policies:
            for _, expression in policy.word_expressions:
                self.assertNotIn("long", expression)
            self.assertIn("(uint32_t)", policy.word_expressions[0][1])
        # The adapter must use supplied policy expressions, not recover its own source.
        p = plan.policy_for("chroma")
        patched = replace(p, crc_inputs=("17",) + p.crc_inputs[1:])
        changed = replace(plan, policies=(patched, plan.policy_for("s100")))
        self.assertIn("ucPtr[0]=17", "\n".join(chroma_build(changed).statements))
        # A CP without its own manufacturing variant consumes the shared layout.
        cp2_version = version.copy()
        cp2_version.loc[0, "CP num"] = "CP2"
        cp2_labels = SimpleNamespace(**{**vars(labels), "uid_variants": (
            replace(labels.uid_variants[0], names=replace(labels.uid_variants[0].names, name="cp2_id")),)})
        cp2 = compile_build_uid_module_plan(cp="CP2", version_frame=cp2_version, flash_label_plan=cp2_labels)
        self.assertEqual([f.semantic_name for f in cp2.fields], [f.semantic_name for f in plan.fields])
        duplicate_layout = SimpleNamespace(**{**vars(labels), "uid_variants": labels.uid_variants * 2})
        deduplicated = compile_build_uid_module_plan(cp="CP4", version_frame=version, flash_label_plan=duplicate_layout)
        self.assertEqual(deduplicated.fields, plan.fields)

        # The verified payload uses signed coordinate bits while CRC uses abs.
        scope = {"SOCKET": 0, "X_CO": [0x123], "Y_CO": [-0x234]}
        xy = next(f for f in plan.fields if f.semantic_name == "xy_coor")
        self.assertEqual(eval(dict(p.field_expressions)[xy.symbol], {}, scope), 0xD1)
        self.assertEqual(eval(p.crc_inputs[8], {}, scope), 0x21)
        altered = version.copy()
        altered.loc[0, "CP spec"] = "0x100"
        with self.assertRaisesRegex(ValueError, "CP_VERNO.*unsigned byte"):
            compile_build_uid_module_plan(cp="CP4", version_frame=altered, flash_label_plan=labels)


    def test_eight_word_expressions_match_independent_byte_layout(self):
        version, labels = fixture()
        plan = compile_build_uid_module_plan(cp="CP4", version_frame=version, flash_label_plan=labels)
        self.assertEqual(tuple(w.word_index for w in plan.words), (0, 1, 2, 3, 4, 5, 6, 15))
        def golden_xy(x, y):
            high = []
            for value in (y, x):
                # Golden TEMP is uint32_t: assignment precedes %2 and /2 extraction.
                temp, bits = value & 0xFFFFFFFF, []
                for _ in range(12):
                    bits.append(temp % 2)
                    temp //= 2
                high.append(sum(bits[8+i] << i for i in range(4)))
            return (high[0] << 4) | high[1]
        rng = random.Random(420)
        # Sweep every Lot byte value, coordinate extremes and asymmetric random inputs.
        cases = [(bytes([b]*7), 25, -1200, 5000, 9, 12) for b in range(256)]
        cases += [(rng.randbytes(7), rng.randrange(1, 26), rng.randrange(-1200, 5001),
                   rng.randrange(-1200, 5001), rng.randrange(100), rng.randrange(1, 13)) for _ in range(1000)]
        for platform in ("chroma", "s100"):
            policy = plan.policy_for(platform)
            expressions = [re.sub(r"(0x[0-9A-Fa-f]+)U", r"\1",
                                 re.sub(r"\((?:uint32_t|unsigned char)\)", "", expr))
                           for _, expr in policy.word_expressions]
            for lot, slot, x, y, year, month in cases:
                # CRC source retains the platform-specific slot choice and abs XY high bits.
                crc_slot = slot if platform == "chroma" else (slot % 25 + 1)
                crc_bytes = list(lot) + [crc_slot, (((abs(y)>>8)&15)<<4)|((abs(x)>>8)&15),
                                        x&255, y&255, ((year%10)<<4)+month, 0x56, 0x12]
                crc = 0
                for byte in crc_bytes:
                    crc ^= byte
                    for _ in range(8):
                        crc = ((crc<<1)^0x07)&255 if crc&128 else (crc<<1)&255
                crc = (~crc)&255
                scope = dict(plan.constants) | {"LOT_ID":lot, "Sys_gszProberWaferID":lot,
                    "SOCKET":0, "T_SOCKET":0, "X_CO":[x], "Y_CO":[y], "year":year,
                    "month":month, "WAFER_SLOT":slot, "wafer_num":crc_slot, "CRC8":crc}
                actual = [eval(expr, {"__builtins__": {}}, scope) for expr in expressions]
                expected = [int.from_bytes(lot[:4], "big"), int.from_bytes(lot[4:]+bytes([slot]), "big"),
                    int.from_bytes(bytes([golden_xy(x, y), x&255, y&255, ((year%10)<<4)+month]), "big"),
                    int.from_bytes(bytes([0x56, 0x12, crc, 0x78]), "big"),
                    0x3456FFFF, 0x65BA78BA, 0x9AFFFFFF, 0xA7875878]
                self.assertEqual(actual, expected, (platform, lot, slot, x, y))
        # The unused half-word is inherited from compiled page data, not guessed as FFFF.
        page = labels.pages[0]
        words = list(page.words)
        words[4] = replace(words[4], value=0xA5A51234)
        changed = compile_build_uid_module_plan(cp="CP4", version_frame=version,
            flash_label_plan=SimpleNamespace(**{**vars(labels), "pages": (SimpleNamespace(name="uid", words=tuple(words)),)}))
        self.assertEqual(changed.words[4].default_value, 0xA5A51234)
        self.assertTrue(changed.policy_for("chroma").word_expressions[4][1].startswith("0x00001234U|"))
        # Layout errors must fail before emitting an overlapping packed word.
        bad = list(labels.uid_field_layout)
        bad[1] = (1, (bad[1][1][0], replace(bad[1][1][1], msb_index=0)))
        with self.assertRaisesRegex(ValueError, "BUILDUID.WORD_LAYOUT"):
            compile_build_uid_module_plan(cp="CP4", version_frame=version,
                flash_label_plan=SimpleNamespace(**{**vars(labels), "uid_field_layout": tuple(bad)}))


if __name__ == "__main__":
    unittest.main()
