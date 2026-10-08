"""Resolve explicit external Pattern names without mutating compiled catalogs."""
from __future__ import annotations

from dataclasses import replace
from program_gen.core.pattern_links import validate_pattern_links


class PatternLinkNameResolver:
    """CP/platform-scoped original-to-source Pattern name lookup."""

    def __init__(self, records=()):
        self._names = {}
        for record in validate_pattern_links(list(records or ())):
            cp = record['cp'].casefold()
            original = record['original']
            pattern = record['pattern']
            platform = record['platform']
            for target in (('chroma', 's100') if platform == 'shared' else (platform,)):
                key = (cp, target, original.casefold())
                existing = self._names.get(key)
                if existing is not None and existing != pattern:
                    raise ValueError(f'Pattern Link 同CP/平台原名映射冲突：{original}')
                self._names[key] = pattern

    def resolve(self, cp, platform, original):
        value = str(original or '').strip()
        return self._names.get((str(cp).strip().casefold(), str(platform).strip().casefold(), value.casefold()), value)

    def names_for(self, cp, platform):
        prefix = (str(cp).strip().casefold(), str(platform).strip().casefold())
        return tuple((original, pattern) for (record_cp, record_platform, original), pattern in self._names.items()
                     if (record_cp, record_platform) == prefix)

    @property
    def is_empty(self):
        return not self._names


def project_specialized_plan(plan, platform, records=()):
    """Return one platform's immutable specialized-plan name projection.

    Every handled replacement is a declared typed Pattern field.  This avoids
    accidental rewrites of test labels, vector bodies, or other string facts.
    """
    resolver = records if isinstance(records, PatternLinkNameResolver) else PatternLinkNameResolver(records)
    cp = plan.cp
    kind = getattr(plan, 'typed_kind', '')
    if kind == 'ADC_TEST':
        phases = tuple(
            _project_adc_phase(phase, resolver, cp, platform)
            if getattr(phase.kind, 'value', phase.kind) == 'SWD_CAPTURE' else phase
            for phase in plan.phases
        )
        return replace(plan, phases=phases)
    if kind == 'DC_PARAMETRIC_TEST':
        return replace(plan, phases=tuple(
            replace(phase, config_pattern=resolver.resolve(cp, platform, phase.config_pattern))
            for phase in plan.phases
        ))
    if kind == 'DC_VIH_VIL' and hasattr(plan, 'config_pattern'):
        return replace(plan,
            config_pattern=resolver.resolve(cp, platform, plan.config_pattern),
            capture_patterns=tuple(resolver.resolve(cp, platform, name) for name in plan.capture_patterns),
        )
    if kind == 'FREQ_TEST':
        return replace(plan, cases=tuple(
            replace(case, config_pattern=resolver.resolve(cp, platform, case.config_pattern))
            if case.config_pattern else case for case in plan.cases
        ))
    if kind == 'OPA_TEST':
        return replace(plan,
            init_pattern=_resolve_optional(resolver, cp, platform, plan.init_pattern),
            cases=tuple(_replace_case(case, 'config_pattern', resolver, cp, platform) for case in plan.cases),
        )
    if kind == 'DAC_TEST':
        return replace(plan,
            init_pattern=_resolve_optional(resolver, cp, platform, plan.init_pattern),
            cases=tuple(_replace_case(case, 'code_pattern', resolver, cp, platform) for case in plan.cases),
            output_pattern_names=tuple(
                (original, pattern) for original, pattern in resolver.names_for(cp, platform)
                if original.casefold().startswith(f'{plan.product}_dac_'.casefold())
                and original.casefold().endswith('_test')
            ),
        )
    return plan


def _adc_pattern_pairs(phase):
    from program_gen.core.adc_test import adc_pattern_names
    names = dict(getattr(phase, 'pattern_names', ()))
    default_config, default_capture = adc_pattern_names(phase.adc_id)
    return (('config', names.get('config', default_config)), ('capture', names.get('capture', default_capture)))


def _project_adc_phase(phase, resolver, cp, platform):
    pairs = _adc_pattern_pairs(phase)
    projected = tuple((role, resolver.resolve(cp, platform, original)) for role, original in pairs)
    return replace(phase, pattern_names=projected) if projected != pairs else phase


def _resolve_optional(resolver, cp, platform, value):
    return resolver.resolve(cp, platform, value) if value else value


def _replace_case(case, field, resolver, cp, platform):
    value = getattr(case, field)
    return replace(case, **{field: _resolve_optional(resolver, cp, platform, value)}) if value else case


__all__ = ['PatternLinkNameResolver', 'project_specialized_plan']
