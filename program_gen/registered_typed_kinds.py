"""Native typed-kind registrations validated for platform-program assembly."""

from __future__ import annotations

from dataclasses import replace

from program_gen.dac_adjust_assembly import compile_dac_adjust_assembly
from program_gen.adc_test_assembly import compile_adc_test_assembly
from program_gen.main_assembly import compile_main_assembly
from program_gen.vt_assembly import compile_vt_assembly
from program_gen.margin_assembly import compile_margin_assembly
from program_gen.os_assembly import compile_os_assembly
from program_gen.pdr_trim_assembly import compile_pdr_trim_assembly
from program_gen.pdr_verify_assembly import compile_pdr_verify_assembly
from program_gen.skeleton import LifecyclePlan, SkeletonPlatformProfile
from program_gen.standard_trim.assembly import (
    compile_standard_trim_assembly_slice,
)
from program_gen.standard_trim.support import compile_standard_trim_support
from program_gen.standard_verify_assembly import compile_standard_verify_assembly
from program_gen.flash_window_assembly import compile_flash_window_assembly
from program_gen.firmware_test_assembly import (
    compile_code_download_assembly,
    compile_firmware_function_test_assembly,
    compile_firmware_run_test_assembly,
)
from program_gen.pvd_test_assembly import compile_pvd_test_assembly
from program_gen.dc_parametric_assembly import compile_dc_parametric_assembly
from program_gen.vih_vil_assembly import compile_vih_vil_assembly
from program_gen.freq_test_assembly import compile_freq_test_assembly
from program_gen.opa_test_assembly import compile_opa_test_assembly
from program_gen.dac_test_assembly import compile_dac_test_assembly
from program_gen.scan_test_assembly import compile_scan_test_assembly
from program_gen.trimdata_read_assembly import compile_trimdata_read_assembly
from program_gen.trimdata_write_assembly import compile_trimdata_write_assembly
from program_gen.uid_assembly import compile_uid_assembly, compile_id_assembly
from program_gen.typed_kind_registry import (
    TypedKindAssembly,
    TypedKindContext,
    TypedKindRegistry,
)


def _compile_standard_trim(plans, context: TypedKindContext) -> TypedKindAssembly:
    # Platform package initialization imports this registry; resolve on use.
    from program_gen.platform_program.baseline import platform_baseline_target_references

    specs = tuple(plans)
    if not specs:
        return TypedKindAssembly("STANDARD_TRIM")

    compilation = context.compilation
    compilation.require_success()
    target = context.target
    cp_plan = compilation.for_cp(target.cp)
    profile = _profile_for(target.platform)
    lifecycle = LifecyclePlan.empty_for(profile)
    regions = {
        spec.dac.pattern_name: context.pattern_producer.write_region(
            spec.dac.pattern_name
        )
        for spec in specs
    }
    assembly = compile_standard_trim_assembly_slice(
        specs,
        target,
        cp_plan.canonical_schedule,
        profile=profile,
        lifecycle=lifecycle,
        resource_closure=cp_plan.resources.identities,
    )
    bodies = tuple(
        replace(
            body,
            fragment=replace(
                body.fragment,
                content=body.fragment.content.replace(b"\r\n", b"\n").replace(
                    b"\n", b"\r\n"
                ),
            ),
        )
        for body in assembly.skeleton_input.bodies
    )
    support = compile_standard_trim_support(
        target,
        specs,
        regions,
        provided_target_references=platform_baseline_target_references(
            context.platform_facts
        ),
    )
    return TypedKindAssembly(
        "STANDARD_TRIM",
        (*assembly.business_contributions, support),
        bodies,
    )


def _profile_for(platform: str) -> SkeletonPlatformProfile:
    platform = str(platform).strip().casefold()
    if platform == "chroma":
        from program_gen.platform_program.chroma import (
            CHROMA_REQUIRED_STRUCTURES,
            CHROMA_SECTION_ORDER,
        )

        return SkeletonPlatformProfile(
            "chroma", ".pln", CHROMA_SECTION_ORDER, CHROMA_REQUIRED_STRUCTURES
        )
    if platform == "s100":
        from program_gen.platform_program.s100 import (
            S100_REQUIRED_STRUCTURES,
            S100_SECTION_ORDER,
        )

        return SkeletonPlatformProfile(
            "s100", ".prg", S100_SECTION_ORDER, S100_REQUIRED_STRUCTURES
        )
    raise ValueError(f"TK.STANDARD_TRIM.PLATFORM: {platform!r}")


NATIVE_TYPED_KIND_REGISTRY = TypedKindRegistry((
    ("STANDARD_TRIM", _compile_standard_trim),
    ("OS", compile_os_assembly),
    ("PDR_TRIM", compile_pdr_trim_assembly),
    ("PDR_VERIFY", compile_pdr_verify_assembly),
    ("STANDARD_VERIFY", compile_standard_verify_assembly),
    ("DAC_ADJUST", compile_dac_adjust_assembly),
    ("FLASH_WINDOW", compile_flash_window_assembly),
    ("TRIMDATA_READ", compile_trimdata_read_assembly),
    ("TRIMDATA_WRITE", compile_trimdata_write_assembly),
    ("UID", compile_uid_assembly),
    ("ID", compile_id_assembly),
    ("MAIN", compile_main_assembly),
    ("VT", compile_vt_assembly),
    ("MARGIN", compile_margin_assembly),
    ("CODE_DOWNLOAD", compile_code_download_assembly),
    ("FIRMWARE_FUNCTION_TEST", compile_firmware_function_test_assembly),
    ("FIRMWARE_RUN_TEST", compile_firmware_run_test_assembly),
    ("PVD_TEST", compile_pvd_test_assembly),
    ("ADC_TEST", compile_adc_test_assembly),
    ("DC_PARAMETRIC_TEST", compile_dc_parametric_assembly),
    ("DC_VIH_VIL", compile_vih_vil_assembly),
    ("FREQ_TEST", compile_freq_test_assembly),
    ("OPA_TEST", compile_opa_test_assembly),
    ("DAC_TEST", compile_dac_test_assembly),
    ("VERIFY_SCAN", compile_scan_test_assembly),
    ("VERIFY_MBIST", compile_scan_test_assembly),
))


__all__ = ["NATIVE_TYPED_KIND_REGISTRY"]
