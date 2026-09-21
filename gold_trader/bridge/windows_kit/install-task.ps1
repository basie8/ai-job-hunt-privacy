# Registers the AURUM bridge as a scheduled task, every 15 minutes.
#
# Written in PowerShell rather than schtasks because the two settings that
# matter cannot be set from the schtasks command line at all:
#
#   MultipleInstances    schtasks leaves this at IgnoreNew, so ONE run that
#                        never registers as finished blocks every run behind
#                        it, permanently and silently. That is what stopped
#                        the bridge at 07:24 on 2026-09-21: it ran on a
#                        perfect 15-minute cadence until a run wedged, and
#                        then nothing, with the machine, MT5, git and the
#                        network all perfectly healthy.
#
#   ExecutionTimeLimit   without it a hung run hangs forever, which is how an
#                        instance wedges in the first place.
#
# The earlier installer's comments claimed both protections. The command it
# actually ran set neither.

param(
    [string]$TaskName = 'AURUM bridge',
    [Parameter(Mandatory = $true)][string]$Folder
)

$ErrorActionPreference = 'Stop'
$launcher = Join-Path $Folder 'RUN-BRIDGE.bat'

if (-not (Test-Path $launcher)) {
    Write-Output "RUN-BRIDGE.bat not found in $Folder"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $Folder

# Repeat forever from now. -RepetitionDuration is omitted deliberately: on
# current Windows that means indefinitely, whereas the GUI's duration box
# defaults to something short and quietly stops repeating.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances StopExisting `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# Interactive, as the logged-on user: the task then sees the same git
# credentials your own shell does. The cost is that it does not run while
# nobody is logged in, which INSTALL.md states plainly.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

# Verify rather than assume. Register-ScheduledTask can succeed and still
# leave a task that never fires, and assuming a schedule took is the mistake
# that started all of this.
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Output 'The task was not registered.'
    exit 1
}

$info = Get-ScheduledTaskInfo -TaskName $TaskName
$repeat = $task.Triggers[0].Repetition.Interval

Write-Output ''
Write-Output "  Task           $TaskName"
Write-Output "  Runs           $launcher"
Write-Output "  State          $($task.State)"
Write-Output "  Repeats every  $repeat"
Write-Output "  Next run       $($info.NextRunTime)"
Write-Output "  If wedged      $($task.Settings.MultipleInstances) (a stuck run is replaced, not skipped)"
Write-Output "  Time limit     $($task.Settings.ExecutionTimeLimit)"
Write-Output ''

if ($repeat -ne 'PT15M') {
    Write-Output '  WARNING: the repetition interval is not 15 minutes.'
    exit 1
}
if (-not $info.NextRunTime) {
    Write-Output '  WARNING: no next run time, so the schedule did not take.'
    exit 1
}
exit 0
