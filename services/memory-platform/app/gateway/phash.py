"""感知哈希（aHash 64bit）：用于近 1 小时帧去重。"""
from __future__ import annotations

from PIL import Image

from ..media import open_image


def compute_phash(data: bytes) -> int:
    """平均哈希：缩放到 8x8 灰度，与均值比较得到 64bit（按有符号 int64 存储）。"""
    img = open_image(data).convert("L").resize((8, 8), Image.LANCZOS)
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= avg else 0)
    if bits >= (1 << 63):  # PG bigint 是有符号 int64
        bits -= 1 << 64
    return bits


def hamming_distance(a: int, b: int) -> int:
    return bin((a ^ b) & 0xFFFFFFFFFFFFFFFF).count("1")
