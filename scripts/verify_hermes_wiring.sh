#!/usr/bin/env bash
set -uo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CONFIG_YAML="$HERMES_HOME/config.yaml"
SOUL_MD="$HERMES_HOME/SOUL.md"
HERMES_AGENT="$HERMES_HOME/hermes-agent"
SKILLS_ENTRY="~/code/aisecretary/skills"
BLOCK_MARKER="Transaction Secretary Rules (aisecretary)"
API_URL="http://127.0.0.1:8000"

PASS=0
FAIL=0

pass() { echo "  ✅  $*"; PASS=$((PASS + 1)); }
fail() { echo "  ❌  $*"; FAIL=$((FAIL + 1)); }
info() { echo "  ℹ️   $*"; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         aisecretary → Hermes wiring check            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

echo "── Check 1: skills.external_dirs ──────────────────────"
if grep -qF "$SKILLS_ENTRY" "$CONFIG_YAML" 2>/dev/null; then
    pass "external_dirs contains '$SKILLS_ENTRY'"
else
    fail "external_dirs missing '$SKILLS_ENTRY' in $CONFIG_YAML"
    info "Fix: run scripts/bootstrap_hermes.sh"
fi

echo ""
echo "── Check 2: SOUL.md injection ─────────────────────────"
if grep -qF "$BLOCK_MARKER" "$SOUL_MD" 2>/dev/null; then
    pass "SOUL.md contains '$BLOCK_MARKER' block"
else
    fail "SOUL.md missing '$BLOCK_MARKER' block"
    info "Fix: run scripts/bootstrap_hermes.sh"
fi

echo ""
echo "── Check 3: local API health ──────────────────────────"
if curl -sf "$API_URL/health" -o /dev/null 2>/dev/null; then
    STATUS=$(curl -sf "$API_URL/health" 2>/dev/null)
    pass "API is up: $STATUS"
else
    fail "API not reachable at $API_URL/health"
    info "Fix: run scripts/start_local_api.sh"
fi

echo ""
echo "── Check 4: transaction_manager skill recognised ──────"
if [ -d "$HERMES_AGENT" ] && [ -f "$HERMES_AGENT/tools/skills_tool.py" ]; then
    RESULT=$(cd "$HERMES_AGENT" && PYTHONPATH=. venv/bin/python3 - 2>/dev/null <<'PYEOF'
from tools.skills_tool import _find_all_skills
skills = _find_all_skills()
found = [s for s in skills if s.get("name") == "transaction_manager"]
if found:
    s = found[0]
    print(f"name={s['name']} | description={s['description'][:60]}")
else:
    print("NOT_FOUND")
PYEOF
    )
    if echo "$RESULT" | grep -q "NOT_FOUND"; then
        fail "transaction_manager skill not found by Hermes runtime"
        info "Check that the SKILL.md exists at ~/code/aisecretary/skills/transaction_manager/SKILL.md"
    else
        pass "Skill recognised: $RESULT"
    fi
else
    info "hermes-agent not found at $HERMES_AGENT — skipping runtime skill check"
    info "Manually verify with: hermes skills list"
fi

echo ""
echo "══════════════════════════════════════════════════════"
echo "  Results: ${PASS} passed, ${FAIL} failed"
echo "══════════════════════════════════════════════════════"
echo ""

[ "$FAIL" -eq 0 ]
