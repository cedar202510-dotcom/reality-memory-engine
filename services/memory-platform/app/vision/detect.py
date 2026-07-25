"""ObjectDetector 协议：开放词表目标检测（拿物品名当 prompt 出框）。

与 VisionEncoder 同风格：业务代码只依赖协议，未配置/推理失败一律返回空列表，绝不抛出。

为什么 CLIP 不够：CLIP 只告诉你「这张图里像有个手机」，不告诉你手机在哪几个像素上。
要给每件物品配一张实拍缩略图，缺的正是这一步定位——没有框就只能拿整帧或几何瓦片
充数，缩到节点那么小时看不出主体是谁。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DetectedBox:
    """一个检测框：label 是命中的 prompt 原文，bbox 是归一化 {x,y,w,h}（左上原点）。

    坐标系与 FrameRegion.bbox 一致——都相对「EXIF 转正后用户看到的那张图」，
    换个坐标系就会画歪，而且歪得很隐蔽（多数照片方向正常，只有竖拍的错）。
    """

    label: str
    score: float
    bbox: dict[str, float]


class ObjectDetector(Protocol):
    """开放词表检测器协议。实现方保证：未配置/推理失败返回 []，绝不抛出。"""

    async def detect(self, image: bytes, prompts: list[str]) -> list[DetectedBox]:
        """图片字节 + 候选物品名（英文短语）→ 每个 prompt 至多一个最佳框。"""
        ...


class NullObjectDetector:
    """恒返回空的检测器：detector_provider=none 或构造失败时的降级实现。

    降级路径必须是「没有缩略图」而不是「报错」：检测器是锦上添花的一层，
    装不上模型时全览页应该照旧显示纯色球，而不是整页打不开。
    """

    async def detect(self, image: bytes, prompts: list[str]) -> list[DetectedBox]:
        return []
