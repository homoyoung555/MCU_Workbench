"""独立的 WGL SCAN 转换服务；不读取或修改 GUI Session / 生成器全局状态。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Iterable

from program_gen.core.wgl_parse import classify_pin_mode, parse_async_clocks, parse_timeplates, wft_display_name
from program_gen.platforms.chroma.project_files import process_pin_name
from program_gen.platforms.chroma.scan_writer import (
    _GROUP_TS as _CHROMA_TS,
    _fmt_period,
    _fmt_edge,
    _group_timeplates,
    _markern_line,
    _pin_mode_line,
    _rename_timesets,
)
from program_gen.platforms.s100.scan_writer import scan_ts_name
from tools.wgl2chroma.converter import convert_one


_CHROMA_HEADER = re.compile(r"(HEADER\n)(.*?)(\n\n)", re.DOTALL)
_CHROMA_VECTOR = re.compile(r"^(\s*)\*([^*]*)\*(.*)$")
_S100_HEAD = re.compile(r"(HEAD\[PIN_NAME\]:\r?\n)(.*?)(\r?\nEND_HEAD;)", re.DOTALL)
_S100_VECTOR = re.compile(r"^(\s*)((?:[A-Za-z_][A-Za-z0-9_]*:)?)([X01LHZ]+)(;.*)$")
_S100_TIMING = re.compile(r"TIMING_SET\s+(\w+)\s*;")


def label_options(marker, base):
    if any(value is not None and not isinstance(value, str) for value in (marker, base)):
        raise ValueError('Label 标记和名前缀必须是文本')
    marker, base = (marker or '').strip(), (base or '').strip()
    if not marker and not base:
        return None, None
    if not marker or not base:
        raise ValueError('请同时填写 Label 识别标记文本和名前缀，或同时留空')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', base):
        raise ValueError('Label 名前缀只能包含英文字母、数字和下划线，不能以数字开头')
    return marker, base


def read_wgl_pins(path: Path) -> list[str]:
    """Read signal order using the same parser as both emitters, without expanding vectors."""
    from tools.wgl2chroma.parser import WGLParser
    parser = WGLParser(Path(path).read_text(encoding='utf-8', errors='replace'))
    pattern = re.search(r'\bpattern\s+\w+\s*\(', parser.clean_text)
    parser._header_text = parser.clean_text[:pattern.start()] if pattern else parser.clean_text
    parser._parse_signal_section()
    pins = [_normal_pin(signal.name, set()) for signal in parser.design.signals]
    if not pins or any(not pin for pin in pins) or len({pin.casefold() for pin in pins}) != len(pins):
        raise ValueError(f'{Path(path).name}：管脚为空或规范化后重名，无法手动筛选')
    return pins


def manual_pin_orders(sources, selection):
    """Validate the batch selection and retain each file's own signal order."""
    if not isinstance(selection, list) or not selection or any(not isinstance(pin, str) or not pin.strip() for pin in selection):
        raise ValueError('请至少选择一个 WGL 管脚')
    wanted = {pin.casefold() for pin in selection}
    if len(wanted) != len(selection):
        raise ValueError('手动选择包含重复管脚')
    catalog = {source: read_wgl_pins(source) for source in sources}
    known = {pin.casefold() for pins in catalog.values() for pin in pins}
    if wanted - known:
        raise ValueError('所选管脚不在当前 WGL 中，请重新识别管脚')
    orders = {}
    for source, pins in catalog.items():
        orders[source] = tuple(pin for pin in pins if pin.casefold() in wanted)
        if not orders[source]:
            raise ValueError(f'{Path(source).name}：至少保留一个管脚')
    return orders


def configuration_fingerprint(workbook, cp: str | None = None) -> str:
    """返回只覆盖 PIN DEC 顺序和 NRST 别名的稳定配置指纹。"""
    if workbook is None:
        selected_cp, pin_rows, nrst_rows = None, [], []
    else:
        pin_frame, selected_cp = _pin_frame_and_cp(workbook, cp)
        pin_column = _pin_column_in_frame(pin_frame)
        pin_rows = [_value(value) for value in pin_frame[pin_column]]
        nrst_rows = _nrst_values(workbook, selected_cp, resolve_cp=False)
    payload = {"cp": selected_cp, "pinDec": pin_rows, "nrst": nrst_rows}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest().upper()


