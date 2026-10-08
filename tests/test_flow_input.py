import json
import unittest
import pandas as pd

from program_gen.core.flow_input import describe_flow_input


class FlowInputDescriptorTests(unittest.TestCase):
    def test_analog_sheet_fields_follow_protocol(self):
        for kind, mode, marker, recipe in (
            ('ADC_TEST','swd','ADC1','SWD_CAPTURE-ADC_JUDGE'),
            ('OPA_TEST','swd','/','OPA_TEST'), ('OPA_TEST','keil','/','OPA_TEST'),
            ('DAC_TEST','swd','/','DAC_TEST'), ('DAC_TEST','keil','/','DAC_TEST'),
            ('PVD_TEST','keil','PVD','PVD_TEST')):
            with self.subTest(kind=kind, mode=mode):
                view = describe_flow_input({'CP NO':'CP1','item':'Analog_New','type':'verify',
                    'mode':mode,'FV/FI':marker,'Recipe':recipe})
                self.assertTrue(view['supported'])
                fields = {f['name']:f for f in view['fields']}
                self.assertEqual('target' in fields, kind == 'DAC_TEST')
                self.assertEqual('step' in fields, mode == 'keil')
                self.assertEqual(view['resourceSheet'],kind.split('_')[0])
                if kind == 'ADC_TEST': self.assertEqual(view['fixedValues']['sub'],'ADC1')
        digital = describe_flow_input({'CP NO':'CP1','item':'Analog','type':'verify','mode':'keil','FV/FI':'ADC1','Recipe':'RUN_SEQUENCE-JUDGE'})
        self.assertTrue(digital['supported'])
        self.assertTrue({'Recipe','step','target','meas pin'}.issubset({f['name'] for f in digital['fields']}))
        capture = describe_flow_input({'CP NO':'CP1','item':'Analog','type':'verify','mode':'keil','FV/FI':'ADC1','Recipe':'RUN_SEQUENCE-SRAM_CAPTURE(0X3000,22x16@2)-ADC_JUDGE'})
        self.assertNotIn('target', {f['name'] for f in capture['fields']})

    def test_specialized_templates_use_protocol_fields(self):
        for kind, row in (
            ('OS', {'type': 'os', 'mode': '/', 'item': 'os_new'}),
            ('FREQ_TEST', {'type': 'verify', 'mode': 'swd', 'item': 'Clock_check_Test', 'FV/FI': 'FREQ'}),
            ('PDR_TRIM', {'type': 'trim', 'mode': 'fbist', 'item': 'Pdr_Trim'}),
            ('PDR_VERIFY', {'type': 'verify', 'mode': 'fbist', 'item': 'Pdr_Verify'}),
        ):
            result = describe_flow_input({'CP NO': 'CP1', **row})
            self.assertTrue(result['supported'], kind)
            self.assertTrue(result['specialized'])
            self.assertNotIn('target', [f['name'] for f in result['fields']])
            self.assertEqual(result['fixedValues']['target'], '/')
        pdr = describe_flow_input({'CP NO': 'CP1', 'type': 'trim', 'mode': 'fbist', 'item': 'Pdr_Trim'})
        self.assertEqual(pdr['fixedValues']['DAC bit'], '4')
        self.assertEqual(pdr['fixedValues']['Bisection'], 'yes')
        freq = describe_flow_input({'CP NO': 'CP1', 'type': 'verify', 'mode': 'keil', 'item': 'Clock', 'FV/FI': 'FREQ'})
        self.assertTrue(freq['supported'])
        self.assertIn('step', [f['name'] for f in freq['fields']])
        self.assertNotIn('step', freq['fixedValues'])

    def test_units_and_conditional_verify_limits_follow_consumers(self):
        base = {'CP NO': 'CP1', 'item': 'New', 'type': 'verify', 'mode': 'fbist', 'UNIT': 'V',
                'low_range(%)': '0.9', 'high_range(%)': '1.1'}
        fields = lambda values, **kw: {f['name']: f for f in describe_flow_input(values, **kw)['fields']}
        self.assertFalse(fields(base)['target']['required'])
        self.assertTrue(fields({**base, 'low_range(%)': '1%'})['target']['required'])
        self.assertTrue(fields({**base, 'UNIT': 'MHz'})['target']['required'])
        self.assertNotIn('GHz', fields(base)['UNIT']['choices'])
        self.assertNotIn('mV', fields({**base, 'type': 'trim'})['UNIT']['choices'])
        version = pd.DataFrame([{'CP num': 'CP1', 'vref': 1.2}])
        inherited = fields({**base, 'item': 'vref_verify'}, version_frame=version)
        self.assertFalse(inherited['low_range(%)']['required'])
        self.assertIn('VERSION:vref', inherited['low_range(%)']['help'])

    def test_complex_recipe_keeps_advanced_fields_and_invalid_identity_is_safe(self):
        base = {'CP NO': 'CP1', 'item': 'New', 'type': 'verify', 'mode': 'fbist'}
        result = describe_flow_input({**base, 'Recipe': 'ENTER-JUDGE(SHMOO=STEP)'})
        self.assertFalse(result['editGuided'])
        self.assertEqual(result['clearFields'], [])
        self.assertFalse(describe_flow_input({**base, 'type': '/'})['supported'])

    def test_standard_trim_uses_production_kind_and_describes_search_fields(self):
        result = describe_flow_input({
            "CP NO": "CP1",
            "item": "Vref_Trim",
            "type": "trim",
            "mode": "fbist",
        })

        fields = {field["name"]: field for field in result["fields"]}
        self.assertEqual(result["kind"], "STANDARD_TRIM")
        self.assertTrue(result["supported"])
        self.assertTrue(fields["DAC bit"]["required"])
        self.assertEqual(fields["Bisection"]["choices"], ["both", "both_m", "no", "yes"])
        self.assertFalse(fields["step"]["required"])
        self.assertTrue(fields["target"]["required"])
        self.assertNotIn("LINE", fields)
        self.assertEqual(fields["sub"]["default"], "/")
        self.assertEqual(fields["relay"]["default"], "/")
        self.assertEqual(fields["PE"]["default"], "no")
        self.assertNotIn("default", fields["Vcc"])

        custom = describe_flow_input({
            "CP NO": "CP1", "item": "Vref_Trim", "type": "trim", "mode": "fbist",
            "_codeMode": "custom",
        })
        self.assertTrue({field["name"]: field for field in custom["fields"]}["step"]["required"])
        json.dumps(custom)

    def test_frequency_trim_does_not_require_electrical_force(self):
        result = describe_flow_input({
            'CP NO': 'CP1', 'item': 'Clock_New', 'type': 'trim', 'mode': 'fbist', 'UNIT': 'MHz',
        })
        fields = {field['name']: field for field in result['fields']}
        self.assertFalse(fields['FV/FI']['required'])
        self.assertTrue(fields['target']['required'])

    def test_standard_verify_clears_trim_search_without_requiring_it(self):
        result = describe_flow_input({
            "CP NO": "CP1",
            "item": "Vref_Verify",
            "type": "verify",
            "mode": "fbist",
        })

        fields = {field["name"]: field for field in result["fields"]}
        self.assertEqual(result["kind"], "STANDARD_VERIFY")
        self.assertTrue(result["supported"])
        self.assertEqual(result["clearFields"], ["DAC bit", "Bisection", "LINE", "step"])
        self.assertTrue(set(fields).isdisjoint({"DAC bit", "Bisection", "LINE", "step"}))
        self.assertTrue(fields["UNIT"]["required"])
        self.assertTrue(fields["meas pin"]["required"])
        self.assertTrue(fields["Vcc"]["required"])

    def test_non_fbist_standard_trim_is_recognized_but_not_guided(self):
        result = describe_flow_input({
            "CP NO": "CP1", "item": "Vref_Trim", "type": "trim", "mode": "swd",
        })

        self.assertEqual(result["kind"], "STANDARD_TRIM")
        self.assertFalse(result["supported"])
        self.assertIn("mode=fbist", result["notice"])

    def test_known_kinds_are_routed_by_the_production_classifier(self):
        cases = (
            ("PDR_TRIM", {"type": "trim", "item": "Pdr_Trim", "mode": "fbist"}),
            ("PDR_VERIFY", {"type": "verify", "item": "Pdr_Verify", "mode": "fbist"}),
            ("ADC_TEST", {"type": "verify", "item": "Adc_Test", "mode": "keil", "FV/FI": "ADC1"}),
            ("OPA_TEST", {"type": "verify", "item": "Opa_Test", "mode": "swd", "Recipe": "OPA_TEST"}),
            ("DAC_TEST", {"type": "verify", "item": "Dac_Test", "mode": "keil", "Recipe": "DAC_TEST"}),
            ("PVD_TEST", {"type": "verify", "item": "Pvd_Test", "mode": "keil", "FV/FI": "PVD"}),
            ("FREQ_TEST", {"type": "verify", "item": "Freq_Test", "mode": "swd", "FV/FI": "FREQ"}),
            ("VERIFY_HEX", {"type": "verify", "item": "Firmware", "mode": "hex"}),
            ("VERIFY_KEIL", {"type": "verify", "item": "Firmware", "mode": "keil"}),
        )

        for expected, values in cases:
            with self.subTest(kind=expected):
                result = describe_flow_input({"CP NO": "CP1", **values})
                self.assertEqual(result["kind"], expected)
                self.assertTrue(result["supported"])
                if not result['supported']:
                    self.assertIn(expected, result["notice"])

    def test_opa_and_dac_descriptors_clear_their_prohibited_measurement_facts(self):
        opa = describe_flow_input({
            "CP NO": "CP1", "item": "Opa_Test", "type": "verify", "mode": "swd",
            "Recipe": "OPA_TEST",
        })
        dac = describe_flow_input({
            "CP NO": "CP1", "item": "Dac_Test", "type": "verify", "mode": "keil",
            "Recipe": "DAC_TEST",
        })

        self.assertTrue({'FV/FI','meas pin','low_range(%)','target','high_range(%)'}.issubset(opa['clearFields']))
        self.assertTrue({'FV/FI','meas pin','low_range(%)','high_range(%)'}.issubset(dac['clearFields']))
        self.assertNotIn('target', dac['clearFields'])
        self.assertNotIn('step', dac['clearFields'])
        self.assertTrue(
            {"target", "Vcc"}.issubset({field["name"] for field in dac["fields"]})
        )

    def test_missing_identity_returns_field_issues(self):
        result = describe_flow_input({"type": "trim"})

        self.assertIsNone(result["kind"])
        self.assertEqual({issue["field"] for issue in result["issues"]}, {"CP NO", "item", "mode"})


if __name__ == "__main__":
    unittest.main()
