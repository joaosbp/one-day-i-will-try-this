#!/bin/bash
# update-and-push.sh — Generate README.md from GitHub stars and push changes.
# Source of truth lives in ~/one-day-i-will-try-this/.
# Hermes cron executes ~/.hermes/scripts/update-and-push.sh, which should be a small shim.

set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/one-day-i-will-try-this}"
cd "$REPO_DIR"

# Cron environments are minimal; ensure user-installed CLIs are available.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if ! command -v git >/dev/null 2>&1; then
    echo "❌ git não encontrado"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 não encontrado"
    exit 1
fi

# Safety: do not run on top of uncommitted tracked source changes.
# Ignored cache files (.repo_cache.json, __pycache__) do not count.
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "❌ Repositório tem alterações tracked não commitadas. Abortando para evitar sobrescrever trabalho local."
    git status --short
    exit 1
fi

# Pull latest changes first. If this fails, abort instead of generating README on stale state.
git fetch origin main --quiet
git pull --rebase --quiet origin main

# Run the generator with output captured. Temporarily disable set -e so we can show useful errors.
set +e
OUTPUT=$(python3 update_readme.py 2>&1)
EXIT_CODE=$?
set -e

if [ $EXIT_CODE -ne 0 ]; then
    echo "❌ Erro ao gerar README:"
    echo "$OUTPUT" | tail -30
    exit $EXIT_CODE
fi

# Extract summary stats. grep returns 1 when not found, so use || true with set -e.
REPO_COUNT=$(echo "$OUTPUT" | grep "Found" | head -1 | awk '{print $2}' || true)
REAL_COUNT=$(echo "$OUTPUT" | grep "Real projects" | awk '{print $3}' || true)
REF_COUNT=$(echo "$OUTPUT" | grep "Reference stuff" | awk '{print $3}' || true)
HYPE_LINE=$(echo "$OUTPUT" | grep "^Real:" | head -1 || true)
ACT_LINE=$(echo "$OUTPUT" | grep "^Real:" | tail -1 || true)
CACHE_LINE=$(echo "$OUTPUT" | grep "Cache saved" | tail -1 || true)

if [ -z "${REPO_COUNT:-}" ]; then REPO_COUNT="?"; fi
if [ -z "${REAL_COUNT:-}" ]; then REAL_COUNT="?"; fi
if [ -z "${REF_COUNT:-}" ]; then REF_COUNT="?"; fi

# Check if README changed.
if git diff --quiet README.md; then
    echo "✅ Nenhuma alteração (README já está atualizado)"
    echo "📊 $REPO_COUNT repos ($REAL_COUNT real + $REF_COUNT ref)"
    if [ -n "$CACHE_LINE" ]; then echo "🗃️  $CACHE_LINE"; fi
    exit 0
fi

# Commit and push README only. The generator script is source; README is generated output.
git add README.md
git commit --quiet -m "auto: update $(date +%Y-%m-%d)"
git push --quiet origin main

echo "✅ README atualizado e push feito!"
echo "📊 $REPO_COUNT repos ($REAL_COUNT real + $REF_COUNT ref)"
if [ -n "$HYPE_LINE" ]; then echo "🔥 Hype: $HYPE_LINE"; fi
if [ -n "$ACT_LINE" ]; then echo "⚡ Activity: $ACT_LINE"; fi
if [ -n "$CACHE_LINE" ]; then echo "🗃️  $CACHE_LINE"; fi
