#!/usr/bin/env bash
# setup_ssh_access.sh
#
# One-time setup: enable Hermes (Docker container) to SSH into the host
# and call aisecretary CLI without a password.
#
# Mac/Linux only. Windows users: run setup_ssh_access.ps1 instead.
# Run on the HOST machine: bash scripts/setup_ssh_access.sh

set -euo pipefail

CONTAINER="${CONTAINER:-hermes}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOST_USER="$(whoami)"
AUTHORIZED_KEYS="$HOME/.ssh/authorized_keys"

ok()   { echo "  ✅  $*"; }
info() { echo "  ℹ️   $*"; }
fail() { echo "  ❌  $*" >&2; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     aisecretary SSH access setup (Mac/Linux)         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Ensure sshd is running ───────────────────────────────────────────

echo "Step 1: SSH server"
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! sudo launchctl list 2>/dev/null | grep -q "com.openssh.sshd"; then
        info "Enabling Remote Login (may prompt for sudo password)..."
        sudo systemsetup -setremotelogin on
    fi
else
    if command -v systemctl &>/dev/null; then
        sudo systemctl enable --now ssh 2>/dev/null || sudo systemctl enable --now sshd 2>/dev/null || true
    fi
fi
ok "sshd ready"

# ── Step 2: Generate SSH key in container ─────────────────────────────────────

echo ""
echo "Step 2: Generate SSH key in Hermes container"

CONTAINER_HOME="$(docker exec "$CONTAINER" bash -c 'echo $HOME' 2>/dev/null)" \
    || fail "Cannot reach container '$CONTAINER'. Is it running?"
CONTAINER_SSH="$CONTAINER_HOME/.ssh"
info "Container HOME: $CONTAINER_HOME"

docker exec "$CONTAINER" bash -c "mkdir -p $CONTAINER_SSH && chmod 700 $CONTAINER_SSH"

if docker exec "$CONTAINER" bash -c "test -f $CONTAINER_SSH/aisecretary_rsa.pub" 2>/dev/null; then
    info "SSH key already exists, reusing"
    PUBKEY="$(docker exec "$CONTAINER" bash -c "cat $CONTAINER_SSH/aisecretary_rsa.pub")"
else
    docker exec "$CONTAINER" bash -c \
        "ssh-keygen -t ed25519 -f $CONTAINER_SSH/aisecretary_rsa -N '' -C hermes-aisecretary -q"
    PUBKEY="$(docker exec "$CONTAINER" bash -c "cat $CONTAINER_SSH/aisecretary_rsa.pub")"
    ok "Key generated"
fi

# ── Step 3: Authorize key on host ─────────────────────────────────────────────

echo ""
echo "Step 3: Authorize key on host"
mkdir -p "$HOME/.ssh"
touch "$AUTHORIZED_KEYS"
chmod 600 "$AUTHORIZED_KEYS"

if grep -qF "$PUBKEY" "$AUTHORIZED_KEYS" 2>/dev/null; then
    ok "Key already authorized"
else
    echo "$PUBKEY" >> "$AUTHORIZED_KEYS"
    ok "Key added to $AUTHORIZED_KEYS"
fi

# ── Step 4: Configure SSH client in container ─────────────────────────────────

echo ""
echo "Step 4: Configure SSH alias in container"

docker exec "$CONTAINER" bash -c \
    "printf 'Host aisecretary-host\n    HostName host.docker.internal\n    User $HOST_USER\n    IdentityFile $CONTAINER_SSH/aisecretary_rsa\n    StrictHostKeyChecking no\n' > $CONTAINER_SSH/config && chmod 600 $CONTAINER_SSH/config"
ok "SSH config written (User=$HOST_USER)"

# ── Step 5: Install aisecretary command ───────────────────────────────────────

echo ""
echo "Step 5: Install aisecretary command"
WRAPPER="/usr/local/bin/aisecretary"
if [ -f "$WRAPPER" ]; then
    ok "aisecretary already installed at $WRAPPER"
else
    printf '#!/bin/bash\npython3 "%s/scripts/aisecretary_cli.py" "$@"\n' "$REPO_DIR" \
        | sudo tee "$WRAPPER" > /dev/null
    sudo chmod +x "$WRAPPER"
    ok "Installed to $WRAPPER"
fi

# ── Step 6: Verify ────────────────────────────────────────────────────────────

echo ""
echo "Step 6: Verify connection"
sleep 1
if RESULT="$(docker exec "$CONTAINER" bash -c "ssh aisecretary-host 'aisecretary summary'" 2>&1)"; then
    ok "Connection verified: $RESULT"
else
    echo "  ⚠️   Verification failed: $RESULT"
    echo "  ℹ️   Try re-running this script, or check sshd and authorized_keys."
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Setup complete.                                      ║"
echo "║  Hermes can now call aisecretary via SSH.             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
