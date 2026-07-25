"""IFLYBUDS 宿主侧采集器：把一副蓝牙耳机接进 RealGit 的上行与下行通道。

耳机本身跑不了我方代码，也不会来拉 inbox，所以 04 号文档三段式里的「设备侧 Collector」
落在**宿主机**上（Mac / 未来的手机 App），耳机只提供麦克风和扬声器：

    IFLYBUDS Air 2 (HFP mic / A2DP out)
      -> 本采集器（录音 → 本地 spool → 上传；订阅下行 → 本地策略 → 播报）
      -> SourceEnvelope(modality=audio) / DeliveryReceipt
      -> Memory Platform

后端不认识 IFLYBUDS：设备差异只出现在信封 meta 的 device_kind / device_adapter 两个
字段里，控制通道复用现成的 inbox，一行后端代码都不需要为它新增。
"""
from .config import ADAPTER_VERSION, DEVICE_ADAPTER, DEVICE_KIND, Config

__all__ = ["ADAPTER_VERSION", "Config", "DEVICE_ADAPTER", "DEVICE_KIND"]
__version__ = ADAPTER_VERSION
