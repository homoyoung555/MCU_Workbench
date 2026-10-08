import unittest
from types import SimpleNamespace
import pandas as pd
from program_gen.compiler import ProductCompiler
from program_gen.core.freq_test import compile_freq_test_plans, FreqTestCompileError
from program_gen.platforms.chroma.freq_test_renderer import render_freq_test as chroma
from program_gen.platforms.s100.freq_test_renderer import render_freq_test as s100
from program_gen.platforms.chroma.firmware_test_renderer import action_pattern_span as chroma_span
from program_gen.platforms.s100.firmware_test_renderer import action_pattern_span as s100_span


class FreqKeilTests(unittest.TestCase):
    def plan(self, template="7-X-99", steps=("11", "RP-22"), mode="keil"):
        op = SimpleNamespace(row=0, cp="CP1", item="Clock", mode=mode, typed_kind="FREQ_TEST", provenance=None)
        flow = pd.DataFrame([{"FV/FI":"FREQ", "step":template, "Vcc":"VCC_TYP", "meas pin":"PA1"}])
        freq = pd.DataFrame([{"FREQ":"Clock", "source":source, "mul":1, "div":1,
            "down_limit":"1%", "up_limit":"1%", "step":step}
            for source, step in zip(("HSI_8M", "HSE_32M"), steps)])
        version = pd.DataFrame([{"CP num":"CP1", "product name":"P", "GET PIN":"PA0"}])
        iomux = pd.DataFrame([{"pin":"PD0", "role":"OSCIN"}])
        return compile_freq_test_plans((op,), {}, flow, freq, iomux, version)[0]

    def test_keil_repower_replays_entry_then_case_and_exits_once(self):
        plan = self.plan()
        self.assertEqual(plan.session_count, 2)
        self.assertEqual(plan.config_patterns, ())
        self.assertEqual([a.value for a in plan.entry_actions], [7])
        self.assertEqual([c.actions[0].value for c in plan.cases], [11, 22])
        for platform, renderer, span, measurement in (
            ("chroma", chroma, chroma_span, "JUDGE_FREQ("),
            ("s100", s100, s100_span, "LOGIC_TMU_MEAS_FREQ(")):
            with self.subTest(platform=platform):
                rendered = renderer(plan, "Clock", 1, SimpleNamespace(platform=platform, cp="CP1"))
                content = rendered.content
                self.assertFalse(rendered.resource_requires)
                self.assertTrue(rendered.resources)
                self.assertNotIn("SWD_FREQ", content)
                self.assertEqual(content.count(measurement), 2)
                entry, case1, case2, exit = [span(a)[0] for a in
                    (plan.entry_actions[0], plan.cases[0].actions[0], plan.cases[1].actions[0], plan.exit_actions[0])]
                cursor = 0
                for token in ("POWER_ON(", entry, case1, measurement, "POWER_OFF(", "POWER_ON(", entry,
                              "PD0", case2, measurement, exit, "POWER_OFF("):
                    cursor = content.index(token, cursor) + len(token)
                self.assertEqual(content.count("POWER_ON("), 2)

    def test_legacy_implicit_slot_and_empty_template(self):
        self.assertEqual(len(self.plan(template="7").entry_actions), 1)
        self.assertEqual(self.plan(template="/").entry_actions, ())

    def test_invalid_keil_steps_rejected_with_freq_location(self):
        for steps, code in ((("RP-11", "22"), "FREQ.RP.FIRST_CASE"),
                            (("11", "22-RP"), "FREQ.RP.POSITION_INVALID"),
                            (("11", "RP"), "FREQ.CASE.STEP.EMPTY"),
                            (("11", "FS"), "FREQ.ACTION.INVALID"),
                            (("11", "bad"), "FREQ.CASE.STEP.INVALID")):
            with self.subTest(steps=steps), self.assertRaises(FreqTestCompileError) as ctx:
                self.plan(steps=steps)
            self.assertEqual(ctx.exception.code, code)
        for template in ("7-X-X", "RP-X", "X-FS"):
            with self.subTest(template=template), self.assertRaises(FreqTestCompileError):
                self.plan(template=template)

    def test_swd_keeps_step_restrictions(self):
        self.assertEqual(len(self.plan(template="/", steps=("/", "RP"), mode="swd").config_patterns), 2)
        shared = self.plan(template="/", steps=("11", "RP-22"), mode="swd")
        self.assertEqual(len(shared.config_patterns), 2)
        self.assertEqual(shared.session_count, 2)
        self.assertTrue(all(not case.actions for case in shared.cases))
        self.assertEqual(self.plan(template="/", steps=("PA0:11", "PA0:RP-22"), mode="swd").session_count, 2)
        for steps in (("RP-11", "22"), ("11", "22-RP"), ("11", "RP-RP-22")):
            with self.subTest(steps=steps), self.assertRaises(FreqTestCompileError):
                self.plan(template="/", steps=steps, mode="swd")


