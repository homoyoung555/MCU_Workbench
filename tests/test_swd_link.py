import unittest
from types import SimpleNamespace

from program_gen.render_plan import ResourceRequirement


class SwdLinkTests(unittest.TestCase):
    def test_frozen_link_uses_target_symbol_and_never_reads_old_file(self):
        from program_gen.core.swd_pattern import SwdPatternProducer
        class Fallback:
            def produce(self, requirement):
                raise AssertionError('linked resource must not fall back')
            def for_target(self, facts):
                return self
        record = {'cp': 'CP3', 'names': {'shared': ['PT104_SWD_VOL']},
                  'pattern': 'PT104_SWD_VOL_Test', 'identity': 'revision-1',
                  'contents': {'chroma': b'SPM_PATTERN(PT104_SWD_VOL_Test) {\n *111*;\n}\n',
                               's100': b'HEAD[PIN_NAME]:\nPA14,PA13,NRST,TRIGPIN;\nEND_HEAD;\n'}}
        producer = SwdPatternProducer([record], Fallback()).for_target(SimpleNamespace(platform='chroma', cp='CP3'))
        result = producer.produce(ResourceRequirement('pattern:PT104_SWD_VOL', 'PAT/PT104_SWD_VOL.pat', 'test'))
        self.assertIn(b'SPM_PATTERN(PT104_SWD_VOL)', result.content)
        self.assertIn('revision-1', result.source_identity)

    def test_conflicting_shared_symbol_fails(self):
        from program_gen.core.swd_pattern import SwdPatternProducer
        records = [{'cp': 'CP3', 'names': {'shared': ['same']}, 'pattern': 'p',
                    'identity': str(i), 'contents': {'s100': str(i).encode()}} for i in range(2)]
        with self.assertRaisesRegex(ValueError, '冲突'):
            SwdPatternProducer(records, None).for_target(SimpleNamespace(platform='s100', cp='CP3'))


if __name__ == '__main__':
    unittest.main()
