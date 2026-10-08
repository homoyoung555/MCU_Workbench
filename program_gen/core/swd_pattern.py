"""Explicit frozen tool resources (SWD/HEX) at the PatternProducer seam."""
from pathlib import Path
import re

from program_gen.render_plan import ResourceRequest
from program_gen.platform_program.pattern import PatternWriteRegion


class SwdPatternProducer:
    def __init__(self, bindings, fallback, *, platform='', cp=''):
        self.bindings, self.fallback = bindings, fallback
        self.platform, self.cp, self.resources = platform, cp, {}
        for binding in bindings:
            if binding['cp'] != cp:
                continue
            for name in binding['names'].get(platform, binding['names'].get('shared', [])):
                if platform not in binding['contents']:
                    raise ValueError('Pattern 关联缺少目标平台产物：' + name)
                old = self.resources.get(name)
                if old and old['identity'] != binding['identity']:
                    raise ValueError('SWD 同名资源关联冲突：' + name)
                self.resources[name] = binding

    def for_target(self, facts):
        fallback = self.fallback
        if hasattr(fallback, 'for_target'):
            fallback = fallback.for_target(facts)
        producer = SwdPatternProducer(self.bindings, fallback, platform=facts.platform, cp=facts.cp)
        for name, binding in producer.resources.items():
            if binding.get('sourceKind') != 'hex':
                continue
            text = producer._text(name)
            header = re.search(r'\bHEADER\s+([^;]+);' if facts.platform == 'chroma' else
                               r'HEAD\[PIN_NAME\]\s*:\s*([^;]+);', text)
            if not header:
                raise ValueError('HEX Pattern 缺少管脚声明：' + name)
            pins = {pin.strip() for pin in header[1].split(',')}
            missing = pins - {pin.name for pin in facts.pins}
            if missing:
                raise ValueError('HEX 管脚未在目标程序中定义：' + ', '.join(sorted(missing)))
        return producer

    def _text(self, name):
        binding = self.resources[name]
        text = binding['contents'][self.platform].decode('gb18030')
        # Only rename the declaration; vector content and labels stay untouched.
        if self.platform == 'chroma':
            text, count = re.subn(r'SPM_PATTERN\s*\(\s*' + re.escape(binding['pattern']) + r'\s*\)',
                                 'SPM_PATTERN(' + name + ')', text)
            if count != 1:
                raise ValueError('SWD Pattern 声明与来源名称不一致：' + name)
        elif binding.get('sourceKind') == 'hex' and binding.get('timingOrigin') == 'chroma':
            # Program timing contracts differ: Chroma TS5/TS6 are erase/program,
            # while S100 G1_4/G1_5 carry those meanings (G1_6 is VIH).
            mapping = {'G1_1': 'G1_1', 'G1_2': 'G1_2', 'G1_5': 'G1_4', 'G1_6': 'G1_5'}
            def timing(match):
                if match[1] not in mapping:
                    raise ValueError('HEX 时序未有程序定义对应：' + match[1])
                return 'TIMING_SET ' + mapping[match[1]] + ';'
            text = re.sub(r'\bTIMING_SET\s+(G\d+_\d+)\s*;', timing, text)
        return text

    def produce(self, requirement):
        name = Path(requirement.relative_path).stem
        if name not in self.resources:
            return self.fallback.produce(requirement)
        binding = self.resources[name]
        if binding.get('sourceKind') == 'hex' and requirement.purpose != 'Firmware download pattern':
            raise ValueError('HEX 产物不能替代非固件下载资源：' + name)
        return ResourceRequest(logical_identity=requirement.logical_identity,
                               relative_path=requirement.relative_path,
                               content=self._text(name).encode('gb18030'),
                               spec_identity=requirement.spec_identity,
                               source_identity=binding.get('sourceKind', 'swd') + ':' + binding['identity'], purpose=requirement.purpose)

    def timing_sets(self, requirements):
        linked = [r for r in requirements if Path(r.relative_path).stem in self.resources]
        names = {name for r in linked for name in re.findall(r'\bTIMING_SET\s+(G\d+_\d+)\s*;', self._text(Path(r.relative_path).stem))}
        remaining = [r for r in requirements if Path(r.relative_path).stem not in self.resources]
        if remaining:
            names.update(self.fallback.timing_sets(remaining))
        return tuple(sorted(names))

    def write_region(self, pattern_name):
        if pattern_name not in self.resources:
            return self.fallback.write_region(pattern_name)
        text = self._text(pattern_name)
        suffix = '_data' if self.platform == 'chroma' else '_data_st'
        labels = re.findall(r'^\s*([A-Za-z_][A-Za-z0-9_]*' + suffix + r')\s*:', text, re.M)
        if len(labels) != 1:
            raise ValueError('SWD 产物不含调用方要求的动态写入标签：' + pattern_name)
        start = labels[0]
        if self.platform == 'chroma':
            return PatternWriteRegion(start, start, start)
        end = start[:-2] + 'sp'
        if not re.search(r'^\s*' + re.escape(end) + r'\s*:', text, re.M):
            raise ValueError('SWD 产物缺少动态写入结束标签：' + pattern_name)
        return PatternWriteRegion(start[:-3], start, end)