def convert_scan(
    input_paths: Iterable[str], output_dir: str, platforms: Iterable[str],
    workbook=None, progress: Callable[[str], None] | None = None, cp: str | None = None,
    manual_pins: list[str] | None = None,
    label_marker: str | None = None, label_base: str | None = None,
) -> dict:
    """将绝对 WGL 路径转换为独立的 Pattern、代码片段和配套时序文件。

    workbook 启用 PIN DEC 适配；manual_pins 在不使用 Excel 时按 WGL 原顺序筛选。
    两者均省略时保留全部管脚。返回路径均相对 ``output_dir``。
    """
    sources = _absolute_wgl_paths(input_paths)
    root = _absolute_output(output_dir)
    targets = _platforms(platforms)
    notify = progress or (lambda _message: None)
    label_marker, label_base = label_options(label_marker, label_base)
    if manual_pins is not None and workbook is not None:
        raise ValueError('手动管脚与 Excel 适配不能同时启用')
    manual_orders = manual_pin_orders(sources, manual_pins) if manual_pins is not None else None
    if workbook is None:
        selected_cp, pin_order, nrst = None, None, set()
    else:
        pin_frame, selected_cp = _pin_frame_and_cp(workbook, cp)
        pin_order = _pin_order_in_frame(pin_frame)
        nrst = set(_nrst_values(workbook, selected_cp, resolve_cp=False))
    used_names = set()
    source_specs = []
    for source in sources:
        stem = source.stem
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stem):
            raise ValueError(f"SCAN.LOGICAL_NAME: {source.name}")
        if stem.casefold() in used_names:
            raise ValueError(f"SCAN.DUPLICATE_BASENAME: {source.name}")
        used_names.add(stem.casefold())
        timeplates = parse_timeplates(source)
        if not timeplates:
            raise ValueError(f"SCAN.TIMEPLATE_MISSING: {source}")
        source_specs.append((source, stem, timeplates))
    s100_indices = {}
    next_s100_index = 1
    for source, _stem, timeplates in source_specs:
        indexes = {}
        for timeplate in timeplates:
            indexes[wft_display_name(str(timeplate["name"]))] = next_s100_index
            next_s100_index += 1
        s100_indices[source] = indexes
    files = []
    for source, stem, timeplates in source_specs:
        notify(f"转换 {source.name}")
        source_order = manual_orders[source] if manual_orders is not None else pin_order
        for platform in targets:
            directory = root / platform
            directory.mkdir(parents=True, exist_ok=True)
            pattern = directory / f"{stem}{'.pat' if platform == 'chroma' else '.sd'}"
            convert_one(str(source), str(pattern), target="chroma" if platform == "chroma" else "sd",
                        label_marker=label_marker, label_base=label_base)
            if platform == "chroma":
                selected = _rewrite_chroma(pattern, source_order, nrst)
                _rename_chroma_timesets(pattern, timeplates)
                timing = directory / f"{stem}.scan_timing.inc"
                timing.write_text(_chroma_timing(timeplates, selected, nrst), encoding="utf-8")
                code = directory / f"{stem}.scan.inc"
                code.write_text(_chroma_code(stem, _async_clocks(source, selected, nrst)), encoding="utf-8")
            else:
                indices = s100_indices[source]
                selected = _rewrite_s100(pattern, source_order, nrst, indices)
                timing = directory / f"{stem}.scan.timing"
                timing.write_text(_s100_timing(stem, timeplates, selected, nrst, indices), encoding="utf-8", newline="")
                code = directory / f"{stem}.scan.prg"
                code.write_text(_s100_code(stem, timeplates[0]["name"], _async_clocks(source, selected, nrst)), encoding="utf-8", newline="")
            files.extend(
                _file_record(root, platform, kind, path, source.name, stem)
                for kind, path in (("pattern", pattern), ("timing", timing), ("code", code))
            )
    return {
        "files": files,
        "mode": "manual-pins" if manual_pins is not None else "pin-dec-adapted" if workbook is not None else "full-pin",
        "manualPins": list(manual_pins) if manual_pins is not None else None,
        "labelMarker": label_marker, "labelBase": label_base,
        "configurationCp": selected_cp,
        "configurationFingerprint": configuration_fingerprint(workbook, selected_cp),
    }


