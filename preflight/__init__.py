# 母本输入校验（preflight）—— ProductCompilation.Diagnostics 的确定性只读视图。
# 依赖方向单向：生成器可调本包当 gate，本包绝不 import 生成器代码。
#
# 用法：
#   from preflight import check_master
#   findings = check_master(xlsx_path)            # 返回 [Finding...]
#   check_master(xlsx_path, gate=True)            # 有 Error 就抛 PreflightError（生成前 gate）
#
# 设计见 .claude/PROJECT_MAP.md 的 preflight 条目与「母本输入契约」HTML 文档。
from .report import Finding, ERROR, WARN, PreflightError, render_console, render_html
from .checker import check_master
from program_gen.workbook import WorkbookModel, WorkbookReader

__all__ = ["check_master", "Finding", "ERROR", "WARN",
           "PreflightError", "render_console", "render_html",
           "WorkbookModel", "WorkbookReader"]
