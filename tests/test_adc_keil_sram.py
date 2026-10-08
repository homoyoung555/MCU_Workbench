import io
import unittest

from program_gen.platforms.chroma import adc_writer as chroma_adc
from program_gen.platforms.s100 import adc_writer as s100_adc


class AdcKeilSramTests(unittest.TestCase):
    def test_chroma_uses_runtime_loop_and_native_sram_data(self):
        out = io.StringIO()
        chans = [
            (0, "PA0", 0.3, "PA0", True, 64),
            (1, None, 1.2, "BUFOUT", True, 128),
        ]

        chroma_adc._keil_sram_loop_write(
            out, 1, chans, [0, 1], 0x3000, 3.3, 4096
        )
        text = out.getvalue()

        self.assertIn("for(K=0;K<2;K++)", text)
        self.assertIn("Read_SRAM(0X3000+K*4);", text)
        self.assertIn("sram_data[SOCKET]", text)
        self.assertNotIn("GBX", text)

    def test_s100_uses_runtime_loop_and_startup_registered_alias(self):
        out = io.StringIO()

        s100_adc._keil_sram_loop_write(out, 1, 2, [0, 1], 0x3000)
        text = out.getvalue()

        self.assertIn("for(int K=0;K<2;K++)", text)
        self.assertIn("Read_SRAM(0X3000+K*4);", text)
        self.assertIn('sprintf(_C_LOG_MSG_ADC1,"ADC1_MEAN_%s_Verify"', text)
        self.assertIn("C_COMPARE(GBX2", text)
        self.assertIn("LOG_ALIAS=_C_LOG_MSG_ADC1", text)


if __name__ == "__main__":
    unittest.main()