def _absolute_wgl_paths(paths: Iterable[str]) -> tuple[Path, ...]:
    result = tuple(Path(path) for path in paths)
    if not result:
        raise ValueError("SCAN.INPUT_EMPTY")
    for path in result:
        if not path.is_absolute() or path.suffix.casefold() != ".wgl" or not path.is_file():
            raise ValueError(f"SCAN.INPUT_PATH: {path}")
    return tuple(path.resolve() for path in result)


def _absolute_output(output_dir: str) -> Path:
    root = Path(output_dir)
    if not root.is_absolute():
        raise ValueError(f"SCAN.OUTPUT_PATH: {output_dir}")
    return root.resolve()


def _platforms(platforms: Iterable[str]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(str(platform).strip().casefold() for platform in platforms))
    if not values or any(platform not in {"chroma", "s100"} for platform in values):
        raise ValueError(f"SCAN.PLATFORM: {values!r}")
    return values


def _file_record(root: Path, platform: str, kind: str, path: Path, source_name: str, logical_name: str) -> dict:
    return {"platform": platform, "kind": kind, "path": path.relative_to(root).as_posix(), "sourceName": source_name, "logicalName": logical_name}


def _pin_frame(workbook, cp: str | None = None):
    return _pin_frame_and_cp(workbook, cp)[0]


def _pin_frame_and_cp(workbook, cp: str | None = None):
    try:
        frame = workbook.dataframe("PIN DEC")
    except KeyError as error:
        raise ValueError("SCAN.PIN_DEC_MISSING") from error
    cp_column = _cp_column(frame)
    if cp_column is None:
        return frame, None
    selected = _configured_cp_in_frame(frame, cp)
    return frame[frame[cp_column].map(_value).str.casefold() == selected.casefold()], selected


def _pin_column(workbook, cp: str | None = None) -> str:
    return _pin_column_in_frame(_pin_frame(workbook, cp))


def _pin_column_in_frame(frame) -> str:
    for column in frame.columns:
        if str(column).strip().casefold() in {"e/c(pad name)", "pad name", "pin name"}:
            return column
    raise ValueError("SCAN.PIN_DEC_PIN_COLUMN_MISSING")


def _pin_order(workbook, cp: str | None = None) -> tuple[str, ...] | None:
    if workbook is None:
        return None
    return _pin_order_in_frame(_pin_frame(workbook, cp))


def _pin_order_in_frame(frame) -> tuple[str, ...]:
    column = _pin_column_in_frame(frame)
    order = []
    known = set()
    for value in frame[column]:
        name = _normal_pin(value, set())
        if name and name.casefold() not in known:
            known.add(name.casefold())
            order.append(name)
    if not order:
        raise ValueError("SCAN.PIN_DEC_EMPTY")
    return tuple(order)


def _nrst_values(workbook, cp: str | None = None, *, resolve_cp: bool = True) -> list[str]:
    if workbook is None:
        return []
    try:
        frame = workbook.dataframe("VERSION")
    except KeyError:
        return []
    if "NRST PIN" not in frame.columns:
        return []
    version_cp = _cp_column(frame, "CP num")
    selected = _configured_cp(workbook, cp) if resolve_cp else cp
    if version_cp is not None and selected:
        frame = frame[frame[version_cp].map(_value).str.casefold() == selected.casefold()]
    return [name for value in frame["NRST PIN"] if (name := _normal_pin(value, set()))]


