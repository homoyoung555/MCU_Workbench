from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import unittest

from gui.generation import available_targets, generate_review
from program_gen.compiler import ProductCompiler
from program_gen.render_plan import ArtifactSet
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class GuiGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_catalog_exposes_real_cp3_chroma_lab_target(self):
        targets = available_targets(self.workbook, self.compilation)

        self.assertTrue(any(
            target["platform"] == "chroma"
            and target["cp"] == "CP3"
            and target["variant"] == "lab"
            for target in targets
        ))
        self.assertTrue(all(
            set(("id", "platform", "cp", "variant", "name")) <= set(target)
            for target in targets
        ))

    def test_resource_outputs_are_independent_and_preserve_real_manifest(self):
        import hashlib
        import json
        from gui.generation import available_pin_targets
        from program_gen.pin_dec import compile_pin_map_generation_plan, generate_pin_dec, generate_s100_prj_resources
        from program_gen.platform_program.facts import compile_platform_program_facts
        from program_gen.render_plan import TargetKey
        pins=available_pin_targets(self.workbook,self.compilation)
        self.assertTrue(any(t['platform']=='s100' and t['variant']=='production' for t in pins))
        evidence=[]
        for scope,platform,variant in [('pin','chroma','lab'),('pin','s100','production'),('patterns','chroma','lab'),('patterns','s100','lab')]:
            choices=pins if scope=='pin' else available_targets(self.workbook,self.compilation)
            target=next(t for t in choices if t['platform']==platform and t['cp']=='CP3' and t['variant']==variant)
            run=WORKSPACE_ROOT/'outputs'/'gui_runs'/f'resource-test-{uuid4().hex}'
            (run/'input').mkdir(parents=True)
            with patch('gui.generation.NativeTargetRenderer',side_effect=AssertionError('full renderer must not run')):
                result=generate_review(self.workbook,self.compilation,[target['id']],run,scope=scope)
            self.assertIn(result['status'],('REVIEW_READY','REVIEW_READY_WITH_WARNINGS'),result)
            output=result['outputs'][0];root=Path(output['path'])
            manifest=json.loads((root/'.render-manifest.json').read_text(encoding='utf-8'))
            files=[a['path'] for a in manifest['artifacts']]
            self.assertTrue(files)
            for a in manifest['artifacts']:
                self.assertEqual(hashlib.sha256((root/a['path']).read_bytes()).hexdigest().upper(),a['sha256'])
            if scope=='pin':
                self.assertEqual(len(files),1)
                key=TargetKey(platform,'CP3',variant,target['name'])
                plan=compile_pin_map_generation_plan(compile_platform_program_facts(self.workbook,key))
                expected=generate_pin_dec(plan) if platform=='chroma' else generate_s100_prj_resources(plan)
                self.assertEqual((root/files[0]).read_bytes(),expected)
                if platform=='s100':self.assertIn('片段',output['note'])
            else:
                self.assertTrue(all(Path(p).suffix.lower() in {'.pat','.sd','.sr'} for p in files))
                blockers={b for a in manifest['artifacts'] for b in a.get('release_blockers',[])}
                self.assertEqual(set(output['release_blockers']),blockers)
                self.assertTrue(blockers)
            self.assertFalse(result['validation']['vendor_compiler_executed'])
            evidence.append({'scope':scope,'platform':platform,'variant':variant,'files':len(files),'path':str(root)})
        print('RESOURCE_OUTPUTS',json.dumps(evidence))

    def test_review_generation_uses_supplied_models_and_never_claims_validation(self):
        target = next(
            target for target in available_targets(self.workbook, self.compilation)
            if target["platform"] == "chroma"
            and target["cp"] == "CP3"
            and target["variant"] == "lab"
        )
        parent = WORKSPACE_ROOT / "outputs" / "gui_runs"
        parent.mkdir(parents=True, exist_ok=True)
        run_dir = parent / f"contract-{uuid4().hex}"
        run_dir.mkdir()
        (run_dir / "input").mkdir()

        def renderer_factory(workbook, _platform_roots, *, scan_bindings=None, swd_bindings=None):
            self.assertIs(workbook, self.workbook)
            self.assertIsNone(scan_bindings)
            self.assertIsNone(swd_bindings)

            def render(compilation, context):
                self.assertIs(compilation, self.compilation)
                context.staging_directory.mkdir(parents=True)
                return ArtifactSet(
                    context.target,
                    context.staging_directory,
                    (),
                    "A" * 64,
                    ("STUB: contract fixture",),
                )

            return render

        with patch("gui.generation.NativeTargetRenderer", renderer_factory):
            result = generate_review(
                self.workbook,
                self.compilation,
                [target["id"]],
                run_dir,
                validate=True,
            )

        self.assertEqual(result["status"], "REVIEW_READY_WITH_WARNINGS")
        self.assertEqual(result["validation"]["state"], "UNSUPPORTED")
        self.assertFalse(result["validation"]["vendor_compiler_executed"])
        self.assertEqual(result["outputs"][0]["id"], target["id"])
        self.assertEqual(result["outputs"][0]["release_blockers"], ["STUB: contract fixture"])

    def test_review_generation_rejects_client_chosen_paths_outside_gui_run_parent(self):
        with self.assertRaisesRegex(ValueError, "RUN_DIR_OUTSIDE_PARENT"):
            generate_review(
                self.workbook,
                self.compilation,
                ["chroma:CP3:lab:ignored"],
                WORKSPACE_ROOT / "scratch" / "not-a-gui-run",
            )


if __name__ == "__main__":
    unittest.main()
