#!/usr/bin/env bash

set -euo pipefail

adb_bin="$(command -v adb || true)"

if [[ -z "${adb_bin}" ]]; then
    default_adb="${HOME}/Library/Android/sdk/platform-tools/adb"
    if [[ -x "${default_adb}" ]]; then
        adb_bin="${default_adb}"
    fi
fi

if [[ -z "${adb_bin}" ]]; then
    echo "没有找到 adb。"
    echo "请先安装 Android Studio，并在 SDK Manager 中安装 Android SDK Platform-Tools。"
    echo "官方下载：https://developer.android.com/studio"
    exit 1
fi

echo "ADB: ${adb_bin}"
"${adb_bin}" version
echo
echo "已连接设备："
"${adb_bin}" devices -l
echo
echo "如果列表为空：确认手机 Rokid AI App 已开启眼镜 ADB，并使用 Rokid 专用开发线连接电脑。"
