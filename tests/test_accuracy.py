from dataclasses import replace
from pathlib import Path
import contextlib
import io
import json
import tempfile
from unittest import TestCase
from unittest.mock import patch

from PIL import Image, ImageDraw

from test_jump import scene
from wechat_jump.calibration import fit_calibration, calibrated_duration, validate_calibration
from wechat_jump.control import guarded_press
from wechat_jump.control import run_loop
from wechat_jump.cli import main
from wechat_jump.vision import DetectionError, detect


class AccuracyTests(TestCase):
    def test_small_disconnected_white_pedestal(self):
        with Image.open(Path(__file__).parent/'fixtures'/'desktop-small-white-pedestal.png') as original:
            for width in (360, 540, 699, 1080):
                for mirrored in (False, True):
                    with self.subTest(width=width, mirrored=mirrored):
                        scale = width/original.width
                        image = original.resize((width, round(original.height*scale)))
                        if mirrored:
                            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        result = detect(image)
                        ex = width-1-512*scale if mirrored else 512*scale
                        self.assertAlmostEqual(result.target[0], ex, delta=4)
                        self.assertAlmostEqual(result.target[1], 571*scale, delta=4)
                        self.assertLess(result.platform_box[3], 600*scale)

    def small_platform(self, diameter, shape='ellipse', color='#f6f6f6'):
        image = scene(marker=False)
        draw = ImageDraw.Draw(image)
        draw.rectangle((200, 240, 320, 320), fill=(210, 220, 225))
        # The pale rim leaves a background-colored gap above the stem.
        draw.polygon([(255, 300), (265, 300), (270, 337), (250, 337)], fill='#999999')
        box = (260-diameter/2, 285-diameter/4,
               260+diameter/2, 285+diameter/4)
        getattr(draw, shape)(box, fill=color)
        return image

    def test_small_round_faces_across_sizes_colors_and_directions(self):
        for diameter in (20, 26, 32, 40, 52):
            for color in ('#f6f6f6', '#66996a'):
                for mirrored in (False, True):
                    with self.subTest(diameter=diameter, color=color, mirrored=mirrored):
                        image = self.small_platform(diameter, color=color)
                        if mirrored:
                            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        result = detect(image)
                        self.assertAlmostEqual(result.target[0], 99 if mirrored else 260, delta=2)
                        self.assertAlmostEqual(result.target[1], 285, delta=2)

    def test_small_rectangular_patch_is_not_a_round_landing_face(self):
        for diameter in (20, 26):
            with self.subTest(diameter=diameter):
                with self.assertRaises(DetectionError):
                    detect(self.small_platform(diameter, shape='rectangle'))

    def test_small_partial_or_hollow_round_face_is_rejected(self):
        for diameter in (20, 26, 32):
            for damage in ('half', 'hole'):
                with self.subTest(diameter=diameter, damage=damage):
                    image = self.small_platform(diameter)
                    draw = ImageDraw.Draw(image)
                    box = ((260-diameter/2, 270, 260, 299) if damage == 'half'
                           else (255, 282, 265, 288))
                    draw.rectangle(box, fill=(210, 220, 225))
                    with self.assertRaises(DetectionError):
                        detect(image)

    def test_narrow_round_platform_with_tall_stem(self):
        with Image.open(Path(__file__).parent/'fixtures'/'desktop-green-pedestal.png') as original:
            for width in (360, 699, 1080):
                for mirrored in (False, True):
                    with self.subTest(width=width, mirrored=mirrored):
                        scale = width/original.width
                        image = original.resize((width, round(original.height*scale)))
                        if mirrored:
                            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        result = detect(image)
                        ex = width-1-300*scale if mirrored else 300*scale
                        self.assertAlmostEqual(result.target[0], ex, delta=5)
                        self.assertAlmostEqual(result.target[1], 619*scale, delta=5)

    def test_textured_marble_and_decorated_roof_have_correct_centers(self):
        for filename, expected in [('desktop-marble.png', (440, 612)),
                                   ('desktop-striped-roof.png', (475, 590))]:
            with Image.open(Path(__file__).parent/'fixtures'/filename) as original:
                for width in (360, 699, 1080):
                    for mirrored in (False, True):
                        with self.subTest(filename=filename, width=width, mirrored=mirrored):
                            scale = width/original.width
                            image = original.resize((width, round(original.height*scale)))
                            if mirrored:
                                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            result = detect(image)
                            ex = width-1-expected[0]*scale if mirrored else expected[0]*scale
                            self.assertAlmostEqual(result.target[0], ex, delta=5)
                            self.assertAlmostEqual(result.target[1], expected[1]*scale, delta=5)

    def test_background_shadow_does_not_enlarge_piece_head(self):
        with Image.open(Path(__file__).parent/'fixtures'/'desktop-striped-roof.png') as image:
            result = detect(image)
        self.assertAlmostEqual(result.head_diameter, 39, delta=3)

    def test_occluded_turntable_does_not_use_partial_color_patch_as_face(self):
        with Image.open(Path(__file__).parent/'fixtures'/'desktop-occluded-turntable.png') as original:
            for mirrored in (False, True):
                with self.subTest(mirrored=mirrored):
                    image = original.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirrored else original
                    with self.assertRaises(DetectionError):
                        detect(image)

    def test_green_face_excludes_similar_side_and_finds_center_marker(self):
        with Image.open(Path(__file__).parent/'fixtures'/'desktop-green-marker.png') as image:
            result = detect(image)
        self.assertEqual(result.method, 'white_marker')
        self.assertAlmostEqual(result.target[0], 487, delta=4)
        self.assertAlmostEqual(result.target[1], 583, delta=4)
        self.assertLess(result.platform_box[3], 670)

    def test_striped_platform_with_shadow_touching_window_border(self):
        with Image.open(Path(__file__).parent/'fixtures'/'desktop-striped-platform.png') as original:
            for width in (360, 699, 1080):
                for mirrored in (False, True):
                    with self.subTest(width=width, mirrored=mirrored):
                        scale = width/original.width
                        image = original.resize((width, round(original.height*scale)))
                        if mirrored:
                            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        result = detect(image)
                        expected_x = width-1-207*scale if mirrored else 207*scale
                        self.assertAlmostEqual(result.target[0], expected_x, delta=5)
                        self.assertAlmostEqual(result.target[1], 565*scale, delta=5)
                        self.assertLess(result.platform_box[3], 650*scale)

    def test_clipped_landing_face_is_still_rejected(self):
        with Image.open(Path(__file__).parent/'fixtures'/'desktop-striped-platform.png') as original:
            image = Image.new('RGB', original.size, original.getpixel((350, 400)))
            image.paste(original, (-100, 0))
        with self.assertRaises(DetectionError):
            detect(image)

    def test_one_occupied_edge_does_not_turn_background_into_target(self):
        image = scene(reverse=True)
        ImageDraw.Draw(image).rectangle((0, 230, 18, 400), fill='#747474')
        result = detect(image)
        self.assertAlmostEqual(result.target[0], 99, delta=5)
        self.assertAlmostEqual(result.target[1], 285, delta=6)

    def test_saved_bad_frame_never_returns_window_border_as_target(self):
        path = Path(__file__).parent/'fixtures'/'desktop-failed-annotated.png'
        with Image.open(path) as image:
            try:
                result = detect(image)
            except DetectionError:
                return  # Fail closed is acceptable when only an annotated frame remains.
        self.assertAlmostEqual(result.target[0], 197, delta=15)
        self.assertAlmostEqual(result.target[1], 556, delta=15)

    def test_input_round_trip_does_not_extend_requested_hold(self):
        class Clock:
            now = 100.
            def monotonic(self): return self.now
            def sleep(self, seconds): self.now += seconds
        clock = Clock()
        class IO:
            def check(self): pass
            def down(self):
                queued = clock.now
                clock.now += .040  # Server synchronization takes 40 ms.
                return queued
            def up(self): return clock.now
        with patch('wechat_jump.control.time.monotonic', side_effect=clock.monotonic):
            with patch('wechat_jump.control.time.sleep', side_effect=clock.sleep):
                timing = guarded_press(IO(), 100)
        self.assertAlmostEqual(clock.now, 100.1, places=5)
        self.assertAlmostEqual(timing['client_hold_ms'], 100, places=3)

    def test_final_jump_also_records_post_jump_frame_and_timing(self):
        class IO:
            def check(self): pass
            def capture(self): return scene()
            def press(self, duration):
                return {'requested_ms': duration, 'client_hold_ms': duration+1}
        records = []
        run_loop(IO(), max_jumps=1, stable_frames=2, poll_seconds=0, settle_seconds=0,
                 after_report=lambda i, image, timing: records.append((i, image.size, timing)))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][0], 1)
        self.assertIn('client_hold_ms', records[0][2])


