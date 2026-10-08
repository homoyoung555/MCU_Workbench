import unittest

from program_gen.core.page_image import (
    ValueBinding,
    compile_value_binding,
    FieldTarget,
    FieldWrite,
    IncompletePageImageError,
    PageImageStore,
)


class PageImageModelTests(unittest.TestCase):
    def test_commit_rejects_a_page_without_a_complete_image(self):
        store = PageImageStore()
        target = FieldTarget(
            field="DLPR0_VSEL_OP_VDDK",
            page="trim1",
            register="ANA_MUX_TRIM2",
            lsb=0,
            width=2,
            destination="OTP",
        )

        with self.assertRaisesRegex(IncompletePageImageError, "trim1"):
            store.commit((FieldWrite(target=target, value=1),))

        self.assertEqual(store.dirty_pages, ())

    def test_commit_rejects_an_explicitly_partial_page_image(self):
        store = PageImageStore()
        store.establish_page(
            "uid", {"UID_REG0": 0x1234}, source="READOTPMAP", complete=False
        )
        target = FieldTarget("PASS_FLAG", "uid", "UID_REG0", 0, 8, "UID")

        self.assertFalse(store.has_complete_page("uid"))
        with self.assertRaisesRegex(IncompletePageImageError, "uid"):
            store.commit((FieldWrite(target, 0xBA),))

        self.assertEqual(store.register_value("uid", "UID_REG0"), 0x1234)

    def test_commit_preserves_other_fields_in_the_real_register_value(self):
        store = PageImageStore()
        store.establish_page(
            "trim1", {"ANA_MUX_TRIM2": 0x0006}, source="READOTPMAP"
        )
        target = FieldTarget(
            field="DLPR0_VSEL_OP_VDDK",
            page="trim1",
            register="ANA_MUX_TRIM2",
            lsb=0,
            width=2,
            destination="OTP",
        )

        affected = store.commit((FieldWrite(target=target, value=1),))

        self.assertEqual(store.register_value("trim1", "ANA_MUX_TRIM2"), 0x0005)
        self.assertEqual(affected, ("trim1",))
        self.assertEqual(store.dirty_pages, ("trim1",))
        self.assertTrue(store.has_complete_page("trim1"))
        self.assertEqual(store.page_source("trim1"), "READOTPMAP")

    def test_one_verify_binding_fans_out_one_encoded_value_to_otp_and_uid(self):
        binding = compile_value_binding(
            item="Vrefint",
            flow_type="verify",
            otp_targets=("VREFINT_OTP",),
            uid_targets=("VREFINT_UID",),
        )

        self.assertEqual(binding.encoding, "BCD16_MV")
        self.assertEqual(binding.source_kind, "MEASUREMENT")
        self.assertEqual(
            [(target.destination, target.field) for target in binding.targets],
            [("OTP", "VREFINT_OTP"), ("UID", "VREFINT_UID")],
        )
        encoded = binding.encode(1.234)
        self.assertEqual(encoded, 0x1234)
        self.assertEqual(binding.values_by_target(1.234), (0x1234, 0x1234))

    def test_ts_verify_and_trim_use_their_domain_default_encodings(self):
        ts = compile_value_binding(
            item="TS_125C",
            flow_type="verify",
            uid_targets=("TS_125C_VERIFY",),
        )
        trim = compile_value_binding(
            item="Vrefint",
            flow_type="trim",
            otp_targets=("VREFINT_TRIM",),
        )

        self.assertEqual((ts.source_kind, ts.encoding), ("MEASUREMENT", "ADC12_3V3"))
        self.assertEqual(ts.encode(1.65), 2048)
        self.assertEqual((trim.source_kind, trim.encoding), ("DAC_FINAL", "FINAL_DAC"))
        self.assertEqual(trim.encode(37), 37)

        embedded_ts = compile_value_binding(
            item="Sensor_TS_30C",
            flow_type="verify",
            uid_targets=("TS_30C_VERIFY",),
        )
        self.assertEqual(embedded_ts.encoding, "ADC12_3V3")

    def test_commit_is_atomic_when_any_target_register_is_unavailable(self):
        store = PageImageStore()
        store.establish_page("trim1", {"REG_A": 0xA}, source="READOTPMAP")
        writes = (
            FieldWrite(FieldTarget("A", "trim1", "REG_A", 0, 2, "OTP"), 1),
            FieldWrite(FieldTarget("B", "trim1", "REG_B", 0, 1, "OTP"), 1),
        )

        with self.assertRaisesRegex(IncompletePageImageError, "REG_B"):
            store.commit(writes)

        self.assertEqual(store.register_value("trim1", "REG_A"), 0xA)
        self.assertEqual(store.dirty_pages, ())


if __name__ == "__main__":
    unittest.main()
