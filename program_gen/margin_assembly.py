"""Margin registration uses the shared Flash read assembly boundary."""

from program_gen.flash_read_assembly import compile_flash_read_assembly


def compile_margin_assembly(plans, context):
    return compile_flash_read_assembly(plans, context, kind="MARGIN", module="MARGIN_TEST")
