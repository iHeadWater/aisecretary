# setup_ssh_access.ps1
#
# One-time setup: enable Hermes (Docker container) to SSH into the host
# and call aisecretary CLI without a password.
#
# Run as Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_ssh_access.ps1

param(
    [string]$ContainerName = "hermes"
)

function Ok($msg)   { Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "  [i]   $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  [!]   $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [X]   $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== aisecretary SSH access setup (Windows) ==="
Write-Host ""

# --- Require admin ---

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "Re-run as Administrator: right-click PowerShell > Run as Administrator"
}

# --- Step 1: Install and start OpenSSH Server ---

Write-Host "Step 1: OpenSSH Server"
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*" | Select-Object -First 1
if ($null -eq $cap -or $cap.State -ne "Installed") {
    Info "Installing OpenSSH Server..."
    Add-WindowsCapability -Online -Name "OpenSSH.Server~~~~0.0.1.0" | Out-Null
    Ok "Installed"
} else {
    Ok "Already installed"
}
Start-Service sshd -ErrorAction SilentlyContinue
Set-Service sshd -StartupType Automatic
Ok "sshd running"

# --- Step 2: Generate SSH key in container ---

Write-Host ""
Write-Host "Step 2: Generate SSH key in Hermes container"

$containerHome = docker exec $ContainerName bash -c 'echo $HOME' 2>$null
if (-not $containerHome) { Fail "Cannot reach container '$ContainerName'. Is it running?" }
$containerSsh = "$containerHome/.ssh"
Info "Container HOME: $containerHome"

docker exec $ContainerName bash -c "mkdir -p $containerSsh" | Out-Null
docker exec $ContainerName bash -c "chmod 700 $containerSsh" | Out-Null

$existingPub = docker exec $ContainerName bash -c "cat $containerSsh/aisecretary_rsa.pub 2>/dev/null"
if ($existingPub) {
    Info "SSH key already exists, reusing"
    $pubKey = $existingPub.Trim()
} else {
    docker exec $ContainerName bash -c "ssh-keygen -t ed25519 -f $containerSsh/aisecretary_rsa -N '' -C hermes-aisecretary -q" | Out-Null
    $pubKey = (docker exec $ContainerName bash -c "cat $containerSsh/aisecretary_rsa.pub").Trim()
    Ok "Key generated"
}

# --- Step 3: Authorize key on host ---

Write-Host ""
Write-Host "Step 3: Authorize key on host"

$authKeys = "C:\ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $authKeys)) {
    New-Item -ItemType File -Path $authKeys -Force | Out-Null
}
$existing = Get-Content $authKeys -ErrorAction SilentlyContinue
if ($existing -and ($existing | Where-Object { $_.Trim() -eq $pubKey })) {
    Ok "Key already authorized"
} else {
    Add-Content $authKeys $pubKey
    Ok "Key added to $authKeys"
}
icacls $authKeys /inheritance:r /grant "SYSTEM:(F)" /grant "Administrators:(F)" | Out-Null
Ok "Permissions set"

# --- Step 4: Configure SSH client in container ---

Write-Host ""
Write-Host "Step 4: Configure SSH alias in container"

$hostUser = $env:USERNAME
$configContent = "Host aisecretary-host\n    HostName host.docker.internal\n    User $hostUser\n    IdentityFile $containerSsh/aisecretary_rsa\n    StrictHostKeyChecking no\n"
docker exec $ContainerName bash -c "printf '$configContent' > $containerSsh/config" | Out-Null
docker exec $ContainerName bash -c "chmod 600 $containerSsh/config" | Out-Null
Ok "SSH config written (User=$hostUser)"

# --- Step 5: Add scripts dir to system PATH ---

Write-Host ""
Write-Host "Step 5: Add scripts directory to PATH"

$scriptsDir = $PSScriptRoot
$machinePath = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::Machine)
if ($machinePath -like "*$scriptsDir*") {
    Ok "Already in PATH"
} else {
    $newPath = $machinePath + ";" + $scriptsDir
    [Environment]::SetEnvironmentVariable("Path", $newPath, [EnvironmentVariableTarget]::Machine)
    Ok "Added $scriptsDir to PATH"
}

# --- Step 6: Restart sshd ---

Write-Host ""
Write-Host "Step 6: Restart sshd"
Restart-Service sshd
Start-Sleep -Seconds 2
Ok "sshd restarted"

# --- Step 7: Verify ---

Write-Host ""
Write-Host "Step 7: Verify connection"

$result = docker exec $ContainerName bash -c "ssh aisecretary-host 'aisecretary summary'" 2>&1
if ($LASTEXITCODE -eq 0) {
    Ok "Connection verified: $result"
} else {
    Warn "Verification failed: $result"
    Warn "Try re-running this script, or check that Docker is running."
}

Write-Host ""
Write-Host "=== Setup complete. Hermes can now call aisecretary via SSH. ==="
Write-Host ""
