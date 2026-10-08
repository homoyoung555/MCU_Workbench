"""
单文件转换入口: WGL → Chroma3380P .pat  或  WGL → S100 .sd
"""

import os
from typing import Optional, Callable
from .parser import parse_wgl_file
from .emitter import PatEmitter
from .emitter_sd import SdEmitter


def convert_one(
    wgl_path: str,
    out_path: Optional[str] = None,
    dec_filename: Optional[str] = None,
    emit_ascii_art: bool = False,
    sticky_wft: bool = True,
    wft_continuation: Optional[str] = None,
    target: str = 'chroma',
    extra_col_name: Optional[str] = None,
    extra_col_value: str = '0',
    insert_gap_on_wft_change: bool = False,
    label_marker: Optional[str] = None,
    label_base: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """
    把一个 .wgl 文件转换成 Chroma .pat 或 S100 .sd 文件。

    参数:
        wgl_path: 输入 WGL 文件路径
        out_path: 输出文件路径; None 时 = 与 WGL 同目录同名 (.pat 或 .sd, 视 target)
        dec_filename: 仅 target='chroma' 用. .pat 中 SET_DEC_FILE 引用; None 时 = ./<basename>.dec
        emit_ascii_art: 是否输出竖排 pin 名注释 (chroma: SPM_PATTERN 内; sd: @@PATTERN_DEFINE 下)
        sticky_wft: True 时 timing 仅在 WFT 切换时输出 (只保留首次切换标志);
                    False 时每拍都输出 timing (仅对 chroma 有效; sd 始终 sticky)
        wft_continuation: 仅 target='chroma' 用. sticky 且未切换那一拍替代 ` * <wft>` 的内容
                    (None/'' = 省略; 如 ' *' = 原样插入)
        target: 'chroma' → Chroma3380P .pat (默认); 'sd' → S100 (YTEC) .sd
        progress: 进度回调

    返回:
        实际写出的文件路径
    """
    if progress is None:
        progress = lambda s: None
    if target not in ('chroma', 'sd'):
        raise ValueError(f"target 只能是 'chroma' 或 'sd', 收到 {target!r}")

    if not os.path.exists(wgl_path):
        raise FileNotFoundError(wgl_path)

    progress(f'解析 {os.path.basename(wgl_path)} ...')
    design = parse_wgl_file(wgl_path, label_marker=label_marker, label_base=label_base)

    n_vec = len(design.pattern.vectors) if design.pattern else 0
    n_pin = len(design.signals)
    n_chain = len(design.scanchains)
    progress(f'  pins={n_pin}, chains={n_chain}, vectors={n_vec}')

    # 决定 basename (用 WGL basename 去后缀)
    base = os.path.basename(wgl_path)
    for ext in ('.wgl', '.WGL', '.Wgl'):
        if base.endswith(ext):
            base = base[:-len(ext)]
            break

    ext_out = '.sd' if target == 'sd' else '.pat'

    # 决定输出路径
    if out_path is None:
        wgl_dir = os.path.dirname(os.path.abspath(wgl_path))
        out_path = os.path.join(wgl_dir, f'{base}{ext_out}')
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if target == 'sd':
        progress('生成 .sd ...')
        emitter = SdEmitter(
            design,
            pattern_name=base,
            emit_ascii_art=emit_ascii_art,
            sticky_wft=sticky_wft,
            extra_col_name=extra_col_name,
            extra_col_value=extra_col_value,
            insert_gap_on_wft_change=insert_gap_on_wft_change,
        )
        # .sd 用 CRLF (与样例一致), 故 newline='' 防止二次转换
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            emitter.emit_to(f)
    else:
        if dec_filename is None:
            dec_filename = f'./{base}.dec'
        progress('生成 .pat ...')
        emitter = PatEmitter(
            design,
            pattern_name=base,
            dec_filename=dec_filename,
            emit_ascii_art=emit_ascii_art,
            sticky_wft=sticky_wft,
            wft_continuation=wft_continuation,
            extra_col_name=extra_col_name,
            extra_col_value=extra_col_value,
            insert_gap_on_wft_change=insert_gap_on_wft_change,
        )
        with open(out_path, 'w', encoding='utf-8') as f:
            emitter.emit_to(f)

    progress(f'已写出 {out_path}')
    return out_path
