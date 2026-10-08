from pathlib import Path
import tempfile
import pytest


def record(address, kind, values):
    raw = bytes([len(values), address >> 8, address & 255, kind]) + bytes(values)
    return ':' + (raw + bytes([-sum(raw) & 255])).hex().upper()


def sample_hex(size=256, base=0x0800):
    lines = [record(0, 4, [base >> 8, base & 255])]
    lines += [record(i, 0, [(i+j) % 256 for j in range(min(16, size-i))]) for i in range(0, size, 16)]
    return ('\n'.join(lines + [record(0, 1, [])]) + '\n').encode()


def test_hex_checksum_addresses_and_legacy_normalization():
    from gui.hex_conversion import parse_hex, prepare_hex
    image = parse_hex(sample_hex(20))
    assert image['summary']['segments'] == [{'start': 0x08000000, 'end': 0x08000014}]
    profile = {'mode':'swd_flash', 'pageSize':256, 'maxAddress':65536, 'verify':True}
    normalized, summary = prepare_hex(image, profile)
    assert normalized.endswith(b':0400000500000000F7\n:00000001FF\n')
    assert summary['dataBytes'] == 20 and summary['paddingBytes'] == 12
    assert summary['targetStart'] == 0x08000000
    assert ':10001000' in normalized.decode()
    with pytest.raises(ValueError, match='校验'):
        parse_hex(sample_hex().replace(b':10000000', b':10000001'))


def test_hex_rejects_ambiguous_inputs_and_unrepresentable_legacy_ranges():
    from gui.hex_conversion import parse_hex, prepare_hex
    with pytest.raises(ValueError, match='结束'):
        parse_hex(record(0, 0, [0, 1, 2, 3]).encode())
    duplicate = '\n'.join([record(0,0,[1,2,3,4])]*2 + [record(0,1,[])])
    with pytest.raises(ValueError, match='重叠'):
        parse_hex(duplicate.encode())
    sparse = '\n'.join([record(0,0,[1]*16), record(32,0,[2]*16), record(0,1,[])])
    with pytest.raises(ValueError, match='不连续'):
        prepare_hex(parse_hex(sparse.encode()), {'mode':'swd_sram', 'pageSize':4})
    with pytest.raises(ValueError, match='地址范围'):
        prepare_hex(parse_hex(sample_hex(base=0x9000)), {'mode':'swd_flash', 'pageSize':256})


def test_all_enabled_original_engines_convert_without_external_paths(tmp_path):
    from gui.hex_conversion import convert_hex, profiles
    results = []
    for profile in profiles():
        if not profile['enabled']:
            continue
        output = tmp_path/profile['id']/'output'
        result = convert_hex(sample_hex(), profile, output, 'firmware.hex')
        assert result['files'], profile['id']
        assert result['summary']['dataBytes'] == 256
        assert result['summary']['vectorRows'] > 256
        assert result['summary']['outputPins'] == profile['pins'], profile['id']
        results.append(profile['id'])
    assert len(results) == 38


def test_pin_options_validate_mapping_and_verify_capability():
    from gui.hex_conversion import configured_profile
    p = configured_profile('swd-sram-pt100', {'pins':['CLK', 'DATA', 'RST'], 'verify':False})
    assert p['pins'] == ['CLK', 'DATA', 'RST'] and p['verify'] is False
    assert p['sourcePins'] == ['PA14', 'PA13', 'NRST']
    for pins in ([], ['A','B'], ['A','a','B'], ['A','B','bad;pin'], ['A','B','']):
        with pytest.raises(ValueError, match='管脚'):
            configured_profile('swd-sram-pt100', {'pins':pins})
    with pytest.raises(ValueError, match='校验'):
        configured_profile('swd-pt104-flash', {'verify':True})
    with pytest.raises(ValueError, match='校验'):
        configured_profile('swd-sram-pt100', {'verify':'false'})


def test_all_profiles_pin_mapping_and_optional_readback(tmp_path):
    import re
    from gui.hex_conversion import configured_profile, convert_hex, profiles
    for profile in profiles():
        if not profile['enabled']:
            continue
        renamed = configured_profile(profile['id'], {'pins':['CLK', 'DATA', 'RST']})
        on_dir = tmp_path/profile['id']/'on'/'output'
        on = convert_hex(sample_hex(), renamed, on_dir, 'firmware.hex')
        off_dir = tmp_path/profile['id']/'off'/'output'
        off = convert_hex(sample_hex(), configured_profile(profile['id'], {'pins':['CLK','DATA','RST'], 'verify':False}), off_dir, 'firmware.hex')
        assert on['summary']['outputPins'] == off['summary']['outputPins'] == ['CLK','DATA','RST']
        assert off['summary']['verify'] is False
        a = (on_dir/on['files'][0]['name']).read_text(encoding='utf-8-sig').splitlines()
        b = (off_dir/off['files'][0]['name']).read_text(encoding='utf-8-sig').splitlines()
        if not profile['verify']:
            assert a == b
        else:
            assert off['summary']['vectorRows'] < on['summary']['vectorRows'], profile['id']
            # Turning off readback must only omit rows, never alter retained writes.
            stream = iter(a)
            assert all(any(row == candidate for candidate in stream) for row in b), profile['id']
