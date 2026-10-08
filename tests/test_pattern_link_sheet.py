import io
import unittest
from zipfile import ZipFile

from openpyxl import Workbook

from gui.workbook_editor import WorkbookEditor
from program_gen.core.pattern_links import PATTERN_LINKS_PART, patch_pattern_links, read_pattern_links


RECORDS = [{
    "cp": "CP1", "item": "SWD", "phase": "P0", "role": "read",
    "platform": "chroma", "original": "swd_read", "pattern": "swd_read_v2",
}]


def workbook_bytes():
    workbook = Workbook()
    workbook.active["A1"] = "value"
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class PatternLinkPartTests(unittest.TestCase):
    def test_patch_round_trip_and_preserves_other_parts(self):
        original = workbook_bytes()
        patched = patch_pattern_links(original, RECORDS)
        self.assertEqual(read_pattern_links(patched), RECORDS)
        with ZipFile(io.BytesIO(original)) as before, ZipFile(io.BytesIO(patched)) as after:
            self.assertEqual(set(before.namelist()), set(after.namelist()) - {PATTERN_LINKS_PART})
            for name in before.namelist():
                self.assertEqual(before.read(name), after.read(name), name)

    def test_editor_apply_explicit_links_reloads(self):
        original = workbook_bytes()
        editor = WorkbookEditor(original, "links.xlsx")
        saved = editor.apply(editor.sha256, [], pattern_links=RECORDS)
        self.assertEqual(WorkbookEditor(saved, "links.xlsx").pattern_links, RECORDS)
        self.assertEqual(read_pattern_links(saved), RECORDS)

    def test_invalid_record_is_rejected_before_writing(self):
        original = workbook_bytes()
        bad = [dict(RECORDS[0], pattern="not-valid!")]
        with self.assertRaises(ValueError):
            patch_pattern_links(original, bad)
        self.assertEqual(read_pattern_links(original), [])

    def test_duplicate_original_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_pattern_links(workbook_bytes(), RECORDS + [dict(RECORDS[0], pattern="other")])


if __name__ == "__main__":
    unittest.main()
