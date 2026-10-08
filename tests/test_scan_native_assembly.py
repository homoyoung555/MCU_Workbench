from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from program_gen.core.scan_test import (
    ScanArtifact,
    ScanArtifactBinding,
    ScanArtifactProducer,
    ScanBindingSet,
    compile_scan_test_plans,
)
from program_gen.compiler import _is_external_scan_or_mbist_row
from program_gen.flow_kinds import compile_flow_rows
from program_gen.platform_program.builder import _unique_requirements
from program_gen.render_plan import ResourceRequirement, TargetKey
from program_gen.typed_kind_registry import TypedKindContext


class ScanNativeAssemblyTests(unittest.TestCase):
    def test_external_scan_and_mbist_rows_are_not_common_dac_dependencies(self):
        self.assertTrue(_is_external_scan_or_mbist_row({"type": "verify", "mode": "scan"}))
        self.assertTrue(_is_external_scan_or_mbist_row({"type": "verify", "mode": "mbist"}))
        self.assertFalse(_is_external_scan_or_mbist_row({"type": "trim", "mode": "fbist"}))

    def test_compiles_a_scan_plan_and_resolves_only_an_explicit_platform_binding(self):
        flow = pd.DataFrame([{
            "CP NO": "CP1", "item": "AC_SCAN_Test", "type": "verify",
            "mode": "scan", "FV/FI": "/", "Vcc": "VCC4",
        }])
        operation, = compile_flow_rows(
            flow, workbook_identity="scan-test", source_sha256="scan-test"
        )
        plan, = compile_scan_test_plans((operation,), flow).values()
        bindings = ScanBindingSet((ScanArtifactBinding(
            cp="CP1", item="AC_SCAN_Test", typed_kind="VERIFY_SCAN",
            configuration_fingerprint="FINGERPRINT",
            artifacts=(
                ScanArtifact("chroma", "pattern", "ac_scan", b"PAT"),
                ScanArtifact("chroma", "timing", "ac_scan", b"TIME TS8"),
                ScanArtifact("chroma", "code", "ac_scan", b"ac_scan(){}"),
            ),
        ),))

        binding = bindings.require(plan, TargetKey("chroma", "CP1", "lab", "SCAN"))

        self.assertEqual(plan.typed_kind, "VERIFY_SCAN")
        self.assertEqual(plan.power_profile, "VCC4")
        self.assertEqual(binding.artifact("chroma", "pattern", "ac_scan").content, b"PAT")
        with self.assertRaisesRegex(ValueError, "SCAN.BINDING.MISSING"):
            bindings.require(plan, TargetKey("s100", "CP1", "lab", "SCAN"))

    def test_native_assembly_consumes_bound_code_timing_and_pattern_for_both_platforms(self):
        from program_gen.scan_test_assembly import compile_scan_test_assembly

        plan = next(iter(compile_scan_test_plans(*_scan_input()).values()))
        binding = ScanArtifactBinding(
            "CP1", "AC_SCAN_Test", "VERIFY_SCAN", "FINGERPRINT", (
                ScanArtifact("chroma", "pattern", "ac_scan", b"PAT"),
                ScanArtifact("chroma", "timing", "ac_scan", b"  TIME fsclk_scan8 = 100nS;"),
                ScanArtifact("chroma", "code", "ac_scan", b"ac_scan()\n{\n  JUDGE_PAT(ac_scan,__ac_scan);\n}\n"),
                ScanArtifact("s100", "pattern", "ac_scan", b"SD"),
                ScanArtifact("s100", "timing", "ac_scan", b"@@AC_SET_1\r\n@@END_AC_SET_1\r\n"),
                ScanArtifact("s100", "code", "ac_scan", b"\tRUN_PATTERN(ac_scan:START,ac_scan:END,2,ac_scan_ts);\r\n"),
            ),
        )
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP1", "lab", "SCAN")
                schedule = SimpleNamespace(
                    definitions=(SimpleNamespace(
                        cp="CP1", item="AC_SCAN_Test", source_rows=(2,),
                        identity="DEF", render_name="AcScan",
                    ),),
                    entries=(SimpleNamespace(
                        identity="SCH", definition_id="DEF", enabled=True,
                        bin_binding=SimpleNamespace(hardware_bin=61),
                    ),),
                )
                compilation = SimpleNamespace(
                    require_success=lambda: compilation,
                    for_cp=lambda _cp: SimpleNamespace(canonical_schedule=schedule),
                )
                assembly = compile_scan_test_assembly(
                    (plan,),
                    TypedKindContext(compilation, target, SimpleNamespace(), None, ScanBindingSet((binding,))),
                )
                self.assertEqual(len(assembly.contributions), 1)
                self.assertIn(b"ac_scan", assembly.bodies[0].fragment.content)
                if platform == "chroma":
                    self.assertIn(b"TIME fsclk_scan8", assembly.bodies[0].fragment.content)
                    self.assertIn(b"JUDGE_PAT", assembly.bodies[0].fragment.content)
                    self.assertIn(b"{\r\n", assembly.bodies[0].fragment.content)
                    self.assertIn(b"JUDGE_PAT(reset_pattern,__reset_pattern)", assembly.bodies[0].fragment.content)
                    self.assertEqual(len(assembly.contributions[0].resource_requires), 2)
                else:
                    self.assertIn(b"RUN_PATTERN", assembly.bodies[0].fragment.content)
                    self.assertIn(b"WAIT(3MS)", assembly.bodies[0].fragment.content)
                    self.assertEqual(len(assembly.contributions[0].timing_fragments), 1)
                    self.assertEqual(len(assembly.contributions[0].resource_requires), 1)

    def test_s100_timing_and_pattern_are_renumbered_together(self):
        binding = ScanArtifactBinding("CP1", "AC_SCAN_Test", "VERIFY_SCAN", "FINGERPRINT", (
            ScanArtifact("s100", "pattern", "ac_scan", b"HEAD[PIN_NAME]:\nPA0;\nEND_HEAD;\nTIMING_SET G2_1;\nTIMING_SET G2_2;"),
            ScanArtifact("s100", "timing", "ac_scan", b"@@AC_SET_1\n@@END_AC_SET_1\n@@AC_SET_2\n@@END_AC_SET_2\n"),
            ScanArtifact("s100", "code", "ac_scan", b"\tRUN_PATTERN(ac_scan:START,ac_scan:END,2,ac_scan_ts);\n"),
        ))
        later = ScanArtifactBinding("CP1", "DC_SCAN_Test", "VERIFY_SCAN", "FINGERPRINT", (
            ScanArtifact("s100", "pattern", "dc_scan", b"HEAD[PIN_NAME]:\nPA0;\nEND_HEAD;\nTIMING_SET G2_1;"),
            ScanArtifact("s100", "timing", "dc_scan", b"@@AC_SET_1\n@@END_AC_SET_1\n"),
            ScanArtifact("s100", "code", "dc_scan", b"\tRUN_PATTERN(dc_scan:START,dc_scan:END,2,dc_scan_ts);\n"),
        ))
        producer = ScanArtifactProducer(ScanBindingSet((binding, later)), _Fallback())
        requirement = SimpleNamespace(
            logical_identity="scan:CP1:AC_SCAN_Test:VERIFY_SCAN:s100:ac_scan",
            relative_path="ac_scan.sd", spec_identity="spec", purpose="SCAN converted Pattern",
        )
        fragment = SimpleNamespace(
            logical_identity=requirement.logical_identity, relative_path="ac.scan.timing",
            content=b"@@AC_SET_1\n@@END_AC_SET_1\n@@AC_SET_2\n@@END_AC_SET_2\n", spec_identity="spec", source_identity="source", purpose="SCAN timing fragment",
        )
        later_requirement = SimpleNamespace(
            logical_identity="scan:CP1:DC_SCAN_Test:VERIFY_SCAN:s100:dc_scan",
            relative_path="dc_scan.sd", spec_identity="spec", purpose="SCAN converted Pattern",
        )
        later_fragment = SimpleNamespace(
            logical_identity=later_requirement.logical_identity, relative_path="dc.scan.timing",
            content=b"@@AC_SET_1\n@@END_AC_SET_1\n", spec_identity="spec", source_identity="source", purpose="SCAN timing fragment",
        )

        indexed, timing = producer.prepare_s100_timing((fragment, later_fragment))
        resource = indexed.produce(requirement)
        later_resource = indexed.produce(later_requirement)

        self.assertIn(b"G2_1", resource.content)
        self.assertIn(b"G2_2", resource.content)
        self.assertIn(b"@@AC_SET_1", timing[0].content)
        self.assertIn(b"@@AC_SET_2", timing[0].content)
        self.assertIn(b"G2_3", later_resource.content)
        self.assertIn(b"@@AC_SET_3", timing[1].content)

    def test_target_boundary_rejects_a_full_pin_pattern_with_unknown_pin(self):
        binding = ScanArtifactBinding("CP1", "AC_SCAN_Test", "VERIFY_SCAN", "FINGERPRINT", (
            ScanArtifact("chroma", "pattern", "ac_scan", b"HEADER\n\nPA0, PX9;\n\n"),
            ScanArtifact("chroma", "timing", "ac_scan", b"TIME TS8 = 100nS;"),
            ScanArtifact("chroma", "code", "ac_scan", b"ac_scan(){}"),
        ))
        facts = SimpleNamespace(
            platform="chroma", cp="CP1",
            pins=(SimpleNamespace(name="PA0"),),
        )

        with self.assertRaisesRegex(ValueError, "SCAN.PIN.UNDECLARED"):
            ScanArtifactProducer(ScanBindingSet((binding,)), _Fallback()).for_target(facts)

    def test_s100_timing_sets_read_bound_scan_not_workspace_seed(self):
        binding = ScanArtifactBinding("CP1", "AC_SCAN_Test", "VERIFY_SCAN", "FINGERPRINT", (
            ScanArtifact("s100", "pattern", "ac_scan", b"TIMING_SET G2_7;"),
            ScanArtifact("s100", "timing", "ac_scan", b"@@AC_SET_7\n@@END_AC_SET_7\n"),
            ScanArtifact("s100", "code", "ac_scan", b"RUN_PATTERN(ac_scan:START,ac_scan:END,2,ac_scan_ts);"),
        ))
        fallback = _TimingFallback()
        requirement = SimpleNamespace(
            logical_identity="scan:CP1:AC_SCAN_Test:VERIFY_SCAN:s100:ac_scan",
            relative_path="ac_scan.sd", spec_identity="spec", purpose="SCAN converted Pattern",
        )
        seed = SimpleNamespace(logical_identity="pattern:seed", relative_path="seed.sd")

        names = ScanArtifactProducer(ScanBindingSet((binding,)), fallback).timing_sets((requirement, seed))

        self.assertEqual(names, ("TS_5MHZ",))
        self.assertEqual(fallback.requirements, (seed,))

    def test_same_frozen_scan_artifact_is_shared_once_per_target(self):
        first = ResourceRequirement(
            "scan:CP1:AC_SCAN_Test:VERIFY_SCAN:s100:shared_scan", "shared_scan.sd",
            "scan-binding/1:FINGERPRINT:s100:shared_scan", "SCAN converted Pattern",
        )
        second = ResourceRequirement(
            "scan:CP1:DC_SCAN_Test:VERIFY_SCAN:s100:shared_scan", "shared_scan.sd",
            "scan-binding/1:FINGERPRINT:s100:shared_scan", "SCAN converted Pattern",
        )
        first_fragment = SimpleNamespace(
            logical_identity=first.logical_identity, relative_path="shared_scan.scan.timing",
            content=b"@@AC_SET_1\n@@END_AC_SET_1\n", spec_identity=first.spec_identity,
            source_identity="scan", purpose="SCAN timing fragment",
        )
        second_fragment = SimpleNamespace(
            logical_identity=second.logical_identity, relative_path="shared_scan.scan.timing",
            content=b"@@AC_SET_1\n@@END_AC_SET_1\n", spec_identity=second.spec_identity,
            source_identity="scan", purpose="SCAN timing fragment",
        )
        shared = tuple(_unique_requirements((
            SimpleNamespace(resource_requires=(first,)),
            SimpleNamespace(resource_requires=(second,)),
        )))
        bindings = ScanBindingSet((
            _s100_binding("AC_SCAN_Test"), _s100_binding("DC_SCAN_Test"),
        ))
        producer = ScanArtifactProducer(bindings, _Fallback())

        indexed, timing = producer.prepare_s100_timing((first_fragment, second_fragment))

        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0].relative_path, "shared_scan.sd")
        self.assertEqual(len(timing), 1)
        self.assertEqual(indexed.produce(first).content, indexed.produce(second).content)

    def test_s100_timing_renumbering_is_single_pass_and_deduplicates_original_fragment(self):
        lead = ScanArtifactBinding("CP1", "Lead", "VERIFY_SCAN", "FINGERPRINT", (
            ScanArtifact("s100", "pattern", "lead", b"TIMING_SET G2_1;"),
            ScanArtifact("s100", "timing", "lead", b"@@AC_SET_1\n@@END_AC_SET_1\n"),
            ScanArtifact("s100", "code", "lead", b"RUN_PATTERN(lead:START,lead:END,2,lead_ts);"),
        ))
        shifted = ScanArtifactBinding("CP1", "Shifted", "VERIFY_SCAN", "FINGERPRINT", (
            ScanArtifact("s100", "pattern", "shifted", b"TIMING_SET G2_1; TIMING_SET G2_2;"),
            ScanArtifact("s100", "timing", "shifted", b"@@AC_SET_1\n@@END_AC_SET_1\n@@AC_SET_2\n@@END_AC_SET_2\n"),
            ScanArtifact("s100", "code", "shifted", b"RUN_PATTERN(shifted:START,shifted:END,2,shifted_ts);"),
        ))
        producer = ScanArtifactProducer(ScanBindingSet((lead, shifted)), _Fallback())
        lead_requirement = _requirement("Lead", "lead")
        shifted_requirement = _requirement("Shifted", "shifted")
        source = b"@@AC_SET_1\n@@END_AC_SET_1\n@@AC_SET_2\n@@END_AC_SET_2\n"
        fragments = (
            _fragment(lead_requirement, b"@@AC_SET_1\n@@END_AC_SET_1\n"),
            _fragment(shifted_requirement, source),
            SimpleNamespace(
                logical_identity="scan:CP1:Duplicate:VERIFY_SCAN:s100:shifted",
                relative_path="shifted.scan.timing", content=source,
                spec_identity=shifted_requirement.spec_identity, source_identity="scan",
                purpose="SCAN timing fragment",
            ),
        )

        indexed, timing = producer.prepare_s100_timing(fragments)

        self.assertEqual(len(timing), 2)
        self.assertIn(b"@@AC_SET_2", timing[1].content)
        self.assertIn(b"@@AC_SET_3", timing[1].content)
        self.assertNotIn(b"@@AC_SET_1", timing[1].content)
        self.assertIn(b"G2_2", indexed.produce(shifted_requirement).content)
        self.assertIn(b"G2_3", indexed.produce(shifted_requirement).content)

    def test_target_boundary_rejects_same_pattern_name_with_different_frozen_bytes(self):
        def binding(item, pattern):
            return ScanArtifactBinding("CP1", item, "VERIFY_SCAN", "FINGERPRINT", (
                ScanArtifact("chroma", "pattern", "shared_scan", pattern),
                ScanArtifact("chroma", "timing", "shared_scan", b"TIME TS8 = 100nS;"),
                ScanArtifact("chroma", "code", "shared_scan", b"shared_scan(){}"),
            ))
        facts = SimpleNamespace(platform="chroma", cp="CP1", pins=(SimpleNamespace(name="PA0"),))
        bindings = ScanBindingSet((
            binding("AC_SCAN_Test", b"HEADER\n\nPA0;\n\n"),
            binding("DC_SCAN_Test", b"HEADER\n\nPA0;\n\n// different"),
        ))

        with self.assertRaisesRegex(ValueError, "SCAN.BINDING.PATTERN_CONFLICT"):
            ScanArtifactProducer(bindings, _Fallback()).for_target(facts)


