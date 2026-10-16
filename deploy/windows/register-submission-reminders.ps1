# Register the Monthly Submissions reminder job with Windows Task Scheduler.
#
#   .\deploy\windows\register-submission-reminders.ps1            hourly, 07:00-19:00
#   .\deploy\windows\register-submission-reminders.ps1 -Remove    unregister it
#
# The task runs `manage.py send_submission_reminders` with this checkout's
# virtualenv, every hour, whether or not anyone is signed in to the machine
# (it asks for the account's Windows password once, to store the task). No
# browser has to stay open, and the Django server does not even have to be
# running: the command talks to the database and the mail server directly.
#
# Safe to run as often as it likes - each email has a unique key, so nothing
# is sent twice - and an email that failed is retried on the next run.
param(
    [switch]$Remove,
    [string]$TaskName = "LGMED-iMMS Monthly Submission Reminders"
)

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $root "venv\Scripts\python.exe"
$log = Join-Path $root "logs\submission-reminders.log"

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

# cmd /c so the output is appended to a log file an administrator can read.
$command = "`"$python`" manage.py send_submission_reminders >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command" -WorkingDirectory $root

# Every hour from 07:00 for 12 hours, every day.
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00am
$hourly = New-ScheduledTaskTrigger -Once -At 7:00am -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 12)
$trigger.Repetition = $hourly.Repetition

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

$credential = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
    -Message "Windows password for the account the reminder task runs as"

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -User $credential.UserName -Password $credential.GetNetworkCredential().Password `
    -RunLevel Limited -Force | Out-Null

Write-Host "Registered '$TaskName': hourly 07:00-19:00, log at $log"
Write-Host "Run it once now with:  Start-ScheduledTask -TaskName '$TaskName'"