class CalibrationTests(TestCase):
    def samples(self):
        return [{'actual_dx': f*600, 'width': 600, 'press_ms': 1600*f+30,
                 'confirmed': True} for f in [.2, .35, .5, .65]]

    def test_fit_known_relation_and_predict(self):
        profile = fit_calibration(self.samples())
        self.assertAlmostEqual(profile['slope_ms'], 1600, places=4)
        self.assertAlmostEqual(profile['intercept_ms'], 30, places=4)
        self.assertLess(profile['rmse_ms'], .001)
        result = detect(scene())
        self.assertAlmostEqual(calibrated_duration(result, 360, profile),
                               abs(result.target[0]-result.piece[0])/360*1600+30, places=3)

    def test_profile_is_independent_of_head_and_image_scale(self):
        profile = fit_calibration(self.samples())
        result = detect(scene())
        scaled = replace(result, piece=tuple(v*2 for v in result.piece),
                         target=tuple(v*2 for v in result.target), head_diameter=2)
        self.assertAlmostEqual(calibrated_duration(result, 360, profile),
                               calibrated_duration(scaled, 720, profile))

    def test_unconfirmed_samples_rejected(self):
        samples = self.samples()
        samples[0]['confirmed'] = False
        with self.assertRaises(ValueError): fit_calibration(samples)

    def test_narrow_distance_range_rejected(self):
        samples = [{'actual_dx': x, 'width': 600, 'press_ms': 500,
                    'confirmed': True} for x in [200, 201, 202]]
        with self.assertRaises(ValueError): fit_calibration(samples)

    def test_decreasing_or_nonfinite_profile_rejected(self):
        profile = fit_calibration(self.samples())
        for value in [-1, float('nan')]:
            with self.assertRaises(ValueError):
                validate_calibration({**profile, 'slope_ms': value})

    def test_far_extrapolation_rejected(self):
        profile = fit_calibration(self.samples())
        result = replace(detect(scene()), piece=(0, 300), target=(350, 200))
        with self.assertRaises(DetectionError): calibrated_duration(result, 360, profile)

    def test_calibration_cli_is_offline_and_saves_valid_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            samples, output = Path(temp)/'samples.json', Path(temp)/'calibration.json'
            samples.write_text(json.dumps(self.samples()))
            with patch('wechat_jump.cli.get_desktop_classes') as desktop:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(['calibrate', str(samples), '--output', str(output)])
            self.assertEqual(code, 0)
            validate_calibration(json.loads(output.read_text()))
            desktop.assert_not_called()