def _configured_cp(workbook, cp: str | None) -> str | None:
    if workbook is None:
        return None
    frame = workbook.dataframe("PIN DEC")
    return _configured_cp_in_frame(frame, cp)


def _configured_cp_in_frame(frame, cp: str | None) -> str | None:
    column = _cp_column(frame)
    if column is None:
        return None
    cps = tuple(dict.fromkeys(value for value in frame[column].map(_value) if value))
    if cp is not None:
        requested = _value(cp)
        if not requested or requested.casefold() not in {value.casefold() for value in cps}:
            raise ValueError(f"SCAN.PIN_DEC_CP_UNKNOWN: {cp!r}")
        return next(value for value in cps if value.casefold() == requested.casefold())
    if len(cps) != 1:
        raise ValueError("SCAN.PIN_DEC_CP_REQUIRED")
    return cps[0]


def _cp_column(frame, preferred: str = "CP NO") -> str | None:
    candidates = (preferred, "CP NO", "CP num")
    labels = {str(column).strip().casefold(): column for column in frame.columns}
    return next((labels[name.casefold()] for name in candidates if name.casefold() in labels), None)


def _value(value) -> str:
    return "" if value is None or (isinstance(value, float) and value != value) else str(value).strip()


def _normal_pin(value, nrst: set[str]) -> str:
    raw = _value(value)
    if not raw:
        return ""
    name = process_pin_name(raw)
    if name is None:
        return ""
    if name == raw and raw.upper().startswith("PAD_"):
        name = raw[4:].replace("_", "")
    return "NRST" if name.casefold() in {item.casefold() for item in nrst} else name


def _selected_pins(original: list[str], order: tuple[str, ...] | None, nrst: set[str]) -> tuple[list[str], list[int]]:
    names = [_normal_pin(pin, nrst) for pin in original]
    if order is None:
        return names, list(range(len(names)))
    by_name = {name.casefold(): index for index, name in enumerate(names) if name}
    # Match PIN DEC and WGL with the same reset alias before selecting columns.
    canonical_order = dict.fromkeys(_normal_pin(name, nrst).casefold() for name in order)
    indexes = [by_name[name] for name in canonical_order if name in by_name]
    if not indexes:
        raise ValueError("SCAN.PIN_DEC_NO_WGL_PIN")
    return [names[index] for index in indexes], indexes


def _rewrite_chroma(path: Path, order: tuple[str, ...] | None, nrst: set[str]) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    match = _CHROMA_HEADER.search(text)
    if not match:
        raise ValueError("SCAN.CHROMA_HEADER_MISSING")
    original = [value.strip() for value in match.group(2).replace("\n", " ").rstrip(";").split(",") if value.strip()]
    pins, indexes = _selected_pins(original, order, nrst)
    text = text[:match.start(2)] + "  " + ", ".join(pins) + ";" + text[match.end(2):]
    rewritten = []
    for line in text.splitlines(keepends=True):
        end = "\n" if line.endswith("\n") else ""
        vector = _CHROMA_VECTOR.match(line[:-1] if end else line)
        if vector:
            prefix, values, suffix = vector.groups()
            if len(values) != len(original):
                raise ValueError("SCAN.CHROMA_VECTOR_WIDTH")
            line = prefix + "*" + "".join(values[index] for index in indexes) + "*" + suffix + end
        rewritten.append(line)
    path.write_text("".join(rewritten), encoding="utf-8")
    return tuple(pins)


def _rename_chroma_timesets(path: Path, timeplates) -> None:
    groups = _group_timeplates(timeplates)
    if len(groups) > len(_CHROMA_TS):
        raise ValueError(f"SCAN.CHROMA_TIMESET_LIMIT: {len(groups)} 组时序，TS8～TS15 最多支持 8 组")
    path.write_text(_rename_timesets(path.read_text(encoding="utf-8"), groups, _CHROMA_TS[:len(groups)]), encoding="utf-8")


