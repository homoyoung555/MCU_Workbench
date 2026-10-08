# 母本输入校验 CLI（独立跑，不碰生成器）。
#   python tools/check_master.py [母本.xlsx] [--html 报告.html]
# 默认母本 = test_data/program.xlsx；默认在母本同目录出 母本校验报告.html。
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from preflight import check_master, render_console, render_html  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_XLSX = os.path.join(ROOT, "test_data", "program.xlsx")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    xlsx = args[0] if args else DEFAULT_XLSX
    if "--contract" in argv:
        from preflight.contract import render_contract_html
        out = os.path.join(ROOT, "母本输入契约.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_contract_html())
        print(f"母本输入契约 -> {out}")
        return 0
    html_out = None
    for a in argv:
        if a.startswith("--html"):
            html_out = a.split("=", 1)[1] if "=" in a else os.path.join(
                os.path.dirname(xlsx), "母本校验报告.html")
    if html_out is None:
        html_out = os.path.join(os.path.dirname(xlsx), "母本校验报告.html")

    findings = check_master(xlsx, gate=False)
    print(render_console(findings))
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(render_html(findings, xlsx))
    print(f"\nHTML 报告 -> {html_out}")
    # 退出码：有 ERROR 非 0（方便接 CI / 脚本）
    return 1 if any(f.severity == "ERROR" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
