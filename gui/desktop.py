"""WebView2 desktop host; the existing local GUI remains the application."""
import argparse
import html
import json
import os
import tempfile
from pathlib import Path
import sys
import threading
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.paths import RESOURCE_ROOT, WORKSPACE_ROOT


class DesktopBridge:
    def __init__(self, create_window, main, get_session=None):
        self._create = create_window
        self._main = main
        self._get_session = get_session
        self._save_lock = threading.Lock()
        self._save_directory = None
        self._preview = None
        self._assistant = None
        self._assistant_origin = None
        self._lock = threading.RLock()
        self._busy = False
        self._closed = False
        self._snapshot = {'sequence': -1, 'status': '请选择FLOW测试项', 'code': '', 'errors': ''}

    def publish_preview(self, snapshot):
        if (not isinstance(snapshot, dict) or type(snapshot.get('sequence')) is not int
                or any(not isinstance(snapshot.get(key), str) for key in ('status', 'code', 'errors'))
                or any(len(snapshot[key]) > 600000 for key in ('status', 'code', 'errors'))):
            raise ValueError('无效的代码预览快照')
        with self._lock:
            if snapshot['sequence'] > self._snapshot['sequence']:
                self._snapshot = {key: snapshot[key] for key in self._snapshot}

    def get_preview(self):
        with self._lock:
            return dict(self._snapshot)

    def set_busy(self, busy):
        if type(busy) is not bool:
            raise ValueError('无效的操作状态')
        self._busy = busy

    def select_scan_files(self):
        import webview
        paths = self._main.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                              file_types=('WGL files (*.wgl)',))
        return [{'path': str(Path(p).resolve()), 'name': Path(p).name} for p in paths or []]

    def save_workbook(self, payload, checked=False):
        """Only the native picker authorizes a destination outside managed outputs."""
        import webview
        if not isinstance(payload, dict) or type(checked) is not bool:
            raise ValueError('无效的另存请求')
        if not self._save_lock.acquire(blocking=False):
            raise ValueError('正在另存工作簿，请等待当前操作完成')
        try:
            session = self._get_session() if self._get_session else None
            editor = session.editor if session else None
            if editor is None:
                raise ValueError('请先载入工作簿')
            editor.ensure_source_current()
            source = editor.source_path
            directory = self._save_directory or (source.parent if source else WORKSPACE_ROOT)
            suffix = '_checked.xlsx' if checked else '_draft.xlsx'
            paths = self._main.create_file_dialog(webview.FileDialog.SAVE, directory=str(directory),
                save_filename=Path(editor.name).stem + suffix, file_types=('Excel workbook (*.xlsx)',))
            if not paths:
                return {'cancelled': True}
            path = Path(paths[0]).resolve()
            if path.suffix.lower() != '.xlsx':
                raise ValueError('另存文件名请使用 .xlsx 后缀')
            if source and (path == source.resolve() or path.exists() and path.samefile(source)):
                raise ValueError('另存副本请选择与已载入源文件不同的位置或文件名')
            if self._get_session() is not session or session.editor is not editor:
                raise ValueError('工作簿已切换，请重新另存')
            result = session.save(payload) if checked else session.save_draft(payload)
            raw = Path(result['path']).read_bytes()
            # The native SaveFileDialog owns overwrite confirmation. Replace only
            # after the complete copy is written, so an I/O error retains the old file.
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.mcu-save-', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self._save_directory = path.parent
            return {**result, 'path': str(path)}
        finally:
            self._save_lock.release()

    def open_preview(self):
        with self._lock:
            if self._closed:
                raise ValueError('主窗口已关闭')
            if self._preview is not None:
                self._preview.restore()
                self._preview.show()
                return True
            window = self._create('当前测试项代码 · MCU 工作台',
                                  html=(RESOURCE_ROOT / 'gui/desktop_preview.html').read_text(encoding='utf-8'),
                                  js_api=self, width=1000, height=740, min_size=(480, 320))
            self._preview = window
            window.events.closed += lambda: self._preview_closed(window)
            return True

    def open_assistant(self):
        with self._lock:
            if self._closed or not self._assistant_origin:
                raise ValueError('工作台尚未就绪或已关闭')
            if self._assistant is not None:
                self._assistant.restore()
                self._assistant.show()
                return True
            window = self._create('AI 助手 · MCU 工作台', url=self._assistant_origin + '/assistant',
                                  js_api=self, width=1000, height=820, min_size=(640, 480))
            self._assistant = window
            window.events.closed += lambda: self._assistant_closed(window)
            return True

    def _assistant_closed(self, window):
        with self._lock:
            if self._assistant is window:
                self._assistant = None

    def assistant_context(self, prepare_editor=False):
        if self._closed:
            raise ValueError('主窗口已关闭')
        if prepare_editor:
            self._main.evaluate_js('window.MCUWorkbench.open("swd")')
        value = self._main.evaluate_js('window.MCUWorkbench.assistantContext()')
        if not isinstance(value, dict):
            raise ValueError('无法读取当前草稿，请等待主窗口就绪')
        return value

    def receive_assistant(self, value):
        if self._closed or not isinstance(value, dict):
            raise ValueError('主窗口不可用')
        return self._main.evaluate_js('window.MCUWorkbench.receiveAssistant(' + json.dumps(value, ensure_ascii=True) + ')')

    def undo_assistant(self):
        if self._closed:
            raise ValueError('主窗口已关闭')
        return self._main.evaluate_js('window.MCUWorkbench.undoAssistant()')

    def assistant_job(self, value):
        if self._closed or not isinstance(value, dict) or value.get('page') not in ('program', 'hex', 'scan'):
            raise ValueError('工作台任务不可用')
        return self._main.evaluate_js('window.MCUWorkbench.assistantJob(' + json.dumps(value, ensure_ascii=True) + ')')

    def _preview_closed(self, window):
        with self._lock:
            if self._preview is window:
                self._preview = None
            closed = self._closed
        if not closed:
            self._main.evaluate_js('window.desktopPreviewClosed?.()')

    def _close(self):
        with self._lock:
            self._closed = True
            window = self._preview
            assistant = self._assistant
        if window is not None:
            window.destroy()
        if assistant is not None:
            assistant.destroy()


