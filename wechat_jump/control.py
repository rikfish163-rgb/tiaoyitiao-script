"""Finite, guarded automation loop; testable without an X server."""
import time

import numpy as np
from PIL import Image

from .vision import DetectionError, detect, press_duration
from .calibration import calibrated_duration


class SafetyStop(RuntimeError):
    pass


def guarded_press(io, duration_ms):
    if not 60 <= duration_ms <= 1500:
        raise SafetyStop('按压时长超出允许范围。')
    io.check()
    # The finally covers even partial failures while sending ButtonPress.
    try:
        queued_at = io.down()
        started = queued_at if type(queued_at) in (int, float) else time.monotonic()
        deadline = started+duration_ms/1000
        while time.monotonic() < deadline:
            io.check()
            time.sleep(min(.01, max(0, deadline-time.monotonic())))
    finally:
        released = io.up()
    ended = released if type(released) in (int, float) else time.monotonic()
    return {'requested_ms': duration_ms, 'client_hold_ms': (ended-started)*1000}


def _thumbnail(image):
    return np.asarray(image.convert('RGB').resize((90, 160), Image.Resampling.BILINEAR),
                      dtype=np.int16)


def run_loop(io, *, max_jumps=1, coefficient=1.0, head_diameter=None,
             stable_frames=3, poll_seconds=.15, settle_seconds=1.3,
             timeout_seconds=10, report=None, after_report=None, reject_report=None, calibration=None):
    if not 1 <= max_jumps <= 1000 or stable_frames < 2:
        raise ValueError('跳跃次数须在 1–1000 内，稳定帧数至少为 2。')
    if (timeout_seconds <= 0 or poll_seconds < 0 or settle_seconds < 0
            or not all(np.isfinite(v) for v in
                       [timeout_seconds, poll_seconds, settle_seconds])):
        raise ValueError('等待参数无效。')
    previous_jump = None
    for jump_index in range(max_jumps):
        deadline = time.monotonic()+timeout_seconds
        last = None
        last_detection = None
        stable = 0
        last_reason = '等待画面稳定'
        while time.monotonic() < deadline:
            io.check()
            image = io.capture()
            thumb = _thumbnail(image)
            # Refuse to blindly repeat when a press had no visible effect.
            if previous_jump is not None and np.mean(np.abs(thumb-previous_jump)) < 2:
                last_reason = '上次按压后画面未发生足够变化'
                time.sleep(poll_seconds)
                continue
            try:
                result = detect(image)
                duration = (calibrated_duration(result, image.width, calibration, coefficient)
                            if calibration is not None else press_duration(result, coefficient, head_diameter))
            except DetectionError as exc:
                last_reason = str(exc)
                if reject_report:
                    reject_report(image, last_reason)
                stable, last, last_detection = 0, None, None
                time.sleep(poll_seconds)
                continue
            same_detection = (last_detection is not None and
                max(abs(a-b) for a, b in zip((*result.piece, *result.target),
                    (*last_detection.piece, *last_detection.target))) < max(2, image.width*.006)
                and abs(result.head_diameter-last_detection.head_diameter) < .08*result.head_diameter)
            if last is not None and same_detection and np.mean(np.abs(thumb-last)) < 1.2:
                stable += 1
            else:
                stable = 1
            last = thumb
            last_detection = result
            if stable >= stable_frames:
                if report:
                    report(jump_index+1, image, result, duration)
                io.check()
                timing = io.press(duration)
                previous_jump = thumb
                break
            time.sleep(poll_seconds)
        else:
            raise SafetyStop(f'{timeout_seconds:g} 秒内未满足起跳条件：{last_reason}')
        if jump_index+1 < max_jumps or after_report is not None:
            until = time.monotonic()+settle_seconds
            while time.monotonic() < until:
                io.check()
                time.sleep(min(.05, max(0, until-time.monotonic())))
        if after_report is not None:
            io.check()
            after_report(jump_index+1, io.capture(), timing)
        if isinstance(timing, dict) and timing['client_hold_ms']-duration > max(30, duration*.1):
            raise SafetyStop('输入同步延迟过大，已释放鼠标并停止；请检查本次时长记录。')
    return max_jumps
