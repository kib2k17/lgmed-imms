# Put the LGMED-IMMS development server on this machine's office-network
# address, so colleagues on the same Wi-Fi can open it in their own browser.
#
#   .\run-lan.ps1              serve on this machine's address, port 8000
#   .\run-lan.ps1 -Port 8080   a different port
#   .\run-lan.ps1 -NoServe     only check the address, settings and firewall
#
# Nothing has to be edited when the address changes: DJANGO_LAN_ACCESS=1 in
# venv\lgmed.env tells settings.py to work it out at start-up. Unlike
# run-cloudflare.ps1 nothing leaves the building either - the server binds to
# 0.0.0.0 and only this network can reach it.
#
# It is still a DEBUG=True server holding demonstration accounts whose password
# is printed in the README, so the cautions in *Before opening a tunnel* apply
# here too: demonstration data, not live LGU records, and stop it when the demo
# ends.
param(
    [int]$Port = 8000,
    [switch]$NoServe
)

$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "venv\Scripts\python.exe not found. See README.md - Running the system."
    exit 1
}

# CSRF compares scheme + host + port, so the port the server is about to use has
# to be the port the origin is trusted on. Passed down rather than written into
# lgmed.env, so -Port needs no second edit anywhere.
$env:DJANGO_LAN_PORTS = "$Port"

# --- what Django will actually accept --------------------------------------
# Asked of Django rather than read out of lgmed.env: the addresses are worked
# out at start-up, so the settings module is the only thing that knows the
# answer, and parsing the file here would be a second guess at it.
$probe = @"
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings
print('LAN_ACCESS=' + ('1' if settings.LAN_ACCESS else '0'))
print('DEBUG=' + ('1' if settings.DEBUG else '0'))
print('ADDRESSES=' + ','.join(settings.LAN_ADDRESSES))
"@
$reported = & $python -c $probe
if ($LASTEXITCODE -ne 0) {
    Write-Host ($reported | Out-String)
    Write-Error "Django could not load its settings - the error above is the real one."
    exit 1
}

$state = @{}
foreach ($line in $reported) {
    if ($line -match '^(\w+)=(.*)$') { $state[$matches[1]] = $matches[2] }
}
$addresses = @($state['ADDRESSES'] -split ',' | Where-Object { $_ })

if ($state['LAN_ACCESS'] -ne '1') {
    Write-Host ""
    Write-Host "DJANGO_LAN_ACCESS is not set, so Django will refuse every request that" -ForegroundColor Yellow
    Write-Host "does not arrive on localhost. Add this line to venv\lgmed.env:"
    Write-Host ""
    Write-Host "    DJANGO_LAN_ACCESS=1"
    Write-Host ""
    exit 1
}
if ($state['DEBUG'] -ne '1') {
    Write-Host ""
    Write-Host "DEBUG is off, and DJANGO_LAN_ACCESS is ignored on a deployed server." -ForegroundColor Yellow
    Write-Host "A real deployment names its hostnames in DJANGO_ALLOWED_HOSTS instead."
    Write-Host ""
    exit 1
}
if ($addresses.Count -eq 0) {
    Write-Host ""
    Write-Host "This machine has no network address - only loopback." -ForegroundColor Yellow
    Write-Host "Is the Wi-Fi connected?"
    Write-Host ""
    exit 1
}

# The address carrying the default route is the one to hand out; the others are
# accepted too, but they are things like a Wi-Fi Direct adapter that no
# colleague can reach.
$primary = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
    Select-Object -First 1 -ExpandProperty IPv4Address |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $primary -or $addresses -notcontains $primary) { $primary = $addresses[0] }

# --- the firewall ----------------------------------------------------------
# Windows blocks inbound connections to python.exe by default, so without this
# the server looks fine here and times out on every other machine - the most
# common reason "it works on localhost but nobody else can reach it".
#
# The rule is scoped to LocalSubnet on every profile rather than to the private
# profile. Windows decides on its own whether a network is private or public -
# DILG-CARAGA-RO comes up public - and a private-only rule silently does not
# apply there, which looks exactly like no rule at all. LocalSubnet keeps the
# port shut to everything beyond this network either way, which is the part
# that actually matters.
$ruleName = "LGMED-IMMS dev server (TCP $Port)"
$rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue

# An existing rule from an earlier run may be scoped to the private profile and
# so be doing nothing on this network. Checked rather than trusted, because the
# symptom - the rule is listed, the site is unreachable - sends you looking
# everywhere else first.
$needsFix = $false
if ($rule) {
    $scope = ($rule | Get-NetFirewallAddressFilter).RemoteAddress
    if ($rule.Profile -ne "Any" -or $scope -ne "LocalSubnet") { $needsFix = $true }
}

if (-not $rule -or $needsFix) {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $elevated  = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    $verb = if ($needsFix) { "Rescoping" } else { "Adding" }
    $command = if ($needsFix) {
        "Set-NetFirewallRule -DisplayName '$ruleName' -Profile Any -RemoteAddress LocalSubnet"
    } else {
        "New-NetFirewallRule -DisplayName '$ruleName' -Direction Inbound -Action Allow " +
        "-Protocol TCP -LocalPort $Port -Profile Any -RemoteAddress LocalSubnet"
    }

    if ($elevated) {
        Invoke-Expression $command | Out-Null
    } else {
        Write-Host ""
        Write-Host "$verb the firewall rule for port $Port needs Administrator." -ForegroundColor Yellow
        Write-Host "Opening an elevated window..."
        $elevatedArgs = @("-NoProfile", "-Command", $command)
        Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -ArgumentList $elevatedArgs
    }

    $rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($rule -and ($rule | Get-NetFirewallAddressFilter).RemoteAddress -eq "LocalSubnet") {
        Write-Host "Firewall: $ruleName - this subnet only." -ForegroundColor Green
    } else {
        Write-Host "The rule is not in place - the server will only answer on this machine." -ForegroundColor Yellow
    }
}

# --- the server ------------------------------------------------------------
Write-Host ""
Write-Host "Colleagues on this network open:  http://${primary}:${Port}/" -ForegroundColor Green
Write-Host "Staff sign in at                  http://${primary}:${Port}/staff"
Write-Host "On this machine                   http://127.0.0.1:${Port}/"
if ($addresses.Count -gt 1) {
    $others = $addresses -join ", "
    Write-Host "Also accepted: $others" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "The sign-in reCAPTCHA is registered per domain and a bare IP cannot be"
Write-Host "registered, so the check will not pass over this address. RECAPTCHA_ENFORCE=0"
Write-Host "lets sign-in through anyway and records the miss in the audit log."
Write-Host ""

if ($NoServe) { exit 0 }

# 0.0.0.0 is what makes the difference: runserver's default 127.0.0.1 answers
# only this machine, whatever the firewall says.
Write-Host "Ctrl+C stops the server." -ForegroundColor Cyan
& $python (Join-Path $PSScriptRoot "manage.py") runserver "0.0.0.0:$Port"
