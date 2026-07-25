"""把 data/phone/ 下手机采集的素材灌进记忆平台（图片/视频/音频通吃）。

设计前提，三条都不能破：

1. **原件只读。** data/phone/ 下的文件永不被改、永不被删，也**永不作为 storage_ref**。
   最后一条是硬约束：TTL 清理器会 `unlink(storage_ref)`，一旦让它指向原件目录，
   到期那天就把你的原图删了。摄入走的是拷贝——gateway 自己 write_bytes 到 EVIDENCE_DIR。

2. **这批素材不参与短命策略。** 脚本在自己进程里把 EVIDENCE_TTL_MINUTES 设成 100 年，
   所以证据拷贝的 ttl_until 是远期，跑着的 TTL worker 扫到也会跳过。不动 .env，
   眼镜实时采集那条链路的短 TTL（隐私设计）保持原样。

3. **图片不在这里转码——平台自己会转。** gateway 已接入 `app/media/normalize_image`
   （pillow-heif），HEIC 在入库边界统一转 JPEG 并把 EXIF 方向烘进像素。脚本再转一遍
   是重复劳动，而且会绕过平台的分辨率策略：`image_normalize_max_side=0` 是刻意的，
   证据副本要保真，缩图只发生在发给 VLM 的那一刻（`vlm_image_max_side=1024`）。
   所以图片原样上传。

4. **视频必须在这里转。** `app/media` 只管图片，视频是原样落盘的，而 Chrome 多数版本
   放不了 iPhone 的 HEVC .MOV，数据页只会退化成一个下载链接。转 H.264 MP4 并加
   +faststart（不加的话 moov 在文件尾部，浏览器得下完整个文件才能起播）。

时间用 EXIF 拍摄时间（sips -g creation），不是文件 mtime——照片在时间线里的位置
应该是它被拍下的那一刻。

用法：
    cd services/memory-platform
    .venv/bin/python scripts/ingest_phone_media.py --dry-run   # 先看要做什么
    .venv/bin/python scripts/ingest_phone_media.py             # 真灌

灌完由**跑着的后端**的 perception worker 做 VLM 描述 + CLIP 向量（读同一个库的 outbox）。
所以真实 k3 视觉调用会发生，一张图一次。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent

# ---- 必须在导入任何 app 模块前设置 ----
# DATABASE_URL 故意不设：沿用 .env 的 rme 库，跟眼镜采集的记忆混在一起。
os.environ["EVIDENCE_TTL_MINUTES"] = str(100 * 365 * 24 * 60)   # 100 年 ≈ 不删
os.environ["EVIDENCE_DIR"] = str(BASE_DIR / "data" / "evidence-phone")

sys.path.insert(0, str(BASE_DIR))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.llm.fake import FakeLLMClient  # noqa: E402
from app.main import create_app  # noqa: E402
from app.media import open_image  # noqa: E402
from app.vision.fake import FakeVisionEncoder  # noqa: E402

PHONE_DIR = REPO_ROOT / "data" / "phone"

# 视频转码参数。图片没有对应常量——图片的分辨率策略由平台的
# image_normalize_max_side 决定，脚本不该在这里另立一套。
VIDEO_MAX_EDGE = 1280
VIDEO_CRF = 23

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
AUDIO_EXTS = {".m4a", ".wav", ".mp3", ".aac", ".caf"}


EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_IFD = 0x8769


def _exif_capture_time(path: Path) -> datetime | None:
    """EXIF DateTimeOriginal。走 app.media.open_image 以确保 HEIF 解码器已注册。

    EXIF 里的时间没有时区，是拍摄地的墙上时间——按本机时区解释再转 UTC。
    """
    try:
        with open_image(path) as img:
            exif = img.getexif()
            raw = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL) or exif.get(
                EXIF_DATETIME_ORIGINAL
            )
        if not raw:
            return None
        naive = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        return naive.astimezone().astimezone(timezone.utc)
    except Exception:  # noqa: BLE001 - 读不到 EXIF 不该让整批灌入失败
        return None


def _video_capture_time(path: Path) -> datetime | None:
    """视频没有 EXIF，用 macOS 的内容创建时间（mdls）。"""
    try:
        out = subprocess.run(
            ["mdls", "-raw", "-name", "kMDItemContentCreationDate", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if not out or out == "(null)":
            return None
        return datetime.strptime(out, "%Y-%m-%d %H:%M:%S %z").astimezone(timezone.utc)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def _capture_time(path: Path, kind: str) -> tuple[datetime, str]:
    """(拍摄时间, 来源)。取不到就退回文件 mtime——并且把来源标进 meta，
    否则时间线上会出现一个看起来精确、其实是「文件被复制的时刻」的时间点。"""
    found = _exif_capture_time(path) if kind == "image" else _video_capture_time(path)
    if found is not None:
        return found, "exif" if kind == "image" else "mdls"
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc), "file_mtime"


def _has_ffmpeg() -> bool:
    return subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0


def _prepare_video(src: Path, workdir: Path) -> tuple[bytes, str, bool]:
    """HEVC → H.264 MP4，浏览器能直接播。没有 ffmpeg 就原样上传（能落盘总比不落好）。"""
    if not _has_ffmpeg():
        return src.read_bytes(), src.name, False
    out = workdir / f"{src.stem}.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?",   # 只取第一路视频和音频；iPhone 还带空间音频和元数据轨
            "-c:v", "libx264", "-crf", str(VIDEO_CRF), "-preset", "veryfast",
            "-vf", f"scale='min({VIDEO_MAX_EDGE},iw)':-2",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",           # moov 前置，否则浏览器要下完整个文件才起播
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out.read_bytes(), out.name, True


def _discover() -> list[tuple[Path, str]]:
    """扫 data/phone 下所有素材，按扩展名判模态。视频音频以后丢进来自动就被认出。"""
    found: list[tuple[Path, str]] = []
    if not PHONE_DIR.exists():
        return found
    for path in sorted(PHONE_DIR.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            found.append((path, "image"))
        elif ext in VIDEO_EXTS:
            found.append((path, "video"))
        elif ext in AUDIO_EXTS:
            found.append((path, "audio"))
    return found


async def main(dry_run: bool) -> None:
    items = _discover()
    if not items:
        sys.exit(f"{PHONE_DIR} 下没找到素材")

    by_kind: dict[str, int] = {}
    for _, kind in items:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    print(f"data/phone 下发现 {len(items)} 个文件：" + "、".join(f"{k} {v}" for k, v in by_kind.items()))
    print(f"证据拷贝写到 {os.environ['EVIDENCE_DIR']}")
    print(f"TTL = 100 年（原件在 data/phone 下，永不被当作 storage_ref）\n")

    session_id = f"phone-{datetime.now().astimezone():%Y%m%d}"
    app = create_app(fake_llm=FakeLLMClient(), fake_vision=FakeVisionEncoder(), with_workers=False)
    # 注：这里注入 Fake 只是为了别在本进程加载 CLIP 权重——摄入本身不用模型。
    # 真正的 VLM 描述和 CLIP 向量由**跑着的后端** worker 做，用的是它自己的真实实现。

    n_ok = n_dup = 0
    with tempfile.TemporaryDirectory(prefix="rme-phone-") as tmp:
        workdir = Path(tmp)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://ingest", timeout=120) as client:
            for src, kind in items:
                captured, time_source = _capture_time(src, kind)
                raw = src.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()

                if kind == "image":
                    # 原样上传：HEIC→JPEG 由 gateway 的 normalize_image 做，
                    # 它还会把 EXIF 方向烘进像素，比这里再转一遍更对
                    payload, upload_name, transcoded = raw, src.name, False
                elif kind == "video":
                    payload, upload_name, transcoded = _prepare_video(src, workdir)
                else:
                    # 音频原样上传：iPhone 的 .m4a 是 AAC，浏览器能直接播，ASR sidecar 也吃这个
                    upload_name, transcoded = src.name, False
                    payload = raw

                envelope = {
                    "source_session_id": session_id,
                    "occurred_at": captured.isoformat(),
                    "observed_at": captured.isoformat(),
                    # 内容哈希做幂等键：重跑不会灌出第二份
                    "idempotency_key": f"phone:{digest[:32]}",
                    "trigger": "explicit",
                    "modality": kind,
                    "meta": {
                        "origin": "phone",
                        "original_filename": src.name,
                        "original_relpath": str(src.relative_to(REPO_ROOT)),
                        "original_sha256": digest,
                        "original_bytes": len(raw),
                        "transcoded": transcoded,
                        "upload_bytes": len(payload),
                        # 时间是真拍摄时间还是文件 mtime，事后要能分清
                        "capture_time_source": time_source,
                    },
                }

                size = f"{len(raw)/1e6:.1f}M"
                arrow = f"→ {len(payload)/1e6:.1f}M" if transcoded else ""
                # 显示本地时间：存的是 UTC，但读日志的人想看的是「几点拍的」
                local = captured.astimezone()
                mark = "" if time_source in ("exif", "mdls") else " (mtime!)"
                print(f"  {src.name:24} {kind:5} {local:%m-%d %H:%M}{mark} {size:>7} {arrow}")
                if dry_run:
                    continue

                resp = await client.post(
                    "/internal/v1/envelopes",
                    data={"envelope": json.dumps(envelope)},
                    files={"files": (upload_name, payload)},
                )
                if resp.status_code != 200:
                    print(f"    !! {resp.status_code} {resp.text[:200]}")
                    continue
                body = resp.json()
                if body["evidence_item_ids"]:
                    n_ok += 1
                else:
                    # 幂等重放，或近 1 小时内有过相似帧被判为「持续证据」
                    n_dup += 1
                    print("    （已存在或被判为重复，未新建证据）")

    if dry_run:
        print("\n--dry-run：什么都没写。去掉这个参数才会真灌。")
        return
    print(f"\n新建证据 {n_ok} 条，跳过 {n_dup} 条。")
    print("感知（k3 描述 + CLIP 向量）由跑着的后端 worker 处理，稍等即可在「数据」页看到。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写任何东西")
    asyncio.run(main(parser.parse_args().dry_run))
