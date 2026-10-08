from types import SimpleNamespace
import os
import pytest

from gui.swd_generator import generate_pattern, load_excel


def test_compiled_word_roundtrips_without_second_shift():
    from gui.assistant_swd import export_candidate
    result = SimpleNamespace(name='MCO_Config', warnings=[], rows=[
        SimpleNamespace(type='W', addr=0x40021008, data=0x02000000,
                        mask=0x0F000000, phase=6, sources=['fixture'], desc='MCO selection')])
    artifact = export_candidate(result, chip_id='py32f420', product_profile_id='PCD009',
                                platform='chroma', initial_state='reset', knowledge_version='fixture-v1')
    model, _ = load_excel(artifact['excel'])
    row = model['rows'][0]
    assert row['data'] == '0x02000000'
    assert row['step'] == '/'
    assert row['reset value'] is None
    assert artifact['pattern'] == generate_pattern('MCO_Config', model['rows'], 'chroma')
    assert artifact['validation']['hardware'] == 'not_verified'


def test_candidate_keeps_requested_product_profile_in_excel_provenance():
    from gui.assistant_swd import prepare_candidate, read_provenance
    artifact = prepare_candidate(mco_register_request(), product_profile_id='PCD009',
                                 platform='chroma', initial_state='reset')
    assert artifact['productProfileId'] == 'PCD009'
    assert read_provenance(artifact['excel'])['record']['productProfileId'] == 'PCD009'


@pytest.mark.parametrize('platform', ['chroma', 's100'])
def test_low_compare_selects_only_masked_bits(platform):
    from gui.assistant_swd import compare_row, export_candidate
    row = compare_row(0x40021000, compare_mask=1, expected_value=0, description='bit0 low')
    result = SimpleNamespace(name='Check_Low', warnings=[], rows=[row])
    artifact = export_candidate(result, chip_id='py32f420', product_profile_id='PT104',
                                platform=platform, initial_state='reset', knowledge_version='v1')
    assert artifact['rows'][0]['type'] == 'C_L'
    assert artifact['rows'][0]['data'] == '0xFFFFFFFE'
    # The data section has one L comparison and 31 X positions; it is not a full-word read.
    text = artifact['pattern'].decode('gb18030')
    marker = '*1L1*;//FFFFFFFE' if platform == 'chroma' else '1L11;//FFFFFFFE'
    assert marker in text


def test_mixed_compare_is_not_split_into_two_reads():
    from gui.assistant_swd import CandidateError, compare_row
    with pytest.raises(CandidateError, match='MIXED_COMPARE_UNSUPPORTED'):
        compare_row(0x40021000, compare_mask=3, expected_value=1)


def test_provenance_survives_reload_but_edit_invalidates_it():
    from gui.assistant_swd import export_candidate, read_provenance
    from gui.swd_generator import export_excel
    result = SimpleNamespace(name='Config', warnings=[], rows=[
        SimpleNamespace(type='W', addr=0x40021008, data=0x02000000,
                        mask=0x0F000000, phase=6, sources=['L0:RCC.CFGR1'], desc='MCO')])
    artifact = export_candidate(result, chip_id='py32f420', product_profile_id='PT104',
                                platform='s100', initial_state='reset', knowledge_version='sha256:example')
    metadata = read_provenance(artifact['excel'])
    assert metadata['status'] == 'consistent'
    assert metadata['record']['knowledgeVersion'] == 'sha256:example'
    assert metadata['record']['pins'] == {'swc': 'PA14', 'swd': 'PA13', 'reset': 'NRST', 'trig': 'TRIGPIN'}
    assert metadata['record']['steps'][0]['sources'] == ['L0:RCC.CFGR1']
    model, sheet = load_excel(artifact['excel'])
    model['rows'][0]['data'] = '0x03000000'
    edited = export_excel(artifact['excel'], sheet, model['rows'])
    assert read_provenance(edited)['status'] in {'modified', 'missing'}
    assert load_excel(edited)[0]['rows'][0]['data'] == '0x03000000'
    assert read_provenance(b'not an Excel')['status'] == 'unknown'


