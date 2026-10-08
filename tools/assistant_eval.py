"""Run the frozen assistant sample with an explicitly supplied provider key."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gui.assistant_model import ModelClient, ModelConfig
from gui.assistant_tasks import AssistantTasks


def context(case):
    if case['expect'] != 'edit':
        return {}
    return {'swd': {'document': {'id': 'eval-source', 'name': 'manual.xlsx', 'rows': []},
                    'popupDraft': {'documentId': 'eval-source', 'rows': [
                        {'row': 2, 'pattern': 'Manual', 'type': 'W', 'step': '/', 'addr': '0x40021014',
                         'data': '0xE1000000', 'description': '保留人工备注'},
                        {'row': 3, 'pattern': 'Manual', 'type': 'WAIT', 'step': '/', 'addr': '/',
                         'data': '100', 'description': '保留人工等待'}]}}}


def assess(case, result):
    candidates = result['candidates']
    if result['status'] != 'completed':
        return 'failed'
    if case['expect'] == 'review':
        return 'needs_review' if not candidates else 'failed'
    if case['expect'] == 'refuse':
        return 'refusal_needs_review' if not candidates else 'failed'
    if len(candidates) != 1:
        return 'failed'
    candidate = candidates[0]
    if not candidate.get('rows') or candidate['rows'][0]['data'] != case['data']:
        return 'failed'
    if case['expect'] == 'new':
        if len(candidate['rows']) != 1 or candidate['rows'][0]['addr'] != '0x40021014':
            return 'failed'
        if candidate['productProfileId'] != case.get('product', 'PT104') or candidate['platform'] != case['platform']:
            return 'failed'
    else:
        original = context(case)['swd']['popupDraft']['rows']
        expected = [{**original[0], 'data': case['data']}, original[1]]
        if candidate.get('kind') != 'edit' or candidate['rows'] != expected:
            return 'failed'
    return 'artifact_constraints_passed_needs_review'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly enable paid API calls')
    parser.add_argument('--provider', choices=('deepseek', 'kimi'))
    parser.add_argument('--model')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--repeats', type=int, default=1)
    args = parser.parse_args()
    fixture = ROOT / 'tests/fixtures/assistant-eval-v1.json'
    raw = fixture.read_bytes()
    cases = json.loads(raw)['cases']
    if args.case:
        unknown = set(args.case) - {case['id'] for case in cases}
        if unknown:
            parser.error('Unknown case: ' + ','.join(sorted(unknown)))
        cases = [case for case in cases if case['id'] in args.case]
    if not args.run:
        print(json.dumps({'callsMade': 0, 'fixtureSha256': hashlib.sha256(raw).hexdigest(),
                          'cases': [case['id'] for case in cases]}, ensure_ascii=False, indent=2))
        return
    if not args.provider or not args.model or not args.output or not 1 <= args.repeats <= 10:
        parser.error('--run requires provider, model, fresh output, and repeats between 1 and 10')
    key = os.environ.get('DEEPSEEK_API_KEY' if args.provider == 'deepseek' else 'MOONSHOT_API_KEY')
    if not key:
        parser.error('Provide the selected provider API key in its environment variable; no saved keys are searched')
    args.output.mkdir(parents=True, exist_ok=False)
    tasks = AssistantTasks(args.output / 'tasks')
    report = {'fixtureSha256': hashlib.sha256(raw).hexdigest(), 'provider': args.provider,
              'model': args.model, 'results': [], 'notice': 'Automatic constraints are not overall task success or hardware verification'}
    try:
        for repeat in range(args.repeats):
            for case in cases:
                payload = {'requestId': case['id'] + '-' + str(repeat), 'text': case['question'], 'context': context(case),
                           'conditions': {'product': case.get('product', 'PT104'), 'platform': case.get('platform', 'chroma'),
                                          'initialState': case.get('initialState', 'reset')}}
                identity = tasks.start(payload, ModelClient(ModelConfig(args.provider, args.model, key)))['id']
                deadline = time.monotonic() + 600
                while tasks.get(identity)['status'] == 'running' and time.monotonic() < deadline:
                    time.sleep(.2)
                if tasks.get(identity)['status'] == 'running':
                    tasks.cancel(identity)
                result = tasks.get(identity)
                report['results'].append({'case': case['id'], 'repeat': repeat, 'taskId': identity,
                                          'assessment': assess(case, result), 'metrics': result.get('metrics')})
                (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(case['id'], report['results'][-1]['assessment'], flush=True)
    finally:
        tasks.close()


if __name__ == '__main__':
    main()
