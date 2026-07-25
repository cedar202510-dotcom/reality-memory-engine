"""物件缩略图：裁切几何 + 幂等键 + 降级路径。

全是纯函数/工厂测试，不碰数据库——裁切框算错的表现是「图看着有点歪」，
不会报错，所以必须靠断言而不是靠跑一遍看看。
"""
from __future__ import annotations

from app.config import Settings
from app.perception.detect import region_key_for, square_crop_box
from app.vision import NullObjectDetector, build_object_detector


def test_crop_box_is_square_and_centered():
    """普通框：补成正方形，中心不动。"""
    box = square_crop_box({"x": 0.4, "y": 0.4, "w": 0.10, "h": 0.06}, 4000, 3000, padding=0.0)
    left, top, right, bottom = box
    assert right - left == bottom - top, "非正方形套圆遮罩会把主体压变形"
    # 长边 0.10*4000=400，短边 0.06*3000=180 → 取长边
    assert right - left == 400
    assert (left + right) / 2 == 4000 * 0.45  # 中心 = 原框中心
    assert (top + bottom) / 2 == 3000 * 0.43


def test_crop_box_padding_expands():
    plain = square_crop_box({"x": 0.4, "y": 0.4, "w": 0.1, "h": 0.1}, 4000, 3000, padding=0.0)
    padded = square_crop_box({"x": 0.4, "y": 0.4, "w": 0.1, "h": 0.1}, 4000, 3000, padding=0.25)
    assert (padded[2] - padded[0]) > (plain[2] - plain[0])


def test_crop_box_at_edge_stays_inside():
    """贴边的物体：方框整体推回画内，而不是裁出画外的黑边。"""
    box = square_crop_box({"x": 0.97, "y": 0.01, "w": 0.03, "h": 0.03}, 4000, 3000, padding=0.2)
    left, top, right, bottom = box
    assert left >= 0 and top >= 0
    assert right <= 4000 and bottom <= 3000
    assert right - left == bottom - top


def test_crop_box_never_exceeds_short_side():
    """框比画面还大时收到短边，否则 crop 会带出画外区域。"""
    box = square_crop_box({"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, 4000, 3000, padding=0.5)
    assert box[2] - box[0] == 3000
    assert box[3] - box[1] == 3000
    assert box[1] == 0 and box[3] == 3000


def test_crop_box_degenerate_bbox_falls_back_to_full_frame():
    """检测器偶尔给出零宽框：退回整帧，而不是产出 0x0 的裁切崩在 PIL 里。"""
    assert square_crop_box({"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0}, 800, 600, padding=0.1) == (
        0,
        0,
        800,
        600,
    )


def test_region_key_is_stable_and_fits_column():
    """幂等键必须定长：中文物品名直接进 region_key(64) 很容易超长。"""
    key = region_key_for("茶叶铁盒")
    assert key == region_key_for("茶叶铁盒"), "同名两次必须同键，否则回填会写重复行"
    assert key != region_key_for("茶叶盒")
    assert len(region_key_for("很长的物品名" * 20)) <= 64


def test_detector_degrades_without_provider():
    """没配检测器不是错误，只是没有缩略图——全览页照旧显示纯色球。"""
    detector = build_object_detector(Settings(detector_provider="none"))
    assert isinstance(detector, NullObjectDetector)


def test_detector_degrades_when_dependency_missing(monkeypatch):
    """transformers 装不上时也要降级，而不是让 worker 起不来。"""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("transformers"):
            raise ImportError("模拟未安装 transformers")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    detector = build_object_detector(Settings(detector_provider="local"))
    assert isinstance(detector, NullObjectDetector)
