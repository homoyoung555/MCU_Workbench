"""Chroma Adapter for the shared SRAM_CAPTURE Recipe Module."""

from program_gen.core.sram_capture import SramCapturePlan
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import (
    RenderSymbolRef,
    ResourceRequirement,
    SymbolProvision,
)


def adapt_sram_capture(plan: SramCapturePlan) -> RecipeModuleEmission:
    if not isinstance(plan, SramCapturePlan):
        raise TypeError("Chroma SRAM_CAPTURE Adapter requires SramCapturePlan")

    layout = plan.layout
    result = plan.result_symbol
    cache = f"{result}_READ32"
    capture_bits = f"{result}_CAPTURE_BITS"
    addresses = _read32_addresses(plan)
    cache_index = {address: index for index, address in enumerate(addresses)}
    lines = [
        f"  unsigned int {result}[MAX_SITE][{layout.count}]={{0}};",
        f"  unsigned int {cache}[MAX_SITE][{len(addresses)}]={{0}};",
        f"  int {capture_bits}[32]={{0}};",
        f"  SET_CAPTURE_MEM_MODE({plan.capture_pin}, PEL_K, ON, 32K);",
        "",
    ]
    for index, address in enumerate(addresses):
        lines.extend(
            _read32(plan.capture_pin, cache, capture_bits, index, address)
        )
    lines.extend((
        f"  SET_CAPTURE_MEM_MODE({plan.capture_pin}, PEL_K, OFF, 32K);",
        "  SOCKET_INC(FRZ_OFF)",
        "  {",
    ))
    mask = f"0X{layout.value_mask:X}U"
    for value in layout.values:
        low = f"{cache}[SOCKET][{cache_index[value.read32_address]}]"
        low = f"({low}>>{value.bit_offset})" if value.bit_offset else f"({low})"
        expression = low
        if value.crosses_word:
            high_index = cache_index[value.second_read32_address]
            high = f"({cache}[SOCKET][{high_index}]<<{32 - value.bit_offset})"
            expression = f"({low}|{high})"
        lines.append(
            f"    {result}[SOCKET][{value.index}]={expression}&{mask};"
        )
    lines.append("  }")
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=(ResourceRequirement(
            logical_identity="pattern:sram-capture:chroma:read32",
            relative_path="pat/sram_capture.pat",
            spec_identity="v14.sram-capture/1:chroma:read32-low16",
            purpose="SRAM_CAPTURE aligned 32-bit read pattern",
        ),),
        provides=(SymbolProvision(
            RenderSymbolRef(
                "CAPTURED_VALUES", plan.result_identity.canonical
            ),
            result,
            "UINT",
            layout.width,
            "SITE",
        ),),
    )


def _read32_addresses(plan: SramCapturePlan) -> tuple[int, ...]:
    addresses = []
    for value in plan.layout.values:
        for address in (value.read32_address, value.second_read32_address):
            if address is not None and address not in addresses:
                addresses.append(address)
    return tuple(addresses)


def _read32(
    pin: str,
    cache: str,
    capture_bits: str,
    index: int,
    address: int,
) -> tuple[str, ...]:
    parity = (address.bit_count() + 1) & 1
    literal = f"0X{address:X}"
    return (
        f"  // SRAM_CAPTURE READ32 {literal}",
        "  SOCKET_INC(FRZ_OFF)",
        "  {",
        f"    convert_to_string({literal},16,BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
        "    for(I=0;I<16;I++)",
        "    {",
        f"      WRITE_PAT_MEM(SOCKET,{pin},sram_capture:addr+I,,BUFF_W_P[I]);",
        "    }",
        f'    WRITE_PAT_MEM(SOCKET,{pin},sram_capture:parity,,"{parity}");',
        "  }",
        "  TEST_NUM++;",
        '  TEST_NO(TEST_NUM); DATALOG_MSG="sram_capture";',
        "  JUDGE_PAT(sram_capture,__sram_capture);",
        "  SOCKET_INC(FRZ_OFF)",
        "  {",
        f"    for(J=0;J<32;J++) {capture_bits}[J]=8;",
        f"    READ_CAPTURE_MEM_BLOCK(SOCKET, {pin}, 0, 31, {capture_bits});",
        f"    {cache}[SOCKET][{index}]=0U;",
        "    for(J=0;J<32;J++)",
        f"      if({capture_bits}[J]!=8) {cache}[SOCKET][{index}]|="
        f"(unsigned int){capture_bits}[J]<<J;",
        "  }",
        "",
    )


__all__ = ["adapt_sram_capture"]
