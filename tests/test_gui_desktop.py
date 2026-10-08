"""Desktop window lifecycle without a native UI dependency."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from gui.desktop import DesktopApp, DesktopBridge


class Event:
    def __iadd__(self, callback):
        self.callback = callback
        return self


class Window:
    def __init__(self):
        self.events = SimpleNamespace(closed=Event(), closing=Event())
        self.scripts = []
        self.shown = 0

    def evaluate_js(self, script):
        self.scripts.append(script)

    def restore(self):
        self.shown += 1

    def show(self):
        self.shown += 1

    def destroy(self):
        self.events.closed.callback()


class DesktopTests(unittest.TestCase):
    def test_assistant_is_singleton_reopens_and_closes_with_main(self):
        windows = []
        def create(*args, **kwargs):
            self.assertEqual(kwargs['url'], 'http://127.0.0.1:5555/assistant')
            window = Window()
            windows.append(window)
            return window
        bridge = DesktopBridge(create, Window())
        bridge._assistant_origin = 'http://127.0.0.1:5555'
        bridge.open_assistant()
        bridge.open_assistant()
        self.assertEqual(len(windows), 1)
        windows[0].destroy()
        bridge.open_assistant()
        self.assertEqual(len(windows), 2)
        bridge._close()
        self.assertIsNone(bridge._assistant)
        with self.assertRaises(ValueError):
            bridge.open_assistant()

    def test_desktop_allows_downloads_before_starting_webview(self):
        settings = {'ALLOW_DOWNLOADS': False}
        def start(*args, **kwargs):
            self.assertTrue(settings['ALLOW_DOWNLOADS'], 'WebView otherwise silently cancels downloads')
        app = DesktopApp(SimpleNamespace(create_window=lambda *a, **k: Window(), settings=settings, start=start))
        app.run()

    def test_desktop_owns_current_backend_even_when_old_service_is_running(self):
        window = Window()
        window.load_url = lambda url: setattr(window, 'url', url)
        app = DesktopApp(SimpleNamespace(create_window=lambda *a, **k: window))
        service = SimpleNamespace(origin='http://127.0.0.1:54321', serve_forever=lambda: None)
        with patch('gui.launch.running', return_value=True), patch('gui.server.make_server', return_value=service) as make:
            app._start()
        make.assert_called_once_with(0, empty=True, compiler_enabled=False)
        self.assertIs(app.service, service)
        self.assertEqual(window.url, service.origin)
        self.assertIsNone(app.error)

    def test_preview_survives_close_and_reopen_and_rejects_late_updates(self):
        windows = []
        def create(*args, **kwargs):
            window = Window()
            windows.append(window)
            return window
        main = Window()
        bridge = DesktopBridge(create, main)
        bridge.publish_preview({'sequence': 2, 'status': 'FLOW 4', 'code': 'new', 'errors': ''})
        bridge.open_preview()
        bridge.open_preview()
        self.assertEqual(len(windows), 1)
        bridge.publish_preview({'sequence': 1, 'status': 'old', 'code': 'old', 'errors': ''})
        self.assertEqual(bridge.get_preview()['code'], 'new')
        windows[0].destroy()
        self.assertIn('desktopPreviewClosed', main.scripts[-1])
        bridge.publish_preview({'sequence': 3, 'status': 'waiting', 'code': '', 'errors': ''})
        bridge.open_preview()
        self.assertEqual(len(windows), 2)
        self.assertEqual(bridge.get_preview()['code'], '')
        bridge.publish_preview({'sequence': 4, 'status': 'ready', 'code': '</script>中文', 'errors': ''})
        self.assertEqual(bridge.get_preview()['code'], '</script>中文')

    def test_bridge_validates_payload_and_close_state(self):
        bridge = DesktopBridge(None, None)
        for payload in (None, {}, {'sequence': True}, {'sequence': 1, 'code': []}):
            with self.assertRaises(ValueError):
                bridge.publish_preview(payload)
        bridge.set_busy(True)
        self.assertTrue(bridge._busy)
        bridge.set_busy(False)
        self.assertFalse(bridge._busy)

    def test_closing_cannot_abort_a_running_owned_generation(self):
        app = DesktopApp(SimpleNamespace(create_window=lambda *a, **k: Window()))
        app.bridge.set_busy(True)
        self.assertIs(app._can_close(), False)
        app.bridge.set_busy(False)
        # A failed frontend poll must not make an ongoing backend job safe to exit.
        app.service = SimpleNamespace(session=SimpleNamespace(job={'status': 'running'}))
        self.assertIs(app._can_close(), False)
        app.service.session.job['status'] = 'completed'
        self.assertIsNone(app._can_close())


if __name__ == '__main__':
    unittest.main()
