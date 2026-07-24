#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path="${1:-$project_dir/device-exports/reality-memory-$(date +%Y%m%d-%H%M%S).tar}"

if command -v adb >/dev/null 2>&1; then
  adb_bin="$(command -v adb)"
elif [[ -n "${ANDROID_HOME:-}" && -x "$ANDROID_HOME/platform-tools/adb" ]]; then
  adb_bin="$ANDROID_HOME/platform-tools/adb"
else
  echo "未找到 adb。请安装 Android Platform-Tools，并把 adb 加入 PATH。" >&2
  exit 1
fi

mkdir -p "$(dirname "$output_path")"
"$adb_bin" get-state >/dev/null
"$adb_bin" exec-out run-as com.realitymemory.glasses \
  tar -C files -cf - reality-memory > "$output_path"

echo "设备数据已导出：$output_path"
echo "其中媒体仍为眼镜 Android Keystore 加密后的密文。"
