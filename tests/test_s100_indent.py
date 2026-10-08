import unittest

from program_gen.core.s100_indent import format_s100


class S100IndentTests(unittest.TestCase):
    def test_nested_bodies_single_statements_and_condition(self):
        source = '\r\n'.join((
            '@@PLAN Test', 'if(enabled)', '{', '{', 'for(i=0;i<2;i++)',
            '// loop body', 'if(ok)', 'run();', 'else', 'fail();',
            'after();', '}', '}', 'CONDITION', 'IF_FAIL',
            'REJECT_BIN = 4;', '@@END_PLAN', '',
        ))
        expected = '\r\n'.join((
            '@@PLAN Test', '\tif(enabled)', '\t{', '\t\t{',
            '\t\t\tfor(i=0;i<2;i++)', '\t\t\t\t// loop body',
            '\t\t\t\tif(ok)', '\t\t\t\t\trun();', '\t\t\t\telse',
            '\t\t\t\t\tfail();', '\t\t\tafter();', '\t\t}', '\t}',
            '\tCONDITION', '\t\tIF_FAIL', '\t\t\tREJECT_BIN = 4;', '@@END_PLAN', '',
        ))
        self.assertEqual(format_s100(source), expected)
        self.assertEqual(format_s100(expected), expected)

    def test_switch_strings_comments_and_trailing_bytes(self):
        source = '\n'.join((
            '@@MACRO M()', 'switch(x)', '{', 'case 0:',
            'log("escaped \\\" { }");  ', '/* {', '} */', 'break;',
            'default:', 'break;', '}', '@@END_MACRO', '',
        ))
        result = format_s100(source)
        self.assertIn('\t\tcase 0:\n\t\t\tlog(', result)
        self.assertIn('\t\tdefault:\n\t\t\tbreak;', result)
        self.assertEqual([s.lstrip(' \t') for s in source.splitlines()],
                         [s.lstrip(' \t') for s in result.splitlines()])
        self.assertEqual(format_s100(result), result)
