import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
from datetime import datetime, timezone

from PIL import Image

from .control import SafetyStop, run_loop
from .vision import annotate, detect, press_duration
from .calibration import fit_calibration, calibrated_duration, validate_calibration


ROOT = Path(__file__).resolve().parent.parent


def game_candidates(windows):
    exact = [entry for entry in windows if entry[1].strip() == '跳一跳']
    return exact or [entry for entry in windows if '跳一跳' in entry[1]]


def choose_game_window(windows, requested=None, read=None, auto=False):
    if not windows:
        raise ValueError('未找到可见窗口，请先打开跳一跳。')
    candidates = game_candidates(windows)
    if requested is not None:
        chosen = next((entry for entry in windows if entry[0] == requested), None)
        if chosen is None:
            raise ValueError('指定窗口不可见或不在窗口列表中。')
    elif auto:
        if len(candidates) != 1:
            raise ValueError('无法唯一识别跳一跳窗口，请去掉 --auto 并输入游戏窗口序号。')
        chosen = candidates[0]
    else:
        default = windows.index(candidates[0]) if len(candidates) == 1 else None
        prompt = ('请输入游戏窗口对应的 [序号]' +
                  (f'（回车选 [{default}] 跳一跳，不要选微信主窗口）' if default is not None else '') + '：')
        answer = (read or input)(prompt).strip()
        try:
            index = default if not answer else int(answer)
        except ValueError:
            raise ValueError('请输入窗口列表中的整数序号。') from None
        if index is None or not 0 <= index < len(windows):
            raise ValueError('请输入有效窗口序号。')
        chosen = windows[index]
    if candidates and chosen[1].strip().casefold() in {'微信', 'wechat', 'weixin'}:
        indices = ', '.join(f'[{windows.index(entry)}] {entry[1]}' for entry in candidates)
        raise ValueError(f'你选中的是微信主窗口，请选择独立游戏窗口 {indices}（跳一跳），再框选。')
    if candidates and chosen not in candidates:
        raise ValueError(f'你选中的是「{chosen[1]}」，请选择列表中标记的「跳一跳」游戏窗口；'
                         '也可以用 setup --auto 自动选择。')
    return chosen


def automatic_crop(window_rect, screen_size):
    """Use the client rectangle; trim only tiny off-screen borders, at most 8px."""
    left, top, right, bottom = window_rect
    bounds = (0, 0, *screen_size) if len(screen_size) == 2 else screen_size
    sl, st, sr, sb = bounds
    visible = (max(sl, left), max(st, top), min(sr, right), min(sb, bottom))
    lost = (visible[0]-left, visible[1]-top, right-visible[2], bottom-visible[3])
    if max(lost) > 8 or visible[2] <= visible[0] or visible[3] <= visible[1]:
        raise ValueError('游戏窗口有较大部分超出屏幕，请先移到屏幕中央再重新设置。')
    return crop_from_selection(window_rect, visible)


def crop_from_selection(window_rect, selection_rect):
    left, top, right, bottom = window_rect
    a, b, c, d = selection_rect
    width, height = c-a, d-b
    if width < 180 or height < 280:
        raise ValueError(f'框选尺寸 {width}×{height}px 太小；请按住左键从游戏内容左上角拖到右下角，不能只单击。')
    if a < left or b < top or c > right or d > bottom:
        raise ValueError(f'框选区域 {selection_rect} 不在所选窗口 {window_rect} 内。'
                         '请选择标题为「跳一跳」的独立窗口，不要选择微信主窗口。')
    if not (width <= 2400 and height <= 4000 and 1.05 <= height/width <= 2.6):
        raise ValueError(f'框选尺寸 {width}×{height}px 不符合竖屏游戏比例，请重新框选游戏内容。')
    return [a-left, b-top, width, height]


