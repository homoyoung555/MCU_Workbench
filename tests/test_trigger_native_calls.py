"""Cross-kind trigger resource closure, including sheet-driven KEIL sweeps."""

from dataclasses import replace
from importlib import import_module
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.run_sequence import parse_run_sequence_step
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.render_plan import ProgramAssembler, ProgramContribution, RenderPlanError, TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class TriggerNativeCallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.catalogs = ProductCompiler().compile(cls.workbook).require_success().plan.catalogs

    def test_opa_and_dac_keil_sweeps_call_shared_labels_in_order(self):
        actions = parse_run_sequence_step('PA13:HL-PA0:1-2-3', 'PA0')
        for platform in ('chroma', 's100'):
            facts = compile_platform_program_facts(self.workbook, TargetKey(platform, 'CP3', 'lab', 'TriggerCheck'))
            for kind in ('opa', 'dac'):
                with self.subTest(platform=platform, kind=kind):
                    source = next(iter(getattr(self.catalogs, kind + '_test_plans').values()))
                    pattern_field = 'config_pattern' if kind == 'opa' else 'code_pattern'
                    case = replace(source.cases[0], actions=actions, **{pattern_field: None})
                    plan = replace(source, protocol='keil', init_pattern=None, cases=(case,), entry_actions=parse_run_sequence_step('PA0:222', 'PA0'), exit_actions=())
                    renderer = getattr(import_module(f'program_gen.platforms.{platform}.{kind}_test_renderer'), f'render_{kind}_test')
                    rendered = renderer(plan, 'TriggerCheck', 12, facts)
                    names = [r.relative_path for r in rendered.resources]
                    extension = '.pat' if platform == 'chroma' else '.sd'
                    self.assertEqual(len(set(names)), 2)
                    self.assertTrue(any(name.endswith('PA13_Trigger_HL_5mS' + extension) for name in names))
                    send = next(r for r in rendered.resources if r.relative_path.endswith('PA0_Trigger_Send' + extension))
                    positions = []
                    for value in (1, 2, 3):
                        label = f'S{value:02X}'
                        self.assertIn((label + '_ST:').encode(), send.content)
                        self.assertIn((label + '_SP:').encode(), send.content)
                        positions.append(rendered.content.index('PA0_Trigger_Send:' + label + '_ST'))
                    self.assertEqual(positions, sorted(positions))
                    self.assertLess(rendered.content.index('PA0_Trigger_Send:SDE_ST'), positions[0])

    def test_generic_name_with_different_physical_pins_cannot_merge(self):
        for platform in ('chroma', 's100'):
            module = import_module(f'program_gen.platforms.{platform}.firmware_test_renderer')
            first = module.generate_send_code_resource(parse_run_sequence_step('1', 'PA0')[0])
            second = module.generate_send_code_resource(parse_run_sequence_step('2', 'PA13')[0])
            target = TargetKey(platform, 'CP3', 'lab', 'TriggerCheck')
            contributions = tuple(ProgramContribution(identity=f'owner{i}', target=target, resources=(resource,)) for i, resource in enumerate((first, second)))
            with self.assertRaises(RenderPlanError) as raised:
                ProgramAssembler._close_resources(contributions)
            self.assertEqual(raised.exception.code, 'RP.RESOURCE.CONFLICT')
