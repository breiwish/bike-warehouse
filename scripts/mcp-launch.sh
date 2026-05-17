#!/bin/bash
# Wrapper so MCP launches with correct cwd regardless of caller.
cd "$(dirname "$0")/.."
exec ./.venv/bin/python -m src.mcp_server "$@"
