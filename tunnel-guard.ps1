# Safety checks shared by run-cloudflare.ps1 and run-ngrok.ps1. Dot-sourced,
# not run on its own.
#
# A tunnel puts the development server on the public internet. What must never
# go out that way is the real database, or a server that skips two-step
# verification (LGMED_MFA_OFF) - together they hand an administrator sign-in
# with no second step to anyone holding the link. Both were possible before
# this file existed, because the scripts only *said* "development only".
#
# Two cases:
#
#   -Serve   the script starts the server itself, so it decides what that
#            server sees: the demo database, and two-step verification on.
#            Real environment variables win over venv\lgmed.env (config/env.py),
#            so setting them for the child process is enough.
#
#   no -Serve  a server is already running and the script cannot ask it which
#            database it opened. It judges by what a server started normally
#            would use - this window's environment, then venv\lgmed.env - and
#            refuses unless that is already a demo database with two-step
#            verification on.

$script:DemoSuffix = "_demo"

function Get-LgmedEnvValue {
    param([string]$Name, [string]$Default = "")
    # The real environment wins, exactly as in config/env.py.
    $real = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($null -ne $real) { return $real.Trim() }

    $file = Join-Path $PSScriptRoot "venv\lgmed.env"
    if (Test-Path $file) {
        foreach ($raw in Get-Content -LiteralPath $file -Encoding UTF8) {
            $line = $raw.Trim()
            if (-not $line -or $line.StartsWith("#")) { continue }
            if ($line.StartsWith("export ")) { $line = $line.Substring(7).TrimStart() }
            $at = $line.IndexOf("=")
            if ($at -lt 1) { continue }
            if ($line.Substring(0, $at).Trim() -ne $Name) { continue }
            $value = $line.Substring($at + 1).Trim()
            if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and @('"', "'") -contains [string]$value[0]) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return $Default
}

function Test-LgmedTruthy([string]$Value) {
    return @("1", "true", "yes", "on") -contains $Value.Trim().ToLower()
}

function Stop-UnsafeTunnel([string[]]$Reasons) {
    Write-Host ""
    Write-Host "The tunnel was NOT opened." -ForegroundColor Red
    foreach ($reason in $Reasons) { Write-Host "  - $reason" -ForegroundColor Red }
    Write-Host ""
    Write-Host "A demo goes out on its own database, never the real one. Once only:"
    Write-Host "  1. In MySQL:  CREATE DATABASE lgmedimms$script:DemoSuffix CHARACTER SET utf8mb4;"
    Write-Host "  2. In PowerShell, in this folder:"
    Write-Host "       `$env:MYSQL_DATABASE = 'lgmedimms$script:DemoSuffix'"
    Write-Host "       venv\Scripts\python manage.py migrate"
    Write-Host "       venv\Scripts\python manage.py bootstrap_demo"
    Write-Host "Then start the demo with -Serve, which points the server at that database."
    Write-Host ""
    exit 1
}

function Assert-DemoTunnelSafe {
    param([switch]$Serve, [string]$Database, [int]$Port)

    $reasons = @()
    if ($Serve) {
        if (-not $Database.EndsWith($script:DemoSuffix)) {
            $reasons += "-Database '$Database' is not a demo database (the name must end in '$script:DemoSuffix')."
        }
        # A second runserver cannot take a port that is in use, and the tunnel
        # would then reach whichever server already holds it - perhaps one on
        # the real database.
        $busy = $null
        try { $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop } catch {}
        if ($busy) {
            $reasons += "A server is already running on port $Port. Stop it first, so the tunnel " +
                        "reaches the demo server this script starts and not that one."
        }
    } else {
        $effective = Get-LgmedEnvValue "MYSQL_DATABASE" "lgmedimms"
        if (-not $effective.EndsWith($script:DemoSuffix)) {
            $reasons += "A server started from this folder would open the '$effective' database, not a demo one. " +
                        "Stop that server and re-run this script with -Serve."
        }
        if (Test-LgmedTruthy (Get-LgmedEnvValue "LGMED_MFA_OFF" "0")) {
            $reasons += "LGMED_MFA_OFF is set, so administrators would sign in without two-step verification. " +
                        "Remove it from venv\lgmed.env, or use -Serve."
        }
    }
    if ($reasons.Count) { Stop-UnsafeTunnel $reasons }
}

function Start-DemoServer {
    # runserver in its own window, on the demo database with two-step
    # verification on. The variables are set only for the child: this window's
    # own environment is put back as it was.
    param([string]$Python, [int]$Port, [string]$Database)

    $saved = @{
        MYSQL_DATABASE = [Environment]::GetEnvironmentVariable("MYSQL_DATABASE", "Process")
        LGMED_MFA_OFF  = [Environment]::GetEnvironmentVariable("LGMED_MFA_OFF", "Process")
    }
    try {
        $env:MYSQL_DATABASE = $Database
        $env:LGMED_MFA_OFF = "0"
        Write-Host "Starting runserver on port $Port (database '$Database', two-step verification on) in a new window..." -ForegroundColor Cyan
        Start-Process -FilePath $Python `
                      -ArgumentList @("manage.py", "runserver", "$Port") `
                      -WorkingDirectory $PSScriptRoot
    } finally {
        foreach ($name in $saved.Keys) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
        }
    }
}
