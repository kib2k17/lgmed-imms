# Put the LGMED-iMMS development server on a public HTTPS URL, so colleagues
# can click through a demo without being on this network.
#
#   .\run-ngrok.ps1            tunnel to the server already running on :8000
#   .\run-ngrok.ps1 -Serve     start runserver in its own window first
#   .\run-ngrok.ps1 -Port 8080 a server on a different port
#   .\run-ngrok.ps1 -Domain x.ngrok-free.app   override NGROK_DOMAIN for one run
#
# DEVELOPMENT ONLY. This exposes a DEBUG=True server holding demonstration
# accounts with a published password. Stop the tunnel (Ctrl+C) when the demo
# ends; do not leave it up unattended. See README.md - "Sharing a demo over
# ngrok" - for what a visitor can and cannot reach.
param(
    [switch]$Serve,
    [int]$Port = 8000,
    [string]$Domain
)

$ErrorActionPreference = "Stop"

# --- ngrok itself ----------------------------------------------------------
# winget edits PATH but the running shell keeps the old copy, so the package
# directory is checked too rather than telling the user to reopen the terminal.
$ngrok = $null
$onPath = Get-Command ngrok -ErrorAction SilentlyContinue
if ($onPath) {
    $ngrok = $onPath.Source
} else {
    $candidate = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
    if (Test-Path $candidate) { $ngrok = $candidate }
}
if (-not $ngrok) {
    Write-Error "ngrok not found. Install it with:  winget install ngrok.ngrok"
    exit 1
}

# --- the agent version ----------------------------------------------------
# winget ships ngrok 3.3.1, and ngrok refuses any agent below the minimum its
# service currently enforces (3.20.0 when this was written) with ERR_NGROK_121.
# The failure arrives as an "authentication failed" message, which reads like a
# bad token and sends you looking in the wrong place - so it is checked here.
$MINIMUM = [version]"3.20.0"
$versionText = (& $ngrok version 2>&1 | Out-String)
if ($versionText -match '(\d+\.\d+\.\d+)') {
    $installed = [version]$matches[1]
    if ($installed -lt $MINIMUM) {
        Write-Host ""
        Write-Host "ngrok $installed is below the minimum $MINIMUM that ngrok now requires." -ForegroundColor Yellow
        Write-Host "Update the agent in place (winget's package is older than this):"
        Write-Host "  ngrok update"
        Write-Host ""
        exit 1
    }
}

# --- the account token -----------------------------------------------------
# A tunnel without it fails with an authentication error from the ngrok service
# rather than anything to do with this project, which is worth saying plainly.
$config = Join-Path $env:LOCALAPPDATA "ngrok\ngrok.yml"
$hasToken = $false
if (Test-Path $config) {
    $hasToken = (Select-String -Path $config -Pattern "authtoken" -Quiet)
}
if (-not $hasToken) {
    Write-Host ""
    Write-Host "ngrok has no authtoken yet." -ForegroundColor Yellow
    Write-Host "Copy yours from https://dashboard.ngrok.com/get-started/your-authtoken then run:"
    Write-Host "  ngrok config add-authtoken <token>"
    Write-Host ""
    exit 1
}

# --- the reserved domain ---------------------------------------------------
# Read from venv\lgmed.env, the same file settings.py reads, so the hostname is
# stated once. config/env.py loads it for Django; PowerShell cannot, so it is
# parsed again here - the one duplication, and it is a read, not a second copy.
if (-not $Domain) {
    $envFile = Join-Path $PSScriptRoot "venv\lgmed.env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*NGROK_DOMAIN\s*=\s*(.*)$') {
                $Domain = $matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
}
# A scheme here is the easy mistake: ngrok wants a bare hostname and rejects
# the URL form with a confusing message.
if ($Domain) { $Domain = $Domain -replace '^https?://', '' -replace '/+$', '' }

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
# makes every sign-in fail the CSRF check for no visible reason.
$argsList = @("http", "$Port")
if ($Domain) {
    $argsList += @("--domain", $Domain)
    Write-Host "Tunnelling https://$Domain  ->  http://127.0.0.1:$Port" -ForegroundColor Green
} else {
    Write-Host "No NGROK_DOMAIN set - using a random hostname for this run." -ForegroundColor Yellow
    Write-Host "Tunnelling a random *.ngrok-free.app  ->  http://127.0.0.1:$Port" -ForegroundColor Green
}
Write-Host "Visitors land on the public site; staff sign in at /accounts/login/."
Write-Host "Ctrl+C closes the tunnel. The inspector is at http://127.0.0.1:4040"
Write-Host ""

& $ngrok @argsList
