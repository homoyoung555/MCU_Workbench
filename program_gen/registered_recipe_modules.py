"""Native Recipe Module registrations approved for typed-plan execution."""

from __future__ import annotations

from program_gen.core.run_pattern import RunPatternPlan
from program_gen.core.sram_capture import SramCapturePlan
from program_gen.core.nm_test import NmTestPlan
from program_gen.core.vt_test import VtTestPlan
from program_gen.core.margin_test import MarginTestPlan
from program_gen.platforms.chroma.margin_test_adapter import adapt_margin_test as chroma_margin_test
from program_gen.platforms.s100.margin_test_adapter import adapt_margin_test as s100_margin_test
from program_gen.platforms.chroma.vt_test_adapter import adapt_vt_test as chroma_vt_test
from program_gen.platforms.s100.vt_test_adapter import adapt_vt_test as s100_vt_test
from program_gen.platforms.chroma.nm_test_adapter import adapt_nm_test as chroma_nm_test
from program_gen.platforms.s100.nm_test_adapter import adapt_nm_test as s100_nm_test
from program_gen.core.commit_module import CommitModulePlan
from program_gen.core.dac_write import DacWriteModulePlan
from program_gen.core.dac_adjust import DacAdjustModulePlan
from program_gen.core.set_vposp import SetVpospPlan
from program_gen.core.flash_window import BuildMapPlan, NmLoopPlan
from program_gen.core.verify_modules import EnterPlan, JudgePlan
from program_gen.core.result_export import ResultExportModulePlan
from program_gen.core.otp_program import LoadMapPlan, PgmOtpModulePlan
from program_gen.core.trimdata_read import CheckOtpPlan, ReadOtpMapPlan
from program_gen.platforms.chroma.run_pattern_adapter import (
    adapt_run_pattern as adapt_chroma_run_pattern,
)
from program_gen.platforms.chroma.commit_adapter import adapt_commit as adapt_chroma_commit
from program_gen.platforms.s100.commit_adapter import adapt_commit as adapt_s100_commit
from program_gen.platforms.chroma.dac_write_adapter import (
    adapt_dac_write as adapt_chroma_dac_write,
)
from program_gen.platforms.chroma.dac_adjust_adapter import adapt_dac_adjust as adapt_chroma_dac_adjust
from program_gen.platforms.s100.dac_write_adapter import (
    adapt_dac_write as adapt_s100_dac_write,
)
from program_gen.platforms.s100.dac_adjust_adapter import adapt_dac_adjust as adapt_s100_dac_adjust
from program_gen.platforms.s100.run_pattern_adapter import (
    adapt_run_pattern as adapt_s100_run_pattern,
)
from program_gen.platforms.chroma.sram_capture_adapter import (
    adapt_sram_capture as adapt_chroma_sram_capture,
)
from program_gen.platforms.s100.sram_capture_adapter import (
    adapt_sram_capture as adapt_s100_sram_capture,
)
from program_gen.platforms.chroma.set_vposp_adapter import (
    adapt_set_vposp as adapt_chroma_set_vposp,
)
from program_gen.platforms.s100.set_vposp_adapter import (
    adapt_set_vposp as adapt_s100_set_vposp,
)
from program_gen.platforms.chroma.verify_module_adapter import (
    adapt_enter as adapt_chroma_enter,
    adapt_judge as adapt_chroma_judge,
)
from program_gen.platforms.s100.verify_module_adapter import (
    adapt_enter as adapt_s100_enter,
    adapt_judge as adapt_s100_judge,
)
from program_gen.platforms.chroma.result_export_adapter import (
    adapt_result_export as adapt_chroma_result_export,
)
from program_gen.platforms.s100.result_export_adapter import (
    adapt_result_export as adapt_s100_result_export,
)
from program_gen.platforms.chroma.flash_window_adapter import (
    adapt_build_map as adapt_chroma_build_map,
    adapt_nm_loop as adapt_chroma_nm_loop,
)
from program_gen.platforms.s100.flash_window_adapter import (
    adapt_build_map as adapt_s100_build_map,
    adapt_nm_loop as adapt_s100_nm_loop,
)
from program_gen.platforms.chroma.trimdata_read_adapter import (
    adapt_check_otp as adapt_chroma_check_otp,
    adapt_load_map as adapt_chroma_load_map,
    adapt_read_otp_map as adapt_chroma_read_otp_map,
)
from program_gen.platforms.s100.trimdata_read_adapter import (
    adapt_check_otp as adapt_s100_check_otp,
    adapt_load_map as adapt_s100_load_map,
    adapt_read_otp_map as adapt_s100_read_otp_map,
)
from program_gen.platforms.chroma.pgm_otp_adapter import (
    adapt_pgm_otp as adapt_chroma_pgm_otp,
)
from program_gen.platforms.s100.pgm_otp_adapter import (
    adapt_pgm_otp as adapt_s100_pgm_otp,
)
from program_gen.recipe_module_registry import (
    RecipeModulePlugin,
    RecipeModuleRegistry,
)


