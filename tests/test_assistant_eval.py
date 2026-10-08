import json
from pathlib import Path

import pytest

from gui.assistant_edits import prepare_edit
from gui.assistant_swd import prepare_candidate
from tools.assistant_eval import assess, context


CASES = json.loads((Path(__file__).parent / 'fixtures/assistant-eval-v1.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', [case for case in CASES if case['expect'] in ('new', 'edit')], ids=lambda case: case['id'])
def test_frozen_success_cases_have_executable_deterministic_oracles(case):
    if case['expect'] == 'new':
        candidate = prepare_candidate({'chip': 'py32f420', 'name': 'Eval', 'directives': [
            {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2},
            {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2PRE', 'value': 14}]},
            product_profile_id=case.get('product', 'PT104'), platform=case['platform'], initial_state='reset')
    else:
        candidate = prepare_edit(context(case)['swd'], [{'rowIndex': 0, 'peripheral': 'RCC',
            'register': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}])
    assert assess(case, {'status': 'completed', 'candidates': [candidate]}) == 'artifact_constraints_passed_needs_review'
