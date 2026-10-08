# 「母本输入契约」HTML 文档生成器——从 schema 渲染，永不和校验逻辑漂移。
# 给手填母本的人看：每列允许什么、禁止什么、常见错例。
# 生成：python tools/check_master.py --contract  （或 import 调 render_contract_html）
import html as _html

from . import schema as S

_TYPE_CN = {
    S.TEXT: "自由文本", S.TOKEN: "标识/词", S.NUMBER: "数值", S.LIMIT: "限值(三写法)",
    S.BITSTRING: "位串(必须文本格式)", S.ENUM: "固定取值", S.PIN: "管脚名",
}


def _col_rows(sheet):
    """某 sheet 的消费列表格行：列名 / 类型 / 规则。"""
    rows = []
    for col in sorted(S.CONSUMED.get(sheet, ())):
        spec = S.spec_for(sheet, col)
        if spec:
            t = _TYPE_CN.get(spec["type"], spec["type"])
            extra = []
            if spec.get("enum"):
                extra.append("取值∈{" + ", ".join(spec["enum"]) + "}" + ("(不分大小写)" if spec.get("ci") else ""))
            if spec.get("slash_ok"):
                extra.append("可填 / 占位")
            rule = "；".join(extra) if extra else "严格解析：禁全角/首尾空格"
            sev = "ERROR"
        elif S.is_freetext(sheet, col):
            t, rule, sev = "自由文本", "允许中文；仅查隐形字符/首尾空格(WARN)", "WARN"
        else:
            t, rule, sev = "宽松", "全角/空格→WARN(母本已证明容忍)", "WARN"
        rows.append((col, t, rule, sev))
    return rows


def render_contract_html():
    sheets = ["VERSION", "FLOW", "pattern", "ADDR_MAP", "FLASH_EPR",
              "NM_pattern", "KP RELAY", "PIN DEC", "PIN DEC SINGEL"]
    parts = []
    for sh in sheets:
        if sh not in S.CONSUMED:
            continue
        body = "\n".join(
            f"<tr class={'e' if sev=='ERROR' else 'w'}><td>{_html.escape(c)}</td>"
            f"<td>{_html.escape(t)}</td><td>{_html.escape(r)}</td><td>{sev}</td></tr>"
            for c, t, r, sev in _col_rows(sh))
        parts.append(f"<h3>{_html.escape(sh)}</h3><table>"
                     f"<tr><th>列</th><th>类型</th><th>规则</th><th>违例级别</th></tr>{body}</table>")
    skip = []
    for sh, cols in S.CONSUMED.items():
        # 跳过列 = 该表里没被生成器消费的（这里反向不易枚举，给已知清单）
        pass
    skip_txt = ("ADDR_MAP: CPU Address / Contents / 备注；"
                "NM_pattern: No；PIN DEC: X[um] / Y[um] / Con")
    cols_html = "\n".join(parts)
    return f"""<!doctype html><meta charset=utf-8><title>母本输入契约</title>
<style>body{{font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:18px;font-size:13px;max-width:1100px}}
h2{{margin:14px 0 4px}}h3{{margin:16px 0 4px;color:#2d3a4a}}table{{border-collapse:collapse;width:100%;margin-bottom:8px}}
th,td{{border:1px solid #ccc;padding:3px 8px;text-align:left;vertical-align:top}}th{{background:#2d3a4a;color:#fff}}
tr.e td:last-child{{color:#c0392b;font-weight:bold}}tr.w td:last-child{{color:#b8860b}}
code{{background:#f0f0f0;padding:0 3px}}.box{{background:#f6f8fa;border:1px solid #ddd;padding:8px 12px;margin:8px 0}}</style>
<h2>母本输入契约（program.xlsx 填写规范）</h2>
<div class=box>
<b>校验工具</b>：<code>python tools/check_master.py</code>（独立跑，出 HTML 报告）；生成时也会自动 gate。<br>
<b>范围</b>：只校验<b>生成器用到的列</b>（用不到的列不查）。<br>
<b>级别</b>：<b style="color:#c0392b">ERROR</b>=会让生成崩/出错的程序，<b>拦住生成</b>；
<b style="color:#b8860b">WARN</b>=建议清理但不影响生成。<br>
<b>跳过的列</b>：{_html.escape(skip_txt)}
</div>

<h2>通用规则（A–E）</h2>
<table>
<tr><th>类</th><th>查什么</th><th>错例</th></tr>
<tr><td>A 字符卫生</td><td>全角/中文符号、首尾空格、全角空格、隐形字符</td><td><code>0.8％</code>(全角%)、<code>"Hsi_10M "</code>(尾空格)</td></tr>
<tr><td>B 结构</td><td>缺列、数据区中间空 item 行</td><td>FLOW 中间空行但其它列有值</td></tr>
<tr><td>C1 位串文本格式</td><td>位串列必须存成文本，不能数字格式</td><td>pattern.addr <code>0011110</code> 存成数字→丢前导0/崩</td></tr>
<tr><td>C2/C3 数值/限值</td><td>数值列须是数；limit 须 带%/带±/纯数字 三选一</td><td>limit <code>50</code>(漏%被当绝对值)、<code>0.8％</code></td></tr>
<tr><td>D 取值/一致</td><td>enum 取值合法；item 名拼写/大小写一致</td><td>bank=<code>Double</code>(应 double)、His/Hsi 不一致</td></tr>
<tr><td>E 位段重叠</td><td>同单元格/寄存器位段不重叠</td><td>vbl[3:0] 与 pre_pdac[4:0] 重叠</td></tr>
</table>

<h2>各 sheet 列规则</h2>
{cols_html}
"""
