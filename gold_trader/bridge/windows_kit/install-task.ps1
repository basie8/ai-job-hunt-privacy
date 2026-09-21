# Registers the AURUM bridge as a scheduled task, every 15 minutes.
#
# Written in PowerShell rather than schtasks because the two settings that
# matter cannot be set from the schtasks command line at all:
#
#   MultipleInstances    Windows defaults to IgnoreNew, so ONE run that never
#                        registers as finished blocks every run behind it,
#                        permanently and silently. That is what stopped the
#                        bridge at 07:24 on 2026-09-21: a perfect 15-minute
#                        cadence, then nothing, with the machine, MT5, git and
#                        the network all healthy.
#
#   ExecutionTimeLimit   without it a hung run hangs forever, which is how an
#                        instance wedges in the first place.
#
# On the policy: StopExisting is the ideal -- kill the stuck run, start the
# new one -- but New-ScheduledTaskSettingsSet's enum only accepts Parallel,
# Queue and IgnoreNew. So the task is created with Parallel and then upgraded
# to StopExisting through the task XML, which does support it. If that upgrade
# fails, Parallel stands, and Parallel never wedges either: a new run starts
# regardless of what the last one is doing. Queue was rejected precisely
# because a stuck run stalls the queue, which is the failure being fixed.
#
# Whatever ends up in force is READ BACK FROM WINDOWS and printed. An earlier
# version of the installer described protections in its comments and set none
# of them, so nothing here is reported unless Windows confirms it.

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
    -MultipleInstances Parallel `
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

# Best-effort upgrade to StopExisting. The task above already works and
# already cannot wedge, so a failure here is not fatal and must not be
# treated as one.
try {
    $xml = Export-ScheduledTask -TaskName $TaskName
    if ($xml -match '<MultipleInstancesPolicy>') {
        $upgraded = $xml -replace '<MultipleInstancesPolicy>[A-Za-z]+</MultipleInstancesPolicy>', '<MultipleInstancesPolicy>StopExisting</MultipleInstancesPolicy>'
        Register-ScheduledTask -TaskName $TaskName -Xml $upgraded `
            -User "$env:USERDOMAIN\$env:USERNAME" -Force | Out-Null
    }
} catch {
    Write-Output "  (kept Parallel; the StopExisting upgrade did not apply: $($_.Exception.Message))"
}

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

# Read the policy from the task XML, not from the cmdlet object.
#
# The cmdlet's enum has no StopExisting, so a task that actually holds it
# reads back as an empty value -- and on 2026-09-21 this script printed a
# blank policy followed by "a stuck run cannot block the runs behind it",
# asserting the very protection it had failed to read. The XML is the
# authoritative source and knows all four values.
$policy = ''
try {
    $policy = ([xml](Export-ScheduledTask -TaskName $TaskName)).Task.Settings.MultipleInstancesPolicy
} catch {
    $policy = ''
}

Write-Output ''
Write-Output "  Task           $TaskName"
Write-Output "  Runs           $launcher"
Write-Output "  State          $($task.State)"
Write-Output "  Repeats every  $repeat"
Write-Output "  Next run       $($info.NextRunTime)"
Write-Output "  Time limit     $($task.Settings.ExecutionTimeLimit)"
if (-not $policy) {
    # Unknown is not the same as fine. Saying nothing reassuring here is the
    # whole point: an unread value must never be reported as a good one.
    Write-Output '  If wedged      COULD NOT READ -- unverified'
    Write-Output ''
    Write-Output '  Check it by pasting THIS ONE LINE, on its own, into PowerShell:'
    Write-Output ''
    # Printed flush left and alone. Indented under a label, it reads as part
    # of a block, and pasting the block made PowerShell parse the label "If
    # wedged" as an if statement -- a parse error where a one-word answer was
    # wanted. A command someone is meant to run has to look like a command.
    Write-Output "([xml](Export-ScheduledTask -TaskName '$TaskName')).Task.Settings.MultipleInstancesPolicy"
    Write-Output ''
} elseif ($policy -eq 'IgnoreNew') {
    Write-Output "  If wedged      $policy"
    Write-Output '                 ^ BAD: a stuck run would block every run behind it.'
} else {
    Write-Output "  If wedged      $policy"
    Write-Output '                 a stuck run cannot block the runs behind it.'
}
Write-Output ''

if ($repeat -ne 'PT15M') {
    Write-Output '  WARNING: the repetition interval is not 15 minutes.'
    exit 1
}
if (-not $info.NextRunTime) {
    Write-Output '  WARNING: no next run time, so the schedule did not take.'
    exit 1
}
if ($policy -eq 'IgnoreNew') {
    Write-Output '  WARNING: the instance policy is the one that caused the outage.'
    exit 1
}
exit 0
