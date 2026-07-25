# Rokid Glasses 第一阶段开发指南

## 1. 当前结论

RealGit 的第一步需要验证“眼镜本机持续采集能力”，因此当前主路线
是 **眼镜端裸机 Android App**，不是 CXR-L 手机 App。

官方 SDK 页面给出的三条路线如下：

| 路线 | 运行位置 | 是否公开 | 是否需要 Rokid AI App | 本阶段用途 |
| --- | --- | --- | --- | --- |
| 眼镜端裸机开发 1.0.0 | 眼镜本机 | 是 | 否（运行时） | 当前主路线 |
| CXR-L 1.0.4 | Android/iOS 手机 | 是 | 是 | 本机路线失败时的手机协同备选 |
| CXR-M 1.1.0 | Android 手机 | 否，需商务对接 | 否，且不可与 Rokid AI App 并行 | 当前不使用 |

这里的“Rokid AI App 不需要”是指裸机 App 运行时不通过它获得相机能力；首次打开
眼镜 ADB 时，官方流程仍要求在手机 Rokid AI App 中操作。

## 2. 为什么当前工程不加入 CXR-L

`apps/rokid-glass-probe/app` 最终会打包为安装到眼镜上的 APK。官方裸机文档明确说明：

- YodaOS-Sprite 基于 Android 12 / API 31 / Android Go
- 使用标准 Android 工程
- 使用标准 Android API
- 不依赖手机端协同 SDK
- 拍照/录像使用 CameraX
- 音频使用 AudioRecord
- IMU 使用 SensorManager
- 按键、佩戴和折叠使用系统广播和 KeyEvent

所以当前 `app/build.gradle.kts` 中只有 AndroidX、CameraX 和生命周期依赖，这是
正确的。不要把下面的 CXR-L 依赖加到眼镜 App 中，否则会把手机协同架构和裸机
架构混在一起。

## 3. CXR-L 什么时候加入

出现以下任一情况时，再单独创建手机端模块，例如 `mobile-cxr-l`：

- Android 12 后台限制导致眼镜本机无法稳定采集
- 需要由手机负责授权、连接或媒体中继
- 需要经 Rokid AI App 获取图像、音频、显示或指令能力
- 产品决定不在眼镜上常驻第三方 App

届时 Maven 配置只应存在于手机端工程或模块。

`settings.gradle.kts`：

```kotlin
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        maven {
            url = uri("https://maven.rokid.com/repository/maven-public/")
        }
    }
}
```

手机模块的 `build.gradle.kts`：

```kotlin
dependencies {
    implementation("com.rokid.cxr:client-l:1.0.4")
}
```

CXR-L 的 Android 最低版本同样要求 `minSdk >= 31`。连接还需要授权 token，并且
必须等待 CXR 会话和眼镜蓝牙链路都就绪。`connect(token)` 返回不代表立刻可以
拍照或推流。

## 4. CXR-M 为什么不纳入

Rokid 开放平台当前把 CXR-M 1.1.0 标为“商务合作/商务对接”，并写明 SDK、文档
和技术支持不在开发者站点公开提供。它面向 Android 手机，支持实时音视频、
Wi-Fi P2P 和自定义场景，并可与眼镜端 CXR-S 配合。

因此：

- 不把社区反向实现或上传工具当作正式产品依赖
- 不用 CXR-M 作为当前 APK 的安装前提
- 没有正式商务授权和 SDK 前，不设计基于 CXR-M 的产品架构

## 5. ADB 开关打开以后做什么

官方裸机快速开始写明：

1. 准备 Rokid Glasses 真机和专用开发线。
2. 手机 Rokid AI App 与眼镜连接。
3. 在手机 App 内打开眼镜 ADB。
4. 用开发线把眼镜连接到 Mac。
5. Android Studio 安装好 Platform-Tools 后执行：

```bash
adb devices
```

预期输出类似：

```text
List of devices attached
<device-serial>    device
```

常见结果：

| 输出 | 含义 | 下一步 |
| --- | --- | --- |
| `device` | 已连接并授权 | 可以安装 APK |
| `unauthorized` | 已发现但未授权 | 在眼镜/App 中确认授权，再重试 |
| 空列表 | 电脑没识别到 ADB 设备 | 检查是否为开发线、USB 接口和 ADB 开关 |
| `offline` | 连接建立但服务异常 | 重插开发线，关闭再打开 ADB |

安装 APK：

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

查看日志：

```bash
adb logcat -s RealityGlassProbe
```

读取本地审计日志：

```bash
adb shell run-as com.realitymemory.glassprobe \
  cat files/probe-log.jsonl
```

## 6. 推荐的验证顺序

### A. 先验证官方 Sample

官方 `GlassesBareDevSample` 已覆盖：

- CameraX 无预览拍照/录像
- AudioRecord
- 佩戴和镜腿折叠广播
- KeyEvent / TouchPad
- SensorManager / IMU

先跑通它可以证明“设备、开发线、ADB 和官方基线”正常。

### B. 再验证 RealityGlassProbe

重点记录：

- 眼镜型号、系统版本和构建号
- Rokid AI App 版本
- 是否能收到佩戴/摘下广播
- 首次 CameraX 绑定耗时
- 单张拍摄耗时和文件大小
- 文件删除结果
- 前台、后台、锁屏、摘下时的行为
- 30 分钟内温升、耗电、崩溃和丢帧

### C. 最后决定是否需要 CXR-L

只有在裸机路径不能满足生命周期、稳定性或联网要求时，才建立
`mobile-cxr-l` 手机模块做对照实验。这个决策应由真机数据驱动，而不是在第一步
同时维护两套架构。

## 7. 官方资料

- [Rokid SDK 列表](https://open.rokid.com/sdk?lang=zh)
- [Rokid 眼镜端裸机开发 v1.0.0](https://custom.rokid.com/prod/rokid_web/ff28c865a9634876be98cbc293588460/pc/cn/index.html)
- [CXR-L SDK v1.0.4](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/3b63d21420e645e3affca478b39e4a13.html)
- [GlassesBareDevSample.zip](https://rokid-ota.oss-cn-hangzhou.aliyuncs.com/toB/Document/CXR_Bare/GlassesBareDevSample.zip)
- [Android Studio 官方下载](https://developer.android.com/studio)
