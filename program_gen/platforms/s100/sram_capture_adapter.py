"""S100 Adapter for the shared SRAM_CAPTURE Recipe Module."""

from program_gen.core.sram_capture import SramCapturePlan
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import (
    RenderSymbolRef,
    ResourceRequirement,
    SymbolProvision,
)


_DAQ_BITS = ",".join(str(bit) for bit in range(1, 33))


def adapt_sram_capture(plan: SramCapturePlan) -> RecipeModuleEmission:
    if not isinstance(plan, SramCapturePlan):
        raise TypeError("S100 SRAM_CAPTURE Adapter requires SramCapturePlan")

    layout = plan.layout
    result = plan.result_symbol
    cache = f"{result}_READ32"
    addresses = _read32_addresses(plan)
    cache_index = {address: index for index, address in enumerate(addresses)}
    lines = [
        f"\tunsigned int {result}[MAX_SITE][{layout.count}]={{0}};",
        f"\tunsigned int {cache}[MAX_SITE][{len(addresses)}]={{0}};",
        "",
    ]
    for index, address in enumerate(addresses):
        lines.extend(_read32(plan.capture_pin, cache, index, address))

    lines.extend((
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t{",
        "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
    ))
    mask = f"0X{layout.value_mask:X}U"
    for value in layout.values:
        low = f"{cache}[T_SOCKET][{cache_index[value.read32_address]}]"
        if value.bit_offset:
            low = f"({low}>>{value.bit_offset})"
        else:
            low = f"({low})"
        expression = low
        if value.crosses_word:
            high_index = cache_index[value.second_read32_address]
            high = f"({cache}[T_SOCKET][{high_index}]<<{32 - value.bit_offset})"
            expression = f"({low}|{high})"
        lines.append(
            f"\t\t{result}[T_SOCKET][{value.index}]={expression}&{mask};"
        )
    lines.append("\t}")

    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=(ResourceRequirement(
            logical_identity="pattern:sram-capture:s100:read32",
            relative_path="sram_capture.sd",
            spec_identity="v14.sram-capture/1:s100:read32-low16",
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


def _read32(pin: str, cache: str, index: int, address: int) -> tuple[str, ...]:
    parity = (address.bit_count() + 1) & 1
    literal = f"0X{address:X}"
    return (
        f"\t// SRAM_CAPTURE READ32 {literal}",
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t{",
        "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
        f"\t\tGB[0+T_SOCKET*64]={literal};",
        f"\t\tGB[1+T_SOCKET*64]={parity};",
        "\t}",
        f"\tLOGIC_WRITE_PATTERN_MEMORY(sram_capture:addr_st,"
        f"sram_capture:addr_sp,{pin},GB1,BIT_COUNT=16,SERIAL,LSB_MSB);",
        f"\tLOGIC_WRITE_PATTERN_MEMORY(sram_capture:parity_st,"
        f"sram_capture:parity_sp,{pin},GB2,BIT_COUNT=1,SERIAL,LSB_MSB);",
        "\tLOGIC_SET_AC_DATALOG(sram_capture:START,sram_capture:END,"
        "LOG_ENABLE_ALL,AC_IGNORE_FAIL);",
        f'\tLOGIC_DAQ_TRANSFER_SETTING({pin},"{_DAQ_BITS}",'
        "TRIG=PTN_TRIG,ACLOG_FILTER_BY_PTN_TRIG_MODE);",
        "\tRUN_PATTERN(sram_capture:START,sram_capture:END,1,TS_5MHZ);",
        "\tLOGIC_DAQ_DATA_READ(DATA_COUNT=32);",
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t{",
        "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
        f"\t\t{cache}[T_SOCKET][{index}]=0U;",
        "\t\tfor(int J=0;J<32;J++)",
        f"\t\t\t{cache}[T_SOCKET][{index}]|="
        "(unsigned int)Sys_SW_BUFFER_DATA[T_SOCKET][J]<<J;",
        "\t}",
        "",
    )


__all__ = ["adapt_sram_capture"]
