# Put the LGMED-iMMS development server on a public HTTPS URL, so colleagues
# can click through a demo without being on this network.
#
#   .\run-cloudflare.ps1            tunnel to the server already running on :8000
#   .\run-cloudflare.ps1 -Serve     start runserver in its own window first
#   .\run-cloudflare.ps1 -Port 8080 a server on a different port
#
# A Cloudflare quick tunnel serves the site on the FIRST request. This is the
# reason the project uses it: a free tunnel from the obvious alternative answers
# every browser with a warning page that has to be clicked through before the
# site appears, which visitors read as a broken link - and a network that blocks
# that provider never shows even that much.
#
# THE TRADE-OFF. Without a Cloudflare account the hostname is random and NEW on
# every start, so the link has to be re-sent each time. Attaching a free
# Cloudflare account (a named tunnel) is what buys a hostname that stays put;
# until then, send the link this script prints, not one from a previous run.
#
# DEVELOPMENT ONLY. This exposes a DEBUG=True server holding demonstration
# accounts with a published password. Stop the tunnel (Ctrl+C) when the demo
# ends; do not leave it up unattended.
param(
    [switch]$Serve,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

# --- cloudflared -----------------------------------------------------------
# The installer edits PATH, but a shell opened before the install keeps the old
# copy - so the install directories are checked too rather than telling the user
# to reopen the terminal.
#
# Note the braces in ${env:ProgramFiles(x86)}. Without them PowerShell reads
# $env:ProgramFiles and then the literal text "(x86)", producing
# "C:\Program Files(x86)\..." - a path that does not exist, so the fallback
# silently finds nothing and the script claims cloudflared is not installed
# when it is.
$cloudflared = $null
$onPath = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($onPath) {
    $cloudflared = $onPath.Source
} else {
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe"
    )) {
        if ($candidate -and (Test-Path $candidate)) { $cloudflared = $candidate; break }
    }
}
if (-not $cloudflared) {
    Write-Error "cloudflared not found. Install it with:  winget install Cloudflare.cloudflared"
    exit 1
}

# --- the server ------------------------------------------------------------
$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if ($Serve) {
    if (-not (Test-Path $python)) {
        Write-Error "venv\Scripts\python.exe not found. See README.md - Running the system."
        exit 1
    }
    Write-Host "Starting runserver on port $Port in a new window..." -ForegroundColor Cyan
    Start-Process -FilePath $python `
                  -ArgumentList @("manage.py", "runserver", "$Port") `
                  -WorkingDirectory $PSScriptRoot
    Start-Sleep -Seconds 3
}

$listening = $null
try {
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
} catch {}
if (-not $listening) {
    Write-Host ""
    Write-Host "Nothing is listening on port $Port." -ForegroundColor Yellow
    Write-Host "The tunnel will open but every request will return a 502 until the"
    Write-Host "server is up. Start it with:"
    Write-Host "  venv\Scripts\python manage.py runserver $Port"
    Write-Host "or re-run this script with -Serve."
    Write-Host ""
}

# --- the tunnel ------------------------------------------------------------
# The Host header is deliberately NOT rewritten to localhost: Django checks the
# Origin of a form post against CSRF_TRUSTED_ORIGINS, and rewriting the host
# makes every sign-in fail the CSRF check for no visible reason. The hostname
# is covered by the .trycloudflare.com entries in venv\lgmed.env.
Write-Host "Opening a Cloudflare quick tunnel  ->  http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Watch for the https://<name>.trycloudflare.com line below - that is the link to send."
Write-Host "Visitors land on the public site; staff sign in at /staff."
Write-Host "Ctrl+C closes the tunnel."
Write-Host ""

& $cloudflared tunnel --url "http://127.0.0.1:$Port" --no-autoupdate
