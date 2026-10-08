import re
import pytest


def test_sd_preserves_vectors_repeat_and_timing_changes():
    from gui.hex_pattern_format import chroma_to_sd
    pat = 'SET_DEC_FILE "pin.dec"\nHEADER\nCLK,DATA,RST;\nSPM_PATTERN(test) {\n *011*TS1;\n *1H1*RPT 99;//read\n *101*TS5;\n *111*TS6;\n *XXX*STOP;\n}\n'
    sd, mapping = chroma_to_sd(pat)
    assert 'CLK,DATA,RST;\nEND_HEAD;' in sd
    assert 'START:011;TIMING_SET G1_1;' in sd
    assert '1H1;RPT 99;//read' in sd
    assert '101;TIMING_SET G1_5;' in sd
    assert '111;TIMING_SET G1_6;' in sd
    assert 'END:XXX;' in sd
    assert mapping == {'TS1':'G1_1','TS5':'G1_5','TS6':'G1_6'}
    longer, _ = chroma_to_sd(pat.replace('RPT 99', 'RPT 70000'))
    assert '1H1;RPT 65535;' in longer and '1H1;RPT 4465;' in longer
    with pytest.raises(ValueError):
        chroma_to_sd(pat.replace('RPT 99;', 'JSR other;'))


def test_all_chroma_versions_export_both_formats_with_identical_vector_semantics(tmp_path):
    from gui.hex_conversion import configured_profile, convert_hex, profiles
    from tests.test_gui_hex_conversion import sample_hex
    for profile in profiles():
        if not profile['enabled'] or profile['platform'] != 'chroma':
            continue
        p = configured_profile(profile['id'], {'outputPlatform':'both'})
        out = tmp_path/profile['id']/'output'
        result = convert_hex(sample_hex(),p,out,'test.hex')
        assert {f['name'].split('.')[-1] for f in result['files']} == {'pat','sd'}
        pat = next(out.glob('*.pat')).read_text(encoding='utf-8-sig')
        sd = next(out.glob('*.sd')).read_text(encoding='utf-8-sig')
        def rows(text, regex):
            result, timing = [], None
            for m in re.finditer(regex,text,re.M):
                tail=m[2].split('//')[0]
                repeat=re.search(r'RPT\s+(\d+)',tail)
                ts=re.search(r'(?:TS|TIMING_SET G1_)(\d+)',tail)
                timing = ts[1] if ts else timing
                amount = int(repeat[1]) if repeat else 1
                if result and result[-1][0] == m[1] and result[-1][2] == timing:
                    result[-1][1] += amount
                else:
                    result.append([m[1], amount, timing])
            return result
        assert list(rows(pat,r'^\s*\*([01XLHZ]+)\*(.*)$')) == list(rows(sd,r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*:)?([01XLHZ]+);(.*)$')), profile['id']
