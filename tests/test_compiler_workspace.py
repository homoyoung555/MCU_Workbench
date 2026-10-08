"""Folder imports and real queue boundaries; vendor processes are the external seam."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import threading
import sys
from unittest.mock import patch

from gui.compiler_workspace import CompilerWorkspace


class CompilerWorkspaceTests(unittest.TestCase):
    def test_clear_history_persists_without_deleting_files_and_blocks_busy_tasks(self):
        with TemporaryDirectory() as directory:
            workspace = CompilerWorkspace(Path(directory))
            task = workspace.create({'name': 'demo'})
            identity = task['id']
            with self.assertRaises(ValueError):
                workspace.clear_history({})
            workspace.add_file(identity, 'demo.prj', b'original')
            workspace.ready({'id': identity})
            log = Path(directory) / identity / 'compile.log'
            log.write_bytes(b'old log')
            workspace.tasks[identity]['status'] = 'running'
            with self.assertRaises(ValueError):
                workspace.clear_history({})
            workspace.tasks[identity]['status'] = 'passed'
            self.assertEqual(workspace.clear_history({})['tasks'], [])
            self.assertEqual(CompilerWorkspace(Path(directory)).state()['tasks'], [])
            self.assertEqual(log.read_bytes(), b'old log')
            self.assertEqual((Path(directory)/identity/'source/demo.prj').read_bytes(), b'original')
            new = workspace.create({'name': 'new'})
            self.assertEqual(workspace.state()['tasks'][0]['id'], new['id'])

    def test_chroma_pat_only_preserves_dec_and_rejects_stale_pattern(self):
        from gui.compiler_runner import compile_program
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder/'pat').mkdir()
            for name in ('demo.pln', 'demo.pin', 'pat/pin.dec', 'pat/a.pat', 'pat/pin_0.pinmap', 'pat/pin_pat.ppo'):
                (folder/name).write_bytes(b'old')
            tools = {'chroma': {'available': True, 'path': directory}}
            def vendor(command, cwd, env, log):
                self.assertTrue(str(command[0]).endswith('patcmp.exe'))
                self.assertEqual((folder/'pat/pin_0.pinmap').read_bytes(), b'old')
                (folder/'pat/pin_pat.ppo').write_bytes(b'new')
                return 0, 'Errors : 0'
            with patch('gui.compiler_runner.tool_status', return_value=tools):
                with patch('gui.compiler_runner.run_command', return_value=(0, 'Errors : 0')):
                    self.assertFalse(compile_program(folder, 'chroma', 'demo.pln', folder/'log', lambda _: None, mode='pat')['ok'])
                with patch('gui.compiler_runner.run_command', side_effect=vendor) as run:
                    self.assertTrue(compile_program(folder, 'chroma', 'demo.pln', folder/'log', lambda _: None, mode='pat')['ok'])
                    self.assertEqual(run.call_count, 1)
                self.assertEqual((folder/'demo.pin').read_bytes(), b'old')

    def test_partial_s100_requires_fresh_mode_output_not_an_old_gsw(self):
        from contextlib import nullcontext
        from gui.compiler_runner import compile_program
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ('program/demo.PJ', 'program/demo.pn', 'program/demo.gsw', 'program/demo.PG', 'pattern_ddr2/a.lmr', 'timing_ddr2/demo.ts2'):
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'old')
            tools = {'s100': {'available': True, 'path': directory}}
            def vendor(command, cwd, env, log):
                self.assertIn('-g', command)
                (folder / 'program/demo.PG').write_bytes(b'fresh program output')
                (folder / 'program/demo.dll').write_bytes(b'fresh library')
                return 0, 'Program process Ok!\nErrors : 0\nWarnings : 0'
            with patch('gui.compiler_runner.tool_status', return_value=tools), patch('gui.compiler_runner.s100.compiler_environment', return_value=nullcontext((directory, {}))):
                with patch('gui.compiler_runner.run_command', return_value=(0, 'Errors : 0')):
                    self.assertFalse(compile_program(folder, 's100', 'demo.prj', folder/'log', lambda _: None, mode='prg')['ok'])
                with patch('gui.compiler_runner.run_command', side_effect=vendor):
                    self.assertTrue(compile_program(folder, 's100', 'demo.prj', folder/'log', lambda _: None, mode='prg')['ok'])
                self.assertEqual((folder/'program/demo.gsw').read_bytes(), b'old')

    def test_modes_are_validated_atomically_and_partial_runs_reuse_only_success(self):
        with TemporaryDirectory() as directory:
            calls = []
            def run(folder, platform, entry, log, progress, mode='all'):
                calls.append((mode, (folder / 'dependency').read_text() if (folder / 'dependency').exists() else None))
                (folder / 'dependency').write_text(mode)
                return {'ok': mode != 'prg', 'stages': [], 'diagnostics': []}
            workspace = CompilerWorkspace(Path(directory), runner=run)
            task = workspace.create({'name': 'demo'})
            identity = task['id']
            workspace.add_file(identity, 'demo.prj', b'project')
            workspace.ready({'id': identity})
            with self.assertRaises(ValueError):
                workspace.start({'ids': [identity], 'modes': {identity: 'pln'}})
            self.assertEqual(workspace.tasks[identity]['status'], 'ready')
            for mode in ('all', 'prj_prg', 'prg', 'pat', 'all'):
                workspace.start({'ids': [identity], 'modes': {identity: mode}})
                workspace.worker.join(5)
                self.assertFalse(workspace.worker.is_alive())
            self.assertEqual(calls, [('all', None), ('prj_prg', 'all'), ('prg', 'prj_prg'), ('pat', 'prj_prg'), ('all', None)])
            restored = CompilerWorkspace(Path(directory))
            self.assertEqual(restored.tasks[identity]['mode'], 'all')

    def test_s100_relocated_config_is_used_during_compile_and_restored_on_failure(self):
        from gui.compiler_runner import compile_program
        from tools.s100_compiler import short_path
        with TemporaryDirectory() as directory:
            home = Path(directory) / 'toolchain'
            (home / 'S100').mkdir(parents=True)
            (home / 'BCB6/Bin').mkdir(parents=True)
            (home / 'S100/YT5100_Pre.exe').touch()
            (home / 'BCB6/Bin/bcc32.exe').touch()
            cfg = home / 'BCB6/Bin/bcc32.cfg'
            original = b'-I"Z:/old/Include"\n'
            cfg.write_bytes(original)
            folder = Path(directory) / 'program'
            folder.mkdir()
            (folder / 'sample.prj').write_text('project')
            def failing_vendor(command, cwd, env, log):
                configured_home = Path(command[0]).parent.parent
                current = (configured_home / 'BCB6/Bin/bcc32.cfg').read_text()
                self.assertNotIn('Z:/old', current)
                self.assertIn(short_path(str(configured_home / 'BCB6')), current)
                raise RuntimeError('vendor failed')
            with patch('gui.compiler_runner.tool_status', return_value={'s100': {'available': True, 'path': str(home)}}), patch('gui.compiler_runner.run_command', side_effect=failing_vendor):
                with self.assertRaisesRegex(RuntimeError, 'vendor failed'):
                    compile_program(folder, 's100', 'sample.prj', Path(directory) / 'log', lambda _: None)
            self.assertEqual(cfg.read_bytes(), original)

    def test_chroma_split_line_error_keeps_file_and_line(self):
        from gui.compiler_runner import diagnostics
        output = '<< File:[pin.dec] Line:[1] Last_Token:[bad] >>\n    Message:[parse error]\n'
        found = diagnostics(output)
        self.assertEqual((found[0]['file'], found[0]['line']), ('pin.dec', 1))

    def test_compiler_process_logs_both_streams_and_reports_timeout(self):
        from gui.compiler_runner import run_command
        import os
        with TemporaryDirectory() as directory:
            log = Path(directory) / 'compiler.log'
            rc, output = run_command([sys.executable, '-c', 'import sys; print("OUT"); print("ERR", file=sys.stderr)'], directory, dict(os.environ), log)
            self.assertEqual(rc, 0)
            self.assertIn('OUT', output)
            self.assertIn('ERR', log.read_text(encoding='utf-8'))
            rc, output = run_command([sys.executable, '-c', 'import time; time.sleep(10)'], directory, dict(os.environ), log, timeout=.05)
            self.assertEqual(rc, 124)
            self.assertIn('超时', output)

    def test_interrupted_upload_is_not_compilable_and_running_restart_needs_explicit_retry(self):
        import json
        with TemporaryDirectory() as directory:
            workspace = CompilerWorkspace(Path(directory))
            incomplete = workspace.create({'name': 'incomplete'})
            task = workspace.create({'name': 'was-running'})
            workspace.add_file(task['id'], 'a.prj', b'a')
            workspace.ready({'id': task['id']})
            metadata = Path(directory) / task['id'] / 'task.json'
            value = json.loads(metadata.read_text(encoding='utf-8'))
            value['status'] = 'running'
            metadata.write_text(json.dumps(value), encoding='utf-8')
            restored = CompilerWorkspace(Path(directory))
            self.assertEqual([t['status'] for t in restored.state()['tasks']], ['interrupted', 'interrupted'])
            self.assertFalse(restored.state()['running'])
            with self.assertRaises(ValueError):
                restored.start({'ids': [incomplete['id']]})

    def test_chroma_old_outputs_never_count_as_success_and_log_has_actionable_location(self):
        from gui.compiler_runner import compile_program, diagnostics
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'pat').mkdir()
            for name in ('main.pln', 'main.pin', 'pat/pin.dec', 'pat/a.pat', 'pat/pin_0.pinmap', 'pat/pin_pat.ppo'):
                (folder / name).write_bytes(b'old')
            tools = {'chroma': {'path': directory, 'available': True}}
            with patch('gui.compiler_runner.tool_status', return_value=tools), patch('gui.compiler_runner.run_command', return_value=(0, 'no compilation')):
                result = compile_program(folder, 'chroma', 'main.pln', folder / 'compile.log', lambda _: None)
            self.assertFalse(result['ok'])
            self.assertIn('pinmap', str(result))
            found = diagnostics('sample.PRG 42 : Unknown \'value[index]\' !\n--> Error!!! C Compiler not found, Program compile failed.\nWarnings : 0\nErrors : 1')
            self.assertEqual((found[0]['file'], found[0]['line']), ('sample.PRG', 42))
            self.assertIn('编译器', found[1]['advice'])
            self.assertEqual(len(found), 2)

    def test_serial_queue_continues_after_failure_and_preserves_results_on_restart(self):
        with TemporaryDirectory() as directory:
            calls = []
            entered, release = threading.Event(), threading.Event()
            def run(folder, platform, entry, log, progress, mode='all'):
                calls.append(entry)
                if len(calls) == 1:
                    entered.set()
                    release.wait(5)
                    raise RuntimeError('first failed')
                log.write_text('done', encoding='utf-8')
                return {'ok': True, 'stages': [], 'diagnostics': [], 'outputAvailable': False}
            workspace = CompilerWorkspace(Path(directory), runner=run)
            ids = []
            for name in ('first', 'second'):
                task = workspace.create({'name': name})
                workspace.add_file(task['id'], name + '.prj', b'project')
                workspace.ready({'id': task['id']})
                ids.append(task['id'])
            workspace.start({'ids': ids})
            self.assertTrue(entered.wait(3))
            self.assertEqual(calls, ['first.prj'])
            with self.assertRaises(ValueError):
                workspace.start({'ids': ids})
            release.set()
            workspace.worker.join(5)
            self.assertFalse(workspace.worker.is_alive())
            self.assertEqual(calls, ['first.prj', 'second.prj'])
            self.assertEqual([t['status'] for t in workspace.state()['tasks']], ['failed', 'passed'])
            restarted = CompilerWorkspace(Path(directory))
            self.assertEqual([t['status'] for t in restarted.state()['tasks']], ['failed', 'passed'])
            self.assertIn('first failed', restarted.log(ids[0])['text'])

    def test_folder_import_preserves_paths_and_rejects_escape_and_ambiguous_entries(self):
        with TemporaryDirectory() as directory:
            workspace = CompilerWorkspace(Path(directory))
            task = workspace.create({'name': '用户程序'})
            for bad in ('../escape', '/absolute', 'C:/evil', 'pat/../evil', 'file:stream', 'CON.txt'):
                with self.assertRaises(ValueError, msg=bad):
                    workspace.add_file(task['id'], bad, b'x')
            workspace.add_file(task['id'], 'main.pln', b'plan')
            workspace.add_file(task['id'], 'pat/pin.dec', b'dec')
            workspace.add_file(task['id'], 'pat/a.pat', b'pattern')
            ready = workspace.ready({'id': task['id']})
            self.assertEqual((ready['status'], ready['platform']), ('ready', 'chroma'))
            self.assertEqual((Path(directory) / task['id'] / 'source/pat/a.pat').read_bytes(), b'pattern')
            with self.assertRaises(ValueError):
                workspace.add_file(task['id'], 'late.pat', b'late')
            other = workspace.create({'name': 'multiple'})
            workspace.add_file(other['id'], 'a.pln', b'a')
            workspace.add_file(other['id'], 'b.pln', b'b')
            with self.assertRaisesRegex(ValueError, '入口'):
                workspace.ready({'id': other['id']})


if __name__ == '__main__':
    unittest.main()