def validate_config(value):
    if not isinstance(value, dict) or set(value) != {
            'version', 'window_id', 'identity', 'crop', 'coefficient', 'head_diameter'}:
        raise ValueError('配置字段不完整或含未知字段，请重新 setup。')
    if (type(value['version']) is not int or value['version'] != 1
            or type(value['window_id']) is not int or value['window_id'] <= 0):
        raise ValueError('窗口编号或配置版本无效。')
    crop = value['crop']
    if (not isinstance(crop, list) or len(crop) != 4
            or any(type(v) is not int for v in crop)):
        raise ValueError('crop 必须是 [x,y,width,height] 整数数组。')
    x, y, w, h = crop
    if x < 0 or y < 0 or not (180 <= w <= 2400 and 280 <= h <= 4000 and 1.05 <= h/w <= 2.6):
        raise ValueError(f'裁剪区域 {w}×{h}px（相对位置 {x},{y}）无效，应仅包含竖屏游戏内容；'
                         '请确认选中「跳一跳」独立窗口，并按住鼠标拖动框选。')
    identity = value['identity']
    if (not isinstance(identity, dict) or set(identity) != {'title', 'pid', 'wm_class'}
            or not isinstance(identity['title'], str)
            or not isinstance(identity['wm_class'], list)
            or not all(isinstance(v, str) for v in identity['wm_class'])
            or (identity['pid'] is not None and
                (type(identity['pid']) is not int or identity['pid'] <= 0))):
        raise ValueError('窗口身份字段无效。')
    coefficient = value['coefficient']
    if (type(coefficient) not in (float, int) or not math.isfinite(coefficient)
            or not .2 <= coefficient <= 4):
        raise ValueError('按压系数须在 0.2–4 内。')
    head = value['head_diameter']
    if head is not None and (type(head) not in (float, int) or not math.isfinite(head) or not 1 <= head <= w/4):
        raise ValueError('头部直径无效。')
    return value


def save_config(path, config):
    validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def report(output, index, image, result, duration):
    output.parent.mkdir(parents=True, exist_ok=True)
    annotate(image, result).save(output)
    data = {'jump': index, 'piece': result.piece, 'target': result.target,
            'head_diameter': result.head_diameter, 'distance': result.distance,
            'press_ms': round(duration, 1), 'method': result.method}
    output.with_suffix('.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n',
                                          encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False), flush=True)
    print(f'识别预览：{output.resolve()}', flush=True)


def save_preview(backend, output, coefficient, head_diameter, calibration=None):
    image = backend.capture()
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = output.with_name(output.stem+'-capture.png')
    image.save(raw)
    print(f'游戏区域原图：{raw.resolve()}', flush=True)
    result = detect(image)
    duration = (calibrated_duration(result, image.width, calibration, coefficient)
                if calibration is not None else press_duration(result, coefficient, head_diameter))
    report(output, 0, image, result, duration)
    print('预览完成：未发送鼠标输入。')


def countdown(seconds):
    for remaining in range(seconds, 0, -1):
        print(f'请切换到游戏窗口；{remaining} 秒后继续。', flush=True)
        time.sleep(1)


def get_desktop_classes():
    if sys.platform == 'win32':
        from .windows import Desktop, WindowsBackend
        return Desktop, WindowsBackend
    if sys.platform.startswith('linux'):
        from .x11 import Desktop, X11Backend
        return Desktop, X11Backend
    raise SafetyStop('仅支持 Linux X11 与 Windows 10/11。')


def doctor():
    print(f'Python: {sys.version.split()[0]}')
    windows = sys.platform == 'win32'
    print('后端: Windows Win32' if windows else '后端: Linux X11')
    if not windows:
        print(f'桌面会话: {os.environ.get("XDG_SESSION_TYPE", "unknown")}')
        print(f'DISPLAY: {"已设置" if os.environ.get("DISPLAY") else "未设置"}')
    missing = False
    for distribution in ['Pillow', 'numpy'] + ([] if windows else ['python-xlib']):
        try:
            version = importlib.metadata.version(distribution)
            print(f'{distribution}: {version}')
            if distribution == 'Pillow' and int(version.split('.')[0]) < 13:
                print('请在独立虚拟环境中安装 requirements.txt：Pillow 13 修复已知漏洞。')
                missing = True
        except importlib.metadata.PackageNotFoundError:
            print(f'{distribution}: 未安装')
            missing = True
    print('此检查未连接桌面、未截图、未发送输入。')
    if not windows and os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland':
        print('本版不支持 Wayland/XWayland。')
        return 2
    return 2 if missing or (not windows and not os.environ.get('DISPLAY')) else 0


