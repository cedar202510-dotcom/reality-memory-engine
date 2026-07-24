"""LocalCLIPEncoder：本机 open_clip 推理（中文注释；模型只在本机加载，不出网）。

- open_clip 为可选依赖：此处 lazy import，未安装时构造抛错，
  由 build_vision_encoder 工厂捕获并降级为 NullVisionEncoder。
- 推理是 CPU/GPU 密集同步调用，一律包 asyncio.to_thread，避免阻塞事件循环。
- 文本/图片向量都 L2 归一化，检索直接用 cosine 距离。
"""
from __future__ import annotations

import asyncio
import io
import math
from typing import Any

# 默认模型与权重（open_clip 注册名）
DEFAULT_MODEL = "ViT-B-32"
DEFAULT_PRETRAINED = "laion2b_s34b_b79k"


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def _create_model(model_name: str, pretrained: str, device: str, *, prefer_hf_hub: bool) -> Any:
    """加载 open_clip 模型，处理两个现实环境的坑：

    1. 网络受限时 HF Hub 下载过慢：prefer_hf_hub=False 强制走权重直链
       （open_clip 对直链有本地缓存 + sha256 校验，已缓存则秒回）。
    2. torch>=2.6 默认 weights_only=True，与 OpenAI 发布的 TorchScript
       权重存档不兼容：给 load_state_dict 包一层 torch.jit.load 回退。
    pretrained tag 带 quick_gelu=True（如 openai）时显式 force_quick_gelu，
    避免新旧配置不一致导致激活函数错配、向量质量下降。
    """
    import open_clip  # noqa: PLC0415
    import open_clip.factory as _factory  # noqa: PLC0415
    import torch  # noqa: PLC0415

    force_quick_gelu = False
    try:
        cfg = open_clip.get_pretrained_cfg(model_name, pretrained)
        force_quick_gelu = bool(cfg.get("quick_gelu"))
    except Exception:  # noqa: BLE001 - cfg 查询失败不阻塞（如本地路径权重）
        pass

    def _load() -> Any:
        return open_clip.create_model_and_transforms(
            model_name,
            pretrained=pretrained,
            device=device,
            force_quick_gelu=force_quick_gelu,
        )

    orig_download = _factory.download_pretrained
    if not prefer_hf_hub:
        import functools

        _factory.download_pretrained = functools.partial(orig_download, prefer_hf_hub=False)
    try:
        try:
            return _load()
        except RuntimeError as exc:
            if "TorchScript" not in str(exc) and "weights_only" not in str(exc):
                raise
            orig_load = _factory.load_state_dict

            def _load_with_jit_fallback(checkpoint_path, device="cpu", weights_only=True):  # noqa: ANN001, ANN202
                try:
                    return orig_load(checkpoint_path, device=device, weights_only=weights_only)
                except RuntimeError:
                    sd = torch.jit.load(checkpoint_path, map_location=device).state_dict()
                    # TorchScript 存档带三个非参数 buffer，strict 加载会报 unexpected key
                    for k in ("input_resolution", "context_length", "vocab_size"):
                        sd.pop(k, None)
                    return sd

            _factory.load_state_dict = _load_with_jit_fallback
            try:
                return _load()
            finally:
                _factory.load_state_dict = orig_load
    finally:
        _factory.download_pretrained = orig_download


class LocalCLIPEncoder:
    """本机 CLIP 编码器。构造即加载模型（懒 import）；构造失败由工厂降级。"""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        pretrained: str = DEFAULT_PRETRAINED,
        device: str | None = None,
        prefer_hf_hub: bool = True,
    ) -> None:
        try:
            import torch  # noqa: PLC0415
            from PIL import Image  # noqa: PLC0415
        except ImportError as exc:  # 让工厂可捕获并降级
            raise RuntimeError(
                "open_clip/torch 未安装：vision_provider=local 需要先安装可选依赖"
                "（见 requirements.txt 注释），或改用 http/fake/none"
            ) from exc

        self._torch = torch
        self._Image = Image
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model, _, self._preprocess = _create_model(
            model_name, pretrained, self._device, prefer_hf_hub=prefer_hf_hub
        )
        self._model.eval()
        import open_clip  # noqa: PLC0415

        self._tokenizer = open_clip.get_tokenizer(model_name)

    @property
    def dim(self) -> int:
        return int(self._model.visual.output_dim)

    # ---- 同步推理（在线程池里跑） ----

    def _encode_images_sync(self, images: list[bytes]) -> list[list[float]]:
        torch = self._torch
        tensors = [
            self._preprocess(self._Image.open(io.BytesIO(b)).convert("RGB")) for b in images
        ]
        batch = torch.stack(tensors).to(self._device)
        with torch.no_grad():
            feats = self._model.encode_image(batch)
        return [_l2_normalize(row.tolist()) for row in feats.cpu()]

    def _encode_texts_sync(self, texts: list[str]) -> list[list[float]]:
        tokens = self._tokenizer(texts).to(self._device)
        with self._torch.no_grad():
            feats = self._model.encode_text(tokens)
        return [_l2_normalize(row.tolist()) for row in feats.cpu()]

    # ---- 协议方法：任何异常都返回 None（调用方降级） ----

    async def embed_images(self, images: list[bytes]) -> list[list[float]] | None:
        if not images:
            return []
        try:
            return await asyncio.to_thread(self._encode_images_sync, images)
        except Exception:  # noqa: BLE001 - 编码失败不阻塞流水线
            return None

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not texts:
            return []
        try:
            return await asyncio.to_thread(self._encode_texts_sync, texts)
        except Exception:  # noqa: BLE001
            return None
