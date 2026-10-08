"""Review-only native program generation for the local GUI.

The caller supplies the already-read workbook and compilation plus a
parent-created run directory.  This module writes only beneath the external
workspace ``outputs/gui_runs`` review area and never invokes the publisher.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Callable

from program_gen.native_target_renderer import NativeTargetRenderer
from program_gen.orchestrator import (
    GenerationRequest,
    GenerationTarget,
    TargetRenderContext,
)
from program_gen.request_factory import GenerationRoots, build_generation_request
from program_gen.platform_program import WorkspacePatternProducer, build_native_target_plan, compile_platform_program_facts
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.platform_program.facts import compile_pin_map_facts
from program_gen.core.fbist_pattern_plan import compile_ordinary_fbist_pattern_plan, compile_pump_fbist_pattern_plan
from program_gen.core.flash_compare_product import compile_required_flash_compare_plans, compile_flash_compare_facts
from program_gen.core.flash_compare_plan import FlashCompareCompileError
from program_gen.core.flash_compare_renderer import render_flash_compare_plans
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.flash_label_plan import compile_flash_label_plan
from program_gen.core.flash_label_renderer import render_flash_label_plan
from program_gen.pin_dec import compile_pin_map_generation_plan, generate_pin_dec, generate_s100_prj_resources
from program_gen.render_plan import ArtifactMaterializer, ArtifactPlan, RenderPlan, TargetKey


_SOURCE_ROOT = Path(__file__).resolve().parents[1]
from gui.paths import WORKSPACE_ROOT
_WORKSPACE_ROOT = WORKSPACE_ROOT
_RUN_PARENT = _WORKSPACE_ROOT / "outputs" / "gui_runs"


def available_targets(workbook, compilation) -> list[dict]:
    """List the concrete targets available from the supplied public models."""
    request = _request(workbook, compilation, _RUN_PARENT / "catalog")
    return [_target_description(target.key) for target in request.targets]


def _pin_keys(workbook):
    try:
        values = workbook.dataframe('VERSION')['CP num']
    except KeyError:
        return ()
    cps = dict.fromkeys(str(value).strip().upper() for value in values
                        if re.fullmatch(r'CP[1-9][0-9]*', str(value).strip(), re.I))
    return tuple(TargetKey(platform, cp, variant, f'PIN_RESOURCES_{cp}')
                 for cp in cps
                 for platform in ('chroma', 's100') for variant in ('lab', 'production'))


def available_pin_targets(workbook, compilation=None) -> list[dict]:
    # Pin generation is independent of complete-program platform restrictions.
    return [_target_description(key) for key in _pin_keys(workbook)]


def _fbist_keys():
    # Ordinary vectors are shared across CP and lab/production pin maps.
    return tuple(TargetKey(platform, 'shared', 'resources', 'FBIST_RESOURCES')
                 for platform in ('chroma', 's100'))


def available_fbist_targets() -> list[dict]:
    return [_target_description(key) for key in _fbist_keys()]


def _pump_keys():
    return tuple(TargetKey(platform, 'shared', 'resources', 'PUMP_RESOURCES')
                 for platform in ('chroma', 's100'))


def available_pump_targets() -> list[dict]:
    return [_target_description(key) for key in _pump_keys()]


def check_pump_targets(workbook, target_ids):
    if not isinstance(target_ids, list):
        raise ValueError('请先选择PUMP汇总平台')
    keys = _select_by_id({key.identity.casefold(): key for key in _pump_keys()}, target_ids)
    diagnostics = []
    for key in keys:
        try:
            RenderPlan.from_artifacts(key, _fbist_artifacts(workbook, key, pump=True))
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            row = re.search(r'(?:pattern|FLOW) row (\d+)', message)
            source = 'VERSION' if 'VERSION' in message else 'FLOW' if 'FLOW' in message else 'pattern'
            diagnostics.append({'severity': 'ERROR', 'code': 'GUI.PUMP.CHECK',
                                'message': f'{key.platform}：{message}',
                                'provenance': {'sheet': source, 'coordinate': f'row {row[1]}' if row else ''},
                                'remediation': '核对FLOW的item/PUMP，以及对应trim dac/pump dac动态字段、地址与标签；还需VERSION引脚和必要的FB MAP。'})
    return diagnostics


def _flash_keys():
    return tuple(TargetKey(platform, 'shared', 'resources', 'FLASH_COMPARE_RESOURCES')
                 for platform in ('chroma', 's100'))


def available_flash_targets() -> list[dict]:
    return [_target_description(key) for key in _flash_keys()]


def _flash_label_keys():
    return tuple(TargetKey(platform, 'shared', 'resources', 'FLASH_LABEL_RESOURCES')
                 for platform in ('chroma', 's100'))


def available_flash_label_targets() -> list[dict]:
    return [_target_description(key) for key in _flash_label_keys()]


def _flash_label_artifacts(workbook, key):
    facts = compile_flash_compare_facts(workbook)
    catalog = compile_addr_map_catalog(workbook.dataframe('ADDR_MAP'))
    plan = compile_flash_label_plan(catalog, facts)
    result = render_flash_label_plan(plan, key.platform)
    return tuple(ArtifactPlan(a.relative_path, a.content, 'RESOURCE', ('gui:flash_labels', a.source_identity))
                 for a in result.artifacts)


def check_flash_label_targets(workbook, target_ids):
    if not isinstance(target_ids, list):
        raise ValueError('请先选择Flash页／UID平台')
    keys = _select_by_id({key.identity.casefold(): key for key in _flash_label_keys()}, target_ids)
    diagnostics = []
    for key in keys:
        try:
            RenderPlan.from_artifacts(key, _flash_label_artifacts(workbook, key))
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            version_column = re.search(r'(?:missing column|column has no value): (?:CLK PIN|SWD PIN|bank|program bit|read bit)$', message)
            source = ('VERSION' if 'VERSION' in message or version_column else
                      'FLASH_EPR' if isinstance(error, FlashCompareCompileError) else 'ADDR_MAP')
            row = re.search(r'\brow (\d+)|第\s*(\d+)\s*行', message)
            diagnostics.append({'severity': 'ERROR', 'code': 'GUI.FLASH_LABEL.CHECK',
                                'message': f'{key.platform}：{message}',
                                'provenance': {'sheet': source, 'coordinate': f'row {row[1] or row[2]}' if row else ''},
                                'remediation': '补齐Flash硬件配置、必要的FB MAP字段和ADDR_MAP完整页映像（含uid页），检查页字数与标签；不检查FLOW或NM_pattern。'})
    return diagnostics


def _flash_artifacts(workbook, key):
    compilation = compile_required_flash_compare_plans(workbook).require_complete()
    result = render_flash_compare_plans(compilation.plans, key.platform)
    if not result.artifacts:
        raise ValueError('NM_pattern 中没有可输出的Flash擦写/比较配置')
    return tuple(ArtifactPlan(a.relative_path, a.content, 'RESOURCE', ('gui:flash', a.source_identity))
                 for a in result.artifacts)


def check_flash_targets(workbook, target_ids):
    if not isinstance(target_ids, list):
        raise ValueError('请先选择Flash擦写/比较平台')
    keys = _select_by_id({key.identity.casefold(): key for key in _flash_keys()}, target_ids)
    diagnostics = []
    for key in keys:
        try:
            RenderPlan.from_artifacts(key, _flash_artifacts(workbook, key))
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            # Column errors from the canonical _first helper omit their sheet name.
            version_column = re.search(r'(?:missing column|column has no value): (?:CLK PIN|SWD PIN|bank|program bit|read bit)$', message)
            source = ('NM_pattern' if 'NM_pattern' in message else 'VERSION' if 'VERSION' in message or version_column
                      else 'FLASH_EPR')
            row = re.search(r'\brow (\d+)', message)
            diagnostics.append({'severity': 'ERROR', 'code': 'GUI.FLASH.CHECK',
                                'message': f'{key.platform}：{message}',
                                'provenance': {'sheet': source, 'coordinate': f'row {row[1]}' if row else ''},
                                'remediation': '补齐NM_pattern、Flash硬件配置和必要的FB MAP字段后重新检查；不检查FLOW或普通FBIST。'})
    return diagnostics


def _fbist_artifacts(workbook, key, *, pump=False):
    from program_gen.platforms.chroma.fbist_pattern_generator import generate_fbist_patterns as chroma
    from program_gen.platforms.s100.fbist_pattern_generator import generate_fbist_patterns as s100
    plan = (compile_pump_fbist_pattern_plan if pump else compile_ordinary_fbist_pattern_plan)(workbook)
    result = (chroma if key.platform == 'chroma' else s100)(plan)
    if not result.artifacts:
        raise ValueError('pattern 中没有可输出的普通FBIST配置；PUMP汇总不属于本范围')
    return tuple(ArtifactPlan(a.relative_path, a.content, 'RESOURCE', ('gui:pump' if pump else 'gui:fbist', a.source_identity))
                 for a in result.artifacts)


def check_fbist_targets(workbook, target_ids):
    if not isinstance(target_ids, list):
        raise ValueError('请先选择普通FBIST平台')
    keys = _select_by_id({key.identity.casefold(): key for key in _fbist_keys()}, target_ids)
    diagnostics = []
    for key in keys:
        try:
            RenderPlan.from_artifacts(key, _fbist_artifacts(workbook, key))
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            row = re.search(r'pattern row (\d+)', message)
            source = 'VERSION' if 'VERSION' in message else 'pattern'
            diagnostics.append({'severity': 'ERROR', 'code': 'GUI.FBIST.CHECK',
                                'message': f'{key.platform}：{message}',
                                'provenance': {'sheet': source, 'coordinate': f'row {row[1]}' if row else ''},
                                'remediation': '补齐普通FBIST的引脚、地址和字段配置后重新检查；省略地址或位段时核对FB MAP。'})
    return diagnostics


def _pin_artifact(workbook, key):
    plan = compile_pin_map_generation_plan(compile_pin_map_facts(workbook, key))
    content = generate_pin_dec(plan) if key.platform == 'chroma' else generate_s100_prj_resources(plan)
    filename = 'pin.dec' if key.platform == 'chroma' else 'pin_resources.prj'
    return ArtifactPlan(filename, content, 'RESOURCE', ('gui:pin',))


def check_pin_targets(workbook, target_ids):
    if not isinstance(target_ids, list):
        raise ValueError('请先选择要检查的Pin目标')
    keys = _select_by_id({key.identity.casefold(): key for key in _pin_keys(workbook)}, target_ids)
    diagnostics = []
    for key in keys:
        try:
            _pin_artifact(workbook, key)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            source = ('VERSION' if 'VERSION' in message or any(n in message for n in ('NRST PIN','SWD PIN','CLK PIN')) else
                      'IOMUX' if 'IOMUX' in message else 'KP RELAY' if 'KP_RELAY' in message or 'KP RELAY' in message else
                      'PIN DEC SINGEL' if key.variant == 'lab' else 'PIN DEC')
            diagnostics.append({'severity': 'ERROR', 'code': 'GUI.PIN.CHECK',
                                'message': f'{key.platform} / {key.cp} / {key.variant}：{message}',
                                'provenance': {'sheet': source, 'coordinate': ''},
                                'remediation': '修正此Pin目标所需配置后，重新检查Pin；其他测试项不参与本次检查。'})
    return diagnostics


def _resource_plan(workbook, compilation, key, scope, scan_bindings=None, swd_bindings=None):
    if scope == 'pin':
        artifacts = (_pin_artifact(workbook, key),)
    elif scope in ('fbist', 'pump'):
        artifacts = _fbist_artifacts(workbook, key, pump=scope == 'pump')
    elif scope == 'flash':
        artifacts = _flash_artifacts(workbook, key)
    elif scope == 'flash_labels':
        artifacts = _flash_label_artifacts(workbook, key)
    else:
        facts = compile_platform_program_facts(workbook, key)
        producer = GeneratedPatternProducer.from_compilation(
            compilation, key.platform,
            fallback=WorkspacePatternProducer(_WORKSPACE_ROOT / 'input' / key.platform))
        if swd_bindings:
            from program_gen.core.swd_pattern import SwdPatternProducer
            producer = SwdPatternProducer(swd_bindings, producer)
        full_plan = build_native_target_plan(compilation, key, facts, producer, scan_bindings=scan_bindings)
        artifacts = tuple(a for a in full_plan.artifacts
                          if a.kind == 'RESOURCE' and Path(a.relative_path).suffix.lower() in {'.pat', '.sd', '.sr'})
    if not artifacts:
        raise ValueError('当前目标没有可输出的资源')
    return RenderPlan.from_artifacts(key, artifacts)


def _render_resources(workbook, compilation, key, staging, scope, scan_bindings=None, swd_bindings=None):
    plan = _resource_plan(workbook, compilation, key, scope, scan_bindings=scan_bindings, swd_bindings=swd_bindings)
    staging.mkdir(parents=True, exist_ok=False)
    return ArtifactMaterializer().materialize(plan, staging)


def preview_plan(workbook, compilation, target_id, scope='program', scan_bindings=None, swd_bindings=None) -> RenderPlan:
    """Render one selected target in memory, without a run or output files."""
    if scope in ('pin', 'fbist', 'flash', 'flash_labels', 'pump'):
        choices = _pin_keys(workbook) if scope == 'pin' else {'fbist': _fbist_keys, 'flash': _flash_keys, 'flash_labels': _flash_label_keys, 'pump': _pump_keys}[scope]()
        key, = _select_by_id({key.identity.casefold(): key for key in choices}, [target_id])
    elif scope in ('program', 'patterns'):
        request = _request(workbook, compilation, _RUN_PARENT / 'preview')
        target, = _select_targets(request, [target_id])
        key = target.key
        if scope == 'program':
            renderer = NativeTargetRenderer(workbook, {
                platform: _WORKSPACE_ROOT / 'input' / platform for platform in ('chroma', 's100')}, scan_bindings=scan_bindings, swd_bindings=swd_bindings)
            context = TargetRenderContext(request.identity, request.compilation_identity, key, target.staging_directory)
            return renderer.build_plan(compilation, context)
    else:
        raise ValueError('GUI.GENERATION.SCOPE_INVALID')
    return _resource_plan(workbook, compilation, key, scope, scan_bindings=scan_bindings, swd_bindings=swd_bindings)


def generate_review(
    workbook,
    compilation,
    target_ids: list[str],
    run_dir: Path,
    validate: bool = False,
    progress: Callable[[dict], None] | None = None,
    scope: str = 'program',
    scan_bindings=None,
    swd_bindings=None,
) -> dict:
    """Materialize selected native targets in an isolated review directory.

    Vendor validation is intentionally unsupported here: this review path does
    not invoke a compiler or publish files, and it reports that fact explicitly.
    """
    if scope not in ('program', 'patterns', 'pin', 'fbist', 'flash', 'flash_labels', 'pump'):
        raise ValueError('GUI.GENERATION.SCOPE_INVALID')
    run_dir = _validated_run_dir(run_dir)
    review_root = run_dir / "review"
    if scope in ('pin', 'fbist', 'flash', 'flash_labels', 'pump'):
        choices = _pin_keys(workbook) if scope == 'pin' else {'fbist': _fbist_keys, 'flash': _flash_keys, 'flash_labels': _flash_label_keys, 'pump': _pump_keys}[scope]()
        keys = _select_by_id({key.identity.casefold(): key for key in choices}, target_ids)
        targets = tuple((key, review_root / key.platform / key.cp / key.variant) for key in keys)
    else:
        request = _request(workbook, compilation, review_root)
        selected = _select_targets(request, target_ids)
        selected_request = GenerationRequest(request.compilation_identity, request.output_root, selected)
        targets = tuple((target.key, target.staging_directory) for target in selected)
    renderer = NativeTargetRenderer(
        workbook,
        {
            "chroma": _WORKSPACE_ROOT / "input" / "chroma",
            "s100": _WORKSPACE_ROOT / "input" / "s100",
        },
        scan_bindings=scan_bindings,
        swd_bindings=swd_bindings,
    ) if scope == 'program' else None
    outputs: list[dict] = []
    warnings: list[str] = []
    failures = False

    _progress(progress, {"event": "started", "target_count": len(targets)})
    for ordinal, (key, staging) in enumerate(targets, start=1):
        _progress(progress, {
            "event": "rendering",
            "ordinal": ordinal,
            "target": _target_description(key),
        })
        try:
            if scope == 'program':
                context = TargetRenderContext(selected_request.identity, selected_request.compilation_identity, key, staging)
                artifacts = renderer(compilation, context)
            else:
                artifacts = _render_resources(workbook, compilation, key, staging, scope, scan_bindings=scan_bindings, swd_bindings=swd_bindings)
        except Exception as error:
            failures = True
            message = f"{type(error).__name__}: {error}"
            outputs.append({
                **_target_description(key),
                "path": str(staging),
                "file_count": 0,
                "artifact_count": 0,
                "manifest_identity": None,
                "release_blockers": [],
                "error": message,
            })
            warnings.append(f"{key.identity}: render failed: {message}")
            _progress(progress, {"event": "failed", "target": key.identity, "error": message})
            continue

        blockers = list(artifacts.release_blockers)
        outputs.append({
            **_target_description(key),
            "path": str(artifacts.root),
            "file_count": len(artifacts.artifacts) + 1,
            "artifact_count": len(artifacts.artifacts),
            "manifest_identity": artifacts.manifest_identity,
            "release_blockers": blockers,
            "error": None,
            "scope": scope,
            "note": ('S100 PRJ引脚资源片段，仅含引脚、继电器和引脚组定义。'
                     if scope == 'pin' and key.platform == 's100' else
                     '普通FBIST共享资源；不含PUMP汇总、Flash或外部Pattern。编译运行仍需匹配的引脚和时序资源。' if scope == 'fbist' else
                     'Flash擦写/比较共享资源，按NM_pattern整组输出；不含页面/UID标签、普通FBIST或外部资源。运行仍需匹配的引脚和时序资源。' if scope == 'flash' else
                     'Flash页／UID共享资源，按ADDR_MAP整组输出默认页映像和标签；运行时Trim结果与UID数据仍由完整程序填入，运行需匹配的引脚和时序资源。' if scope == 'flash_labels' else
                     'PUMP汇总资源set_all_final_vposp；按全部FLOW的PUMP=yes项生成动态DAC默认向量及标签，最终DAC值仍由程序写入，运行需匹配的引脚与时序资源。' if scope == 'pump' else
                     '当前目标实际引用的Pattern资源，未输出主程序或Pin定义。' if scope == 'patterns' else
                     'Chroma Pin DEC引脚定义。' if scope == 'pin' else ''),
        })
        warnings.extend(f"{key.identity}: release blocked: {blocker}" for blocker in blockers)
        _progress(progress, {"event": "rendered", "target": key.identity})

    validation = {
        "requested": bool(validate),
        "state": "UNSUPPORTED" if validate else "NOT_REQUESTED",
        "vendor_compiler_executed": False,
        "errors": (
            ["GUI.GENERATION.VALIDATION_UNSUPPORTED: review generation does not run vendor compilers"]
            if validate else []
        ),
    }
    warnings.extend(validation["errors"])
    status = "RENDER_FAILED" if failures else (
        "REVIEW_READY_WITH_WARNINGS" if warnings else "REVIEW_READY"
    )
    result = {
        "status": status,
        "scope": scope,
        "run_dir": str(run_dir),
        "outputs": outputs,
        "warnings": warnings,
        "validation": validation,
    }
    _progress(progress, {"event": "completed", "status": status})
    return result


def _request(workbook, compilation, output_root: Path) -> GenerationRequest:
    roots = GenerationRoots(
        output_root,
        output_root / "chroma",
        output_root / "s100",
    )
    return build_generation_request(
        compilation,
        workbook,
        roots,
        tools_root=_SOURCE_ROOT / "tools",
        toolchain_roots={
            "chroma": _WORKSPACE_ROOT / "toolchains" / "chroma",
            "s100": _WORKSPACE_ROOT / "toolchains" / "s100",
        },
    )


def _validated_run_dir(value: Path) -> Path:
    run_dir = Path(value).resolve()
    parent = _RUN_PARENT.resolve()
    if run_dir.parent != parent:
        raise ValueError("GUI.GENERATION.RUN_DIR_OUTSIDE_PARENT")
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("GUI.GENERATION.RUN_DIR_INVALID")
    snapshot = run_dir / "input"
    if not snapshot.is_dir() or snapshot.is_symlink():
        raise ValueError("GUI.GENERATION.RUN_DIR_SNAPSHOT_MISSING")
    if (run_dir / "review").exists():
        raise ValueError("GUI.GENERATION.RUN_DIR_REVIEW_EXISTS")
    return run_dir


def _select_targets(
    request: GenerationRequest, target_ids: list[str]
) -> tuple[GenerationTarget, ...]:
    return _select_by_id({target.key.identity.casefold(): target for target in request.targets}, target_ids)


def _select_by_id(by_id, target_ids):
    requested = tuple(str(target_id).strip() for target_id in target_ids)
    if not requested or any(not target_id for target_id in requested):
        raise ValueError("GUI.GENERATION.TARGETS_EMPTY")
    normalized = tuple(target_id.casefold() for target_id in requested)
    if len(set(normalized)) != len(normalized):
        raise ValueError("GUI.GENERATION.TARGET_DUPLICATE")
    unknown = next((target_id for target_id in normalized if target_id not in by_id), None)
    if unknown is not None:
        raise ValueError(f"GUI.GENERATION.TARGET_UNKNOWN: {unknown}")
    return tuple(by_id[target_id] for target_id in normalized)


def _target_description(key) -> dict:
    shared_name = {'FBIST_RESOURCES': '普通FBIST（共享配置）',
                   'FLASH_COMPARE_RESOURCES': 'Flash擦写/比较（共享配置）',
                   'PUMP_RESOURCES': 'set_all_final_vposp（PUMP汇总）',
                   'FLASH_LABEL_RESOURCES': 'Flash页／UID（共享配置）'}.get(key.program_name)
    return {
        "id": key.identity,
        "platform": key.platform,
        "cp": '' if shared_name else key.cp,
        "variant": '' if shared_name else key.variant,
        "name": shared_name or key.program_name,
    }


def _progress(callback: Callable[[dict], None] | None, event: dict) -> None:
    if callback is not None:
        callback(event)
