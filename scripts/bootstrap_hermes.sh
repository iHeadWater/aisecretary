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
#   4. Appends task_secretary_rules.md to SOUL.md under a labelled block (if not already present)
#
# Requirements: bash, python3 (macOS system python is sufficient), sed, grep

set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────────────────

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CONFIG_YAML="$HERMES_HOME/config.yaml"
SOUL_MD="$HERMES_HOME/SOUL.md"
SOUL_BAK="$HERMES_HOME/SOUL.md.bak"
SKILLS_DIR="$REPO_DIR/skills"
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

# ── Step 2: Register skills/external_dirs ────────────────────────────────────

echo ""
echo "Step 2: Registering skills external_dirs"

if ! [ -d "$SKILLS_DIR" ]; then
    fail "Skills directory not found: $SKILLS_DIR"
fi

# Normalise the path to store — use the tilde form so it's portable across users
# but store the real expanded path to make grep matching reliable.
# We store the literal "~/code/aisecretary/skills" form.
SKILLS_ENTRY="~/code/aisecretary/skills"

if grep -qF "$SKILLS_ENTRY" "$CONFIG_YAML" 2>/dev/null; then
    skip "external_dirs already contains '$SKILLS_ENTRY'"
else
    # Use python3 (stdlib only) to surgically patch the YAML.
    # Strategy: find the "  external_dirs:" key and either
    #   (a) replace "external_dirs: []" with multi-line form, or
    #   (b) append a new "  - <path>" line after the existing external_dirs header.
    python3 - "$CONFIG_YAML" "$SKILLS_ENTRY" <<'PYEOF'
import sys, re

config_path = sys.argv[1]
new_entry   = sys.argv[2]

with open(config_path, "r", encoding="utf-8") as f:
    content = f.read()

# Case A: inline empty list form   →  replace with multi-line
inline_re = re.compile(r'(  external_dirs:) \[\]')
if inline_re.search(content):
    content = inline_re.sub(r'\1\n  - ' + new_entry, content)
else:
    # Case B: multi-line form already; find the block and append after last entry
    # Insert after the "  external_dirs:" header line.
    content = re.sub(
        r'(  external_dirs:\n)',
        r'\1  - ' + new_entry + r'\n',
        content,
        count=1,
    )

with open(config_path, "w", encoding="utf-8") as f:
    f.write(content)
PYEOF
    ok "Added '$SKILLS_ENTRY' to external_dirs"
fi

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
    skip "Block '$BLOCK_MARKER' already present in SOUL.md"
else
    {
        printf '\n'
        printf '## %s\n' "$BLOCK_MARKER"
        printf '\n'
        # Skip the first-line "# Task Secretary Rules" heading to avoid duplication
        # (the block marker above already acts as section heading)
        tail -n +2 "$PROMPT_FILE"
    } >> "$SOUL_MD"
    ok "Appended '$BLOCK_MARKER' block to SOUL.md"
fi

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Bootstrap complete.                                  ║"
echo "║  Run scripts/verify_hermes_wiring.sh to confirm.     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