def keil_changes(editor):
    from openpyxl.utils import get_column_letter
    changes = []
    for sheet_name in ("FLOW", "FREQ"):
        sheet = editor.by_name[sheet_name]
        columns = {c["label"]: i for i, c in enumerate(sheet["columns"])}
        for row_number, row in enumerate(sheet["rows"][1:], 2):
            field = "FV/FI" if sheet_name == "FLOW" else "source"
            value = row[columns[field]]["value"]
            if (sheet_name == "FLOW" and str(value).upper() != "FREQ") or not value:
                continue
            fields = {"mode":"keil", "step":"H-L-7-X-99"} if sheet_name == "FLOW" else {
                "step":"RP-22" if str(row[columns["step"]]["value"]).upper() == "RP" else "11-W1"}
            for field, value in fields.items():
                cell = row[columns[field]]
                changes.append({"sheet":sheet_name, "cell":f"{get_column_letter(columns[field] + 1)}{row_number}", "old":cell["value"], "value":value})
    return changes


def native_renders(workbook, compilation, cp="CP3"):
    from program_gen.platform_program import PlatformProgramBuilder, ProgramAssemblyInput, WorkspacePatternProducer
    from program_gen.platform_program.facts import compile_platform_program_facts
    from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
    from program_gen.render_plan import TargetKey
    from program_gen.typed_kind_registry import TypedKindContext
    from tests.workspace_paths import WORKSPACE_ROOT
    plans = tuple(p for p in compilation.plan.catalogs.freq_test_plans.values() if p.cp == cp)
    for platform in ("chroma", "s100"):
        target = TargetKey(platform, cp, "lab", f"FREQ_KEIL_{platform}")
        facts = compile_platform_program_facts(workbook, target)
        producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
        assembly = NATIVE_TYPED_KIND_REGISTRY.compile("FREQ_TEST", plans,
            TypedKindContext(compilation, target, facts, producer))
        yield platform, PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target, facts, compilation.for_cp(cp).canonical_schedule, assembly.contributions, assembly.bodies))


class FreqKeilIntegrationTests(unittest.TestCase):
    def test_wizard_creates_keil_row_and_both_native_platforms_close(self):
        import tempfile
        from pathlib import Path
        from gui.server import Session
        with tempfile.TemporaryDirectory() as folder:
            session = Session(output=Path(folder))
            editor = session.editor
            sheet = editor.by_name["FLOW"]
            values = {c["label"]:str(cell["value"] or "")
                for c, cell in zip(sheet["columns"], sheet["rows"][193]) if c["label"]}
            values.update({"CP NO":"CP1", "mode":"keil", "step":"H-L-7-X-99"})
            result = session.new_flow_item({"action":"prepare", "before":3,
                "baseSha256":editor.sha256, "changes":[c for c in keil_changes(editor) if c["sheet"] == "FREQ"], "values":values})
            self.assertTrue(result["ready"], result.get("issues"))
            draft = result["draft"]
            raw = editor.apply(editor.sha256, draft["changes"], draft["appendRows"], draft["flowOrder"],
                draft["trimStorageMappings"], draft["verifyStorageMappings"], draft["patternEdits"])
            workbook, compiled = session.compile(raw)
            compiled.require_success()
            plans = tuple(p for p in compiled.plan.catalogs.freq_test_plans.values() if p.cp == "CP1")
            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].protocol, "keil")
            self.assertEqual(plans[0].exit_actions[0].value, 99)
            swd_plans = tuple(p for p in compiled.plan.catalogs.freq_test_plans.values() if p.cp == "CP3")
            self.assertTrue(all(p.protocol == "swd" and all(not c.actions for c in p.cases) for p in swd_plans))
            for platform, rendered in native_renders(workbook, compiled, cp="CP1"):
                with self.subTest(platform=platform):
                    self.assertFalse(any(b"STUB: no real FREQ" in a.content for a in rendered.artifacts))
                    self.assertFalse(any("SWD_FREQ" in a.relative_path for a in rendered.artifacts))
                    self.assertTrue(any(a.relative_path.endswith(".pat" if platform == "chroma" else ".sd") for a in rendered.artifacts))
            editor.ensure_source_current()
