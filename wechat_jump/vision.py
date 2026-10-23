"""Image-only detection. No desktop access or mouse input in this module."""
from dataclasses import dataclass
from math import hypot, isfinite, sqrt

import numpy as np
from PIL import Image, ImageDraw


class DetectionError(ValueError):
    pass


@dataclass(frozen=True)
class Detection:
    piece: tuple[float, float]
    target: tuple[float, float]
    head_diameter: float
    platform_box: tuple[float, float, float, float]
    method: str

    @property
    def distance(self):
        return hypot(self.target[0] - self.piece[0], self.target[1] - self.piece[1])


def _components(mask):
    """Four-connected components, returning only bounding boxes and pixel counts."""
    remaining = mask.copy()
    height, width = remaining.shape
    for seed_y, seed_x in zip(*np.nonzero(mask)):
        if not remaining[seed_y, seed_x]:
            continue
        stack = [(int(seed_x), int(seed_y))]
        remaining[seed_y, seed_x] = False
        left = right = int(seed_x)
        top = bottom = int(seed_y)
        count = 0
        while stack:
            x, y = stack.pop()
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            count += 1
            for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if 0 <= nx < width and 0 <= ny < height and remaining[ny, nx]:
                    remaining[ny, nx] = False
                    stack.append((nx, ny))
        yield (left, top, right+1, bottom+1, count)


def _surface_box(rgb, foreground, box):
    """Find the top face by its cap color, excluding side faces and cast shadows."""
    x1, y1, x2, y2, _ = box
    w = rgb.shape[1]
    cap_end = min(y2, y1+max(4, round(.02*w)))
    cap_mask = foreground[y1:cap_end, x1:x2]
    ys, xs = np.nonzero(cap_mask)
    if len(xs) < 4:
        return None
    cap_color = np.median(rgb[y1+ys, x1+xs], axis=0)
    # Adjacent shaded faces can differ by only ~25 RGB levels in total.
    # Keep that face out so its lower edge cannot pull the landing point down.
    color_match = np.abs(rgb.astype(np.int16)-cap_color).sum(axis=2) <= 18
    surface = np.zeros_like(foreground)
    surface[y1:y2, x1:x2] = color_match[y1:y2, x1:x2] & foreground[y1:y2, x1:x2]
    cap_x = float(xs.mean()+x1)
    options = []
    for a, b, c, d, area in _components(surface):
        width, height = c-a, d-b
        if (.08*w <= width <= .65*w and .15 <= height/width <= .95
                and b <= y1+.025*w and abs((a+c)/2-cap_x) < .12*w
                and area >= .002*w*w):
            options.append((a, b, c, d, area))
    if not options:
        return None
    return max(options, key=lambda item: item[4])[:4]


