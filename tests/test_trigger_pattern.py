import unittest

from program_gen.core.run_sequence import parse_run_sequence_step


class TriggerPatternContractTests(unittest.TestCase):
    def test_compare_labels_use_st_sp_on_both_platforms(self):
        from types import SimpleNamespace
        from program_gen.platforms.chroma import firmware_test_renderer as chroma
        from program_gen.platforms.s100 import firmware_test_renderer as s100
        judge = SimpleNamespace(pins=('PA13', 'PA14'), expected=('L', 'L'))
        for platform in (chroma, s100):
            resource = platform.generate_digital_compare_resource(judge).content.decode('ascii')
            for state in ('HH', 'HL', 'LH', 'LL'):
                self.assertIn(state + '_ST:', resource)
                self.assertIn(state + '_SP:', resource)
                self.assertNotIn('__' + state, resource)
            span = chroma.compare_pattern_span(judge.pins, judge.expected) if platform is chroma else s100.compare_pattern_span(judge)
            self.assertEqual(span, ('PA13_PA14_Compare:LL_ST', 'PA13_PA14_Compare:LL_SP'))
        resource = chroma.generate_digital_compare_resource(judge).content.decode('ascii')
        self.assertNotIn('Settled', resource)
        for state in ('HH', 'HL', 'LH', 'LL'):
            self.assertIn(
                f'{state}_ST:\n  *XX*TS1;\n'
                '  *XX*RPT 100;\n  *XX*RPT 100;\n'
                f'  *{state}*;\n  *{state}*;\n'
                f'  *{state}*RPT 100;\n  *{state}*;\n'
                f'  *XX*;\n  *XX*;\n{state}_SP:\n  *XX*;\n',
                resource,
            )

    def test_default_pin_and_inline_overrides_preserve_naming_source(self):
        default = parse_run_sequence_step('HL-1-2', 'PA0')
        self.assertEqual([action.explicit_pin for action in default], [False] * 3)
        explicit = parse_run_sequence_step('PA13:HL-PA0:1-2-3', 'PB0')
        self.assertEqual([action.pin for action in explicit], ['PA13', 'PA0', 'PA0', 'PA0'])
        self.assertTrue(all(action.explicit_pin for action in explicit))

    def test_resource_names_and_labels_follow_user_contract(self):
        from program_gen.core.trigger_pattern import trigger_pattern_name, send_label, compare_pattern_name, compare_label
        self.assertEqual(
            [trigger_pattern_name(a) for a in parse_run_sequence_step('HL-1-2', 'PA0')],
            ['Trigger_HL_5mS', 'Trigger_Send', 'Trigger_Send'],
        )
        self.assertEqual(
            [trigger_pattern_name(a) for a in parse_run_sequence_step('PA13:HL-PA0:1-2-3', 'PB0')],
            ['PA13_Trigger_HL_5mS', 'PA0_Trigger_Send', 'PA0_Trigger_Send', 'PA0_Trigger_Send'],
        )
        self.assertEqual(trigger_pattern_name(parse_run_sequence_step('PA11:HLHL-500uS', 'PA0')[0]), 'PA11_Trigger_HLHL_500uS')
        self.assertEqual(send_label(1), 'S01')
        self.assertEqual(send_label(222), 'SDE')
        self.assertEqual(compare_pattern_name(('PA13', 'PA11')), 'PA13_PA11_Compare')
        self.assertEqual(compare_label(('H', 'L')), 'HL')

    def test_new_line_restores_default_pin_scope(self):
        actions = parse_run_sequence_step('PA13:HL\n1-2', 'PA0')
        self.assertEqual([action.pin for action in actions], ['PA13', 'PA0', 'PA0'])
        self.assertEqual([action.explicit_pin for action in actions], [True, False, False])

    def test_opa_dac_template_preserves_pin_across_insertion(self):
        from program_gen.core.opa_test import _template_actions
        from program_gen.core.dac_test import _template
        for compiler in (_template_actions, _template):
            for step in ('PA13:HL-X-2', 'HL-PA13:X-2'):
                with self.subTest(compiler=compiler.__module__, step=step):
                    entry, exit_actions = compiler(step, 'PA0', 0, 'keil')
                    self.assertEqual(exit_actions[0].pin, 'PA13')
                    self.assertTrue(exit_actions[0].explicit_pin)
