"""Run with the dedicated desktop venv to build MCU_Workbench_App/MCU_Workbench_App.exe."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.Codex/tmp/desktop-build'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distpath', type=Path, default=ROOT)
    parser.add_argument('--buildpath', type=Path, default=BUILD)
    args = parser.parse_args()
    BUILD = args.buildpath.resolve()
    BUILD.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(BUILD / 'cache'))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--onedir', '--windowed',
        '--name', 'MCU_Workbench_App', '--distpath', str(args.distpath.resolve()), '--workpath', str(BUILD / 'work'),
        '--specpath', str(BUILD), '--paths', str(ROOT), '--collect-submodules', 'program_gen',
        '--add-data', str(ROOT / 'gui/index.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/workbench.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/workbench.js') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/workbench.css') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/swd.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/swd.js') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/compiler.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/compiler.js') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/hex.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/hex.js') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/data/py32f420_svd_cache.json') + os.pathsep + 'gui/data',
        '--add-data', str(ROOT / 'gui/desktop_preview.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/assistant.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'gui/assistant.js') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'swd_authoring/data') + os.pathsep + 'swd_authoring/data',
        '--add-data', str(ROOT / 'swd_authoring/schema') + os.pathsep + 'swd_authoring/schema',
        '--add-data', str(ROOT / 'gui/使用说明.html') + os.pathsep + 'gui',
        '--add-data', str(ROOT / 'tools') + os.pathsep + 'tools',
        '--exclude-module', 'PyQt5', '--exclude-module', 'PyQt6',
        '--exclude-module', 'PySide2', '--exclude-module', 'PySide6',
        str(ROOT / 'gui/desktop.py')], cwd=ROOT, env=environment, check=True)
