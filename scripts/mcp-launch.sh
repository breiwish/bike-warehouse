#!/bin/bash
# Wrapper so MCP launches with correct cwd regardless of caller.
# Also pre-syncs from cloud release if local warehouse is stale.
set -e
cd "$(dirname "$0")/.."

# Best-effort sync (cache-aware, ~27ms if local fresh). Never block MCP boot
# on sync failures — stale data > no server.
./scripts/sync-fast.sh --quiet 2>/dev/null || true

exec ./.venv/bin/python -m src.mcp_server "$@"
