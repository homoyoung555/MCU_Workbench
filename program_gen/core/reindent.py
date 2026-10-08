# 生成后对程序源文件做"行首缩进规整"：按花括号 / S100 的 @@ 块层级，
# 重新计算每行行首缩进。**只改行首空白，绝不触碰行内任何字节**——
# 因此对 DSL（对空白不敏感）零风险，也不会破坏注释里的 GBK 等非 UTF-8 字节。
#
# - S100 .prg：缩进单位 = 1 个 TAB；@@PLAN/@@MACRO/@@START_UP/@@BOOKING 为块开，
#   @@END_* 为块闭，与花括号层级叠加。
# - Chroma .pln：缩进单位 = 2 个空格；纯花括号层级。
#
# 字节安全：整文件按 latin-1 解码（每字节↔每字符一一对应）处理后再编回 latin-1，
# 行内内容逐字节保持原样。
import os

# 这些目录不是本生成器产物（用户参考/输入/缓存），一律跳过。
_SKIP_DIRS = {"code", "pat_temp", "fbist_pattern", "temp", "__pycache__", ".user", ".git"}


def _code_only(line):
    """剔除双引号字符串字面量与 // 注释，只留用于花括号计数的代码部分。"""
    out = []
    i, n = 0, len(line)
    in_str = False
    while i < n:
        c = line[i]
        if in_str:
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == '/' and i + 1 < n and line[i + 1] == '/':
            break  # 行内注释，余下不计
        out.append(c)
        i += 1
    return ''.join(out)


def reindent_text(text, unit, use_at_blocks):
    """按层级重排每行行首缩进。返回 (新文本, 收尾层级)。
    收尾层级非 0 说明花括号/块不闭合（可能源码本身有问题），调用方可据此告警。"""
    nl = '\r\n' if '\r\n' in text else '\n'   # 保留原换行风格（CRLF/LF）
    out = []
    depth = 0
    for raw in text.split(nl):
        line = raw.strip(' \t\r')        # 去掉首尾空格/制表符/回车
        if line == '':
            out.append('')
            continue
        code = _code_only(line).lstrip()
        if use_at_blocks and code.startswith('@@END'):
            depth = max(0, depth - 1)
            indent = depth
        elif use_at_blocks and code.startswith('@@'):
            indent = depth
            depth += 1
        else:
            opens = code.count('{')
            closes = code.count('}')
            lead = 0                     # 行首连续的 } 让本行先回退
            for ch in code:
                if ch == '}':
                    lead += 1
                elif ch in ' \t':
                    continue
                else:
                    break
            indent = max(0, depth - lead)
            depth = max(0, depth + opens - closes)
        out.append(unit * indent + line)
    return nl.join(out), depth


def reindent_file(path, unit, use_at_blocks):
    """重排单个文件。返回 (是否改动, 收尾层级)。按字节透传。"""
    data = open(path, 'rb').read()
    text = data.decode('latin-1')
    new_text, final_depth = reindent_text(text, unit, use_at_blocks)
    new = new_text.encode('latin-1')
    changed = new != data
    if changed:
        open(path, 'wb').write(new)
    return changed, final_depth


def reindent_tree(root, platform):
    """遍历 root 下本平台的程序源文件并规整缩进（跳过非产物目录）。
    返回改动文件数；收尾层级非 0 的文件打印告警。"""
    if platform == "s100":
        ext, unit, use_at = ".prg", "\t", True
    else:
        ext, unit, use_at = ".pln", "  ", False
    changed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(ext):
                p = os.path.join(dirpath, fn)
                did, depth = reindent_file(p, unit, use_at)
                changed += 1 if did else 0
                if depth != 0:
                    print("  [reindent] WARN 收尾层级=%d（括号/块不闭合）: %s" % (depth, p))
    return changed