def detect(image: Image.Image) -> Detection:
    width, height = image.size
    if not (180 <= width <= 2400 and 280 <= height <= 4000):
        raise DetectionError('游戏画面尺寸不合理，请只框选游戏内容。')
    if not 1.05 <= height / width <= 2.6:
        raise DetectionError('游戏区域应为竖屏，不能包含整张桌面。')
    factor = min(1.0, 540 / width)
    rgb = np.asarray(image.convert('RGB').resize(
        (round(width*factor), round(height*factor)), Image.Resampling.BILINEAR))
    h, w = rgb.shape[:2]
    r, g, b = (rgb[:, :, k].astype(np.int16) for k in range(3))
    purple = ((r >= 35) & (r <= 85) & (g >= 38) & (g <= 88)
              & (b >= 75) & (b <= 145) & (b-r >= 22) & (b-g >= 14))
    purple[:int(h*.22)] = False
    purple[int(h*.82):] = False
    pieces = []
    for box in _components(purple):
        l, t, rr, bb, area = box
        bw, bh = rr-l, bb-t
        if (.018*w <= bw <= .13*w and .06*w <= bh <= .32*w
                and 1.3 <= bh/bw <= 7 and area >= .0006*w*w):
            pieces.append(box)
    pieces.sort(key=lambda item: item[4], reverse=True)
    if not pieces:
        raise DetectionError('未识别到棋子：确认游戏已开始、区域正确且未被遮挡。')
    if len(pieces) > 1 and pieces[1][4] >= .55*pieces[0][4]:
        raise DetectionError('存在多个相似棋子，停止以避免误按。')
    l, t, rr, bb, _ = pieces[0]
    # The sphere may be separated from the torso by a few background pixels.
    # Measuring the torso's first rows alone badly underestimates its diameter.
    head = float(rr-l)
    head_mask = ((r >= 20) & (r <= 155) & (g >= 20) & (g <= 150)
                 & (b >= 40) & (b <= 190) & (b-r > 8) & (b-g > 4))
    isolated = np.zeros_like(head_mask)
    ha, hb = max(0, round(l-.025*w)), min(w, round(rr+.025*w))
    ht, he = max(0, round(t-.13*w)), min(h, round(t+.005*w))
    isolated[ht:he, ha:hb] = head_mask[ht:he, ha:hb]
    heads = []
    for a, c, d, e, area in _components(isolated):
        hw, hh = d-a, e-c
        if (.025*w <= hw <= .12*w and .7 <= hw/hh <= 1.5
                and abs((a+d-l-rr)/2) < .025*w and e <= t+.01*w
                and area >= .0002*w*w):
            heads.append((area, hw))
    if heads:
        head = float(max(heads)[1])
    if head < .018*w:
        raise DetectionError('棋子头部尺寸不可靠。')
    bottom = purple[max(t, bb-3):bb, l:rr]
    px = float(np.nonzero(bottom)[1].mean() + l)
    py = float(bb - 1 - .32*head)

    # Select likely background pixels using a quiet upper band as an anchor.
    # Averaging opposite edges creates a nonexistent color if a platform covers
    # one edge; the real background then turns into a huge false component.
    anchor = np.median(rgb[int(h*.22):int(h*.33)], axis=(0, 1))
    distance_to_anchor = np.abs(rgb.astype(np.int16)-anchor).sum(axis=2)
    sample_count = max(8, round(w*.2))
    indices = np.argpartition(distance_to_anchor, sample_count-1, axis=1)[:, :sample_count]
    samples = np.take_along_axis(rgb, indices[:, :, None], axis=1)
    background = np.median(samples, axis=1)
    foreground = np.abs(rgb.astype(np.int16)-background[:, None, :]).sum(axis=2) > 48
    foreground[:int(h*.22)] = False
    foreground[min(h, round(py+.03*h)):] = False
    # A thin window border can connect a platform's shadow to the entire
    # image edge. Remove only the border; validate the landing face below.
    edge = max(2, round(.005*w))
    foreground[:, :edge] = False
    foreground[:, -edge:] = False
    # Search the side opposite the current piece, leaving its body out.
    if px < w/2:
        foreground[:, :round(px+.09*w)] = False
    else:
        foreground[:, round(px-.09*w):] = False
    candidates = []
    for box in _components(foreground):
        x1, y1, x2, y2, area = box
        bw, bh = x2-x1, y2-y1
        if (.10*w <= bw <= .75*w and .15*bw <= bh <= 1.4*bw
                and y1 > h*.22+2
                and area > .002*w*w and abs((x1+x2)/2-px) > .14*w):
            candidates.append(box)
    candidates.sort(key=lambda item: item[1])
    if not candidates:
        raise DetectionError('未识别到独立的下一跳台，停止。')
    if len(candidates) > 1 and candidates[1][1]-candidates[0][1] < .035*w:
        raise DetectionError('下一跳台不唯一，停止。')
    x1, y1, x2, y2, _ = candidates[0]
    bw = x2-x1
    # Average the top edge rather than the whole object (which includes sides).
    ys, xs = np.nonzero(foreground[y1:min(y1+3, y2), x1:x2])
    tx = float(xs.mean()+x1)
    ty = float(y1+.29*bw)
    method = 'platform_geometry'
    face = _surface_box(rgb, foreground, candidates[0])
    if face is not None:
        x1, y1, x2, y2 = face
        if x1 <= .01*w or x2 >= .99*w:
            raise DetectionError('平台顶面接近画面边缘，无法确认完整落点。')
        bw = x2-x1
        tx, ty = (x1+x2-1)/2, (y1+y2-1)/2
    white = np.all(rgb > 235, axis=2)
    restricted = np.zeros_like(white)
    restricted[y1:min(y2, round(y1+.65*bw)), x1:x2] = white[
        y1:min(y2, round(y1+.65*bw)), x1:x2]
    markers = []
    for a, c, d, e, area in _components(restricted):
        mw, mh = d-a, e-c
        mx, my = (a+d-1)/2, (c+e-1)/2
        if (2 <= mw <= .2*bw and 2 <= mh <= .2*bw and .5 <= mw/mh <= 2
                and area >= 4 and abs(mx-tx) < .18*bw and abs(my-ty) < .14*bw):
            markers.append((mx, my))
    if len(markers) == 1:
        tx, ty = markers[0]
        method = 'white_marker'
    if face is None and method != 'white_marker':
        raise DetectionError('平台顶面和中心点均不可靠，拒绝按外轮廓猜测落点。')
    slope = (py-ty)/max(1, abs(tx-px))
    if not (.03*w < tx < .97*w and h*.20 < ty < py
            and .2 <= slope <= 1.1 and hypot(tx-px, ty-py) < w):
        raise DetectionError('目标几何关系异常，停止。')
    return Detection((px/factor, py/factor), (tx/factor, ty/factor), head/factor,
                     tuple(v/factor for v in (x1, y1, x2, y2)), method)


def press_duration(result: Detection, coefficient=1.0, head_diameter=None) -> float:
    """Milliseconds; quadratic motion model described by wangshub/wechat_jump_game."""
    if not isfinite(coefficient) or not .2 <= coefficient <= 4:
        raise ValueError('按压系数须在 0.2 到 4 之间。')
    head = result.head_diameter if head_diameter is None else head_diameter
    if not isfinite(head) or head <= 0:
        raise ValueError('头部直径须为正数。')
    distance = result.distance * (0.945*2/head) * (sqrt(6)/2)
    # Rationalized positive quadratic root avoids cancellation for short hops.
    ms = 72*distance/(945+sqrt(945**2+4*105*36*distance))*1000*coefficient
    if not isfinite(ms) or not 60 <= ms <= 1500:
        raise DetectionError(f'估计按压 {ms:.0f}ms 超出允许范围 60–1500ms。')
    return ms


def annotate(image, result):
    output = image.convert('RGB').copy()
    draw = ImageDraw.Draw(output)
    draw.rectangle(result.platform_box, outline='#ffbb00', width=2)
    draw.line((*result.piece, *result.target), fill='#00aaff', width=3)
    for point, color in [(result.piece, '#ff3355'), (result.target, '#00ff88')]:
        x, y = point
        draw.ellipse((x-5, y-5, x+5, y+5), outline=color, width=3)
    return output