def _scan_input():
    flow = pd.DataFrame([{
        "CP NO": "CP1", "item": "AC_SCAN_Test", "type": "verify",
        "mode": "scan", "FV/FI": "/", "Vcc": "VCC4",
    }])
    operations = compile_flow_rows(
        flow, workbook_identity="scan-test", source_sha256="scan-test"
    )
    return operations, flow


def _s100_binding(item):
    return ScanArtifactBinding("CP1", item, "VERIFY_SCAN", "FINGERPRINT", (
        ScanArtifact("s100", "pattern", "shared_scan", b"TIMING_SET G2_1;"),
        ScanArtifact("s100", "timing", "shared_scan", b"@@AC_SET_1\n@@END_AC_SET_1\n"),
        ScanArtifact("s100", "code", "shared_scan", b"RUN_PATTERN(shared_scan:START,shared_scan:END,2,shared_scan_ts);"),
    ))


def _requirement(item, logical_name):
    return SimpleNamespace(
        logical_identity=f"scan:CP1:{item}:VERIFY_SCAN:s100:{logical_name}",
        relative_path=f"{logical_name}.sd", spec_identity="scan-binding/1:FINGERPRINT:s100",
        purpose="SCAN converted Pattern",
    )


def _fragment(requirement, content):
    return SimpleNamespace(
        logical_identity=requirement.logical_identity,
        relative_path=requirement.relative_path.removesuffix(".sd") + ".scan.timing",
        content=content, spec_identity=requirement.spec_identity,
        source_identity="scan", purpose="SCAN timing fragment",
    )


class _Fallback:
    def produce(self, requirement):
        raise AssertionError(requirement)

    def timing_sets(self, requirements):
        return ()


class _TimingFallback(_Fallback):
    def __init__(self):
        self.requirements = ()

    def timing_sets(self, requirements):
        self.requirements = tuple(requirements)
        return ("TS_5MHZ",)


if __name__ == "__main__":
    unittest.main()
