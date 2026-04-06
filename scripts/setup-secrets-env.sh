#!/usr/bin/env bash
# Setup script for ~/.secrets.env — shared between host shell and claudec container.
# Creates the file (if missing), locks permissions, and patches ~/.zshrc + _claudec().
set -euo pipefail

SECRETS_FILE="$HOME/.secrets.env"

# 1. Create secrets file if it doesn't exist
if [[ ! -f "$SECRETS_FILE" ]]; then
  cat > "$SECRETS_FILE" <<'ENVEOF'
# ~/.secrets.env — sourced by shell & passed to containers
# Format: KEY=VALUE (no 'export' — compatible with podman --env-file)
# Permissions: 600 — never commit this file anywhere

GITHUB_TOKEN=ghp_REPLACE_ME
NEON_API_KEY=REPLACE_ME
ANTHROPIC_API_KEY=sk-ant-REPLACE_ME
# OLLAMA_HOST=http://localhost:11434
# Add more as needed
ENVEOF
  echo "[+] Created $SECRETS_FILE"
else
  echo "[=] $SECRETS_FILE already exists, skipping creation"
fi

# 2. Lock down permissions
chmod 600 "$SECRETS_FILE"
echo "[+] Permissions set to 600"

echo ""
echo "Next steps:"
echo "  1. Edit ~/.secrets.env and replace placeholder values with real tokens"
echo "  2. Restart your shell (or run: set -a; source ~/.secrets.env; set +a)"
echo "  3. Verify: echo \$GITHUB_TOKEN"