def _rewrite_s100(path: Path, order: tuple[str, ...] | None, nrst: set[str], timesets) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    match = _S100_HEAD.search(text)
    if not match:
        raise ValueError("SCAN.S100_HEADER_MISSING")
    original = [value.strip().rstrip(",;") for value in match.group(2).splitlines() if value.strip()]
    pins, indexes = _selected_pins(original, order, nrst)
    text = text[:match.start(2)] + "\r\n".join("\t" + pin + ("," if index < len(pins) - 1 else ";") for index, pin in enumerate(pins)) + text[match.end(2):]
    rewritten = []
    for line in text.splitlines(keepends=True):
        end = "\n" if line.endswith("\n") else ""
        vector = _S100_VECTOR.match(line[:-1] if end else line)
        if vector:
            indent, tag, values, suffix = vector.groups()
            if len(values) != len(original):
                raise ValueError("SCAN.S100_VECTOR_WIDTH")
            suffix = _S100_TIMING.sub(lambda item: f"TIMING_SET G2_{timesets.get(item.group(1), item.group(1))};", suffix)
            line = indent + tag + "".join(values[index] for index in indexes) + suffix + end
        rewritten.append(line)
    path.write_text("".join(rewritten), encoding="utf-8", newline="")
    return tuple(pins)


def _time_pins(tp, selected: tuple[str, ...], nrst: set[str]):
    facts = {_normal_pin(pin, nrst).casefold(): (_normal_pin(pin, nrst), info) for pin, info in tp["pins"].items()}
    return [facts[pin.casefold()] for pin in selected if pin.casefold() in facts]


def _chroma_timing(timeplates, selected: tuple[str, ...], nrst: set[str]) -> str:
    groups = _group_timeplates(timeplates)
    if len(groups) > len(_CHROMA_TS):
        raise ValueError(f"SCAN.CHROMA_TIMESET_LIMIT: {len(groups)} 组时序，TS8～TS15 最多支持 8 组")
    lines = ["// Insert into the Chroma scan function before JUDGE_PAT."]
    for index, (tp, _names) in enumerate(groups):
        ts_name = _CHROMA_TS[index]
        ts_var = f"fsclk_scan{8 + index}"
        lines.extend((f"  TIME {ts_var} = {_fmt_period(tp['period_ns'])};//{ts_name}", f"  RATEN({ts_name}, {ts_var});"))
        timing_pins = _time_pins(tp, selected, nrst)
        live = [(pin, info) for pin, info in timing_pins if "input" in info]
        lines.extend(_markern_line(ts_name, pin, info, ts_var).rstrip() for pin, info in live)
        lines.extend(_chroma_output_markern(ts_name, pin, info, ts_var) for pin, info in timing_pins if "input" not in info and "output" in info)
        lines.extend(_pin_mode_line(pin, info).rstrip() for pin, info in live)
        lines.append("")
    return "\n".join(lines)


def _async_clocks(source: Path, selected: tuple[str, ...], nrst: set[str]) -> tuple[tuple[str, float], ...]:
    selected_names = {pin.casefold() for pin in selected}
    return tuple(
        (pin, frequency)
        for raw_pin, frequency in parse_async_clocks(str(source))
        if (pin := _normal_pin(raw_pin, nrst)) and pin.casefold() in selected_names
    )


def _chroma_code(stem: str, clocks: tuple[tuple[str, float], ...]) -> str:
    name = _identifier(stem)
    lines = [f"{name}()", "{"]
    for pin, frequency in clocks:
        half_period_ns = 1e9 / (2 * frequency)
        lines.extend((
            f"  PIN_MODE({pin},FCLK,EDGE,MASK,IO_ON,OFF);",
            f"  FRUN_CLK({pin},{2 * half_period_ns:.2f}nS,0nS,{half_period_ns:.2f}nS);",
            f"  FRUN_CLK_MODE({pin},1,0,ON);",
        ))
    if clocks:
        lines.append("")
    lines.append(f"  JUDGE_PAT({stem},__{name});")
    lines.extend(f"  FRUN_CLK_MODE({pin},1,0,OFF);" for pin, _frequency in clocks)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _chroma_output_markern(ts_name: str, pin: str, info, ts_var: str) -> str:
    edges = info["output"]
    q_index = next((index for index, (_fraction, code) in enumerate(edges) if code == "Q"), None)
    if q_index is None or q_index + 1 == len(edges):
        raise ValueError(f"SCAN.CHROMA_OUTPUT_STROBE: {pin}")
    strobe = _fmt_edge(edges[q_index][0], ts_var)
    end = _fmt_edge(edges[q_index + 1][0], ts_var)
    return f"  MARKERN({ts_name}, {pin}, 0ns, ,     ,   0ns,      ,   {strobe}, {end});"