class DesktopApp:
    def __init__(self, webview, self_test=None, self_test_scope='all'):
        self.webview = webview
        self.self_test = self_test
        self.self_test_scope = self_test_scope
        self.service = None
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.error = None
        self.bridge = DesktopBridge(webview.create_window, None, lambda: self.service.session if self.service else None)
        self.window = webview.create_window('MCU 工作台 V0.5',
            html='<meta charset="utf-8"><p style="font:18px Microsoft YaHei;padding:40px">正在启动 MCU 程序工作台，请稍候…</p>',
            js_api=self.bridge, width=1440, height=900, min_size=(900, 650),
            confirm_close=not bool(self_test))
        self.bridge._main = self.window
        self.window.events.closing += self._can_close
        self.window.events.closed += self._closed

    def _can_close(self):
        job = self.service.session.job if self.service else None
        scan = getattr(self.service, 'scan', None)
        compiler = getattr(self.service, 'compiler', None)
        hex_jobs = getattr(self.service, 'hex', None)
        if self.bridge._busy or job and job.get('status') == 'running' or scan and scan.job and scan.job.get('status') == 'running' or compiler and compiler.state()['running'] or hex_jobs and hex_jobs.state()['running']:
            # The closing callback runs while the UI thread waits; never evaluate JS here.
            return False

    def _closed(self):
        self.closed.set()
        self.bridge._close()
        if self.service:
            if getattr(self.service, 'assistant', None):
                self.service.assistant.close()
            self.service.shutdown()
            self.service.server_close()

    def _start(self):
        try:
            # Keep packaged UI and backend together; port 8765 may run an older build.
            # Each desktop owns its session and never interrupts another window's drafts.
            from gui.server import make_server
            self.service = make_server(0, empty=True, compiler_enabled=self.self_test_scope == 'compiler' and bool(self.self_test))
            threading.Thread(target=self.service.serve_forever, daemon=True).start()
            origin = self.service.origin
            self.bridge._assistant_origin = origin
            if self.closed.is_set():
                if self.service:
                    self.service.shutdown()
                    self.service.server_close()
                return
            self.window.load_url(origin)
        except Exception:
            self.error = traceback.format_exc()
            log = WORKSPACE_ROOT / 'logs/gui-desktop-error.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(self.error, encoding='utf-8')
            try:
                self.window.load_html('<meta charset="utf-8"><h2>工作台启动失败</h2><pre>' + html.escape(self.error) + '</pre>')
            except Exception:
                # A crashed WebView cannot display its own failure; retain the original log.
                pass
        finally:
            self.ready.set()

    def run(self):
        self.webview.settings['ALLOW_DOWNLOADS'] = True
        def started():
            self._start()
            if self.self_test:
                if self.self_test_scope == 'assistant':
                    from gui.assistant_smoke import run_smoke
                elif self.self_test_scope == 'compiler':
                    from gui.compiler_smoke import run_smoke
                elif self.self_test_scope == 'hex':
                    from gui.hex_smoke import run_smoke
                else:
                    from gui.desktop_smoke import run_smoke
                run_smoke(self, self.self_test)
        storage = (self.self_test.parent / 'webview-profile' if self.self_test else
                   WORKSPACE_ROOT / 'cache/gui-desktop')
        self.webview.start(started, gui='edgechromium', private_mode=bool(self.self_test),
            storage_path=str(storage), localization={
                'global.quitConfirmation': '确定退出工作台吗？请先另存需要保留的 Excel 草稿。',
                'global.quit': '退出工作台', 'global.cancel': '取消'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', type=Path, help='Run isolated desktop acceptance and write JSON evidence')
    parser.add_argument('--self-test-scope', choices=('all', 'compiler', 'hex', 'assistant'), default='all')
    args = parser.parse_args()
    if args.self_test:
        args.self_test = args.self_test.resolve()
        args.self_test.parent.mkdir(parents=True, exist_ok=True)
    import webview
    DesktopApp(webview, args.self_test, args.self_test_scope).run()
    if args.self_test and not json.loads(args.self_test.read_text(encoding='utf-8'))['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
