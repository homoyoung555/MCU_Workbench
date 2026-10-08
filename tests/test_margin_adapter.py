"""Margin adapters must bisect per site without rejecting scan failures."""

from pathlib import Path
import os
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from program_gen.core.margin_test import MarginTestPlan
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.platforms.chroma.margin_test_adapter import adapt_margin_test as adapt_chroma_margin
from program_gen.platforms.s100.margin_test_adapter import adapt_margin_test
from tests.workspace_paths import WORKSPACE_ROOT


def margin_plan(start=0.0, end=-1.0, gated=False):
    def run(name):
        return RunPatternPlan(PatternResourceRef(name, f"pattern:{name}", ("START", "END")),
                              PatternSpan.full(), "TS_5MHZ")
    gate = SimpleNamespace(gate_symbol="gateFlags", gate_semantic_identity="CP2:bake") if gated else None
    return MarginTestPlan("VCC_TYP", run("enter_fbist_mode"), run("enter_vt"), run("read_nm"),
                          start, end, 8, "Margin_Test", gate)


def _replace_chroma_io(plan):
    """Keep emitted control flow; replace only CRAFT-specific I/O in the harness."""
    source = "\n".join(adapt_chroma_margin(plan).statements).replace("VOLTAGE ", "double ")
    source = re.sub(r"(?<![A-Za-z0-9_])(-?(?:\d+(?:\.\d*)?|\.\d+))V\b", r"\1", source)
    source = source.replace("SOCKET_SET(B:gateFlags,FRZ_OFF)\n  {", "gate_open();\n  {")
    source = source.replace("  POWER_OFF();\n  }\n  }", "  POWER_OFF();\n  gate_close();\n  }\n  }")
    source = source.replace("SOCKET_INC(FRZ_OFF)",
                            "for(SOCKET=0;SOCKET<MAX_SITE;SOCKET++) if(Sys_ActiveSite[SOCKET])")
    source = re.sub(r"POWER_ON\([^;]+;", "power(1);", source)
    source = source.replace("POWER_OFF();", "power(0);")
    source = re.sub(r"(?:RELAY_ON|RELAY_OFF|WAIT)\([^;]+;", ";", source)
    source = re.sub(r"JUDGE_PAT\(([^,]+),[^;]+;",
                    lambda match: "run(%d, false);" % (2 if match[1] == "read_nm" else 0), source)
    source = re.sub(r"FORCE_V_PPMU\(TP,marginMid\[SOCKET\],[^;]+;",
                    "force(SOCKET,marginMid[SOCKET]);", source)
    source = re.sub(r"FORCE_V_PPMU\([^;]+;", "cleanup();", source)
    source = re.sub(r'TEST_NO\([^;]+;\s*DATALOG_MSG="[^"]+";', ";", source)
    return re.sub(r"JUDGE_VARIABLE\(SOCKET,([^,]+),[^;]+;", r"log_value(SOCKET,\1);", source)


def _replace_s100_io(plan):
    """Keep emitted control flow; replace only YT5100-specific I/O in the harness."""
    source = "\n".join(adapt_margin_test(plan).statements)
    source = re.sub(r"RUN_PATTERN\(([^:]+):[^;]+;",
                    lambda match: "run(%d, %s);" % (
                        2 if match[1] == "read_nm" else 0,
                        "true" if "IGNORE_FAIL" in match[0] else "false"), source)
    source = re.sub(r"CALL_MACRO POWER_ON\([^;]+;", "power(1);", source)
    source = source.replace("CALL_MACRO POWER_OFF();", "power(0);")
    source = re.sub(r"LOGIC_PPMU_FV\(TP, _C_marginVoltage,[^;]+;",
                    "force_single_site(marginSite,_C_marginVoltage);", source)
    source = re.sub(r"LOGIC_PPMU_FV\(TP, 0V,[^;]+;", "cleanup();", source)
    source = re.sub(r"(?:LOGIC_PPMU_FV|LOGIC_DISCONNECT_PPMU_PIN|WAIT)\([^;]+;", ";", source)
    return re.sub(r"C_COMPARE\([^;]+;", "commit_logs();", source)


def _runtime_harness(chroma_vte, chroma_vtp, s100_vte, s100_vtp):
    return r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#define MAX_SITE 2
