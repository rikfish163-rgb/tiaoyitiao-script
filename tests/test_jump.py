import math
import unittest
from dataclasses import replace

from PIL import Image, ImageDraw

from wechat_jump.vision import DetectionError, detect, press_duration
from wechat_jump.control import SafetyStop, guarded_press, run_loop


def scene(width=360, reverse=False, marker=True, background=(210, 220, 225)):
    height = round(width * 16 / 9)
    image = Image.new('RGB', (width, height), background)
    d = ImageDraw.Draw(image)
    s = width / 360
    def poly(points, fill):
        d.polygon([(round(x*s), round(y*s)) for x, y in points], fill=fill)
    poly([(110, 343), (165, 375), (110, 407), (55, 375)], '#989490')
    poly([(260, 253), (315, 285), (260, 317), (205, 285)], '#dfaa60')
    if marker:
        d.ellipse(tuple(round(v*s) for v in (256, 281, 264, 289)), fill='white')
    d.ellipse(tuple(round(v*s) for v in (100, 315, 120, 335)), fill=(55, 59, 102))
    d.rectangle(tuple(round(v*s) for v in (104, 329, 116, 374)), fill=(55, 59, 102))
    d.ellipse(tuple(round(v*s) for v in (100, 367, 120, 383)), fill=(55, 59, 102))
    if reverse:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return image


class VisionTests(unittest.TestCase):
    def test_both_directions_and_resolutions(self):
        for w in [360, 540, 720]:
            for reverse in [False, True]:
                with self.subTest(w=w, reverse=reverse):
                    result = detect(scene(w, reverse))
                    target_x = w - 1 - 260*w/360 if reverse else 260*w/360
                    self.assertAlmostEqual(result.target[0], target_x, delta=3)
                    self.assertAlmostEqual(result.target[1], 285*w/360, delta=4)
                    self.assertAlmostEqual(result.piece[1], 375*w/360, delta=4)

    def test_no_marker_and_changed_background(self):
        result = detect(scene(marker=False, background=(170, 200, 180)))
        self.assertAlmostEqual(result.target[1], 285, delta=6)
        self.assertEqual(result.method, 'platform_geometry')

    def test_missing_piece_stops(self):
        with self.assertRaises(DetectionError):
            detect(Image.new('RGB', (360, 640), 'white'))

    def test_ambiguous_piece_stops(self):
        image = scene()
        image.paste(image.crop((95, 310, 125, 389)), (180, 310))
        with self.assertRaises(DetectionError):
            detect(image)

    def test_speckles_are_ignored(self):
        image = scene()
        d = ImageDraw.Draw(image)
        for x in range(200, 330, 9):
            d.point((x, 220), fill='black')
        self.assertAlmostEqual(detect(image).target[0], 260, delta=3)

    def test_press_is_monotonic_and_resolution_independent(self):
        a = detect(scene())
        b = detect(scene(720))
        self.assertAlmostEqual(press_duration(a), press_duration(b), delta=35)
        scaled = replace(a, piece=tuple(v*2 for v in a.piece),
                         target=tuple(v*2 for v in a.target),
                         head_diameter=a.head_diameter*2)
        self.assertAlmostEqual(press_duration(a), press_duration(scaled), delta=.001)
        self.assertGreater(press_duration(a, coefficient=1.2), press_duration(a))
        self.assertTrue(math.isfinite(press_duration(a)))

    def test_invalid_coefficient_rejected(self):
        for coefficient in [0, -1, float('nan'), 10]:
            with self.assertRaises(ValueError):
                press_duration(detect(scene()), coefficient=coefficient)


class FakeIO:
    def __init__(self, fail_after_down=False):
        self.events = []
        self.fail_after_down = fail_after_down
    def check(self):
        if self.fail_after_down and 'down' in self.events:
            raise SafetyStop('focus lost')
    def down(self): self.events.append('down')
    def up(self): self.events.append('up')


class SafetyTests(unittest.TestCase):
    def test_releases_when_focus_lost_during_press(self):
        io = FakeIO(True)
        with self.assertRaises(SafetyStop):
            guarded_press(io, 80)
        self.assertEqual(io.events, ['down', 'up'])

    def test_checks_before_press(self):
        class Blocked(FakeIO):
            def check(self): raise SafetyStop('occluded')
        io = Blocked()
        with self.assertRaises(SafetyStop): guarded_press(io, 50)
        self.assertEqual(io.events, [])

    def test_static_screen_never_gets_second_jump(self):
        class Backend(FakeIO):
            def capture(self): return scene()
            def press(self, duration): self.events.append('jump')
        io = Backend()
        with self.assertRaises(SafetyStop):
            run_loop(io, max_jumps=2, stable_frames=2, poll_seconds=0,
                     settle_seconds=0, timeout_seconds=0.15)
        self.assertEqual(io.events, ['jump'])

    def test_failed_detection_does_not_press(self):
        class Backend(FakeIO):
            def capture(self): return Image.new('RGB', (360, 640), 'white')
            def press(self, duration): self.events.append('jump')
        io = Backend()
        with self.assertRaises(SafetyStop):
            run_loop(io, max_jumps=1, stable_frames=2, poll_seconds=0,
                     settle_seconds=0, timeout_seconds=0.1)
        self.assertEqual(io.events, [])


if __name__ == '__main__':
    unittest.main()
