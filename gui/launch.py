"""Start/reuse the local GUI. --no-browser is for command-line verification."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8765/'


def running():
    try:
        with urlopen(URL,timeout=2) as response:
            return b'MCU PROGRAM WORKSPACE' in response.read()
    except Exception:
        return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if not running():
        log=Path(tempfile.gettempdir())/'mcu-gui-8765.log'
        with log.open('w',encoding='utf-8') as stream:
            process=subprocess.Popen([sys.executable,'-B',str(ROOT/'gui/server.py'),'--port','8765'],
                                     cwd=ROOT,stdout=stream,stderr=stream,stdin=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        deadline=time.monotonic()+75
        while time.monotonic()<deadline:
            if running():break
            if process.poll() is not None:
                raise RuntimeError('GUI未能启动，请查看日志：'+str(log)+'\n'+log.read_text(encoding='utf-8')[-2000:])
            time.sleep(.5)
        else:
            raise RuntimeError('GUI仍在启动，请稍后重试；日志：'+str(log))
    if not args.no_browser:webbrowser.open(URL)
    print(URL)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
