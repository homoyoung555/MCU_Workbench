"""Vendor stages with complete logs and conservative, evidence-based diagnostics."""
import codecs
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache

from gui.paths import WORKSPACE_ROOT
from tools import chroma_compiler as chroma, s100_compiler as s100


COMPILER_MODES = {
    'chroma': {'all': '全部 · DEC + PAT + PLN', 'dec': '仅 DEC', 'pat': '仅 PAT', 'pln': '仅 PLN'},
    's100': {'all': '全部', 'prj_prg': 'PRJ + PRG', 'prg': '仅 PRG', 'pat_tim': 'PAT + TIM', 'pat': '仅 PAT'},
}


@lru_cache(maxsize=8)
def _bcc_identity(path, modified, size):
    raw = Path(path).read_bytes()
    if 'Synaptics'.encode('utf-16le') in raw:
        return 'bcc32.exe 版本标识为 Synaptics，和预期 Borland 编译器不符'
    if not any(marker in raw for marker in (b'Borland C++', 'Borland C/C++ Compiler'.encode('utf-16le'))):
        return 'bcc32.exe 未识别为预期的 Borland 编译器'
    return ''


def tool_status():
    craft = next((p for p in (os.environ.get('CRAFT_HOME'), 'C:/CRAFT',
                              str(WORKSPACE_ROOT / 'toolchains/chroma'))
                  if p and (Path(p) / 'bin/plncmp.exe').is_file()), '')
    yt = os.environ.get('S100_HOME') or str(WORKSPACE_ROOT / 'toolchains/s100')
    bcc = Path(s100._tool_dirs(yt)[1]) / 'Bin/bcc32.exe'
    reason = ''
    if bcc.is_file():
        stat = bcc.stat()
        reason = _bcc_identity(str(bcc), stat.st_mtime_ns, stat.st_size)
    return {'chroma': {'path': craft, 'available': bool(craft) and all(
                (Path(craft) / 'bin' / name).is_file() for name in ('plncmp.exe', 'patcmp.exe', 'deccmp.exe'))},
            's100': {'path': yt, 'available': Path(s100._pre(yt)).is_file() and bcc.is_file() and not reason,
                     'reason': reason}}


def diagnostics(text):
    found, seen = [], set()
    pending_location = None
    for raw in text.splitlines():
        message = raw.strip().replace('\x00', '')
        context = re.search(r'File:\[([^\]]+)\]\s+Line:\[(\d+)\]', message)
        if context:
            pending_location = (context.group(1), int(context.group(2)))
            continue
        if not message or message in seen or re.match(r'^(Errors|Warnings|Critical warnings)\s*:', message, re.I):
            continue
        if not re.search(r'error|warning|failed|unknown|undefined|cannot|can not|not found|unresolved|错误|警告|超时', message, re.I):
            continue
        seen.add(message)
        location = re.search(r'([\w:./\\ -]+\.(?:prg|pln|pat|dec|tim|h|c|cpp))\s*(?:\(\s*|:\s*|\s+)(\d+)\s*\)?\s*:', message, re.I)
        file_line = (location.group(1).strip(), int(location.group(2))) if location else (
            pending_location if message.startswith('Message:') and pending_location else (None, None))
        pending_location = None
        cause, advice = '日志未提供足够信息确认根因', '检查原始日志中此处之前的首条错误及对应源码；不要仅据汇总行修改程序。'
        lower = message.lower()
        if 'bcc32.exe' in lower and ('Borland' in message or 'Synaptics' in message):
            cause, advice = '配置的 C 编译器身份与预期不一致', '请提供正确的 S100 / BCB6 工具链，并通过 S100_HOME 指定根目录后重启工作台；不要修改程序来绕过该错误。'
        elif '编译器不完整' in message:
            cause, advice = '本地编译工具链缺失或配置错误', '检查工具链目录；Chroma 可通过 CRAFT_HOME 指定，S100 可通过 S100_HOME 指定，配置后重启工作台。'
        elif 'c compiler not found' in lower:
            cause, advice = 'S100 未找到可调用的 C 编译器', '检查 BCB6 编译器位置、启动参数及编译环境；修复工具链后重新编译。'
        elif any(x in lower for x in ('cannot open', 'can not open', 'no such file', 'not found', 'fail to open')):
            cause, advice = '日志报告文件或依赖不可访问', '核对所选文件夹是否包含依赖，检查日志中的文件路径、相对目录及工具链配置。'
        elif any(x in lower for x in ('unknown', 'undefined', 'undeclared', 'unresolved')):
            cause, advice = '符号、指令或链接定义未被识别', '核对该位置的名称、声明及包含文件；确认当前平台和工具链版本支持该指令。'
        elif 'measure accuracy' in lower:
            cause, advice = '设定的测量限值低于编译器所述精度范围', '核对所用 PPMU 量程、测量精度和规格限值；结合机台规格确认，不自动放宽限值。'
        elif '超时' in message:
            cause, advice = '编译进程超过等待时限', '检查最后输出的阶段、工具链安装与授权环境；确认没有等待交互窗口后重试。'
        elif re.search(r'syntax|parse error|error C\d+', message, re.I):
            cause, advice = '编译器报告语法或类型错误', '从首条错误位置检查表达式、分号、括号和类型；后续错误可能由该处引起。'
        found.append({'severity': 'warning' if re.search(r'warning|警告', message, re.I) else 'error',
                      'file': file_line[0], 'line': file_line[1],
                      'message': message, 'cause': cause, 'advice': advice})
    return found


