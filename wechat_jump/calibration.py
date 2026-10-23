"""Fit measured horizontal displacement against press time, without desktop access."""
from math import isfinite

import numpy as np

from .vision import DetectionError


def _number(value):
    return type(value) in (int, float) and isfinite(value)


def validate_calibration(profile):
    keys = {'version', 'model', 'slope_ms', 'intercept_ms', 'sample_count', 'rmse_ms', 'x_min', 'x_max'}
    if not isinstance(profile, dict) or set(profile) != keys:
        raise ValueError('校准文件字段无效。')
    if type(profile['version']) is not int or profile['version'] != 1 or profile['model'] != 'normalized_horizontal_linear':
        raise ValueError('校准文件版本或模型无效。')
    if (type(profile['sample_count']) is not int or not 3 <= profile['sample_count'] <= 10000
            or not all(_number(profile[k]) for k in ['slope_ms', 'intercept_ms', 'rmse_ms', 'x_min', 'x_max'])
            or not 100 <= profile['slope_ms'] <= 10000
            or not -300 <= profile['intercept_ms'] <= 300
            or not 0 <= profile['rmse_ms'] <= 100
            or not 0 < profile['x_min'] < profile['x_max'] <= 1
            or profile['x_max']-profile['x_min'] < .15-1e-9):
        raise ValueError('校准模型数值或样本范围不合理。')
    return profile


def fit_calibration(samples):
    if not isinstance(samples, list) or not 3 <= len(samples) <= 10000:
        raise ValueError('至少需要 3 条实测样本，最多 10000 条。')
    xs, ys = [], []
    for sample in samples:
        if (not isinstance(sample, dict) or set(sample) != {'actual_dx', 'width', 'press_ms', 'confirmed'}
                or sample['confirmed'] is not True
                or not all(_number(sample[k]) for k in ['actual_dx', 'width', 'press_ms'])
                or not 180 <= sample['width'] <= 2400
                or not 0 < sample['actual_dx'] <= sample['width']
                or not 60 <= sample['press_ms'] <= 1500):
            raise ValueError('样本须为已确认的实际水平位移 actual_dx、画面宽 width 和按压毫秒 press_ms。')
        xs.append(sample['actual_dx']/sample['width'])
        ys.append(sample['press_ms'])
    if len(set(xs)) < 3 or max(xs)-min(xs) < .15-1e-9:
        raise ValueError('至少覆盖 3 个不同距离，水平位移跨度须达到画面宽度的 15%。')
    matrix = np.column_stack([xs, np.ones(len(xs))])
    slope, intercept = np.linalg.lstsq(matrix, ys, rcond=None)[0]
    residual = np.asarray(ys)-matrix @ [slope, intercept]
    if np.max(np.abs(residual)) > max(25, np.mean(ys)*.12):
        raise ValueError('样本误差过大，不能可靠拟合；请核对实际位移与按压记录。')
    return validate_calibration({'version': 1, 'model': 'normalized_horizontal_linear',
        'slope_ms': float(slope), 'intercept_ms': float(intercept), 'sample_count': len(xs),
        'rmse_ms': float(np.sqrt(np.mean(residual**2))), 'x_min': min(xs), 'x_max': max(xs)})


def calibrated_duration(result, width, profile, coefficient=1.0):
    validate_calibration(profile)
    if not _number(width) or width <= 0 or not _number(coefficient) or not .2 <= coefficient <= 4:
        raise ValueError('画面宽度或按压系数无效。')
    fraction = abs(result.target[0]-result.piece[0])/width
    margin = .02+.1*(profile['x_max']-profile['x_min'])
    if not profile['x_min']-margin <= fraction <= profile['x_max']+margin:
        raise DetectionError('当前跳距超出校准样本范围，拒绝远距离外推。')
    duration = (profile['slope_ms']*fraction+profile['intercept_ms'])*coefficient
    if not 60 <= duration <= 1500:
        raise DetectionError('校准后的按压超出 60–1500ms。')
    return duration
