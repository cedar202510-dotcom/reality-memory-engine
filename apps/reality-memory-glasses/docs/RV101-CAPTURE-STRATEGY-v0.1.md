# RV101 眼镜端采集策略与当前验证顺序 v0.1

## 1. 当前先解决什么

当前第一目标不是立刻优化所有运动阈值和视频时长，而是先证明这条链路可靠：

```text
RV101 无业务预览拍照
  -> 本地 JPG
  -> CaptureAttempt / EvidenceItem / SourceEnvelope
  -> Debug 上传队列
  -> adb reverse
  -> 电脑后端接收并幂等入库
```

上一轮图片和视频都在相机准备阶段失败。Rokid 官方 Sample 的确认路径是拍照只绑定
`ImageCapture`、录像只绑定 `VideoCapture`，两者都不需要 `Preview`。因此当前
Runtime 不再同时绑定图片和视频。

## 2. 当前相机状态机

```text
服务进入前台并获得相机权限
  -> 只绑定 ImageCapture
  -> IMAGE_READY

图片请求
  -> 保持 IMAGE_READY
  -> 拍一张图片

视频请求
  -> 拒绝同时到达的其它相机请求
  -> unbindAll
  -> 只绑定 VideoCapture
  -> VIDEO_RECORDING
  -> Finalize
  -> unbindAll
  -> 重新只绑定 ImageCapture
  -> IMAGE_READY
```

相机绑定、图片拍摄和视频模式切换期间，新的相机请求记录为 `CAMERA_BUSY`，不排队
形成过时证据。音频和 IMU 使用各自设备通道，仍可与当前采集窗口并行。

## 3. 当前临时策略

| 场景 | 当前采集 |
| --- | --- |
| 佩戴后首次窗口 | 图片 + IMU |
| 低频基线 | 图片 + IMU |
| 普通头部变化 | 图片 + 10 秒音频 + IMU |
| 强头部变化 | 2.5 秒视频 + 10 秒音频 + IMU |
| 用户主动“记一下” | 图片 + 10 秒音频 + IMU |

`2.5 秒`只是沿用既有真机验证值，不是最终产品结论。本轮不依据尚未成功的相机样本
扩展视频时长。

## 4. 后续策略方向

图片链路和模式切换得到真实延迟、帧率、温升与信息增量后，再比较以下有界策略：

1. 单张图片：场景稳定、物品和状态摘要。
2. 前后两帧：拿起、放下、开合等状态变化。
3. 快速短视频：短促但静态帧难表达的动作。
4. 延长短视频：运动持续且仍有信息增量时，在明确上限内延长。
5. 语音关联窗口：动作附近检测到有效人声时延长音频，而不是持续保存环境音。

无论采用哪一档，都不进入连续录像；最终时长由真机数据、功耗、温升、隐私和后端
解析收益共同决定。

## 5. 第一轮图片验收

必须同时满足：

- `audit.ndjson` 出现 `CAMERA_PREPARED_IMAGE_ONLY`。
- 相机清单包含镜头方向、硬件等级、可用帧率范围和输出尺寸。
- 图片 `CaptureAttempt.result` 为 `SUCCEEDED`，而不是零延迟
  `DEVICE_UNAVAILABLE`。
- Debug 导出存在可打开的 JPG，宽高和字节数大于 0。
- `EvidenceItem.media.capture_mode` 为 `CAMERAX_IMAGE_ONLY_NO_PREVIEW`。
- 电脑后端收到相同 `evidence_item_id` 和 `capture_window_id`。
- 重试不产生重复入库。

图片链路通过后，第二轮才验证 `IMAGE -> VIDEO -> IMAGE` 切换和视频实际帧率。