def build_parser():
    parser = argparse.ArgumentParser(description='Linux X11 / Windows 10/11 微信跳一跳助手（默认单步，Esc 停止）')
    parser.add_argument('--config', type=Path, default=ROOT/'config.json')
    parser.add_argument('--calibration', type=Path, default=ROOT/'calibration.json',
                        help='实测水平位移校准模型；文件不存在时使用未校准的旧版公式')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='只检查会话和依赖，不访问桌面')
    sub.add_parser('windows', help='列出可见窗口编号')
    calibrate = sub.add_parser('calibrate', help='根据已确认的实测位移/按压样本拟合模型，不连接桌面')
    calibrate.add_argument('samples', type=Path)
    calibrate.add_argument('--output', type=Path, default=ROOT/'calibration.json')
    setup = sub.add_parser('setup', help='选择游戏窗口并保存区域')
    setup.add_argument('--window', type=lambda s: int(s, 0))
    setup.add_argument('--auto', action='store_true', help='自动使用唯一的跳一跳窗口，无需输入序号')
    setup.add_argument('--pick', action='store_true', help='拖动鼠标框选游戏内容（不含标题栏）')
    setup.add_argument('--preview', action='store_true', help='保存配置后倒计时截图预览，不发送鼠标输入')
    setup.add_argument('--output', type=Path, default=ROOT/'runs'/'latest.png')
    setup.add_argument('--crop', help='相对窗口的 x,y,width,height；与 --pick 互斥')
    setup.add_argument('--coefficient', type=float, default=1.0)
    setup.add_argument('--head-diameter', type=float)
    setup.add_argument('--delay', type=int, default=5)
    for name in ['preview', 'run', 'analyze']:
        cmd = sub.add_parser(name, help={'preview': '截图并保存标注，不按鼠标',
                                         'run': '执行有限次数自动跳跃，默认 1 次',
                                         'analyze': '分析已有图片，不访问桌面'}[name])
        cmd.add_argument('--output', type=Path, default=ROOT/'runs'/'latest.png')
        cmd.add_argument('--coefficient', type=float)
        cmd.add_argument('--head-diameter', type=float)
        if name == 'analyze':
            cmd.add_argument('image', type=Path)
        else:
            cmd.add_argument('--delay', type=int, default=5)
        if name == 'run':
            cmd.add_argument('--max-jumps', type=int, default=1)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    desktop = backend = None
    try:
        if hasattr(args, 'delay') and not 0 <= args.delay <= 60:
            raise ValueError('倒计时须为 0–60 秒。')
        if getattr(args, 'max_jumps', 1) not in range(1, 1001):
            raise ValueError('跳跃次数须为 1–1000。')
        if args.command == 'doctor':
            return doctor()
        if args.command == 'calibrate':
            if args.samples.stat().st_size > 1_000_000:
                raise ValueError('样本文件过大。')
            profile = fit_calibration(json.loads(args.samples.read_text(encoding='utf-8')))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(profile, indent=2)+'\n', encoding='utf-8')
            print(f'已拟合 {profile["sample_count"]} 条实测样本，RMSE={profile["rmse_ms"]:.1f}ms。')
            print(f'校准文件：{args.output.resolve()}。拟合误差不等于实际游戏命中率。')
            return 0
        if int(importlib.metadata.version('Pillow').split('.')[0]) < 13:
            raise SafetyStop('请先在虚拟环境安装 requirements.txt（需要 Pillow >= 13）。')
        calibration = None
        if args.calibration.is_file():
            if args.calibration.stat().st_size > 10000:
                raise ValueError('校准文件过大。')
            calibration = validate_calibration(json.loads(args.calibration.read_text(encoding='utf-8')))
        if args.command == 'analyze':
            with Image.open(args.image) as image:
                result = detect(image)
                coefficient = 1.0 if args.coefficient is None else args.coefficient
                ms = (calibrated_duration(result, image.width, calibration, coefficient)
                      if calibration is not None else press_duration(result, coefficient, args.head_diameter))
                report(args.output, 0, image, result, ms)
            return 0

        if args.command in ['preview', 'run'] and not args.config.is_file():
            launcher = r'.\start.cmd' if sys.platform == 'win32' else 'bash start.sh'
            raise SafetyStop(f'尚未成功保存游戏区域配置。请先运行 {launcher} setup --auto --preview，'
                             '看到“配置已保存”后再运行 preview。')

        # No platform imports or desktop connections for image-only operations.
        Desktop, Backend = get_desktop_classes()
        desktop = Desktop()
        if args.command in ['windows', 'setup']:
            windows = desktop.windows()
            candidates = game_candidates(windows)
            for index, (window_id, title, rect) in enumerate(windows):
                tag = '  ← 跳一跳游戏窗口' if (window_id, title, rect) in candidates else ''
                print(f'[{index}] {hex(window_id)}  {title}  {rect}{tag}')
            if args.command == 'windows':
                return 0
            if args.pick and args.crop:
                raise ValueError('--pick 和 --crop 不能同时使用。')
            if args.pick and sys.platform == 'win32':
                raise ValueError('Windows 请使用 setup --auto --preview 或 --crop，不支持 --pick。')
            if args.auto and args.window is not None:
                raise ValueError('--auto 和 --window 不能同时使用。')
            window_id, title, _ = choose_game_window(windows, requested=args.window, auto=args.auto)
            print(f'已选择：{title} ({hex(window_id)})')
            window = desktop.window(window_id)
            left, top, right, bottom = desktop.rect(window)
            crop = None
            if args.pick:
                print('请将游戏置前。从游戏内容左上角按住左键拖到右下角后松开；Esc 取消。')
                countdown(args.delay)
                a, b, c, d = desktop.select_region()
                # The user can move the window during the countdown.
                left, top, right, bottom = desktop.rect(window)
                crop = crop_from_selection((left, top, right, bottom), (a, b, c, d))
            elif args.crop:
                crop = [int(v) for v in args.crop.split(',')]
            else:
                crop = automatic_crop((left, top, right, bottom), desktop.screen_bounds())
                print(f'已自动使用游戏窗口区域：{crop[2]}×{crop[3]}px，无需鼠标框选。')
            config = {'version': 1, 'window_id': window_id,
                      'identity': desktop.identity(window), 'crop': crop,
                      'coefficient': args.coefficient, 'head_diameter': args.head_diameter}
            validate_config(config)
            # Backend/geometry validation only; no focus change or mouse input.
            backend = Backend(desktop, config)
            save_config(args.config, config)
            print(f'配置已保存：{args.config.resolve()}。')
            if args.preview:
                countdown(args.delay)
                save_preview(backend, args.output, config['coefficient'], config['head_diameter'], calibration)
            else:
                print('下一步先运行 preview 检查标注。')
            return 0

        config = validate_config(json.loads(args.config.read_text(encoding='utf-8')))
        if args.coefficient is not None:
            config['coefficient'] = args.coefficient
        if args.head_diameter is not None:
            config['head_diameter'] = args.head_diameter
        validate_config(config)
        backend = Backend(desktop, config)
        countdown(args.delay)
        if args.command == 'preview':
            save_preview(backend, args.output, config['coefficient'], config['head_diameter'], calibration)
            return 0
        def handle_signal(_number, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, handle_signal)
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, handle_signal)
        session = ROOT/'runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        session.mkdir(parents=True)
        print(f'本次记录：{session}（原图、按压时长和落地后画面；不会自动认定成功）')
        print('模型：实测水平位移拟合' if calibration is not None else
              '模型：未校准的旧版公式，不能保证适合当前微信版本。')
        def before_jump(index, image, result, ms):
            image.save(session/f'{index:04d}-before.png')
            report(args.output, index, image, result, ms)
            record = {'index': index, 'width': image.width, 'piece': result.piece,
                      'target': result.target, 'planned_ms': ms, 'method': result.method,
                      'model': calibration['model'] if calibration else 'legacy_uncalibrated'}
            (session/f'{index:04d}-plan.json').write_text(json.dumps(record, indent=2)+'\n')
        def after_jump(index, image, timing):
            image.save(session/f'{index:04d}-after.png')
            (session/f'{index:04d}-timing.json').write_text(json.dumps(timing, indent=2)+'\n')
            print(f'第 {index} 次按压记录：{json.dumps(timing)}；已保存落地后画面，成功与否待核实。')
        def rejected_frame(image, reason):
            image.save(session/'rejected.png')
            (session/'rejected.json').write_text(json.dumps({'reason': reason}, ensure_ascii=False)+'\n', encoding='utf-8')
        count = run_loop(backend, max_jumps=args.max_jumps,
                         coefficient=config['coefficient'], head_diameter=config['head_diameter'],
                         report=before_jump, after_report=after_jump,
                         reject_report=rejected_frame, calibration=calibration)
        print(f'已发送 {count} 次跳跃按压。实际落地和得分请在游戏中核实。')
        return 0
    except KeyboardInterrupt:
        print('\n已停止，释放脚本按下的鼠标键。', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'停止：{exc}', file=sys.stderr)
        return 2
    finally:
        try:
            if backend is not None:
                backend.up()
        finally:
            if desktop is not None:
                desktop.close()
