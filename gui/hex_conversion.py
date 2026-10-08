"""Validated Intel HEX input and isolated, versioned legacy download engines."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from gui.paths import RESOURCE_ROOT

ENGINE_ROOT = RESOURCE_ROOT/'tools/hex_to_pattern'


def profiles():
    return json.loads((ENGINE_ROOT/'profiles.json').read_text(encoding='utf-8'))


def profile_by_id(identity):
    profile = next((p for p in profiles() if p['id'] == identity), None)
    if profile is None:
        raise ValueError('请选择已提供的芯片下载版本')
    if not profile['enabled']:
        raise ValueError(profile['reason'])
    return profile


def configured_profile(identity, options):
    profile = profile_by_id(identity)
    pins = options.get('pins', profile['pins'])
    if not isinstance(pins, list) or len(pins) != len(profile['pins']) or any(
            not isinstance(pin, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', pin.strip()) for pin in pins):
        raise ValueError('管脚必须逐列填写有效名称（字母或下划线开头，最多64字符）')
    pins = [pin.strip() for pin in pins]
    if len({pin.upper() for pin in pins}) != len(pins):
        raise ValueError('管脚名称不能重复')
    verify = options.get('verify', profile['verify'])
    if not isinstance(verify, bool):
        raise ValueError('校验开关必须是布尔值')
    if verify and not profile['verify']:
        raise ValueError('该原版本未启用数据读回校验，不能开启')
    target = options.get('outputPlatform', profile['platform'])
    allowed = ('chroma', 's100', 'both') if profile['platform'] == 'chroma' else ('s100',)
    if target not in allowed:
        raise ValueError('该版本不支持所选输出格式')
    return dict(profile, sourcePins=profile['pins'], pins=pins, verify=verify, outputPlatform=target)


def parse_hex(raw):
    try:
        text = raw.decode('ascii')
    except UnicodeError:
        raise ValueError('HEX 必须是 Intel HEX ASCII 文本') from None
    memory, base, ended, entry = {}, 0, False, None
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if ended:
            raise ValueError(f'第 {number} 行：结束记录后仍有数据')
        if not re.fullmatch(r':[0-9a-fA-F]+', line) or len(line) % 2 != 1:
            raise ValueError(f'第 {number} 行：HEX 记录格式错误')
        record = bytes.fromhex(line[1:])
        if len(record) < 5 or len(record) != record[0] + 5:
            raise ValueError(f'第 {number} 行：HEX 长度错误')
        if sum(record) & 255:
            raise ValueError(f'第 {number} 行：HEX 校验和错误')
        address, kind, data = int.from_bytes(record[1:3], 'big'), record[3], record[4:-1]
        if kind == 0:
            for offset, byte in enumerate(data):
                absolute = base + address + offset
                if absolute > 0xFFFFFFFF:
                    raise ValueError('HEX 地址溢出')
                if absolute in memory:
                    raise ValueError(f'第 {number} 行：地址 0x{absolute:08X} 重叠')
                memory[absolute] = byte
            if len(memory) > 1024 * 1024:
                raise ValueError('当前转换最多接受 1 MiB 有效数据')
        elif kind == 1 and not data and not address:
            ended = True
        elif kind in (2, 4) and len(data) == 2 and not address:
            base = int.from_bytes(data, 'big') << (4 if kind == 2 else 16)
        elif kind in (3, 5) and len(data) == 4 and not address:
            entry = int.from_bytes(data, 'big')
        else:
            raise ValueError(f'第 {number} 行：不支持或无效的 HEX 记录类型 {kind:02X}')
    if not ended:
        raise ValueError('HEX 缺少结束记录')
    if not memory:
        raise ValueError('HEX 没有有效数据')
    ordered = sorted(memory)
    segments = []
    for address in ordered:
        if not segments or segments[-1]['end'] != address:
            segments.append({'start': address, 'end': address + 1})
        else:
            segments[-1]['end'] += 1
    return {'memory': memory, 'summary': {'bytes': len(memory), 'segments': segments, 'entryAddress': entry,
                                         'sha256': hashlib.sha256(raw).hexdigest()}}


def _record(address, kind, data):
    raw = bytes([len(data), address >> 8, address & 255, kind]) + bytes(data)
    return ':' + (raw + bytes([-sum(raw) & 255])).hex().upper()


def prepare_hex(image, profile):
    segments = image['summary']['segments']
    if len(segments) != 1:
        raise ValueError('HEX 地址不连续；原下载版本不能安全表达空洞，请提供连续区域的 HEX')
    start, end = segments[0]['start'], segments[0]['end']
    sram = profile['mode'] == 'swd_sram'
    if start < 0x20000:
        source_base = 0
    elif 0x08000000 <= start < end <= 0x08020000:
        source_base = 0x08000000
    elif sram and 0x20000000 <= start < end <= 0x20020000:
        source_base = 0x20000000
    elif ('boot' in profile.get('label', '').lower() or 'btl' in profile.get('source', '').lower()) and 0x1FFF0000 <= start < end <= 0x20000000:
        source_base = 0x1FFF0000
    else:
        raise ValueError('HEX 地址范围不适用于所选下载版本，请核对型号和目标区域')
    offset = start - source_base
    page = profile.get('pageSize') or (4 if sram else 256)
    if offset % (4 if sram else page):
        raise ValueError(f'起始地址必须按 {4 if sram else page} 字节对齐，原版本仅在边界设置地址')
    data = bytes(image['memory'][i] for i in range(start, end))
    padding = (-len(data)) % (4 if sram else 16)
    data += bytes([0 if sram else 255]) * padding
    # Conservative gate: audited legacy readback routines do not generally retain
    # extended addresses. Never silently wrap the high address to another region.
    limit = min(profile.get('maxAddress') or 65536, 65536)
    if offset + len(data) > limit:
        raise ValueError(f'超出该原版本已核对的地址范围 0x{limit:X}；不能截断高位地址')
    lines = [_record(offset+i, 0, data[i:i+16]) for i in range(0, len(data), 16)]
    # Several original converters flush the partial page on type 05, not type 01.
    lines += [_record(0, 5, [0, 0, 0, 0]), _record(0, 1, [])]
    target_base = 0x20000000 if sram else 0x08000000 if profile['mode'] == 'swd_flash' else 0
    summary = {'sourceStart': start, 'sourceEnd': end, 'sourceBase': source_base,
               'targetStart': target_base + offset, 'targetEnd': target_base + offset + len(data),
               'dataBytes': len(data)-padding, 'paddingBytes': padding, 'paddingByte': 0 if sram else 255,
               'verify': profile['verify'], 'erase': profile.get('erase'), 'pins': profile['pins'] if 'pins' in profile else []}
    return ('\n'.join(lines) + '\n').encode('ascii'), summary


def convert_hex(raw, profile, output, name, progress=None):
    notify = progress or (lambda message: None)
    normalized, summary = prepare_hex(parse_hex(raw), profile)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    normalized_path = output.parent/'normalized.hex'
    normalized_path.write_bytes(normalized)
    worker = hashlib.sha256(profile['source'].encode('utf-8')).hexdigest()[:20] + '.exe'
    executable = ENGINE_ROOT/'workers'/worker
    if not executable.is_file():
        raise ValueError('当前安装包缺少该芯片转换内核，请更新完整工作台')
    manifest = json.loads((ENGINE_ROOT/'workers/manifest.json').read_text(encoding='utf-8'))
    expected = next((item['sha256'] for item in manifest if item['worker'] == worker), None)
    if hashlib.sha256(executable.read_bytes()).hexdigest() != expected:
        raise ValueError('转换内核完整性检查失败，请恢复安装包')
    pattern = re.sub(r'[^A-Za-z0-9_]', '_', Path(name).stem)
    if not pattern or not re.match(r'[A-Za-z_]', pattern):
        pattern = 'hex_' + pattern
    notify(f"{profile['chip']} · {profile['label']} · {profile['platform']}")
    notify(f"有效数据 {summary['dataBytes']} 字节；尾部补齐 {summary['paddingBytes']} 字节")
    notify('数据读回校验：' + ('开启' if profile['verify'] else '关闭'))
    run = subprocess.run([str(executable), str(normalized_path), str(output), pattern, str(profile['verify']).lower()],
                         capture_output=True, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        raise ValueError('原转换内核失败：' + (run.stderr or run.stdout).decode('mbcs', errors='replace')[:2000])
    paths = sorted(output.glob('*.pat' if profile['platform'] == 'chroma' else '*.sd'))
    if len(paths) != 1 or paths[0].stat().st_size == 0:
        raise ValueError('原转换内核没有生成有效 Pattern')
    # Validate the generated header and every vector before offering a download.
    text = paths[0].read_text(encoding='utf-8-sig')
    if profile['platform'] == 'chroma':
        header = re.search(r'HEADER\s+(.*?)SPM_PATTERN', text, re.S)
        vectors = re.findall(r'^\s*\*([^*]+)\*', text, re.M)
    else:
        header = re.search(r'HEAD\[PIN_NAME\]:\s*(.*?)END_HEAD;', text, re.S)
        vectors = re.findall(r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*:)?([01XLHZ]+)\s*;', text, re.M)
    if not header or not vectors:
        raise ValueError('输出缺少管脚定义或向量')
    original_pins = [pin.strip() for pin in header.group(1).replace(';', '').split(',') if pin.strip()]
    if original_pins != profile.get('sourcePins', profile['pins']):
        raise ValueError('原转换输出管脚与版本定义不一致')
    if original_pins != profile['pins']:
        text = text[:header.start(1)] + ','.join(profile['pins']) + ';\n' + text[header.end(1):]
        paths[0].write_text(text, encoding='utf-8', newline='')
    width = len([pin for pin in header.group(1).replace(';', '').split(',') if pin.strip()])
    if any(len(vector) != width for vector in vectors):
        raise ValueError('原转换输出向量宽度与管脚不一致')
    summary['vectorRows'] = len(vectors)
    summary['outputPins'] = list(profile['pins'])
    target = profile.get('outputPlatform', profile['platform'])
    summary['outputPlatform'] = target
    if profile['platform'] == 'chroma' and target in ('s100', 'both'):
        from gui.hex_pattern_format import chroma_to_sd
        sd, summary['timingMap'] = chroma_to_sd(text)
        sd_path = paths[0].with_suffix('.sd')
        sd_path.write_text(sd, encoding='utf-8', newline='')
        paths = paths + [sd_path] if target == 'both' else [sd_path]
        summary['timingNotice'] = 'TSn 对应 S100 G1_n；周期与边沿需在 S100 工程中配置为与原时序相同。'
        notify(summary['timingNotice'])
    notify(f'生成 {paths[0].name}，{len(vectors)} 行向量；未执行机台下载')
    return {'files': [{'name': p.name, 'size': p.stat().st_size} for p in paths], 'summary': summary}
