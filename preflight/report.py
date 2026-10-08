# Finding 数据结构 + 控制台/HTML 报告渲染。
import html as _html

ERROR = "ERROR"   # 拦住生成（gate 抛异常）
WARN = "WARN"     # 只报告，不拦


class PreflightError(Exception):
    """gate 模式下发现 ERROR 时抛出，附带 findings。"""
    def __init__(self, findings):
        self.findings = findings
        n = sum(1 for f in findings if f.severity == ERROR)
        super().__init__(f"母本输入校验未通过：{n} 个 ERROR（详见报告）")


class Finding:
    __slots__ = ("sheet", "coord", "category", "severity", "message", "suggest")

    def __init__(self, sheet, coord, category, severity, message, suggest=""):
        self.sheet = sheet
        self.coord = coord            # 单元格如 "Q40"；整行/整表问题可为 "" 或 "row 12"
        self.category = category      # "A 字符卫生" / "C1 类型" ...
        self.severity = severity      # ERROR / WARN
        self.message = message
        self.suggest = suggest

    @property
    def loc(self):
        return f"{self.sheet}!{self.coord}" if self.coord else self.sheet

    def __repr__(self):
        return f"<{self.severity} {self.loc} {self.category}: {self.message}>"


def _sort_key(f):
    return (0 if f.severity == ERROR else 1, f.sheet, f.coord)


def render_console(findings):
    """返回控制台文本报告。"""
    if not findings:
        return "[preflight] 母本校验通过：0 问题。"
    findings = sorted(findings, key=_sort_key)
    nerr = sum(1 for f in findings if f.severity == ERROR)
    nwarn = len(findings) - nerr
    lines = [f"[preflight] 母本校验：{nerr} ERROR / {nwarn} WARN", "-" * 72]
    for f in findings:
        tag = "X" if f.severity == ERROR else "!"  # console 用 ASCII（Windows gbk 不支持 ✗）
        line = f"  {tag} [{f.severity}] {f.loc:<22} {f.category}: {f.message}"
        lines.append(line)
        if f.suggest:
            lines.append(f"      建议: {f.suggest}")
    return "\n".join(lines)


def render_html(findings, xlsx_path=""):
    """返回 HTML 报告字符串（符合项目"文档默认 HTML"规范）。"""
    findings = sorted(findings, key=_sort_key)
    nerr = sum(1 for f in findings if f.severity == ERROR)
    nwarn = len(findings) - nerr
    rows = []
    for f in findings:
        cls = "err" if f.severity == ERROR else "warn"
        rows.append(
            f"<tr class={cls}><td>{f.severity}</td><td>{_html.escape(f.loc)}</td>"
            f"<td>{_html.escape(f.category)}</td><td>{_html.escape(f.message)}</td>"
            f"<td>{_html.escape(f.suggest)}</td></tr>")
    body = "\n".join(rows) if rows else "<tr><td colspan=5>0 问题，母本校验通过 ✓</td></tr>"
    return f"""<!doctype html><meta charset=utf-8><title>母本输入校验报告</title>
<style>body{{font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:16px;font-size:13px}}
h2{{margin:8px 0}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}}
th{{background:#2d3a4a;color:#fff;position:sticky;top:0}}tr.err td{{background:#fdecea}}tr.warn td{{background:#fff8e1}}
.sum{{font-size:15px;margin:6px 0}}</style>
<h2>母本输入校验报告</h2>
<p class=sum>来源：{_html.escape(xlsx_path)}　结果：<b style="color:#c0392b">{nerr} ERROR</b> / <b style="color:#b8860b">{nwarn} WARN</b></p>
<table><tr><th>级别</th><th>位置</th><th>类别</th><th>说明</th><th>建议</th></tr>
{body}
</table>"""
