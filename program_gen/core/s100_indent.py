"""Indent generated S100 source, preserving all bytes after leading whitespace."""

import re


_LITERALS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\r\n]*|/\*.*?\*/', re.S)
_CONTROL = re.compile(r'(?:(?:else\s+)?if|for|while|switch)\s*\(.*\)$|else$', re.S)


def format_s100(text):
    raw = text.splitlines(keepends=True)
    masked = _LITERALS.sub(lambda m: re.sub(r'[^\r\n]', ' ', m[0]), text)
    code = [line.strip() for line in masked.splitlines()]
    extra = [0] * len(raw)

    def next_code(index):
        while index < len(code) and not code[index]:
            index += 1
        return index

    def statement_end(index):
        """Find a generated control body's end, including its optional else."""
        if index >= len(code):
            raise ValueError('S100.INDENT.CONTROL_BODY_MISSING')
        if _CONTROL.fullmatch(code[index]):
            end = statement_end(next_code(index + 1))
            following = next_code(end + 1)
            if re.match(r'(?:else\s+)?if\b', code[index]) and following < len(code) and re.match(r'else\b', code[following]):
                end = statement_end(following)
            return end
        braces = parens = 0
        for end in range(index, len(code)):
            for char in code[end]:
                braces += (char == '{') - (char == '}')
                parens += (char == '(') - (char == ')')
                if braces == parens == 0 and (char == ';' or (char == '}' and code[index].startswith('{'))):
                    return end
        raise ValueError('S100.INDENT.STATEMENT_UNCLOSED')

    for index, line in enumerate(code):
        if _CONTROL.fullmatch(line):
            child = next_code(index + 1)
            if child < len(code) and not code[child].startswith('{'):
                end = statement_end(child)
                for item in range(index + 1, end + 1):
                    extra[item] += 1

    depth = 0
    case_depths = set()
    condition = 0
    out = []
    for index, original in enumerate(raw):
        line = code[index]
        content = original.lstrip(' \t')
        if not content.strip():
            out.append(original)
            continue
        if line.startswith('@@END'):
            depth -= 1
            indent = depth
            condition = 0
        elif line.startswith('@@'):
            indent = depth
            depth += 1
        else:
            leading_closes = len(re.match(r'^(?:}\s*)*', line)[0].replace(' ', '').replace('\t', ''))
            indent = depth - leading_closes
            case_depths = {value for value in case_depths if value <= indent}
            is_case = bool(re.match(r'(?:case\b.*|default)\s*:', line))
            if is_case:
                case_depths.add(indent)
            indent += sum(value < indent or (value == indent and not is_case) for value in case_depths)
            depth += line.count('{') - line.count('}')
            if line == 'CONDITION':
                condition = 1
            elif condition and re.fullmatch(r'IF_\w+', line):
                condition = 2
                indent += 1
            elif condition == 2:
                indent += 2
        if depth < 0 or indent < 0:
            raise ValueError('S100.INDENT.BLOCK_UNDERFLOW')
        out.append('\t' * (indent + extra[index]) + content)
    if depth:
        raise ValueError('S100.INDENT.BLOCK_UNCLOSED')
    return ''.join(out)
