"""
WGL 构造覆盖诊断 (阶段0, 非侵入式)。

目的
----
当前 parser 对不认识的 WGL 语法是 **静默丢弃** 的 (例如别的 EDA 工具产生的
`vector(0, 0pS, name)` 三元组写法、`call sub();`、第二个 pattern 块……),
转换得到的 .pat/.sd 看起来正常,实际可能少了周期或数据错位,且无任何提示。

本模块在 **不参与、不改变转换路径** 的前提下扫描一份 WGL,报告:
  1. 文件里出现了哪些 WGL 保留构造,其中哪些是当前 parser 不消费的;
  2. vector / scan 子句里,有多少条是当前匹配规则 **抓不到** 的 (=会被丢弃);
  3. 是否存在多个 pattern 块 (当前只处理第一个)。

设计原则: 只读、零副作用。本模块的存在不影响 convert_one 的任何输出。
复用 parser 的真实正则 (_CLAUSE_FULL_RE 等),保证"漏匹配检测"与实际解析行为始终一致。

用法
----
    from wgl2chroma.diagnostics import diagnose_file
    report = diagnose_file('foo.wgl')
    print(report.format())          # 人读文本
    report.has_warnings             # bool, 适合 CI / 批量门禁
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from .parser import strip_brace_comments, WGLParser


# parser 当前 *会消费* 的头部 block 关键字
_SUPPORTED_HEADER = {'signal', 'scancell', 'scanchain', 'timeplate', 'scanstate'}
# scancell 是"被有意忽略"(非缺口); 其余为真正解析
_INTENTIONALLY_IGNORED = {'scancell'}

# pattern 体内当前 *会消费* 的子句
_SUPPORTED_PATTERN = {'vector', 'scan', 'loop', 'repeat'}

# spec 定义、但当前 *不* 实现的构造 → 出现即应告警。
# (键 = WGL 保留字; 值 = 说明 + spec 出处提示)
_KNOWN_UNSUPPORTED = {
    'subroutine': '子程序定义 (spec: subroutine <name> ... end)',
    'call':       '子程序调用 (spec: call <name>( );) —— 会被整条丢弃',
    'skip':       '偏移/跳拍 (spec: Offset ::= skip Time;)',
    'macro':      '宏定义 / 符号展开',
    'format':     'ATE format 段',
    'formats':    'ATE formats 程序块',
    'equation':   '嵌入方程表达式',
    'variable':   '变量定义',
    'group':      '信号组定义 (scanstate 引用其名但不解析组内容)',
    'mode':       'mode 段',
    'register':   'register 段',
    'include':    '文件包含 (不会拉取被包含文件)',
    'annotation': '注释 / 元数据段',
}


@dataclass
class Finding:
    level: str          # 'warn' | 'info'
    code: str           # 机器可读标签
    message: str        # 人读说明
    sample: str = ''    # 可选: 命中片段示例


@dataclass
class DiagnosisReport:
    path: str = ''
    findings: List[Finding] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def has_warnings(self) -> bool:
        return any(f.level == 'warn' for f in self.findings)

    def add(self, level, code, message, sample=''):
        self.findings.append(Finding(level, code, message, sample))

    def format(self) -> str:
        lines = []
        lines.append(f'WGL 覆盖诊断: {self.path or "<text>"}')
        lines.append('-' * 60)
        if self.stats:
            s = self.stats
            lines.append(
                f"vector/scan 子句: 总计 {s.get('clauses_total', 0)}, "
                f"已匹配 {s.get('clauses_matched', 0)}, "
                f"漏匹配 {s.get('clauses_unmatched', 0)}")
            lines.append(f"pattern 块数量: {s.get('pattern_blocks', 0)}")
        warns = [f for f in self.findings if f.level == 'warn']
        infos = [f for f in self.findings if f.level == 'info']
        if warns:
            lines.append('')
            lines.append(f'⚠ 告警 ({len(warns)}) —— 可能导致周期丢失或数据错位:')
            for f in warns:
                lines.append(f'  [{f.code}] {f.message}')
                if f.sample:
                    lines.append(f'        例: {f.sample}')
        if infos:
            lines.append('')
            lines.append(f'信息 ({len(infos)}):')
            for f in infos:
                lines.append(f'  [{f.code}] {f.message}')
        if not warns:
            lines.append('')
            lines.append('✓ 未发现当前 parser 无法消费的构造。')
        return '\n'.join(lines)


# 子句头计数: 匹配 (可选 repeat 前缀) 后紧跟的 vector( / scan(
_CLAUSE_HEAD_RE = re.compile(r'\b(vector|scan)\s*\(')
_PATTERN_HEAD_RE = re.compile(r'\bpattern\s+\w+\s*\(')
_WORD_RE = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')


def diagnose_text(text: str, path: str = '') -> DiagnosisReport:
    """对一段 WGL 文本做覆盖诊断 (只读)。"""
    rep = DiagnosisReport(path=path)
    clean = strip_brace_comments(text)

    # --- pattern 段切分 (与 parser.parse 的切法一致) ---
    pat_heads = list(_PATTERN_HEAD_RE.finditer(clean))
    rep.stats['pattern_blocks'] = len(pat_heads)
    if len(pat_heads) > 1:
        rep.add('warn', 'MULTI_PATTERN',
                f'发现 {len(pat_heads)} 个 pattern 块,但当前只处理第 1 个; '
                f'其余块的向量会被错误并入或丢失。')

    header_text = clean[:pat_heads[0].start()] if pat_heads else clean
    body_text = clean[pat_heads[0].start():] if pat_heads else ''

    # --- 头部: 出现了哪些不支持的构造 ---
    _scan_unsupported_keywords(header_text, rep, region='头部')

    # --- pattern 体: vector/scan 漏匹配检测 (核心) ---
    total = len(_CLAUSE_HEAD_RE.findall(body_text))
    matched = sum(1 for _ in WGLParser._CLAUSE_FULL_RE.finditer(body_text))
    unmatched = total - matched
    rep.stats['clauses_total'] = total
    rep.stats['clauses_matched'] = matched
    rep.stats['clauses_unmatched'] = unmatched
    if unmatched > 0:
        sample = _first_unmatched_clause(body_text)
        rep.add('warn', 'CLAUSE_UNMATCHED',
                f'{unmatched} 条 vector/scan 子句不符合当前匹配规则 '
                f'(只认 `vector(+, 名字):=[...]`),会被静默丢弃。'
                f'常见原因: 三元组写法 vector(周期号,时间,timeplate)、'
                f'无 timeplate 的 vector(+)、用圆括号 ( ) 包数据。',
                sample=sample)

    # --- pattern 体: call / skip / 命名 loop / feedback 等 ---
    _scan_unsupported_keywords(body_text, rep, region='pattern 体')
    _scan_pattern_specifics(body_text, rep)

    return rep


def _scan_unsupported_keywords(region_text: str, rep: DiagnosisReport, region: str):
    """报告 region 内出现的、当前不支持的保留构造。"""
    seen = set()
    for m in _WORD_RE.finditer(region_text):
        w = m.group(0)
        if w in _KNOWN_UNSUPPORTED and w not in seen:
            seen.add(w)
            rep.add('warn', f'UNSUPPORTED_{w.upper()}',
                    f'[{region}] 出现 `{w}`: {_KNOWN_UNSUPPORTED[w]}')


def _scan_pattern_specifics(body_text: str, rep: DiagnosisReport):
    # feedback 扫描方向 (parser 只认 input/output)
    if re.search(r'\bfeedback\s*\[', body_text):
        rep.add('warn', 'SCANDIR_FEEDBACK',
                'pattern 体出现 feedback[chain:state] 扫描方向,当前只处理 input/output。')
    # 命名 loop: loop 后跟的不是纯数字
    for m in re.finditer(r'\bloop\b\s+(\S+)', body_text):
        tok = m.group(1)
        if not tok.isdigit():
            rep.add('warn', 'NAMED_LOOP',
                    f'出现命名/非数字 loop (`loop {tok} ...`),'
                    f'当前 loop 展开要求 `loop <整数>`,该块不会展开。')
            break


def _first_unmatched_clause(body_text: str, max_len: int = 90) -> str:
    """找出第一条 *未* 被 _CLAUSE_FULL_RE 命中的 vector/scan 子句头,作示例。"""
    matched_spans = [m.start() for m in WGLParser._CLAUSE_FULL_RE.finditer(body_text)]
    matched_starts = set(matched_spans)
    for m in _CLAUSE_HEAD_RE.finditer(body_text):
        # 该子句头是否对应某个完整匹配的起点? (完整匹配可能含 repeat 前缀,
        # 故用"附近无完整匹配起点"近似: 取该头到分号的片段试单独匹配)
        seg_end = body_text.find(';', m.start())
        seg = body_text[m.start(): seg_end + 1 if seg_end != -1 else m.start() + max_len]
        if not WGLParser._CLAUSE_FULL_RE.search(seg):
            one = ' '.join(seg.split())
            return one[:max_len] + ('…' if len(one) > max_len else '')
    return ''


def diagnose_file(path: str) -> DiagnosisReport:
    """从文件路径做覆盖诊断 (只读, 不写任何文件)。"""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    return diagnose_text(text, path=os.path.basename(path))


def _cli(argv=None):
    import sys
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print('用法: python -m wgl2chroma.diagnostics <file.wgl> [更多文件...]')
        return 2
    any_warn = False
    for p in argv:
        rep = diagnose_file(p)
        print(rep.format())
        print()
        any_warn = any_warn or rep.has_warnings
    return 1 if any_warn else 0


if __name__ == '__main__':
    import sys
    sys.exit(_cli())
