#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "用法：$0 <start-test-run.sh 输出的结果目录>" >&2
  exit 1
fi

result_dir="$1"
if [[ ! -d "$result_dir" || ! -f "$result_dir/run-info.txt" ]]; then
  echo "无效的测试结果目录：$result_dir" >&2
  exit 1
fi

if command -v adb >/dev/null 2>&1; then
  adb_bin="$(command -v adb)"
elif [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/platform-tools/adb" ]]; then
  adb_bin="$ANDROID_HOME/platform-tools/adb"
else
  echo "未找到 adb。请安装 Android Platform-Tools，并把 adb 加入 PATH。" >&2
  exit 1
fi

"$adb_bin" get-state >/dev/null
"$adb_bin" logcat -d -v threadtime > "$result_dir/logcat.txt"
"$adb_bin" shell dumpsys battery > "$result_dir/battery-after.txt"
"$adb_bin" shell dumpsys sensorservice > "$result_dir/sensorservice-after.txt"
"$adb_bin" shell dumpsys meminfo com.realitymemory.glasses > "$result_dir/meminfo-after.txt"
"$adb_bin" shell dumpsys package com.realitymemory.glasses > "$result_dir/package-after.txt"
"$adb_bin" exec-out run-as com.realitymemory.glasses \
  tar -C files -cf - reality-memory > "$result_dir/reality-memory-app-data.tar"

{
  echo ""
  echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >> "$result_dir/run-info.txt"

archive_path="${result_dir%/}.tar.gz"
tar -C "$(dirname "$result_dir")" -czf "$archive_path" "$(basename "$result_dir")"
shasum -a 256 "$archive_path" > "$archive_path.sha256"

echo "测试结果已收集：$result_dir"
echo "GitHub 回传压缩包：$archive_path"
echo "校验文件：$archive_path.sha256"
echo "上传前请确认场景中没有无关人脸、隐私文字或未获同意的对话。"
