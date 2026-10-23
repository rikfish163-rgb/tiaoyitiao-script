"""Windows contract/guard tests run without interacting with the desktop."""
import contextlib
import ctypes
import io
import json
import tempfile
import sys
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from wechat_jump.cli import automatic_crop, doctor, get_desktop_classes, main
from wechat_jump.control import SafetyStop, guarded_press
from wechat_jump.windows import Desktop, WindowsBackend, INPUT, Win32API
from test_jump import scene


class WindowsTests(TestCase):
    @skipUnless(sys.platform == 'win32', 'Real Win32 DLL smoke test requires Windows')
    def test_native_api_bindings_and_dpi_without_sending_input(self):
        api = Win32API()
        left, top, right, bottom = api.screen_bounds()
        self.assertGreater(right, left)
        self.assertGreater(bottom, top)
        self.assertIsInstance(api.window_ids(), list)

    def test_native_sendinput_packet_and_blocked_result(self):
        api = Win32API.__new__(Win32API)
        api.user32 = Mock()
        packets = []
        def send(count, pointer, size):
            event = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents
            packets.append((count, size, event.type, event.mi.dwFlags))
            return 1
        api.user32.SendInput.side_effect = send
        api.send_button(True)
        api.send_button(False)
        self.assertEqual(packets, [(1, ctypes.sizeof(INPUT), 0, 2), (1, ctypes.sizeof(INPUT), 0, 4)])
        api.user32.SendInput.side_effect = None
        api.user32.SendInput.return_value = 0
        with self.assertRaisesRegex(SafetyStop, 'SendInput'): api.send_button(True)

    def backend(self):
        api = Mock()
        api.client_rect.return_value = (100, 100, 460, 740)
        api.identity.return_value = {'title': '跳一跳', 'wm_class': ['win32:game'], 'pid': 42}
        api.screen_bounds.return_value = (-1920, 0, 2560, 1440)
        api.visible.return_value = True
        api.region_visible.return_value = True
        api.foreground.return_value = 7
        api.window_ids.return_value = [7]
        api.above.return_value = []
        api.pointer.return_value = (200, 200)
        api.key_down.return_value = False
        desktop = Desktop(api=api)
        config = {'window_id': 7, 'identity': api.identity.return_value, 'crop': [0, 0, 360, 640]}
        return WindowsBackend(desktop, config), api

    def test_input_structure_matches_windows_abi(self):
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_windows_backend_selected_without_importing_xlib(self):
        with patch('wechat_jump.cli.sys.platform', 'win32'):
            self.assertEqual(get_desktop_classes(), (Desktop, WindowsBackend))

    def test_windows_doctor_needs_neither_xlib_nor_display(self):
        with patch('wechat_jump.cli.sys.platform', 'win32'), patch.dict('os.environ', {}, clear=True):
            with patch('wechat_jump.cli.importlib.metadata.version', return_value='13.0.0') as version:
                with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(doctor(), 0)
        self.assertNotIn('python-xlib', [c.args[0] for c in version.call_args_list])

    def test_negative_monitor_coordinates_are_valid(self):
        self.assertEqual(automatic_crop((-1600, 100, -1240, 740), (-1920, 0, 2560, 1440)),
                         [0, 0, 360, 640])

    def test_focused_visible_window_allowed(self):
        backend, api = self.backend()
        backend.check()
        api.send_button.assert_not_called()

    def test_focus_hidden_identity_move_escape_and_user_motion_stop(self):
        for condition in ('focus', 'hidden', 'identity', 'move', 'escape', 'pointer', 'screen'):
            with self.subTest(condition=condition):
                backend, api = self.backend()
                if condition == 'focus': api.foreground.return_value = 9
                if condition == 'hidden': api.visible.return_value = False
                if condition == 'identity': api.identity.return_value = {}
                if condition == 'move': api.client_rect.return_value = (101, 100, 461, 740)
                if condition == 'escape': api.key_down.side_effect = lambda k: k == 0x1b
                if condition == 'pointer': backend.held = True
                if condition == 'screen': api.region_visible.return_value = False
                with self.assertRaises(SafetyStop): backend.check()

    def test_overlapping_window_stops(self):
        backend, api = self.backend()
        api.above.return_value = [9]
        api.window_rect.return_value = (200, 100, 600, 700)
        with self.assertRaisesRegex(SafetyStop, '遮挡'): backend.check()

    def test_capture_checks_before_and_after(self):
        backend, api = self.backend()
        with patch('wechat_jump.windows.ImageGrab.grab', return_value=scene()) as grab:
            backend.capture()
        grab.assert_called_once_with(bbox=backend.region, all_screens=True, include_layered_windows=True)
        self.assertEqual(api.foreground.call_count, 2)

    def test_failed_send_still_attempts_release(self):
        backend, api = self.backend()
        api.move_pointer.side_effect = lambda xy: setattr(api.pointer, 'return_value', xy)
        api.send_button.side_effect = [SafetyStop('SendInput failed'), None]
        with self.assertRaises(SafetyStop): guarded_press(backend, 80)
        self.assertEqual([c.args for c in api.send_button.call_args_list], [(True,), (False,)])
        self.assertFalse(backend.held)

    def test_failed_release_can_be_retried_by_cleanup(self):
        backend, api = self.backend()
        backend.held = True
        api.send_button.side_effect = [SafetyStop('blocked'), None]
        with self.assertRaises(SafetyStop): backend.up()
        self.assertTrue(backend.held)
        backend.up()
        self.assertFalse(backend.held)

    def test_pressed_user_button_prevents_input(self):
        backend, api = self.backend()
        api.key_down.side_effect = lambda k: k == 1
        with self.assertRaises(SafetyStop): backend.down()
        api.send_button.assert_not_called()

    def test_windows_setup_preview_without_x11_or_input(self):
        backend, api = self.backend()
        desktop = backend.desktop
        api.window_ids.return_value = [7]
        with tempfile.TemporaryDirectory() as temp:
            config, output = Path(temp)/'config.json', Path(temp)/'preview.png'
            with patch('wechat_jump.cli.get_desktop_classes', return_value=(lambda: desktop, WindowsBackend)):
                with patch('wechat_jump.windows.ImageGrab.grab', return_value=scene()):
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = main(['--config', str(config), 'setup', '--auto', '--preview',
                                     '--delay', '0', '--output', str(output)])
            self.assertEqual(code, 0)
            self.assertTrue(config.is_file())
            self.assertTrue(output.is_file())
            api.send_button.assert_not_called()

    def test_windows_run_cli_reaches_loop_and_cleanup(self):
        backend, api = self.backend()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root/'config.json'
            config.write_text(json.dumps({**backend.config, 'version': 1, 'coefficient': 1.,
                                          'head_diameter': None}), encoding='utf-8')
            with patch('wechat_jump.cli.get_desktop_classes', return_value=(lambda: backend.desktop, WindowsBackend)):
                with patch('wechat_jump.cli.ROOT', root), patch('wechat_jump.cli.run_loop', return_value=1) as loop:
                    with patch('wechat_jump.cli.signal.signal'), contextlib.redirect_stdout(io.StringIO()):
                        result = main(['--config', str(config), 'run', '--delay', '0'])
            self.assertEqual(result, 0)
            loop.assert_called_once()
            api.send_button.assert_not_called()
