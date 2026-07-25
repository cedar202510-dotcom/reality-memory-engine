#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_PATH="${1:-$HOME/Desktop/Reality Memory Debug Console.app}"
CONTENTS="$OUTPUT_PATH/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

rm -rf "$OUTPUT_PATH"
mkdir -p "$MACOS" "$RESOURCES"
cp "$SCRIPT_DIR/server.mjs" "$RESOURCES/server.mjs"
cp "$SCRIPT_DIR/rv101-adb.mjs" "$RESOURCES/rv101-adb.mjs"
cp "$SCRIPT_DIR/rv101-page.mjs" "$RESOURCES/rv101-page.mjs"

cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>Reality Memory 调试台</string>
  <key>CFBundleExecutable</key>
  <string>RealityMemoryDebugConsole</string>
  <key>CFBundleIdentifier</key>
  <string>com.realitymemoryengine.debug-console</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Reality Memory Debug Console</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$MACOS/RealityMemoryDebugConsole" <<'LAUNCHER'
#!/usr/bin/env bash
set -u

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="$CONTENTS/Resources/server.mjs"
DATA_ROOT="$HOME/Library/Application Support/RealityMemoryDebug"
STATE_ROOT="$HOME/Library/Application Support/RealityMemoryDebugConsole"
LOG_ROOT="$HOME/Library/Logs"
PID_FILE="$STATE_ROOT/server.pid"
LOG_FILE="$LOG_ROOT/RealityMemoryDebugConsole.log"
PORT=8787

mkdir -p "$DATA_ROOT/sessions" "$STATE_ROOT" "$LOG_ROOT"

find_node() {
  local candidate
  for candidate in \
    "$HOME/.local/bin/node" \
    "/opt/homebrew/bin/node" \
    "/usr/local/bin/node" \
    "/usr/bin/node"
  do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  command -v node 2>/dev/null || return 1
}

NODE="$(find_node || true)"
if [[ -z "$NODE" ]]; then
  /usr/bin/osascript -e 'display alert "Reality Memory 调试台无法启动" message "没有找到 Node.js。请先安装 Node.js，再重新打开调试台。" as critical'
  exit 1
fi

is_debug_console_ready() {
  /usr/bin/curl --silent --fail --max-time 1 "http://127.0.0.1:$PORT/api/live" >/dev/null 2>&1
}

if ! is_debug_console_ready; then
  if [[ -f "$PID_FILE" ]]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
      kill "$OLD_PID" 2>/dev/null || true
      sleep 0.3
    fi
  fi

  nohup "$NODE" "$SERVER" --live "$DATA_ROOT" "$PORT" >>"$LOG_FILE" 2>&1 &
  SERVER_PID=$!
  printf '%s\n' "$SERVER_PID" > "$PID_FILE"

  for _ in {1..40}; do
    if is_debug_console_ready; then
      break
    fi
    sleep 0.2
  done
fi

if is_debug_console_ready; then
  /usr/bin/open "http://127.0.0.1:$PORT/"
  exit 0
fi

/usr/bin/osascript -e 'display alert "Reality Memory 调试台启动失败" message "请查看 ~/Library/Logs/RealityMemoryDebugConsole.log 获取错误信息。" as critical'
exit 1
LAUNCHER

chmod +x "$MACOS/RealityMemoryDebugConsole"
plutil -lint "$CONTENTS/Info.plist" >/dev/null
codesign --force --deep --sign - "$OUTPUT_PATH" >/dev/null 2>&1

printf '已生成：%s\n' "$OUTPUT_PATH"
