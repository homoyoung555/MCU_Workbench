"""Migration contracts: source/frozen paths and the complete workbench bundle."""
import os
from pathlib import Path
import runpy
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class WorkbenchMigrationTests(unittest.TestCase):
    def test_source_defaults_to_independent_workspace(self):
        with patch.dict(os.environ, {}, clear=True):
            values = runpy.run_path(str(ROOT / 'gui/paths.py'))
        self.assertEqual(values['WORKSPACE_ROOT'], ROOT.parent / 'MCU_Workbench_WORKSPACE')

    def test_explicit_workspace_override(self):
        target = ROOT.parent / 'custom-workbench-data'
        with patch.dict(os.environ, {'MCU_WORKBENCH_WORKSPACE': str(target)}, clear=True):
            values = runpy.run_path(str(ROOT / 'gui/paths.py'))
        self.assertEqual(values['WORKSPACE_ROOT'], target)

    def test_frozen_bundle_uses_workspace_beside_distribution_root(self):
        distribution = ROOT.parent / 'portable-workbench'
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(distribution / 'MCU_Workbench_App/MCU_Workbench_App.exe')):
            values = runpy.run_path(str(ROOT / 'gui/paths.py'))
        self.assertEqual(values['WORKSPACE_ROOT'], distribution.parent / 'MCU_Workbench_WORKSPACE')

    def test_build_includes_all_workbench_assets(self):
        with TemporaryDirectory() as folder, patch.object(sys, 'argv', ['build_desktop.py', '--buildpath', folder]), patch('subprocess.run') as run:
            runpy.run_path(str(ROOT / 'gui/build_desktop.py'), run_name='__main__')
        command = run.call_args.args[0]
        for asset in ('workbench.html', 'workbench.js', 'workbench.css'):
            self.assertIn(str(ROOT / 'gui' / asset) + os.pathsep + 'gui', command)
        self.assertEqual(command[command.index('--name') + 1], 'MCU_Workbench_App')
