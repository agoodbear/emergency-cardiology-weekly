#!/usr/bin/env bash
# ER Cardio Weekly 雲端版：安裝寫稿與驗證需要的工具（冪等，可重跑）。
# 需要的網路：pypi.org、files.pythonhosted.org、github.com、objects.githubusercontent.com
set -euo pipefail
HUGO_VERSION=0.156.0          # 與 agoodbear.github.io/.github/workflows/hugo.yaml 對齊
BIN="$HOME/.local/bin"; mkdir -p "$BIN"; export PATH="$BIN:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

case "$(uname -m)" in
  x86_64|amd64) HARCH=amd64; ZARCH=x86_64 ;;
  aarch64|arm64) HARCH=arm64; ZARCH=aarch64 ;;
  *) echo "unsupported arch $(uname -m)"; exit 1 ;;
esac

command -v uv >/dev/null || python3 -m pip install --quiet --user uv
command -v uv >/dev/null || export PATH="$(python3 -m site --user-base)/bin:$PATH"

if ! hugo version 2>/dev/null | grep -q "v${HUGO_VERSION}+extended"; then
  curl -fsSL "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-${HARCH}.tar.gz" \
    | tar -xz -C "$BIN" hugo
fi

if ! command -v zhtw-mcp >/dev/null; then
  curl -fsSL "https://github.com/sysprog21/zhtw-mcp/releases/latest/download/zhtw-mcp-${ZARCH}-unknown-linux-gnu.tar.gz" \
    | tar -xz -C "$BIN" || echo "WARN: zhtw-mcp 下載失敗，finalize 會略過 lint"
  find "$BIN" -name zhtw-mcp -type f -exec chmod +x {} \; 2>/dev/null || true
fi

(cd "$ROOT" && uv sync --quiet)
echo "setup ok: $(hugo version | cut -d' ' -f2) · uv $(uv --version | cut -d' ' -f2) · zhtw $(command -v zhtw-mcp || echo none)"
