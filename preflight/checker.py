# 校验入口：跑全部规则，回 findings；gate=True 时有 ERROR 就抛 PreflightError。
from program_gen.workbook import WorkbookModel, WorkbookReader

from .reader import MasterReader
from .rules import INPUT_CHECKS
from .report import ERROR, PreflightError, render_console


def check_master(workbook_or_path, gate=False, verbose=False):
    """Project ProductCompilation.Diagnostics as legacy preflight Findings."""
    from program_gen.compiler import ProductCompilation, ProductCompiler

    if isinstance(workbook_or_path, ProductCompilation):
        compilation = workbook_or_path
    else:
        workbook = (
            workbook_or_path
            if isinstance(workbook_or_path, WorkbookModel)
            else WorkbookReader().read(workbook_or_path)
        )
        compilation = ProductCompiler().compile(workbook)

    findings = [
        _finding_from_diagnostic(item)
        for item in compilation.diagnostics.items
        if item.enforcement == "ENFORCED"
    ]
    _report_or_gate(findings, gate=gate, verbose=verbose)
    return findings


def _run_input_checks(workbook):
    """Run only workbook-shape rules; never invoke a business compiler."""
    reader = MasterReader(workbook)
    findings = []
    try:
        for check in INPUT_CHECKS:
            check(reader, findings)
    finally:
        reader.close()
    return findings


def _finding_from_diagnostic(diagnostic):
    from .report import Finding

    return Finding(
        diagnostic.provenance.sheet,
        diagnostic.provenance.coordinate,
        diagnostic.category,
        diagnostic.severity,
        diagnostic.message,
        diagnostic.remediation,
    )


def _report_or_gate(findings, *, gate, verbose):
    nerr = sum(1 for f in findings if f.severity == ERROR)
    nwarn = len(findings) - nerr
    if verbose:
        print(render_console(findings))
    elif gate:
        if nerr:
            print(render_console(findings))      # 有 ERROR：打全表
        else:
            # 例行生成只一行摘要，WARN 详情去 tools/check_master.py 报告，别刷屏
            print(f"[preflight] 母本校验通过：0 ERROR / {nwarn} WARN"
                  + ("（详情跑 tools/check_master.py）" if nwarn else ""))

    if gate and nerr:
        raise PreflightError(findings)