def run_command(command, cwd, env, log, timeout=600):
    """Only terminate the process tree started for this task, never by executable name."""
    with Path(log).open('a', encoding='utf-8') as output:
        output.write('\n$ ' + subprocess.list2cmdline([str(v) for v in command]) + '\n')
    timed_out = False
    with tempfile.TemporaryFile() as raw:
        process = subprocess.Popen([str(v) for v in command], cwd=cwd, env=env,
                                   stdout=raw, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if process.poll() is None:
                process.kill()
            process.wait()
        raw.seek(0)
        decoder = codecs.getincrementaldecoder('gb18030')(errors='replace')
        parts = []
        with Path(log).open('a', encoding='utf-8') as output:
            for block in iter(lambda: raw.read(256 * 1024), b''):
                decoded = decoder.decode(block)
                output.write(decoded)
                parts.append(decoded)
            tail = decoder.decode(b'', final=True)
            output.write(tail)
            parts.append(tail)
            if timed_out:
                output.write('\n编译超时，已终止本任务进程树\n')
                parts.append('\n编译超时，已终止本任务进程树\n')
    return (124 if timed_out else process.returncode), ''.join(parts)


def compile_program(folder, platform, entry, log, progress, mode='all'):
    folder, log = Path(folder), Path(log)
    if mode not in COMPILER_MODES.get(platform, {}):
        raise ValueError('当前平台不支持此编译模式')
    stages, messages = [], []
    tool = tool_status()[platform]
    if not tool['available']:
        raise ValueError(tool.get('reason') or f'{platform} 编译器不完整或未配置：{tool["path"]}')
    home = Path(tool['path'])

    def stage(label, command, cwd, env, verify):
        progress(label)
        rc, output = run_command(command, cwd, env, log)
        errors = chroma._scan(output) if platform == 'chroma' else [d['message'] for d in diagnostics(output) if d['severity'] == 'error']
        valid, reason = verify(output)
        ok = rc == 0 and not errors and valid
        if not ok and not errors:
            errors = [reason or f'编译器退出码 {rc}，未确认成功']
        stages.append({'stage': label, 'ok': ok, 'returncode': rc, 'errors': errors})
        messages.append(output)
        if errors:
            with log.open('a', encoding='utf-8') as stream:
                stream.write('\n阶段判定：' + '; '.join(errors) + '\n')
        return ok

    def made(path):
        return path.is_file() and path.stat().st_size > 0

    if platform == 'chroma':
        env = chroma.build_env(str(home))
        pat = next((p for p in folder.iterdir() if p.is_dir() and p.name.lower() == 'pat'), None)
        if pat is None:
            raise ValueError('Chroma 程序缺少 pat 文件夹')
        decs = sorted(p for p in pat.iterdir() if p.suffix.lower() == '.dec')
        if mode in ('all', 'dec') and not decs:
            raise ValueError('Chroma 程序缺少 DEC 文件')
        if mode in ('all', 'pat') and not any(p.suffix.lower() == '.pat' for p in pat.iterdir()):
            raise ValueError('Chroma 程序缺少 PAT 文件')
        if mode == 'pat' and not any(made(p) for p in pat.glob('*.pinmap')):
            raise ValueError('仅 PAT 需要 DEC 产物，请先编译 DEC 或全部编译')
        if mode == 'pln' and not made(pat / 'pin_pat.ppo'):
            raise ValueError('仅 PLN 需要 PAT 产物，请先全部编译或依次编译 DEC、PAT')
        suffixes = set()
        if mode in ('all', 'dec'):
            suffixes.update(('.pinmap', '.pgmap'))
        if mode in ('all', 'pat'):
            suffixes.update(('.pdt', '.ppo'))
        for path in pat.iterdir():
            if path.is_file() and path.suffix.lower() in suffixes:
                path.unlink()
        if mode in ('all', 'pln'):
            (folder / Path(entry).with_suffix('.pin')).unlink(missing_ok=True)
        if mode in ('all', 'dec'):
            for dec in decs:
                if not stage('DEC · ' + dec.name, [home / 'bin/deccmp.exe', dec.name], pat, env,
                             lambda _, dec=dec: (any(made(p) for p in pat.glob(dec.stem + '_*.pinmap')), '没有生成本次 pinmap')):
                    break
        if mode in ('all', 'pat') and all(s['ok'] for s in stages):
            chroma.generate_makefile(str(folder), str(pat))
            stage('PAT · 编译及链接', [home / 'bin/patcmp.exe', '-o.\\PAT\\pin_pat', '-f', 'makefile_pat0.lst'], folder, env,
                  lambda _: (made(pat / 'pin_pat.ppo'), '没有生成本次 pin_pat.ppo'))
        if mode in ('all', 'pln') and all(s['ok'] for s in stages):
            stage('PLN · 完整编译', [home / 'bin/plncmp.exe', entry], folder, env,
                  lambda out: (bool(chroma._PLN_OK_RE.search(out)) and made(folder / Path(entry).with_suffix('.pin')),
                               '缺少完整编译成功标记或本次 PIN 产物'))
    else:
        program = folder / 'program'
        stem = Path(entry).stem
        if mode == 'all':
            for name in s100._INTERMEDIATE:
                path = folder / name
                if path.is_dir():
                    shutil.rmtree(path)
        else:
            required = [folder / 'pattern_ddr2', folder / 'timing_ddr2']
            if mode != 'prj_prg':
                required.append(program / (stem + '.pj'))
            if mode == 'pat':
                required.append(program / (stem + '.pn'))
            if any(not p.exists() for p in required):
                raise ValueError('局部编译缺少工程依赖，请先对本任务全部编译，或上传包含完整编译产物的程序文件夹')
        before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for name in s100._INTERMEDIATE
                  for p in (folder / name).rglob('*') if p.is_file()}
        def fresh(path):
            return made(path) and before.get(path) != (path.stat().st_mtime_ns, path.stat().st_size)
        def s100_output(out):
            if mode in ('all', 'prj_prg'):
                valid = fresh(program / (stem + '.gsw'))
            elif mode == 'prg':
                valid = fresh(program / (stem + '.PG')) and fresh(program / (stem + '.dll'))
            else:
                valid = any(fresh(p) for p in (folder / 'pattern_ddr2').glob('*.lmr'))
                if mode == 'pat_tim':
                    valid = valid and any(fresh(p) for p in (folder / 'timing_ddr2').glob('*.ts2'))
            return (s100._scan(out)[0] == 0 and valid, '缺少零错误汇总或本模式新生成的产物')
        args = {'all': ['-A', '-bcb6', '-de'], 'prj_prg': ['-pp', '-bcb6', '-de'],
                'prg': ['-g', '-bcb6', '-de'], 'pat_tim': ['-pn', '-de'],
                'pat': ['-de', '-pno', '-fprogram/' + stem + '.pn']}[mode]
        with s100.compiler_environment(home) as (compiler_home, env):
            stage('S100 · ' + COMPILER_MODES['s100'][mode], [s100._pre(compiler_home), folder / entry, *args],
                  folder, env, s100_output)
    findings = diagnostics('\n'.join(messages))
    for item in stages:
        for error in item['errors']:
            if not any(d['message'] == error for d in findings):
                findings.append({'severity': 'error', 'file': None, 'line': None, 'message': error,
                                 'cause': '本阶段未满足完整编译条件', 'advice': '查看该阶段完整日志，先解决最早出现的错误，再重新编译。'})
    return {'ok': bool(stages) and all(s['ok'] for s in stages), 'stages': stages,
            'diagnostics': findings, 'outputAvailable': False}
