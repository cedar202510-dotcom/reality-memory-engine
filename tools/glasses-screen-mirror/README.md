# 眼镜屏幕镜像桥

把眼镜的**屏幕内容**（不是相机画面）以 MJPEG 流的形式发到本机，供前端联调页显示。

相机第一视角走探针 App 自带的 `:8090`（见 `apps/rokid-glass-probe`）；这个脚本补的是
另一条：看眼镜 UI 上正在发生什么（App 状态、系统弹窗、权限对话框）。

## 用法

```bash
adb devices              # 确认眼镜已连接
python3 screen-stream.py # 默认 8091，可传端口参数
```

然后在前端联调页的地址栏填 `http://127.0.0.1:8091/stream` 点连接。

| 路径 | 内容 |
| --- | --- |
| `/stream` | MJPEG（multipart/x-mixed-replace），前端 `<img>` 直接吃 |
| `/frame` | 最新单帧 PNG |
| `/` | 自带的极简预览页 |

## 限制

- 帧率受 `adb screencap` 限制，USB 下约 1–3 fps；看 UI 状态够用，不适合看动作
- 眼镜屏幕休眠时镜像是黑的（联调时用 `adb shell svc power stayon usb` 保持常亮）
- 零依赖（只用标准库 + adb），无认证明文 HTTP，仅限本机联调
