from tests.workspace_paths import FORMAL_MASTER
import unittest

from flow_recipe import _MODULE_ARGUMENTS, parse_recipe


class RecipeEditorTests(unittest.TestCase):
    def test_errors_locate_modules_and_reserved_names_only_warn(self):
        from gui.recipe_editor import inspect_recipe, module_manual
        raw = 'ENTER(WAIT=bad)-RUN-JUDGE(PF=MAYBE)'
        result = inspect_recipe({'text': raw})
        self.assertEqual([x['index'] for x in result['issues']], [0, 1, 2])
        self.assertTrue(all(x['message'] for x in result['issues']))
        self.assertEqual(result['text'], raw)
        self.assertEqual(result['steps'], [])
        fixed = inspect_recipe({'text': 'ENTER(WAIT=1MS)-RUN(foo)-JUDGE(PF=YES)'})
        self.assertEqual(fixed['issues'], [])
        self.assertFalse(fixed['error'])
        reserved = next(m['name'] for m in module_manual() if m['reserved'])
        warning = inspect_recipe({'text': reserved})
        self.assertFalse(warning['error'])
        self.assertEqual(warning['warnings'][0]['index'], 0)
        self.assertEqual(inspect_recipe({'text': 'ENTER)-RUN(foo)'})['issues'][0]['index'], None)

    def test_all_explicit_master_recipes_roundtrip_without_changing_tokens(self):
        import openpyxl
        from gui.recipe_editor import inspect_recipe
        path = FORMAL_MASTER
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            values = workbook['FLOW'].values
            headers = next(values)
            texts = {str(row[headers.index('Recipe')]) for row in values if row[headers.index('Recipe')]}
            self.assertTrue(texts)
            for raw in texts:
                with self.subTest(raw=raw):
                    result = inspect_recipe({'text': raw})
                    self.assertFalse(result['error'])
                    encoded = '-'.join(s['module'] + ('(' + s['arguments'] + ')' if s['arguments'] else '') for s in result['steps'])
                    self.assertEqual(parse_recipe(encoded), parse_recipe(raw))
        finally:
            workbook.close()

    def test_http_parser_requires_auth_and_does_not_touch_workbook_or_check(self):
        import json
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from gui.server import Session, make_server
        session = Session(master=None)
        server = make_server(0, session)
        before = dict(vars(session))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(token, payload):
                return urlopen(Request(server.origin + '/api/recipe', data=json.dumps(payload).encode(),
                                       headers={'Content-Type': 'application/json', 'X-GUI-Session': token}), timeout=5)
            with self.assertRaises(HTTPError) as error:
                request('wrong', {'text': 'TRIM'})
            self.assertEqual(error.exception.code, 403)
            with request(server.token, {'text': 'ENTER-TRIM-JUDGE'}) as response:
                result = json.load(response)
            self.assertEqual([s['module'] for s in result['steps']], ['ENTER', 'TRIM', 'JUDGE'])
            self.assertEqual(vars(session), before)
            self.assertIsNone(session.editor)
            self.assertIsNone(session.checked)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

    def test_roundtrip_signed_binary_assignment_and_capture_arguments(self):
        from gui.recipe_editor import inspect_recipe
        raw = 'ENTER(0010,WAIT=1MS)-DAC_ADJ(<-0.5:-1)\nCOMMIT(foo=0b0010,bar=STEP)-SRAM_CAPTURE(0x100,2x16@4)'
        result = inspect_recipe({'text': raw})
        self.assertEqual(result['error'], '')
        encoded = '-'.join(s['module'] + ('(' + s['arguments'] + ')' if s['arguments'] else '') for s in result['steps'])
        self.assertEqual(parse_recipe(encoded), parse_recipe(raw))
        self.assertEqual(result['text'], raw)
        self.assertEqual(result['steps'][0]['arguments'], '0010,WAIT=1MS')

    def test_blank_defaults_are_preview_only_and_hex_has_no_editable_recipe(self):
        from gui.recipe_editor import inspect_recipe
        result = inspect_recipe({'text': '', 'item': 'Vref0p8_ABS', 'type': 'trim', 'mode': 'fbist'})
        self.assertEqual(result['text'], '')
        self.assertEqual(result['source'], 'default')
        self.assertEqual([s['module'] for s in result['steps']], ['ENTER', 'TRIM', 'JUDGE'])
        result = inspect_recipe({'text': '', 'mode': 'hex'})
        self.assertEqual(result['source'], 'intrinsic')
        self.assertEqual(result['steps'], [])
        self.assertTrue(inspect_recipe({'text': 'RUN(foo)', 'mode': 'hex'})['error'])

    def test_invalid_input_is_retained_for_repair_and_manual_covers_parser(self):
        from gui.recipe_editor import inspect_recipe, module_manual
        bad = 'ENTER)-RUN(foo)'
        result = inspect_recipe({'text': bad})
        self.assertEqual(result['text'], bad)
        self.assertTrue(result['error'])
        self.assertEqual(result['steps'], [])
        manual = module_manual()
        self.assertEqual({m['name'] for m in manual}, set(_MODULE_ARGUMENTS))
        for module in manual:
            self.assertTrue(module['description'])
            self.assertTrue(module['parameters'])
            if module['example']:
                parse_recipe(module['example'])
        with self.assertRaises(ValueError): inspect_recipe({'text': []})


if __name__ == '__main__':
    unittest.main()