def _s100_timing(stem: str, timeplates, selected: tuple[str, ...], nrst: set[str], timesets) -> str:
    lines = []
    for tp in timeplates:
        index = timesets[wft_display_name(str(tp["name"]))]
        period = float(tp["period_ns"])
        ts_name = scan_ts_name(stem, wft_display_name(str(tp["name"])))
        lines.extend((f"\t\t@@AC_SET_{index}", f"\t\t\t[NAME={ts_name}]", "\t\t\t[TS]", f"\t\t\t\tPERIOD    = {_number(period)};   //unit ns", f"\t\t\t\tIO_ALLPINS: {{DRV_RS={_number(period * .05)} }}", f"\t\t\t\t            {{DRV_FL={_number(period * .75)}}}", f"\t\t\t\t            {{STB_RS={_number(period * .5)}}}"))
        special = []
        for pin, info in _time_pins(tp, selected, nrst):
            edges = info.get("input", [])
            if len(edges) != 3:
                continue
            output = info.get("output", [])
            strobe = next((fraction for fraction, code in output if code == "Q"), .5)
            special.append((pin, edges[1][0] * period, edges[2][0] * period, strobe * period, classify_pin_mode(edges)))
        for pin, rise, fall, strobe, _mode in special:
            lines.extend((f"\t\t\t\t{pin}: {{DRV_RS={_number(rise)} }}", f"\t\t\t\t      {{DRV_FL={_number(fall)}}}", f"\t\t\t\t      {{STB_RS={_number(strobe)}}}"))
        for pin, info in _time_pins(tp, selected, nrst):
            if len(info.get("input", [])) == 3:
                continue
            strobe = next((fraction for fraction, code in info.get("output", []) if code == "Q"), None)
            if strobe is not None:
                lines.append(f"\t\t\t\t{pin}: {{STB_RS={_number(strobe * period)} }}")
        lines.extend(("\t\t\t[END_TS]", "\t\t\t[FMT]", "\t\t\t\tIO_ALLPINS: {DRV_FMT=NRZ}"))
        for pin, _rise, _fall, _strobe, mode in special:
            fmt = "RTO" if mode == "RO" else mode
            lines.append(f"\t\t\t\t{pin}: {{DRV_FMT={fmt}}}")
        lines.extend(("\t\t\t[END_FMT]", f"\t\t@@END_AC_SET_{index}", ""))
    lines.append("")
    return "\r\n".join(lines)


def _s100_code(stem: str, first_timeplate: str, clocks: tuple[tuple[str, float], ...]) -> str:
    ts_name = scan_ts_name(stem, wft_display_name(str(first_timeplate)))
    lines = [f"\tLOGIC_SET_FREE_RUN_CLOCK_PIN({pin},{int(round(frequency))});" for pin, frequency in clocks]
    if clocks:
        lines.append("")
    lines.append(f"\tRUN_PATTERN({stem}:START,{stem}:END,2,{ts_name});")
    lines.extend(f"\tLOGIC_SET_FREE_RUN_CLOCK_PIN(NULL,{int(round(frequency))});" for _pin, frequency in clocks)
    return "\r\n".join(lines) + "\r\n"


def _number(value: float) -> str:
    return "%g" % round(value, 3)


def _identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


__all__ = ["configuration_fingerprint", "convert_scan"]
