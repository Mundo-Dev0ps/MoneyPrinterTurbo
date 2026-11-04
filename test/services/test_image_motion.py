"""验证图片亚像素放大平滑度，避免整数尺寸缩放抖动。"""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.services import video


def _white_span(frame, dark=20):
    # 以亚像素精度估算中间几行的白色宽度：按亮度比例累加，避免整数边界掩盖细微变化。
    rows = frame.astype(float)[118:138].mean(axis=2)
    return ((rows - dark) / (255 - dark)).clip(0, 1).sum(axis=1).mean()


def test_zoom_grows_smoothly_every_frame_without_integer_resize_jitter():
    # 旧实现按整数尺寸逐帧缩放：慢速放大时约 3/4 的相邻帧尺寸不变，随后再跳 1px，
    # 成片表现为抖动/顿挫。亚像素放大应让画面每一帧都以相近的幅度增长。
    image = Image.new("RGB", (256, 256), (20, 20, 20))
    ImageDraw.Draw(image).rectangle((28, 28, 227, 227), fill="white")
    clip = video.ImageClip(np.asarray(image)).with_duration(3)
    zoomed = video._smooth_zoom_clip(clip, 0.09)
    first, last = zoomed.get_frame(0), zoomed.get_frame(3)
    assert first.shape == last.shape == (256, 256, 3)
    assert _white_span(first) == pytest.approx(200, abs=1)
    assert _white_span(last) == pytest.approx(218, abs=1.5)
    spans = [_white_span(zoomed.get_frame(index / 30)) for index in range(1, 85)]
    steps = np.diff(spans)
    assert steps.min() > steps.mean() * 0.5
    assert steps.std() / steps.mean() < 0.3
