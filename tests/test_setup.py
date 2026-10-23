import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from wechat_jump.cli import automatic_crop, choose_game_window, crop_from_selection, main, save_preview
from wechat_jump.vision import DetectionError
from test_jump import scene


WINDOWS = [
    (0x340000a, 'Terminal', (76, 32, 2560, 1600)),
    (0x6400017, '跳一跳', (1911, 444, 2564, 1604)),
    (0x4800004, 'ChatGPT', (76, 32, 2560, 1600)),
    (0x6200011, '微信', (76, 816, 2560, 1600)),
]


class SetupTests(unittest.TestCase):
    def test_enter_selects_unique_game_instead_of_wechat_main(self):
        chosen = choose_game_window(WINDOWS, read=lambda prompt: '')
        self.assertEqual(chosen, WINDOWS[1])

    def test_wrong_wechat_window_rejected_before_picking(self):
        with self.assertRaisesRegex(ValueError, '微信主窗口.*跳一跳'):
            choose_game_window(WINDOWS, read=lambda prompt: '3')

    def test_explicit_game_id_supported(self):
        self.assertEqual(choose_game_window(WINDOWS, requested=0x6400017), WINDOWS[1])

    def test_auto_selects_unique_game_without_prompt(self):
        read = patch('builtins.input', side_effect=AssertionError('must not prompt'))
        with read:
            self.assertEqual(choose_game_window(WINDOWS, auto=True), WINDOWS[1])

    def test_auto_rejects_multiple_games(self):
        with self.assertRaisesRegex(ValueError, '唯一'):
            choose_game_window(WINDOWS + [(99, '跳一跳', (0, 0, 360, 640))], auto=True)

    def test_qq_selection_rejected_when_game_exists(self):
        with self.assertRaisesRegex(ValueError, '跳一跳'):
            choose_game_window(WINDOWS + [(99, 'QQ', (0, 0, 400, 800))], read=lambda prompt: '4')

    def test_negative_index_rejected(self):
        with self.assertRaisesRegex(ValueError, '序号'):
            choose_game_window(WINDOWS, read=lambda prompt: '-1')

    def test_empty_choice_does_not_guess_between_two_games(self):
        windows = WINDOWS + [(99, '跳一跳', (0, 0, 360, 640))]
        with self.assertRaisesRegex(ValueError, '序号'):
            choose_game_window(windows, read=lambda prompt: '')

    def test_pick_in_game_is_outside_wrong_wechat_main(self):
        with self.assertRaisesRegex(ValueError, '所选窗口'):
            crop_from_selection(WINDOWS[3][2], (1915, 480, 2555, 1595))

    def test_valid_pick_uses_window_relative_coordinates(self):
        self.assertEqual(crop_from_selection(WINDOWS[1][2], (1915, 480, 2555, 1595)),
                         [4, 36, 640, 1115])

    def test_single_click_explains_drag_requirement(self):
        with self.assertRaisesRegex(ValueError, '按住.*拖'):
            crop_from_selection(WINDOWS[1][2], (2000, 800, 2000, 800))

    def test_missing_config_has_setup_hint_without_connecting_desktop(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp)/'config.json'
            stderr = io.StringIO()
            with patch('wechat_jump.x11.Desktop') as desktop:
                with contextlib.redirect_stderr(stderr):
                    code = main(['--config', str(missing), 'preview'])
            self.assertEqual(code, 2)
            self.assertIn('setup --auto --preview', stderr.getvalue())
            self.assertNotIn('No such file', stderr.getvalue())
            desktop.assert_not_called()

    def test_automatic_crop_handles_four_pixel_border_outside_screen(self):
        self.assertEqual(automatic_crop((1911, 444, 2564, 1604), (2560, 1600)),
                         [0, 0, 649, 1156])

    def test_automatic_crop_preserves_fully_visible_window(self):
        self.assertEqual(automatic_crop((1774, 360, 2427, 1520), (2560, 1600)),
                         [0, 0, 653, 1160])

    def test_automatic_crop_refuses_substantially_hidden_game(self):
        with self.assertRaisesRegex(ValueError, '屏幕'):
            automatic_crop((1900, 360, 2700, 1600), (2560, 1600))

    def test_setup_and_preview_need_no_pointer_grab_or_window_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            config, output = Path(temp)/'config.json', Path(temp)/'preview.png'
            desktop, backend = Mock(), Mock()
            desktop.windows.return_value = WINDOWS
            desktop.rect.return_value = (1774, 360, 2427, 1520)
            desktop.identity.return_value = {'title': '跳一跳', 'wm_class': [], 'pid': 42}
            desktop.root.get_geometry.return_value = SimpleNamespace(width=2560, height=1600)
            backend.capture.return_value = scene()
            with patch('wechat_jump.x11.Desktop', return_value=desktop):
                with patch('wechat_jump.x11.X11Backend', return_value=backend):
                    with patch('builtins.input', side_effect=AssertionError('must not prompt')):
                        with contextlib.redirect_stdout(io.StringIO()):
                            code = main(['--config', str(config), 'setup', '--auto', '--preview',
                                         '--delay', '0', '--output', str(output)])
            self.assertEqual(code, 0)
            self.assertTrue(config.is_file())
            self.assertTrue(output.is_file())
            desktop.select_region.assert_not_called()
            backend.press.assert_not_called()
            backend.down.assert_not_called()
            backend.capture.assert_called_once()

    def test_failed_preview_keeps_raw_game_image(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'preview.png'
            backend = Mock()
            backend.capture.return_value = Image.new('RGB', (360, 640), 'white')
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(DetectionError):
                    save_preview(backend, output, 1.0, None)
            self.assertTrue((Path(temp)/'preview-capture.png').is_file())
            backend.press.assert_not_called()


if __name__ == '__main__':
    unittest.main()
