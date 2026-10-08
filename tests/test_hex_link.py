"""HEX links freeze a selected run and reuse the explicit Pattern resource seam."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import zipfile

import pytest

from gui.hex_workspace import HexWorkspace
from gui.swd_workspace import SwdWorkspace
from program_gen.core.swd_pattern import SwdPatternProducer
from program_gen.render_plan import ResourceRequirement


def workspace(tmp_path):
    session = SimpleNamespace(output=tmp_path, checked=None,
        editor=SimpleNamespace(sha256='book', raw=b'book'),
        scan=SimpleNamespace(candidate=lambda draft: (None, b'book')),
        links=[{'flowRow': 4, 'cp': 'CP3', 'item': 'DOWNLOAD', 'resourceSlots': [
            {'phase': '4', 'role': 'download', 'names': {'shared': ['target']}}]}])
    session.hex = HexWorkspace(tmp_path/'hex')
    run = session.hex.root/'task'/'run-one'
    output = run/'output'
    output.mkdir(parents=True)
    contents = {'input.pat': 'HEADER CLK,DATA,RST;\nSPM_PATTERN(input_swd) {\n*010* TS2;\n*111* STOP;\n}\n',
                'input.sd': 'HEAD[PIN_NAME]:\nCLK,DATA,RST;\nEND_HEAD;\nSTART:\nTIMING_SET G1_2;\n010;\nEND:\n111;\n'}
    with zipfile.ZipFile(run/'output.zip', 'w') as archive:
        for name, value in contents.items():
            (output/name).write_text(value, encoding='utf-8')
            archive.writestr(name, (output/name).read_bytes())
    session.hex.tasks['task'] = {'id': 'task', 'name': 'input.hex', 'status': 'completed', 'run': 'run-one',
        'profile': {'chip': 'PT104', 'id': 'swd-pt104', 'pins': ['CLK','DATA','RST'], 'verify': False},
        'summary': {'sha256': 'input-sha'}, 'result': {'files': [{'name': n} for n in contents]}}
    return session, SwdWorkspace(session)


def test_hex_link_freezes_selected_run_and_survives_clear_save_reload(tmp_path):
    session, links = workspace(tmp_path)
    target = links.targets()['targets'][0]
    links.link({'targetId': target['id'], 'hexTaskId': 'task', 'hexRun': 'run-one'})
    frozen = links.freeze()
    assert frozen[0]['sourceKind'] == 'hex'
    assert frozen[0]['pattern'] == 'input_swd'
    assert len(links.pattern_state()['generations']) == 1
    assert links.state()['generations'] == []  # SWD editor remains SWD-only.
    session.hex.clear()
    links.persist('saved')
    session.editor.sha256 = 'saved'
    restored = SwdWorkspace(session)
    assert restored.freeze() == frozen
    facts = SimpleNamespace(platform='chroma', cp='CP3', pins=[SimpleNamespace(name=n) for n in ['CLK','DATA','RST']])
    producer = SwdPatternProducer(frozen, None).for_target(facts)
    result = producer.produce(ResourceRequirement('pattern:target', 'pat/target.pat', 'test', purpose='Firmware download pattern'))
    assert b'SPM_PATTERN(target)' in result.content
    assert b'*010* TS2;' in result.content
    assert result.source_identity.startswith('hex:')
    with pytest.raises(ValueError, match='下载'):
        producer.produce(ResourceRequirement('pattern:target', 'pat/target.pat', 'test', purpose='other'))
    facts.pins = facts.pins[:2]
    with pytest.raises(ValueError, match='管脚'):
        SwdPatternProducer(frozen, None).for_target(facts)


def test_hex_link_rejects_stale_selection_and_non_download_slot(tmp_path):
    session, links = workspace(tmp_path)
    target = links.targets()['targets'][0]
    with pytest.raises(ValueError, match='版本'):
        links.link({'targetId': target['id'], 'hexTaskId': 'task', 'hexRun': 'run-old'})
    session.links[0]['resourceSlots'][0]['role'] = 'capture'
    target = links.targets()['targets'][0]
    with pytest.raises(ValueError, match='下载'):
        links.link({'targetId': target['id'], 'hexTaskId': 'task', 'hexRun': 'run-one'})
    assert links.freeze() == []


def test_hex_link_detects_modified_output_and_missing_target_platform(tmp_path):
    session, links = workspace(tmp_path)
    target = links.targets()['targets'][0]
    path = session.hex.root/'task'/'run-one'/'output'/'input.pat'
    original = path.read_bytes()
    path.write_bytes(original + b'changed')
    with pytest.raises(ValueError, match='变化|修改'):
        links.link({'targetId': target['id'], 'hexTaskId': 'task', 'hexRun': 'run-one'})
    path.write_bytes(original)
    session.hex.tasks['task']['result']['files'] = [{'name': 'input.pat'}]
    links.link({'targetId': target['id'], 'hexTaskId': 'task', 'hexRun': 'run-one'})
    with pytest.raises(ValueError, match='平台'):
        SwdPatternProducer(links.freeze(), None).for_target(SimpleNamespace(platform='s100', cp='CP3'))
    gen = links.pattern_state()['generations'][0]
    links.output(gen['id'], gen['files'][0]['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='修改|丢失'):
        links.freeze()


class PatternStateTests(unittest.TestCase):
    def test_exposes_only_current_workbook_links_and_swd_source_label(self):
        with TemporaryDirectory() as temp:
            session, links = workspace(Path(temp))
            document = {'id': 'steps', 'name': 'steps.xlsx', 'rows': [], 'patterns': []}
            links.data['documents'].append(document)
            links.data['generations'].append({
                'id': 'swd-generation', 'documentId': document['id'], 'pattern': 'PT104_demo',
                'revision': links._revision(document), 'files': [],
            })
            current = {'target': {'id': 'current-target'}, 'generationId': 'swd-generation'}
            other = {'target': {'id': 'other-target'}, 'generationId': 'swd-generation'}
            links.data['links'] = {'book': [current], 'another-workbook': [other]}

            state = links.pattern_state()

            generation = next(gen for gen in state['generations'] if gen['id'] == 'swd-generation')
            self.assertEqual(generation['sourceKind'], 'swd')
            self.assertEqual(generation['sourceLabel'], 'steps.xlsx')
            self.assertFalse(generation['stale'])
            self.assertEqual(state['links'], [current])
            self.assertNotIn(other, state['links'])

            session.editor = None
            self.assertEqual(links.pattern_state()['links'], [])


def test_hex_s100_assembly_maps_erase_program_by_purpose_without_changing_vectors():
    raw = b'TIMING_SET G1_5;\n010;\nTIMING_SET G1_6;\n111;\n'
    binding = {'cp': 'CP3', 'names': {'shared': ['target']}, 'pattern': 'source',
               'identity': 'hex-run', 'sourceKind': 'hex', 'timingOrigin': 'chroma',
               'contents': {'s100': raw}}
    producer = SwdPatternProducer([binding], None, platform='s100', cp='CP3')
    result = producer.produce(ResourceRequirement('pattern:target', 'target.sd', 'test', purpose='Firmware download pattern'))
    assert result.content == b'TIMING_SET G1_4;\n010;\nTIMING_SET G1_5;\n111;\n'
    assert producer.timing_sets([ResourceRequirement('pattern:target', 'target.sd', 'test')]) == ('G1_4','G1_5')
