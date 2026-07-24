#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_apk="$project_dir/app/build/outputs/apk/debug/app-debug.apk"
apk_path="${1:-$default_apk}"

if command -v adb >/dev/null 2>&1; then
  adb_bin="$(command -v adb)"
elif [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/platform-tools/adb" ]]; then
  adb_bin="$ANDROID_HOME/platform-tools/adb"
else
  echo "未找到 adb。请安装 Android Platform-Tools，并把 adb 加入 PATH。" >&2
  exit 1
fi

if [[ ! -f "$apk_path" ]]; then
  echo "未找到 APK：$apk_path" >&2
  exit 1
fi

device_lines="$("$adb_bin" devices | awk 'NR > 1 && NF > 0 { print $1, $2 }')"
device_count="$(printf '%s\n' "$device_lines" | awk '$2 == "device" { count += 1 } END { print count + 0 }')"

if [[ "$device_count" -ne 1 ]]; then
  echo "需要且只允许连接一台状态为 device 的眼镜，当前设备列表：" >&2
  "$adb_bin" devices -l >&2
  echo "请在 Rokid AI App 打开眼镜 ADB 调试，并检查开发线和授权状态。" >&2
  exit 1
fi

echo "正在安装：$apk_path"
"$adb_bin" install -r "$apk_path"
echo "安装完成。正在启动 Reality Memory..."
"$adb_bin" shell am force-stop com.realitymemory.glasses
"$adb_bin" shell monkey -p com.realitymemory.glasses 1 >/dev/null
echo "已启动。实时日志命令："
echo "  $adb_bin logcat --pid=\$($adb_bin shell pidof -s com.realitymemory.glasses)"
