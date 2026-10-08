"""Composer — comparator (COMP), a peripheral type the engine had not touched.

Proves the field resolvers reach COMP.CSR and that the multi-instance
`instance` selector targets COMP2 (0x40016C10), not just the default COMP1.
Skips when KB products absent.
"""
from __future__ import annotations

import pytest

from swd_authoring import Composer, ComposeRequest, Directive
from swd_authoring.encoding import CACHE_ROOT

CHIP = "py32f420"

pytestmark = pytest.mark.skipif(
    not (CACHE_ROOT / CHIP / "fieldmap.json").exists(),
    reason="encoding_v2 products not built (run build first)",
)


@pytest.fixture(scope="module")
def composer():
    return Composer(CHIP)


def _w(result, addr):
    # config-then-enable 后,使能寄存器会被写两次(配置→使能);取末行=最终值
    ws = [r for r in result.rows if r.type == "W" and r.addr == addr]
    return ws[-1] if ws else None


def test_csr_mask_excludes_readonly_output_bit(composer):
    # 回读 mask 只含写过的配置位,不含 COMP_OUT(bit30,只读硬件输出)——
    # 否则比较器正常输出会让回读假阴(真硅 COMP1 踩过)。
    r = composer.compile(ComposeRequest(name="comp", directives=[
        Directive(kind="enable_bit", peri="COMP", instance="COMP1",
                  reg="CSR", field="EN"),
        Directive(kind="field_value", peri="COMP", instance="COMP1",
                  reg="CSR", field="INPSEL", value=1),
    ]))
    csr = [x for x in r.rows if x.type == "W" and x.addr == 0x40016C00]
    union = 0
    for x in csr:
        union |= (x.mask or 0)
    assert union, "CSR 行应带 mask"
    assert not union & 0x40000000, "mask 不应含 bit30(COMP_OUT 只读输出)"


def _select_inputs(instance):
    return [
        Directive(kind="field_symbol", peri="COMP", reg="CSR",
                  instance=instance, symbol="COMP_INPUT_PLUS_IO1"),
        Directive(kind="field_symbol", peri="COMP", reg="CSR",
                  instance=instance, symbol="COMP_INPUT_MINUS_IO1"),
        Directive(kind="enable_bit", peri="COMP", reg="CSR",
                  instance=instance, field="EN"),
    ]


def test_comp1_enable(composer):
    r = composer.compile(ComposeRequest(name="comp1en", directives=[
        Directive(kind="enable_bit", peri="COMP", reg="CSR",
                  instance="COMP1", field="EN"),
    ]))
    assert _w(r, 0x40016C00).data == 0x00000001     # PT104_COMP1_CASE01


def test_comp1_input_select(composer):
    r = composer.compile(ComposeRequest(name="comp1in",
                                        directives=_select_inputs("COMP1")))
    # EN | INPSEL=IO1(<<8) | INNSEL=IO1(<<3) — matches PT104_COMP1_CASE02
    assert _w(r, 0x40016C00).data == 0x00000109


def test_comp2_instance_selector(composer):
    # same recipe, instance=COMP2 must land at 0x40016C10, not COMP1's 0x..C00
    r = composer.compile(ComposeRequest(name="comp2",
                                        directives=_select_inputs("COMP2")))
    assert _w(r, 0x40016C00) is None                # not the default instance
    assert _w(r, 0x40016C10).data == 0x00000109     # PT104_COMP2_CASE02


def test_unknown_instance_raises(composer):
    """Previously emitted unchecked output; V1 must refuse the known missing semantics."""
    with pytest.raises(ValueError, match='unknown instance'):
        composer.compile(ComposeRequest(name="bad", directives=[
                Directive(kind="enable_bit", peri="COMP", reg="CSR",
                          instance="COMP9", field="EN"),
            ]))
