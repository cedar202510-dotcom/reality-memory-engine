#!/usr/bin/env bash
set -euo pipefail

message="${1:-记得把资料给小王}"

if command -v adb >/dev/null 2>&1; then
  adb_bin="$(command -v adb)"
elif [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/platform-tools/adb" ]]; then
  adb_bin="$ANDROID_HOME/platform-tools/adb"
elif [[ -x "$HOME/Library/Android/sdk/platform-tools/adb" ]]; then
  adb_bin="$HOME/Library/Android/sdk/platform-tools/adb"
else
  echo "未找到 adb。请安装 Android Platform-Tools，并把 adb 加入 PATH。" >&2
  exit 1
fi

"$adb_bin" get-state >/dev/null
"$adb_bin" shell am start \
  -n com.realitymemory.glasses/.MainActivity \
  --es debug_reminder_text "$message" >/dev/null

echo "已发送 Debug 测试提醒：$message"
