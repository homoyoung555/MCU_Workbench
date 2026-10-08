"""Focused contract tests for ordinary VT platform adapters."""

from types import SimpleNamespace
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.vt_test import VtTestPlan
from program_gen.platforms.chroma.vt_test_adapter import adapt_vt_test
from program_gen.platforms.s100.vt_test_adapter import adapt_vt_test as adapt_s100_vt_test
from tests.workspace_paths import WORKSPACE_ROOT


def _run(name, labels=("START", "END"), span=None):
    pattern = PatternResourceRef(name, f"pattern:{name}", labels)
    return RunPatternPlan(pattern, span or PatternSpan.full(), "TS_5MHZ")


class VtAdapterTests(unittest.TestCase):
    def test_chroma_emits_custom_spans_gate_and_vte_retry_cleanup(self):
        gate = SimpleNamespace(
            gate_symbol="CP1_BAKEID_NEEDS_WRITE",
            gate_semantic_identity="CP1:CP1_BAKEID_NEEDS_WRITE",
        )
        plan = VtTestPlan(
            "VCC_TYP",
            _run("enter_fbist_mode"),
            _run("enter_vte_verify", ("START", "verify", "END"),
                 PatternSpan.segment("START", "verify")),
            _run("fbist_bulk_read_nm", ("START", "read", "END"),
                 PatternSpan.segment("read", "END")),
            -0.2,
            True,
            gate,
        )

        emission = adapt_vt_test(plan)
        source = "\n".join(emission.statements)

        self.assertEqual(source.count("POWER_ON(VCC_TYP);"), 1)
        self.assertIn("SOCKET_SET(B:CP1_BAKEID_NEEDS_WRITE,FRZ_OFF)", source)
        self.assertIn("JUDGE_PAT(enter_vte_verify,enter_vte_verify:verify);", source)
        self.assertIn("JUDGE_PAT(fbist_bulk_read_nm:read,__fbist_bulk_read_nm);", source)
        self.assertIn("BACKUP_PLAN_RESULT();", source)
        self.assertEqual(source.count("FAIL_REJUDGE(1,FRZ_OFF)"), 1)
        self.assertEqual(source.count("JUDGE_PAT(fbist_bulk_read_nm:read,__fbist_bulk_read_nm);"), 2)
        self.assertEqual(source.count('DATALOG_MSG="enter_fbist_mode"'), 1)
        self.assertEqual(source.count('DATALOG_MSG="enter_vte_verify"'), 1)
        self.assertEqual(source.count('DATALOG_MSG="fbist_bulk_read_nm"'), 2)
        self.assertLess(source.index("POWER_ON"), source.index("RELAY_ON"))
        self.assertLess(source.index("FORCE_V_PPMU(TP, -0.2V"), source.index("BACKUP_PLAN_RESULT"))
        self.assertLess(source.index("FORCE_V_PPMU(TP,0V"), source.index("RELAY_OFF"))
        self.assertLess(source.index("RELAY_OFF"), source.index("POWER_OFF"))
        self.assertEqual(emission.provides, ())
        self.assertEqual(
            {(item.logical_identity, item.relative_path) for item in emission.resource_requires},
            {
                ("pattern:enter_fbist_mode", "pat/enter_fbist_mode.pat"),
                ("pattern:enter_vte_verify", "pat/enter_vte_verify.pat"),
                ("pattern:fbist_bulk_read_nm", "pat/fbist_bulk_read_nm.pat"),
            },
        )
        self.assertEqual(
            tuple(item.ref.identity for item in emission.requires),
            ("ID_GATE.CP1:CP1_BAKEID_NEEDS_WRITE",),
        )

    def test_s100_retries_only_failed_sites_and_restores_failure(self):
        plan = VtTestPlan(
            "VCC_MAX",
            _run("enter_fbist_mode"),
            _run("enter_vtp_verify"),
            _run("fbist_bulk_read_nm"),
            0.45,
            True,
        )

        emission = adapt_s100_vt_test(plan)
        source = "\n".join(emission.statements)

        self.assertIn("RUN_PATTERN(fbist_bulk_read_nm:START,fbist_bulk_read_nm:END,1,TS_5MHZ, IGNORE_FAIL);", source)
        self.assertEqual(source.count("RUN_PATTERN(fbist_bulk_read_nm:START,fbist_bulk_read_nm:END,1,TS_5MHZ);"), 1)
        self.assertIn("vtReadFailed[T_SOCKET]=vtActiveSites[T_SOCKET] && Sys_DriverResult[T_SOCKET]<0.5;", source)
        self.assertIn("Sys_ActiveSite[T_SOCKET]=vtReadFailed[T_SOCKET];", source)
        self.assertNotIn("SYS_SetTestResult", source)
        self.assertLess(source.index("CALL_MACRO POWER_ON"), source.index("RUN_PATTERN(enter_fbist_mode"))
        self.assertLess(source.index("LOGIC_PPMU_FV(TP, 0.45V"), source.index("RUN_PATTERN(fbist_bulk_read_nm"))
        self.assertLess(source.index("LOGIC_PPMU_FV(TP, 0V"), source.index("CALL_MACRO POWER_OFF"))
        self.assertNotIn("MARK_NO", source)
        self.assertNotIn("provides", source)

    def test_s100_emitted_site_control_executes_retry_and_gate_truth_table(self):
        bcb = WORKSPACE_ROOT / "toolchains" / "s100" / "app" / "BCB6"
        compiler = bcb / "Bin" / "bcc32.exe"
        if not compiler.is_file():
            self.skipTest("local BCB6 runtime harness unavailable")
        # Execute emitted C++ control flow. Only tester I/O is replaced with a
        # fake that records calls and accumulates failures (not hardware proof).
        functions = []
        for gated in (False, True):
            for retry in (False, True):
                gate = SimpleNamespace(gate_symbol="gateFlags", gate_semantic_identity="CP2:test") if gated else None
                plan = VtTestPlan("VCC_TYP", _run("enter_fbist_mode"), _run("enter_vt"),
                                  _run("read_nm"), -0.2, retry, gate)
                source = "\n".join(adapt_s100_vt_test(plan).statements)
                source = re.sub(r"RUN_PATTERN\(([^:]+):[^;]+;", lambda m:
                    "run(%d,%s);" % ({"enter_fbist_mode": 0, "enter_vt": 1, "read_nm": 2}[m[1]],
                                      "true" if "IGNORE_FAIL" in m[0] else "false"), source)
                source = re.sub(r"CALL_MACRO POWER_ON\([^;]+;", "power(1);", source)
                source = source.replace("CALL_MACRO POWER_OFF();", "power(0);")
                source = re.sub(r"(?:LOGIC_PPMU_FV|LOGIC_DISCONNECT_PPMU_PIN|WAIT)\([^;]+;", ";", source)
                functions.append(f"void test_{int(gated)}{int(retry)}() {{\n{source}\n}}")
        harness = r'''
#include <assert.h>
#include <stdio.h>
#define MAX_SITE 2
int T_SOCKET,Sys_TEST_DIE=2,Sys_ActiveSite[2],Sys_DriverResult[2],gateFlags[2];
int masks[7],result[2],reads[2],powered[2],on[2],off[2];
void power(int value) { for(int s=0;s<2;s++) if(Sys_ActiveSite[s]) {
  powered[s]=value; if(value) on[s]++; else off[s]++;
} }
void run(int step,bool ignore) { for(int s=0;s<2;s++) if(Sys_ActiveSite[s]) {
  assert(powered[s]);
  int mask=step<2 ? masks[3+step] : masks[5+(reads[s]++>0)];
  int ok=(mask>>s)&1; Sys_DriverResult[s]=ok;
  if(!ignore && !ok) result[s]=0;
} }
''' + "\n".join(functions) + r'''
int main() {
 void (*tests[4])()={test_00,test_01,test_10,test_11};
 for(int kind=0;kind<4;kind++) for(int c=0;c<16384;c++) {
  int bits=c;
  for(int m=0;m<7;m++){masks[m]=bits&3;bits>>=2;}
  for(int s=0;s<2;s++) {
   Sys_ActiveSite[s]=(masks[0]>>s)&1; gateFlags[s]=(masks[1]>>s)&1;
   result[s]=(masks[2]>>s)&1; reads[s]=powered[s]=on[s]=off[s]=0;
  }
  tests[kind]();
  for(int s=0;s<2;s++) {
   int active=(masks[0]>>s)&1, selected=active && (!(kind&2)||gateFlags[s]);
   int initial=(masks[2]>>s)&1, enter=((masks[3]&masks[4])>>s)&1;
   int first=(masks[5]>>s)&1, second=(masks[6]>>s)&1;
   assert(Sys_ActiveSite[s]==active && !powered[s]);
   assert(on[s]==selected && off[s]==selected);
   assert(reads[s]==(selected ? 1+((kind&1)&&!first) : 0));
   assert(result[s]==(initial && (!selected || (enter && (first || ((kind&1)&&second))))));
  }
 }
 puts("65536 gate/retry/previous-result scenarios passed");
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="vt_check_") as temporary:
            folder = Path(temporary)
            (folder / "check.cpp").write_text(harness, encoding="ascii")
            environment = dict(os.environ, PATH=str(bcb / "Bin") + os.pathsep + os.environ.get("PATH", ""))
            compile_result = subprocess.run([str(compiler), "-q", "-tWC", f"-I{bcb / 'Include'}",
                f"-L{bcb / 'Lib'}", "-echeck.exe", "check.cpp"], cwd=folder, env=environment,
                capture_output=True, timeout=60)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            result = subprocess.run([str(folder / "check.exe")], cwd=folder, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(b"65536", result.stdout)

    def test_s100_uses_two_microamp_range_and_disconnects_ppmu_before_power_off(self):
        plan = VtTestPlan("VCC_TYP", _run("enter_fbist_mode"), _run("enter_vt"),
                          _run("read_nm"), -0.2, False)
        source = "\n".join(adapt_s100_vt_test(plan).statements)
        self.assertIn("LOGIC_PPMU_FV(TP, -0.2V, E2, I1);", source)
        self.assertIn("LOGIC_PPMU_FV(TP, 0V, E2, I5);", source)
        self.assertLess(source.index("LOGIC_PPMU_FV(TP, 0V"), source.index("LOGIC_DISCONNECT_PPMU_PIN(TP)"))
        self.assertLess(source.index("LOGIC_DISCONNECT_PPMU_PIN(TP)"), source.index("CALL_MACRO POWER_OFF"))


if __name__ == "__main__":
    unittest.main()
