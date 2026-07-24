#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_id="${1:-$(date +%Y%m%d-%H%M%S)-rv101-native}"
result_dir="${2:-$project_dir/device-test-results/$run_id}"

if command -v adb >/dev/null 2>&1; then
  adb_bin="$(command -v adb)"
elif [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/platform-tools/adb" ]]; then
  adb_bin="$ANDROID_HOME/platform-tools/adb"
else
  echo "未找到 adb。请安装 Android Platform-Tools，并把 adb 加入 PATH。" >&2
  exit 1
fi

mkdir -p "$result_dir"
"$adb_bin" get-state >/dev/null
"$adb_bin" reverse tcp:8765 tcp:8765
"$adb_bin" devices -l > "$result_dir/adb-devices-before.txt"
"$adb_bin" reverse --list > "$result_dir/adb-reverse-before.txt"
"$adb_bin" shell getprop > "$result_dir/device-getprop.txt"
"$adb_bin" shell dumpsys sensorservice > "$result_dir/sensorservice-before.txt"
"$adb_bin" shell dumpsys battery > "$result_dir/battery-before.txt"
"$adb_bin" shell dumpsys package com.realitymemory.glasses > "$result_dir/package-before.txt"
"$adb_bin" logcat -c
"$adb_bin" shell am force-stop com.realitymemory.glasses
"$adb_bin" shell monkey -p com.realitymemory.glasses 1 >/dev/null

{
  echo "run_id=$run_id"
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "result_dir=$result_dir"
  echo "apk_version=$("$adb_bin" shell dumpsys package com.realitymemory.glasses | awk -F= '/versionName=/{print $2; exit}' | tr -d '\r')"
} > "$result_dir/run-info.txt"

echo "测试已开始：$run_id"
echo "请按 RV101-TEST-PLAN-v0.1.md 完成动作。结束后执行："
echo "  ./scripts/collect-test-results.sh '$result_dir'"
