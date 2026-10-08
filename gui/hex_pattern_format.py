"""Translate the bounded PAT syntax emitted by the supplied HEX engines to SD."""
import re


def chroma_to_sd(text):
    header = re.search(r'\bHEADER\s+(.*?)\bSPM_PATTERN\([^)]*\)\s*\{', text, re.S)
    if not header:
        raise ValueError('PAT 缺少有效的管脚头和 Pattern 定义')
    pins = header[1].strip().rstrip(';').strip()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*', pins):
        raise ValueError('PAT 管脚头无法转换')
    output = ['HEAD[PIN_NAME]:', pins+';', 'END_HEAD;', '@@PATTERN_DEFINE']
    timing_map, count, stopped, closed = {}, 0, False, False
    pending_label = ''
    labels = set()
    for number, line in enumerate(text[header.end():].splitlines(), 1):
        code, marker, comment = line.partition('//')
        code = code.strip()
        if not code:
            if marker:
                output.append('//'+comment)
            continue
        if code == '}' and stopped and not closed:
            closed = True
            continue
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*:', code) and not stopped:
            if pending_label or code.upper() in labels or code.upper() in ('START:', 'END:'):
                raise ValueError('PAT 标签重复或与SD起止标签冲突')
            pending_label = code
            labels.add(code.upper())
            continue
        match = re.fullmatch(r'\*([01HLXZ]+)\*\s*(.*?)\s*;', code)
        if not match or stopped or closed:
            raise ValueError(f'PAT 数据段第{number}行含未支持的语法，不能静默丢弃')
        vector, tail = match.groups()
        if len(vector) != len(pins.split(',')):
            raise ValueError('PAT 管脚数与向量宽度不一致')
        ts = re.fullmatch(r'TS(\d+)', tail)
        rpt = re.fullmatch(r'RPT\s+(\d+)', tail)
        if tail and not ts and not rpt and tail != 'STOP':
            raise ValueError(f'PAT 数据段第{number}行指令不能转换：{tail}')
        if rpt and int(rpt[1]) < 1:
            raise ValueError('PAT 重复次数超出已支持范围')
        stopped = tail == 'STOP'
        if pending_label and (stopped or count == 0):
            raise ValueError('PAT 起止向量含额外标签，不能静默丢弃')
        prefix = 'END:' if stopped else 'START:' if count == 0 else pending_label or '      '
        pending_label = ''
        converted = prefix + vector + ';'
        if ts:
            target = 'G1_'+ts[1]
            timing_map['TS'+ts[1]] = target
            converted += 'TIMING_SET '+target+';'
        repeats = int(rpt[1]) if rpt else 1
        if repeats > 1:
            converted += 'RPT '+str(min(repeats, 65535))+';'
        if marker:
            converted += '//'+comment
        output.append(converted)
        repeats -= min(repeats, 65535)
        while repeats:
            chunk = min(repeats, 65535)
            output.append('      '+vector+';'+('RPT '+str(chunk)+';' if chunk > 1 else ''))
            repeats -= chunk
        count += 1
    if count < 2 or not stopped or not closed:
        raise ValueError('PAT 缺少有效起止向量')
    output.append('@@END_PATTERN_DEFINE')
    return '\n'.join(output)+'\n', timing_map
