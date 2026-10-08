"""Read-only, current-definition preview through the native generation seam."""
from dataclasses import asdict

from gui.generation import _WORKSPACE_ROOT, available_targets
from program_gen.platform_program import compile_platform_program_facts, WorkspacePatternProducer
from program_gen.platform_program.native_target import build_native_definition_bodies
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.render_plan import TargetKey


def render_item_preview(workbook, compilation, row, platform, variant, scan_bindings=None):
    if not compilation.is_valid:
        return {'valid': False, 'text': '', 'diagnostics': [asdict(d) for d in compilation.diagnostics.errors]}
    definitions = [d for cp in compilation.plan.cp_plans.values() for d in cp.definitions if row in d.source_rows]
    if len(definitions) != 1:
        raise ValueError('该行尚未形成唯一测试项，请补齐item、type、mode及该项必需配置；表头或空行不显示代码')
    definition, = definitions
    target = next((t for t in available_targets(workbook, compilation)
                   if t['platform'] == platform and t['cp'] == definition.cp and t['variant'] == variant), None)
    if target is None:
        raise ValueError(f'{definition.cp}不适用于当前平台／版本，请切换预览平台或LAB／Production')
    key = TargetKey(platform, definition.cp, variant, target['name'])
    facts = compile_platform_program_facts(workbook, key)
    if platform == 'chroma':
        from program_gen.platforms.chroma.fbist_pattern_generator import generate_fbist_patterns
    else:
        from program_gen.platforms.s100.fbist_pattern_generator import generate_fbist_patterns
    # Test bodies consume FBIST write regions only; complete resources stay in full generation.
    producer = GeneratedPatternProducer(generate_fbist_patterns(compilation.pattern_compilation),
                                        fallback=WorkspacePatternProducer(_WORKSPACE_ROOT / 'input' / platform))
    bodies = build_native_definition_bodies(compilation, key, facts, producer, definition, scan_bindings=scan_bindings)
    raw = b'\r\n'.join(body.fragment.content for body in bodies)
    if platform == 's100':
        from program_gen.core.s100_indent import format_s100
        raw = format_s100(raw.decode('latin-1')).encode('latin-1')
    from gui.server import preview_text
    return {'valid': True, 'item': definition.item, 'kind': definition.typed_kind,
            'cp': definition.cp, 'rows': list(definition.source_rows),
            'recipe': list(definition.effective_recipe), 'target': key.identity,
            'diagnostics': [], **preview_text(raw)}
