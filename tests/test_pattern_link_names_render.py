import unittest
from pathlib import Path
from pathlib import PurePosixPath
from tempfile import TemporaryDirectory

from program_gen.compiler import ProductCompiler
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platform_program.native_target import _plans_for_kind
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class PatternLinkNameRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.catalogs = cls.compilation.plan.catalogs

    def test_adc_projection_uses_platform_link_name_in_body_and_requirement(self):
        plan = next(iter(self.catalogs.adc_test_plans.values()))
        phase = next(item for item in plan.phases if item.kind.value == 'SWD_CAPTURE')
        records = [{
            'cp': plan.cp, 'item': plan.item, 'phase': phase.adc_id,
            'role': 'config', 'platform': 'chroma',
            'original': 'PT104_SWD_' + phase.adc_id, 'pattern': 'source_adc_config',
        }, {
            'cp': plan.cp, 'item': plan.item, 'phase': phase.adc_id,
            'role': 'capture', 'platform': 'chroma',
            'original': 'PT104_' + phase.adc_id + '_capture', 'pattern': 'source_adc_capture',
        }]
        projected, = _plans_for_kind(self.catalogs, 'ADC_TEST', 'chroma', plan.cp, records)
        from program_gen.platforms.chroma.adc_test_renderer import render_adc_test
        facts = compile_platform_program_facts(self.workbook, type('Target', (), {'platform': 'chroma', 'cp': plan.cp, 'variant': 'production'})())
        rendered = render_adc_test(projected, 'ADC_Test', 1, facts)
        self.assertIn('source_adc_config', rendered.content)
        self.assertIn('source_adc_capture', rendered.content)
        required = {PurePosixPath(item.relative_path).stem for item in rendered.resource_requires}
        self.assertIn('source_adc_config', required)
        self.assertIn('source_adc_capture', required)

    def test_dc_projection_is_platform_scoped_and_default_is_unchanged(self):
        plan = next(iter(self.catalogs.dc_parametric_plans.values()))
        original = plan.config_patterns[0]
        record = {'cp': plan.cp, 'item': plan.item, 'phase': 'DC', 'role': 'config',
                  'platform': 's100', 'original': original, 'pattern': 'source_dc_config'}
        chroma = next(item for item in _plans_for_kind(self.catalogs, 'DC_PARAMETRIC_TEST', 'chroma', plan.cp, [record]) if item.row == plan.row)
        s100 = next(item for item in _plans_for_kind(self.catalogs, 'DC_PARAMETRIC_TEST', 's100', plan.cp, [record]) if item.row == plan.row)
        self.assertEqual(chroma.config_patterns, plan.config_patterns)
        self.assertIn('source_dc_config', s100.config_patterns)
        from program_gen.platforms.s100.dc_parametric_renderer import render_dc_parametric
        facts = compile_platform_program_facts(self.workbook, type('Target', (), {'platform': 's100', 'cp': plan.cp, 'variant': 'production'})())
        rendered = render_dc_parametric(s100, 'DC_Test', 1, facts)
        self.assertIn('source_dc_config', rendered.content)
        self.assertIn('source_dc_config', {PurePosixPath(item.relative_path).stem for item in rendered.resource_requires})

    def test_reader_carries_internal_json_records_into_compilation(self):
        plan = next(iter(self.catalogs.dc_parametric_plans.values()))
        record = {'cp': plan.cp, 'item': plan.item, 'phase': 'DC', 'role': 'config',
                  'platform': 'shared', 'original': plan.config_patterns[0], 'pattern': 'source_dc_shared'}
        from program_gen.core.pattern_links import patch_pattern_links
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'linked.xlsx'
            path.write_bytes(patch_pattern_links(FORMAL_MASTER.read_bytes(), [record]))
            workbook = WorkbookReader().read(path)
        self.assertEqual(workbook.pattern_links, (record,))
        compilation = ProductCompiler().compile(workbook).require_success()
        self.assertEqual(compilation.pattern_links, (record,))

    def test_dac_output_projection_changes_both_platform_body_and_requirement(self):
        plan = next(item for item in self.catalogs.dac_test_plans.values() if item.protocol == 'swd')
        case = plan.cases[0]
        records = []
        for platform, pattern in (('chroma', 'source_dac_chroma'), ('s100', 'source_dac_s100')):
            facts = compile_platform_program_facts(self.workbook, type('Target', (), {'platform': platform, 'cp': plan.cp, 'variant': 'production'})())
            pin = facts.pin_groups.dac_out[0].name
            records.append({'cp': plan.cp, 'item': plan.item, 'phase': 'DAC', 'role': 'output',
                            'platform': platform, 'original': f'{plan.product}_DAC_{case.mode}_{pin}_Test',
                            'pattern': pattern})
        for platform, expected in (('chroma', 'source_dac_chroma'), ('s100', 'source_dac_s100')):
            projected = next(item for item in _plans_for_kind(self.catalogs, 'DAC_TEST', platform, plan.cp, records) if item.row == plan.row)
            facts = compile_platform_program_facts(self.workbook, type('Target', (), {'platform': platform, 'cp': plan.cp, 'variant': 'production'})())
            renderer = (__import__(f'program_gen.platforms.{platform}.dac_test_renderer', fromlist=['render_dac_test']).render_dac_test)
            rendered = renderer(projected, 'DAC_Test', 1, facts)
            self.assertIn(expected, rendered.content)
            self.assertIn(expected, {PurePosixPath(item.relative_path).stem for item in rendered.resource_requires})


if __name__ == '__main__':
    unittest.main()
