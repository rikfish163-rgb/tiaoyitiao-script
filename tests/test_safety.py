from pathlib import Path
from types import SimpleNamespace as NS
from unittest import TestCase, skipUnless
import sys
from unittest.mock import Mock, patch
from dataclasses import replace

from PIL import Image
if sys.platform.startswith('linux'):
    from Xlib import X
    from wechat_jump.x11 import Desktop, X11Backend

from wechat_jump.cli import validate_config
from wechat_jump.control import SafetyStop, guarded_press, run_loop
from wechat_jump.vision import detect
from test_jump import FakeIO, scene


class RuntimeTests(TestCase):
    def test_release_after_partial_send_failure(self):
        class Broken(FakeIO):
            def down(self):
                self.events.append('down')
                raise RuntimeError('transport failed')
        io = Broken()
        with self.assertRaises(RuntimeError): guarded_press(io, 100)
        self.assertEqual(io.events, ['down', 'up'])

    def test_releases_after_keyboard_interrupt(self):
        class Interrupted(FakeIO):
            def check(self):
                if 'down' in self.events: raise KeyboardInterrupt
        io = Interrupted()
        with self.assertRaises(KeyboardInterrupt): guarded_press(io, 100)
        self.assertEqual(io.events, ['down', 'up'])

    def test_out_of_range_duration_does_not_press(self):
        for duration in [0, -1, 1501, float('nan')]:
            io = FakeIO()
            with self.assertRaises(SafetyStop): guarded_press(io, duration)
            self.assertEqual(io.events, [])

    def test_requires_consecutive_stable_valid_frames(self):
        class Backend(FakeIO):
            frames = 0
            def capture(self):
                self.frames += 1
                return Image.new('RGB', (360, 640), 'white') if self.frames == 2 else scene()
            def press(self, duration): self.events.append('jump')
        io = Backend()
        run_loop(io, max_jumps=1, stable_frames=3, poll_seconds=0, timeout_seconds=3)
        self.assertEqual(io.frames, 5)
        self.assertEqual(io.events, ['jump'])

    def test_unstable_head_estimate_does_not_press(self):
        class Backend(FakeIO):
            frames = 0
            def capture(self):
                self.frames += 1
                if self.frames > 4:
                    raise SafetyStop('test ends')
                return scene()
            def press(self, duration): self.events.append('jump')
        io = Backend()
        baseline = detect(scene())
        variants = [baseline, replace(baseline, head_diameter=baseline.head_diameter*1.5)]*2
        with patch('wechat_jump.control.detect', side_effect=variants):
            with self.assertRaises(SafetyStop):
                run_loop(io, max_jumps=1, stable_frames=2, poll_seconds=0, timeout_seconds=3)
        self.assertEqual(io.events, [])


@skipUnless(sys.platform.startswith('linux'), 'X11 guards require python-xlib on Linux')
class DesktopGuardTests(TestCase):
    def backend(self):
        backend = X11Backend.__new__(X11Backend)
        backend.config = {'window_id': 1, 'identity': {'title': 'game'}}
        backend.anchor = backend.region = (10, 10, 370, 650)
        backend.window = NS(get_attributes=lambda: NS(map_state=X.IsViewable))
        backend.held = False
        backend.click = (310, 550)
        desktop = NS(cancelled=lambda: False,
                     root=NS(query_pointer=lambda: NS(root_x=100, root_y=100)),
                     identity=lambda w: {'title': 'game'},
                     rect=lambda w: backend.anchor,
                     prop=lambda w, name: [1],
                     connection=NS(create_resource_object=Mock()))
        backend.desktop = desktop
        return backend

    def test_clear_focused_window_allowed(self):
        self.backend().check()

    def test_focus_loss_rejected(self):
        backend = self.backend()
        backend.desktop.prop = lambda w, name: [2] if name == '_NET_ACTIVE_WINDOW' else [1]
        with self.assertRaises(SafetyStop): backend.check()

    def test_overlapping_window_rejected(self):
        backend = self.backend()
        other = NS(get_attributes=lambda: NS(map_state=X.IsViewable))
        backend.desktop.connection.create_resource_object.return_value = other
        backend.desktop.prop = lambda w, name: [1] if name == '_NET_ACTIVE_WINDOW' else [1, 2]
        with self.assertRaises(SafetyStop): backend.check()

    def test_window_movement_rejected(self):
        backend = self.backend()
        backend.desktop.rect = lambda w: (20, 10, 380, 650)
        with self.assertRaises(SafetyStop): backend.check()

    def test_escape_rejected(self):
        backend = self.backend()
        backend.desktop.cancelled = lambda: True
        with self.assertRaises(SafetyStop): backend.check()

    def test_pointer_corner_rejected(self):
        backend = self.backend()
        backend.desktop.root.query_pointer = lambda: NS(root_x=0, root_y=0)
        with self.assertRaises(SafetyStop): backend.check()

    def test_user_pointer_movement_during_press_rejected(self):
        backend = self.backend()
        backend.held = True
        with self.assertRaises(SafetyStop): backend.check()

    def test_wayland_rejected_without_opening_display(self):
        with patch.dict('os.environ', {'XDG_SESSION_TYPE': 'wayland'}):
            with patch('wechat_jump.x11.display.Display') as connect:
                with self.assertRaises(SafetyStop): Desktop()
                connect.assert_not_called()


class ConfigTests(TestCase):
    def test_invalid_external_config_rejected(self):
        config = {'version': 1, 'window_id': 1,
                  'identity': {'title': 'game', 'wm_class': ['WeChat'], 'pid': 42},
                  'crop': [0, 0, 360, 640], 'coefficient': 1., 'head_diameter': None}
        validate_config(config)
        for key, value in [('window_id', -1), ('crop', [-2, 0, 360, 640]),
                           ('crop', [0, 0, 10000, 10000]), ('coefficient', float('nan')),
                           ('coefficient', True), ('head_diameter', -2)]:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError): validate_config({**config, key: value})


class ReferenceImageTests(TestCase):
    def test_desktop_start_targets_white_platform_not_current_platform_edge(self):
        path = Path(__file__).parent/'fixtures'/'desktop-start.png'
        with Image.open(path) as image:
            result = detect(image)
        self.assertAlmostEqual(result.piece[0], 218, delta=5)
        self.assertAlmostEqual(result.target[0], 511, delta=8)
        self.assertAlmostEqual(result.target[1], 578, delta=8)
        self.assertGreater(result.platform_box[0], 350)

    def test_upstream_real_frame(self):
        path = Path(__file__).parent/'fixtures'/'reference-game.png'
        with Image.open(path) as image:
            result = detect(image)
        self.assertAlmostEqual(result.piece[0], 217, delta=4)
        self.assertAlmostEqual(result.piece[1], 304, delta=6)
        self.assertAlmostEqual(result.target[0], 145, delta=3)
        self.assertAlmostEqual(result.target[1], 256, delta=3)