@pytest.mark.parametrize('operation,value', [('us', 10), ('us', 156), ('ms', 1), ('R', 0), ('CAP', 0)])
def test_unverified_operations_never_export(operation, value):
    from gui.assistant_swd import CandidateError, export_candidate
    result = SimpleNamespace(name='Blocked', warnings=[], rows=[
        SimpleNamespace(type=operation, addr=None, data=value, mask=None, desc='')])
    with pytest.raises(CandidateError, match='UNSUPPORTED_OPERATION'):
        export_candidate(result, chip_id='py32f420', product_profile_id='PT104',
                         platform='s100', initial_state='reset', knowledge_version='v1')


def comp_request(instance='COMP1'):
    return {'name': f'{instance}_IO1', 'chip': 'py32f420', 'directives': [
        {'kind': 'field_symbol', 'peri': 'COMP', 'reg': 'CSR', 'instance': instance,
         'symbol': 'COMP_INPUT_PLUS_IO1'},
        {'kind': 'field_symbol', 'peri': 'COMP', 'reg': 'CSR', 'instance': instance,
         'symbol': 'COMP_INPUT_MINUS_IO1'},
        {'kind': 'enable_bit', 'peri': 'COMP', 'reg': 'CSR', 'instance': instance, 'field': 'EN'}]}


def mco_register_request():
    # This configures the RCC fields only; it does not claim to configure an output pin.
    return {'name': 'RCC_MCO_Fields', 'chip': 'py32f420', 'directives': [
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2},
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2PRE', 'value': 14}]}


@pytest.mark.parametrize('platform', ['chroma', 's100'])
@pytest.mark.parametrize('product', ['PT104', 'PCD009'])
def test_real_directives_compile_to_independent_excel(platform, product):
    from gui.assistant_swd import prepare_candidate
    artifact = prepare_candidate(mco_register_request(), product_profile_id=product,
                                 platform=platform, initial_state='reset')
    writes = [(row['addr'], row['data']) for row in artifact['rows'] if row['type'] == 'W']
    # Independent oracle: MCO2SEL=2 at bit24, MCO2PRE=14 at bit28.
    assert writes == [('0x40021014', '0xE2000000')]
    assert artifact['knowledgeVersion']
    assert artifact['validation']['staticRules'] == 'passed'


@pytest.mark.parametrize('instance', ['COMP1', 'COMP2'])
def test_incomplete_reset_knowledge_is_not_silently_zero_filled(instance):
    from gui.assistant_swd import CandidateError, prepare_candidate
    with pytest.raises(CandidateError, match='INCOMPLETE_COMPILATION'):
        prepare_candidate(comp_request(instance), product_profile_id='PT104',
                          platform='chroma', initial_state='reset')


def test_known_unresolved_address_conflict_never_exports():
    from gui.assistant_swd import CandidateError, prepare_candidate
    request = {'name': 'Conflict', 'chip': 'py32f420', 'directives': [
        {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CSR', 'field': 'NRST_FLTDIS', 'value': 1}]}
    with pytest.raises(CandidateError, match='MATERIAL_CONFLICT'):
        prepare_candidate(request, product_profile_id='PT104', platform='chroma', initial_state='reset')


def test_offline_cli_creates_files_and_refuses_overwrite(tmp_path):
    import json
    import subprocess
    import sys
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(mco_register_request()), encoding='utf-8')
    output = tmp_path / 'artifacts'
    command = [sys.executable, '-m', 'tools.assistant_offline', '--request', str(request),
               '--product', 'PT104', '--platform', 'chroma', '--initial-state', 'reset', '--output', str(output)]
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    first = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', env=environment)
    assert first.returncode == 0, first.stderr
    original = (output / 'configuration.xlsx').read_bytes()
    assert (output / 'RCC_MCO_Fields.pat').exists()
    second = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', env=environment)
    assert second.returncode != 0
    assert (output / 'configuration.xlsx').read_bytes() == original
