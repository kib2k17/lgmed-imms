# Put the LGMED-IMMS development server on its fixed public ngrok URL:
#
#   https://engaging-elephant-curiously.ngrok-free.app/
#
#   .\run-ngrok.ps1            tunnel to the server already running on :8000
#   .\run-ngrok.ps1 -Serve     start runserver in its own window first
#   .\run-ngrok.ps1 -Port 8080 a server on a different port
#
# Unlike run-cloudflare.ps1, the address does NOT change between runs: it is
# the free static domain reserved on the ngrok account, so the same link can be
# sent once and reused. The trade-off is ngrok's interstitial warning page,
# which a first-time visitor has to click through before the site appears.
#
# The domain belongs to the ngrok account whose authtoken is saved on this
# machine (ngrok config add-authtoken <token>). On another machine or account
# ngrok refuses to start with this domain.
#
# DEVELOPMENT ONLY. This exposes a DEBUG=True server holding demonstration
# accounts with a published password. Stop the tunnel (Ctrl+C) when the demo
# ends; do not leave it up unattended.
#
# It refuses to open the tunnel onto the real database or onto a server that
# skips two-step verification - see tunnel-guard.ps1. With -Serve the server it
# starts uses the demo database (-Database, default lgmedimms_demo).
param(
    [switch]$Serve,
    [int]$Port = 8000,
    [string]$Domain = "engaging-elephant-curiously.ngrok-free.app",
    [string]$Database = "lgmedimms_demo"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "tunnel-guard.ps1")
Assert-DemoTunnelSafe -Serve:$Serve -Database $Database -Port $Port

# --- ngrok -----------------------------------------------------------------
# The winget install edits PATH, but a shell opened before the install keeps
# the old copy - so the winget directories are checked too.
$ngrok = $null
$onPath = Get-Command ngrok -ErrorAction SilentlyContinue
if ($onPath) {
    $ngrok = $onPath.Source
} else {
    $candidates = @("$env:LOCALAPPDATA\Microsoft\WinGet\Links\ngrok.exe")
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Ngrok.Ngrok_*\ngrok.exe" `
                       -ErrorAction SilentlyContinue | ForEach-Object FullName
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { $ngrok = $candidate; break }
    }
}
if (-not $ngrok) {
    Write-Error "ngrok not found. Install it with:  winget install Ngrok.Ngrok"
    exit 1
}

# --- the server ------------------------------------------------------------
$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if ($Serve) {
    if (-not (Test-Path $python)) {
        Write-Error "venv\Scripts\python.exe not found. See README.md - Running the system."
        exit 1
    }
    Start-DemoServer -Python $python -Port $Port -Database $Database
    Start-Sleep -Seconds 3
}

$listening = $null
try {
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
} catch {}
if (-not $listening) {
    Write-Host ""
    Write-Host "Nothing is listening on port $Port." -ForegroundColor Yellow
    Write-Host "The tunnel will open but every request will fail until the"
    Write-Host "server is up. Start it with:"
    Write-Host "  venv\Scripts\python manage.py runserver $Port"
    Write-Host "or re-run this script with -Serve."
    Write-Host ""
}

# --- the tunnel ------------------------------------------------------------
# The Host header is deliberately NOT rewritten to localhost: Django checks the
# Origin of a form post against CSRF_TRUSTED_ORIGINS, and rewriting the host
# makes every sign-in fail the CSRF check. The hostname is covered by the
# .ngrok-free.app entries in venv\lgmed.env.
Write-Host "Opening ngrok  https://$Domain  ->  http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Visitors land on the public site; staff sign in at /staff."
Write-Host "Ctrl+C closes the tunnel."
Write-Host ""

# 127.0.0.1, not a bare port: ngrok would forward to "localhost", which on
# Windows resolves to ::1 first, while runserver listens on IPv4 only.
& $ngrok http "--url=$Domain" "127.0.0.1:$Port"