from program_gen.core.id_module import IdModulePlan
from program_gen.core.build_uid_module import BuildUidModulePlan
from program_gen.platforms.chroma.id_adapter import adapt_read_id as chroma_read_id, adapt_check_id as chroma_check_id
from program_gen.platforms.s100.id_adapter import adapt_read_id as s100_read_id, adapt_check_id as s100_check_id
from program_gen.platforms.chroma.build_uid_adapter import adapt_build_uid as chroma_build_uid
from program_gen.platforms.s100.build_uid_adapter import adapt_build_uid as s100_build_uid


NATIVE_RECIPE_MODULE_REGISTRY = RecipeModuleRegistry((
    RecipeModulePlugin("MARGIN_TEST", MarginTestPlan, (("chroma", chroma_margin_test), ("s100", s100_margin_test))),
    RecipeModulePlugin("VT_TEST", VtTestPlan, (("chroma", chroma_vt_test), ("s100", s100_vt_test))),
    RecipeModulePlugin("NM_TEST", NmTestPlan, (("chroma", chroma_nm_test), ("s100", s100_nm_test))),
    RecipeModulePlugin("READID", IdModulePlan, (("chroma", chroma_read_id), ("s100", s100_read_id))),
    RecipeModulePlugin("CHECKID", IdModulePlan, (("chroma", chroma_check_id), ("s100", s100_check_id))),
    RecipeModulePlugin("BUILDUID", BuildUidModulePlan, (("chroma", chroma_build_uid), ("s100", s100_build_uid))),
    RecipeModulePlugin(
        name="RUN",
        plan_type=RunPatternPlan,
        adapters=(
            ("chroma", adapt_chroma_run_pattern),
            ("s100", adapt_s100_run_pattern),
        ),
    ),
    RecipeModulePlugin(
        name="SRAM_CAPTURE",
        plan_type=SramCapturePlan,
        adapters=(
            ("chroma", adapt_chroma_sram_capture),
            ("s100", adapt_s100_sram_capture),
        ),
    ),
    RecipeModulePlugin(
        name="ENTER",
        plan_type=EnterPlan,
        adapters=(("chroma", adapt_chroma_enter), ("s100", adapt_s100_enter)),
    ),
    RecipeModulePlugin(
        name="JUDGE",
        plan_type=JudgePlan,
        adapters=(("chroma", adapt_chroma_judge), ("s100", adapt_s100_judge)),
    ),
    RecipeModulePlugin(
        name="EXPORT",
        plan_type=ResultExportModulePlan,
        adapters=(
            ("chroma", adapt_chroma_result_export),
            ("s100", adapt_s100_result_export),
        ),
    ),
    RecipeModulePlugin(
        name="SETVPOSP",
        plan_type=SetVpospPlan,
        adapters=(
            ("chroma", adapt_chroma_set_vposp),
            ("s100", adapt_s100_set_vposp),
        ),
    ),
    RecipeModulePlugin(
        name="DAC_ADJ",
        plan_type=DacAdjustModulePlan,
        adapters=(("chroma", adapt_chroma_dac_adjust), ("s100", adapt_s100_dac_adjust)),
    ),
    RecipeModulePlugin(
        name="DAC_WRITE",
        plan_type=DacWriteModulePlan,
        adapters=(
            ("chroma", adapt_chroma_dac_write),
            ("s100", adapt_s100_dac_write),
        ),
    ),
    RecipeModulePlugin(
        name="COMMIT",
        plan_type=CommitModulePlan,
        adapters=(
            ("chroma", adapt_chroma_commit),
            ("s100", adapt_s100_commit),
        ),
    ),
    RecipeModulePlugin(
        name="BUILDMAP",
        plan_type=BuildMapPlan,
        adapters=(
            ("chroma", adapt_chroma_build_map),
            ("s100", adapt_s100_build_map),
        ),
    ),
    RecipeModulePlugin(
        name="NMLOOP",
        plan_type=NmLoopPlan,
        adapters=(
            ("chroma", adapt_chroma_nm_loop),
            ("s100", adapt_s100_nm_loop),
        ),
    ),
    RecipeModulePlugin(
        name="READOTPMAP",
        plan_type=ReadOtpMapPlan,
        adapters=(
            ("chroma", adapt_chroma_read_otp_map),
            ("s100", adapt_s100_read_otp_map),
        ),
    ),
    RecipeModulePlugin(
        name="LOADMAP",
        plan_type=LoadMapPlan,
        adapters=(
            ("chroma", adapt_chroma_load_map),
            ("s100", adapt_s100_load_map),
        ),
    ),
    RecipeModulePlugin(
        name="CHECKOTP",
        plan_type=CheckOtpPlan,
        adapters=(
            ("chroma", adapt_chroma_check_otp),
            ("s100", adapt_s100_check_otp),
        ),
    ),
    RecipeModulePlugin(
        name="PGMOTP",
        plan_type=PgmOtpModulePlan,
        adapters=(
            ("chroma", adapt_chroma_pgm_otp),
            ("s100", adapt_s100_pgm_otp),
        ),
    ),
))


__all__ = ["NATIVE_RECIPE_MODULE_REGISTRY"]
