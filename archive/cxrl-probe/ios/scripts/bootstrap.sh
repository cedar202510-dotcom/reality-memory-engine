#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IOS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export PATH="$HOME/.gem/ruby/2.6.0/bin:$PATH"
export RUBYOPT="${RUBYOPT:+$RUBYOPT }-rlogger"

cd "$IOS_DIR"
pod install

printf '\nReady. Open:\n  %s\n' "$IOS_DIR/CXRClientDemo.xcworkspace"
