#!/usr/bin/env bash
set -euo pipefail

port="${1:-8765}"

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
"$adb_bin" reverse "tcp:$port" "tcp:$port"

echo "已建立 RV101 -> 电脑的端口映射：tcp:$port"
"$adb_bin" reverse --list
echo "请确认电脑后端健康检查：curl http://127.0.0.1:$port/healthz"