const int PASS=1;
int SOCKET,T_SOCKET,Sys_TEST_DIE=MAX_SITE,Sys_ActiveSite[MAX_SITE],gateFlags[MAX_SITE];
int PLAN_RESULT_MS[MAX_SITE],JUDGE_RESULT_MS[MAX_SITE],enterMask;
double Sys_DriverResult[MAX_SITE],GB[128];
bool VTEN_FLAG;
int scanCode[MAX_SITE],readCount[MAX_SITE],forceCount[MAX_SITE],onCount[MAX_SITE],offCount[MAX_SITE];
int cleanupCount[MAX_SITE],logCount[MAX_SITE],TEST_NUM;
double forced[MAX_SITE][8],logged[MAX_SITE];
int gateSites[MAX_SITE];

void gate_open() {
  for(int s=0;s<MAX_SITE;s++) { gateSites[s]=Sys_ActiveSite[s]; Sys_ActiveSite[s]=gateSites[s] && gateFlags[s]; }
}
void gate_close() { for(int s=0;s<MAX_SITE;s++) Sys_ActiveSite[s]=gateSites[s]; }
void power(int value) {
  for(int s=0;s<MAX_SITE;s++) if(Sys_ActiveSite[s]) { if(value) onCount[s]++; else offCount[s]++; }
}
void force(int site,double value) {
  assert(Sys_ActiveSite[site] && forceCount[site]<8);
  forced[site][forceCount[site]++]=value;
}
void force_single_site(int site,double value) {
  for(int s=0;s<MAX_SITE;s++) assert(Sys_ActiveSite[s]==(s==site));
  force(site,value);
}
void cleanup() { for(int s=0;s<MAX_SITE;s++) if(Sys_ActiveSite[s]) cleanupCount[s]++; }
void run(int pattern,bool ignore) {
  for(int s=0;s<MAX_SITE;s++) if(Sys_ActiveSite[s]) {
    int pass=pattern==2 ? ((scanCode[s]>>(7-readCount[s]++))&1) : ((enterMask>>s)&1);
    JUDGE_RESULT_MS[s]=pass; Sys_DriverResult[s]=pass;
    if(!ignore && !pass) PLAN_RESULT_MS[s]=0;
  }
}
void log_value(int site,double value) { logged[site]=value; logCount[site]++; PLAN_RESULT_MS[site]=0; }
void commit_logs() {
  for(int s=0;s<MAX_SITE;s++) if(Sys_ActiveSite[s]) { logged[s]=GB[7+s*64]; logCount[s]++; }
}
void reset_case(int active,int gate,int entered,int enabled,int first,int second) {
  enterMask=entered; VTEN_FLAG=enabled; TEST_NUM=0;
  for(int s=0;s<MAX_SITE;s++) {
    Sys_ActiveSite[s]=(active>>s)&1; gateFlags[s]=(gate>>s)&1; PLAN_RESULT_MS[s]=PASS;
    JUDGE_RESULT_MS[s]=Sys_DriverResult[s]=-7; scanCode[s]=s ? second : first;
    readCount[s]=forceCount[s]=onCount[s]=offCount[s]=cleanupCount[s]=logCount[s]=0;
    logged[s]=GB[7+s*64]=12345.0;
  }
}
double expect_mid(double start,double end,int code,int step) {
  double left=start,right=end;
  for(int bit=0;bit<step;bit++) { double mid=(left+right)/2; if((code>>(7-bit))&1) left=mid; else right=mid; }
  return (left+right)/2;
}
double expect_result(double start,double end,int code) {
  if(code==0) return start;
  if(code==255) return end;
  return start+(end-start)*(code+.5)/256.0;
}
void check_case(double start,double end,int active,int gate,int enabled,int first,int second) {
  for(int s=0;s<MAX_SITE;s++) {
    int selected=enabled && ((active>>s)&1) && ((gate>>s)&1), code=s ? second : first;
    assert(Sys_ActiveSite[s]==((active>>s)&1));
    assert(onCount[s]==selected && offCount[s]==selected && cleanupCount[s]==selected);
    assert(readCount[s]==(selected ? 8 : 0) && forceCount[s]==(selected ? 8 : 0));
    assert(PLAN_RESULT_MS[s]==PASS);
    assert(logCount[s]==selected && (selected || GB[7+s*64]==12345.0));
    if(selected) {
      for(int step=0;step<8;step++) assert(fabs(forced[s][step]-expect_mid(start,end,code,step))<1e-12);
      assert(fabs(logged[s]-expect_result(start,end,code))<1e-12);
    }
  }
}

