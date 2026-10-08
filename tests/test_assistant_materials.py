"""Public reconciliation contract for imported SWD materials."""

from copy import deepcopy
from pathlib import Path

import pytest

from gui.swd_materials import MaterialLibrary


ROOT = Path(__file__).resolve().parents[1]
ROW = {"addr": "0x40021014", "type": "W", "data": "0xE2000000"}


def _source(source_id="good", *, address="0x40021014", bits="[27:24]", access="RW", reset="0"):
    return {
        "id": source_id,
        "materialId": "manual-material",
        "kind": "svd_cache",
        "peripheral": "RCC",
        "name": "CFGR1",
        "address": address,
        "resetValue": "",
        "access": "",
        "fields": [{"name": "MCO2SEL", "bits": bits, "access": access, "resetValue": reset}],
    }


def _state(*sources, conflicts=(), confirmations=None):
    by_address = {}
    for source in sources:
        by_address.setdefault(source["address"], []).append(source)
    return {
        "materials": [{"id": "manual-material", "sha256": "manual-material", "originalName": "manual.svd"}],
        "registers": [{"address": address, "sources": values} for address, values in by_address.items()],
        "conflicts": list(conflicts),
        "confirmations": {} if confirmations is None else confirmations,
    }


def test_empty_materials_are_bundled_only_and_inputs_are_not_mutated():
    from gui.assistant_materials import reconcile_materials

    state = {"materials": [], "registers": [], "conflicts": [], "confirmations": {}}
    before = deepcopy(state)
    evidence = reconcile_materials(state, [ROW])

    assert evidence["checkedSources"] == []
    assert evidence["scope"] == "bundled_only"
    assert len(evidence["materialVersion"]) == 64
    assert state == before


def test_real_cache_import_exposes_the_ppre1_range_contradiction(tmp_path):
    from gui.assistant_materials import reconcile_materials

    library = MaterialLibrary(tmp_path / "materials")
    library.import_material((ROOT / "gui" / "data" / "py32f420_svd_cache.json").read_bytes(),
                            "py32f420_svd_cache.json", "svd_cache")
    state = library.state()
    # This is a real imported cache, not a hand-built fixture: its PPRE1 is
    # [15:12], while the bundled EncodingDB records a three-bit PPRE1.
    with pytest.raises(ValueError, match="PPRE1.*位段"):
        reconcile_materials(state, [ROW])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda source: source["fields"][0].update(bits="[26:24]"), "位段"),
        (lambda source: source["fields"][0].update(access="RO"), "访问"),
        (lambda source: source["fields"][0].update(resetValue="1"), "复位"),
    ],
)
def test_relevant_field_range_access_or_reset_contradiction_is_rejected(change, message):
    from gui.assistant_materials import reconcile_materials

    source = _source()
    change(source)
    with pytest.raises(ValueError, match=message):
        reconcile_materials(_state(source), [ROW])


def test_field_access_overrides_parent_default_and_hex_reset_is_real_evidence():
    from gui.assistant_materials import reconcile_materials

    source = _source(reset="0x0")
    source["access"] = "RW"
    source["fields"] = [
        {"name": "MCO2SEL", "bits": "[27:24]", "access": "", "resetValue": "0x0"},
        # The real cache describes SWS as read-only while the register default
        # is RW; EncodingDB represents that same field as the R/RO equivalent.
        {"name": "SWS", "bits": "[5:4]", "access": "read-only", "resetValue": "0x0"},
    ]
    assert reconcile_materials(_state(source), [ROW])["scope"] == "reconciled"


def test_note_does_not_resolve_but_selected_consistent_source_does():
    from gui.assistant_materials import reconcile_materials

    good, bad = _source("good"), _source("bad", reset="1")
    conflict = {"id": "cfgr1-reset", "sourceIds": ["good", "bad"], "kind": "fieldReset"}
    with pytest.raises(ValueError, match="未选择"):
        reconcile_materials(_state(good, bad, conflicts=[conflict], confirmations={
            conflict["id"]: {"sourceId": None, "note": "人工复核过"}}), [ROW])
    with pytest.raises(ValueError, match="复位"):
        reconcile_materials(_state(good, bad, conflicts=[conflict], confirmations={
            conflict["id"]: {"sourceId": "bad", "note": "选择错误来源"}}), [ROW])

    evidence = reconcile_materials(_state(good, bad, conflicts=[conflict], confirmations={
        conflict["id"]: {"sourceId": "good", "note": "选择一致来源"}}), [ROW])
    assert [item["sourceId"] for item in evidence["checkedSources"]] == ["good"]


def test_unrelated_conflicts_do_not_block_relevant_reconciliation():
    from gui.assistant_materials import reconcile_materials

    state = _state(_source(), conflicts=[{"id": "elsewhere", "sourceIds": ["unrelated"], "kind": "resetValue"}])
    assert reconcile_materials(state, [ROW])["scope"] == "reconciled"


def test_same_identity_at_alternate_address_and_missing_field_evidence_are_rejected():
    from gui.assistant_materials import reconcile_materials

    with pytest.raises(ValueError, match="地址"):
        reconcile_materials(_state(_source(address="0x40021018")), [ROW])
    incomplete = _source()
    incomplete["fields"] = []
    with pytest.raises(ValueError, match="字段"):
        reconcile_materials(_state(incomplete), [ROW])


def test_incompatible_source_selections_are_not_silently_combined():
    from gui.assistant_materials import reconcile_materials
    state = _state(_source('a'), _source('b'), conflicts=[
        {'id': 'one', 'sourceIds': ['a', 'b']}, {'id': 'two', 'sourceIds': ['a', 'b']}],
        confirmations={'one': {'sourceId': 'a'}, 'two': {'sourceId': 'b'}})
    with pytest.raises(ValueError, match='来源选择'):
        reconcile_materials(state, [ROW])
