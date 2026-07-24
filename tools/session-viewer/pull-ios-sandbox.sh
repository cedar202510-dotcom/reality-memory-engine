#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ID="${RME_BUNDLE_ID:-com.realitymemoryengine.RMEGlassProbe}"
DEVICE_ID="${1:-${RME_DEVICE_ID:-}}"
DEST="${2:-${RME_CAPTURE_DEST:-/tmp/rme-session-viewer-$(date +%Y%m%d-%H%M%S)}}"

if [[ -z "$DEVICE_ID" ]]; then
  DEVICE_ID="$(xcrun devicectl list devices | grep -Eo '[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}' | head -1 || true)"
fi

if [[ -z "$DEVICE_ID" ]]; then
  echo "没有找到已连接的 iPhone。请先连接设备，或传入 device id。" >&2
  exit 1
fi

mkdir -p "$DEST"

xcrun devicectl device copy from \
  --device "$DEVICE_ID" \
  --domain-type appDataContainer \
  --domain-identifier "$BUNDLE_ID" \
  --source 'Library/Application Support/RealityMemoryProbe' \
  --destination "$DEST"

echo "$DEST"
echo "启动查看器：node tools/session-viewer/server.mjs \"$DEST\""
