#!/usr/bin/env bash
set -euo pipefail

command="${1:-start}"

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

case "$command" in
  start)
    action="com.realitymemory.glasses.START_HEART_RATE_BROADCAST_POC"
    ;;
  stop)
    action="com.realitymemory.glasses.STOP_HEART_RATE_BROADCAST_POC"
    ;;
  *)
    echo "用法：$0 [start|stop]" >&2
    exit 2
    ;;
esac

"$adb_bin" get-state >/dev/null
api_level="$("$adb_bin" shell getprop ro.build.version.sdk | tr -d '\r')"
if [[ "$command" == "start" && "$api_level" -ge 31 ]]; then
  "$adb_bin" shell pm grant \
    com.realitymemory.glasses android.permission.BLUETOOTH_SCAN >/dev/null 2>&1 || true
  "$adb_bin" shell pm grant \
    com.realitymemory.glasses android.permission.BLUETOOTH_CONNECT >/dev/null 2>&1 || true
fi

"$adb_bin" shell am start-foreground-service \
  -n com.realitymemory.glasses/.runtime.RealityRuntimeService \
  -a "$action" >/dev/null

echo "已发送心率广播 POC 命令：$command"
