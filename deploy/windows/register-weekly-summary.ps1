# Register the Division Chief's weekly summary email as a Windows scheduled
# task, for running the system on a Windows machine. (On a Linux server use
# deploy/systemd/lgmed-weekly-summary.timer instead.)
#
#   .\deploy\windows\register-weekly-summary.ps1           register it
#   .\deploy\windows\register-weekly-summary.ps1 -Remove   remove it
#
# It runs every morning at 07:00; the command sends each recipient one summary
# per week, so the first run of the week sends it and a failed send is retried
# the next morning.
param(
    [switch]$Remove,
    [string]$TaskName = "LGMED-iMMS Weekly Summary"
)

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $root "venv\Scripts\python.exe"
$log = Join-Path $root "logs\weekly-summary.log"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'."
    exit 0
}

if (-not (Test-Path $python)) {
    Write-Error "venv\Scripts\python.exe not found under $root. Create the virtualenv first."
    exit 1
}
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

$command = "`"$python`" manage.py send_weekly_summary >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew

$credential = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
    -Message "Windows password for the account the summary task runs as"

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -User $credential.UserName -Password $credential.GetNetworkCredential().Password `
    -RunLevel Limited -Force | Out-Null

Write-Host "Registered '$TaskName': daily 07:00 (sends once a week), log at $log"
Write-Host "Send one now with:  venv\Scripts\python manage.py send_weekly_summary --force"
