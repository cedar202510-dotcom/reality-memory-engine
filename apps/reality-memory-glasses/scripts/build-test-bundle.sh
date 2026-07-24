#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-0.1.0-debug}"
apk_path="${2:-$project_dir/app/build/outputs/apk/debug/app-debug.apk}"
bundle_root="$project_dir/release-bundles"
bundle_name="reality-memory-glasses-$version"
bundle_dir="$bundle_root/$bundle_name"

if [[ ! -f "$apk_path" ]]; then
  echo "未找到 APK：$apk_path" >&2
  exit 1
fi

mkdir -p "$bundle_dir/scripts"
cp "$apk_path" "$bundle_dir/reality-memory-glasses-debug.apk"
cp "$project_dir/docs/RV101-TEST-PLAN-v0.1.md" "$bundle_dir/"
cp "$project_dir/scripts/install-on-rv101.sh" "$bundle_dir/scripts/"
cp "$project_dir/scripts/start-test-run.sh" "$bundle_dir/scripts/"
cp "$project_dir/scripts/collect-test-results.sh" "$bundle_dir/scripts/"

(
  cd "$bundle_dir"
  shasum -a 256 reality-memory-glasses-debug.apk > SHA256SUMS
)
mkdir -p "$bundle_root"
(
  cd "$bundle_root"
  zip -qr "$bundle_name.zip" "$bundle_name"
)

echo "测试包已生成：$bundle_root/$bundle_name.zip"
