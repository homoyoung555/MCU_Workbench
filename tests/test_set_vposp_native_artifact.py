"""Complete dual-platform artifact probe for the shared SETVPOSP Module."""

from __future__ import annotations

from dataclasses import replace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.fbist_pattern_plan import compile_fbist_label_catalog
from program_gen.core.logical_item import logical_item_key
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.set_vposp import (
    PumpDacPlan,
    SetVpospSnapshot,
    compile_set_vposp_plan,
)
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.platforms.chroma.fbist_pattern_generator import (
    generate_fbist_patterns as generate_chroma_patterns,
)
from program_gen.platforms.s100.fbist_pattern_generator import (
    generate_fbist_patterns as generate_s100_patterns,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.standard_verify_assembly import compile_standard_verify_assembly
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


def build_set_vposp_probe(platform: str):
    workbook = WorkbookReader().read(FORMAL_MASTER)
    compilation = ProductCompiler().compile(workbook).require_success()
    verify = next(
        plan
        for plan in compilation.plan.catalogs.standard_verify_plans.values()
        if plan.cp == "CP1" and plan.item == "Vrefint"
    )
    fbist = compilation.plan.catalogs.fbist_pattern_plan
    labels = compile_fbist_label_catalog(fbist)
    bindings = {}
    for binding in compilation.plan.catalogs.trim_data.bindings:
        if binding.pump:
            bindings.setdefault(logical_item_key(binding.item), binding)
    pumps = tuple(
        PumpDacPlan(item, bindings[logical_item_key(item)].dac_final_symbol)
        for item in fbist.pump_items
    )
    run = RunPatternPlan(
        PatternResourceRef(
            fbist.pump_aggregate.pattern_name,
            f"pattern:{fbist.pump_aggregate.pattern_name}",
            ("START", "END"),
        ),
        PatternSpan.full(),
        "TS_5MHZ",
    )
    prepare = compile_set_vposp_plan(
        pumps,
        labels,
        SetVpospSnapshot(),
        swd_pin=fbist.swd_pin,
        run_pattern=run,
    )
    clean = compile_set_vposp_plan(
        pumps,
        labels,
        prepare.snapshot,
        swd_pin=fbist.swd_pin,
        run_pattern=run,
    )
    prepare_emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(
        "SETVPOSP", prepare.plan, platform
    )
    run_emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(
        "SETVPOSP", clean.plan, platform
    )

    target = TargetKey(
        platform,
        "CP1",
        "lab",
        f"Standard_Verify_SETVPOSP_CP1_{platform}",
    )
    facts = compile_platform_program_facts(workbook, target)
    generated = (
        generate_chroma_patterns(fbist)
        if platform == "chroma"
        else generate_s100_patterns(fbist)
    )
    producer = GeneratedPatternProducer(
        generated,
        fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform),
    )
    assembly = compile_standard_verify_assembly(
        (verify,), TypedKindContext(compilation, target, facts, producer)
    )
    body = assembly.bodies[0]
    text = body.fragment.content.decode("gbk")
    newline = "\r\n" if "\r\n" in text else "\n"
    marker = (
        "  JUDGE_PAT(enter_vrefint_verify,__enter_vrefint_verify);"
        if platform == "chroma"
        else "\tRUN_PATTERN(enter_vrefint_verify:START,"
        "enter_vrefint_verify:END,1,TS_5MHZ);"
    )
    indent = "  " if platform == "chroma" else "\t"
    inserted = newline.join((
        marker,
        f"{indent}// SETVPOSP initial/dirty: prepare only",
        *prepare_emission.statements,
        f"{indent}// SETVPOSP next clean call: RUN only",
        *run_emission.statements,
    ))
    if text.count(marker) != 1:
        raise AssertionError(f"SETVPOSP probe marker missing for {platform}")
    body = replace(
        body,
        fragment=replace(
            body.fragment,
            content=text.replace(marker, inserted, 1).encode("gbk"),
        ),
    )
    contribution = replace(
        assembly.contributions[0],
        resource_requires=(
            *assembly.contributions[0].resource_requires,
            *prepare_emission.resource_requires,
        ),
    )
    render = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
        target=target,
        platform_facts=facts,
        canonical_schedule=compilation.for_cp("CP1").canonical_schedule,
        contributions=(contribution,),
        bodies=(body,),
        runtime_declarations=compilation.for_cp("CP1").runtime_state.declarations,
    ))
    return render, len(labels)


class SetVpospNativeArtifactTests(unittest.TestCase):
    def test_complete_dual_platform_probe_uses_generated_catalog_pattern(self):
        for platform, extension, write_token, run_token in (
            (
                "chroma",
                "pln",
                "WRITE_PAT_MEM(SOCKET,PA13,set_all_final_vposp:",
                "JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp);",
            ),
            (
                "s100",
                "prg",
                "LOGIC_WRITE_PATTERN_MEMORY(set_all_final_vposp:",
                "RUN_PATTERN(set_all_final_vposp:START,",
            ),
        ):
            with self.subTest(platform=platform):
                render, label_count = build_set_vposp_probe(platform)
                source = render.artifact(
                    f"Standard_Verify_SETVPOSP_CP1_{platform}.{extension}"
                ).content.decode("gbk")
                pattern_path = (
                    "pat/set_all_final_vposp.pat"
                    if platform == "chroma"
                    else "set_all_final_vposp.sd"
                )

                self.assertEqual(source.count(write_token), label_count)
                self.assertEqual(source.count(run_token), 1)
                self.assertIn(
                    "SETVPOSP initial/dirty: prepare only", source
                )
                self.assertIn("SETVPOSP next clean call: RUN only", source)
                self.assertTrue(render.artifact(pattern_path).content)
                if platform == "s100":
                    self.assertIn("@@MACRO write_pat_temp_arry(int* a)", source)


if __name__ == "__main__":
    unittest.main()
