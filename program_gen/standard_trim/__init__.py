"""Generic STANDARD_TRIM dual-platform function-block renderer.

Read-only typed layer for ordinary Trim with no I/O or renderer registration.
Complete-program Skeleton, Pattern, project resources and materialization are
owned by the upper ``program_gen.platform_program`` module.
"""

from program_gen.standard_trim.function_blocks import (
    StandardTrimSliceError,
    StandardTrimSkeletonError,
    request_assembly,
    resolve_slice_target,
    render_standard_trim,
)
from program_gen.standard_trim.assembly import (
    StandardTrimAssemblySlice,
    compile_standard_trim_assembly_slice,
)
from program_gen.standard_trim.syntax import ChromaSyntax, S100Syntax

__all__ = [
    "ChromaSyntax",
    "S100Syntax",
    "StandardTrimSliceError",
    "StandardTrimSkeletonError",
    "StandardTrimAssemblySlice",
    "compile_standard_trim_assembly_slice",
    "render_standard_trim",
    "request_assembly",
    "resolve_slice_target",
]