void chroma_vte() {
''' + chroma_vte + r'''
}
void chroma_vtp() {
''' + chroma_vtp + r'''
}
void s100_vte() {
''' + s100_vte + r'''
}
void s100_vtp() {
''' + s100_vtp + r'''
}
int main() {
  void (*tests[2][2])()={{chroma_vte,chroma_vtp},{s100_vte,s100_vtp}};
  double starts[2]={0.0,0.2},ends[2]={-1.0,1.0};
  for(int platform=0;platform<2;platform++) for(int polarity=0;polarity<2;polarity++)
    for(int first=0;first<256;first++) for(int second=0;second<256;second++) {
      reset_case(3,3,3,1,first,second); tests[platform][polarity]();
      check_case(starts[polarity],ends[polarity],3,3,1,first,second);
    }
  int representative[3][2]={{0,255},{0x35,0xca},{255,0}};
  for(int platform=0;platform<2;platform++) for(int sample=0;sample<3;sample++)
    for(int active=0;active<4;active++) for(int gate=0;gate<4;gate++)
      for(int entered=0;entered<4;entered++)
        for(int enabled=0;enabled<2;enabled++) {
          reset_case(active,gate,entered,enabled,representative[sample][0],representative[sample][1]);
          tests[platform][0]();
          check_case(0.0,-1.0,active,gate,enabled,
                     representative[sample][0],representative[sample][1]);
        }
  puts("margin adapters: 65536 two-site sequences per platform plus state masks passed");
  return 0;
}
'''


class MarginAdapterTests(unittest.TestCase):
    def test_chroma_logs_without_limits_or_result_backups(self):
        emission = adapt_chroma_margin(margin_plan(gated=True))
        source = "\n".join(emission.statements)
        self.assertIn("if(VTEN_FLAG)", source)
        self.assertIn("SOCKET_SET(B:gateFlags,FRZ_OFF)", source)
        self.assertIn("marginStep<8", source)
        self.assertIn("JUDGE_RESULT_MS[SOCKET]==PASS", source)
        self.assertEqual(source.count("PLAN_RESULT_MS[SOCKET]=PASS;"), 1)
        self.assertIn('JUDGE_VARIABLE(SOCKET,marginMid[SOCKET], , ,"Margin_Test");', source)
        self.assertEqual(source.count('DATALOG_MSG="enter_fbist_mode"'), 1)
        self.assertEqual(source.count('DATALOG_MSG="enter_vt"'), 1)
        self.assertEqual(source.count('DATALOG_MSG="read_nm"'), 1)
        for redundant in ("marginPrior", "marginSeenPass", "marginSeenFail", "marginResult"):
            self.assertNotIn(redundant, source)
        self.assertEqual(len(emission.resource_requires), 3)

    def test_s100_emits_bisection_and_isolated_scan_results(self):
        emission = adapt_margin_test(margin_plan(gated=True))
        source = "\n".join(emission.statements)
        self.assertIn("if(VTEN_FLAG)", source)
        self.assertIn("marginStep<8", source)
        self.assertIn("marginMid[marginSite]", source)
        for redundant in ("marginSeenPass", "marginSeenFail", "marginResult"):
            self.assertNotIn(redundant, source)
        self.assertIn("RUN_PATTERN(read_nm:START,read_nm:END,1,TS_5MHZ, IGNORE_FAIL);", source)
        self.assertIn("RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ, IGNORE_FAIL);", source)
        self.assertIn("RUN_PATTERN(enter_vt:START,enter_vt:END,1,TS_5MHZ, IGNORE_FAIL);", source)
        self.assertNotIn("SYS_SetTestResult", source)
        self.assertNotIn("VT_RANG", source)
        self.assertIn("IGNORE_FAIL", source.split("C_COMPARE(")[1])
        self.assertEqual(len(emission.resource_requires), 3)
        self.assertEqual(emission.requires[0].ref.identity, "ID_GATE.CP2:bake")

    def test_emitted_bisection_runtime_covers_sequences_and_site_masks(self):
        bcb = WORKSPACE_ROOT / "toolchains" / "s100" / "app" / "BCB6"
        compiler = bcb / "Bin" / "bcc32.exe"
        if not compiler.is_file():
            self.skipTest("local BCB6 runtime harness unavailable")
        chroma_vte = _replace_chroma_io(margin_plan(0.0, -1.0, gated=True))
        chroma_vtp = _replace_chroma_io(margin_plan(0.2, 1.0, gated=True))
        s100_vte = _replace_s100_io(margin_plan(0.0, -1.0, gated=True))
        s100_vtp = _replace_s100_io(margin_plan(0.2, 1.0, gated=True))
        harness = _runtime_harness(chroma_vte, chroma_vtp, s100_vte, s100_vtp)
        with tempfile.TemporaryDirectory(prefix="margin_adapter_check_") as temporary:
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


if __name__ == "__main__":
    unittest.main()
