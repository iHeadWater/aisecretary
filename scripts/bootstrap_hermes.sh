#!/usr/bin/env bash
# bootstrap_hermes.sh
#
# Wire aisecretary into a local Hermes installation.
# Safe to run multiple times — all operations are idempotent.
#
# What this does:
#   1. Verifies ~/.hermes/config.yaml exists
#   2. Registers ~/code/aisecretary/skills in skills.external_dirs (if not already present)
#   3. Backs up ~/.hermes/SOUL.md → SOUL.md.bak (only on first run)
#   4. Injects task_secretary_rules.md into SOUL.md under a labelled block, refreshing it if already present
#
# Requirements: bash, python3 (macOS system python is sufficient), sed, grep

set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────────────────

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CONFIG_YAML="$HERMES_HOME/config.yaml"
SOUL_MD="$HERMES_HOME/SOUL.md"
SOUL_BAK="$HERMES_HOME/SOUL.md.bak"
SKILLS_SRC="$REPO_DIR/skills/transaction_manager"
SKILLS_DEST="$HERMES_HOME/skills/transaction_manager"
PROMPT_FILE="$REPO_DIR/prompts/task_secretary_rules.md"
BLOCK_MARKER="Transaction Secretary Rules (aisecretary)"

# ── Helpers ──────────────────────────────────────────────────────────────────

ok()   { echo "  ✅  $*"; }
skip() { echo "  ⏭️   $*"; }
info() { echo "  ℹ️   $*"; }
fail() { echo "  ❌  $*" >&2; exit 1; }

# ── Header ───────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         aisecretary → Hermes bootstrap               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Verify Hermes config exists ──────────────────────────────────────

echo "Step 1: Checking Hermes config"
if [ ! -f "$CONFIG_YAML" ]; then
    fail "~/.hermes/config.yaml not found. Is Hermes installed and initialised?"
fi
ok "Found $CONFIG_YAML"

# ── Step 2: Copy skill files to ~/.hermes/skills/ ────────────────────────────
#
# Hermes runs inside Docker with ~/.hermes/ mounted. Registering an external_dirs
# path on the host filesystem is invisible to the container, so we copy the skill
# files directly into ~/.hermes/skills/transaction_manager/ instead.

echo ""
echo "Step 2: Copying skill files to $SKILLS_DEST"

if [ ! -d "$SKILLS_SRC" ]; then
    fail "Skill source directory not found: $SKILLS_SRC"
fi

mkdir -p "$SKILLS_DEST"
cp -f "$SKILLS_SRC/SKILL.md"         "$SKILLS_DEST/SKILL.md"
cp -f "$SKILLS_SRC/tool_contract.md" "$SKILLS_DEST/tool_contract.md"
ok "Copied skill files to $SKILLS_DEST"

# ── Step 3: Back up SOUL.md ───────────────────────────────────────────────────

echo ""
echo "Step 3: Backing up SOUL.md"

if [ ! -f "$SOUL_MD" ]; then
    fail "$SOUL_MD not found. Is Hermes initialised?"
fi

if [ -f "$SOUL_BAK" ]; then
    skip "Backup already exists at $SOUL_BAK"
else
    cp "$SOUL_MD" "$SOUL_BAK"
    ok "Backed up SOUL.md → SOUL.md.bak"
fi

# ── Step 4: Inject prompt block into SOUL.md ─────────────────────────────────

echo ""
echo "Step 4: Injecting Transaction Secretary Rules into SOUL.md"

if [ ! -f "$PROMPT_FILE" ]; then
    fail "Prompt file not found: $PROMPT_FILE"
fi

if grep -qF "$BLOCK_MARKER" "$SOUL_MD" 2>/dev/null; then
    # Remove the previously-injected block (its heading → EOF; the block is
    # always appended last) so the current prompt content replaces it.
    sed -i "/^## $BLOCK_MARKER/,\$d" "$SOUL_MD"
    # Trim trailing blank lines so spacing stays stable across re-runs.
    sed -i -e :a -e '/^[[:space:]]*$/{$d;N;ba}' "$SOUL_MD"
    action="Refreshed"
else
    action="Appended"
fi

{
    printf '\n'
    printf '## %s\n' "$BLOCK_MARKER"
    printf '\n'
    # Skip the first-line "# Task Secretary Rules" heading to avoid duplication
    # (the block marker above already acts as section heading)
    tail -n +2 "$PROMPT_FILE"
} >> "$SOUL_MD"
ok "$action '$BLOCK_MARKER' block in SOUL.md"

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Bootstrap complete.                                  ║"
echo "║  Run scripts/verify_hermes_wiring.sh to confirm.     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
